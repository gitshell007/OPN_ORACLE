"""Entity intelligence proxy API.

Vector uses these endpoints for global actor discovery.  They intentionally
proxy read-only Signal calls through Flask to keep credentials and tenant
mapping server-side.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from apiflask import APIBlueprint, Schema
from apiflask.fields import Boolean, Dict, Integer, List, Raw, String
from flask import Response, g, request
from flask_login import current_user
from marshmallow import validate
from sqlalchemy import select

from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.common.request_context import get_correlation_id, get_request_id
from opn_oracle.extensions import db, limiter
from opn_oracle.integrations.entity_intel import (
    EntityIntelConfigurationError,
    EntityIntelProviderError,
    cached_dossier,
    cached_graph,
    cached_registry,
    cached_suggest,
    resolve_signal_external_tenant_id,
)
from opn_oracle.jobs.service import serialize_job
from opn_oracle.oracle.entity_dossier_report import (
    ENTITY_DOSSIER_REPORT_JOB,
    enqueue_entity_dossier_report,
    entity_key,
    incorporate_entity_dossier_report,
    serialize_entity_report_job,
)
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.reporting.service import ReportWorkflowError, serialize_report

bp = APIBlueprint(
    "entity_intel",
    __name__,
    url_prefix="/api/v1/entity-intel",
    tag="Inteligencia de entidades",
)


class EntityKindQuerySchema(Schema):
    kind = String(load_default="company", validate=validate.OneOf(["company", "person"]))


class EntitySuggestQuerySchema(EntityKindQuerySchema):
    q = String(required=True, validate=validate.Length(min=3, max=200))
    limit = Integer(load_default=8, validate=validate.Range(min=1, max=20))


class EntitySuggestResponseSchema(Schema):
    kind = String(required=True)
    suggestions = List(String(), required=True)
    cached_seconds = Integer(required=True)
    cache_hit = Boolean(required=True)


class EntityGraphQuerySchema(Schema):
    name = String(required=True, validate=validate.Length(min=2, max=300))
    type = String(load_default="company", validate=validate.OneOf(["company", "person"]))
    depth = Integer(load_default=2, validate=validate.Range(min=1, max=2))
    active_only = Boolean(load_default=False)


class EntityGraphResponseSchema(Schema):
    center = Raw(required=False, allow_none=True)
    nodes = List(Dict(keys=String(), values=Raw()), required=True)
    edges = List(Dict(keys=String(), values=Raw()), required=True)
    truncated = Boolean(required=True)
    note = String(required=False, allow_none=True)
    cached_seconds = Integer(required=True)
    cache_hit = Boolean(required=True)


class EntityRegistryQuerySchema(Schema):
    name = String(required=True, validate=validate.Length(min=2, max=300))
    type = String(load_default="company", validate=validate.OneOf(["company", "person"]))
    limit = Integer(load_default=50, validate=validate.Range(min=1, max=200))
    offset = Integer(load_default=0, validate=validate.Range(min=0, max=10000))


class EntityRegistryResponseSchema(Schema):
    query = Raw(required=False, allow_none=True)
    company_norm = Raw(required=False, allow_none=True)
    person_norm = Raw(required=False, allow_none=True)
    total = Integer(required=False, allow_none=True)
    items = List(Dict(keys=String(), values=Raw()), required=True)
    companies = List(Raw(), required=False)
    roles = List(Raw(), required=False)
    profile = Dict(keys=String(), values=Raw(), required=False, allow_none=True)
    cached_seconds = Integer(required=True)
    cache_hit = Boolean(required=True)


class EntityDossierQuerySchema(Schema):
    name = String(required=True, validate=validate.Length(min=2, max=300))
    type = String(load_default="company", validate=validate.OneOf(["company", "person"]))


class EntityDossierResponseSchema(Schema):
    entity = Dict(keys=String(), values=Raw(), required=True)
    sections = Dict(keys=String(), values=Raw(), required=True)
    cached_seconds = Integer(required=True)
    cache_hit = Boolean(required=True)


class EntityReportRequestSchema(Schema):
    name = String(required=True, validate=validate.Length(min=2, max=300))
    type = String(load_default="company", validate=validate.OneOf(["company", "person"]))


class EntityReportListQuerySchema(EntityReportRequestSchema):
    limit = Integer(load_default=10, validate=validate.Range(min=1, max=50))


class EntityReportIncorporateSchema(Schema):
    dossier_id = String(required=True, validate=validate.Length(min=32, max=40))


def _problem_response_passthrough(
    status: int,
    *,
    title: str,
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


def _provider_error_response(error: EntityIntelProviderError) -> Response:
    if error.status_code == 403 and error.code == "entity_service_disabled":
        detail = (
            "El servicio de inteligencia de entidades está apagado en el administrador de Signal."
        )
    else:
        detail = error.detail
    return _problem_response_passthrough(
        error.status_code,
        title="No se pudo consultar la inteligencia de entidades",
        detail=detail,
        code=error.code,
        errors=error.errors,
    )


def _configuration_error_response(error: EntityIntelConfigurationError) -> Response:
    return _problem_response_passthrough(
        503,
        title="Inteligencia de entidades no disponible",
        detail=str(error),
        code="entity_intel_not_configured",
    )


@bp.get("/suggest")
@require_permission("actor.read")
@bp.input(EntitySuggestQuerySchema, location="query")
@bp.output(EntitySuggestResponseSchema)
@limiter.limit("60/minute")
def suggest_entities(query_data: dict[str, Any]) -> dict[str, Any] | Any:
    tenant_id = str(g.active_tenant_id)
    try:
        return cached_suggest(
            tenant_id=tenant_id,
            query=cast(str, query_data["q"]).strip(),
            kind=cast(Any, query_data["kind"]),
            limit=int(query_data["limit"]),
        )
    except EntityIntelConfigurationError as exc:
        return _configuration_error_response(exc)
    except EntityIntelProviderError as exc:
        return _provider_error_response(exc)


@bp.get("/graph")
@require_permission("actor.read")
@bp.input(EntityGraphQuerySchema, location="query")
@bp.output(EntityGraphResponseSchema)
@limiter.limit("30/minute")
def entity_graph(query_data: dict[str, Any]) -> dict[str, Any] | Any:
    tenant_id = str(g.active_tenant_id)
    try:
        external_tenant_id = resolve_signal_external_tenant_id()
        return cached_graph(
            tenant_id=tenant_id,
            name=cast(str, query_data["name"]).strip(),
            kind=cast(Any, query_data["type"]),
            depth=int(query_data["depth"]),
            active_only=bool(query_data["active_only"]),
            external_tenant_id=external_tenant_id,
        )
    except EntityIntelConfigurationError as exc:
        return _configuration_error_response(exc)
    except EntityIntelProviderError as exc:
        return _provider_error_response(exc)


@bp.get("/registry")
@require_permission("actor.read")
@bp.input(EntityRegistryQuerySchema, location="query")
@bp.output(EntityRegistryResponseSchema)
@limiter.limit("30/minute")
def entity_registry(query_data: dict[str, Any]) -> dict[str, Any] | Any:
    tenant_id = str(g.active_tenant_id)
    try:
        return cached_registry(
            tenant_id=tenant_id,
            name=cast(str, query_data["name"]).strip(),
            kind=cast(Any, query_data["type"]),
            limit=int(query_data["limit"]),
            offset=int(query_data["offset"]),
        )
    except EntityIntelConfigurationError as exc:
        return _configuration_error_response(exc)
    except EntityIntelProviderError as exc:
        return _provider_error_response(exc)


@bp.get("/dossier")
@require_permission("actor.read")
@bp.input(EntityDossierQuerySchema, location="query")
@bp.output(EntityDossierResponseSchema)
@limiter.limit("15/minute")
def entity_dossier(query_data: dict[str, Any]) -> dict[str, Any] | Any:
    tenant_id = str(g.active_tenant_id)
    try:
        external_tenant_id = resolve_signal_external_tenant_id()
        return cached_dossier(
            tenant_id=tenant_id,
            name=cast(str, query_data["name"]).strip(),
            kind=cast(Any, query_data["type"]),
            external_tenant_id=external_tenant_id,
        )
    except EntityIntelConfigurationError as exc:
        return _configuration_error_response(exc)
    except EntityIntelProviderError as exc:
        return _provider_error_response(exc)


@bp.post("/reports")
@require_permission("report.generate")
@bp.input(EntityReportRequestSchema, location="json")
@limiter.limit("10/minute")
def create_entity_report(json_data: dict[str, Any]) -> Any:
    key = request.headers.get("Idempotency-Key", "").strip()
    if not 8 <= len(key) <= 200:
        return problem_response(
            422,
            detail="Idempotency-Key es obligatoria y debe tener entre 8 y 200 caracteres.",
            code="idempotency_key_required",
        )
    try:
        job = enqueue_entity_dossier_report(
            name=cast(str, json_data["name"]),
            kind=cast(str, json_data["type"]),
            idempotency_key=key,
            requested_by_user_id=current_user.id,
            correlation_id=get_correlation_id(),
            request_id=get_request_id(),
        )
    except ValueError as exc:
        db.session.rollback()
        return problem_response(409, detail=str(exc), code="idempotency_conflict")
    return {"job": serialize_job(job), "job_id": str(job.id)}, 202


@bp.get("/reports")
@require_permission("report.generate")
@bp.input(EntityReportListQuerySchema, location="query")
def list_entity_reports(query_data: dict[str, Any]) -> dict[str, Any]:
    name = cast(str, query_data["name"]).strip()
    kind = cast(str, query_data["type"])
    key = entity_key(name=name, kind=kind)
    limit = int(query_data["limit"])
    rows = db.session.scalars(
        select(BackgroundJob)
        .where(
            BackgroundJob.tenant_id == g.active_tenant_id,
            BackgroundJob.job_type == ENTITY_DOSSIER_REPORT_JOB,
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(max(limit, 25))
    ).all()
    visible = [
        row
        for row in rows
        if row.input_payload.get("entity_key") == key
        and (
            row.requested_by_user_id == current_user.id
            or row.result_ref.get("incorporated_dossier_id")
        )
    ]
    return {"data": [serialize_entity_report_job(row) for row in visible[:limit]]}


@bp.post("/reports/<uuid:job_id>/incorporate")
@require_permission("report.generate")
@bp.input(EntityReportIncorporateSchema, location="json")
def incorporate_entity_report(job_id: uuid.UUID, payload: dict[str, Any]) -> Any:
    try:
        dossier_id = uuid.UUID(str(payload["dossier_id"]))
    except ValueError:
        return problem_response(422, detail="dossier_id no válido.", code="validation_error")
    try:
        report, job = incorporate_entity_dossier_report(
            job_id=job_id,
            dossier_id=dossier_id,
            actor_id=current_user.id,
        )
    except ReportWorkflowError as exc:
        db.session.rollback()
        return problem_response(422, detail=str(exc), code="entity_report_not_ready")
    return {"report": serialize_report(report, detail=True), "job": serialize_job(job)}, 201
