"""HTTP API MDEV-07 · vigilancias del expediente (confirmación, ciclo de vida, alignment)."""

from __future__ import annotations

import uuid
from typing import Any

from apiflask import APIBlueprint, Schema
from apiflask.fields import UUID as FieldUUID
from apiflask.fields import Boolean, Dict, List, String
from flask import Response, request
from flask_login import current_user
from marshmallow import validate

from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db, limiter
from opn_oracle.oracle.service import ResourceNotFound, VersionConflict
from opn_oracle.oracle.surveillance import (
    ACTION_TYPES,
    CADENCES,
    ORIGINS,
    PreconditionRequired,
    SurveillanceValidationError,
    adopt_alignment,
    confirm_surveillance_action,
    keep_alignment,
    list_actions,
    pause_action,
    resume_action,
    retire_action,
    retry_action,
    serialize_action,
    sync_action,
)

bp = APIBlueprint(
    "dossier_surveillance",
    __name__,
    url_prefix="/api/v1",
    tag="Vigilancias del expediente",
)


class ConfirmSurveillanceSchema(Schema):
    action_type = String(required=True, validate=validate.OneOf(sorted(ACTION_TYPES)))
    cadence = String(load_default="manual", validate=validate.OneOf(sorted(CADENCES)))
    timezone = String(load_default="Europe/Madrid")
    actor_id = FieldUUID(load_default=None, allow_none=True)
    offering_id = FieldUUID(load_default=None, allow_none=True)
    requirement_id = FieldUUID(load_default=None, allow_none=True)
    intent_revision_id = FieldUUID(load_default=None, allow_none=True)
    origin = String(load_default="user", validate=validate.OneOf(sorted(ORIGINS)))
    title = String(load_default=None, allow_none=True)
    notes = String(load_default="")
    keywords = List(String(), load_default=list)
    source_types = List(String(), load_default=list)
    manual_overrides = Dict(load_default=dict)
    create_backend_resources = Boolean(load_default=False)


class ListQuerySchema(Schema):
    action_type = String(
        load_default=None, validate=validate.OneOf(sorted(ACTION_TYPES)), allow_none=True
    )
    actor_id = FieldUUID(load_default=None, allow_none=True)


def _problem(status: int, *, detail: str, code: str) -> Response:
    response, response_status, headers = problem_response(status, detail=detail, code=code)
    response.status_code = response_status
    response.headers.update(headers)
    return response


def _parse_if_match() -> int | None:
    raw = request.headers.get("If-Match", "")
    raw = raw.removeprefix('W/"').removesuffix('"').strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _etag_headers(version: int) -> dict[str, str]:
    return {"ETag": f'W/"{version}"'}


@bp.get("/dossiers/<uuid:dossier_id>/surveillance-actions")
@require_permission("dossier.read")
@bp.input(ListQuerySchema, location="query")
@limiter.limit("60/minute")
def list_surveillance_actions(
    query_data: dict[str, Any],
    dossier_id: uuid.UUID,
) -> dict[str, Any] | Response:
    try:
        rows = list_actions(
            db.session(),
            dossier_id,
            current_user.id,
            action_type=query_data.get("action_type"),
            actor_id=query_data.get("actor_id"),
        )
    except ResourceNotFound:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    return {
        "dossier_id": str(dossier_id),
        "items": [serialize_action(row) for row in rows],
        "total": len(rows),
    }


@bp.post("/dossiers/<uuid:dossier_id>/surveillance-actions/confirm")
@require_permission("dossier.write")
@bp.input(ConfirmSurveillanceSchema, location="json")
@limiter.limit("30/minute")
def confirm_surveillance(
    json_data: dict[str, Any],
    dossier_id: uuid.UUID,
) -> tuple[dict[str, Any], int, dict[str, str]] | Response:
    """Confirm a surveillance type. Viewer cannot call (dossier.write required)."""

    key = request.headers.get("Idempotency-Key", "")
    if len(key) < 8:
        return _problem(
            422, detail="Idempotency-Key es obligatoria (mín. 8).", code="validation_failed"
        )
    try:
        action, created = confirm_surveillance_action(
            db.session(),
            dossier_id=dossier_id,
            actor_user_id=current_user.id,
            payload=json_data,
            request_id=request.headers.get("X-Request-Id"),
            create_backend_resources=bool(json_data.get("create_backend_resources")),
        )
    except ResourceNotFound:
        return _problem(404, detail="Expediente o actor no encontrado.", code="not_found")
    except SurveillanceValidationError as error:
        return _problem(422, detail=str(error), code="validation_failed")
    body = serialize_action(action)
    body["duplicate"] = not created
    body["idempotency_key"] = key
    status = 201 if created else 200
    return body, status, _etag_headers(action.row_version)


