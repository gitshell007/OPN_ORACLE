"""HTTP boundary for human-approved procurement search profiles."""

from __future__ import annotations

import uuid
from typing import Any

from apiflask import APIBlueprint, Schema
from apiflask.fields import Dict, Float, Integer, List, Nested, Raw, String
from flask import Response, g, request
from flask_login import current_user
from marshmallow import validate
from sqlalchemy import select

from opn_oracle.ai.models import AIArtifact
from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db, limiter
from opn_oracle.integrations.procurement import (
    ProcurementConfigurationError,
    ProcurementProviderError,
    create_tender_search,
)
from opn_oracle.jobs.service import enqueue_job, serialize_job
from opn_oracle.oracle.procurement_search_preview import SearchPlanExecutionError
from opn_oracle.oracle.procurement_search_profiles import (
    ProcurementSearchProfileNotFound,
    ProcurementSearchProfileValidationError,
    ProcurementSearchProfileVersionConflict,
    accept_procurement_search_profile,
    create_procurement_search_profile,
    get_procurement_search_profile,
    list_procurement_search_profiles,
    serialize_procurement_search_profile,
)
from opn_oracle.oracle.procurement_search_watch import save_profile_watch

bp = APIBlueprint(
    "procurement_search_profiles",
    __name__,
    url_prefix="/api/v1/procurement-search-profiles",
    tag="Perfiles de búsqueda de licitaciones",
)


class CandidateCPVSchema(Schema):
    code = String(required=True)
    label = String(required=True)


class AcceptedTenderSearchPlanSchema(Schema):
    intent_summary = String(required=True)
    include_terms = List(String(), required=True)
    synonyms = List(String(), required=True)
    exclude_terms = List(String(), required=True)
    candidate_cpv = List(Nested(CandidateCPVSchema), required=True)
    buyers = List(String(), required=True)
    geographies = List(String(), required=True)
    scope = String(required=True, validate=validate.OneOf(["active", "historical", "all"]))
    min_amount = Float(allow_none=True, required=True)
    max_amount = Float(allow_none=True, required=True)
    assumptions = List(String(), required=True)
    questions = List(String(), required=True)
    confidence = Integer(required=True, validate=validate.Range(min=0, max=100))
    discarded_count = Integer(required=True, validate=validate.Range(min=0))
    discarded_reasons = Dict(
        keys=String(),
        values=Integer(validate=validate.Range(min=1)),
        required=True,
    )


class CreateProcurementSearchProfileSchema(Schema):
    original_description = String(required=True, validate=validate.Length(min=2, max=5000))
    comparables = List(
        String(validate=validate.Length(min=1, max=250)),
        load_default=list,
        validate=validate.Length(max=10),
    )
    accepted_plan = Nested(AcceptedTenderSearchPlanSchema, required=True)
    ai_artifact_id = String(required=True)


class AcceptProcurementSearchProfileSchema(Schema):
    expected_version = Integer(required=True, validate=validate.Range(min=1))
    accepted_plan = Nested(AcceptedTenderSearchPlanSchema, required=True)
    ai_artifact_id = String(required=True)


class ProcurementSearchProfilePathSchema(Schema):
    profile_id = String(required=True)


class SaveProcurementSearchProfileSchema(Schema):
    expected_version = Integer(required=True, validate=validate.Range(min=1))
    name = String(required=True, validate=validate.Length(min=2, max=120))


class ProcurementSearchProfileResponseSchema(Schema):
    id = String(required=True)
    schema = String(required=True)
    original_description = String(required=True)
    comparables = List(String(), required=True)
    accepted_plan = Nested(AcceptedTenderSearchPlanSchema, required=True)
    accepted_plan_hash = String(required=True)
    version = Integer(required=True)
    ai_artifact_id = String(required=True)
    tender_search_id = String(allow_none=True)
    accepted_by_user_id = String(required=True)
    created_at = String(required=True)
    updated_at = String(required=True)
    last_accepted_at = String(required=True)


class ProcurementSearchProfileListSchema(Schema):
    items = List(Nested(ProcurementSearchProfileResponseSchema), required=True)


class SavedProcurementSearchResponseSchema(Schema):
    profile = Nested(ProcurementSearchProfileResponseSchema, required=True)
    saved_search = Dict(keys=String(), values=Raw(), required=True)


