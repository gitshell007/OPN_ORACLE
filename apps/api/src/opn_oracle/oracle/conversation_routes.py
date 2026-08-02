"""HTTP boundary for durable dossier conversations (MEMSOL-06) and custom briefs (MEMSOL-07)."""

from __future__ import annotations

import uuid
from typing import Any

from apiflask import APIBlueprint, Schema
from apiflask.fields import Dict, Integer, Raw, String
from flask import Response, g, request
from flask_login import current_user
from marshmallow import validate
from sqlalchemy import select

from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db, limiter
from opn_oracle.oracle.conversations import (
    ConversationConflict,
    ConversationError,
    ConversationNotFound,
    create_conversation,
    enqueue_user_message,
    get_message,
    serialize_conversation,
    serialize_message,
)
from opn_oracle.oracle.custom_report_lifecycle import (
    IllegalTransition,
    PreconditionRequired,
    accept_plan,
    cancel_report,
    edit_plan,
    get_downloadable_artifact,
    reject_plan,
    retry_report,
)
from opn_oracle.oracle.custom_reports import (
    CustomReportConflict,
    CustomReportError,
    CustomReportNotFound,
    create_custom_report_brief,
    get_custom_brief,
    serialize_custom_brief,
)
from opn_oracle.oracle.models import StrategicDossier
from opn_oracle.oracle.policy import dossier_accessible

bp = APIBlueprint(
    "dossier_conversations",
    __name__,
    url_prefix="/api/v1",
    tag="Conversaciones e informes personalizados",
)


class ConversationCreateSchema(Schema):
    title = String(load_default="", validate=validate.Length(max=300))


class ConversationResponseSchema(Schema):
    id = String(required=True)
    tenant_id = String(required=True)
    dossier_id = String(required=True)
    status = String(required=True)
    title = String(required=True)
    created_by_user_id = String(required=True)
    intent_revision_id = String(allow_none=True)
    created_at = String(allow_none=True)
    updated_at = String(allow_none=True)


class MessageCreateSchema(Schema):
    content_text = String(required=True, validate=validate.Length(min=1, max=8000))


class MessageAcceptedSchema(Schema):
    job_id = String(required=True)
    message_id = String(required=True)
    status = String(required=True)
    message = Dict(keys=String(), values=Raw(), required=True)


class MessageResponseSchema(Schema):
    id = String(required=True)
    tenant_id = String(required=True)
    dossier_id = String(required=True)
    conversation_id = String(required=True)
    role = String(required=True)
    status = String(required=True)
    sequence = Integer(required=True)
    content_text = String(required=True)
    answer_payload = Dict(keys=String(), values=Raw(), required=True)
    coverage_manifest = Dict(keys=String(), values=Raw(), required=True)
    background_job_id = String(allow_none=True)
    created_by_user_id = String(allow_none=True)
    error_code = String(allow_none=True)
    error_message = String(allow_none=True)
    created_at = String(allow_none=True)
    updated_at = String(allow_none=True)


class CustomBriefCreateSchema(Schema):
    brief_request = String(required=True, validate=validate.Length(min=1, max=20000))


class CustomBriefAcceptedSchema(Schema):
    job_id = String(required=True)
    report_id = String(required=True)
    plan_status = String(required=True)
    status = String(required=True)
    report = Dict(keys=String(), values=Raw(), required=True)


class CustomBriefDetailSchema(Schema):
    id = String(required=True)
    tenant_id = String(required=True)
    dossier_id = String(required=True)
    title = String(required=True)
    status = String(required=True)
    report_type = String(required=True)
    template_key = String(required=True)
    template_version = String(required=True)
    generation_version = Integer(required=True)
    version = Integer(load_default=1)
    etag = String(allow_none=True)
    brief_request = String(required=True)
    plan_status = String(required=True)
    lifecycle_state = String(allow_none=True)
    proposed_plan = Dict(keys=String(), values=Raw(), allow_none=True)
    accepted_plan = Dict(keys=String(), values=Raw(), allow_none=True)
    accepted_snapshot_hash = String(allow_none=True)
    memory_degraded = Raw(load_default=False)
    memory_degraded_reason = String(allow_none=True)
    coverage = Dict(keys=String(), values=Raw(), allow_none=True)
    ready_artifact = Dict(keys=String(), values=Raw(), allow_none=True)
    downloadable = Raw(load_default=False)
    background_job_id = String(allow_none=True)
    error_code = String(allow_none=True)
    error_message = String(allow_none=True)
    requested_by_user_id = String(required=True)
    created_at = String(allow_none=True)
    updated_at = String(allow_none=True)
    ready_at = String(allow_none=True)


