"""HTTP contract for deterministic procurement-search feedback and digest."""

from __future__ import annotations

import uuid
from typing import Any

from apiflask import APIBlueprint, Schema
from apiflask.fields import Boolean, Dict, Integer, List, Nested, String
from flask import Response, g
from flask_login import current_user
from marshmallow import validate

from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db, limiter
from opn_oracle.oracle.procurement_search_feedback import (
    FEEDBACK_REASONS,
    FEEDBACK_VERDICTS,
    ProcurementSearchFeedbackConflict,
    ProcurementSearchFeedbackNotFound,
    ProcurementSearchFeedbackValidationError,
    build_procurement_search_feedback_digest,
    list_procurement_search_feedback,
    register_procurement_search_feedback,
    serialize_procurement_search_feedback,
    withdraw_procurement_search_feedback,
)
from opn_oracle.oracle.procurement_search_profiles import (
    ProcurementSearchProfileNotFound,
)

bp = APIBlueprint(
    "procurement_search_feedback",
    __name__,
    url_prefix="/api/v1/procurement-search-profiles",
    tag="Feedback de búsquedas de licitaciones",
)


class TenderFeedbackSnapshotSchema(Schema):
    title = String(load_default="", validate=validate.Length(max=2000))
    cpvs = List(
        String(validate=validate.Length(min=1, max=32)),
        load_default=list,
        validate=validate.Length(max=20),
    )


class RegisterProcurementSearchFeedbackSchema(Schema):
    plan_version = Integer(required=True, validate=validate.Range(min=1))
    folder_id = String(required=True, validate=validate.Length(min=1, max=240))
    verdict = String(required=True, validate=validate.OneOf(FEEDBACK_VERDICTS))
    reason = String(
        allow_none=True,
        load_default=None,
        validate=validate.OneOf(FEEDBACK_REASONS),
    )
    note = String(load_default="", validate=validate.Length(max=2000))
    tender = Nested(TenderFeedbackSnapshotSchema, required=True)


class ProcurementSearchFeedbackSchema(Schema):
    id = String(required=True)
    profile_id = String(required=True)
    plan_version = Integer(required=True)
    folder_id = String(required=True)
    verdict = String(required=True)
    reason = String(allow_none=True)
    note = String(allow_none=True)
    user_id = String(required=True)
    tender = Nested(TenderFeedbackSnapshotSchema, required=True)
    state = String(required=True)
    created_at = String(required=True)
    updated_at = String(required=True)


class ProcurementSearchFeedbackListQuerySchema(Schema):
    include_history = Boolean(load_default=False)
    limit = Integer(load_default=50, validate=validate.Range(min=1, max=100))
    offset = Integer(
        load_default=0,
        validate=validate.Range(min=0, max=100_000),
    )


class ProcurementSearchFeedbackListSchema(Schema):
    items = List(Nested(ProcurementSearchFeedbackSchema), required=True)
    total = Integer(required=True)
    limit = Integer(required=True)
    offset = Integer(required=True)


class FeedbackTermCandidateSchema(Schema):
    value = String(required=True)
    count = Integer(required=True)
    relevant_count = Integer(required=True)
    rejected_count = Integer(required=True)
    delta = Integer(required=True)


class FeedbackCPVCandidateSchema(Schema):
    code = String(required=True)
    label = String(allow_none=True)
    count = Integer(required=True)
    relevant_count = Integer(required=True)
    rejected_count = Integer(required=True)
    delta = Integer(required=True)


class FeedbackCandidatesSchema(Schema):
    terms = List(Nested(FeedbackTermCandidateSchema), required=True)
    cpvs = List(Nested(FeedbackCPVCandidateSchema), required=True)


class ProcurementSearchFeedbackDigestSchema(Schema):
    schema = String(required=True)
    profile_id = String(required=True)
    plan_version = Integer(required=True)
    digest_hash = String(required=True)
    feedback_state_hash = String(required=True)
    new_feedback_count = Integer(required=True)
    counts = Dict(keys=String(), values=Integer(), required=True)
    reasons = Dict(keys=String(), values=Integer(), required=True)
    exclusion_candidates = Nested(FeedbackCandidatesSchema, required=True)
    reinforcement_candidates = Nested(FeedbackCandidatesSchema, required=True)
    tokenizer_version = String(required=True)
    taxonomy_version = String(required=True)


