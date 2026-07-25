"""HTTP boundary for the traceable investigation workbench."""

from __future__ import annotations

import uuid
from typing import Any

from apiflask import APIBlueprint, Schema
from apiflask.fields import Dict, Integer, List, Nested, Raw, String
from flask import Response, g, request
from flask_login import current_user
from marshmallow import validate
from sqlalchemy import select

from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db, limiter
from opn_oracle.jobs.service import enqueue_job, serialize_job
from opn_oracle.oracle.investigations import (
    InvestigationConflict,
    InvestigationError,
    InvestigationNotFound,
    InvestigationRun,
    actor_alias_candidates,
    create_investigation,
    get_investigation,
    investigation_report_preview,
    investigation_summary,
    review_research_entity,
    set_investigation_state,
)

bp = APIBlueprint(
    "investigations",
    __name__,
    url_prefix="/api/v1",
    tag="Investigaciones empresariales",
)


class InvestigationLimitsSchema(Schema):
    max_depth = Integer(validate=validate.Range(min=1, max=3))
    max_entities = Integer(validate=validate.Range(min=1, max=500))
    max_documents = Integer(validate=validate.Range(min=0, max=5000))
    max_ai_calls = Integer(validate=validate.Range(min=0, max=1000))
    max_runtime_minutes = Integer(validate=validate.Range(min=10, max=1440))


class CreateInvestigationSchema(Schema):
    question = String(required=True, validate=validate.Length(min=10, max=5000))
    seed_name = String(required=True, validate=validate.Length(min=2, max=300))
    seed_kind = String(
        required=True,
        validate=validate.OneOf(["company", "person", "unknown"]),
    )
    seed_identifiers = Dict(keys=String(), values=Raw(), load_default=dict)
    period_start = String(allow_none=True)
    period_end = String(allow_none=True)
    limits = Nested(InvestigationLimitsSchema, load_default=dict)


class InvestigationPathSchema(Schema):
    dossier_id = String(required=True)


class RunPathSchema(Schema):
    run_id = String(required=True)


class EntityReviewPathSchema(Schema):
    run_id = String(required=True)
    entity_id = String(required=True)


class EntityReviewSchema(Schema):
    decision = String(
        required=True,
        validate=validate.OneOf(["verify", "reject", "add_alias"]),
    )
    alias = String(allow_none=True, validate=validate.Length(min=2, max=300))


class InvestigationResponseSchema(Schema):
    id = String(required=True)
    dossier_id = String(required=True)
    question = String(required=True)
    seed = Dict(keys=String(), values=Raw(), required=True)
    status = String(required=True)
    stage = String(required=True)
    progress = Integer(required=True)
    cutoff_at = String(required=True)
    period_start = String(allow_none=True)
    period_end = String(allow_none=True)
    protocol_version = String(required=True)
    source_policy_version = String(required=True)
    limits = Dict(keys=String(), values=Raw(), required=True)
    source_policy = Dict(keys=String(), values=Raw(), required=True)
    corpus_hash = String(allow_none=True)
    stop_reason = String(allow_none=True)
    version = Integer(required=True)
    created_at = String(required=True)
    updated_at = String(required=True)
    steps = List(Dict(keys=String(), values=Raw()), required=True)
    counts = Dict(keys=String(), values=Raw(), required=True)
    entities = List(Dict(keys=String(), values=Raw()), required=True)
    relations = List(Dict(keys=String(), values=Raw()), required=True)
    procurement_participations = List(Dict(keys=String(), values=Raw()), required=True)
    claims = List(Dict(keys=String(), values=Raw()), required=True)


class InvestigationListSchema(Schema):
    items = List(Nested(InvestigationResponseSchema), required=True)


class InvestigationExecutionSchema(Schema):
    investigation = Nested(InvestigationResponseSchema, required=True)
    job = Dict(keys=String(), values=Raw(), required=True)


class AliasCandidateListSchema(Schema):
    items = List(Dict(keys=String(), values=Raw()), required=True)


class InvestigationReportPreviewSchema(Schema):
    investigation = Nested(InvestigationResponseSchema, required=True)
    report = Dict(keys=String(), values=Raw(), required=True)
    verified_entities = List(Dict(keys=String(), values=Raw()), required=True)
    candidate_entities = List(Dict(keys=String(), values=Raw()), required=True)


