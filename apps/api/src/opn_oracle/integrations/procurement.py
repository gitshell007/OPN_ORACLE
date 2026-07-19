"""Server-side proxy for public procurement intelligence served by Signal.

The browser must never call Signal directly.  This module reuses the same
Signal AI service-to-service configuration and SSRF/error boundary already
used by entity intelligence, while keeping the two authentication families
separate:

* global registry data: API key only;
* saved tender searches: API key plus X-OPN-External-Tenant-ID.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx
from flask import current_app

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

ProcurementConfigurationError = EntityIntelConfigurationError
ProcurementProviderError = EntityIntelProviderError

PROCUREMENT_AWARDS_CACHE_TTL_SECONDS = 600
PROCUREMENT_SUGGEST_CACHE_TTL_SECONDS = 300
PROCUREMENT_TENDERS_CACHE_TTL_SECONDS = 90

_AWARDS_CACHE = EntityIntelCache(ttl_seconds=PROCUREMENT_AWARDS_CACHE_TTL_SECONDS)
_SUGGEST_CACHE = EntityIntelCache(ttl_seconds=PROCUREMENT_SUGGEST_CACHE_TTL_SECONDS)
_TENDERS_CACHE = EntityIntelCache(ttl_seconds=PROCUREMENT_TENDERS_CACHE_TTL_SECONDS)


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
        return self._get(
            "api/v1/registry/awards",
            params={"company": company, "buyer": buyer, "limit": limit, "offset": offset},
        )

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
        active: bool,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        return self._get(
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
                "limit": limit,
                "offset": offset,
            },
        )

    def tender_summary(self, *, folder_id: str) -> dict[str, Any]:
        return self._post(f"api/v1/registry/tenders/{_quote_path_part(folder_id)}/summary")

    def tender_by_folder(self, *, folder_id: str) -> dict[str, Any]:
        return self._get(
            f"api/v1/registry/tenders/{_quote_path_part(folder_id)}",
            params={},
        )

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
        return self._get(
            f"api/v1/oracle/tender-searches/{_quote_path_part(search_id)}/run",
            params={"limit": limit, "offset": offset},
            external_tenant_id=external_tenant_id,
        )

    def close(self) -> None:
        self._client.close()


def procurement_client_from_config(
    *,
    transport: httpx.BaseTransport | None = None,
) -> ProcurementClient:
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
    active: bool,
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
            limit=limit,
            offset=offset,
        )
    finally:
        client.close()
    # Open tenders change intraday; keep only a short local cache. Summary is
    # deliberately uncached here because Signal owns its LLM summary cache.
    value = {**value, "cached_seconds": PROCUREMENT_TENDERS_CACHE_TTL_SECONDS}
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
    client = procurement_client_from_config()
    try:
        return client.list_searches(external_tenant_id=external_tenant_id)
    finally:
        client.close()


def create_tender_search(*, payload: Mapping[str, Any]) -> dict[str, Any]:
    external_tenant_id = resolve_signal_external_tenant_id()
    client = procurement_client_from_config()
    try:
        return client.create_search(payload=payload, external_tenant_id=external_tenant_id)
    finally:
        client.close()


def get_tender_search(*, search_id: str) -> dict[str, Any]:
    external_tenant_id = resolve_signal_external_tenant_id()
    client = procurement_client_from_config()
    try:
        return client.get_search(search_id=search_id, external_tenant_id=external_tenant_id)
    finally:
        client.close()


def patch_tender_search(*, search_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    external_tenant_id = resolve_signal_external_tenant_id()
    client = procurement_client_from_config()
    try:
        return client.patch_search(
            search_id=search_id,
            payload=payload,
            external_tenant_id=external_tenant_id,
        )
    finally:
        client.close()


def delete_tender_search(*, search_id: str) -> dict[str, Any]:
    external_tenant_id = resolve_signal_external_tenant_id()
    client = procurement_client_from_config()
    try:
        return client.delete_search(search_id=search_id, external_tenant_id=external_tenant_id)
    finally:
        client.close()


def run_tender_search(*, search_id: str, limit: int, offset: int) -> dict[str, Any]:
    external_tenant_id = resolve_signal_external_tenant_id()
    client = procurement_client_from_config()
    try:
        return client.run_search(
            search_id=search_id,
            limit=limit,
            offset=offset,
            external_tenant_id=external_tenant_id,
        )
    finally:
        client.close()
