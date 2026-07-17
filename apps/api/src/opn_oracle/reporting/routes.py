"""APIs for reports, notifications, alert policies and secure exports."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apiflask import APIBlueprint
from flask import Response, current_app, g, request, session
from flask_login import current_user
from sqlalchemy import func, select, update

from opn_oracle.auth.permissions import current_permissions, require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db
from opn_oracle.oracle.competitive_procurement import (
    COMPETITIVE_PROCUREMENT_JOB,
    COMPETITIVE_PROCUREMENT_TEMPLATE,
)
from opn_oracle.oracle.models import Report, StrategicDossier
from opn_oracle.oracle.policy import dossier_access_clause, dossier_accessible
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.reporting.alerts import (
    AlertPolicyError,
    create_dossier_override,
    dossier_alert_override,
    effective_alert_policy,
    tenant_alert_policy,
    validate_policy_maps,
)
from opn_oracle.reporting.artifacts import (
    ArtifactAccessError,
    artifact_fingerprint,
    create_download_signature,
    export_artifact,
    read_artifact,
    report_artifact,
    verify_download_signature,
)
from opn_oracle.reporting.exports import (
    DATASETS,
    ExportConflictError,
    ExportError,
    create_export_request,
    serialize_export,
)
from opn_oracle.reporting.models import (
    AlertPolicy,
    DataExport,
    Notification,
    NotificationPreference,
    ReportArtifact,
)
from opn_oracle.reporting.notifications import (
    LOCKED_NOTIFICATION_TYPES,
    NotificationError,
    serialize_notification,
    serialize_preference,
    sync_digest_schedule,
    unread_count,
)
from opn_oracle.reporting.registry import ReportTemplateRegistry
from opn_oracle.reporting.service import (
    ReportConflictError,
    ReportWorkflowError,
    create_human_revision,
    create_report_request,
    publish_report,
    review_report,
    serialize_report,
)

bp = APIBlueprint("reporting", __name__, url_prefix="/api/v1", tag="Reporting")


class VersionConflictError(ReportWorkflowError):
    pass


def _payload() -> dict[str, Any]:
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


def _page() -> tuple[int, int]:
    try:
        page = max(1, int(request.args.get("page[number]", "1")))
        size = min(100, max(1, int(request.args.get("page[size]", "25"))))
    except ValueError as error:
        raise ReportWorkflowError("Paginación no válida.") from error
    return page, size


def _dossier(dossier_id: uuid.UUID, *, write: bool) -> StrategicDossier | None:
    dossier = db.session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == g.active_tenant_id,
        )
    )
    if dossier is None or not dossier_accessible(
        db.session(), dossier, current_user.id, write=write
    ):
        return None
    return dossier


def _report(report_id: uuid.UUID, *, write: bool) -> Report | None:
    row = db.session.scalar(
        select(Report).where(Report.id == report_id, Report.tenant_id == g.active_tenant_id)
    )
    if row is None or _dossier(row.dossier_id, write=write) is None:
        return None
    return row


def _expected_version(payload: dict[str, Any], current: int) -> None:
    raw = payload.get("version")
    try:
        expected = int(cast(Any, raw))
    except (TypeError, ValueError) as error:
        raise ReportWorkflowError("version es obligatoria.") from error
    if expected != current:
        raise VersionConflictError("El recurso fue modificado por otro proceso.")


@bp.get("/report-templates")
@require_permission("report.read")
def list_report_templates() -> Any:
    return {
        "items": [item.public_dict() for item in ReportTemplateRegistry().list()],
        "capabilities": {"pdf": bool(current_app.extensions["pdf_renderer"].enabled)},
    }


@bp.get("/reports")
@require_permission("report.read")
def list_reports_global() -> Any:
    try:
        page, size = _page()
    except ReportWorkflowError as error:
        return problem_response(422, detail=str(error), code="validation_error")
    statement = (
        select(Report)
        .join(StrategicDossier, StrategicDossier.id == Report.dossier_id)
        .where(
            dossier_access_clause(
                tenant_id=g.active_tenant_id,
                user_id=current_user.id,
            )
        )
    )
    count_statement = (
        select(func.count(Report.id))
        .join(StrategicDossier, StrategicDossier.id == Report.dossier_id)
        .where(
            dossier_access_clause(
                tenant_id=g.active_tenant_id,
                user_id=current_user.id,
            )
        )
    )
    status = request.args.get("filter[status]")
    template = request.args.get("filter[template]")
    search = request.args.get("filter[search]", "").strip()
    criteria = []
    if status:
        criteria.append(Report.status == status)
    if template:
        criteria.append(Report.template_key == template)
    if search:
        criteria.append(Report.title.ilike(f"%{search[:200]}%"))
    if criteria:
        statement = statement.where(*criteria)
        count_statement = count_statement.where(*criteria)
    rows = list(
        db.session.scalars(
            statement.order_by(Report.created_at.desc()).offset((page - 1) * size).limit(size)
        )
    )
    return {
        "data": [serialize_report(row) for row in rows],
        "meta": {"page": page, "size": size, "total": int(db.session.scalar(count_statement) or 0)},
    }


@bp.post("/reports/<uuid:report_id>/retry")
@require_permission("report.generate")
def retry_report(report_id: uuid.UUID) -> Any:
    report = _report(report_id, write=True)
    if report is None:
        return problem_response(404, detail="Informe no disponible.", code="not_found")
    if report.status != "failed":
        return problem_response(
            409, detail="Solo se reintentan informes fallidos.", code="invalid_state"
        )
    dossier = _dossier(report.dossier_id, write=True)
    assert dossier is not None
    try:
        retried, job, created = create_report_request(
            dossier,
            template_key=report.template_key,
            options=dict(report.options),
            requested_by_user_id=current_user.id,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
            parent_report_id=report.id,
            job_type=(
                COMPETITIVE_PROCUREMENT_JOB
                if report.template_key == COMPETITIVE_PROCUREMENT_TEMPLATE
                else "oracle.report.generate"
            ),
        )
    except ReportConflictError as error:
        db.session.rollback()
        return problem_response(409, detail=str(error), code="idempotency_conflict")
    except (ReportWorkflowError, KeyError) as error:
        db.session.rollback()
        return problem_response(422, detail=str(error), code="validation_error")
    return {
        "report": serialize_report(retried),
        "job_id": str(job.id),
        "replayed": not created,
    }, (202 if created else 200)


@bp.post("/reports/<uuid:report_id>/revisions")
@require_permission("report.review")
def create_revision(report_id: uuid.UUID) -> Any:
    report = _report(report_id, write=True)
    if report is None:
        return problem_response(404, detail="Informe no disponible.", code="not_found")
    payload = _payload()
    try:
        _expected_version(payload, report.version)
        content = payload.get("content")
        if not isinstance(content, dict):
            raise ReportWorkflowError("content debe ser un objeto ReportOutput.")
        create_human_revision(
            report,
            payload=content,
            user_id=current_user.id,
            change_summary=str(payload.get("change_summary", "")),
        )
    except VersionConflictError as error:
        db.session.rollback()
        return problem_response(409, detail=str(error), code="version_conflict")
    except (ReportWorkflowError, ValueError) as error:
        db.session.rollback()
        return problem_response(422, detail=str(error), code="validation_error")
    return serialize_report(report, detail=True), 201


@bp.post("/reports/<uuid:report_id>/reviews")
@require_permission("report.review")
def create_report_review(report_id: uuid.UUID) -> Any:
    report = _report(report_id, write=True)
    if report is None:
        return problem_response(404, detail="Informe no disponible.", code="not_found")
    payload = _payload()
    try:
        _expected_version(payload, report.version)
        revision_id = uuid.UUID(str(payload.get("revision_id", "")))
        review = review_report(
            report,
            revision_id=revision_id,
            decision=str(payload.get("decision", "")),
            comment=str(payload.get("comment", "")),
            reviewer_user_id=current_user.id,
        )
    except VersionConflictError as error:
        db.session.rollback()
        return problem_response(409, detail=str(error), code="version_conflict")
    except (ValueError, ReportWorkflowError) as error:
        db.session.rollback()
        return problem_response(422, detail=str(error), code="validation_error")
    return {
        "review_id": str(review.id),
        "report": serialize_report(report, detail=True),
    }, 201


@bp.post("/reports/<uuid:report_id>/publish")
@require_permission("report.publish")
def publish_report_route(report_id: uuid.UUID) -> Any:
    report = _report(report_id, write=True)
    if report is None:
        return problem_response(404, detail="Informe no disponible.", code="not_found")
    try:
        _expected_version(_payload(), report.version)
        report = publish_report(report, publisher_user_id=current_user.id)
    except ReportWorkflowError as error:
        db.session.rollback()
        return problem_response(409, detail=str(error), code="invalid_state")
    return serialize_report(report, detail=True)


@bp.post("/reports/<uuid:report_id>/artifacts/<uuid:artifact_id>/download-link")
@require_permission("report.read")
def report_download_link(report_id: uuid.UUID, artifact_id: uuid.UUID) -> Any:
    report = _report(report_id, write=False)
    artifact = db.session.scalar(
        select(ReportArtifact).where(
            ReportArtifact.id == artifact_id,
            ReportArtifact.report_id == report_id,
        )
    )
    if report is None or artifact is None or artifact.status != "available":
        return problem_response(404, detail="Artefacto no disponible.", code="not_found")
    try:
        item = report_artifact(artifact)
        expires, signature = create_download_signature(
            kind="report",
            artifact_id=artifact.id,
            artifact_fingerprint=artifact_fingerprint(item),
            tenant_id=g.active_tenant_id,
            user_id=current_user.id,
            session_id=_active_session_id(),
        )
    except ArtifactAccessError:
        return problem_response(404, detail="Artefacto no disponible.", code="not_found")
    return {
        "url": (
            f"/api/v1/report-artifacts/{artifact.id}/download"
            f"?expires={expires}&signature={signature}"
        ),
        "expires_at": datetime.fromtimestamp(expires, UTC).isoformat(),
    }


def _signed_values() -> tuple[int, str]:
    try:
        return int(request.args.get("expires", "0")), request.args.get("signature", "")
    except ValueError as error:
        raise ArtifactAccessError("Enlace de descarga no válido.") from error


def _active_session_id() -> uuid.UUID:
    try:
        return uuid.UUID(str(session["user_session_id"]))
    except (KeyError, ValueError) as error:
        raise ArtifactAccessError("La sesión de descarga no es válida.") from error


def _download_response(payload: bytes, media_type: str, filename: str) -> Response:
    return Response(
        payload,
        headers={
            "Content-Type": media_type,
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
        },
    )


@bp.get("/report-artifacts/<uuid:artifact_id>/download")
@require_permission("report.read")
def download_report_artifact(artifact_id: uuid.UUID) -> Any:
    artifact = db.session.scalar(
        select(ReportArtifact).where(
            ReportArtifact.id == artifact_id,
            ReportArtifact.tenant_id == g.active_tenant_id,
        )
    )
    report = _report(artifact.report_id, write=False) if artifact is not None else None
    if artifact is None or report is None:
        return problem_response(404, detail="Artefacto no disponible.", code="not_found")
    try:
        expires, signature = _signed_values()
        verify_download_signature(
            kind="report",
            artifact_id=artifact.id,
            artifact_fingerprint=artifact_fingerprint(report_artifact(artifact)),
            tenant_id=g.active_tenant_id,
            user_id=current_user.id,
            session_id=_active_session_id(),
            expires=expires,
            signature=signature,
        )
        item = report_artifact(artifact)
        payload = read_artifact(item)
    except ArtifactAccessError as error:
        return problem_response(403, detail=str(error), code="download_denied")
    return _download_response(payload, item.media_type, item.filename)


@bp.get("/notifications")
@require_permission("notifications.read")
def list_notifications() -> Any:
    try:
        page, size = _page()
    except ReportWorkflowError as error:
        return problem_response(422, detail=str(error), code="validation_error")
    now = datetime.now(UTC)
    criteria = (
        Notification.user_id == current_user.id,
        Notification.in_app_visible.is_(True),
        Notification.dismissed_at.is_(None),
        (Notification.expires_at.is_(None) | (Notification.expires_at > now)),
    )
    rows = list(
        db.session.scalars(
            select(Notification)
            .where(*criteria)
            .order_by(Notification.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    )
    total = int(db.session.scalar(select(func.count(Notification.id)).where(*criteria)) or 0)
    return {
        "data": [serialize_notification(row) for row in rows],
        "meta": {
            "page": page,
            "size": size,
            "total": total,
            "unread_count": unread_count(current_user.id),
        },
    }


def _own_notification(notification_id: uuid.UUID) -> Notification | None:
    return db.session.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
            Notification.tenant_id == g.active_tenant_id,
            Notification.in_app_visible.is_(True),
        )
    )


@bp.post("/notifications/<uuid:notification_id>/read")
@require_permission("notifications.read")
def read_notification(notification_id: uuid.UUID) -> Any:
    row = _own_notification(notification_id)
    if row is None:
        return problem_response(404, detail="Notificación no disponible.", code="not_found")
    row.read_at = row.read_at or datetime.now(UTC)
    db.session.commit()
    return serialize_notification(row)


@bp.post("/notifications/read-all")
@require_permission("notifications.read")
def read_all_notifications() -> Any:
    result = db.session.execute(
        update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.in_app_visible.is_(True),
            Notification.read_at.is_(None),
            Notification.dismissed_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    db.session.commit()
    return {"updated": int(cast(Any, result).rowcount or 0), "unread_count": 0}


@bp.post("/notifications/<uuid:notification_id>/dismiss")
@require_permission("notifications.read")
def dismiss_notification(notification_id: uuid.UUID) -> Any:
    row = _own_notification(notification_id)
    if row is None:
        return problem_response(404, detail="Notificación no disponible.", code="not_found")
    row.dismissed_at = row.dismissed_at or datetime.now(UTC)
    db.session.commit()
    return serialize_notification(row)


def _parse_time(value: Any, *, required: bool) -> time | None:
    if value in (None, ""):
        if required:
            raise NotificationError("La hora es obligatoria.")
        return None
    try:
        return time.fromisoformat(str(value))
    except ValueError as error:
        raise NotificationError("Hora no válida.") from error


def _preference(notification_type: str) -> NotificationPreference | None:
    return db.session.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == current_user.id,
            NotificationPreference.notification_type == notification_type,
        )
    )


@bp.get("/notification-preferences")
@require_permission("notifications.manage")
def get_notification_preferences() -> Any:
    rows = list(
        db.session.scalars(
            select(NotificationPreference)
            .where(NotificationPreference.user_id == current_user.id)
            .order_by(NotificationPreference.notification_type)
        )
    )
    return {"items": [serialize_preference(row) for row in rows]}


@bp.patch("/notification-preferences")
@require_permission("notifications.manage")
def patch_notification_preferences() -> Any:
    payload = _payload()
    notification_type = str(payload.get("notification_type", "*")).strip()[:80]
    if not notification_type:
        return problem_response(
            422, detail="notification_type es obligatorio.", code="validation_error"
        )
    row = _preference(notification_type)
    try:
        channels = payload.get("channels", {"in_app": True, "email": False})
        if not isinstance(channels, dict) or set(channels) != {"in_app", "email"}:
            raise NotificationError("channels debe definir in_app y email.")
        if not all(isinstance(channels[key], bool) for key in ("in_app", "email")):
            raise NotificationError("Los canales deben tener valores booleanos.")
        channels = {"in_app": channels["in_app"], "email": channels["email"]}
        locked = notification_type in LOCKED_NOTIFICATION_TYPES
        if locked:
            channels = {"in_app": True, "email": True}
        cadence = str(payload.get("digest_cadence", "instant"))
        if cadence not in {"instant", "daily", "weekly", "off"}:
            raise NotificationError("digest_cadence no es válido.")
        if locked:
            cadence = "instant"
        timezone = str(payload.get("timezone", "Europe/Madrid"))
        ZoneInfo(timezone)
        weekday_raw = payload.get("weekday")
        weekday = int(weekday_raw) if weekday_raw is not None else None
        if cadence == "weekly" and weekday not in range(7):
            raise NotificationError("weekday es obligatorio entre 0 y 6 para digest semanal.")
        if cadence != "weekly":
            weekday = None
        if row is not None:
            _expected_version(payload, row.version)
        if row is None:
            row = NotificationPreference(
                tenant_id=g.active_tenant_id,
                user_id=current_user.id,
                notification_type=notification_type,
            )
            db.session.add(row)
        row.channels = channels
        row.digest_cadence = cadence
        row.timezone = timezone
        local_time = _parse_time(payload.get("local_time", "08:00"), required=True)
        assert local_time is not None
        row.local_time = local_time
        row.weekday = weekday
        row.quiet_hours_start = _parse_time(payload.get("quiet_hours_start"), required=False)
        row.quiet_hours_end = _parse_time(payload.get("quiet_hours_end"), required=False)
        if (row.quiet_hours_start is None) != (row.quiet_hours_end is None):
            raise NotificationError("Las horas silenciosas deben definir inicio y fin.")
        row.minimum_severity = str(payload.get("minimum_severity", "info"))
        if row.minimum_severity not in {"info", "success", "warning", "critical"}:
            raise NotificationError("minimum_severity no es válida.")
        row.security_locked = locked
        row.version = (row.version or 0) + 1 if row.id else 1
        db.session.flush()
        sync_digest_schedule(row)
        append_audit_event(
            db.session,
            action="notification_preferences.updated",
            resource_type="notification_preference",
            resource_id=row.id,
            result="success",
            metadata={"notification_type": notification_type, "cadence": cadence},
        )
        db.session.commit()
    except VersionConflictError as error:
        db.session.rollback()
        return problem_response(409, detail=str(error), code="version_conflict")
    except (NotificationError, ReportWorkflowError, ValueError, ZoneInfoNotFoundError) as error:
        db.session.rollback()
        return problem_response(422, detail=str(error), code="validation_error")
    return serialize_preference(row)


@bp.get("/dossiers/<uuid:dossier_id>/alert-policy")
@require_permission("dossier.read")
def get_alert_policy(dossier_id: uuid.UUID) -> Any:
    if _dossier(dossier_id, write=False) is None:
        return problem_response(404, detail="Expediente no disponible.", code="not_found")
    override = dossier_alert_override(dossier_id)
    policy = override or effective_alert_policy(None)
    db.session.commit()
    return _serialize_alert_policy(policy, dossier_id=dossier_id, inherited=override is None)


def _serialize_alert_policy(
    policy: AlertPolicy,
    *,
    dossier_id: uuid.UUID | None = None,
    inherited: bool = False,
) -> dict[str, Any]:
    return {
        "id": str(policy.id),
        "scope": policy.scope,
        "inherited": inherited,
        "dossier_id": str(dossier_id or policy.dossier_id)
        if (dossier_id or policy.dossier_id)
        else None,
        "signal_score_threshold": policy.signal_score_threshold,
        "risk_score_threshold": policy.risk_score_threshold,
        "opportunity_deadline_days": policy.opportunity_deadline_days,
        "meeting_upcoming_hours": policy.meeting_upcoming_hours,
        "cooldown_minutes": policy.cooldown_minutes,
        "enabled_types": policy.enabled_types,
        "severity_map": policy.severity_map,
        "quiet_hours_start": policy.quiet_hours_start.isoformat()
        if policy.quiet_hours_start
        else None,
        "quiet_hours_end": policy.quiet_hours_end.isoformat() if policy.quiet_hours_end else None,
        "timezone": policy.timezone,
        "version": policy.version,
    }


@bp.patch("/dossiers/<uuid:dossier_id>/alert-policy")
@require_permission("dossier.write")
def patch_alert_policy(dossier_id: uuid.UUID) -> Any:
    if _dossier(dossier_id, write=True) is None:
        return problem_response(404, detail="Expediente no disponible.", code="not_found")
    policy = dossier_alert_override(dossier_id)
    payload = _payload()
    try:
        if policy is None:
            inherited = effective_alert_policy(None)
            _expected_version(payload, inherited.version)
            policy = create_dossier_override(dossier_id)
        else:
            _expected_version(payload, policy.version)
        _apply_alert_policy(policy, payload)
        db.session.commit()
    except VersionConflictError as error:
        db.session.rollback()
        return problem_response(409, detail=str(error), code="version_conflict")
    except (
        ValueError,
        AlertPolicyError,
        NotificationError,
        ReportWorkflowError,
        ZoneInfoNotFoundError,
    ) as error:
        db.session.rollback()
        return problem_response(422, detail=str(error), code="validation_error")
    return _serialize_alert_policy(policy)


def _apply_alert_policy(policy: AlertPolicy, payload: dict[str, Any]) -> None:
    for key in (
        "signal_score_threshold",
        "risk_score_threshold",
        "opportunity_deadline_days",
        "meeting_upcoming_hours",
        "cooldown_minutes",
    ):
        if key in payload:
            setattr(policy, key, int(payload[key]))
    if not 0 <= policy.signal_score_threshold <= 100:
        raise AlertPolicyError("signal_score_threshold debe estar entre 0 y 100.")
    if not 0 <= policy.risk_score_threshold <= 100:
        raise AlertPolicyError("risk_score_threshold debe estar entre 0 y 100.")
    if not 0 <= policy.opportunity_deadline_days <= 365:
        raise AlertPolicyError("opportunity_deadline_days debe estar entre 0 y 365.")
    if not 1 <= policy.meeting_upcoming_hours <= 720:
        raise AlertPolicyError("meeting_upcoming_hours debe estar entre 1 y 720.")
    if not 0 <= policy.cooldown_minutes <= 10080:
        raise AlertPolicyError("cooldown_minutes debe estar entre 0 y 10080.")
    enabled_input = payload.get("enabled_types", {})
    severity_input = payload.get("severity_map", {})
    if not isinstance(enabled_input, dict) or not isinstance(severity_input, dict):
        raise AlertPolicyError("enabled_types y severity_map deben ser objetos.")
    enabled, severity = validate_policy_maps(
        {**policy.enabled_types, **enabled_input},
        {**policy.severity_map, **severity_input},
    )
    policy.enabled_types, policy.severity_map = enabled, severity
    if "timezone" in payload:
        ZoneInfo(str(payload["timezone"]))
        policy.timezone = str(payload["timezone"])
    if "quiet_hours_start" in payload or "quiet_hours_end" in payload:
        policy.quiet_hours_start = _parse_time(payload.get("quiet_hours_start"), required=False)
        policy.quiet_hours_end = _parse_time(payload.get("quiet_hours_end"), required=False)
    if (policy.quiet_hours_start is None) != (policy.quiet_hours_end is None):
        raise AlertPolicyError("Las horas silenciosas deben definir inicio y fin.")
    policy.version += 1


@bp.get("/alert-policy")
@require_permission("tenant.settings.manage")
def get_tenant_alert_policy() -> Any:
    policy = tenant_alert_policy(create=True)
    assert policy is not None
    db.session.commit()
    return _serialize_alert_policy(policy)


@bp.patch("/alert-policy")
@require_permission("tenant.settings.manage")
def patch_tenant_alert_policy() -> Any:
    policy = tenant_alert_policy(create=True)
    assert policy is not None
    payload = _payload()
    try:
        _expected_version(payload, policy.version)
        _apply_alert_policy(policy, payload)
        db.session.commit()
    except VersionConflictError as error:
        db.session.rollback()
        return problem_response(409, detail=str(error), code="version_conflict")
    except (ValueError, AlertPolicyError, ReportWorkflowError, ZoneInfoNotFoundError) as error:
        db.session.rollback()
        return problem_response(422, detail=str(error), code="validation_error")
    return _serialize_alert_policy(policy)


@bp.get("/exports")
@require_permission("export.create")
def list_exports() -> Any:
    try:
        page, size = _page()
    except ReportWorkflowError as error:
        return problem_response(422, detail=str(error), code="validation_error")
    permissions = current_permissions(current_user.id, g.active_tenant_id)
    allowed_datasets = tuple(
        key for key, spec in DATASETS.items() if spec.permission in permissions
    )
    criteria = (
        DataExport.requested_by_user_id == current_user.id,
        DataExport.dataset.in_(allowed_datasets),
    )
    rows = list(
        db.session.scalars(
            select(DataExport)
            .where(*criteria)
            .order_by(DataExport.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    )
    total = int(db.session.scalar(select(func.count(DataExport.id)).where(*criteria)) or 0)
    return {
        "data": [serialize_export(row) for row in rows],
        "meta": {"page": page, "size": size, "total": total},
    }


@bp.post("/exports")
@require_permission("export.create")
def create_export() -> Any:
    payload = _payload()
    dataset = str(payload.get("dataset", ""))
    spec = DATASETS.get(dataset)
    if spec is None or spec.permission not in current_permissions(
        current_user.id, g.active_tenant_id
    ):
        return problem_response(403, detail="Dataset no autorizado.", code="permission_denied")
    dossier_id = None
    if payload.get("dossier_id"):
        try:
            dossier_id = uuid.UUID(str(payload["dossier_id"]))
        except ValueError:
            return problem_response(422, detail="dossier_id no válido.", code="validation_error")
        if _dossier(dossier_id, write=False) is None:
            return problem_response(404, detail="Expediente no disponible.", code="not_found")
    try:
        raw_columns, raw_filters = payload.get("columns"), payload.get("filters")
        export_columns: list[Any] = raw_columns if isinstance(raw_columns, list) else []
        export_filters: dict[str, Any] = raw_filters if isinstance(raw_filters, dict) else {}
        row, job, created = create_export_request(
            dataset=dataset,
            columns=export_columns,
            filters=export_filters,
            dossier_id=dossier_id,
            requested_by_user_id=current_user.id,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
    except ExportConflictError as error:
        db.session.rollback()
        return problem_response(409, detail=str(error), code="idempotency_conflict")
    except ExportError as error:
        db.session.rollback()
        return problem_response(422, detail=str(error), code="validation_error")
    return {
        "export": serialize_export(row),
        "job_id": str(job.id),
        "replayed": not created,
    }, (202 if created else 200)


def _own_export(export_id: uuid.UUID) -> DataExport | None:
    row = db.session.scalar(
        select(DataExport).where(
            DataExport.id == export_id,
            DataExport.requested_by_user_id == current_user.id,
        )
    )
    if row is None:
        return None
    spec = DATASETS.get(row.dataset)
    permissions = current_permissions(current_user.id, g.active_tenant_id)
    return row if spec is not None and spec.permission in permissions else None


@bp.get("/exports/<uuid:export_id>")
@require_permission("export.create")
def get_export(export_id: uuid.UUID) -> Any:
    row = _own_export(export_id)
    if row is None:
        return problem_response(404, detail="Exportación no disponible.", code="not_found")
    return serialize_export(row)


@bp.post("/exports/<uuid:export_id>/download-link")
@require_permission("export.create")
def export_download_link(export_id: uuid.UUID) -> Any:
    row = _own_export(export_id)
    if row is None or row.status != "ready" or row.expires_at is None:
        return problem_response(404, detail="Exportación no disponible.", code="not_found")
    if row.expires_at <= datetime.now(UTC):
        row.status = "expired"
        row.version += 1
        db.session.commit()
        return problem_response(410, detail="La exportación ha caducado.", code="expired")
    try:
        item = export_artifact(row)
        expires, signature = create_download_signature(
            kind="export",
            artifact_id=row.id,
            artifact_fingerprint=artifact_fingerprint(item),
            tenant_id=g.active_tenant_id,
            user_id=current_user.id,
            session_id=_active_session_id(),
        )
    except ArtifactAccessError:
        return problem_response(404, detail="Exportación no disponible.", code="not_found")
    return {
        "url": (
            f"/api/v1/export-artifacts/{row.id}/download?expires={expires}&signature={signature}"
        ),
        "expires_at": datetime.fromtimestamp(expires, UTC).isoformat(),
    }


@bp.get("/export-artifacts/<uuid:export_id>/download")
@require_permission("export.create")
def download_export_artifact(export_id: uuid.UUID) -> Any:
    row = _own_export(export_id)
    if row is None:
        return problem_response(404, detail="Exportación no disponible.", code="not_found")
    try:
        if row.expires_at is None or row.expires_at <= datetime.now(UTC):
            raise ArtifactAccessError("La exportación ha caducado.")
        expires, signature = _signed_values()
        verify_download_signature(
            kind="export",
            artifact_id=row.id,
            artifact_fingerprint=artifact_fingerprint(export_artifact(row)),
            tenant_id=g.active_tenant_id,
            user_id=current_user.id,
            session_id=_active_session_id(),
            expires=expires,
            signature=signature,
        )
        item = export_artifact(row)
        payload = read_artifact(item)
    except ArtifactAccessError as error:
        return problem_response(403, detail=str(error), code="download_denied")
    return _download_response(payload, item.media_type, item.filename)
