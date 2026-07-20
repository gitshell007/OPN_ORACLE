from __future__ import annotations

import base64
import hashlib
import hmac
import inspect
import json
import os
import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from datetime import time as dt_time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from celery.contrib.testing.worker import start_worker
from celery.exceptions import Retry
from flask import g
from flask_login import login_user
from flask_migrate import downgrade, upgrade
from redis import Redis
from sqlalchemy import create_engine, delete, func, select, text

from opn_oracle import create_app
from opn_oracle.ai import routes as ai_routes
from opn_oracle.ai.models import AIArtifact, AIAttempt, AITenantPolicy, AIUsageLedger
from opn_oracle.ai.provider import AIUnavailable, LLMResult, MockLLMProvider
from opn_oracle.ai.schemas import ReportOutput
from opn_oracle.ai.service import (
    AIPolicyDenied,
    EvidenceReviewError,
    execute_agent,
    recover_stale_ai_executions,
)
from opn_oracle.auth.tokens import hash_token, stable_invitation_token
from opn_oracle.extensions import db
from opn_oracle.integrations import routes as signal_routes
from opn_oracle.integrations.crypto import IntegrationKeyring
from opn_oracle.integrations.models import (
    IntegrationInboxEvent,
    IntegrationOutboxEvent,
    SignalIngestionRecord,
    SignalMonitorConfigVersion,
)
from opn_oracle.integrations.service import (
    IdempotencyConflict,
    active_secrets,
    canonical_hash,
    stage_outbox,
    store_credential,
    sync_monitor,
)
from opn_oracle.integrations.signal_avanza import (
    ProvenanceItem,
    SignalContractError,
    SignalItem,
    SignalPage,
    SignalTemporaryError,
    SourceItem,
)
from opn_oracle.integrations.tasks import (
    dispatch_outbox,
    process_inbox,
    reconcile_inbox,
    reconcile_outbox,
)
from opn_oracle.integrations.webhooks import inbox_aad
from opn_oracle.jobs import tasks as job_tasks
from opn_oracle.jobs.service import enqueue_job, publish_job, stage_job
from opn_oracle.jobs.tasks import execute_durable
from opn_oracle.oracle.jobs import AIAuditLog, BackgroundJob, JobSchedule
from opn_oracle.oracle.models import (
    DossierSignal,
    Signal,
    SignalMonitor,
    StrategicDossier,
    Watchlist,
)
from opn_oracle.platform.models import (
    IntegrationConnection,
    Invitation,
    PasswordResetToken,
    Tenant,
    TenantMembership,
    User,
    Workspace,
)
from opn_oracle.tenants.context import TenantContext, tenant_context

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def jobs_stack() -> Iterator[tuple[Any, dict[str, uuid.UUID]]]:
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1")
    migration_url = os.environ["TEST_DATABASE_URL"]
    runtime_url = os.environ["TEST_RUNTIME_DATABASE_URL"]
    redis_url = os.environ["TEST_REDIS_URL"]
    redis = Redis.from_url(redis_url)
    redis.flushdb()
    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "jobs-integration-secret-key-at-least-32",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
            "SESSION_REDIS_URL": redis_url,
            "RATELIMIT_STORAGE_URL": redis_url,
            "CELERY_BROKER_URL": redis_url,
            "CELERY_RESULT_BACKEND": redis_url,
            "CELERY_TASK_ALWAYS_EAGER": False,
            "CELERY_TASK_EAGER_PROPAGATES": False,
            "AI_ENABLED": True,
            "AI_MODE": "mock",
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        downgrade(directory=migrations, revision="base")
        upgrade(directory=migrations)
    ids = {name: uuid.uuid4() for name in ("tenant", "user", "membership", "workspace")}
    migrator = create_engine(migration_url)
    with migrator.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tenants"
                "(id,slug,name,status,locale,timezone,settings,created_at,updated_at) "
                "VALUES (:t,'jobs','Jobs','active','es-ES','UTC','{}',now(),now())"
            ),
            {"t": ids["tenant"]},
        )
        connection.execute(
            text(
                "INSERT INTO users"
                "(id,email,display_name,status,email_verified_at,created_at,updated_at) "
                "VALUES (:u,'jobs@example.test','Jobs User','active',now(),now(),now())"
            ),
            {"u": ids["user"]},
        )
        connection.execute(
            text(
                "INSERT INTO tenant_memberships"
                "(id,tenant_id,user_id,status,accepted_at,settings,created_at,updated_at) "
                "VALUES (:m,:t,:u,'active',now(),'{}',now(),now())"
            ),
            {"m": ids["membership"], "t": ids["tenant"], "u": ids["user"]},
        )
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        workspace = Workspace(
            id=ids["workspace"],
            tenant_id=ids["tenant"],
            slug="principal",
            name="Principal",
            status="active",
            is_default=True,
        )
        dossier = StrategicDossier(
            tenant_id=ids["tenant"],
            workspace_id=workspace.id,
            title="Signal Job",
            owner_user_id=ids["user"],
        )
        db.session.add(workspace)
        db.session.flush()
        db.session.add(dossier)
        db.session.flush()
        watchlist = Watchlist(
            tenant_id=ids["tenant"], dossier_id=dossier.id, name="Radar", status="active"
        )
        db.session.add(watchlist)
        db.session.flush()
        monitor = SignalMonitor(
            tenant_id=ids["tenant"],
            watchlist_id=watchlist.id,
            provider="signal-avanza-mock",
            external_id="mock-monitor-1",
            status="active",
        )
        db.session.add(monitor)
        db.session.add(
            AITenantPolicy(
                tenant_id=ids["tenant"],
                enabled=True,
                provider="mock",
                allowed_models=["mock-oracle-v1"],
                max_classification="internal",
                daily_call_limit=20,
                max_concurrency=2,
                kill_switch=False,
            )
        )
        db.session.commit()
        ids["monitor"] = monitor.id
        ids["dossier"] = dossier.id
    celery = app.extensions["celery"]
    with start_worker(
        celery,
        pool="solo",
        concurrency=1,
        perform_ping_check=False,
        queues=("signals", "notifications", "maintenance", "ai"),
        loglevel="WARNING",
    ):
        yield app, ids
    redis.flushdb()
    migrator.dispose()
    with app.app_context():
        downgrade(directory=migrations, revision="base")


def _wait_job(app: Any, ids: dict[str, uuid.UUID], job_id: uuid.UUID, status: str) -> BackgroundJob:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with (
            app.app_context(),
            tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
        ):
            job = db.session.get(BackgroundJob, job_id)
            if job is not None and job.status == status:
                db.session.expunge(job)
                return job
            if job is not None and job.status == "failed" and status != "failed":
                raise AssertionError(f"job {job_id} falló: {job.error_code} {job.error_message}")
            db.session.remove()
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} no alcanzó {status}")


def test_real_worker_routing_result_and_idempotency(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
) -> None:
    app, ids = jobs_stack
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        signal = Signal(
            tenant_id=ids["tenant"],
            provider="signal-avanza-mock",
            external_id="triage-worker-signal",
            title="Nueva licitación de baterías",
            summary="Se publica una convocatoria para almacenamiento energético.",
            source_type="official_publication",
            source_name="BOE",
            source_url="https://example.test/triage-worker-signal",
            raw_hash=hashlib.sha256(b"triage-worker-signal").digest(),
            credibility=80,
        )
        db.session.add(signal)
        db.session.flush()
        db.session.add(
            DossierSignal(
                tenant_id=ids["tenant"],
                dossier_id=ids["dossier"],
                signal_id=signal.id,
            )
        )
        db.session.commit()
        first = enqueue_job(
            "oracle.signal.triage",
            payload={"resource_id": str(signal.id), "dossier_id": str(ids["dossier"])},
            idempotency_key="worker-real-idempotency",
            requested_by_user_id=ids["user"],
        )
        job_id = first.id
    finished = _wait_job(app, ids, job_id, "succeeded")
    assert finished.queue == "signals"
    assert finished.attempts == 1
    assert finished.result_ref["applied"] is True
    assert finished.result_ref["overall_score"] > 0
    duplicate = (
        app.extensions["celery"]
        .tasks["oracle.signal.triage"]
        .apply(
            kwargs={
                "job_id": str(job_id),
                "tenant_id": str(ids["tenant"]),
                "payload": finished.input_payload,
            },
            task_id=finished.celery_task_id,
            throw=True,
        )
    )
    assert duplicate.get()["applied"] is True
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        repeated = enqueue_job(
            "oracle.signal.triage",
            payload=finished.input_payload,
            idempotency_key="worker-real-idempotency",
            requested_by_user_id=ids["user"],
        )
        assert repeated.id == job_id and repeated.attempts == 1


def test_signal_sync_job_uses_replaceable_mock_and_persists_cursor(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
) -> None:
    app, ids = jobs_stack
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        job = enqueue_job(
            "oracle.signal.sync_monitor",
            payload={"monitor_id": str(ids["monitor"])},
            idempotency_key="mock-signal-sync-functional",
            requested_by_user_id=ids["user"],
            resource_type="signal_monitor",
            resource_id=ids["monitor"],
        )
        job_id = job.id
    finished = _wait_job(app, ids, job_id, "succeeded")
    assert finished.result_ref["received"] == 2
    assert finished.result_ref["created"] == 2
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        monitor = db.session.get(SignalMonitor, ids["monitor"])
        assert monitor is not None
        assert monitor.cursor == finished.result_ref["next_cursor"]
        assert monitor.last_synced_at is not None


