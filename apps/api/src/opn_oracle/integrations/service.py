"""Transactional Signal orchestration, idempotency and normalized ingestion."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from flask import current_app
from sqlalchemy import or_, select, text
from sqlalchemy.exc import IntegrityError

from opn_oracle.extensions import db
from opn_oracle.integrations.crypto import IntegrationKeyring, credential_aad
from opn_oracle.integrations.models import (
    IntegrationOutboxEvent,
    SignalIngestionRecord,
    SignalSyncRun,
)
from opn_oracle.integrations.signal_avanza import (
    HttpSignalAvanzaAdapter,
    SignalAvanzaAdapter,
    SignalItem,
)
from opn_oracle.jobs.service import stage_job
from opn_oracle.oracle.actor_candidates import extract_signal_entities
from opn_oracle.oracle.models import DossierSignal, Signal, SignalMonitor, Watchlist
from opn_oracle.platform.models import ApiCredential, IntegrationConnection


class IdempotencyConflict(RuntimeError):
    pass


def adapter_for_connection(connection: IntegrationConnection) -> SignalAvanzaAdapter:
    if connection.adapter_mode == "mock":
        return cast(SignalAvanzaAdapter, current_app.extensions["signal_avanza_adapter"])
    tokens = active_secrets(connection, "api_token", limit=1)
    if not tokens:
        raise RuntimeError("La conexión Signal no tiene token activo.")
    allowed = frozenset(
        part.strip()
        for part in current_app.config["SIGNAL_AVANZA_ALLOWED_HOSTS"].split(",")
        if part.strip()
    )
    return HttpSignalAvanzaAdapter(
        base_url=connection.base_url or "",
        api_version=connection.api_version,
        token=tokens[0],
        external_tenant_id=str(connection.tenant_id),
        contract_confirmed=current_app.config["SIGNAL_AVANZA_CONTRACT_CONFIRMED"],
        connect_timeout=current_app.config["SIGNAL_CONNECT_TIMEOUT_SECONDS"],
        read_timeout=current_app.config["SIGNAL_READ_TIMEOUT_SECONDS"],
        allowed_hosts=allowed,
    )


def canonical_hash(value: Any) -> bytes:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).digest()


def outbox_request_hash(
    *,
    connection_id: uuid.UUID,
    monitor_id: uuid.UUID | None,
    event_type: str,
    payload: dict[str, Any],
) -> bytes:
    return canonical_hash(
        {
            "connection_id": str(connection_id),
            "monitor_id": str(monitor_id) if monitor_id else None,
            "event_type": event_type,
            "payload": payload,
        }
    )


def lock_idempotency_key(*, tenant_id: uuid.UUID, idempotency_key: str) -> None:
    """Serialize one tenant/key for the surrounding database transaction."""

    bind = db.session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    material = hashlib.sha256(f"{tenant_id}:{idempotency_key}".encode()).digest()
    lock_key = int.from_bytes(material[:8], "big", signed=True)
    db.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})


def store_credential(*, connection: IntegrationConnection, kind: str, secret: str) -> ApiCredential:
    keyring: IntegrationKeyring | None = current_app.extensions.get("integration_keyring")
    if keyring is None:
        raise RuntimeError("El keyring de integraciones no está configurado.")
    latest = db.session.scalar(
        select(ApiCredential)
        .where(
            ApiCredential.tenant_id == connection.tenant_id,
            ApiCredential.connection_id == connection.id,
            ApiCredential.credential_kind == kind,
        )
        .order_by(ApiCredential.credential_version.desc())
        .limit(1)
    )
    version = 1 if latest is None else latest.credential_version + 1
    encrypted = keyring.encrypt(
        secret,
        aad=credential_aad(
            tenant_id=str(connection.tenant_id),
            connection_id=str(connection.id),
            kind=kind,
            version=version,
        ),
    )
    now = datetime.now(UTC)
    if latest is not None and kind == "api_token":
        latest.is_active = False
        latest.retired_at = now
        latest.rotated_at = now
    elif latest is not None:
        latest.valid_until = now + timedelta(minutes=5)
        older = list(
            db.session.scalars(
                select(ApiCredential).where(
                    ApiCredential.tenant_id == connection.tenant_id,
                    ApiCredential.connection_id == connection.id,
                    ApiCredential.credential_kind == kind,
                    ApiCredential.is_active.is_(True),
                    ApiCredential.id != latest.id,
                )
            )
        )
        for item in older:
            item.is_active = False
            item.retired_at = now
    credential = ApiCredential(
        tenant_id=connection.tenant_id,
        connection_id=connection.id,
        credential_kind=kind,
        algorithm="AES-256-GCM",
        ciphertext=encrypted.ciphertext,
        nonce=encrypted.nonce,
        key_version=encrypted.key_version,
        credential_version=version,
        fingerprint=encrypted.fingerprint,
        is_active=True,
        valid_from=now,
        rotated_at=now if latest is not None else None,
    )
    db.session.add(credential)
    return credential


def active_secrets(connection: IntegrationConnection, kind: str, *, limit: int = 2) -> list[str]:
    keyring: IntegrationKeyring | None = current_app.extensions.get("integration_keyring")
    if keyring is None:
        return []
    credentials = db.session.scalars(
        select(ApiCredential)
        .where(
            ApiCredential.tenant_id == connection.tenant_id,
            ApiCredential.connection_id == connection.id,
            ApiCredential.credential_kind == kind,
            ApiCredential.is_active.is_(True),
            ApiCredential.valid_from <= datetime.now(UTC),
            or_(ApiCredential.valid_until.is_(None), ApiCredential.valid_until > datetime.now(UTC)),
            ApiCredential.retired_at.is_(None),
        )
        .order_by(ApiCredential.credential_version.desc())
        .limit(limit)
    )
    return [
        keyring.decrypt(
            item.ciphertext,
            item.nonce,
            item.key_version,
            aad=credential_aad(
                tenant_id=str(item.tenant_id),
                connection_id=str(item.connection_id),
                kind=item.credential_kind,
                version=item.credential_version,
            ),
        )
        for item in credentials
    ]


def stage_outbox(
    *,
    connection: IntegrationConnection,
    monitor: SignalMonitor | None,
    event_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
    correlation_id: str | None = None,
    intention_hash: bytes | None = None,
) -> IntegrationOutboxEvent:
    digest = outbox_request_hash(
        connection_id=connection.id,
        monitor_id=monitor.id if monitor else None,
        event_type=event_type,
        payload=payload,
    )
    existing = db.session.scalar(
        select(IntegrationOutboxEvent).where(
            IntegrationOutboxEvent.tenant_id == connection.tenant_id,
            IntegrationOutboxEvent.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != digest:
            raise IdempotencyConflict("La clave idempotente ya se usó con otro payload.")
        return existing
    event = IntegrationOutboxEvent(
        tenant_id=connection.tenant_id,
        connection_id=connection.id,
        monitor_id=monitor.id if monitor else None,
        event_type=event_type,
        payload=payload,
        idempotency_key=idempotency_key,
        request_hash=digest,
        intention_hash=intention_hash or digest,
        correlation_id=correlation_id,
    )
    try:
        with db.session.begin_nested():
            db.session.add(event)
            db.session.flush()
        return event
    except IntegrityError:
        concurrent = db.session.scalar(
            select(IntegrationOutboxEvent).where(
                IntegrationOutboxEvent.tenant_id == connection.tenant_id,
                IntegrationOutboxEvent.idempotency_key == idempotency_key,
            )
        )
        if concurrent is None or concurrent.request_hash != digest:
            raise IdempotencyConflict("Conflicto concurrente de idempotencia.") from None
        return concurrent


def _try_monitor_lock(monitor_id: uuid.UUID) -> bool:
    bind = db.session.get_bind()
    if bind.dialect.name != "postgresql":
        return True
    key = int.from_bytes(hashlib.sha256(monitor_id.bytes).digest()[:8], "big", signed=True)
    return bool(db.session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}))


def _link_and_stage_triage(
    monitor: SignalMonitor, signal: Signal, item: SignalItem, digest: bytes, *, force: bool
) -> None:
    watchlist = db.session.get(Watchlist, monitor.watchlist_id)
    if watchlist is None:
        return
    link = db.session.scalar(
        select(DossierSignal.id).where(
            DossierSignal.tenant_id == monitor.tenant_id,
            DossierSignal.dossier_id == watchlist.dossier_id,
            DossierSignal.signal_id == signal.id,
        )
    )
    new_link = link is None
    if new_link:
        db.session.add(
            DossierSignal(
                tenant_id=monitor.tenant_id,
                dossier_id=watchlist.dossier_id,
                signal_id=signal.id,
                relevance=50,
            )
        )
    if force or new_link:
        stage_job(
            "oracle.signal.triage",
            payload={"resource_id": str(signal.id), "dossier_id": str(watchlist.dossier_id)},
            idempotency_key=f"signal-triage:{monitor.id}:{item.id}:{digest.hex()[:16]}",
            dossier_id=watchlist.dossier_id,
            resource_type="signal",
            resource_id=signal.id,
        )


def _matches_monitor_language(monitor: SignalMonitor, item: SignalItem) -> bool:
    """Keep provider output inside the monitor's explicit language scope when known."""
    watchlist = db.session.get(Watchlist, monitor.watchlist_id)
    config = (
        watchlist.query_config if watchlist and isinstance(watchlist.query_config, dict) else {}
    )
    allowed = {str(value).strip().casefold() for value in config.get("languages", []) if value}
    detected = (item.language or "").strip().casefold()
    return not allowed or not detected or detected in allowed


