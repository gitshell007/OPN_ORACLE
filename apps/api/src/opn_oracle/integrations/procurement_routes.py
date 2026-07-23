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
from pydantic import ValidationError as PydanticValidationError

from opn_oracle.ai.tender_search_wizard import (
    TenderSearchPlanValidationError,
    postvalidate_tender_search_plan,
)
from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import limiter
from opn_oracle.integrations.procurement import (
    ProcurementConfigurationError,
    ProcurementProviderError,
    cached_awards,
    cached_comparable_profile,
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
from opn_oracle.oracle.procurement_search_preview import (
    SearchPlanExecutionError,
    preview_search_plan,
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
    awarded_from = String(
        load_default=None,
        allow_none=True,
        validate=validate.Regexp(r"^\d{4}-\d{2}-\d{2}$"),
    )
    awarded_to = String(
        load_default=None,
        allow_none=True,
        validate=validate.Regexp(r"^\d{4}-\d{2}-\d{2}$"),
    )

    @validates_schema
    def validate_lookup(self, data: dict[str, Any], **kwargs: Any) -> None:
        del kwargs
        for field in ("awarded_from", "awarded_to"):
            if data.get(field) is not None:
                raise ValidationError(
                    "Signal v1 no admite todavía rangos por fecha de adjudicación.",
                    field_name=field,
                )
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


class ComparableProfileQuerySchema(Schema):
    company = String(required=True, validate=validate.Length(min=2, max=250))


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
    published_from = String(
        load_default=None,
        allow_none=True,
        validate=validate.Regexp(r"^\d{4}-\d{2}-\d{2}$"),
    )
    published_to = String(
        load_default=None,
        allow_none=True,
        validate=validate.Regexp(r"^\d{4}-\d{2}-\d{2}$"),
    )
    deadline_from = String(
        load_default=None,
        allow_none=True,
        validate=validate.Regexp(r"^\d{4}-\d{2}-\d{2}$"),
    )
    deadline_to = String(
        load_default=None,
        allow_none=True,
        validate=validate.Regexp(r"^\d{4}-\d{2}-\d{2}$"),
    )
    buyer = String(load_default=None, allow_none=True, validate=validate.Length(max=250))
    region = String(load_default=None, allow_none=True, validate=validate.Length(max=120))
    scope = String(
        load_default=None,
        allow_none=True,
        validate=validate.OneOf(["active", "historical", "all"]),
    )
    active = Boolean(load_default=None, allow_none=True)

    @validates_schema
    def validate_temporal_contract(self, data: dict[str, Any], **kwargs: Any) -> None:
        del kwargs
        if data.get("scope") is not None and data.get("active") is not None:
            raise ValidationError(
                "Usa scope o el alias deprecado active, pero no ambos.",
                field_name="scope",
            )
        if data.get("scope") == "historical":
            raise ValidationError(
                "Signal v1 no permite aislar licitaciones históricas. "
                "El histórico disponible se consulta por adjudicaciones.",
                field_name="scope",
            )
        for field in ("published_from", "published_to", "deadline_from", "deadline_to"):
            if data.get(field) is not None:
                raise ValidationError(
                    "Signal v1 no admite todavía este rango temporal.",
                    field_name=field,
                )


class TenderSummaryPathSchema(Schema):
    folder_id = String(required=True, validate=validate.Length(min=1, max=200))


class TenderSearchPathSchema(Schema):
    search_id = String(required=True, validate=validate.Length(min=1, max=120))


class TenderSearchRunQuerySchema(PaginationQuerySchema):
    pass


class TenderSearchPlanPreviewPayloadSchema(Schema):
    plan = Dict(keys=String(), values=Raw(allow_none=True), required=True)


class TenderSearchPlanPreviewResponseSchema(Schema):
    plan = Dict(keys=String(), values=Raw(), required=True)
    preview = Dict(keys=String(), values=Raw(), required=True)


def _validate_saved_search_temporal_scope(filters: dict[str, Any]) -> None:
    scope = filters.get("scope")
    active_alias = filters.get("active")
    if scope is not None and active_alias is not None:
        raise ValidationError(
            "Usa scope o el alias deprecado active, pero no ambos.",
            field_name="filters",
        )
    if scope not in (None, "active") or active_alias is False:
        raise ValidationError(
            "Signal v1 solo conserva búsquedas guardadas de licitaciones activas.",
            field_name="filters",
        )


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
        _validate_saved_search_temporal_scope(data.get("filters") or {})


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
        if "filters" in data:
            _validate_saved_search_temporal_scope(data["filters"] or {})


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


class ComparableIdentitySchema(Schema):
    oracle_normalized_name = String(required=True)
    oracle_company_core = String(required=True)
    legal_identity_verified = Boolean(required=True)


class ComparableMeasurementSchema(Schema):
    source = String(required=True)
    unit = String(required=True)
    fields_used = List(String(), required=True)
    llm_calls = Integer(required=True)
    regions_inferred = Boolean(required=True)
    dates_repaired = Boolean(required=True)


class ComparableCorpusSchema(Schema):
    provider_total_rows = Integer(required=True)
    analyzed_rows = Integer(required=True)
    row_cap = Integer(required=True)
    truncated = Boolean(required=True)
    aggregated_contracts = Integer(required=True)
    ignored_rows_without_folder_id = Integer(required=True)


class ComparableInvalidDateSchema(Schema):
    raw_value = String(required=True)
    rows = Integer(required=True)


class ComparableDateWindowSchema(Schema):
    method = String(required=True)
    raw_observed_start = String(required=True, allow_none=True)
    raw_observed_end = String(required=True, allow_none=True)
    rows_with_valid_date = Integer(required=True)
    rows_without_date = Integer(required=True)
    rows_with_invalid_date = Integer(required=True)
    invalid_date_examples = List(Nested(ComparableInvalidDateSchema), required=True)


class ComparableTaxonomySchema(Schema):
    version = String(required=True)
    language = String(required=True)
    source_uri = String(required=True)
    downloaded_at = String(required=True)
    code_count = Integer(required=True)


class ComparableInvalidCPVSchema(Schema):
    raw_value = String(required=True)
    contracts = Integer(required=True)


class ComparableCPVItemSchema(Schema):
    code = String(required=True)
    label = String(required=True, allow_none=True)
    taxonomy_match = Boolean(required=True)
    contracts = Integer(required=True)
    denominator_contracts = Integer(required=True)
    share_percent = String(required=True, allow_none=True)
    raw_examples = List(String(), required=True)


class ComparableCPVDistributionSchema(Schema):
    method = String(required=True)
    signal_format_observed = String(required=True)
    taxonomy = Nested(ComparableTaxonomySchema, required=True)
    denominator_contracts = Integer(required=True)
    contracts_with_normalized_cpv = Integer(required=True)
    contracts_without_normalized_cpv = Integer(required=True)
    contracts_with_taxonomy_label = Integer(required=True)
    invalid_or_unrecognized = List(Nested(ComparableInvalidCPVSchema), required=True)
    items = List(Nested(ComparableCPVItemSchema), required=True)


class ComparableBuyerSchema(Schema):
    buyer = String(required=True)
    contracts = Integer(required=True)
    denominator_contracts = Integer(required=True)
    contract_share_percent = String(required=True, allow_none=True)
    contracts_with_amount = Integer(required=True)
    total_awarded_eur = String(required=True, allow_none=True)
    median_awarded_eur = String(required=True, allow_none=True)


class ComparableAmountBucketSchema(Schema):
    label = String(required=True)
    count = Integer(required=True)
    denominator = Integer(required=True)
    share_percent = String(required=True, allow_none=True)


class ComparableAmountDistributionSchema(Schema):
    contracts_with_amount = Integer(required=True)
    contracts_without_amount = Integer(required=True)
    denominator_contracts = Integer(required=True)
    total_awarded_eur = String(required=True, allow_none=True)
    mean_awarded_eur = String(required=True, allow_none=True)
    median_awarded_eur = String(required=True, allow_none=True)
    minimum_awarded_eur = String(required=True, allow_none=True)
    maximum_awarded_eur = String(required=True, allow_none=True)
    buckets = List(Nested(ComparableAmountBucketSchema), required=True)


class ComparableTermItemSchema(Schema):
    term = String(required=True)
    contracts = Integer(required=True)
    denominator_contracts = Integer(required=True)
    share_percent = String(required=True, allow_none=True)


class ComparableTermDistributionSchema(Schema):
    method = String(required=True)
    method_version = String(required=True)
    denominator_contracts = Integer(required=True)
    contracts_with_terms = Integer(required=True)
    contracts_without_terms = Integer(required=True)
    items = List(Nested(ComparableTermItemSchema), required=True)


class ComparableUTEPartnerSchema(Schema):
    name = String(required=True)
    contracts = Integer(required=True)
    denominator_ute_contracts = Integer(required=True)


class ComparableUTESchema(Schema):
    method = String(required=True)
    verified = Boolean(required=True)
    confidence = String(required=True)
    warning = String(required=True)
    ute_contracts = Integer(required=True)
    denominator_contracts = Integer(required=True)
    ute_share_percent = String(required=True, allow_none=True)
    parsed_ute_contracts = Integer(required=True)
    unparsed_ute_contracts = Integer(required=True)
    partners = List(Nested(ComparableUTEPartnerSchema), required=True)


class ComparableProfileResponseSchema(Schema):
    schema = String(required=True)
    company_requested = String(required=True)
    company_normalized_by_signal = String(required=True)
    identity_basis = Nested(ComparableIdentitySchema, required=True)
    measurement_contract = Nested(ComparableMeasurementSchema, required=True)
    corpus = Nested(ComparableCorpusSchema, required=True)
    award_date_window = Nested(ComparableDateWindowSchema, required=True)
    frequent_cpvs = Nested(ComparableCPVDistributionSchema, required=True)
    buyers = List(Nested(ComparableBuyerSchema), required=True)
    amount_distribution = Nested(ComparableAmountDistributionSchema, required=True)
    title_terms = Nested(ComparableTermDistributionSchema, required=True)
    ute_participation = Nested(ComparableUTESchema, required=True)
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


def _resolve_tender_scope(query_data: dict[str, Any]) -> tuple[str, bool | None]:
    """Translate Oracle's honest temporal scope to the current Signal registry contract."""

    scope = cast(str | None, query_data.get("scope"))
    active_alias = cast(bool | None, query_data.get("active"))
    if scope == "active":
        return "active", True
    if scope == "all":
        # Signal v1 uses false as "do not add the is_active predicate", not as
        # "inactive only". This is one request over the provider's native order.
        return "all", False
    if active_alias is not None:
        return ("active", True) if active_alias else ("all", False)
    # Signal v1 defaults omission to active. Preserve that compatibility while
    # omitting the parameter so Oracle no longer manufactures active=true.
    return "active", None


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


@bp.get("/comparable-profile")
@require_permission("actor.read")
@bp.input(ComparableProfileQuerySchema, location="query")
@bp.output(ComparableProfileResponseSchema)
@limiter.limit("6/hour")
def comparable_profile(query_data: dict[str, Any]) -> dict[str, Any] | Any:
    tenant_id = str(g.active_tenant_id)
    return _handle_provider_call(
        lambda: cached_comparable_profile(
            tenant_id=tenant_id,
            company=cast(str, query_data["company"]).strip(),
        )
    )


@bp.post("/search-plans/preview")
@require_permission("opportunity.read")
@bp.input(TenderSearchPlanPreviewPayloadSchema)
@bp.output(TenderSearchPlanPreviewResponseSchema)
@limiter.limit("6/minute")
def tender_search_plan_preview(json_data: dict[str, Any]) -> dict[str, Any] | Any:
    try:
        plan = postvalidate_tender_search_plan(cast(dict[str, Any], json_data["plan"]))
        preview = preview_search_plan(
            tenant_id=str(g.active_tenant_id),
            plan=plan,
            tender_loader=cached_tenders,
        )
    except (PydanticValidationError, TenderSearchPlanValidationError) as error:
        return _problem_response_passthrough(
            422,
            title="Plan de búsqueda no válido",
            detail=f"El plan de búsqueda no es válido: {error}",
            code="validation_error",
        )
    except SearchPlanExecutionError as error:
        return _problem_response_passthrough(
            422,
            title="Plan de búsqueda no ejecutable",
            detail=str(error),
            code="validation_error",
        )
    except ProcurementConfigurationError as error:
        return _configuration_error_response(error)
    except ProcurementProviderError as error:
        return _provider_error_response(error)
    return {"plan": plan, "preview": preview}


@bp.get("/tenders")
@require_permission("opportunity.read")
@bp.input(TendersQuerySchema, location="query")
@bp.output(TendersResponseSchema)
@limiter.limit("60/minute")
def tenders(query_data: dict[str, Any]) -> dict[str, Any] | Any:
    tenant_id = str(g.active_tenant_id)
    scope, active = _resolve_tender_scope(query_data)
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
            active=active,
            scope=scope,
            limit=int(query_data["limit"]),
            offset=int(query_data["offset"]),
        )
    )


