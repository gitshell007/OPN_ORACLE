"""Server-side proxy for public procurement intelligence served by Signal.

The browser must never call Signal directly.  This module reuses the same
Signal AI service-to-service configuration and SSRF/error boundary already
used by entity intelligence, while keeping the two authentication families
separate:

* global registry data: ``SIGNAL_AI_API_KEY`` only (no tenant header);
* saved tender searches (tenant-bound Oracle namespace): active Signal connection
  ``api_token`` (CTC) + ``X-OPN-External-Tenant-ID``.

Do **not** send the AI pilot / global key to ``/api/v1/oracle/tender-searches``:
that key often lacks ``signal:read`` / ``monitor:write`` and is not the CTC
bound to the tenant connection.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
from flask import current_app, g
from sqlalchemy import select

from opn_oracle.extensions import db
from opn_oracle.integrations.entity_intel import (
    ENTITY_INTEL_MAX_BYTES as PROCUREMENT_MAX_BYTES,
)
from opn_oracle.integrations.entity_intel import (
    EntityIntelCache,
    EntityIntelConfigurationError,
    EntityIntelProviderError,
    _provider_problem,
    _safe_host_allowed,
    resolve_signal_external_tenant_id,
)
from opn_oracle.integrations.service import active_secrets
from opn_oracle.platform.models import IntegrationConnection

ProcurementConfigurationError = EntityIntelConfigurationError
ProcurementProviderError = EntityIntelProviderError

PROCUREMENT_AWARDS_CACHE_TTL_SECONDS = 600
PROCUREMENT_COMPARABLE_PROFILE_CACHE_TTL_SECONDS = 21_600
PROCUREMENT_SUGGEST_CACHE_TTL_SECONDS = 300
PROCUREMENT_TENDERS_CACHE_TTL_SECONDS = 90

_AWARDS_CACHE = EntityIntelCache(ttl_seconds=PROCUREMENT_AWARDS_CACHE_TTL_SECONDS)
_COMPARABLE_PROFILE_CACHE = EntityIntelCache(
    ttl_seconds=PROCUREMENT_COMPARABLE_PROFILE_CACHE_TTL_SECONDS
)
_SUGGEST_CACHE = EntityIntelCache(ttl_seconds=PROCUREMENT_SUGGEST_CACHE_TTL_SECONDS)
_TENDERS_CACHE = EntityIntelCache(ttl_seconds=PROCUREMENT_TENDERS_CACHE_TTL_SECONDS)

_CANONICAL_TENDER_STATUSES: dict[str, str] = {
    "open": "open",
    "abierta": "open",
    "abierto": "open",
    "activa": "open",
    "activo": "open",
    # PLACSP / Signal short codes (case-insensitive via casefold).
    "pub": "open",  # Publicada
    "ev": "open",  # En vigor / en evaluación con is_active (filtrar por plazo aparte)
    "pre": "open",
    "closed": "closed",
    "cerrada": "closed",
    "cerrado": "closed",
    "res": "closed",  # Resuelta
    "resuelta": "closed",
    "resuelto": "closed",
    "awarded": "awarded",
    "adjudicada": "awarded",
    "adjudicado": "awarded",
    "adj": "awarded",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "cancelada": "cancelled",
    "cancelado": "cancelled",
    "anulada": "cancelled",
    "anulado": "cancelled",
    "anul": "cancelled",
    "an": "cancelled",
}

# Terminal / non-pending provider status tokens (after casefold + strip).
_NON_PENDING_STATUS_TOKENS = frozenset(
    {
        "adj",
        "adjudicada",
        "adjudicado",
        "awarded",
        "res",
        "resuelta",
        "resuelto",
        "closed",
        "cerrada",
        "cerrado",
        "anul",
        "an",
        "anulada",
        "anulado",
        "cancelled",
        "canceled",
        "cancelada",
        "cancelado",
    }
)


def _clean_params(params: Mapping[str, Any]) -> dict[str, str]:
    clean: dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                continue
            clean[key] = stripped
            continue
        if isinstance(value, bool):
            clean[key] = "true" if value else "false"
            continue
        clean[key] = str(value)
    return clean


def _quote_path_part(value: str) -> str:
    # Signal usa converter :path: la barra del folder_id viaja como parte de la
    # ruta, codificada o no; uvicorn decodifica %2F a "/" antes del matching.
    return quote(value.strip(), safe="")


def canonical_tender_status(value: Any) -> str:
    """Map only explicitly understood provider values to Oracle's closed vocabulary."""

    if not isinstance(value, str):
        return "unknown"
    return _CANONICAL_TENDER_STATUSES.get(value.strip().casefold(), "unknown")