class _PageAdapter:
    def __init__(self, pages: list[SignalPage]) -> None:
        self.pages = pages
        self.calls = 0

    def sync_signals(self, monitor_id: str, *, cursor: str | None) -> SignalPage:
        del monitor_id, cursor
        page = self.pages[min(self.calls, len(self.pages) - 1)]
        self.calls += 1
        return page


def _signal_item(
    item_id: str,
    *,
    title: str = "CATL defiende su fábrica de baterías en España",
    url: str | None = "https://example.test/noticia?utm_source=feed",
    source_name: str = "Medio",
    summary: str = "Resumen inicial",
) -> SignalItem:
    return SignalItem(
        id=item_id,
        monitor_id="mock-monitor-1",
        type="news",
        title=title,
        summary=summary,
        source=SourceItem(name=source_name, url=url, published_at=datetime.now(UTC)),
        language="es",
        tags=[],
        entities=[],
        categories=[],
        content_hash=hashlib.sha256(f"{item_id}:{summary}".encode()).hexdigest(),
        observed_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        provenance=ProvenanceItem(connector="test", monitor_config_version=1),
    )


def test_signal_ingest_reuses_canonical_url_and_title_source_dedupe(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
) -> None:
    app, ids = jobs_stack
    same_url = SignalPage(
        items=[
            _signal_item("url-a", url="https://Example.test/noticia/?utm_source=feed#frag"),
            _signal_item("url-b", url="https://example.test/noticia"),
            _signal_item("url-c", url="https://example.test/otra"),
        ],
        has_more=False,
        next_cursor="url-page",
    )
    same_title = SignalPage(
        items=[
            _signal_item(
                "title-a", title="  Aviso industrial relevante  ", url=None, source_name="BOE"
            ),
            _signal_item(
                "title-b", title="aviso   industrial RELEVANTE", url=None, source_name="BOE"
            ),
            _signal_item(
                "title-c", title="aviso industrial relevante", url=None, source_name="Otro"
            ),
        ],
        has_more=False,
        next_cursor="title-page",
    )
    changed_url = SignalPage(
        items=[
            _signal_item(
                "url-d",
                url="https://example.test/noticia?utm_campaign=otra",
                summary="Resumen actualizado",
            )
        ],
        has_more=False,
        next_cursor="changed-page",
    )
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        original_adapter = app.extensions.get("signal_avanza_adapter")
        monitor = db.session.get(SignalMonitor, ids["monitor"])
        assert monitor is not None
        provider_ids = {"url-a", "url-b", "url-c", "title-a", "title-b", "title-c", "url-d"}
        try:
            app.extensions["signal_avanza_adapter"] = _PageAdapter(
                [same_url, same_title, changed_url]
            )
            result_url = sync_monitor(monitor)
            assert result_url["created"] == 2
            assert result_url["duplicates"] == 1
            url_signals = db.session.scalars(
                select(Signal).where(Signal.external_id.in_(["url-a", "url-c"]))
            ).all()
            assert len(url_signals) == 2
            assert (
                db.session.scalar(
                    select(func.count(DossierSignal.id)).where(
                        DossierSignal.signal_id.in_([signal.id for signal in url_signals])
                    )
                )
                == 2
            )
            assert (
                db.session.scalar(
                    select(func.count(SignalIngestionRecord.id)).where(
                        SignalIngestionRecord.provider_signal_id.in_(["url-a", "url-b", "url-c"])
                    )
                )
                == 3
            )
            reused = db.session.scalar(select(Signal).where(Signal.external_id == "url-a"))
            assert reused is not None
            assert reused.canonical_source_url == "https://example.test/noticia"
            assert reused.dedupe_key == "url:https://example.test/noticia"

            result_title = sync_monitor(monitor)
            assert result_title["created"] == 2
            assert result_title["duplicates"] == 1
            scoped_signals = db.session.scalars(
                select(Signal).where(
                    Signal.external_id.in_(["url-a", "url-c", "title-a", "title-c"])
                )
            ).all()
            assert len(scoped_signals) == 4
            assert (
                db.session.scalar(
                    select(func.count(DossierSignal.id)).where(
                        DossierSignal.signal_id.in_([signal.id for signal in scoped_signals])
                    )
                )
                == 4
            )

            result_changed = sync_monitor(monitor)
            assert result_changed["created"] == 0
            assert result_changed["duplicates"] == 1
            assert (
                db.session.scalar(
                    select(func.count(Signal.id)).where(
                        Signal.external_id.in_(["url-a", "url-c", "title-a", "title-c"])
                    )
                )
                == 4
            )
            db.session.refresh(reused)
            assert reused.summary == "Resumen actualizado"
            changed_record = db.session.scalar(
                select(SignalIngestionRecord).where(
                    SignalIngestionRecord.provider_signal_id == "url-d"
                )
            )
            assert changed_record is not None
            assert changed_record.status == "changed"
        finally:
            if original_adapter is not None:
                app.extensions["signal_avanza_adapter"] = original_adapter
            db.session.execute(
                delete(BackgroundJob).where(
                    BackgroundJob.tenant_id == ids["tenant"],
                    BackgroundJob.idempotency_key.like(f"signal-triage:{monitor.id}:%"),
                )
            )
            db.session.execute(
                delete(SignalIngestionRecord).where(
                    SignalIngestionRecord.tenant_id == ids["tenant"],
                    SignalIngestionRecord.provider_signal_id.in_(provider_ids),
                )
            )
            signal_ids = select(Signal.id).where(
                Signal.tenant_id == ids["tenant"],
                Signal.external_id.in_(["url-a", "url-c", "title-a", "title-c"]),
            )
            db.session.execute(
                delete(DossierSignal).where(
                    DossierSignal.tenant_id == ids["tenant"],
                    DossierSignal.signal_id.in_(signal_ids),
                )
            )
            db.session.execute(
                delete(Signal).where(
                    Signal.tenant_id == ids["tenant"],
                    Signal.external_id.in_(["url-a", "url-c", "title-a", "title-c"]),
                )
            )
            db.session.commit()


