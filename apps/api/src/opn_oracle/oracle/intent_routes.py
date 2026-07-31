"""HTTP boundary for versioned dossier intent (MEMSOL-03)."""

from __future__ import annotations

import uuid
from typing import Any

from apiflask import APIBlueprint, Schema
from apiflask.fields import Dict, Integer, List, Nested, Raw, String
from flask import Response, g
from flask_login import current_user
from marshmallow import validate
from sqlalchemy import select

from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db, limiter
from opn_oracle.oracle.intent import (
    IntentConflict,
    IntentNotFound,
    IntentValidationError,
    accept_revision,
    create_draft,
    create_offering,
    create_requirement,
    get_revision,
    intent_overview,
    list_offerings,
    list_requirements,
    reject_revision,
    serialize_intent_revision,
    serialize_offering,
    serialize_requirement,
    update_draft,
)
from opn_oracle.oracle.models import StrategicDossier
from opn_oracle.oracle.policy import dossier_accessible

bp = APIBlueprint(
    "dossier_intent",
    __name__,
    url_prefix="/api/v1",
    tag="Intención del expediente",
)


class SourceRefSchema(Schema):
    kind = String(required=True, validate=validate.Length(min=1, max=120))
    ref = String(required=True, validate=validate.Length(min=1, max=500))
    label = String(allow_none=True, validate=validate.Length(max=300))


class IntentDraftCreateSchema(Schema):
    schema_key = String(
        required=True,
        validate=validate.OneOf(
            [
                "market",
                "procurement",
                "research",
                "competitive-intelligence",
                "custom",
            ]
        ),
    )
    schema_version = String(
        required=True,
        validate=validate.Regexp(r"^v[0-9]+$"),
    )
    request_text = String(required=True, validate=validate.Length(min=1, max=20000))
    structured_spec = Dict(keys=String(), values=Raw(), load_default=dict)
    source_refs = List(Nested(SourceRefSchema), load_default=list, validate=validate.Length(max=50))


class IntentDraftPatchSchema(Schema):
    expected_row_version = Integer(required=True, validate=validate.Range(min=1))
    schema_key = String(
        validate=validate.OneOf(
            [
                "market",
                "procurement",
                "research",
                "competitive-intelligence",
                "custom",
            ]
        ),
    )
    schema_version = String(validate=validate.Regexp(r"^v[0-9]+$"))
    request_text = String(validate=validate.Length(min=1, max=20000))
    structured_spec = Dict(keys=String(), values=Raw())
    source_refs = List(Nested(SourceRefSchema), validate=validate.Length(max=50))


class IntentRevisionResponseSchema(Schema):
    id = String(required=True)
    tenant_id = String(required=True)
    dossier_id = String(required=True)
    version = Integer(required=True)
    schema_key = String(required=True)
    schema_version = String(required=True)
    request_text = String(required=True)
    structured_spec = Dict(keys=String(), values=Raw(), required=True)
    status = String(required=True)
    content_hash = String(required=True)
    source_refs = List(Dict(keys=String(), values=String()), required=True)
    proposed_by_user_id = String(allow_none=True)
    accepted_by_user_id = String(allow_none=True)
    accepted_at = String(allow_none=True)
    row_version = Integer(required=True)
    created_at = String(allow_none=True)
    updated_at = String(allow_none=True)


class IntentOverviewResponseSchema(Schema):
    current = Nested(IntentRevisionResponseSchema, allow_none=True)
    revisions = List(Nested(IntentRevisionResponseSchema), required=True)


class RequirementCreateSchema(Schema):
    class_ = String(
        data_key="class",
        attribute="class",
        required=True,
        validate=validate.OneOf(
            [
                "market_scan",
                "competitive_watch",
                "procurement_fit",
                "actor_monitor",
                "research_question",
                "risk_watch",
                "custom",
            ]
        ),
    )
    priority = String(
        load_default="medium",
        validate=validate.OneOf(["low", "medium", "high", "critical"]),
    )
    question = String(required=True, validate=validate.Length(min=1, max=2000))
    decision_to_support = String(load_default="", validate=validate.Length(max=2000))
    scope = Dict(keys=String(), values=Raw(), load_default=dict)
    exclusions = Dict(keys=String(), values=Raw(), load_default=dict)
    success_criteria = List(
        String(validate=validate.Length(max=500)),
        load_default=list,
        validate=validate.Length(max=20),
    )
    status = String(
        load_default="active",
        validate=validate.OneOf(["active", "paused", "needs_review", "retired"]),
    )
    alignment_state = String(
        load_default="aligned",
        validate=validate.OneOf(["aligned", "needs_review", "overridden"]),
    )
    intent_revision_id = String(allow_none=True)