class ReplanProcurementSearchProfileSchema(Schema):
    expected_version = Integer(required=True, validate=validate.Range(min=1))
    digest_hash = String(
        required=True,
        validate=validate.Regexp(r"^[0-9a-f]{64}$"),
    )


class ReplanProcurementSearchProfileResponseSchema(Schema):
    job = Dict(keys=String(), values=Raw(), required=True)
    artifact = Dict(keys=String(), values=Raw(), allow_none=True)


def _uuid(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as error:
        raise ProcurementSearchProfileNotFound("Perfil de búsqueda no encontrado.") from error


def _problem(
    status: int,
    *,
    title: str | None = None,
    detail: str,
    code: str,
    errors: Any = None,
) -> Response:
    response, response_status, headers = problem_response(
        status,
        title=title,
        detail=detail,
        code=code,
        errors=errors,
    )
    response.status_code = response_status
    response.headers.update(headers)
    return response


def _error(error: Exception) -> Response:
    if isinstance(error, ProcurementSearchProfileNotFound):
        return _problem(404, detail=str(error), code="not_found")
    if isinstance(error, ProcurementSearchProfileVersionConflict):
        return _problem(409, detail=str(error), code="version_conflict")
    if isinstance(error, ProcurementSearchProfileValidationError):
        errors = error.errors
    elif isinstance(error, SearchPlanExecutionError):
        message = str(error)
        path = (
            "accepted_plan.scope"
            if "históric" in message.casefold()
            or "activas" in message.casefold()
            or "ámbito temporal" in message.casefold()
            else "accepted_plan.include_terms"
        )
        errors = {path: [message]}
    else:
        errors = {"profile": [str(error)]}
    return _problem(
        422,
        detail=str(error),
        code="validation_error",
        errors=errors,
    )


@bp.get("")
@require_permission("opportunity.read")
@bp.output(ProcurementSearchProfileListSchema)
@limiter.limit("60/minute")
def profiles_list() -> dict[str, Any]:
    return {
        "items": [
            serialize_procurement_search_profile(profile)
            for profile in list_procurement_search_profiles(db.session())
        ]
    }


@bp.post("")
@require_permission("opportunity.write")
@bp.input(CreateProcurementSearchProfileSchema)
@bp.output(ProcurementSearchProfileResponseSchema, status_code=201)
@limiter.limit("30/minute")
def profiles_create(json_data: dict[str, Any]) -> dict[str, Any] | Any:
    try:
        profile = create_procurement_search_profile(
            db.session(),
            json_data,
            actor_id=current_user.id,
            request_id=getattr(g, "request_id", None),
        )
    except ProcurementSearchProfileValidationError as error:
        db.session.rollback()
        return _error(error)
    return serialize_procurement_search_profile(profile)


@bp.get("/<profile_id>")
@require_permission("opportunity.read")
@bp.output(ProcurementSearchProfileResponseSchema)
@limiter.limit("60/minute")
def profiles_get(profile_id: str) -> dict[str, Any] | Any:
    try:
        profile = get_procurement_search_profile(db.session(), _uuid(profile_id))
    except ProcurementSearchProfileNotFound as error:
        return _error(error)
    return serialize_procurement_search_profile(profile)


@bp.post("/<profile_id>/acceptances")
@require_permission("opportunity.write")
@bp.input(AcceptProcurementSearchProfileSchema)
@bp.output(ProcurementSearchProfileResponseSchema)
@limiter.limit("30/minute")
def profiles_accept(
    json_data: dict[str, Any],
    profile_id: str,
) -> dict[str, Any] | Any:
    try:
        profile = accept_procurement_search_profile(
            db.session(),
            _uuid(profile_id),
            json_data,
            actor_id=current_user.id,
            request_id=getattr(g, "request_id", None),
        )
    except (
        ProcurementSearchProfileNotFound,
        ProcurementSearchProfileValidationError,
        ProcurementSearchProfileVersionConflict,
    ) as error:
        db.session.rollback()
        return _error(error)
    return serialize_procurement_search_profile(profile)


def _latest_replan_artifact(profile_id: uuid.UUID) -> dict[str, Any] | None:
    artifact = db.session.scalar(
        select(AIArtifact)
        .where(
            AIArtifact.tenant_id == g.active_tenant_id,
            AIArtifact.dossier_id.is_(None),
            AIArtifact.agent == "tender_search_wizard",
            AIArtifact.target_type == "procurement_search_profile",
            AIArtifact.target_id == profile_id,
        )
        .order_by(AIArtifact.created_at.desc(), AIArtifact.id.desc())
        .limit(1)
    )
    if artifact is None:
        return None
    return {
        "id": str(artifact.id),
        "dossier_id": None,
        "agent": artifact.agent,
        "schema_name": artifact.schema_name,
        "schema_version": artifact.schema_version,
        "status": artifact.status,
        "output": artifact.output,
        "created_at": artifact.created_at.isoformat(),
        "updated_at": artifact.updated_at.isoformat(),
        "version": artifact.version,
    }


@bp.post("/<profile_id>/replans")
@require_permission("ai.execute")
@bp.input(ReplanProcurementSearchProfileSchema)
@bp.output(ReplanProcurementSearchProfileResponseSchema, status_code=202)
@limiter.limit("6/minute")
def profiles_replan(
    json_data: dict[str, Any],
    profile_id: str,
) -> dict[str, Any] | Any:
    from opn_oracle.oracle.procurement_search_feedback import (
        build_procurement_search_feedback_digest,
    )

    try:
        parsed_profile_id = _uuid(profile_id)
        profile = get_procurement_search_profile(db.session(), parsed_profile_id)
    except ProcurementSearchProfileNotFound as error:
        return _error(error)
    if profile.version != int(json_data["expected_version"]):
        return _problem(
            409,
            detail="El perfil cambió desde la última lectura.",
            code="version_conflict",
        )
    digest = build_procurement_search_feedback_digest(db.session(), parsed_profile_id)
    expected_digest_hash = str(json_data["digest_hash"])
    if digest.get("digest_hash") != expected_digest_hash:
        return _problem(
            409,
            detail="El feedback cambió desde la última lectura.",
            code="feedback_digest_conflict",
        )
    key = request.headers.get("Idempotency-Key", "")
    if not key:
        return _problem(
            428,
            detail="Idempotency-Key es obligatorio para revisar el plan.",
            code="precondition_required",
        )
    try:
        job = enqueue_job(
            "oracle.ai.tender_search_wizard",
            payload={
                "mode": "replan",
                "profile_id": str(profile.id),
                "expected_profile_version": profile.version,
                "expected_plan_hash": profile.accepted_plan_hash.hex(),
                "expected_digest_hash": expected_digest_hash,
            },
            idempotency_key=key,
            requested_by_user_id=current_user.id,
            resource_type="procurement_search_profile",
            resource_id=profile.id,
        )
    except ValueError as error:
        return _problem(
            422,
            detail=str(error),
            code="validation_error",
        )
    return {
        "job": serialize_job(job),
        "artifact": _latest_replan_artifact(profile.id),
    }, 202


@bp.post("/<profile_id>/saved-search")
@require_permission("opportunity.write")
@bp.input(SaveProcurementSearchProfileSchema)
@bp.output(SavedProcurementSearchResponseSchema)
@limiter.limit("30/minute")
def profiles_save_search(
    json_data: dict[str, Any],
    profile_id: str,
) -> dict[str, Any] | Any:
    session = db.session()
    try:
        profile = get_procurement_search_profile(
            session,
            _uuid(profile_id),
            for_update=True,
        )
        profile, saved_search = save_profile_watch(
            session,
            profile,
            expected_version=int(json_data["expected_version"]),
            name=str(json_data["name"]),
            create_search=create_tender_search,
            request_id=getattr(g, "request_id", None),
        )
    except (
        ProcurementSearchProfileNotFound,
        ProcurementSearchProfileValidationError,
        ProcurementSearchProfileVersionConflict,
        SearchPlanExecutionError,
    ) as error:
        db.session.rollback()
        return _error(error)
    except ProcurementConfigurationError as error:
        db.session.rollback()
        return _problem(
            503,
            title="Contratación pública no disponible",
            detail=str(error),
            code="procurement_not_configured",
        )
    except ProcurementProviderError as error:
        db.session.rollback()
        return _problem(
            error.status_code,
            title="No se pudo guardar la vigilancia",
            detail=error.detail,
            code=error.code,
            errors=(
                error.errors
                if error.errors
                else ({"saved_search": [error.detail]} if error.status_code == 422 else None)
            ),
        )
    return {
        "profile": serialize_procurement_search_profile(profile),
        "saved_search": saved_search,
    }
