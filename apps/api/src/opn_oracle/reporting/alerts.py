"""Tenant-safe durable alert policy inheritance and evaluation."""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text

from opn_oracle.auth.permissions import current_permissions
from opn_oracle.extensions import db
from opn_oracle.integrations.models import IntegrationOutboxEvent
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.oracle.models import (
    DossierSignal,
    Meeting,
    Opportunity,
    Report,
    RiskItem,
    StrategicDossier,
)
from opn_oracle.oracle.policy import dossier_accessible, is_tenant_admin
from opn_oracle.platform.models import IntegrationConnection, TenantMembership
from opn_oracle.reporting.models import AlertEvaluation, AlertPolicy, Notification
from opn_oracle.reporting.notifications import CreatedNotification, create_notification
from opn_oracle.tenants.context import require_tenant_id

ALERT_TYPES = (
    "high_signal",
    "high_risk",
    "opportunity_deadline",
    "failed_integration",
    "failed_job",
    "meeting_upcoming",
    "report_ready",
)
SEVERITIES = frozenset({"info", "success", "warning", "critical"})
DEFAULT_ENABLED_TYPES = {key: True for key in ALERT_TYPES}
DEFAULT_SEVERITY_MAP = {
    "high_signal": "warning",
    "high_risk": "critical",
    "opportunity_deadline": "warning",
    "failed_integration": "critical",
    "failed_job": "critical",
    "meeting_upcoming": "info",
    "report_ready": "success",
}


class AlertPolicyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AlertCandidate:
    alert_type: str
    dossier_id: uuid.UUID | None
    resource_type: str
    resource_id: uuid.UUID
    occurrence: str
    title: str
    detail: str
    link: str
    preferred_recipient: uuid.UUID | None = None


def validate_policy_maps(
    enabled_types: Any, severity_map: Any
) -> tuple[dict[str, bool], dict[str, str]]:
    if not isinstance(enabled_types, dict) or set(enabled_types) != set(ALERT_TYPES):
        raise AlertPolicyError("enabled_types debe definir exactamente los siete tipos permitidos.")
    if any(not isinstance(value, bool) for value in enabled_types.values()):
        raise AlertPolicyError("enabled_types solo admite valores booleanos.")
    if not isinstance(severity_map, dict) or not set(severity_map).issubset(ALERT_TYPES):
        raise AlertPolicyError("severity_map contiene tipos no permitidos.")
    if any(value not in SEVERITIES for value in severity_map.values()):
        raise AlertPolicyError("severity_map contiene severidades no permitidas.")
    return dict(enabled_types), dict(severity_map)


def tenant_alert_policy(*, create: bool) -> AlertPolicy | None:
    tenant_id = require_tenant_id()
    policy = db.session.scalar(
        select(AlertPolicy).where(AlertPolicy.tenant_id == tenant_id, AlertPolicy.scope == "tenant")
    )
    if policy is None and create:
        policy = AlertPolicy(
            tenant_id=tenant_id,
            scope="tenant",
            dossier_id=None,
            signal_score_threshold=75,
            risk_score_threshold=75,
            opportunity_deadline_days=14,
            meeting_upcoming_hours=24,
            cooldown_minutes=60,
            enabled_types=dict(DEFAULT_ENABLED_TYPES),
            severity_map=dict(DEFAULT_SEVERITY_MAP),
            timezone="Europe/Madrid",
            version=1,
        )
        db.session.add(policy)
        db.session.flush()
    return policy


def dossier_alert_override(dossier_id: uuid.UUID) -> AlertPolicy | None:
    tenant_id = require_tenant_id()
    return db.session.scalar(
        select(AlertPolicy)
        .where(
            AlertPolicy.tenant_id == tenant_id,
            AlertPolicy.scope == "dossier",
            AlertPolicy.dossier_id == dossier_id,
        )
        .limit(1)
    )