def _lifecycle(
    *,
    dossier_id: uuid.UUID,
    action_id: uuid.UUID,
    op_name: str,
) -> tuple[dict[str, Any], int, dict[str, str]] | Response:
    key = request.headers.get("Idempotency-Key", "")
    if len(key) < 8:
        return _problem(
            422, detail="Idempotency-Key es obligatoria (mín. 8).", code="validation_failed"
        )
    expected = _parse_if_match()
    handlers = {
        "pause": pause_action,
        "resume": resume_action,
        "sync": sync_action,
        "retry": retry_action,
        "retire": retire_action,
        "adopt": adopt_alignment,
        "keep": keep_alignment,
    }
    handler = handlers[op_name]
    try:
        action = handler(
            db.session(),
            action_id=action_id,
            actor_user_id=current_user.id,
            expected_version=expected,
            request_id=request.headers.get("X-Request-Id"),
        )
    except PreconditionRequired as error:
        return _problem(428, detail=str(error), code="precondition_required")
    except VersionConflict as error:
        return _problem(409, detail=str(error), code="version_conflict")
    except ResourceNotFound:
        return _problem(404, detail="Vigilancia no encontrada.", code="not_found")
    except SurveillanceValidationError as error:
        return _problem(422, detail=str(error), code="validation_failed")
    if action.dossier_id != dossier_id:
        # IDOR: do not leak cross-dossier existence
        return _problem(404, detail="Vigilancia no encontrada.", code="not_found")
    body = serialize_action(action)
    body["idempotency_key"] = key
    return body, 200, _etag_headers(action.row_version)


@bp.post("/dossiers/<uuid:dossier_id>/surveillance-actions/<uuid:action_id>/pause")
@require_permission("signal.review")
@limiter.limit("30/minute")
def pause_surveillance(dossier_id: uuid.UUID, action_id: uuid.UUID) -> Any:
    return _lifecycle(dossier_id=dossier_id, action_id=action_id, op_name="pause")


@bp.post("/dossiers/<uuid:dossier_id>/surveillance-actions/<uuid:action_id>/resume")
@require_permission("signal.review")
@limiter.limit("30/minute")
def resume_surveillance(dossier_id: uuid.UUID, action_id: uuid.UUID) -> Any:
    return _lifecycle(dossier_id=dossier_id, action_id=action_id, op_name="resume")


@bp.post("/dossiers/<uuid:dossier_id>/surveillance-actions/<uuid:action_id>/sync")
@require_permission("signal.review")
@limiter.limit("30/minute")
def sync_surveillance(dossier_id: uuid.UUID, action_id: uuid.UUID) -> Any:
    return _lifecycle(dossier_id=dossier_id, action_id=action_id, op_name="sync")


@bp.post("/dossiers/<uuid:dossier_id>/surveillance-actions/<uuid:action_id>/retry")
@require_permission("signal.review")
@limiter.limit("30/minute")
def retry_surveillance(dossier_id: uuid.UUID, action_id: uuid.UUID) -> Any:
    return _lifecycle(dossier_id=dossier_id, action_id=action_id, op_name="retry")


@bp.post("/dossiers/<uuid:dossier_id>/surveillance-actions/<uuid:action_id>/retire")
@require_permission("signal.review")
@limiter.limit("30/minute")
def retire_surveillance(dossier_id: uuid.UUID, action_id: uuid.UUID) -> Any:
    return _lifecycle(dossier_id=dossier_id, action_id=action_id, op_name="retire")


@bp.post("/dossiers/<uuid:dossier_id>/surveillance-actions/<uuid:action_id>/alignment/adopt")
@require_permission("dossier.write")
@limiter.limit("30/minute")
def adopt_surveillance_alignment(dossier_id: uuid.UUID, action_id: uuid.UUID) -> Any:
    return _lifecycle(dossier_id=dossier_id, action_id=action_id, op_name="adopt")


@bp.post("/dossiers/<uuid:dossier_id>/surveillance-actions/<uuid:action_id>/alignment/keep")
@require_permission("dossier.write")
@limiter.limit("30/minute")
def keep_surveillance_alignment(dossier_id: uuid.UUID, action_id: uuid.UUID) -> Any:
    return _lifecycle(dossier_id=dossier_id, action_id=action_id, op_name="keep")


@bp.post("/dossiers/<uuid:dossier_id>/surveillance-actions/<uuid:action_id>/alignment/retire")
@require_permission("dossier.write")
@limiter.limit("30/minute")
def retire_surveillance_alignment(dossier_id: uuid.UUID, action_id: uuid.UUID) -> Any:
    # Same as retire lifecycle, exposed under alignment for UI needs_review.
    return _lifecycle(dossier_id=dossier_id, action_id=action_id, op_name="retire")
