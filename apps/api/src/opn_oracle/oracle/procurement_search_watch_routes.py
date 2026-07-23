"""HTTP boundary for deterministic procurement-search vigilance."""

from __future__ import annotations

import uuid
from typing import Any

from apiflask import APIBlueprint, Schema
from apiflask.fields import Boolean, Dict, Integer, List, Raw, String
from flask import Response, g
from flask_login import current_user
from marshmallow import validate

from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db, limiter
from opn_oracle.oracle.procurement_search_profiles import ProcurementSearchProfileValidationError
from opn_oracle.oracle.procurement_search_watch import (
    ProcurementSearchWatchConflict,
    ProcurementSearchWatchNotFound,
    configure_procurement_search_watch,
    list_procurement_search_watch_items,
    list_procurement_search_watches,
    mark_watch_items_reviewed,
    serialize_procurement_search_watch,
)

bp = APIBlueprint(
    "procurement_search_watches",
    __name__,
    url_prefix="/api/v1/procurement-search-watches",
    tag="Vigilancia incremental de licitaciones",
)


class WatchResponseSchema(Schema):
    id = String(required=True)
    profile_id = String(required=True)
    tender_search_id = String(required=True)
    name = String(required=True)
    enabled = Boolean(required=True)
    notifications_enabled = Boolean(required=True)
    cadence_seconds = Integer(required=True)
    new_count = Integer(required=True)
    last_success_at = String(allow_none=True)
    last_attempt_at = String(allow_none=True)
    last_error_code = String(allow_none=True)
    last_error_message = String(allow_none=True)
    created_at = String(required=True)
    updated_at = String(required=True)


class WatchListSchema(Schema):
    items = List(Dict(keys=String(), values=Raw()), required=True)


class UpdateWatchSchema(Schema):
    enabled = Boolean(required=True)
    notifications_enabled = Boolean(required=True)
    cadence_seconds = Integer(
        allow_none=True,
        load_default=None,
        validate=validate.OneOf([900, 3600, 86_400]),
    )


class WatchItemsSchema(Schema):
    items = List(Dict(keys=String(), values=Raw()), required=True)


class ReviewWatchItemsSchema(Schema):
    folder_ids = List(
        String(validate=validate.Length(min=1, max=300)),
        required=True,
        validate=validate.Length(min=1, max=200),
    )
    reviewed = Boolean(required=True)


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as error:
        raise ProcurementSearchWatchNotFound("Vigilancia de licitaciones no encontrada.") from error


def _problem(status: int, *, detail: str, code: str, errors: Any = None) -> Response:
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
    if isinstance(error, ProcurementSearchWatchNotFound):
        return _problem(404, detail=str(error), code="not_found")
    if isinstance(error, ProcurementSearchWatchConflict):
        return _problem(409, detail=str(error), code="watch_conflict")
    if isinstance(error, ProcurementSearchProfileValidationError):
        return _problem(422, detail=str(error), code="validation_error", errors=error.errors)
    return _problem(422, detail=str(error), code="validation_error")


@bp.get("")
@require_permission("opportunity.read")
@bp.output(WatchListSchema)
@limiter.limit("60/minute")
def watches_list() -> dict[str, Any]:
    watches = list_procurement_search_watches(db.session())
    return {"items": [serialize_procurement_search_watch(watch) for watch in watches]}


@bp.patch("/<watch_id>")
@require_permission("opportunity.write")
@bp.input(UpdateWatchSchema)
@bp.output(WatchResponseSchema)
@limiter.limit("30/minute")
def watches_update(json_data: dict[str, Any], watch_id: str) -> dict[str, Any] | Response:
    try:
        watch = configure_procurement_search_watch(
            db.session(),
            _uuid(watch_id),
            enabled=bool(json_data["enabled"]),
            notifications_enabled=bool(json_data["notifications_enabled"]),
            cadence_seconds=json_data.get("cadence_seconds"),
            actor_id=current_user.id,
            request_id=getattr(g, "request_id", None),
        )
    except (
        ProcurementSearchWatchNotFound,
        ProcurementSearchWatchConflict,
        ProcurementSearchProfileValidationError,
    ) as error:
        db.session.rollback()
        return _error(error)
    return serialize_procurement_search_watch(watch)


@bp.get("/<watch_id>/items")
@require_permission("opportunity.read")
@bp.output(WatchItemsSchema)
@limiter.limit("60/minute")
def watches_items(watch_id: str) -> dict[str, Any] | Response:
    try:
        return {"items": list_procurement_search_watch_items(db.session(), _uuid(watch_id))}
    except ProcurementSearchWatchNotFound as error:
        return _error(error)


@bp.post("/<watch_id>/items/reviewed")
@require_permission("opportunity.write")
@bp.input(ReviewWatchItemsSchema)
@bp.output(WatchItemsSchema)
@limiter.limit("30/minute")
def watches_review_items(json_data: dict[str, Any], watch_id: str) -> dict[str, Any] | Response:
    try:
        mark_watch_items_reviewed(
            db.session(),
            _uuid(watch_id),
            folder_ids=list(json_data["folder_ids"]),
            reviewed=bool(json_data["reviewed"]),
            actor_id=current_user.id,
            request_id=getattr(g, "request_id", None),
        )
        return {"items": list_procurement_search_watch_items(db.session(), _uuid(watch_id))}
    except (ProcurementSearchWatchNotFound, ProcurementSearchProfileValidationError) as error:
        db.session.rollback()
        return _error(error)