def _ingest_item(
    monitor: SignalMonitor,
    run: SignalSyncRun,
    item: SignalItem,
    *,
    inbox_event_id: uuid.UUID | None = None,
) -> tuple[Signal, bool]:
    raw = item.model_dump(mode="json")
    digest = canonical_hash(raw)
    entities = item.entities or extract_signal_entities(
        [], raw_payload=raw, title=item.title, summary=item.summary or ""
    )
    ingestion = db.session.scalar(
        select(SignalIngestionRecord).where(
            SignalIngestionRecord.tenant_id == monitor.tenant_id,
            SignalIngestionRecord.monitor_id == monitor.id,
            SignalIngestionRecord.provider_signal_id == item.id,
        )
    )
    if ingestion is not None:
        signal = db.session.get(Signal, ingestion.signal_id) if ingestion.signal_id else None
        if signal is None:
            raise RuntimeError("Registro de ingesta sin señal asociada.")
        ingestion.occurrence_count += 1
        ingestion.last_seen_at = datetime.now(UTC)
        if ingestion.content_hash == digest:
            ingestion.status = "duplicate"
            return signal, False
        ingestion.content_hash = digest
        ingestion.status = "changed"
        signal.title = item.title
        signal.summary = item.summary or ""
        signal.source_url = str(item.source.url) if item.source.url else None
        signal.published_at = item.source.published_at
        signal.language = item.language
        signal.tags = item.tags
        signal.entities = entities
        signal.categories = item.categories
        signal.raw_hash = digest
        signal.raw_payload = raw
        _link_and_stage_triage(monitor, signal, item, digest, force=True)
        return signal, True
    existing = db.session.scalar(
        select(Signal).where(
            Signal.tenant_id == monitor.tenant_id,
            Signal.provider_connection_id == monitor.connection_id,
            Signal.external_id == item.id,
        )
    )
    created = existing is None
    signal = existing or Signal(
        tenant_id=monitor.tenant_id,
        provider=monitor.provider,
        provider_connection_id=monitor.connection_id,
        external_id=item.id,
        title=item.title,
        summary=item.summary or "",
        source_type=item.type,
        source_name=item.source.name,
        source_url=str(item.source.url) if item.source.url else None,
        published_at=item.source.published_at,
        language=item.language,
        tags=item.tags,
        entities=entities,
        categories=item.categories,
        raw_hash=digest,
        credibility=int(item.source.credibility_score or 50),
        raw_payload=raw,
    )
    if created:
        db.session.add(signal)
        db.session.flush()
    record = SignalIngestionRecord(
        tenant_id=monitor.tenant_id,
        monitor_id=monitor.id,
        sync_run_id=run.id,
        signal_id=signal.id,
        inbox_event_id=inbox_event_id,
        provider_signal_id=item.id,
        content_hash=digest,
        status="created" if created else "duplicate",
    )
    db.session.add(record)
    _link_and_stage_triage(monitor, signal, item, digest, force=created)
    return signal, created


