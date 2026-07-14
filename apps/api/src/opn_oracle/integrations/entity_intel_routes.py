"""Entity intelligence proxy API.

Vector uses these endpoints for global actor discovery.  They intentionally
proxy read-only Signal calls through Flask to keep credentials and tenant
mapping server-side.
"""

from __future__ import annotations

from typing import Any, cast

from apiflask import APIBlueprint, Schema
from apiflask.fields import Boolean, Dict, Integer, List, Raw, String
from flask import Response, g
from marshmallow import validate

from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import limiter
from opn_oracle.integrations.entity_intel import (
    EntityIntelConfigurationError,
    EntityIntelProviderError,
    cached_graph,
    cached_suggest,
    resolve_signal_external_tenant_id,
)

bp = APIBlueprint(
    "entity_intel",
    __name__,
    url_prefix="/api/v1/entity-intel",
    tag="Inteligencia de entidades",
)


class EntityKindQuerySchema(Schema):
    kind = String(load_default="company", validate=validate.OneOf(["company", "person"]))


class EntitySuggestQuerySchema(EntityKindQuerySchema):
    q = String(required=True, validate=validate.Length(min=2, max=200))
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
    active_only = Boolean(load_default=True)


class EntityGraphResponseSchema(Schema):
    center = Raw(required=False, allow_none=True)
    nodes = List(Dict(keys=String(), values=Raw()), required=True)
    edges = List(Dict(keys=String(), values=Raw()), required=True)
    truncated = Boolean(required=True)
    note = String(required=False, allow_none=True)
    cached_seconds = Integer(required=True)
    cache_hit = Boolean(required=True)


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
    return _problem_response_passthrough(
        error.status_code,
        title="No se pudo consultar la inteligencia de entidades",
        detail=error.detail,
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
@bp.input(EntitySuggestQuerySchema, location="query")
@bp.output(EntitySuggestResponseSchema)
@require_permission("actor.read")
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
@bp.input(EntityGraphQuerySchema, location="query")
@bp.output(EntityGraphResponseSchema)
@require_permission("actor.read")
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
