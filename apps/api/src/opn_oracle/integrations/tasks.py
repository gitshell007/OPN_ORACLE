"""Celery delivery for the durable Signal outbox."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import shared_task
from flask import current_app
from sqlalchemy import select, text

from opn_oracle.extensions import db
from opn_oracle.integrations.crypto import IntegrationKeyring
from opn_oracle.integrations.models import (
    IntegrationInboxEvent,
    IntegrationOutboxEvent,
    SignalSyncRun,
)
from opn_oracle.integrations.service import _ingest_item, adapter_for_connection
from opn_oracle.integrations.signal_avanza import (
    MonitorSpec,
    SignalItem,
    SignalTemporaryError,
)
from opn_oracle.integrations.webhooks import inbox_aad
from opn_oracle.oracle.models import SignalMonitor
from opn_oracle.platform.models import IntegrationConnection
from opn_oracle.tenants.context import TenantContext, tenant_context


@shared_task(
    bind=True,
    name="oracle.signal.dispatch_outbox",
    autoretry_for=(),
    acks_late=True,
    soft_time_limit=45,
    time_limit=60,
)
def dispatch_outbox(self: Any, *, event_id: str, tenant_id: str) -> dict[str, Any]:
    tenant_uuid = uuid.UUID(tenant_id)
    event_uuid = uuid.UUID(event_id)
    with tenant_context(TenantContext(tenant_id=tenant_uuid, actor_id=None)):
        event = db.session.scalar(
            select(IntegrationOutboxEvent)
            .where(
                IntegrationOutboxEvent.id == event_uuid,
                IntegrationOutboxEvent.tenant_id == tenant_uuid,
            )
            .with_for_update(skip_locked=True)
        )
        if event is None or event.status == "delivered":
            return {"status": "already_delivered"}
        now = datetime.now(UTC)
        if (
            event.status == "processing"
            and event.claimed_at is not None
            and event.claimed_at > now - timedelta(minutes=2)
        ):
            return {"status": "already_claimed"}
        if event.next_attempt_at and event.next_attempt_at > now:
            return {"status": "not_due"}
        event.status = "processing"
        event.attempts += 1
        event.claimed_at = now
        event.claimed_by = str(getattr(self.request, "id", "worker"))[:200]
        db.session.commit()
        connection = db.session.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.id == event.connection_id,
                IntegrationConnection.tenant_id == tenant_uuid,
                IntegrationConnection.status.in_(("active", "pending")),
            )
        )
        if connection is None:
            event.status = "failed"
            event.last_error = "connection_unavailable"
            db.session.commit()
            return {"status": "failed"}
        external_id = str(event.payload.get("external_id") or event.payload.get("monitor_id"))
        try:
            adapter = adapter_for_connection(connection)
            if event.event_type == "monitor.pause":
                adapter.pause_monitor(external_id, idempotency_key=event.idempotency_key)
            elif event.event_type == "monitor.resume":
                adapter.resume_monitor(external_id, idempotency_key=event.idempotency_key)
            elif event.event_type == "monitor.create":
                spec_payload = {
                    key: value
                    for key, value in event.payload.items()
                    if key in MonitorSpec.model_fields
                }
                created = adapter.create_monitor(
                    MonitorSpec.model_validate(spec_payload),
                    idempotency_key=event.idempotency_key,
                )
                if event.monitor_id:
                    monitor = db.session.get(SignalMonitor, event.monitor_id)
                    if monitor is not None:
                        monitor.external_id = created.id
            elif event.event_type == "monitor.update":
                spec_payload = {
                    key: value for key, value in event.payload.items() if key != "external_id"
                }
                adapter.update_monitor(
                    external_id,
                    MonitorSpec.model_validate(spec_payload),
                    idempotency_key=event.idempotency_key,
                )
            elif event.event_type == "connection.test":
                connection.last_health_at = datetime.now(UTC)
                if not adapter.health():
                    raise SignalTemporaryError("Signal respondió en estado degradado.")
                connection.last_success_at = datetime.now(UTC)
                connection.last_error = None
                connection.status = "active"
            else:
                raise ValueError("Tipo de evento outbox no soportado.")
        except SignalTemporaryError as exc:
            event = db.session.get(IntegrationOutboxEvent, event_uuid)
            assert event is not None
            event.last_error = "temporary_failure"
            if event.attempts >= event.max_attempts:
                event.status = "failed"
            else:
                event.status = "retrying"
                event.next_attempt_at = datetime.now(UTC) + timedelta(
                    seconds=min(300, 2**event.attempts)
                )
            event.claimed_at = None
            event.claimed_by = None
            db.session.commit()
            if event.status == "retrying":
                raise self.retry(exc=exc, countdown=min(300, 2**event.attempts)) from exc
            return {"status": "failed"}
        except Exception:
            event = db.session.get(IntegrationOutboxEvent, event_uuid)
            assert event is not None
            event.status = "failed"
            event.last_error = "permanent_failure"
            event.claimed_at = None
            event.claimed_by = None
            db.session.commit()
            raise
        event = db.session.get(IntegrationOutboxEvent, event_uuid)
        assert event is not None
        event.status = "delivered"
        event.delivered_at = datetime.now(UTC)
        event.last_error = None
        event.claimed_at = None
        event.claimed_by = None
        if event.monitor_id:
            monitor = db.session.scalar(
                select(SignalMonitor).where(
                    SignalMonitor.id == event.monitor_id,
                    SignalMonitor.tenant_id == tenant_uuid,
                )
            )
            if monitor is not None:
                monitor.observed_status = monitor.desired_status
                monitor.status = monitor.desired_status
                monitor.last_error = None
        db.session.commit()
        return {"status": "delivered", "event_id": str(event.id)}


@shared_task(name="maintenance.signal_reconcile_outbox")
def reconcile_outbox() -> dict[str, int]:
    if db.engine.dialect.name != "postgresql":
        return {"requeued": 0}
    rows = db.session.execute(text("SELECT tenant_id,event_id FROM oracle_signal_outbox_due(100)"))
    count = 0
    for row in rows:
        dispatch_outbox.apply_async(
            kwargs={"event_id": str(row.event_id), "tenant_id": str(row.tenant_id)},
            queue="signals",
        )
        count += 1
    db.session.rollback()
    return {"requeued": count}


@shared_task(name="maintenance.signal_reconcile_inbox")
def reconcile_inbox() -> dict[str, int]:
    if db.engine.dialect.name != "postgresql":
        return {"requeued": 0}
    rows = db.session.execute(text("SELECT tenant_id,inbox_id FROM oracle_signal_inbox_due(100)"))
    count = 0
    for row in rows:
        process_inbox.apply_async(
            kwargs={"inbox_id": str(row.inbox_id), "tenant_id": str(row.tenant_id)},
            queue="signals",
        )
        count += 1
    db.session.rollback()
    return {"requeued": count}


@shared_task(
    bind=True,
    name="oracle.signal.process_inbox",
    acks_late=True,
    soft_time_limit=45,
    time_limit=60,
)
def process_inbox(self: Any, *, inbox_id: str, tenant_id: str) -> dict[str, Any]:
    del self
    tenant_uuid, inbox_uuid = uuid.UUID(tenant_id), uuid.UUID(inbox_id)
    with tenant_context(TenantContext(tenant_id=tenant_uuid, actor_id=None)):
        inbox = db.session.scalar(
            select(IntegrationInboxEvent)
            .where(
                IntegrationInboxEvent.id == inbox_uuid,
                IntegrationInboxEvent.tenant_id == tenant_uuid,
            )
            .with_for_update()
        )
        if inbox is None or inbox.status == "processed":
            return {"status": "already_processed"}
        now = datetime.now(UTC)
        if (
            inbox.status == "validated"
            and inbox.updated_at is not None
            and inbox.updated_at > now - timedelta(minutes=2)
        ):
            return {"status": "already_claimed"}
        inbox.status = "validated"
        inbox.attempts += 1
        db.session.commit()
        try:
            keyring: IntegrationKeyring = current_app.extensions["integration_keyring"]
            raw = keyring.decrypt(
                inbox.raw_ciphertext,
                inbox.raw_nonce,
                inbox.key_version,
                aad=inbox_aad(tenant_uuid, inbox.connection_id, inbox.provider_event_id),
            )
            envelope = json.loads(raw)
            event_type = envelope.get("event_type")
            if event_type == "monitor.status_changed":
                monitor_data = envelope.get("data", {}).get("monitor", {})
                monitor = db.session.scalar(
                    select(SignalMonitor).where(
                        SignalMonitor.tenant_id == tenant_uuid,
                        SignalMonitor.connection_id == inbox.connection_id,
                        SignalMonitor.external_id == monitor_data.get("id"),
                    )
                )
                if monitor is None:
                    inbox.status = "rejected"
                    inbox.last_error = "monitor_not_found"
                    db.session.commit()
                    return {"status": "rejected"}
                observed = str(monitor_data.get("new_status", ""))
                if observed not in {"draft", "active", "paused", "disabled", "error"}:
                    inbox.status = "rejected"
                    inbox.last_error = "invalid_monitor_status"
                    db.session.commit()
                    return {"status": "rejected"}
                monitor.observed_status = observed
                monitor.last_error = None
                inbox.status = "processed"
                inbox.processed_at = datetime.now(UTC)
                inbox.last_error = None
                db.session.commit()
                return {"status": "processed", "monitor_status": observed}
            if event_type not in {"signal.created", "signal.updated"}:
                inbox.status = "rejected"
                inbox.last_error = "unsupported_event_type"
                db.session.commit()
                return {"status": "rejected"}
            signal_item = SignalItem.model_validate(envelope["data"]["signal"])
            monitor = db.session.scalar(
                select(SignalMonitor).where(
                    SignalMonitor.tenant_id == tenant_uuid,
                    SignalMonitor.connection_id == inbox.connection_id,
                    SignalMonitor.external_id == signal_item.monitor_id,
                )
            )
            if monitor is None:
                inbox.status = "rejected"
                inbox.last_error = "monitor_not_found"
                db.session.commit()
                return {"status": "rejected"}
            run = SignalSyncRun(
                tenant_id=tenant_uuid,
                monitor_id=monitor.id,
                status="running",
                cursor_before=monitor.cursor,
            )
            db.session.add(run)
            db.session.flush()
            _, changed = _ingest_item(monitor, run, signal_item, inbox_event_id=inbox.id)
            run.received = 1
            run.created = int(changed)
            run.duplicates = int(not changed)
            run.status = "succeeded"
            run.finished_at = datetime.now(UTC)
            inbox.status = "processed"
            inbox.processed_at = datetime.now(UTC)
            inbox.last_error = None
            db.session.commit()
            return {"status": "processed", "changed": changed}
        except Exception:
            db.session.rollback()
            inbox = db.session.get(IntegrationInboxEvent, inbox_uuid)
            if inbox is not None:
                inbox.status = "failed"
                inbox.last_error = "processing_failure"
                db.session.commit()
            raise