def test_signal_connection_outbox_webhook_replay_and_polling_dedupe(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
) -> None:
    app, ids = jobs_stack
    keyring = IntegrationKeyring(
        f"1:{base64.b64encode(b'phase08-integration-key-material!'[:32]).decode()}", 1
    )
    app.extensions["integration_keyring"] = keyring
    app.config["SIGNAL_WEBHOOK_TOLERANCE_SECONDS"] = 300
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        connection = IntegrationConnection(
            tenant_id=ids["tenant"],
            provider="signal-avanza",
            name="phase08",
            status="active",
            adapter_mode="mock",
            api_version="v1",
            subscription_key="phase08-subscription-key",
        )
        db.session.add(connection)
        db.session.flush()
        store_credential(
            connection=connection, kind="webhook_secret", secret="webhook-secret-phase08"
        )
        monitor = db.session.get(SignalMonitor, ids["monitor"])
        assert monitor is not None
        monitor.connection_id = connection.id
        monitor.provider = "signal-avanza"
        monitor.observed_status = "active"
        monitor.desired_status = "active"
        result = sync_monitor(monitor)
        assert result["created"] == 2
        pause = stage_outbox(
            connection=connection,
            monitor=monitor,
            event_type="monitor.pause",
            payload={"monitor_id": str(monitor.id), "external_id": monitor.external_id},
            idempotency_key="phase08-pause-idempotency",
        )
        db.session.commit()
        connection_id, pause_id = connection.id, pause.id
    delivered = dispatch_outbox.apply(
        kwargs={"event_id": str(pause_id), "tenant_id": str(ids["tenant"])}, throw=True
    ).get()
    assert delivered["status"] == "delivered"
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        monitor = db.session.get(SignalMonitor, ids["monitor"])
        event = db.session.get(IntegrationOutboxEvent, pause_id)
        assert monitor is not None and monitor.observed_status == "active"
        assert event is not None and event.status == "delivered"

    status_envelope = {
        "event_id": "event-phase08-monitor-status",
        "event_type": "monitor.status_changed",
        "data": {
            "monitor": {
                "id": "mock-monitor-1",
                "new_status": "draft",
            }
        },
    }
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        connection = db.session.get(IntegrationConnection, connection_id)
        monitor = db.session.get(SignalMonitor, ids["monitor"])
        assert connection is not None and monitor is not None
        monitor.external_id = "mock-monitor-1"
        encrypted = keyring.encrypt(
            json.dumps(status_envelope),
            aad=inbox_aad(ids["tenant"], connection_id, status_envelope["event_id"]),
        )
        status_inbox = IntegrationInboxEvent(
            tenant_id=ids["tenant"],
            connection_id=connection_id,
            provider_event_id=status_envelope["event_id"],
            event_type=status_envelope["event_type"],
            status="received",
            raw_ciphertext=encrypted.ciphertext,
            raw_nonce=encrypted.nonce,
            key_version=encrypted.key_version,
            raw_hash=hashlib.sha256(json.dumps(status_envelope).encode()).digest(),
        )
        db.session.add(status_inbox)
        db.session.commit()
        status_inbox_id = status_inbox.id
    status_result = process_inbox.apply(
        kwargs={"inbox_id": str(status_inbox_id), "tenant_id": str(ids["tenant"])},
        throw=True,
    ).get()
    assert status_result == {"status": "processed", "monitor_status": "pending"}

    now = datetime.now(UTC)
    signal_id = "webhook-signal-phase08"
    envelope = {
        "event_id": "event-phase08-1",
        "event_type": "signal.created",
        "api_version": "2026-07-01",
        "occurred_at": now.isoformat(),
        "delivery_attempt": 1,
        "monitor_id": "mock-monitor-1",
        "data": {
            "signal": {
                "id": signal_id,
                "monitor_id": "mock-monitor-1",
                "type": "official_publication",
                "title": "Convocatoria sintética",
                "summary": "Resumen sin HTML.",
                "source": {
                    "name": "Fuente",
                    "published_at": now.isoformat(),
                    "credibility_score": 75,
                },
                "language": "es",
                "entities": [],
                "tags": [],
                "categories": [],
                "content_hash": "sha256:phase08",
                "observed_at": now.isoformat(),
                "created_at": now.isoformat(),
                "provenance": {"connector": "fixture", "monitor_config_version": 1},
            }
        },
    }
    raw = json.dumps(envelope, separators=(",", ":")).encode()
    timestamp = str(int(now.timestamp()))
    signature = hmac.new(
        b"webhook-secret-phase08", timestamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Opn-Signal-Timestamp": timestamp,
        "X-Opn-Signal-Signature-V2": signature,
    }
    client = app.test_client()
    response = client.post(
        "/api/v1/integrations/signal-avanza/webhooks/v1/phase08-subscription-key",
        data=raw,
        headers=headers,
    )
    assert response.status_code == 202
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        inbox_id = db.session.scalar(
            select(IntegrationInboxEvent.id).where(
                IntegrationInboxEvent.connection_id == connection_id,
                IntegrationInboxEvent.provider_event_id == "event-phase08-1",
            )
        )
        assert inbox_id is not None
    process_result = process_inbox.apply(
        kwargs={"inbox_id": str(inbox_id), "tenant_id": str(ids["tenant"])}, throw=True
    ).get()
    assert process_result["status"] in {"processed", "already_processed", "already_claimed"}
    duplicate = client.post(
        "/api/v1/integrations/signal-avanza/webhooks/v1/phase08-subscription-key",
        data=raw,
        headers=headers,
    )
    assert duplicate.status_code == 202 and duplicate.json["duplicate"] is True
    assert (
        client.post(
            "/api/v1/integrations/signal-avanza/webhooks/v1/phase08-subscription-key",
            data=b"{}",
            headers={"Content-Type": "text/plain"},
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/api/v1/integrations/signal-avanza/webhooks/v1/missing-subscription",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/integrations/signal-avanza/webhooks/v1/phase08-subscription-key",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        ).status_code
        == 400
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with (
            app.app_context(),
            tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
        ):
            inbox = db.session.scalar(
                select(IntegrationInboxEvent).where(
                    IntegrationInboxEvent.connection_id == connection_id,
                    IntegrationInboxEvent.provider_event_id == "event-phase08-1",
                )
            )
            if inbox is not None and inbox.status == "processed":
                break
            db.session.remove()
        time.sleep(0.1)
    else:
        raise AssertionError("Webhook inbox no fue procesado.")
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        db.session.execute(
            delete(BackgroundJob).where(
                BackgroundJob.tenant_id == ids["tenant"],
                BackgroundJob.idempotency_key.like("signal-triage:%"),
            )
        )
        db.session.commit()
    with app.app_context():
        assert reconcile_outbox.run()["requeued"] >= 0
        assert reconcile_inbox.run()["requeued"] >= 0


def test_signal_route_bodies_cover_connection_and_monitor_contract(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
) -> None:
    app, ids = jobs_stack
    app.extensions["integration_keyring"] = IntegrationKeyring(
        f"1:{base64.b64encode(b'route-integration-key-material-32'[:32]).decode()}", 1
    )

    def invoke(function: Any, *args: Any) -> Any:
        return inspect.unwrap(function)(*args)

    with (
        app.test_request_context(
            "/",
            method="POST",
            json={
                "name": "routes",
                "adapter_mode": "mock",
                "webhook_secret": "route-webhook-secret-123",
            },
        ),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        user = db.session.get(User, ids["user"])
        assert user is not None
        login_user(user)
        g.active_tenant_id = ids["tenant"]
        response, status = invoke(signal_routes.create_connection)
        assert status == 201
        connection_id = uuid.UUID(response.get_json()["id"])
    with (
        app.test_request_context(
            "/",
            method="POST",
            json={
                "connection_id": str(connection_id),
                "query": "convocatorias",
                "name": "Radar",
                "keywords": ["baterías", "CATL"],
                "entities": [{"type": "company", "name": "BYD"}],
                "languages": ["ES"],
                "geographies": ["es"],
                "source_types": ["news", "company_signal"],
                "cadence": "weekly",
                "retention_days": 30,
            },
            headers={"Idempotency-Key": "route-monitor-create-v1"},
        ),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        user = db.session.get(User, ids["user"])
        assert user is not None
        login_user(user)
        g.active_tenant_id = ids["tenant"]
        original = db.session.get(SignalMonitor, ids["monitor"])
        assert original is not None
        watchlist = db.session.get(Watchlist, original.watchlist_id)
        assert watchlist is not None
        dossier_id = watchlist.dossier_id
        response, status = invoke(signal_routes.create_dossier_monitor, dossier_id)
        assert status == 202
        monitor_id = uuid.UUID(response.get_json()["id"])
        create_event_id = response.get_json()["outbox_event_id"]
        snapshot = db.session.scalar(
            select(SignalMonitorConfigVersion.snapshot).where(
                SignalMonitorConfigVersion.tenant_id == ids["tenant"],
                SignalMonitorConfigVersion.monitor_id == monitor_id,
                SignalMonitorConfigVersion.version == 1,
            )
        )
        assert snapshot is not None
        assert snapshot["keywords"] == ["baterías", "CATL"]
        assert snapshot["entities"] == [{"type": "company", "name": "BYD"}]
        assert snapshot["languages"] == ["es"]
        assert snapshot["geographies"] == ["ES"]
        assert snapshot["source_types"] == ["news", "company_signal"]
        assert snapshot["retention_days"] == 30
        replay, replay_status = invoke(signal_routes.create_dossier_monitor, dossier_id)
        assert replay_status == 202 and replay.get_json()["duplicate"] is True
    with (
        app.test_request_context(
            "/",
            method="POST",
            json={"connection_id": str(connection_id), "query": "different", "name": "Radar"},
            headers={"Idempotency-Key": "route-monitor-create-v1"},
        ),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        user = db.session.get(User, ids["user"])
        assert user is not None
        login_user(user)
        g.active_tenant_id = ids["tenant"]
        _, conflict_status, _ = invoke(signal_routes.create_dossier_monitor, dossier_id)
        assert conflict_status == 409
    dispatch_outbox.apply(
        kwargs={"event_id": create_event_id, "tenant_id": str(ids["tenant"])}, throw=True
    ).get()
    with (
        app.test_request_context("/", method="GET"),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        user = db.session.get(User, ids["user"])
        assert user is not None
        login_user(user)
        g.active_tenant_id = ids["tenant"]
        assert invoke(signal_routes.list_connections).status_code == 200
        assert invoke(signal_routes.list_dossier_monitors, dossier_id).status_code == 200
        assert invoke(signal_routes.monitor_health, monitor_id).status_code == 200
    with (
        app.test_request_context(
            "/",
            method="POST",
            json={"connection_id": str(connection_id)},
            headers={"Idempotency-Key": "route-connection-test-v1"},
        ),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        user = db.session.get(User, ids["user"])
        assert user is not None
        login_user(user)
        g.active_tenant_id = ids["tenant"]
        response, status = invoke(signal_routes.test_connection)
        assert status == 202
        test_event_id = response.get_json()["outbox_event_id"]
        _, status = invoke(signal_routes.reconcile_connection, connection_id)
        assert status == 202
    dispatch_outbox.apply(
        kwargs={"event_id": test_event_id, "tenant_id": str(ids["tenant"])}, throw=True
    ).get()
    with (
        app.test_request_context(
            "/",
            method="PATCH",
            json={
                "query": "convocatorias europeas",
                "languages": ["es", "pt"],
                "retention_days": 90,
            },
            headers={
                "Idempotency-Key": "route-monitor-update-v2",
                "If-Match": 'W/"1"',
            },
        ),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        user = db.session.get(User, ids["user"])
        assert user is not None
        login_user(user)
        g.active_tenant_id = ids["tenant"]
        response, status = invoke(signal_routes.update_monitor, monitor_id)
        assert status == 202
        update_event_id = response.get_json()["outbox_event_id"]
        snapshot = db.session.scalar(
            select(SignalMonitorConfigVersion.snapshot).where(
                SignalMonitorConfigVersion.tenant_id == ids["tenant"],
                SignalMonitorConfigVersion.monitor_id == monitor_id,
                SignalMonitorConfigVersion.version == 2,
            )
        )
        assert snapshot is not None
        assert snapshot["keywords"] == ["baterías", "CATL"]
        assert snapshot["entities"] == [{"type": "company", "name": "BYD"}]
        assert snapshot["languages"] == ["es", "pt"]
        assert snapshot["geographies"] == ["ES"]
        assert snapshot["source_types"] == ["news", "company_signal"]
        assert snapshot["retention_days"] == 90
        replay, replay_status = invoke(signal_routes.update_monitor, monitor_id)
        assert replay_status == 202 and replay.get_json()["duplicate"] is True
    with (
        app.test_request_context(
            "/",
            method="PATCH",
            json={"query": "cambio concurrente obsoleto"},
            headers={
                "Idempotency-Key": "route-monitor-update-stale-v1",
                "If-Match": 'W/"1"',
            },
        ),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        user = db.session.get(User, ids["user"])
        assert user is not None
        login_user(user)
        g.active_tenant_id = ids["tenant"]
        _, stale_status, _ = invoke(signal_routes.update_monitor, monitor_id)
        assert stale_status == 409
    dispatch_outbox.apply(
        kwargs={"event_id": update_event_id, "tenant_id": str(ids["tenant"])}, throw=True
    ).get()
    with (
        app.test_request_context(
            "/",
            method="POST",
            headers={"Idempotency-Key": "route-monitor-pause-v1"},
        ),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        user = db.session.get(User, ids["user"])
        assert user is not None
        login_user(user)
        g.active_tenant_id = ids["tenant"]
        response, status = invoke(signal_routes.monitor_action, monitor_id, "pause")
        assert status == 202
        pause_event_id = response.get_json()["outbox_event_id"]
    dispatch_outbox.apply(
        kwargs={"event_id": pause_event_id, "tenant_id": str(ids["tenant"])}, throw=True
    ).get()
    with (
        app.test_request_context(
            "/",
            method="POST",
            json={"kind": "webhook_secret", "secret": "rotated-route-secret-123"},
        ),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        user = db.session.get(User, ids["user"])
        assert user is not None
        login_user(user)
        g.active_tenant_id = ids["tenant"]
        assert invoke(signal_routes.rotate_connection, connection_id).status_code == 200
        assert invoke(signal_routes.disable_connection, connection_id).status_code == 200


def test_concurrent_monitor_create_reserves_one_idempotent_intention(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
) -> None:
    app, ids = jobs_stack
    name = f"Concurrent {uuid.uuid4().hex[:8]}"
    idempotency_key = f"monitor-concurrent-{uuid.uuid4()}"
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        original = db.session.get(SignalMonitor, ids["monitor"])
        assert original is not None
        source_watchlist = db.session.get(Watchlist, original.watchlist_id)
        assert source_watchlist is not None
        dossier_id = source_watchlist.dossier_id
        connection = IntegrationConnection(
            tenant_id=ids["tenant"],
            provider="signal-avanza",
            name=f"concurrent-{uuid.uuid4().hex[:8]}",
            status="active",
            adapter_mode="mock",
            api_version="v1",
        )
        db.session.add(connection)
        db.session.commit()
        connection_id = connection.id

    barrier = threading.Barrier(2)

    def create_once() -> tuple[int, str]:
        with (
            app.test_request_context(
                "/",
                method="POST",
                json={
                    "connection_id": str(connection_id),
                    "query": "same concurrent query",
                    "name": name,
                    "cadence": "daily",
                },
                headers={"Idempotency-Key": idempotency_key},
            ),
            tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
        ):
            user = db.session.get(User, ids["user"])
            assert user is not None
            login_user(user)
            g.active_tenant_id = ids["tenant"]
            barrier.wait(timeout=5)
            response, status = inspect.unwrap(signal_routes.create_dossier_monitor)(dossier_id)
            db.session.remove()
            return status, response.get_json()["id"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=10)
            for future in (executor.submit(create_once), executor.submit(create_once))
        ]
    assert [status for status, _ in results] == [202, 202]
    assert len({monitor_id for _, monitor_id in results}) == 1
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        watchlist_ids = list(
            db.session.scalars(
                select(Watchlist.id).where(
                    Watchlist.tenant_id == ids["tenant"],
                    Watchlist.dossier_id == dossier_id,
                    Watchlist.name == name,
                )
            )
        )
        assert len(watchlist_ids) == 1
        assert (
            db.session.scalar(
                select(func.count())
                .select_from(SignalMonitor)
                .where(
                    SignalMonitor.tenant_id == ids["tenant"],
                    SignalMonitor.watchlist_id == watchlist_ids[0],
                )
            )
            == 1
        )
        assert (
            db.session.scalar(
                select(func.count())
                .select_from(IntegrationOutboxEvent)
                .where(
                    IntegrationOutboxEvent.tenant_id == ids["tenant"],
                    IntegrationOutboxEvent.idempotency_key == idempotency_key,
                )
            )
            == 1
        )


def test_signal_outbox_fencing_and_failure_states(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, ids = jobs_stack
    app.extensions["integration_keyring"] = IntegrationKeyring(
        f"1:{base64.b64encode(b'outbox-integration-key-material!'[:32]).decode()}", 1
    )
    now = datetime.now(UTC)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        connection = IntegrationConnection(
            tenant_id=ids["tenant"],
            provider="signal-avanza",
            name="outbox-states",
            status="active",
            adapter_mode="mock",
            api_version="v1",
        )
        db.session.add(connection)
        db.session.flush()
        store_credential(connection=connection, kind="api_token", secret="api-token-first-123")
        store_credential(connection=connection, kind="api_token", secret="api-token-second-123")
        store_credential(connection=connection, kind="webhook_secret", secret="webhook-first-123")
        store_credential(connection=connection, kind="webhook_secret", secret="webhook-second-123")
        store_credential(connection=connection, kind="webhook_secret", secret="webhook-third-123")
        assert active_secrets(connection, "api_token") == ["api-token-second-123"]
        assert active_secrets(connection, "webhook_secret") == [
            "webhook-third-123",
            "webhook-second-123",
        ]

        def event(
            status: str, key: str, *, monitor_id: uuid.UUID | None = None, **values: Any
        ) -> IntegrationOutboxEvent:
            payload = {"external_id": "mock-monitor-1"}
            digest = canonical_hash({"event_type": "monitor.pause", "payload": payload})
            item = IntegrationOutboxEvent(
                tenant_id=ids["tenant"],
                connection_id=connection.id,
                monitor_id=monitor_id,
                event_type="monitor.pause",
                payload=payload,
                idempotency_key=key,
                request_hash=digest,
                intention_hash=digest,
                status=status,
                **values,
            )
            db.session.add(item)
            db.session.flush()
            return item

        delivered = event("delivered", "state-delivered")
        future = event("retrying", "state-not-due", next_attempt_at=now + timedelta(hours=1))
        claimed = event("processing", "state-claimed", claimed_at=now, claimed_by="worker")
        unsupported = event("pending", "state-unsupported", monitor_id=ids["monitor"])
        unsupported.event_type = "unsupported"
        contract_failure = event("pending", "state-contract-error", monitor_id=ids["monitor"])
        transient = event("pending", "state-transient")
        disabled = IntegrationConnection(
            tenant_id=ids["tenant"],
            provider="signal-avanza",
            name="disabled-state",
            status="disabled",
            adapter_mode="mock",
            api_version="v1",
        )
        db.session.add(disabled)
        db.session.flush()
        unavailable = IntegrationOutboxEvent(
            tenant_id=ids["tenant"],
            connection_id=disabled.id,
            event_type="connection.test",
            payload={},
            idempotency_key="state-unavailable",
            request_hash=canonical_hash({"event_type": "connection.test", "payload": {}}),
            intention_hash=canonical_hash({"event_type": "connection.test", "payload": {}}),
            status="pending",
        )
        db.session.add(unavailable)
        staged = stage_outbox(
            connection=connection,
            monitor=None,
            event_type="connection.test",
            payload={"value": 1},
            idempotency_key="state-conflict",
        )
        assert (
            stage_outbox(
                connection=connection,
                monitor=None,
                event_type="connection.test",
                payload={"value": 1},
                idempotency_key="state-conflict",
            ).id
            == staged.id
        )
        with pytest.raises(IdempotencyConflict):
            stage_outbox(
                connection=connection,
                monitor=None,
                event_type="connection.test",
                payload={"value": 2},
                idempotency_key="state-conflict",
            )
        other_connection = IntegrationConnection(
            tenant_id=ids["tenant"],
            provider="signal-avanza",
            name="other-resource",
            status="active",
            adapter_mode="mock",
            api_version="v1",
        )
        db.session.add(other_connection)
        db.session.flush()
        with pytest.raises(IdempotencyConflict):
            stage_outbox(
                connection=other_connection,
                monitor=None,
                event_type="connection.test",
                payload={"value": 1},
                idempotency_key="state-conflict",
            )
        db.session.commit()
        event_ids = [
            delivered.id,
            future.id,
            claimed.id,
            unsupported.id,
            contract_failure.id,
            unavailable.id,
            transient.id,
        ]
    assert (
        dispatch_outbox.apply(
            kwargs={"event_id": str(event_ids[0]), "tenant_id": str(ids["tenant"])}, throw=True
        ).get()["status"]
        == "already_delivered"
    )
    assert (
        dispatch_outbox.apply(
            kwargs={"event_id": str(event_ids[1]), "tenant_id": str(ids["tenant"])}, throw=True
        ).get()["status"]
        == "not_due"
    )
    assert (
        dispatch_outbox.apply(
            kwargs={"event_id": str(event_ids[2]), "tenant_id": str(ids["tenant"])}, throw=True
        ).get()["status"]
        == "already_claimed"
    )
    assert dispatch_outbox.apply(
        kwargs={"event_id": str(event_ids[3]), "tenant_id": str(ids["tenant"])}, throw=True
    ).get() == {"status": "failed", "reason": "permanent_failure"}
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        monitor = db.session.get(SignalMonitor, ids["monitor"])
        assert monitor is not None
        assert monitor.status == "error"
        assert monitor.observed_status == "error"
        assert monitor.last_error == (
            "No se pudo aplicar la configuración en Signal. Revise los campos e inténtelo de nuevo."
        )

    class ContractAdapter:
        def pause_monitor(self, monitor_id: str, *, idempotency_key: str) -> None:
            del monitor_id, idempotency_key
            raise SignalContractError("provider contract detail must not reach the monitor")

    monkeypatch.setitem(app.extensions, "signal_avanza_adapter", ContractAdapter())
    assert dispatch_outbox.apply(
        kwargs={"event_id": str(event_ids[4]), "tenant_id": str(ids["tenant"])}, throw=True
    ).get() == {"status": "failed", "reason": "signal_contract_error"}
    assert (
        dispatch_outbox.apply(
            kwargs={"event_id": str(event_ids[5]), "tenant_id": str(ids["tenant"])}, throw=True
        ).get()["status"]
        == "failed"
    )

    class TemporaryAdapter:
        def pause_monitor(self, monitor_id: str, *, idempotency_key: str) -> None:
            del monitor_id, idempotency_key
            raise SignalTemporaryError("temporary")

    monkeypatch.setitem(app.extensions, "signal_avanza_adapter", TemporaryAdapter())
    with pytest.raises(Retry):
        dispatch_outbox.apply(
            kwargs={"event_id": str(event_ids[6]), "tenant_id": str(ids["tenant"])}, throw=True
        ).get()


def test_weekly_digest_schedule_propagates_tenant_wall_clock_timezone(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
) -> None:
    app, ids = jobs_stack
    now = datetime.now(UTC)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        schedule = JobSchedule(
            tenant_id=ids["tenant"],
            schedule_key="weekly-madrid",
            task_name="maintenance.weekly_digest",
            queue="maintenance",
            payload={},
            cadence_seconds=604800,
            next_run_at=now - timedelta(minutes=1),
            schedule_kind="weekly",
            local_time=dt_time(9),
            weekday=6,
            timezone="Europe/Madrid",
        )
        db.session.add(schedule)
        db.session.commit()
        schedule_id = schedule.id
    with app.app_context():
        assert job_tasks.dispatch_due_jobs.run() == 1
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        job_id = db.session.scalar(
            select(BackgroundJob.id).where(
                BackgroundJob.idempotency_key.like(f"schedule:{schedule_id}:%")
            )
        )
        assert job_id is not None
    finished = _wait_job(app, ids, job_id, "succeeded")
    assert finished.result_ref["timezone"] == "Europe/Madrid"


def test_concurrent_same_delivery_executes_handler_once(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, ids = jobs_stack
    entered, release = threading.Event(), threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def blocking_handler(payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
        nonlocal calls
        del payload, job
        with calls_lock:
            calls += 1
        entered.set()
        assert release.wait(timeout=5)
        return {"executed": True}

    monkeypatch.setitem(job_tasks.HANDLERS, "oracle.signal.triage", blocking_handler)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        job = enqueue_job(
            "oracle.signal.triage",
            payload={},
            idempotency_key="concurrent-delivery-lease",
            requested_by_user_id=ids["user"],
            publish=False,
        )
        job_id, task_id = job.id, str(job.celery_task_id)

    class Delivery:
        request = SimpleNamespace(id=task_id)

        def retry(self, **kwargs: Any) -> None:
            del kwargs
            raise AssertionError("No debe reintentarse")

    def deliver() -> dict[str, Any]:
        with app.app_context():
            return execute_durable(  # type: ignore[arg-type]
                Delivery(), job_id=str(job_id), tenant_id=str(ids["tenant"]), payload={}
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(deliver)
        assert entered.wait(timeout=5)
        second = executor.submit(deliver)
        second_result = second.result(timeout=5)
        release.set()
        first_result = first.result(timeout=5)
    assert calls == 1
    assert first_result == {"executed": True}
    assert second_result == {"ignored": True, "reason": "active_delivery"}
    finished = _wait_job(app, ids, job_id, "succeeded")
    assert finished.attempts == 1
    assert finished.execution_lease_id is None and finished.lease_expires_at is None


def test_cancel_during_handler_finishes_cancelled_not_succeeded(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, ids = jobs_stack
    entered, release = threading.Event(), threading.Event()
    lifecycle: list[dict[str, Any]] = []

    def capture_log(event: str, *, extra: dict[str, Any]) -> None:
        lifecycle.append({"event": event, **extra["event_fields"]})

    monkeypatch.setattr(job_tasks.logger, "info", capture_log)

    def blocking_handler(payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
        del payload, job
        entered.set()
        assert release.wait(timeout=5)
        return {"must_not_persist": True}

    monkeypatch.setitem(job_tasks.HANDLERS, "oracle.signal.triage", blocking_handler)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        job = enqueue_job(
            "oracle.signal.triage",
            payload={},
            idempotency_key="cooperative-cancel-mid-handler",
            requested_by_user_id=ids["user"],
            publish=False,
        )
        job_id, task_id = job.id, str(job.celery_task_id)

    class Delivery:
        request = SimpleNamespace(id=task_id)

    def deliver() -> dict[str, Any]:
        with app.app_context():
            return execute_durable(  # type: ignore[arg-type]
                Delivery(), job_id=str(job_id), tenant_id=str(ids["tenant"]), payload={}
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(deliver)
        assert entered.wait(timeout=5)
        with (
            app.app_context(),
            tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
        ):
            row = db.session.get(BackgroundJob, job_id)
            assert row is not None
            row.cancel_requested = True
            row.cancel_requested_at = datetime.now(UTC)
            row.version += 1
            db.session.commit()
        release.set()
        assert future.result(timeout=5) == {"cancelled": True}
    cancelled = _wait_job(app, ids, job_id, "cancelled")
    assert cancelled.result_ref == {}
    assert any(
        fields.get("job_id") == str(job_id)
        and fields.get("tenant_id") == str(ids["tenant"])
        and "correlation_id" in fields
        for fields in lifecycle
    )


def test_concurrent_publish_claim_contacts_broker_once(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, ids = jobs_stack
    calls = 0
    calls_lock = threading.Lock()
    task = app.extensions["celery"].tasks["oracle.signal.triage"]

    def accepted(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        del args, kwargs
        with calls_lock:
            calls += 1

    monkeypatch.setattr(task, "apply_async", accepted)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        job = enqueue_job(
            "oracle.signal.triage",
            payload={},
            idempotency_key="concurrent-publish-claim",
            requested_by_user_id=ids["user"],
            publish=False,
        )
        job_id = job.id

    def publish() -> bool:
        with (
            app.app_context(),
            tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
        ):
            row = db.session.get(BackgroundJob, job_id)
            assert row is not None
            return publish_job(row)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(executor.map(lambda _: publish(), range(2)))
    assert results == [False, True]
    assert calls == 1
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        row = db.session.get(BackgroundJob, job_id)
        assert row is not None and row.stage == "published" and row.publish_attempts == 1
        row.status, row.stage = "cancelled", "cancelled"
        db.session.commit()


def test_stale_worker_is_fenced_and_recovered(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
) -> None:
    app, ids = jobs_stack
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        stale = BackgroundJob(
            tenant_id=ids["tenant"],
            job_type="oracle.signal.triage",
            status="running",
            stage="processing",
            queue="signals",
            idempotency_key="stale-worker-recovery",
            payload_hash=__import__("hashlib").sha256(b"{}").digest(),
            input_payload={},
            celery_task_id=str(uuid.uuid4()),
            attempts=1,
            heartbeat_at=datetime.now(UTC) - timedelta(hours=1),
            execution_lease_id=uuid.uuid4(),
            lease_expires_at=datetime.now(UTC) - timedelta(minutes=1),
            requested_by_user_id=ids["user"],
        )
        db.session.add(stale)
        db.session.commit()
        stale_id = stale.id
    with app.app_context():
        assert job_tasks.recover_stale_jobs.run() == 1
        assert job_tasks.dispatch_queued_jobs.run() == 1
    recovered = _wait_job(app, ids, stale_id, "succeeded")
    assert recovered.attempts == 2
    assert recovered.error_code is None


def test_real_worker_retry_permanent_error_and_sanitization(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
) -> None:
    app, ids = jobs_stack
    created: list[uuid.UUID] = []
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        for suffix, simulate, attempts in (
            ("retry", "retryable", 2),
            ("permanent", "permanent", 3),
        ):
            job = enqueue_job(
                "oracle.signal.triage",
                payload={"simulate": simulate},
                idempotency_key=f"worker-{suffix}-sanitized",
                requested_by_user_id=ids["user"],
                max_attempts=attempts,
            )
            created.append(job.id)
    retried = _wait_job(app, ids, created[0], "failed")
    permanent = _wait_job(app, ids, created[1], "failed")
    assert retried.attempts == 2 and retried.retryable is True
    assert retried.error_code == "retry_exhausted"
    assert permanent.attempts == 1 and permanent.retryable is False
    assert permanent.error_code == "permanent_failure"
    assert "Dependencia" not in (retried.error_message or "")
    assert "Payload" not in (permanent.error_message or "")


def test_publish_failure_reconciles_once_and_scheduler_commit_survives_crash(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, ids = jobs_stack
    celery = app.extensions["celery"]
    task = celery.tasks["oracle.signal.triage"]
    original_apply = task.apply_async

    def broker_down(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise ConnectionError("secret broker detail")

    monkeypatch.setattr(task, "apply_async", broker_down)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        job = enqueue_job(
            "oracle.signal.triage",
            payload={},
            idempotency_key="publish-pending-reconcile",
            requested_by_user_id=ids["user"],
        )
        assert job.stage == "publish_pending"
        assert job.error_message == "El job está pendiente de publicación."
        job_id = job.id
    monkeypatch.setattr(task, "apply_async", original_apply)
    with app.app_context():
        assert job_tasks.dispatch_queued_jobs.run() == 1
        assert job_tasks.dispatch_queued_jobs.run() == 0
    assert _wait_job(app, ids, job_id, "succeeded").publish_attempts == 2

    now = datetime.now(UTC)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        schedule = JobSchedule(
            tenant_id=ids["tenant"],
            schedule_key="crash-safe",
            task_name="oracle.signal.triage",
            queue="signals",
            payload={},
            cadence_seconds=3600,
            next_run_at=now - timedelta(minutes=1),
        )
        db.session.add(schedule)
        db.session.commit()
        schedule_id = schedule.id

    original_publish = job_tasks.publish_job

    def crash_after_commit(job: BackgroundJob) -> bool:
        del job
        raise RuntimeError("simulated process crash")

    monkeypatch.setattr(job_tasks, "publish_job", crash_after_commit)
    with app.app_context(), pytest.raises(RuntimeError, match="simulated"):
        job_tasks.dispatch_due_jobs.run()
    monkeypatch.setattr(job_tasks, "publish_job", original_publish)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        schedule = db.session.get(JobSchedule, schedule_id)
        assert schedule is not None and schedule.next_run_at > now
        assert (
            db.session.scalar(
                select(func.count())
                .select_from(BackgroundJob)
                .where(BackgroundJob.idempotency_key.like(f"schedule:{schedule_id}:%"))
            )
            == 1
        )
    with app.app_context():
        assert job_tasks.dispatch_due_jobs.run() == 0
        assert job_tasks.dispatch_queued_jobs.run() == 1


def test_invitation_email_is_durable_and_reconciles_after_broker_failure(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, ids = jobs_stack
    celery = app.extensions["celery"]
    task = celery.tasks["notifications.send_email"]
    original_apply = task.apply_async
    sender = app.extensions["email_sender"]
    before = len(sender.messages)

    def broker_down(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise ConnectionError("broker-password=must-not-leak")

    monkeypatch.setattr(task, "apply_async", broker_down)
    invitation_id = uuid.uuid4()
    user_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        tenant = db.session.get(Tenant, ids["tenant"])
        assert tenant is not None
        user = User(
            id=user_id,
            email=f"invite-{user_id}@example.test",
            display_name="Invited",
            status="invited",
        )
        membership = TenantMembership(
            id=membership_id,
            tenant_id=ids["tenant"],
            user_id=user_id,
            status="invited",
            invited_at=datetime.now(UTC),
        )
        raw = stable_invitation_token(
            invitation_id=invitation_id,
            secret_key=app.config["SECRET_KEY"],
        )
        invitation = Invitation(
            id=invitation_id,
            tenant_id=ids["tenant"],
            membership_id=membership_id,
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            invited_by_user_id=ids["user"],
        )
        db.session.add(user)
        db.session.flush()
        db.session.add(membership)
        db.session.flush()
        db.session.add(invitation)
        job = stage_job(
            "notifications.send_email",
            payload={"kind": "invitation", "invitation_id": str(invitation_id)},
            idempotency_key=f"invitation-email:{invitation_id}",
            requested_by_user_id=ids["user"],
            resource_type="invitation",
            resource_id=invitation_id,
        )
        db.session.commit()
        assert publish_job(job) is False
        db.session.refresh(job)
        assert job.stage == "publish_pending"
        serialized_payload = json.dumps(job.input_payload)
        assert "token" not in serialized_payload.casefold()
        assert raw not in serialized_payload
        job_id = job.id

    assert len(sender.messages) == before
    monkeypatch.setattr(task, "apply_async", original_apply)
    with app.app_context():
        assert job_tasks.dispatch_queued_jobs.run() == 1
        assert job_tasks.dispatch_queued_jobs.run() == 0
    finished = _wait_job(app, ids, job_id, "succeeded")
    assert finished.publish_attempts == 2
    assert finished.result_ref["invitation_id"] == str(invitation_id)
    assert len(sender.messages) == before + 1
    message = sender.messages[-1]
    delivered_token = message.body.split("token=", 1)[1].splitlines()[0]
    assert hash_token(delivered_token) == hash_token(raw)
    assert message.message_id == f"invitation-{invitation_id}"


class _FailingEmailSender:
    supports_idempotency = True

    def send_password_reset(self, **kwargs: Any) -> None:
        del kwargs
        raise TimeoutError("smtp password=do-not-leak")


def test_transient_email_failure_revokes_generated_token(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
) -> None:
    app, ids = jobs_stack
    original = app.extensions["email_sender"]
    app.extensions["email_sender"] = _FailingEmailSender()
    try:
        with (
            app.app_context(),
            tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
        ):
            job = enqueue_job(
                "notifications.send_email",
                payload={"kind": "password_reset", "user_id": str(ids["user"])},
                idempotency_key="email-transient-revokes-token",
                requested_by_user_id=ids["user"],
                max_attempts=1,
            )
            job_id = job.id
        finished = _wait_job(app, ids, job_id, "failed")
        assert finished.error_message == "Se agotaron los reintentos permitidos."
        migrator = create_engine(os.environ["TEST_DATABASE_URL"])
        with migrator.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM password_reset_tokens "
                        "WHERE user_id=:user AND revoked_at IS NULL"
                    ),
                    {"user": ids["user"]},
                )
                == 0
            )
        migrator.dispose()
    finally:
        app.extensions["email_sender"] = original


class _NonIdempotentUncertainSender:
    supports_idempotency = False

    def __init__(self) -> None:
        self.calls = 0

    def send_password_reset(self, **kwargs: Any) -> None:
        del kwargs
        self.calls += 1
        raise TimeoutError("SMTP accepted or disconnected; outcome unknown")


def test_non_idempotent_smtp_unknown_outcome_is_never_resent(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
) -> None:
    app, ids = jobs_stack
    original = app.extensions["email_sender"]
    sender = _NonIdempotentUncertainSender()
    app.extensions["email_sender"] = sender
    try:
        with (
            app.app_context(),
            tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
        ):
            job = enqueue_job(
                "notifications.send_email",
                payload={"kind": "password_reset", "user_id": str(ids["user"])},
                idempotency_key="smtp-unknown-at-most-once",
                requested_by_user_id=ids["user"],
                max_attempts=3,
            )
            job_id = job.id
        failed = _wait_job(app, ids, job_id, "failed")
        assert failed.attempts == 2
        assert failed.error_code == "permanent_failure"
        assert sender.calls == 1
        migrator = create_engine(os.environ["TEST_DATABASE_URL"])
        with migrator.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM password_reset_tokens "
                        "WHERE delivery_key=:key AND delivery_started_at IS NOT NULL "
                        "AND delivered_at IS NULL AND revoked_at IS NOT NULL"
                    ),
                    {"key": f"password-reset-{job_id}"},
                )
                == 1
            )
        migrator.dispose()
    finally:
        app.extensions["email_sender"] = original


def test_post_send_crash_retries_one_logical_delivery_and_one_valid_token(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, ids = jobs_stack
    sender = app.extensions["email_sender"]
    before = len(sender.messages)
    original_send = sender.send_password_reset
    attempts = 0

    def crash_after_first_send(**kwargs: Any) -> None:
        nonlocal attempts
        attempts += 1
        original_send(**kwargs)
        if attempts == 1:
            raise TimeoutError("process crashed after SMTP accepted the message")

    monkeypatch.setattr(sender, "send_password_reset", crash_after_first_send)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        job = enqueue_job(
            "notifications.send_email",
            payload={
                "kind": "password_reset",
                "user_id": str(ids["user"]),
            },
            idempotency_key="post-send-crash-deduplicated",
            requested_by_user_id=ids["user"],
            max_attempts=2,
        )
        job_id = job.id
    finished = _wait_job(app, ids, job_id, "succeeded")
    delivery_key = f"password-reset-{job_id}"
    assert finished.attempts == 2
    assert attempts == 2
    assert finished.result_ref["delivery_key"] == delivery_key
    assert len(sender.messages) == before + 1
    assert sender.messages[-1].message_id == delivery_key
    migrator = create_engine(os.environ["TEST_DATABASE_URL"])
    with migrator.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM password_reset_tokens "
                    "WHERE delivery_key=:key AND delivered_at IS NOT NULL "
                    "AND revoked_at IS NULL AND used_at IS NULL"
                ),
                {"key": delivery_key},
            )
            == 1
        )
    migrator.dispose()


def test_email_job_rejects_user_without_active_tenant_membership(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
) -> None:
    app, ids = jobs_stack
    foreign_user = uuid.uuid4()
    migrator = create_engine(os.environ["TEST_DATABASE_URL"])
    with migrator.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users"
                "(id,email,display_name,status,email_verified_at,created_at,updated_at) "
                "VALUES (:id,'foreign@example.test','Foreign','active',now(),now(),now())"
            ),
            {"id": foreign_user},
        )
    sender = app.extensions["email_sender"]
    before = len(sender.messages)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        job = enqueue_job(
            "notifications.send_email",
            payload={"kind": "password_reset", "user_id": str(foreign_user)},
            idempotency_key="cross-tenant-email-rejected",
            requested_by_user_id=ids["user"],
        )
        job_id = job.id
    failed = _wait_job(app, ids, job_id, "failed")
    assert failed.error_code == "permanent_failure"
    assert len(sender.messages) == before
    with migrator.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM password_reset_tokens WHERE user_id=:user"),
                {"user": foreign_user},
            )
            == 0
        )
    migrator.dispose()


def test_maintenance_cleanup_runs_per_tenant_under_rls(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
) -> None:
    app, ids = jobs_stack
    old = datetime.now(UTC) - timedelta(days=9)
    migrator = create_engine(os.environ["TEST_DATABASE_URL"])
    with migrator.begin() as connection:
        connection.execute(
            text("UPDATE tenants SET status='suspended' WHERE id=:tenant"),
            {"tenant": ids["tenant"]},
        )
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        user = db.session.get(User, ids["user"])
        membership = db.session.get(TenantMembership, ids["membership"])
        assert user is not None and membership is not None
        token = PasswordResetToken(
            user_id=user.id,
            tenant_id=ids["tenant"],
            token_hash=b"x" * 32,
            expires_at=old,
        )
        db.session.add(token)
        db.session.commit()
        token_id = token.id
    with app.app_context():
        assert job_tasks.cleanup_tokens.run() >= 1
    with migrator.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM password_reset_tokens WHERE id=:id"), {"id": token_id}
            )
            == 0
        )
    with migrator.begin() as connection:
        connection.execute(
            text("UPDATE tenants SET status='active' WHERE id=:tenant"),
            {"tenant": ids["tenant"]},
        )
    migrator.dispose()


def test_ai_job_persists_reviewer_attempt_and_settles_reservation(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
) -> None:
    app, ids = jobs_stack
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        dossier_id = db.session.scalar(select(StrategicDossier.id))
        assert dossier_id is not None
        job = enqueue_job(
            "oracle.ai.opportunity",
            payload={"dossier_id": str(dossier_id)},
            idempotency_key="ai-opportunity-reviewed-v1",
            requested_by_user_id=ids["user"],
            dossier_id=dossier_id,
        )
        job_id = job.id
    completed = _wait_job(app, ids, job_id, "succeeded")
    assert completed.result_ref["status"] == "candidate"
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        artifact = db.session.scalar(
            select(AIArtifact)
            .where(AIArtifact.dossier_id == dossier_id, AIArtifact.agent == "opportunity")
            .order_by(AIArtifact.created_at.desc())
        )
        assert artifact is not None
        attempts = list(
            db.session.scalars(
                select(AIAttempt)
                .where(AIAttempt.audit_log_id == artifact.audit_log_id)
                .order_by(AIAttempt.attempt_number)
            )
        )
        ledger = db.session.scalar(
            select(AIUsageLedger).where(AIUsageLedger.audit_log_id == artifact.audit_log_id)
        )
        assert [row.kind for row in attempts] == ["generate", "reviewer"]
        assert all(row.status == "succeeded" and row.completed_at for row in attempts)
        assert ledger is not None and ledger.status == "settled"
        assert ledger.reserved_cost_micros == 0
        replay_job = db.session.get(BackgroundJob, job_id)
        assert replay_job is not None
        replay = execute_agent(agent="opportunity", dossier_id=dossier_id, job=replay_job)
        assert replay["artifact_id"] == str(artifact.id)
        audit = db.session.scalar(select(AIAuditLog))
        assert audit is not None
        audit_id, artifact_id = audit.id, artifact.id
    with (
        app.test_request_context("/", method="GET"),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        user = db.session.get(User, ids["user"])
        assert user is not None
        login_user(user)
        g.active_tenant_id = ids["tenant"]
        payload = inspect.unwrap(ai_routes.get_audit)(audit_id)
        assert payload["status"] == "succeeded"
        listing = inspect.unwrap(ai_routes.list_ai_audit)()
        assert str(audit_id) in {item["id"] for item in listing["items"]}
    with (
        app.test_request_context(
            "/", method="POST", json={"decision": "accepted", "reason": "validado"}
        ),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        user = db.session.get(User, ids["user"])
        assert user is not None
        login_user(user)
        g.active_tenant_id = ids["tenant"]
        review, status = inspect.unwrap(ai_routes.review_artifact)(artifact_id)
        assert status == 201 and review["artifact_status"] == "valid"


def test_long_report_reviewer_uses_compact_claim_package(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, ids = jobs_stack
    captured: dict[str, Any] = {}
    long_sentence = (
        "La posición competitiva exige una lectura material de órganos compradores, importes, "
        "frecuencia de adjudicación y límites de cobertura para decidir el siguiente paso. "
    )
    long_paragraph = long_sentence * 12
    huge_computed_analysis = {
        "sentinel": "competitive aggregate sentinel",
        "rows": [
            {
                "buyer": f"Organismo {index}",
                "amount": index * 1000,
                "notes": "dato agregado que no debe reenviarse al revisor " * 30,
            }
            for index in range(180)
        ],
    }

    class LongReportProvider(MockLLMProvider):
        def generate_structured(self, request: Any, schema: Any) -> LLMResult:
            if request.agent == "competitive_procurement_intelligence":
                output = ReportOutput.model_validate(
                    {
                        "facts": [],
                        "inferences": [],
                        "recommendations": [],
                        "confidence": 72,
                        "open_questions": [],
                        "warnings": [],
                        "title": "Informe competitivo largo",
                        "executive_summary": long_paragraph,
                        "sections": [
                            {
                                "heading": f"Sección {index}",
                                "paragraphs": [
                                    {
                                        "text": long_paragraph,
                                        "kind": "inference",
                                        "confidence": 70,
                                        "evidence_ids": [],
                                    }
                                ],
                            }
                            for index in range(14)
                        ],
                        "top_opportunities": ["Priorizar la conversación con compradores."],
                        "top_risks": ["Cobertura incompleta del histórico público."],
                        "recommended_actions": ["Revisar manualmente las hipótesis comerciales."],
                        "decisions_required": [],
                        "source_index": [],
                    }
                )
                return LLMResult(output, 10_000, 3_200, 0, 1)
            if request.agent == "evidence_reviewer":
                encoded = json.dumps(request.context, ensure_ascii=False)
                captured["review_context_chars"] = len(encoded)
                captured["review_context"] = request.context
                captured["max_output_tokens"] = request.max_output_tokens
                if len(encoded) > 30_000 or "competitive aggregate sentinel" in encoded:
                    raise ValueError("Invalid JSON: EOF while parsing a value")
            return super().generate_structured(request, schema)

    monkeypatch.setattr(
        "opn_oracle.ai.service.provider_from_config", lambda config: LongReportProvider("long")
    )
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        dossier_id = ids["dossier"]
        policy = db.session.scalar(select(AITenantPolicy).with_for_update())
        assert policy is not None
        policy.max_output_tokens = 16_000
        job = BackgroundJob(
            tenant_id=ids["tenant"],
            dossier_id=dossier_id,
            job_type="oracle.ai.competitive_procurement_intelligence",
            status="running",
            queue="ai",
            idempotency_key=f"long-reviewer-{uuid.uuid4()}",
            payload_hash=hashlib.sha256(b"long-reviewer").digest(),
            input_payload={"dossier_id": str(dossier_id)},
            requested_by_user_id=ids["user"],
        )
        db.session.add(job)
        db.session.commit()

        result = execute_agent(
            agent="competitive_procurement_intelligence",
            dossier_id=dossier_id,
            job=job,
            supplemental_context={"computed_analysis": huge_computed_analysis},
        )

        assert result["status"] == "candidate"
        assert captured["review_context_chars"] < 30_000
        assert captured["max_output_tokens"] > 2_000
        review_context = captured["review_context"]
        assert "candidate_claims" in review_context
        assert "candidate_output" not in review_context
        assert "requested_scope" not in review_context
        assert "computed_analysis" not in review_context
        assert len(review_context["candidate_claims"]) == 14
        audit_id = db.session.scalar(
            select(AIArtifact.audit_log_id).where(AIArtifact.id == uuid.UUID(result["artifact_id"]))
        )
        assert audit_id is not None
        attempts = list(
            db.session.scalars(
                select(AIAttempt)
                .where(AIAttempt.audit_log_id == audit_id)
                .order_by(AIAttempt.attempt_number)
            )
        )
        assert [row.kind for row in attempts] == ["generate", "reviewer"]
        assert all(row.status == "succeeded" for row in attempts)


def test_ai_quota_reservation_is_tenant_global_under_real_concurrency(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, ids = jobs_stack
    entered, release = threading.Event(), threading.Event()

    class SlowProvider(MockLLMProvider):
        def generate_structured(self, request: Any, schema: Any) -> Any:
            if request.agent != "evidence_reviewer":
                entered.set()
                assert release.wait(10)
            return super().generate_structured(request, schema)

    monkeypatch.setattr(
        "opn_oracle.ai.service.provider_from_config", lambda config: SlowProvider("quota")
    )
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        policy = db.session.scalar(select(AITenantPolicy).with_for_update())
        dossier_id = db.session.scalar(select(StrategicDossier.id))
        assert policy is not None and dossier_id is not None
        policy.max_concurrency = 1
        jobs: list[uuid.UUID] = []
        for index, agent in enumerate(("opportunity", "risk")):
            row = BackgroundJob(
                tenant_id=ids["tenant"],
                dossier_id=dossier_id,
                job_type=f"oracle.ai.{agent}",
                status="running",
                queue="ai",
                idempotency_key=f"quota-concurrent-{index}",
                payload_hash=hashlib.sha256(str(index).encode()).digest(),
                input_payload={"dossier_id": str(dossier_id)},
                requested_by_user_id=ids["user"],
            )
            db.session.add(row)
            db.session.flush()
            jobs.append(row.id)
        db.session.commit()

    def run(job_id: uuid.UUID, agent: str) -> str:
        with (
            app.app_context(),
            tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
        ):
            row = db.session.get(BackgroundJob, job_id)
            assert row is not None
            try:
                execute_agent(agent=agent, dossier_id=dossier_id, job=row)
            except AIPolicyDenied:
                return "denied"
            return "succeeded"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, jobs[0], "opportunity")
        assert entered.wait(10)
        second = pool.submit(run, jobs[1], "risk")
        assert second.result(timeout=10) == "denied"
        release.set()
        assert first.result(timeout=10) == "succeeded"


def test_ai_stale_recovery_terminalizes_attempt_audit_and_reservation(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
) -> None:
    app, ids = jobs_stack
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        attempt = db.session.scalar(select(AIAttempt).order_by(AIAttempt.created_at.desc()))
        assert attempt is not None
        audit = db.session.get(AIAuditLog, attempt.audit_log_id)
        ledger = db.session.scalar(
            select(AIUsageLedger).where(AIUsageLedger.audit_log_id == attempt.audit_log_id)
        )
        assert audit is not None and ledger is not None
        attempt.status = "running"
        attempt.lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        attempt.completed_at = None
        audit.status = "running"
        audit.completed_at = None
        ledger.status = "reserved"
        ledger.reserved_cost_micros = 10
        db.session.commit()
        assert recover_stale_ai_executions() == 1
        assert attempt.status == "abandoned" and attempt.error_code == "stale_execution"
        assert audit.status == "failed" and audit.error_code == "stale_execution"
        assert ledger.status == "released" and ledger.reserved_cost_micros == 0


@pytest.mark.parametrize("fail_reviewer", [False, True])
def test_ai_provider_and_reviewer_failures_terminalize_durable_state(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
    fail_reviewer: bool,
) -> None:
    app, ids = jobs_stack

    class FailingProvider(MockLLMProvider):
        def generate_structured(self, request: Any, schema: Any) -> Any:
            if not fail_reviewer or request.agent == "evidence_reviewer":
                raise AIUnavailable("synthetic provider failure")
            return super().generate_structured(request, schema)

    monkeypatch.setattr(
        "opn_oracle.ai.service.provider_from_config", lambda config: FailingProvider("failure")
    )
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        dossier_id = db.session.scalar(select(StrategicDossier.id))
        policy = db.session.scalar(select(AITenantPolicy).with_for_update())
        assert dossier_id is not None and policy is not None
        policy.max_concurrency = 2
        job = BackgroundJob(
            tenant_id=ids["tenant"],
            dossier_id=dossier_id,
            job_type="oracle.ai.opportunity",
            status="running",
            queue="ai",
            idempotency_key=f"terminal-failure-{fail_reviewer}",
            payload_hash=hashlib.sha256(str(fail_reviewer).encode()).digest(),
            input_payload={"dossier_id": str(dossier_id)},
            requested_by_user_id=ids["user"],
        )
        db.session.add(job)
        db.session.commit()
        expected_error = EvidenceReviewError if fail_reviewer else AIUnavailable
        with pytest.raises(expected_error):
            execute_agent(agent="opportunity", dossier_id=dossier_id, job=job)
        audit = db.session.scalar(select(AIAuditLog).where(AIAuditLog.background_job_id == job.id))
        assert audit is not None and audit.status == "failed"
        attempts = list(
            db.session.scalars(
                select(AIAttempt)
                .where(AIAttempt.audit_log_id == audit.id)
                .order_by(AIAttempt.attempt_number)
            )
        )
        assert attempts[-1].status == "failed" and attempts[-1].completed_at is not None
        assert [row.kind for row in attempts] == (
            ["generate", "reviewer"] if fail_reviewer else ["generate"]
        )
        ledger = db.session.scalar(
            select(AIUsageLedger).where(AIUsageLedger.audit_log_id == audit.id)
        )
        assert ledger is not None
        assert ledger.status == "released" and ledger.reserved_cost_micros == 0
        assert (
            db.session.scalar(
                select(func.count(AIArtifact.id)).where(AIArtifact.audit_log_id == audit.id)
            )
            == 0
        )


def test_ai_recovery_fences_inflight_provider_and_prevents_resurrection(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, ids = jobs_stack
    entered, release = threading.Event(), threading.Event()

    class BlockedProvider(MockLLMProvider):
        def generate_structured(self, request: Any, schema: Any) -> Any:
            if request.agent != "evidence_reviewer":
                entered.set()
                assert release.wait(10)
            return super().generate_structured(request, schema)

    monkeypatch.setattr(
        "opn_oracle.ai.service.provider_from_config", lambda config: BlockedProvider("fenced")
    )
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        dossier_id = db.session.scalar(select(StrategicDossier.id))
        policy = db.session.scalar(select(AITenantPolicy).with_for_update())
        assert dossier_id is not None and policy is not None
        policy.max_concurrency = 2
        job = BackgroundJob(
            tenant_id=ids["tenant"],
            dossier_id=dossier_id,
            job_type="oracle.ai.opportunity",
            status="running",
            queue="ai",
            idempotency_key="stale-inflight-fencing",
            payload_hash=hashlib.sha256(b"stale-inflight-fencing").digest(),
            input_payload={"dossier_id": str(dossier_id)},
            requested_by_user_id=ids["user"],
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    def run() -> str:
        with (
            app.app_context(),
            tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
        ):
            row = db.session.get(BackgroundJob, job_id)
            assert row is not None
            with pytest.raises(AIPolicyDenied, match="lease"):
                execute_agent(agent="opportunity", dossier_id=dossier_id, job=row)
            return "fenced"

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run)
        assert entered.wait(10)
        with (
            app.app_context(),
            tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
        ):
            assert recover_stale_ai_executions(now=datetime.now(UTC) + timedelta(hours=1)) == 1
        release.set()
        assert future.result(timeout=10) == "fenced"
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        audit = db.session.scalar(select(AIAuditLog).where(AIAuditLog.background_job_id == job_id))
        assert audit is not None and audit.status == "failed"
        assert (
            db.session.scalar(
                select(func.count(AIArtifact.id)).where(AIArtifact.audit_log_id == audit.id)
            )
            == 0
        )
        ledger = db.session.scalar(
            select(AIUsageLedger).where(AIUsageLedger.audit_log_id == audit.id)
        )
        assert ledger is not None and ledger.status == "released"
        assert ledger.reserved_cost_micros == 0
        replay_job = db.session.get(BackgroundJob, job_id)
        assert replay_job is not None
        replay = execute_agent(agent="opportunity", dossier_id=dossier_id, job=replay_job)
        retry_artifact = db.session.get(AIArtifact, uuid.UUID(replay["artifact_id"]))
        assert retry_artifact is not None
        retry_audit = db.session.scalar(
            select(AIAuditLog).where(AIAuditLog.background_job_id == job_id)
        )
        assert retry_audit is not None and retry_audit.status == "succeeded"
        retry_attempts = list(
            db.session.scalars(
                select(AIAttempt)
                .where(AIAttempt.audit_log_id == retry_audit.id)
                .order_by(AIAttempt.attempt_number)
            )
        )
        assert [row.status for row in retry_attempts] == ["abandoned", "succeeded", "succeeded"]
        assert retry_artifact.audit_log_id == retry_audit.id


def test_ai_retry_after_transient_failure_creates_new_attempt_and_preserves_root_cause(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, ids = jobs_stack
    calls = 0

    class FlakyProvider(MockLLMProvider):
        def generate_structured(self, request: Any, schema: Any) -> Any:
            nonlocal calls
            if request.agent != "evidence_reviewer":
                calls += 1
                if calls == 1:
                    raise AIUnavailable("synthetic transient root")
            return super().generate_structured(request, schema)

    monkeypatch.setattr(
        "opn_oracle.ai.service.provider_from_config", lambda config: FlakyProvider("retry")
    )
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        dossier_id = db.session.scalar(select(StrategicDossier.id))
        policy = db.session.scalar(select(AITenantPolicy).with_for_update())
        assert dossier_id is not None and policy is not None
        policy.max_concurrency = 2
        job = BackgroundJob(
            tenant_id=ids["tenant"],
            dossier_id=dossier_id,
            job_type="oracle.ai.opportunity",
            status="running",
            queue="ai",
            idempotency_key="ai-transient-retry-settlement",
            payload_hash=hashlib.sha256(b"ai-transient-retry-settlement").digest(),
            input_payload={"dossier_id": str(dossier_id)},
            requested_by_user_id=ids["user"],
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id
        with pytest.raises(AIUnavailable, match="synthetic transient root"):
            execute_agent(agent="opportunity", dossier_id=dossier_id, job=job)
        failed_audit = db.session.scalar(
            select(AIAuditLog).where(AIAuditLog.background_job_id == job_id)
        )
        assert failed_audit is not None and failed_audit.status == "failed"
        assert failed_audit.error_code == "AIUnavailable"
        retry_job = db.session.get(BackgroundJob, job_id)
        assert retry_job is not None
        result = execute_agent(agent="opportunity", dossier_id=dossier_id, job=retry_job)
        artifact = db.session.get(AIArtifact, uuid.UUID(result["artifact_id"]))
        assert artifact is not None
        final_audit = db.session.scalar(
            select(AIAuditLog).where(AIAuditLog.background_job_id == job_id)
        )
        assert final_audit is not None and final_audit.status == "succeeded"
        attempts = list(
            db.session.scalars(
                select(AIAttempt)
                .where(AIAttempt.audit_log_id == final_audit.id)
                .order_by(AIAttempt.attempt_number)
            )
        )
        assert [row.status for row in attempts] == ["failed", "succeeded", "succeeded"]
        assert calls == 2