def _problem(
    status: int,
    *,
    detail: str,
    code: str,
    errors: Any = None,
) -> Response:
    response, response_status, headers = problem_response(
        status,
        detail=detail,
        code=code,
        errors=errors,
    )
    response.status_code = response_status
    response.headers.update(headers)
    return response


def _dossier_or_404(dossier_id: uuid.UUID, *, write: bool) -> StrategicDossier | None:
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


@bp.post("/dossiers/<uuid:dossier_id>/conversations")
@require_permission("dossier.write")
@bp.input(ConversationCreateSchema)
@bp.output(ConversationResponseSchema, status_code=201)
@limiter.limit("30/minute")
def create_dossier_conversation(
    json_data: dict[str, Any],
    dossier_id: uuid.UUID,
) -> dict[str, Any] | Response:
    if _dossier_or_404(dossier_id, write=True) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    try:
        conversation = create_conversation(
            db.session(),
            dossier_id=dossier_id,
            actor_id=current_user.id,
            title=str(json_data.get("title") or ""),
        )
        db.session.commit()
    except ConversationNotFound as error:
        db.session.rollback()
        return _problem(404, detail=str(error), code="not_found")
    except ConversationError as error:
        db.session.rollback()
        return _problem(422, detail=str(error), code="validation_error", errors=error.errors)
    return serialize_conversation(conversation)