def sync_monitor(monitor: SignalMonitor, *, job_id: uuid.UUID | None = None) -> dict[str, Any]:
    if monitor.desired_status != "active" or monitor.observed_status == "paused":
        raise RuntimeError("El monitor está pausado o pendiente de reconciliación.")
    if not _try_monitor_lock(monitor.id):
        raise RuntimeError("Ya existe una sincronización activa para el monitor.")
    run = SignalSyncRun(
        tenant_id=monitor.tenant_id,
        monitor_id=monitor.id,
        job_id=job_id,
        cursor_before=monitor.cursor,
        status="running",
    )
    db.session.add(run)
    db.session.flush()
    if monitor.connection_id is None:
        adapter = cast(SignalAvanzaAdapter, current_app.extensions["signal_avanza_adapter"])
    else:
        connection = db.session.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.id == monitor.connection_id,
                IntegrationConnection.tenant_id == monitor.tenant_id,
                IntegrationConnection.status == "active",
            )
        )
        if connection is None:
            raise RuntimeError("Monitor sin conexión Signal activa.")
        adapter = adapter_for_connection(connection)
    created = 0
    duplicates = 0
    cursor = monitor.cursor
    received = 0
    for _ in range(current_app.config["SIGNAL_SYNC_MAX_PAGES"]):
        page = adapter.sync_signals(monitor.external_id or str(monitor.id), cursor=cursor)
        for item in page.items:
            if not _matches_monitor_language(monitor, item):
                continue
            _, was_created = _ingest_item(monitor, run, item)
            created += int(was_created)
            duplicates += int(not was_created)
        received += len(page.items)
        cursor = page.next_cursor or cursor
        if not page.has_more:
            break
        if not page.next_cursor:
            raise RuntimeError("Signal indicó más páginas sin cursor siguiente.")
    else:
        raise RuntimeError("La sincronización alcanzó el límite de páginas configurado.")
    monitor.cursor = cursor
    monitor.last_synced_at = datetime.now(UTC)
    monitor.last_sync_attempt_at = monitor.last_synced_at
    monitor.last_error = None
    monitor.observed_status = "active"
    run.cursor_after = monitor.cursor
    run.received = received
    run.created = created
    run.duplicates = duplicates
    run.status = "succeeded"
    run.finished_at = datetime.now(UTC)
    return {
        "kind": "signal_sync",
        "monitor_id": str(monitor.id),
        "received": run.received,
        "created": created,
        "duplicates": duplicates,
        "next_cursor": monitor.cursor,
    }