def _uuid(value: Any, *, resource: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as error:
        raise ProcurementSearchFeedbackNotFound(f"{resource} no encontrado.") from error


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


def _error(error: Exception) -> Response:
    if isinstance(
        error,
        (ProcurementSearchFeedbackNotFound, ProcurementSearchProfileNotFound),
    ):
        return _problem(404, detail=str(error), code="not_found")
    if isinstance(error, ProcurementSearchFeedbackConflict):
        return _problem(409, detail=str(error), code="version_conflict")
    errors = (
        error.errors
        if isinstance(error, ProcurementSearchFeedbackValidationError)
        else {"feedback": [str(error)]}
    )
    return _problem(
        422,
        detail=str(error),
        code="validation_error",
        errors=errors,
    )


@bp.post("/<profile_id>/feedback")
@require_permission("opportunity.write")
@bp.input(RegisterProcurementSearchFeedbackSchema)
@bp.output(ProcurementSearchFeedbackSchema, status_code=201)
@limiter.limit("120/minute")
def feedback_register(
    json_data: dict[str, Any],
    profile_id: str,
) -> dict[str, Any] | Any:
    try:
        feedback, _created = register_procurement_search_feedback(
            db.session(),
            _uuid(profile_id, resource="Perfil"),
            json_data,
            actor_id=current_user.id,
            request_id=getattr(g, "request_id", None),
        )
    except (
        ProcurementSearchFeedbackNotFound,
        ProcurementSearchFeedbackValidationError,
        ProcurementSearchProfileNotFound,
    ) as error:
        db.session.rollback()
        return _error(error)
    return serialize_procurement_search_feedback(feedback)


@bp.delete("/<profile_id>/feedback/<feedback_id>")
@require_permission("opportunity.write")
@limiter.limit("120/minute")
def feedback_withdraw(profile_id: str, feedback_id: str) -> Any:
    try:
        withdraw_procurement_search_feedback(
            db.session(),
            _uuid(profile_id, resource="Perfil"),
            _uuid(feedback_id, resource="Feedback"),
            actor_id=current_user.id,
            request_id=getattr(g, "request_id", None),
        )
    except (
        ProcurementSearchFeedbackConflict,
        ProcurementSearchFeedbackNotFound,
        ProcurementSearchProfileNotFound,
    ) as error:
        db.session.rollback()
        return _error(error)
    return "", 204


@bp.get("/<profile_id>/feedback")
@require_permission("opportunity.read")
@bp.input(ProcurementSearchFeedbackListQuerySchema, location="query")
@bp.output(ProcurementSearchFeedbackListSchema)
@limiter.limit("60/minute")
def feedback_list(
    query_data: dict[str, Any],
    profile_id: str,
) -> dict[str, Any] | Any:
    try:
        limit = int(query_data["limit"])
        offset = int(query_data["offset"])
        rows, total = list_procurement_search_feedback(
            db.session(),
            _uuid(profile_id, resource="Perfil"),
            include_history=bool(query_data["include_history"]),
            limit=limit,
            offset=offset,
        )
    except (
        ProcurementSearchFeedbackNotFound,
        ProcurementSearchProfileNotFound,
    ) as error:
        return _error(error)
    return {
        "items": [serialize_procurement_search_feedback(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@bp.get("/<profile_id>/feedback-digest")
@require_permission("opportunity.read")
@bp.output(ProcurementSearchFeedbackDigestSchema)
@limiter.limit("60/minute")
def feedback_digest(profile_id: str) -> dict[str, Any] | Any:
    try:
        return build_procurement_search_feedback_digest(
            db.session(),
            _uuid(profile_id, resource="Perfil"),
        )
    except (
        ProcurementSearchFeedbackNotFound,
        ProcurementSearchProfileNotFound,
    ) as error:
        return _error(error)
