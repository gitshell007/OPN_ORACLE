from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from opn_oracle.extensions import db
from opn_oracle.jobs.service import stage_job
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.oracle.models import (
    DossierSignal,
    Meeting,
    Opportunity,
    RiskItem,
    Signal,
)
from opn_oracle.platform.models import IntegrationConnection
from opn_oracle.reporting.alerts import (
    ALERT_TYPES,
    create_dossier_override,
    effective_alert_policy,
    evaluate_alerts,
)
from opn_oracle.reporting.models import (
    AlertEvaluation,
    Notification,
    NotificationDelivery,
    NotificationPreference,
)
from opn_oracle.tenants.context import TenantContext, tenant_context
from tests import test_integration_reporting_extra as reporting_helpers

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def reporting_stack(
    tmp_path_factory: pytest.TempPathFactory,
) -> Any:
    fixture = reporting_helpers.reporting_stack.__wrapped__(tmp_path_factory)
    yield from fixture


@pytest.fixture(autouse=True)
def clean_reporting_sessions(
    reporting_stack: tuple[Any, dict[str, uuid.UUID], str, Any],
) -> None:
    reporting_helpers.clean_reporting_sessions.__wrapped__(reporting_stack)


def test_alert_evaluator_seven_types_bundle_replay_cooldown_and_report_recipient(
    reporting_stack: tuple[Any, dict[str, uuid.UUID], str, Any],
) -> None:
    app, ids, _, _ = reporting_stack
    owner = reporting_helpers._client(reporting_stack)
    dossier = reporting_helpers._create_dossier(owner, ids, f"Alertas {uuid.uuid4().hex[:8]}")
    dossier_id = uuid.UUID(dossier["id"])
    report = reporting_helpers._create_report(owner, dossier["id"])
    report_id = uuid.UUID(report["id"])
    now = datetime(2026, 7, 11, 6, 0, tzinfo=UTC)

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["owner"])),
    ):
        signal = Signal(
            tenant_id=ids["tenant"],
            provider="test",
            external_id=f"alert-{uuid.uuid4()}",
            title="Señal con impacto",
            summary="Cambio verificable",
            source_type="official_publication",
            source_name="Fuente sintética",
            raw_hash=hashlib.sha256(uuid.uuid4().bytes).digest(),
            credibility=90,
        )
        db.session.add(signal)
        db.session.flush()
        db.session.add_all(
            [
                DossierSignal(
                    tenant_id=ids["tenant"],
                    dossier_id=dossier_id,
                    signal_id=signal.id,
                    status="new",
                    overall_score=90,
                ),
                RiskItem(
                    tenant_id=ids["tenant"],
                    dossier_id=dossier_id,
                    title="Riesgo uno",
                    status="open",
                    overall_score=90,
                ),
                RiskItem(
                    tenant_id=ids["tenant"],
                    dossier_id=dossier_id,
                    title="Riesgo dos",
                    status="monitoring",
                    overall_score=85,
                ),
                Opportunity(
                    tenant_id=ids["tenant"],
                    dossier_id=dossier_id,
                    title="Oportunidad próxima",
                    status="qualified",
                    deadline=now.date() + timedelta(days=2),
                ),
                Meeting(
                    tenant_id=ids["tenant"],
                    dossier_id=dossier_id,
                    title="Reunión próxima",
                    status="planned",
                    scheduled_at=now + timedelta(hours=2),
                ),
                IntegrationConnection(
                    tenant_id=ids["tenant"],
                    provider="synthetic-alert-provider",
                    name=f"error-{uuid.uuid4().hex[:8]}",
                    status="error",
                    adapter_mode="mock",
                    circuit_state="open",
                ),
            ]
        )
        failed_job = stage_job(
            "oracle.memory.refresh",
            payload={"resource_id": str(dossier_id)},
            idempotency_key=f"alert-failed-job:{uuid.uuid4()}",
            requested_by_user_id=ids["owner"],
            dossier_id=dossier_id,
        )
        failed_job.status = "failed"
        failed_job.stage = "failed"
        failed_job.finished_at = now
        db.session.commit()

        inherited = effective_alert_policy(dossier_id)
        assert inherited.scope == "tenant"
        first = evaluate_alerts(now=now)
        assert first["emitted"] >= 7
        types = set(db.session.scalars(select(AlertEvaluation.alert_type)))
        assert set(ALERT_TYPES).issubset(types)

        requester_ready = db.session.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == ids["owner"],
                Notification.report_id == report_id,
                Notification.notification_type == "report.ready",
            )
        )
        requester_alert = db.session.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == ids["owner"],
                Notification.report_id == report_id,
                Notification.notification_type == "alert.report_ready",
            )
        )
        collaborator_alert = db.session.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == ids["other_user"],
                Notification.resource_id == report_id,
                Notification.notification_type == "alert.report_ready",
            )
        )
        assert (requester_ready, requester_alert, collaborator_alert) == (1, 0, 1)

        high_risk_notifications = db.session.scalar(
            select(func.count(Notification.id)).where(
                Notification.notification_type == "alert.high_risk",
                Notification.dossier_id == dossier_id,
            )
        )
        high_risk_ledger = db.session.scalar(
            select(func.count(AlertEvaluation.id)).where(
                AlertEvaluation.alert_type == "high_risk",
                AlertEvaluation.dossier_id == dossier_id,
                AlertEvaluation.decision == "emitted",
            )
        )
        assert high_risk_notifications == 2
        assert high_risk_ledger == 4

        notification_count = db.session.scalar(select(func.count(Notification.id)))
        replay = evaluate_alerts(now=now)
        assert replay["emitted"] == 0
        assert db.session.scalar(select(func.count(Notification.id))) == notification_count

        risk = db.session.scalar(
            select(RiskItem).where(RiskItem.dossier_id == dossier_id).order_by(RiskItem.id)
        )
        assert risk is not None
        risk.updated_at = now + timedelta(minutes=1)
        db.session.commit()
        cooled = evaluate_alerts(now=now + timedelta(minutes=1))
        assert cooled["suppressed"] > 0
        assert (
            db.session.scalar(
                select(func.count(AlertEvaluation.id)).where(
                    AlertEvaluation.resource_id == risk.id,
                    AlertEvaluation.decision == "cooldown",
                )
            )
            == 2
        )

        override = create_dossier_override(dossier_id)
        override.cooldown_minutes = 0
        override.version += 1
        risk.updated_at = now + timedelta(minutes=2)
        db.session.commit()
        assert effective_alert_policy(dossier_id).id == override.id
        resumed = evaluate_alerts(now=now + timedelta(minutes=2))
        assert resumed["emitted"] >= 2

        quiet_now = datetime(2026, 7, 11, 23, 0, tzinfo=UTC)
        override.quiet_hours_start = time(22, 0)
        override.quiet_hours_end = time(7, 0)
        override.timezone = "UTC"
        preference = NotificationPreference(
            tenant_id=ids["tenant"],
            user_id=ids["other_user"],
            notification_type="alert.high_signal",
            channels={"in_app": True, "email": True},
            digest_cadence="instant",
            timezone="UTC",
            local_time=time(8, 0),
            minimum_severity="info",
        )
        quiet_signal = Signal(
            tenant_id=ids["tenant"],
            provider="test",
            external_id=f"alert-quiet-{uuid.uuid4()}",
            title="Señal en horario silencioso",
            summary="Cambio verificable",
            source_type="official_publication",
            source_name="Fuente sintética",
            raw_hash=hashlib.sha256(uuid.uuid4().bytes).digest(),
            credibility=90,
        )
        db.session.add_all([preference, quiet_signal])
        db.session.flush()
        quiet_link = DossierSignal(
            tenant_id=ids["tenant"],
            dossier_id=dossier_id,
            signal_id=quiet_signal.id,
            status="new",
            overall_score=95,
        )
        db.session.add(quiet_link)
        db.session.commit()
        quiet_result = evaluate_alerts(now=quiet_now)
        assert quiet_result["emitted"] >= 2
        deferred = db.session.scalar(
            select(BackgroundJob)
            .join(NotificationDelivery, NotificationDelivery.job_id == BackgroundJob.id)
            .join(Notification, Notification.id == NotificationDelivery.notification_id)
            .where(
                Notification.user_id == ids["other_user"],
                Notification.resource_id == quiet_link.id,
                Notification.notification_type == "alert.high_signal",
            )
        )
        assert deferred is not None
        assert deferred.not_before == datetime(2026, 7, 12, 7, 0, tzinfo=UTC)