def _parse_tender_deadline(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def tender_is_pending_open(item: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    """Whether a tender still looks open for "solo pendientes".

    Signal's active=true is the primary filter, but residual RES/ADJ rows or expired
    deadlines still appear in multi-probe merges. This is the honest local gate.
    """

    if item.get("is_active") is False:
        return False
    status_raw = item.get("status")
    status = status_raw.strip().casefold() if isinstance(status_raw, str) else ""
    if status in _NON_PENDING_STATUS_TOKENS:
        return False
    canonical = item.get("canonical_status")
    if canonical in {"awarded", "closed", "cancelled"}:
        return False
    # Also re-map from raw status in case normalize has not run yet.
    if canonical_tender_status(status_raw) in {"awarded", "closed", "cancelled"}:
        return False
    deadline = _parse_tender_deadline(item.get("deadline"))
    if deadline is not None:
        moment = now or datetime.now(UTC)
        if deadline < moment:
            return False
    return True


def filter_pending_tender_items(
    items: list[Any],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    moment = now or datetime.now(UTC)
    kept: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_tender_item(item)
        if tender_is_pending_open(normalized, now=moment):
            kept.append(normalized)
    return kept


def _normalize_tender_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    return {**item, "canonical_status": canonical_tender_status(item.get("status"))}


def _normalize_tender_collection(
    payload: dict[str, Any],
    *,
    pending_only: bool = False,
) -> dict[str, Any]:
    items = payload.get("items")
    if not isinstance(items, list):
        return payload
    if pending_only:
        filtered = filter_pending_tender_items(items)
        return {
            **payload,
            "items": filtered,
            # Keep provider total if present; note local drop for clients.
            "pending_filter_dropped": max(0, len(items) - len(filtered)),
        }
    return {**payload, "items": [_normalize_tender_item(item) for item in items]}


def _coerce_nonneg_int(value: Any, *, fallback: int) -> int:
    if isinstance(value, bool) or value is None:
        return fallback
    if isinstance(value, int):
        return value if value >= 0 else fallback
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return fallback


def _normalize_awards_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Make Signal awards responses dump-safe for AwardsResponseSchema.

    Intermittent 500s when paging often came from null norms, non-int totals, or
    non-dict rows that blew up APIFlask output validation after a successful
    provider call.
    """

    raw_items = payload.get("items")
    items: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for entry in raw_items:
            if isinstance(entry, dict):
                items.append(entry)

    total = _coerce_nonneg_int(payload.get("total"), fallback=len(items))
    if total < len(items):
        total = len(items)

    company_norm = payload.get("company_norm")
    if not isinstance(company_norm, str):
        company_norm = "" if company_norm is None else str(company_norm)

    buyer_norm = payload.get("buyer_norm")
    if not isinstance(buyer_norm, str):
        buyer_norm = "" if buyer_norm is None else str(buyer_norm)

    return {
        **payload,
        "items": items,
        "total": total,
        "company_norm": company_norm,
        "buyer_norm": buyer_norm,
    }


class ProcurementClient:
    """HTTP client for Signal registry/procurement endpoints."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        allowed_hosts: frozenset[str],
        connect_timeout: float = 2.0,
        read_timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ProcurementConfigurationError("Falta la clave de API de Signal.")
        _safe_host_allowed(base_url=base_url, allowed_hosts=allowed_hosts, transport=transport)
        self._client = httpx.Client(
            base_url=f"{base_url.rstrip('/')}/",
            timeout=httpx.Timeout(read_timeout, connect=connect_timeout),
            follow_redirects=False,
            transport=transport,
        )
        self._api_key = api_key

    def _headers(self, *, external_tenant_id: str | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json", "X-API-Key": self._api_key}
        if external_tenant_id:
            headers["X-OPN-External-Tenant-ID"] = external_tenant_id
        return headers

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        external_tenant_id: str | None = None,
    ) -> dict[str, Any]:
        headers = self._headers(external_tenant_id=external_tenant_id)
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = self._client.request(
                method,
                path,
                params=_clean_params(params or {}),
                json=dict(json_body) if json_body is not None else None,
                headers=headers,
            )
        # httpx.RequestError, no solo timeout/red: RemoteProtocolError, LocalProtocolError,
        # DecodingError, ProxyError, TooManyRedirects y UnsupportedProtocol NO son subclases
        # de las anteriores y se escapaban crudas. Un corte de keep-alive ('Server
        # disconnected') mataba el job como fallo permanente en vez de degradar a error de
        # proveedor reintentable.
        except httpx.RequestError as exc:
            raise ProcurementProviderError(
                status_code=503,
                code="procurement_provider_unavailable",
                detail="Signal no está disponible temporalmente.",
                retryable=True,
            ) from exc
        if response.is_redirect:
            raise ProcurementProviderError(
                status_code=502,
                code="procurement_redirect_rejected",
                detail="Signal devolvió una redirección no permitida.",
            )
        if response.status_code >= 400:
            raise _provider_problem(response)
        if response.status_code == 204 and not response.content:
            return {"deleted": True}
        if "json" not in response.headers.get("Content-Type", ""):
            raise ProcurementProviderError(
                status_code=502,
                code="procurement_invalid_content_type",
                detail="Signal devolvió un formato no compatible.",
            )
        if len(response.content) > PROCUREMENT_MAX_BYTES:
            raise ProcurementProviderError(
                status_code=502,
                code="procurement_response_too_large",
                detail="Signal devolvió una respuesta demasiado grande.",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProcurementProviderError(
                status_code=502,
                code="procurement_invalid_json",
                detail="Signal devolvió JSON no válido.",
            ) from exc
        if not isinstance(payload, dict):
            raise ProcurementProviderError(
                status_code=502,
                code="procurement_invalid_payload",
                detail="Signal devolvió una respuesta inesperada.",
            )
        return payload

    def _get(
        self,
        path: str,
        *,
        params: Mapping[str, Any],
        external_tenant_id: str | None = None,
    ) -> dict[str, Any]:
        return self._request_json(
            "GET",
            path,
            params=params,
            external_tenant_id=external_tenant_id,
        )

    def _post(
        self,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        external_tenant_id: str | None = None,
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            path,
            json_body=json_body or {},
            external_tenant_id=external_tenant_id,
        )

    def _patch(
        self,
        path: str,
        *,
        json_body: Mapping[str, Any],
        external_tenant_id: str,
    ) -> dict[str, Any]:
        return self._request_json(
            "PATCH",
            path,
            json_body=json_body,
            external_tenant_id=external_tenant_id,
        )

    def _delete(self, path: str, *, external_tenant_id: str) -> dict[str, Any]:
        return self._request_json("DELETE", path, external_tenant_id=external_tenant_id)

    def awards(
        self,
        *,
        company: str | None,
        buyer: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        payload = self._get(
            "api/v1/registry/awards",
            params={"company": company, "buyer": buyer, "limit": limit, "offset": offset},
        )
        return _normalize_awards_payload(payload)

    def suggest(self, *, query: str, kind: str, limit: int) -> dict[str, Any]:
        payload = self._get(
            "api/v1/registry/suggest",
            params={"q": query, "kind": kind, "limit": limit},
        )
        suggestions = payload.get("suggestions", [])
        if not isinstance(suggestions, list):
            raise ProcurementProviderError(
                status_code=502,
                code="procurement_invalid_suggestions",
                detail="Signal devolvió sugerencias con un formato inesperado.",
            )
        return {
            "kind": str(payload.get("kind") or kind),
            "suggestions": [str(item)[:300] for item in suggestions if isinstance(item, str)],
            "cached_seconds": PROCUREMENT_SUGGEST_CACHE_TTL_SECONDS,
        }

    def tenders(
        self,
        *,
        keywords: str | None,
        cpv: str | None,
        min_amount: str | None,
        max_amount: str | None,
        deadline_before: str | None,
        buyer: str | None,
        region: str | None,
        active: bool | None,
        scope: str | None = None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        payload = self._get(
            "api/v1/registry/tenders",
            params={
                "keywords": keywords,
                "cpv": cpv,
                "min_amount": min_amount,
                "max_amount": max_amount,
                "deadline_before": deadline_before,
                "buyer": buyer,
                "region": region,
                "active": active,
                "scope": scope,
                "limit": limit,
                "offset": offset,
            },
        )
        # active=True / scope=active: also drop residual closed/awarded/expired rows.
        pending_only = active is True or scope == "active"
        return _normalize_tender_collection(payload, pending_only=pending_only)

    def tender_summary(self, *, folder_id: str) -> dict[str, Any]:
        payload = self._post(f"api/v1/registry/tenders/{_quote_path_part(folder_id)}/summary")
        item = payload.get("item")
        if isinstance(item, dict):
            return {**payload, "item": _normalize_tender_item(item)}
        return payload

    def tender_by_folder(self, *, folder_id: str) -> dict[str, Any]:
        payload = self._get(
            f"api/v1/registry/tenders/{_quote_path_part(folder_id)}",
            params={},
        )
        item = payload.get("item")
        if isinstance(item, dict):
            return {**payload, "item": _normalize_tender_item(item)}
        return payload

    def awards_by_folder(self, *, folder_id: str) -> dict[str, Any]:
        return self._get(
            f"api/v1/registry/awards/{_quote_path_part(folder_id)}",
            params={},
        )

    def stats(self) -> dict[str, Any]:
        return self._get("api/v1/registry/stats", params={})

    def list_searches(self, *, external_tenant_id: str) -> dict[str, Any]:
        return self._get(
            "api/v1/oracle/tender-searches",
            params={},
            external_tenant_id=external_tenant_id,
        )

    def create_search(
        self,
        *,
        payload: Mapping[str, Any],
        external_tenant_id: str,
    ) -> dict[str, Any]:
        return self._post(
            "api/v1/oracle/tender-searches",
            json_body=payload,
            external_tenant_id=external_tenant_id,
        )

    def get_search(self, *, search_id: str, external_tenant_id: str) -> dict[str, Any]:
        return self._get(
            f"api/v1/oracle/tender-searches/{_quote_path_part(search_id)}",
            params={},
            external_tenant_id=external_tenant_id,
        )

    def patch_search(
        self,
        *,
        search_id: str,
        payload: Mapping[str, Any],
        external_tenant_id: str,
    ) -> dict[str, Any]:
        return self._patch(
            f"api/v1/oracle/tender-searches/{_quote_path_part(search_id)}",
            json_body=payload,
            external_tenant_id=external_tenant_id,
        )

    def delete_search(self, *, search_id: str, external_tenant_id: str) -> dict[str, Any]:
        return self._delete(
            f"api/v1/oracle/tender-searches/{_quote_path_part(search_id)}",
            external_tenant_id=external_tenant_id,
        )

    def run_search(
        self,
        *,
        search_id: str,
        limit: int,
        offset: int,
        external_tenant_id: str,
    ) -> dict[str, Any]:
        payload = self._get(
            f"api/v1/oracle/tender-searches/{_quote_path_part(search_id)}/run",
            params={"limit": limit, "offset": offset},
            external_tenant_id=external_tenant_id,
        )
        results = payload.get("results")
        if isinstance(results, dict):
            return {**payload, "results": _normalize_tender_collection(results)}
        return payload

    def close(self) -> None:
        self._client.close()


def procurement_client_from_config(
    *,
    transport: httpx.BaseTransport | None = None,
) -> ProcurementClient:
    """Client for **global** Signal registry paths (no tenant-bound scopes)."""

    allowed_hosts = frozenset(
        item.strip().lower()
        for item in current_app.config["SIGNAL_AI_ALLOWED_HOSTS"].split(",")
        if item.strip()
    )
    return ProcurementClient(
        base_url=current_app.config["SIGNAL_AI_BASE_URL"],
        api_key=current_app.config["SIGNAL_AI_API_KEY"],
        allowed_hosts=allowed_hosts,
        connect_timeout=current_app.config["SIGNAL_CONNECT_TIMEOUT_SECONDS"],
        read_timeout=current_app.config["SIGNAL_AI_TIMEOUT_SECONDS"],
        transport=transport,
    )


def _active_signal_avanza_connection(tenant_id: uuid.UUID) -> IntegrationConnection:
    connection = db.session.scalar(
        select(IntegrationConnection)
        .where(
            IntegrationConnection.tenant_id == tenant_id,
            IntegrationConnection.provider == "signal-avanza",
            IntegrationConnection.status == "active",
        )
        .order_by(IntegrationConnection.updated_at.desc(), IntegrationConnection.created_at.desc())
        .limit(1)
    )
    if connection is None:
        raise ProcurementProviderError(
            status_code=409,
            code="signal_connection_missing",
            detail="Configura una conexión activa con Signal antes de guardar vigilancias.",
        )
    return connection


def procurement_client_for_tenant_bound(
    *,
    transport: httpx.BaseTransport | None = None,
) -> ProcurementClient:
    """Client for tenant-bound Oracle tender-search APIs (CTC / connection token).

    Uses the active ``signal-avanza`` connection's ``api_token`` so Signal resolves
    ``auth_mode=tenant_credential`` with the scopes stored on the CTC — not the
    global ``SIGNAL_AI_API_KEY`` (often a synthetic AI pilot without scopes).
    """

    tenant_id = g.active_tenant_id
    connection = _active_signal_avanza_connection(tenant_id)
    tokens = active_secrets(connection, "api_token", limit=1)
    if not tokens:
        raise ProcurementProviderError(
            status_code=409,
            code="signal_connection_token_missing",
            detail=(
                "La conexión Signal no tiene api_token activo. "
                "Guarda la CTC del tenant en la conexión (no uses solo SIGNAL_AI_API_KEY)."
            ),
        )
    base_url = (connection.base_url or "").strip() or str(current_app.config["SIGNAL_AI_BASE_URL"])
    allowed_hosts = frozenset(
        item.strip().lower()
        for item in current_app.config["SIGNAL_AI_ALLOWED_HOSTS"].split(",")
        if item.strip()
    )
    return ProcurementClient(
        base_url=base_url,
        api_key=tokens[0],
        allowed_hosts=allowed_hosts,
        connect_timeout=current_app.config["SIGNAL_CONNECT_TIMEOUT_SECONDS"],
        read_timeout=current_app.config["SIGNAL_AI_TIMEOUT_SECONDS"],
        transport=transport,
    )


def cached_awards(
    *,
    tenant_id: str,
    company: str | None,
    buyer: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    key = (
        "awards",
        tenant_id,
        (company or "").casefold(),
        (buyer or "").casefold(),
        limit,
        offset,
    )
    cached = _AWARDS_CACHE.get(key)
    if cached is not None:
        return {**cached, "cache_hit": True}
    client = procurement_client_from_config()
    try:
        value = client.awards(company=company, buyer=buyer, limit=limit, offset=offset)
    finally:
        client.close()
    value = {**value, "cached_seconds": PROCUREMENT_AWARDS_CACHE_TTL_SECONDS}
    _AWARDS_CACHE.set(key, value)
    return {**value, "cache_hit": False}


def cached_comparable_profile(*, tenant_id: str, company: str) -> dict[str, Any]:
    """Cache the aggregate, not the provider rows, for a bounded six-hour TTL."""

    from opn_oracle.oracle.comparable_procurement import (  # Avoid integration/domain cycle.
        COMPARABLE_PROFILE_MAX_ROWS,
        build_comparable_profile,
    )

    key = (
        "comparable-profile-v1",
        tenant_id,
        " ".join(company.casefold().split()),
        COMPARABLE_PROFILE_MAX_ROWS,
    )
    cached = _COMPARABLE_PROFILE_CACHE.get(key)
    if cached is not None:
        return {**cached, "cache_hit": True}
    client = procurement_client_from_config()
    try:
        value = build_comparable_profile(
            client,
            company_name=company,
            max_rows=COMPARABLE_PROFILE_MAX_ROWS,
        )
    finally:
        client.close()
    value = {
        **value,
        "cached_seconds": PROCUREMENT_COMPARABLE_PROFILE_CACHE_TTL_SECONDS,
    }
    _COMPARABLE_PROFILE_CACHE.set(key, value)
    return {**value, "cache_hit": False}


def cached_suggest(*, tenant_id: str, query: str, kind: str, limit: int) -> dict[str, Any]:
    key = ("suggest", tenant_id, kind, query.casefold(), limit)
    cached = _SUGGEST_CACHE.get(key)
    if cached is not None:
        return {**cached, "cache_hit": True}
    client = procurement_client_from_config()
    try:
        value = client.suggest(query=query, kind=kind, limit=limit)
    finally:
        client.close()
    _SUGGEST_CACHE.set(key, value)
    return {**value, "cache_hit": False}


def cached_tenders(
    *,
    tenant_id: str,
    keywords: str | None,
    cpv: str | None,
    min_amount: str | None,
    max_amount: str | None,
    deadline_before: str | None,
    buyer: str | None,
    region: str | None,
    active: bool | None,
    scope: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    key = (
        "tenders",
        tenant_id,
        (keywords or "").casefold(),
        (cpv or "").casefold(),
        min_amount or "",
        max_amount or "",
        deadline_before or "",
        (buyer or "").casefold(),
        (region or "").casefold(),
        active,
        scope,
        limit,
        offset,
    )
    cached = _TENDERS_CACHE.get(key)
    if cached is not None:
        return {**cached, "cache_hit": True}
    client = procurement_client_from_config()
    try:
        value = client.tenders(
            keywords=keywords,
            cpv=cpv,
            min_amount=min_amount,
            max_amount=max_amount,
            deadline_before=deadline_before,
            buyer=buyer,
            region=region,
            active=active,
            scope=scope,
            limit=limit,
            offset=offset,
        )
    finally:
        client.close()
    # Open tenders change intraday; keep only a short local cache. Summary is
    # deliberately uncached here because Signal owns its LLM summary cache.
    upstream_semantics = value.get("semantics")
    semantics = dict(upstream_semantics) if isinstance(upstream_semantics, dict) else {}
    semantics.update(
        {
            "oracle_scope": scope,
            "historical_scope_available": False,
            "scope_contract": "signal-registry-v1",
        }
    )
    value = {
        **value,
        "semantics": semantics,
        "cached_seconds": PROCUREMENT_TENDERS_CACHE_TTL_SECONDS,
    }
    _TENDERS_CACHE.set(key, value)
    return {**value, "cache_hit": False}


def uncached_tender_summary(*, folder_id: str) -> dict[str, Any]:
    client = procurement_client_from_config()
    try:
        return client.tender_summary(folder_id=folder_id)
    finally:
        client.close()


def procurement_stats() -> dict[str, Any]:
    client = procurement_client_from_config()
    try:
        return client.stats()
    finally:
        client.close()


def list_tender_searches() -> dict[str, Any]:
    external_tenant_id = resolve_signal_external_tenant_id()
    client = procurement_client_for_tenant_bound()
    try:
        return client.list_searches(external_tenant_id=external_tenant_id)
    finally:
        client.close()


def create_tender_search(*, payload: Mapping[str, Any]) -> dict[str, Any]:
    external_tenant_id = resolve_signal_external_tenant_id()
    client = procurement_client_for_tenant_bound()
    try:
        return client.create_search(payload=payload, external_tenant_id=external_tenant_id)
    finally:
        client.close()


def get_tender_search(*, search_id: str) -> dict[str, Any]:
    external_tenant_id = resolve_signal_external_tenant_id()
    client = procurement_client_for_tenant_bound()
    try:
        return client.get_search(search_id=search_id, external_tenant_id=external_tenant_id)
    finally:
        client.close()


def patch_tender_search(*, search_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    external_tenant_id = resolve_signal_external_tenant_id()
    client = procurement_client_for_tenant_bound()
    try:
        return client.patch_search(
            search_id=search_id,
            payload=payload,
            external_tenant_id=external_tenant_id,
        )
    finally:
        client.close()


def delete_tender_search(
    *,
    search_id: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    external_tenant_id = resolve_signal_external_tenant_id()
    client = procurement_client_for_tenant_bound()
    try:
        deleted = client.delete_search(search_id=search_id, external_tenant_id=external_tenant_id)
    finally:
        client.close()
    # Import lazily: the watch module reads saved searches through this module.
    # Retiring is deliberately local and deterministic; it disables the durable
    # schedule but leaves seen-state available to the 90-day retention task.
    from opn_oracle.oracle.procurement_search_watch import (
        retire_procurement_search_watch_for_tender_search,
    )

    retire_procurement_search_watch_for_tender_search(
        db.session(),
        tender_search_id=search_id,
        request_id=request_id,
    )
    return deleted


def run_tender_search(*, search_id: str, limit: int, offset: int) -> dict[str, Any]:
    external_tenant_id = resolve_signal_external_tenant_id()
    client = procurement_client_for_tenant_bound()
    try:
        return client.run_search(
            search_id=search_id,
            limit=limit,
            offset=offset,
            external_tenant_id=external_tenant_id,
        )
    finally:
        client.close()