def effective_alert_policy(dossier_id: uuid.UUID | None) -> AlertPolicy:
    if dossier_id is not None:
        override = dossier_alert_override(dossier_id)
        if override is not None:
            return override
    policy = tenant_alert_policy(create=True)
    assert policy is not None
    return policy


def create_dossier_override(dossier_id: uuid.UUID) -> AlertPolicy:
    existing = dossier_alert_override(dossier_id)
    if existing is not None:
        return existing
    inherited = effective_alert_policy(None)
    override = AlertPolicy(
        tenant_id=require_tenant_id(),
        scope="dossier",
        dossier_id=dossier_id,
        signal_score_threshold=inherited.signal_score_threshold,
        risk_score_threshold=inherited.risk_score_threshold,
        opportunity_deadline_days=inherited.opportunity_deadline_days,
        meeting_upcoming_hours=inherited.meeting_upcoming_hours,
        cooldown_minutes=inherited.cooldown_minutes,
        enabled_types=dict(inherited.enabled_types),
        severity_map=dict(inherited.severity_map),
        quiet_hours_start=inherited.quiet_hours_start,
        quiet_hours_end=inherited.quiet_hours_end,
        timezone=inherited.timezone,
        version=1,
    )
    db.session.add(override)
    db.session.flush()
    return override


def _occurrence(row: Any) -> str:
    value = getattr(row, "updated_at", None) or getattr(row, "created_at", None)
    return value.astimezone(UTC).isoformat() if value else "stable"


def _dossier_candidates(
    dossier: StrategicDossier, policy: AlertPolicy, now: datetime
) -> list[AlertCandidate]:
    dossier_id = dossier.id
    candidates: list[AlertCandidate] = []
    for signal_row in db.session.scalars(
        select(DossierSignal)
        .where(
            DossierSignal.dossier_id == dossier_id,
            DossierSignal.status == "new",
            DossierSignal.overall_score >= policy.signal_score_threshold,
        )
        .order_by(DossierSignal.updated_at, DossierSignal.id)
        .limit(500)
    ):
        candidates.append(
            AlertCandidate(
                "high_signal",
                dossier_id,
                "dossier_signal",
                signal_row.id,
                _occurrence(signal_row),
                "Señal prioritaria",
                f"Señal con score {signal_row.overall_score}.",
                f"/app/dossiers/{dossier_id}",
            )
        )
    for risk_row in db.session.scalars(
        select(RiskItem)
        .where(
            RiskItem.dossier_id == dossier_id,
            RiskItem.status.in_(("open", "monitoring")),
            func.coalesce(RiskItem.score_override, RiskItem.overall_score)
            >= policy.risk_score_threshold,
        )
        .order_by(RiskItem.updated_at, RiskItem.id)
        .limit(500)
    ):
        score = (
            risk_row.score_override
            if risk_row.score_override is not None
            else risk_row.overall_score
        )
        candidates.append(
            AlertCandidate(
                "high_risk",
                dossier_id,
                "risk",
                risk_row.id,
                _occurrence(risk_row),
                "Riesgo alto",
                f"{risk_row.title} alcanza score {score}.",
                f"/app/dossiers/{dossier_id}",
            )
        )
    today = now.astimezone(ZoneInfo(policy.timezone)).date()
    horizon = today + timedelta(days=policy.opportunity_deadline_days)
    for opportunity_row in db.session.scalars(
        select(Opportunity)
        .where(
            Opportunity.dossier_id == dossier_id,
            Opportunity.status.in_(("identified", "qualified", "pursuing")),
            Opportunity.deadline.is_not(None),
            Opportunity.deadline >= today,
            Opportunity.deadline <= horizon,
        )
        .order_by(Opportunity.deadline, Opportunity.id)
        .limit(500)
    ):
        assert opportunity_row.deadline is not None
        candidates.append(
            AlertCandidate(
                "opportunity_deadline",
                dossier_id,
                "opportunity",
                opportunity_row.id,
                f"deadline:{opportunity_row.deadline.isoformat()}",
                "Vence una oportunidad",
                f"{opportunity_row.title}: fecha límite {opportunity_row.deadline.isoformat()}.",
                f"/app/dossiers/{dossier_id}",
            )
        )
    meeting_horizon = now + timedelta(hours=policy.meeting_upcoming_hours)
    for meeting_row in db.session.scalars(
        select(Meeting)
        .where(
            Meeting.dossier_id == dossier_id,
            Meeting.status == "planned",
            Meeting.scheduled_at >= now,
            Meeting.scheduled_at <= meeting_horizon,
        )
        .order_by(Meeting.scheduled_at, Meeting.id)
        .limit(500)
    ):
        assert meeting_row.scheduled_at is not None
        candidates.append(
            AlertCandidate(
                "meeting_upcoming",
                dossier_id,
                "meeting",
                meeting_row.id,
                f"scheduled:{meeting_row.scheduled_at.astimezone(UTC).isoformat()}",
                "Reunión próxima",
                f"{meeting_row.title}: {meeting_row.scheduled_at.isoformat()}.",
                f"/app/dossiers/{dossier_id}",
            )
        )
    for report_row in db.session.scalars(
        select(Report)
        .where(Report.dossier_id == dossier_id, Report.status == "ready")
        .order_by(Report.updated_at, Report.id)
        .limit(500)
    ):
        candidates.append(
            AlertCandidate(
                "report_ready",
                dossier_id,
                "report",
                report_row.id,
                _occurrence(report_row),
                "Informe listo",
                f"{report_row.title} está listo para revisión.",
                f"/app/reports/{report_row.id}",
                report_row.requested_by_user_id,
            )
        )
    return candidates


