"""Public procurement proxy API.

These endpoints keep Signal credentials server-side and expose PLACSP registry
and saved tender-search capabilities to Vector through Oracle permissions.
"""

from __future__ import annotations

from typing import Any, cast

from apiflask import APIBlueprint, Schema
from apiflask.fields import Boolean, Dict, Float, Integer, List, Nested, Raw, String
from flask import Response, g
from marshmallow import ValidationError, validate, validates_schema

from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import limiter
from opn_oracle.integrations.procurement import (
    ProcurementConfigurationError,
    ProcurementProviderError,
    cached_awards,
    cached_suggest,
    cached_tenders,
    create_tender_search,
    delete_tender_search,
    get_tender_search,
    list_tender_searches,
    patch_tender_search,
    procurement_stats,
    run_tender_search,
    uncached_tender_summary,
)

bp = APIBlueprint(
    "procurement",
    __name__,
    url_prefix="/api/v1/procurement",
    tag="Contratación pública",
)


class PaginationQuerySchema(Schema):
    limit = Integer(load_default=20, validate=validate.Range(min=1, max=100))
    offset = Integer(load_default=0, validate=validate.Range(min=0, max=100_000))


class AwardsQuerySchema(PaginationQuerySchema):
    company = String(load_default=None, allow_none=True, validate=validate.Length(max=250))
    buyer = String(load_default=None, allow_none=True, validate=validate.Length(max=250))

    @validates_schema
    def validate_lookup(self, data: dict[str, Any], **kwargs: Any) -> None:
        del kwargs
        company = (data.get("company") or "").strip()
        buyer = (data.get("buyer") or "").strip()
        if len(company) < 2 and len(buyer) < 2:
            raise ValidationError(
                "Indica al menos adjudicatario o comprador con dos caracteres.",
                field_name="company",
            )


class ProcurementSuggestQuerySchema(Schema):
    q = String(required=True, validate=validate.Length(min=2, max=120))
    kind = String(
        load_default="winner",
        validate=validate.OneOf(["winner", "buyer"]),
    )
    limit = Integer(load_default=8, validate=validate.Range(min=1, max=20))


class TendersQuerySchema(PaginationQuerySchema):
    keywords = String(load_default=None, allow_none=True, validate=validate.Length(max=500))
    cpv = String(load_default=None, allow_none=True, validate=validate.Length(max=200))
    min_amount = Float(load_default=None, allow_none=True, validate=validate.Range(min=0))
    max_amount = Float(load_default=None, allow_none=True, validate=validate.Range(min=0))
    deadline_before = String(
        load_default=None,
        allow_none=True,
        validate=validate.Regexp(r"^\d{4}-\d{2}-\d{2}$"),
    )
    buyer = String(load_default=None, allow_none=True, validate=validate.Length(max=250))
    region = String(load_default=None, allow_none=True, validate=validate.Length(max=120))
    active = Boolean(load_default=True)


class TenderSummaryPathSchema(Schema):
    folder_id = String(required=True, validate=validate.Length(min=1, max=200))


class TenderSearchPathSchema(Schema):
    search_id = String(required=True, validate=validate.Length(min=1, max=120))


class TenderSearchRunQuerySchema(PaginationQuerySchema):
    pass


class TenderSearchPayloadSchema(Schema):
    name = String(required=True, validate=validate.Length(min=2, max=120))
    keywords = List(String(validate=validate.Length(min=1, max=120)), required=True)
    filters = Dict(keys=String(validate=validate.Length(max=80)), values=Raw(), load_default=dict)

    @validates_schema
    def validate_keywords(self, data: dict[str, Any], **kwargs: Any) -> None:
        del kwargs
        keywords = data.get("keywords") or []
        if not 1 <= len(keywords) <= 20:
            raise ValidationError("Incluye entre 1 y 20 palabras clave.", field_name="keywords")


class TenderSearchPatchSchema(Schema):
    name = String(validate=validate.Length(min=2, max=120))
    keywords = List(String(validate=validate.Length(min=1, max=120)))
    filters = Dict(keys=String(validate=validate.Length(max=80)), values=Raw())

    @validates_schema
    def validate_partial(self, data: dict[str, Any], **kwargs: Any) -> None:
        del kwargs
        if not data:
            raise ValidationError("Indica al menos un campo para actualizar.")
        if "keywords" in data and not 1 <= len(data["keywords"] or []) <= 20:
            raise ValidationError("Incluye entre 1 y 20 palabras clave.", field_name="keywords")


