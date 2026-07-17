"""Tenant-scoped polling, cancellation and retry API for durable jobs."""

from __future__ import annotations

import uuid
from typing import Any

from apiflask import APIBlueprint
from flask import g, request
from flask_login import current_user
from sqlalchemy import func, or_, select

from opn_oracle.auth.permissions import current_permissions, require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.common.request_context import get_correlation_id, get_request_id
from opn_oracle.extensions import db
from opn_oracle.jobs.service import prepare_retry, publish_job, request_cancel, serialize_job
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.oracle.models import StrategicDossier
from opn_oracle.oracle.policy import dossier_access_clause, dossier_accessible, is_tenant_admin
from opn_oracle.platform.audit import append_audit_event

bp = APIBlueprint("jobs", __name__, url_prefix="/api/v1/jobs", tag="Trabajos")
JOB_CONTROL_PERMISSIONS = {
    "oracle.signal.sync_monitor": "signal.review",
    "oracle.signal.triage": "signal.review",
    "oracle.memory.refresh": "dossier.write",
    "oracle.report.generate": "report.generate",
    "oracle.procurement_document_report.generate": "report.generate",
    "oracle.competitive_procurement_report.generate": "report.generate",
    "oracle.entity_dossier_report.generate": "report.generate",
    "oracle.document.process": "dossier.write",
    "notifications.send_email": "tenant.users.manage",
    "maintenance.weekly_digest": "tenant.settings.manage",
}


def _job_or_404(job_id: uuid.UUID, *, write: bool = False) -> BackgroundJob | None:
    session = db.session()
    job = db.session.scalar(
        select(BackgroundJob).where(
            BackgroundJob.id == job_id,
            BackgroundJob.tenant_id == g.active_tenant_id,
        )
    )
    if job is None:
        return None
    if is_tenant_admin(session, g.active_tenant_id, current_user.id):
        return job
    if write and JOB_CONTROL_PERMISSIONS.get(job.job_type) not in current_permissions(
        current_user.id, g.active_tenant_id
    ):
        return None
    if job.requested_by_user_id == current_user.id:
        return job
    if job.dossier_id is None:
        return None
    dossier = db.session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == job.dossier_id,
            StrategicDossier.tenant_id == g.active_tenant_id,
        )
    )
    if dossier is None or not dossier_accessible(session, dossier, current_user.id, write=write):
        return None
    return job


def _expected_version() -> int | None:
    raw = request.headers.get("If-Match", "").removeprefix('W/"').removesuffix('"')
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 1 else None


@bp.get("")
@require_permission("dossier.read")
def jobs_list() -> Any:
    session = db.session()
    try:
        page = max(1, int(request.args.get("page[number]", "1")))
        size = min(100, max(1, int(request.args.get("page[size]", "25"))))
    except ValueError:
        return problem_response(422, detail="Paginación no válida.", code="validation_error")
    criteria = [BackgroundJob.tenant_id == g.active_tenant_id]
    if not is_tenant_admin(session, g.active_tenant_id, current_user.id):
        dossier_ids = select(StrategicDossier.id).where(
            dossier_access_clause(tenant_id=g.active_tenant_id, user_id=current_user.id)
        )
        criteria.append(
            or_(
                BackgroundJob.requested_by_user_id == current_user.id,
                BackgroundJob.dossier_id.in_(dossier_ids),
            )
        )
    if status := request.args.get("filter[status]"):
        criteria.append(BackgroundJob.status == status)
    total = db.session.scalar(select(func.count()).select_from(BackgroundJob).where(*criteria)) or 0
    rows = db.session.scalars(
        select(BackgroundJob)
        .where(*criteria)
        .order_by(BackgroundJob.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    return {
        "data": [serialize_job(row) for row in rows],
        "meta": {"page": page, "size": size, "total": total},
    }


@bp.get("/<uuid:job_id>")
@require_permission("dossier.read")
def job_get(job_id: uuid.UUID) -> Any:
    job = _job_or_404(job_id)
    if job is None:
        return problem_response(404, detail="Job no encontrado.", code="not_found")
    return serialize_job(job), 200, {"ETag": f'W/"{job.version}"'}


@bp.post("/<uuid:job_id>/cancel")
@require_permission("dossier.read")
def job_cancel(job_id: uuid.UUID) -> Any:
    job = _job_or_404(job_id, write=True)
    if job is None:
        return problem_response(404, detail="Job no encontrado.", code="not_found")
    expected = _expected_version()
    if expected is None:
        return problem_response(
            428, detail="If-Match es obligatorio.", code="precondition_required"
        )
    try:
        request_cancel(job, expected_version=expected)
    except ValueError as error:
        return problem_response(409, detail=str(error), code="job_not_cancellable")
    append_audit_event(
        db.session,
        action="background_job.cancel_requested",
        resource_type="background_job",
        resource_id=job.id,
        dossier_id=job.dossier_id,
        result="success",
        request_id=get_request_id(),
        correlation_id=get_correlation_id(),
    )
    db.session.commit()
    return serialize_job(job), 202, {"ETag": f'W/"{job.version}"'}


@bp.post("/<uuid:job_id>/retry")
@require_permission("dossier.read")
def job_retry(job_id: uuid.UUID) -> Any:
    job = _job_or_404(job_id, write=True)
    if job is None:
        return problem_response(404, detail="Job no encontrado.", code="not_found")
    expected = _expected_version()
    if expected is None:
        return problem_response(
            428, detail="If-Match es obligatorio.", code="precondition_required"
        )
    try:
        prepare_retry(job, expected_version=expected)
    except ValueError as error:
        return problem_response(409, detail=str(error), code="job_not_retryable")
    append_audit_event(
        db.session,
        action="background_job.retry_requested",
        resource_type="background_job",
        resource_id=job.id,
        dossier_id=job.dossier_id,
        result="success",
        request_id=get_request_id(),
        correlation_id=get_correlation_id(),
    )
    db.session.commit()
    publish_job(job)
    return serialize_job(job), 202, {"ETag": f'W/"{job.version}"'}