@bp.post("/dossiers/<uuid:dossier_id>/conversations/<uuid:conversation_id>/messages")
@require_permission("ai.execute")
@bp.input(MessageCreateSchema)
@bp.output(MessageAcceptedSchema, status_code=202)
@limiter.limit("30/minute")
def enqueue_conversation_message(
    json_data: dict[str, Any],
    dossier_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> tuple[dict[str, Any], int] | Response:
    if _dossier_or_404(dossier_id, write=True) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    key = request.headers.get("Idempotency-Key", "")
    try:
        message, job = enqueue_user_message(
            db.session(),
            dossier_id=dossier_id,
            conversation_id=conversation_id,
            actor_id=current_user.id,
            content_text=str(json_data.get("content_text") or ""),
            idempotency_key=key,
            request_id=getattr(g, "request_id", None),
            publish=False,
        )
        # Persist first, then publish so Celery can run the real HANDLER.
        db.session.commit()
        from opn_oracle.jobs.service import publish_job

        publish_job(job)
    except ConversationNotFound as error:
        db.session.rollback()
        return _problem(404, detail=str(error), code="not_found")
    except ConversationConflict as error:
        db.session.rollback()
        return _problem(409, detail=str(error), code="conflict")
    except (ConversationError, ValueError) as error:
        db.session.rollback()
        errors = getattr(error, "errors", None)
        return _problem(422, detail=str(error), code="validation_error", errors=errors)
    return {
        "job_id": str(job.id),
        "message_id": str(message.id),
        "status": message.status,
        "message": serialize_message(message),
    }, 202


@bp.get(
    "/dossiers/<uuid:dossier_id>/conversations/<uuid:conversation_id>/messages/<uuid:message_id>"
)
@require_permission("dossier.read")
@bp.output(MessageResponseSchema)
@limiter.limit("60/minute")
def get_conversation_message(
    dossier_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
) -> dict[str, Any] | Response:
    if _dossier_or_404(dossier_id, write=False) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    try:
        message = get_message(
            db.session(),
            message_id,
            dossier_id=dossier_id,
            conversation_id=conversation_id,
        )
    except ConversationNotFound as error:
        return _problem(404, detail=str(error), code="not_found")
    return serialize_message(message)


@bp.post("/dossiers/<uuid:dossier_id>/reports/custom")
@require_permission("report.generate")
@bp.input(CustomBriefCreateSchema)
@bp.output(CustomBriefAcceptedSchema, status_code=202)
@limiter.limit("20/minute")
def create_custom_report(
    json_data: dict[str, Any],
    dossier_id: uuid.UUID,
) -> tuple[dict[str, Any], int] | Response:
    if _dossier_or_404(dossier_id, write=True) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    key = request.headers.get("Idempotency-Key", "")
    try:
        report, job = create_custom_report_brief(
            db.session(),
            dossier_id=dossier_id,
            actor_id=current_user.id,
            brief_request=str(json_data.get("brief_request") or ""),
            idempotency_key=key,
            request_id=getattr(g, "request_id", None),
            publish=False,
        )
        db.session.commit()
        from opn_oracle.jobs.service import publish_job

        publish_job(job)
    except CustomReportNotFound as error:
        db.session.rollback()
        return _problem(404, detail=str(error), code="not_found")
    except CustomReportConflict as error:
        db.session.rollback()
        return _problem(409, detail=str(error), code="conflict")
    except (CustomReportError, ValueError) as error:
        db.session.rollback()
        errors = getattr(error, "errors", None)
        return _problem(422, detail=str(error), code="validation_error", errors=errors)
    body = serialize_custom_brief(report)
    return {
        "job_id": str(job.id),
        "report_id": str(report.id),
        "plan_status": body["plan_status"],
        "status": report.status,
        "report": body,
    }, 202


@bp.get("/dossiers/<uuid:dossier_id>/reports/custom/<uuid:report_id>")
@require_permission("report.read")
@bp.output(CustomBriefDetailSchema)
@limiter.limit("60/minute")
def get_custom_report_brief(
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
) -> dict[str, Any] | Response:
    """Poll custom brief plan_status / proposed_plan after 202 create."""

    if _dossier_or_404(dossier_id, write=False) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    try:
        report = get_custom_brief(
            db.session(),
            dossier_id=dossier_id,
            report_id=report_id,
        )
    except CustomReportNotFound as error:
        return _problem(404, detail=str(error), code="not_found")
    return serialize_custom_brief(report)


def _parse_if_match() -> int | None:
    raw = request.headers.get("If-Match", "").strip()
    if not raw:
        return None
    raw = raw.removeprefix('W/"').removeprefix("W/").removeprefix('"').removesuffix('"')
    try:
        return int(raw)
    except ValueError:
        return None


class CustomPlanEditSchema(Schema):
    proposed_plan = Dict(keys=String(), values=Raw(), required=True)


class CustomPlanRejectSchema(Schema):
    reason = String(load_default="", validate=validate.Length(max=500))


class CustomPlanAcceptSchema(Schema):
    proposed_plan = Dict(keys=String(), values=Raw(), load_default=None)
    start_generation = Raw(load_default=True)


@bp.post("/dossiers/<uuid:dossier_id>/reports/custom/<uuid:report_id>/plan/accept")
@require_permission("report.generate")
@bp.input(CustomPlanAcceptSchema)
@limiter.limit("20/minute")
def accept_custom_report_plan(
    json_data: dict[str, Any],
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
) -> tuple[dict[str, Any], int] | Response:
    if _dossier_or_404(dossier_id, write=True) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    expected = _parse_if_match()
    try:
        plan_override = json_data.get("proposed_plan")
        auto = json_data.get("start_generation")
        if isinstance(auto, str):
            auto = auto.lower() in {"1", "true", "yes", "on"}
        elif auto is None:
            auto = True
        else:
            auto = bool(auto)
        report = accept_plan(
            db.session(),
            dossier_id=dossier_id,
            report_id=report_id,
            actor_id=current_user.id,
            expected_version=expected,
            plan_override=plan_override if isinstance(plan_override, dict) else None,
            request_id=getattr(g, "request_id", None),
            auto_start_generation=auto,
        )
        # publish write job if staged
        job_id = report.background_job_id
        db.session.commit()
        life_state = str((report.options or {}).get("lifecycle_state") or "")
        if job_id is not None and life_state == "generating":
            from opn_oracle.jobs.service import publish_job
            from opn_oracle.oracle.jobs import BackgroundJob

            job = db.session.get(BackgroundJob, job_id)
            if job is not None:
                publish_job(job)
    except PreconditionRequired as error:
        db.session.rollback()
        return _problem(428, detail=str(error), code="precondition_required")
    except CustomReportConflict as error:
        db.session.rollback()
        return _problem(409, detail=str(error), code="conflict")
    except IllegalTransition as error:
        db.session.rollback()
        return _problem(409, detail=str(error), code="illegal_transition")
    except CustomReportNotFound as error:
        db.session.rollback()
        return _problem(404, detail=str(error), code="not_found")
    except CustomReportError as error:
        db.session.rollback()
        return _problem(
            422,
            detail=str(error),
            code="validation_error",
            errors=getattr(error, "errors", None),
        )
    body = serialize_custom_brief(report)
    return body, 200


@bp.post("/dossiers/<uuid:dossier_id>/reports/custom/<uuid:report_id>/plan/edit")
@require_permission("report.generate")
@bp.input(CustomPlanEditSchema)
@limiter.limit("20/minute")
def edit_custom_report_plan(
    json_data: dict[str, Any],
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
) -> tuple[dict[str, Any], int] | Response:
    if _dossier_or_404(dossier_id, write=True) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    expected = _parse_if_match()
    try:
        report = edit_plan(
            db.session(),
            dossier_id=dossier_id,
            report_id=report_id,
            actor_id=current_user.id,
            expected_version=expected,
            proposed_plan=json_data.get("proposed_plan") or {},
            request_id=getattr(g, "request_id", None),
        )
        db.session.commit()
    except PreconditionRequired as error:
        db.session.rollback()
        return _problem(428, detail=str(error), code="precondition_required")
    except CustomReportConflict as error:
        db.session.rollback()
        return _problem(409, detail=str(error), code="conflict")
    except IllegalTransition as error:
        db.session.rollback()
        return _problem(409, detail=str(error), code="illegal_transition")
    except CustomReportNotFound as error:
        db.session.rollback()
        return _problem(404, detail=str(error), code="not_found")
    except CustomReportError as error:
        db.session.rollback()
        return _problem(
            422,
            detail=str(error),
            code="validation_error",
            errors=getattr(error, "errors", None),
        )
    return serialize_custom_brief(report), 200


@bp.post("/dossiers/<uuid:dossier_id>/reports/custom/<uuid:report_id>/plan/reject")
@require_permission("report.generate")
@bp.input(CustomPlanRejectSchema)
@limiter.limit("20/minute")
def reject_custom_report_plan(
    json_data: dict[str, Any],
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
) -> tuple[dict[str, Any], int] | Response:
    if _dossier_or_404(dossier_id, write=True) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    expected = _parse_if_match()
    try:
        report = reject_plan(
            db.session(),
            dossier_id=dossier_id,
            report_id=report_id,
            actor_id=current_user.id,
            expected_version=expected,
            reason=str(json_data.get("reason") or ""),
            request_id=getattr(g, "request_id", None),
        )
        db.session.commit()
    except PreconditionRequired as error:
        db.session.rollback()
        return _problem(428, detail=str(error), code="precondition_required")
    except CustomReportConflict as error:
        db.session.rollback()
        return _problem(409, detail=str(error), code="conflict")
    except IllegalTransition as error:
        db.session.rollback()
        return _problem(409, detail=str(error), code="illegal_transition")
    except CustomReportNotFound as error:
        db.session.rollback()
        return _problem(404, detail=str(error), code="not_found")
    except CustomReportError as error:
        db.session.rollback()
        return _problem(
            422,
            detail=str(error),
            code="validation_error",
            errors=getattr(error, "errors", None),
        )
    return serialize_custom_brief(report), 200


@bp.post("/dossiers/<uuid:dossier_id>/reports/custom/<uuid:report_id>/cancel")
@require_permission("report.generate")
@limiter.limit("20/minute")
def cancel_custom_report(
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
) -> tuple[dict[str, Any], int] | Response:
    if _dossier_or_404(dossier_id, write=True) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    expected = _parse_if_match()
    try:
        report = cancel_report(
            db.session(),
            dossier_id=dossier_id,
            report_id=report_id,
            actor_id=current_user.id,
            expected_version=expected,
            request_id=getattr(g, "request_id", None),
        )
        db.session.commit()
    except PreconditionRequired as error:
        db.session.rollback()
        return _problem(428, detail=str(error), code="precondition_required")
    except CustomReportConflict as error:
        db.session.rollback()
        return _problem(409, detail=str(error), code="conflict")
    except IllegalTransition as error:
        db.session.rollback()
        return _problem(409, detail=str(error), code="illegal_transition")
    except CustomReportNotFound as error:
        db.session.rollback()
        return _problem(404, detail=str(error), code="not_found")
    except CustomReportError as error:
        db.session.rollback()
        return _problem(
            422,
            detail=str(error),
            code="validation_error",
            errors=getattr(error, "errors", None),
        )
    return serialize_custom_brief(report), 200


@bp.post("/dossiers/<uuid:dossier_id>/reports/custom/<uuid:report_id>/retry")
@require_permission("report.generate")
@limiter.limit("20/minute")
def retry_custom_report(
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
) -> tuple[dict[str, Any], int] | Response:
    if _dossier_or_404(dossier_id, write=True) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    expected = _parse_if_match()
    try:
        report = retry_report(
            db.session(),
            dossier_id=dossier_id,
            report_id=report_id,
            actor_id=current_user.id,
            expected_version=expected,
            request_id=getattr(g, "request_id", None),
        )
        job_id = report.background_job_id
        db.session.commit()
        life_state = str((report.options or {}).get("lifecycle_state") or "")
        if job_id is not None and life_state == "generating":
            from opn_oracle.jobs.service import publish_job
            from opn_oracle.oracle.jobs import BackgroundJob

            job = db.session.get(BackgroundJob, job_id)
            if job is not None:
                publish_job(job)
    except PreconditionRequired as error:
        db.session.rollback()
        return _problem(428, detail=str(error), code="precondition_required")
    except CustomReportConflict as error:
        db.session.rollback()
        return _problem(409, detail=str(error), code="conflict")
    except IllegalTransition as error:
        db.session.rollback()
        return _problem(409, detail=str(error), code="illegal_transition")
    except CustomReportNotFound as error:
        db.session.rollback()
        return _problem(404, detail=str(error), code="not_found")
    except CustomReportError as error:
        db.session.rollback()
        return _problem(
            422,
            detail=str(error),
            code="validation_error",
            errors=getattr(error, "errors", None),
        )
    return serialize_custom_brief(report), 200


@bp.get("/dossiers/<uuid:dossier_id>/reports/custom/<uuid:report_id>/download")
@require_permission("report.read")
@limiter.limit("30/minute")
def download_custom_report(
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
) -> Response:
    if _dossier_or_404(dossier_id, write=False) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    try:
        report = get_custom_brief(
            db.session(),
            dossier_id=dossier_id,
            report_id=report_id,
        )
    except CustomReportNotFound as error:
        return _problem(404, detail=str(error), code="not_found")
    art = get_downloadable_artifact(report)
    if art is None:
        return _problem(
            409,
            detail="Artefacto no disponible para descarga (no ready o no validado).",
            code="artifact_not_ready",
        )
    import json as _json

    body = _json.dumps(art.get("content") or {}, ensure_ascii=False, indent=2)
    resp = Response(body, mimetype="application/json")
    resp.headers["Content-Disposition"] = f'attachment; filename="report-{report_id}.json"'
    resp.headers["X-Content-SHA256"] = str(art.get("sha256") or "")
    resp.headers["X-Content-Size"] = str(art.get("byte_size") or 0)
    resp.headers["ETag"] = f'W/"{report.version}"'
    return resp