class AwardsResponseSchema(Schema):
    company_norm = String(load_default="")
    buyer_norm = String(load_default="")
    total = Integer(required=True)
    items = List(Dict(keys=String(), values=Raw()), required=True)
    cached_seconds = Integer(required=True)
    cache_hit = Boolean(required=True)


class ProcurementSuggestResponseSchema(Schema):
    kind = String(required=True)
    suggestions = List(String(), required=True)
    cached_seconds = Integer(required=True)
    cache_hit = Boolean(required=True)


class TendersResponseSchema(Schema):
    keywords = Raw(allow_none=True)
    filters = Dict(keys=String(), values=Raw(), load_default=dict)
    semantics = Dict(keys=String(), values=Raw(), load_default=dict)
    total = Integer(required=True)
    limit = Integer(required=True)
    offset = Integer(required=True)
    items = List(Dict(keys=String(), values=Raw()), required=True)
    cached_seconds = Integer(required=True)
    cache_hit = Boolean(required=True)


class TenderSummaryResponseSchema(Schema):
    cached = Boolean(required=True)
    item = Dict(keys=String(), values=Raw(), required=True)


class StatsResponseSchema(Schema):
    entries = Integer(load_default=0)
    distinct_people = Integer(load_default=0)
    distinct_companies = Integer(load_default=0)
    oldest = String(allow_none=True)
    newest = String(allow_none=True)
    days_processed = Integer(load_default=0)
    placsp_awards = Dict(keys=String(), values=Raw(), load_default=dict)
    placsp_open_tenders = Dict(keys=String(), values=Raw(), load_default=dict)


class TenderSearchResourceSchema(Schema):
    # Omitimos tenant_id: es un identificador externo operativo de Signal, no contrato de UI.
    id = String(allow_none=True)
    name = String(allow_none=True)
    keywords = List(String(), load_default=list)
    filters = Dict(keys=String(), values=Raw(), load_default=dict)
    created_at = String(allow_none=True)
    updated_at = String(allow_none=True)


class TenderSearchListSchema(Schema):
    items = List(Nested(TenderSearchResourceSchema), required=True)


class TenderSearchRunSchema(Schema):
    search = Nested(TenderSearchResourceSchema, required=True)
    results = Dict(keys=String(), values=Raw(), required=True)


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


def _provider_error_response(error: ProcurementProviderError) -> Response:
    return _problem_response_passthrough(
        error.status_code,
        title="No se pudo consultar contratación pública",
        detail=error.detail,
        code=error.code,
        errors=error.errors,
    )


def _configuration_error_response(error: ProcurementConfigurationError) -> Response:
    return _problem_response_passthrough(
        503,
        title="Contratación pública no disponible",
        detail=str(error),
        code="procurement_not_configured",
    )


def _handle_provider_call(function: Any) -> Any:
    try:
        return function()
    except ProcurementConfigurationError as exc:
        return _configuration_error_response(exc)
    except ProcurementProviderError as exc:
        return _provider_error_response(exc)


@bp.get("/awards")
@require_permission("actor.read")
@bp.input(AwardsQuerySchema, location="query")
@bp.output(AwardsResponseSchema)
@limiter.limit("60/minute")
def awards(query_data: dict[str, Any]) -> dict[str, Any] | Any:
    tenant_id = str(g.active_tenant_id)
    return _handle_provider_call(
        lambda: cached_awards(
            tenant_id=tenant_id,
            company=(cast(str | None, query_data.get("company")) or "").strip() or None,
            buyer=(cast(str | None, query_data.get("buyer")) or "").strip() or None,
            limit=int(query_data["limit"]),
            offset=int(query_data["offset"]),
        )
    )


@bp.get("/suggest")
@require_permission("actor.read")
@bp.input(ProcurementSuggestQuerySchema, location="query")
@bp.output(ProcurementSuggestResponseSchema)
@limiter.limit("90/minute")
def suggest(query_data: dict[str, Any]) -> dict[str, Any] | Any:
    tenant_id = str(g.active_tenant_id)
    return _handle_provider_call(
        lambda: cached_suggest(
            tenant_id=tenant_id,
            query=cast(str, query_data["q"]).strip(),
            kind=cast(str, query_data["kind"]),
            limit=int(query_data["limit"]),
        )
    )