def _global_candidates(now: datetime) -> list[AlertCandidate]:
    candidates: list[AlertCandidate] = []
    for connection_row in db.session.scalars(
        select(IntegrationConnection)
        .where(IntegrationConnection.status == "error")
        .order_by(IntegrationConnection.updated_at, IntegrationConnection.id)
        .limit(500)
    ):
        candidates.append(
            AlertCandidate(
                "failed_integration",
                None,
                "integration_connection",
                connection_row.id,
                _occurrence(connection_row),
                "Integración con error",
                f"La integración {connection_row.name} requiere revisión.",
                "/app/notifications",
            )
        )
    for outbox_row in db.session.scalars(
        select(IntegrationOutboxEvent)
        .where(IntegrationOutboxEvent.status == "failed")
        .order_by(IntegrationOutboxEvent.updated_at, IntegrationOutboxEvent.id)
        .limit(500)
    ):
        candidates.append(
            AlertCandidate(
                "failed_integration",
                None,
                "integration_outbox",
                outbox_row.id,
                _occurrence(outbox_row),
                "Entrega de integración fallida",
                "Una entrega agotó sus reintentos.",
                "/app/notifications",
            )
        )
    for job_row in db.session.scalars(
        select(BackgroundJob)
        .where(
            BackgroundJob.status == "failed",
            BackgroundJob.job_type != "notifications.evaluate_alerts",
        )
        .order_by(BackgroundJob.updated_at, BackgroundJob.id)
        .limit(500)
    ):
        candidates.append(
            AlertCandidate(
                "failed_job",
                job_row.dossier_id,
                "background_job",
                job_row.id,
                _occurrence(job_row),
                "Proceso en segundo plano fallido",
                f"El proceso {job_row.job_type} necesita atención.",
                "/app/notifications",
                job_row.requested_by_user_id,
            )
        )
    return candidates