class RequirementResponseSchema(Schema):
    id = String(required=True)
    tenant_id = String(required=True)
    dossier_id = String(required=True)
    intent_revision_id = String(allow_none=True)
    class_ = String(data_key="class", attribute="class", required=True)
    priority = String(required=True)
    question = String(required=True)
    decision_to_support = String(required=True)
    scope = Dict(keys=String(), values=Raw(), required=True)
    exclusions = Dict(keys=String(), values=Raw(), required=True)
    success_criteria = List(String(), required=True)
    status = String(required=True)
    alignment_state = String(required=True)
    created_at = String(allow_none=True)
    updated_at = String(allow_none=True)


class RequirementListSchema(Schema):
    items = List(Nested(RequirementResponseSchema), required=True)


class OfferingCreateSchema(Schema):
    name = String(required=True, validate=validate.Length(min=1, max=300))
    aliases = List(String(validate=validate.Length(max=200)), load_default=list)
    taxonomies = Dict(keys=String(), values=Raw(), load_default=dict)
    description = String(load_default="", validate=validate.Length(max=5000))
    status = String(load_default="active", validate=validate.OneOf(["active", "retired"]))
    intent_revision_id = String(allow_none=True)


class OfferingResponseSchema(Schema):
    id = String(required=True)
    tenant_id = String(required=True)
    dossier_id = String(required=True)
    intent_revision_id = String(allow_none=True)
    name = String(required=True)
    aliases = List(String(), required=True)
    taxonomies = Dict(keys=String(), values=Raw(), required=True)
    description = String(required=True)
    status = String(required=True)
    created_at = String(allow_none=True)
    updated_at = String(allow_none=True)


class OfferingListSchema(Schema):
    items = List(Nested(OfferingResponseSchema), required=True)


