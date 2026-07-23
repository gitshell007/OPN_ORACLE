"""HTTP boundary for human-approved procurement search profiles."""

from __future__ import annotations

import uuid
from typing import Any

from apiflask import APIBlueprint, Schema
from apiflask.fields import Dict, Float, Integer, List, Nested, Raw, String
from flask import Response, g
from flask_login import current_user
from marshmallow import validate

from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db, limiter
from opn_oracle.integrations.procurement import (
    ProcurementConfigurationError,
    ProcurementProviderError,
    create_tender_search,
)
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
    return _problem(422, detail=str(error), code="validation_error")


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
            errors=error.errors,
        )
    return {
        "profile": serialize_procurement_search_profile(profile),
        "saved_search": saved_search,
    }