@bp.get("/tenders")
@require_permission("opportunity.read")
@bp.input(TendersQuerySchema, location="query")
@bp.output(TendersResponseSchema)
@limiter.limit("60/minute")
def tenders(query_data: dict[str, Any]) -> dict[str, Any] | Any:
    tenant_id = str(g.active_tenant_id)
    return _handle_provider_call(
        lambda: cached_tenders(
            tenant_id=tenant_id,
            keywords=(cast(str | None, query_data.get("keywords")) or "").strip() or None,
            cpv=(cast(str | None, query_data.get("cpv")) or "").strip() or None,
            min_amount=(
                str(query_data["min_amount"]) if query_data.get("min_amount") is not None else None
            ),
            max_amount=(
                str(query_data["max_amount"]) if query_data.get("max_amount") is not None else None
            ),
            deadline_before=cast(str | None, query_data.get("deadline_before")),
            buyer=(cast(str | None, query_data.get("buyer")) or "").strip() or None,
            region=(cast(str | None, query_data.get("region")) or "").strip() or None,
            active=bool(query_data["active"]),
            limit=int(query_data["limit"]),
            offset=int(query_data["offset"]),
        )
    )


@bp.post("/tenders/<path:folder_id>/summary")
@bp.input(TenderSummaryPathSchema, location="path")
@bp.output(TenderSummaryResponseSchema)
@require_permission("opportunity.read")
@limiter.limit("20/minute")
def tender_summary(path_data: dict[str, Any]) -> dict[str, Any] | Any:
    return _handle_provider_call(
        lambda: uncached_tender_summary(folder_id=cast(str, path_data["folder_id"]))
    )


@bp.get("/stats")
@bp.output(StatsResponseSchema)
@require_permission("signal.read")
@limiter.limit("30/minute")
def stats() -> dict[str, Any] | Any:
    return _handle_provider_call(procurement_stats)


@bp.get("/tender-searches")
@bp.output(TenderSearchListSchema)
@require_permission("opportunity.read")
@limiter.limit("60/minute")
def tender_searches_list() -> dict[str, Any] | Any:
    return _handle_provider_call(list_tender_searches)


@bp.post("/tender-searches")
@bp.input(TenderSearchPayloadSchema)
@bp.output(TenderSearchResourceSchema, status_code=201)
@require_permission("opportunity.write")
@limiter.limit("30/minute")
def tender_searches_create(json_data: dict[str, Any]) -> dict[str, Any] | Any:
    return _handle_provider_call(lambda: create_tender_search(payload=json_data))


@bp.get("/tender-searches/<search_id>")
@bp.input(TenderSearchPathSchema, location="path")
@bp.output(TenderSearchResourceSchema)
@require_permission("opportunity.read")
@limiter.limit("60/minute")
def tender_searches_get(path_data: dict[str, Any]) -> dict[str, Any] | Any:
    return _handle_provider_call(
        lambda: get_tender_search(search_id=cast(str, path_data["search_id"]))
    )


@bp.patch("/tender-searches/<search_id>")
@bp.input(TenderSearchPathSchema, location="path")
@bp.input(TenderSearchPatchSchema)
@bp.output(TenderSearchResourceSchema)
@require_permission("opportunity.write")
@limiter.limit("30/minute")
def tender_searches_patch(
    json_data: dict[str, Any],
    path_data: dict[str, Any],
) -> dict[str, Any] | Any:
    return _handle_provider_call(
        lambda: patch_tender_search(
            search_id=cast(str, path_data["search_id"]),
            payload=json_data,
        )
    )


@bp.delete("/tender-searches/<search_id>")
@bp.input(TenderSearchPathSchema, location="path")
@bp.output(TenderSearchResourceSchema)
@require_permission("opportunity.write")
@limiter.limit("30/minute")
def tender_searches_delete(path_data: dict[str, Any]) -> dict[str, Any] | Any:
    return _handle_provider_call(
        lambda: delete_tender_search(search_id=cast(str, path_data["search_id"]))
    )


@bp.get("/tender-searches/<search_id>/run")
@bp.input(TenderSearchPathSchema, location="path")
@bp.input(TenderSearchRunQuerySchema, location="query")
@bp.output(TenderSearchRunSchema)
@require_permission("opportunity.read")
@limiter.limit("60/minute")
def tender_searches_run(
    query_data: dict[str, Any],
    path_data: dict[str, Any],
) -> dict[str, Any] | Any:
    return _handle_provider_call(
        lambda: run_tender_search(
            search_id=cast(str, path_data["search_id"]),
            limit=int(query_data["limit"]),
            offset=int(query_data["offset"]),
        )
    )