def _recipients(dossier: StrategicDossier | None, candidate: AlertCandidate) -> list[uuid.UUID]:
    tenant_id = require_tenant_id()
    active = list(
        db.session.scalars(
            select(TenantMembership.user_id).where(
                TenantMembership.tenant_id == tenant_id, TenantMembership.status == "active"
            )
        )
    )
    active = [
        user_id
        for user_id in active
        if "notifications.read" in current_permissions(user_id, tenant_id)
    ]
    if dossier is None:
        if candidate.alert_type == "failed_job" and candidate.preferred_recipient in active:
            return [candidate.preferred_recipient]
        return [user_id for user_id in active if is_tenant_admin(db.session(), tenant_id, user_id)]
    if candidate.alert_type == "failed_job":
        preferred = candidate.preferred_recipient
        if preferred in active and dossier_accessible(
            db.session(), dossier, preferred, write=False
        ):
            return [preferred]
        return [user_id for user_id in active if is_tenant_admin(db.session(), tenant_id, user_id)]
    if candidate.alert_type == "report_ready":
        return [
            user_id
            for user_id in active
            if user_id != candidate.preferred_recipient
            and dossier_accessible(db.session(), dossier, user_id, write=False)
        ]
    return [
        user_id
        for user_id in active
        if dossier_accessible(db.session(), dossier, user_id, write=False)
    ]


def _quiet_end(policy: AlertPolicy, now: datetime) -> datetime | None:
    start, end = policy.quiet_hours_start, policy.quiet_hours_end
    if start is None or end is None:
        return None
    zone = ZoneInfo(policy.timezone)
    local = now.astimezone(zone)
    local_time = local.time().replace(tzinfo=None)
    quiet = (
        True
        if start == end
        else (start <= local_time < end if start < end else local_time >= start or local_time < end)
    )
    if not quiet:
        return None
    day = local.date() + timedelta(days=1 if start >= end and local_time >= start else 0)
    candidate = datetime.combine(day, end, tzinfo=zone).astimezone(UTC)
    return candidate if candidate > now else candidate + timedelta(days=1)


def _key(candidate: AlertCandidate) -> str:
    raw = ":".join(
        (
            candidate.alert_type,
            candidate.resource_type,
            str(candidate.resource_id),
            candidate.occurrence,
        )
    )
    return f"alert:{candidate.alert_type}:{hashlib.sha256(raw.encode()).hexdigest()}"