@bp.post("/tenders/<path:folder_id>/summary")
@require_permission("opportunity.read")
@bp.input(TenderSummaryPathSchema, location="path")
@bp.output(TenderSummaryResponseSchema)
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
@require_permission("opportunity.write")
@bp.input(TenderSearchPayloadSchema)
@bp.output(TenderSearchResourceSchema, status_code=201)
@limiter.limit("30/minute")
def tender_searches_create(json_data: dict[str, Any]) -> dict[str, Any] | Any:
    return _handle_provider_call(lambda: create_tender_search(payload=json_data))


@bp.get("/tender-searches/<search_id>")
@require_permission("opportunity.read")
@bp.input(TenderSearchPathSchema, location="path")
@bp.output(TenderSearchResourceSchema)
@limiter.limit("60/minute")
def tender_searches_get(path_data: dict[str, Any]) -> dict[str, Any] | Any:
    return _handle_provider_call(
        lambda: get_tender_search(search_id=cast(str, path_data["search_id"]))
    )


@bp.patch("/tender-searches/<search_id>")
@require_permission("opportunity.write")
@bp.input(TenderSearchPathSchema, location="path")
@bp.input(TenderSearchPatchSchema)
@bp.output(TenderSearchResourceSchema)
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
@require_permission("opportunity.write")
@bp.input(TenderSearchPathSchema, location="path")
@bp.output(TenderSearchResourceSchema)
@limiter.limit("30/minute")
def tender_searches_delete(path_data: dict[str, Any]) -> dict[str, Any] | Any:
    return _handle_provider_call(
        lambda: delete_tender_search(search_id=cast(str, path_data["search_id"]))
    )


@bp.get("/tender-searches/<search_id>/run")
@require_permission("opportunity.read")
@bp.input(TenderSearchPathSchema, location="path")
@bp.input(TenderSearchRunQuerySchema, location="query")
@bp.output(TenderSearchRunSchema)
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