def _problem(
    status: int,
    *,
    detail: str,
    code: str,
    errors: Any = None,
    title: str | None = None,
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
    if isinstance(error, IntentNotFound):
        return _problem(404, detail=str(error), code="not_found")
    if isinstance(error, IntentConflict):
        return _problem(409, detail=str(error), code="version_conflict")
    if isinstance(error, IntentValidationError):
        return _problem(
            422,
            detail=str(error),
            code="validation_error",
            errors=error.errors,
        )
    return _problem(422, detail=str(error), code="validation_error")


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


@bp.get("/dossiers/<uuid:dossier_id>/intent")
@require_permission("dossier.read")
@bp.output(IntentOverviewResponseSchema)
@limiter.limit("60/minute")
def intent_get(dossier_id: uuid.UUID) -> dict[str, Any] | Response:
    if _dossier_or_404(dossier_id, write=False) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    try:
        return intent_overview(db.session(), dossier_id)
    except IntentNotFound as error:
        return _error(error)


@bp.post("/dossiers/<uuid:dossier_id>/intent/drafts")
@require_permission("dossier.write")
@bp.input(IntentDraftCreateSchema)
@bp.output(IntentRevisionResponseSchema, status_code=201)
@limiter.limit("30/minute")
def intent_create_draft(
    json_data: dict[str, Any],
    dossier_id: uuid.UUID,
) -> dict[str, Any] | Response:
    if _dossier_or_404(dossier_id, write=True) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    try:
        revision = create_draft(
            db.session(),
            dossier_id=dossier_id,
            payload=json_data,
            actor_id=current_user.id,
            request_id=getattr(g, "request_id", None),
        )
    except (IntentValidationError, IntentNotFound, IntentConflict) as error:
        db.session.rollback()
        return _error(error)
    return serialize_intent_revision(revision)


@bp.patch("/dossiers/<uuid:dossier_id>/intent/drafts/<uuid:revision_id>")
@require_permission("dossier.write")
@bp.input(IntentDraftPatchSchema)
@bp.output(IntentRevisionResponseSchema)
@limiter.limit("30/minute")
def intent_update_draft(
    json_data: dict[str, Any],
    dossier_id: uuid.UUID,
    revision_id: uuid.UUID,
) -> dict[str, Any] | Response:
    if _dossier_or_404(dossier_id, write=True) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    try:
        revision = get_revision(db.session(), revision_id)
        if revision.dossier_id != dossier_id:
            raise IntentNotFound("Revisión de intención no encontrada.")
        expected = json_data.pop("expected_row_version")
        revision = update_draft(
            db.session(),
            revision_id=revision_id,
            payload=json_data,
            expected_row_version=expected,
            actor_id=current_user.id,
            request_id=getattr(g, "request_id", None),
        )
    except (IntentValidationError, IntentNotFound, IntentConflict) as error:
        db.session.rollback()
        return _error(error)
    return serialize_intent_revision(revision)


@bp.post("/dossiers/<uuid:dossier_id>/intent/drafts/<uuid:revision_id>/accept")
@require_permission("dossier.write")
@bp.output(IntentRevisionResponseSchema)
@limiter.limit("20/minute")
def intent_accept_draft(
    dossier_id: uuid.UUID,
    revision_id: uuid.UUID,
) -> dict[str, Any] | Response:
    if _dossier_or_404(dossier_id, write=True) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    try:
        revision = get_revision(db.session(), revision_id)
        if revision.dossier_id != dossier_id:
            raise IntentNotFound("Revisión de intención no encontrada.")
        revision = accept_revision(
            db.session(),
            revision_id=revision_id,
            actor_id=current_user.id,
            request_id=getattr(g, "request_id", None),
        )
    except (IntentValidationError, IntentNotFound, IntentConflict) as error:
        db.session.rollback()
        return _error(error)
    return serialize_intent_revision(revision)


@bp.post("/dossiers/<uuid:dossier_id>/intent/drafts/<uuid:revision_id>/reject")
@require_permission("dossier.write")
@bp.output(IntentRevisionResponseSchema)
@limiter.limit("20/minute")
def intent_reject_draft(
    dossier_id: uuid.UUID,
    revision_id: uuid.UUID,
) -> dict[str, Any] | Response:
    if _dossier_or_404(dossier_id, write=True) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    try:
        revision = get_revision(db.session(), revision_id)
        if revision.dossier_id != dossier_id:
            raise IntentNotFound("Revisión de intención no encontrada.")
        revision = reject_revision(
            db.session(),
            revision_id=revision_id,
            actor_id=current_user.id,
            request_id=getattr(g, "request_id", None),
        )
    except (IntentValidationError, IntentNotFound, IntentConflict) as error:
        db.session.rollback()
        return _error(error)
    return serialize_intent_revision(revision)


@bp.get("/dossiers/<uuid:dossier_id>/requirements")
@require_permission("dossier.read")
@bp.output(RequirementListSchema)
@limiter.limit("60/minute")
def requirements_list(dossier_id: uuid.UUID) -> dict[str, Any] | Response:
    if _dossier_or_404(dossier_id, write=False) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    return {
        "items": [
            serialize_requirement(item) for item in list_requirements(db.session(), dossier_id)
        ]
    }


@bp.post("/dossiers/<uuid:dossier_id>/requirements")
@require_permission("dossier.write")
@bp.input(RequirementCreateSchema)
@bp.output(RequirementResponseSchema, status_code=201)
@limiter.limit("30/minute")
def requirements_create(
    json_data: dict[str, Any],
    dossier_id: uuid.UUID,
) -> dict[str, Any] | Response:
    if _dossier_or_404(dossier_id, write=True) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    # Marshmallow may expose "class" via data_key
    payload = dict(json_data)
    if "class_" in payload and "class" not in payload:
        payload["class"] = payload.pop("class_")
    try:
        requirement = create_requirement(
            db.session(),
            dossier_id=dossier_id,
            payload=payload,
            actor_id=current_user.id,
            request_id=getattr(g, "request_id", None),
        )
    except (IntentValidationError, IntentNotFound, IntentConflict) as error:
        db.session.rollback()
        return _error(error)
    return serialize_requirement(requirement)


@bp.get("/dossiers/<uuid:dossier_id>/offerings")
@require_permission("dossier.read")
@bp.output(OfferingListSchema)
@limiter.limit("60/minute")
def offerings_list(dossier_id: uuid.UUID) -> dict[str, Any] | Response:
    if _dossier_or_404(dossier_id, write=False) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    return {
        "items": [serialize_offering(item) for item in list_offerings(db.session(), dossier_id)]
    }


@bp.post("/dossiers/<uuid:dossier_id>/offerings")
@require_permission("dossier.write")
@bp.input(OfferingCreateSchema)
@bp.output(OfferingResponseSchema, status_code=201)
@limiter.limit("30/minute")
def offerings_create(
    json_data: dict[str, Any],
    dossier_id: uuid.UUID,
) -> dict[str, Any] | Response:
    if _dossier_or_404(dossier_id, write=True) is None:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    try:
        offering = create_offering(
            db.session(),
            dossier_id=dossier_id,
            payload=json_data,
            actor_id=current_user.id,
            request_id=getattr(g, "request_id", None),
        )
    except (IntentValidationError, IntentNotFound, IntentConflict) as error:
        db.session.rollback()
        return _error(error)
    return serialize_offering(offering)