def evaluate_alerts(*, now: datetime | None = None) -> dict[str, int]:
    """Evaluate and bundle all seven alert types once for the active tenant."""

    tenant_id = require_tenant_id()
    current = now or datetime.now(UTC)
    db.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:slot,0))"),
        {"slot": f"alerts:{tenant_id}"},
    )
    tenant_policy = effective_alert_policy(None)
    dossiers = list(
        db.session.scalars(
            select(StrategicDossier)
            .where(StrategicDossier.status.in_(("draft", "active", "paused")))
            .order_by(StrategicDossier.updated_at, StrategicDossier.id)
            .limit(500)
        )
    )
    dossier_by_id = {row.id: row for row in dossiers}
    pairs: list[tuple[AlertPolicy, AlertCandidate]] = []
    for dossier in dossiers:
        policy = effective_alert_policy(dossier.id)
        pairs.extend(
            (policy, candidate) for candidate in _dossier_candidates(dossier, policy, current)
        )
    for candidate in _global_candidates(current):
        policy = (
            effective_alert_policy(candidate.dossier_id) if candidate.dossier_id else tenant_policy
        )
        pairs.append((policy, candidate))

    groups: dict[tuple[uuid.UUID, uuid.UUID, str, uuid.UUID | None], list[AlertCandidate]] = (
        defaultdict(list)
    )
    suppressed = 0
    for policy, candidate in pairs:
        if not policy.enabled_types.get(candidate.alert_type, False):
            continue
        target_dossier = dossier_by_id.get(candidate.dossier_id) if candidate.dossier_id else None
        for recipient in _recipients(target_dossier, candidate):
            if candidate.alert_type == "report_ready" and db.session.scalar(
                select(Notification.id).where(
                    Notification.user_id == recipient,
                    Notification.report_id == candidate.resource_id,
                    Notification.notification_type.in_(("report.ready", "alert.report_ready")),
                )
            ):
                suppressed += 1
                continue
            occurrence_key = _key(candidate)
            if db.session.scalar(
                select(AlertEvaluation.id).where(
                    AlertEvaluation.recipient_user_id == recipient,
                    AlertEvaluation.occurrence_key == occurrence_key,
                )
            ):
                suppressed += 1
                continue
            cutoff = current - timedelta(minutes=policy.cooldown_minutes)
            recent = db.session.scalar(
                select(AlertEvaluation.id)
                .where(
                    AlertEvaluation.recipient_user_id == recipient,
                    AlertEvaluation.alert_type == candidate.alert_type,
                    AlertEvaluation.resource_id == candidate.resource_id,
                    AlertEvaluation.decision == "emitted",
                    AlertEvaluation.evaluated_at > cutoff,
                )
                .limit(1)
            )
            if recent is not None:
                db.session.add(
                    AlertEvaluation(
                        tenant_id=tenant_id,
                        policy_id=policy.id,
                        dossier_id=candidate.dossier_id,
                        recipient_user_id=recipient,
                        alert_type=candidate.alert_type,
                        severity=policy.severity_map.get(
                            candidate.alert_type, DEFAULT_SEVERITY_MAP[candidate.alert_type]
                        ),
                        decision="cooldown",
                        resource_type=candidate.resource_type,
                        resource_id=candidate.resource_id,
                        occurrence_key=occurrence_key,
                        evaluated_at=current,
                        cooldown_until=current + timedelta(minutes=policy.cooldown_minutes),
                        evaluation_metadata={"reason": "cooldown"},
                    )
                )
                suppressed += 1
                continue
            groups[(policy.id, recipient, candidate.alert_type, candidate.dossier_id)].append(
                candidate
            )

    created_jobs: list[CreatedNotification] = []
    emitted = 0
    for (policy_id, recipient, alert_type, dossier_id), candidates in groups.items():
        resolved_policy = db.session.get(AlertPolicy, policy_id)
        assert resolved_policy is not None
        severity = resolved_policy.severity_map.get(alert_type, DEFAULT_SEVERITY_MAP[alert_type])
        first = candidates[0]
        count = len(candidates)
        body = (
            first.detail if count == 1 else f"{count} elementos requieren atención. {first.detail}"
        )
        bundle_hash = hashlib.sha256(
            "|".join(sorted(_key(item) for item in candidates)).encode()
        ).hexdigest()
        created = create_notification(
            user_id=recipient,
            notification_type=f"alert.{alert_type}",
            severity=severity,
            title=first.title if count == 1 else f"{first.title} · {count}",
            body=body,
            dedupe_key=f"alert-bundle:{bundle_hash}",
            link=first.link,
            dossier_id=dossier_id,
            resource_type=first.resource_type,
            resource_id=first.resource_id,
            now=current,
        )
        quiet_end = _quiet_end(resolved_policy, current)
        if created.email_job is not None and quiet_end is not None:
            created.email_job.not_before = max(created.email_job.not_before or quiet_end, quiet_end)
        created_jobs.append(created)
        for candidate in candidates:
            db.session.add(
                AlertEvaluation(
                    tenant_id=tenant_id,
                    policy_id=resolved_policy.id,
                    dossier_id=dossier_id,
                    recipient_user_id=recipient,
                    notification_id=created.notification.id,
                    alert_type=alert_type,
                    severity=severity,
                    decision="emitted",
                    resource_type=candidate.resource_type,
                    resource_id=candidate.resource_id,
                    occurrence_key=_key(candidate),
                    evaluated_at=current,
                    cooldown_until=current + timedelta(minutes=resolved_policy.cooldown_minutes),
                    evaluation_metadata={"bundle_size": count},
                )
            )
            emitted += 1
    db.session.commit()
    from opn_oracle.reporting.notifications import publish_notification_job

    for created in created_jobs:
        publish_notification_job(created)
    return {
        "candidates": len(pairs),
        "emitted": emitted,
        "suppressed": suppressed,
        "bundles": len(groups),
    }