def _uuid(value: str, *, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as error:
        raise InvestigationNotFound(f"{label} no encontrado.") from error


def _problem(error: Exception) -> Response:
    if isinstance(error, InvestigationNotFound):
        status, code = 404, "not_found"
    elif isinstance(error, InvestigationConflict):
        status, code = 409, "state_conflict"
    else:
        status, code = 422, "validation_error"
    response, response_status, headers = problem_response(
        status,
        detail=str(error),
        code=code,
    )
    response.status_code = response_status
    response.headers.update(headers)
    return response


@bp.post("/dossiers/<dossier_id>/investigations")
@require_permission("dossier.write")
@bp.input(CreateInvestigationSchema)
@bp.output(InvestigationResponseSchema, status_code=201)
@limiter.limit("10/minute")
def investigations_create(json_data: dict[str, Any], dossier_id: str) -> dict[str, Any] | Response:
    try:
        run = create_investigation(
            db.session(),
            dossier_id=_uuid(dossier_id, label="Expediente"),
            payload=json_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
            requested_by_user_id=current_user.id,
            request_id=getattr(g, "request_id", None),
        )
    except (InvestigationError, InvestigationNotFound) as error:
        db.session.rollback()
        return _problem(error)
    return investigation_summary(db.session(), run)


@bp.get("/dossiers/<dossier_id>/investigations")
@require_permission("dossier.read")
@bp.output(InvestigationListSchema)
@limiter.limit("60/minute")
def investigations_list(dossier_id: str) -> dict[str, Any] | Response:
    try:
        parsed_dossier_id = _uuid(dossier_id, label="Expediente")
    except InvestigationNotFound as error:
        return _problem(error)
    runs = list(
        db.session.scalars(
            select(InvestigationRun)
            .where(
                InvestigationRun.tenant_id == g.active_tenant_id,
                InvestigationRun.dossier_id == parsed_dossier_id,
            )
            .order_by(InvestigationRun.created_at.desc())
        )
    )
    return {"items": [investigation_summary(db.session(), run) for run in runs]}


@bp.get("/investigations/<run_id>")
@require_permission("dossier.read")
@bp.output(InvestigationResponseSchema)
@limiter.limit("60/minute")
def investigations_get(run_id: str) -> dict[str, Any] | Response:
    try:
        run = get_investigation(db.session(), _uuid(run_id, label="Investigación"))
    except InvestigationNotFound as error:
        return _problem(error)
    return investigation_summary(db.session(), run)


@bp.get("/investigations/<run_id>/report-preview")
@require_permission("dossier.read")
@bp.output(InvestigationReportPreviewSchema)
@limiter.limit("30/minute")
def investigations_report_preview(run_id: str) -> dict[str, Any] | Response:
    try:
        return investigation_report_preview(db.session(), _uuid(run_id, label="Investigación"))
    except InvestigationNotFound as error:
        return _problem(error)


@bp.post("/investigations/<run_id>/entities/<entity_id>/reviews")
@require_permission("actor.write")
@bp.input(EntityReviewSchema)
@bp.output(InvestigationResponseSchema)
@limiter.limit("30/minute")
def investigations_review_entity(
    json_data: dict[str, Any],
    run_id: str,
    entity_id: str,
) -> dict[str, Any] | Response:
    try:
        run_uuid = _uuid(run_id, label="Investigación")
        review_research_entity(
            db.session(),
            run_id=run_uuid,
            entity_id=_uuid(entity_id, label="Entidad"),
            decision=json_data["decision"],
            alias=json_data.get("alias"),
            actor_id=current_user.id,
        )
        run = get_investigation(db.session(), run_uuid)
    except (InvestigationError, InvestigationNotFound, InvestigationConflict) as error:
        db.session.rollback()
        return _problem(error)
    return investigation_summary(db.session(), run)


def _state_action(run_id: str, action: str) -> dict[str, Any] | Response:
    try:
        run = set_investigation_state(
            db.session(),
            run_id=_uuid(run_id, label="Investigación"),
            action=action,
        )
    except (InvestigationNotFound, InvestigationConflict) as error:
        db.session.rollback()
        return _problem(error)
    return investigation_summary(db.session(), run)


@bp.post("/investigations/<run_id>/pause")
@require_permission("dossier.write")
@bp.output(InvestigationResponseSchema)
@limiter.limit("20/minute")
def investigations_pause(run_id: str) -> dict[str, Any] | Response:
    return _state_action(run_id, "pause")


@bp.post("/investigations/<run_id>/cancel")
@require_permission("dossier.write")
@bp.output(InvestigationResponseSchema)
@limiter.limit("20/minute")
def investigations_cancel(run_id: str) -> dict[str, Any] | Response:
    return _state_action(run_id, "cancel")


@bp.post("/investigations/<run_id>/execute")
@require_permission("dossier.write")
@bp.output(InvestigationExecutionSchema, status_code=202)
@limiter.limit("10/minute")
def investigations_execute(run_id: str) -> dict[str, Any] | Response:
    key = request.headers.get("Idempotency-Key", "")
    if not 8 <= len(key) <= 200:
        return _problem(InvestigationError("Idempotency-Key debe tener entre 8 y 200 caracteres."))
    try:
        run_uuid = _uuid(run_id, label="Investigación")
        run = set_investigation_state(db.session(), run_id=run_uuid, action="resume")
        job = enqueue_job(
            "oracle.investigation.run",
            payload={"run_id": str(run.id)},
            idempotency_key=key,
            requested_by_user_id=current_user.id,
            dossier_id=run.dossier_id,
            resource_type="investigation_run",
            resource_id=run.id,
            correlation_id=getattr(g, "correlation_id", None),
            request_id=getattr(g, "request_id", None),
        )
    except (
        InvestigationError,
        InvestigationNotFound,
        InvestigationConflict,
        ValueError,
    ) as error:
        db.session.rollback()
        return _problem(
            error
            if isinstance(error, (InvestigationError, InvestigationNotFound, InvestigationConflict))
            else InvestigationConflict(str(error))
        )
    return {
        "investigation": investigation_summary(db.session(), run),
        "job": serialize_job(job),
    }


@bp.get("/actors/alias-candidates")
@require_permission("actor.read")
@bp.output(AliasCandidateListSchema)
@limiter.limit("30/minute")
def actor_alias_candidate_list() -> dict[str, Any]:
    return {"items": actor_alias_candidates(db.session())}
