"""Server-side proxy for Signal entity intelligence endpoints.

The browser must never talk to Signal directly.  This module keeps the
provider key, tenant mapping, allowlist and short cache inside Flask.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass
from threading import RLock
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from flask import current_app, g
from sqlalchemy import select

from opn_oracle.extensions import db
from opn_oracle.platform.models import IntegrationConnection

EntityKind = Literal["company", "person"]

ENTITY_INTEL_CACHE_TTL_SECONDS = 600
ENTITY_INTEL_MAX_BYTES = 2_000_000


class EntityIntelConfigurationError(RuntimeError):
    """Oracle is not safely configured to call the entity-intel provider."""


@dataclass(frozen=True, slots=True)
class EntityIntelProviderError(RuntimeError):
    """Problem returned by Signal or raised by the transport boundary."""

    status_code: int
    code: str
    detail: str
    retryable: bool = False
    errors: Any = None


@dataclass(frozen=True, slots=True)
class CachedValue:
    expires_at: float
    value: dict[str, Any]


class EntityIntelCache:
    """Tiny process-local TTL cache for read-only provider calls."""

    def __init__(self, *, ttl_seconds: int = ENTITY_INTEL_CACHE_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._values: dict[tuple[Any, ...], CachedValue] = {}
        self._lock = RLock()

    def get(self, key: tuple[Any, ...]) -> dict[str, Any] | None:
        now = time.monotonic()
        with self._lock:
            cached = self._values.get(key)
            if cached is None:
                return None
            if cached.expires_at <= now:
                self._values.pop(key, None)
                return None
            return cached.value

    def set(self, key: tuple[Any, ...], value: dict[str, Any]) -> None:
        with self._lock:
            self._values[key] = CachedValue(
                expires_at=time.monotonic() + self._ttl_seconds,
                value=value,
            )


_CACHE = EntityIntelCache()


def _safe_host_allowed(
    *,
    base_url: str,
    allowed_hosts: frozenset[str],
    transport: httpx.BaseTransport | None,
) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme != "https":
        raise EntityIntelConfigurationError("La URL de Signal para entidades debe usar HTTPS.")
    if parsed.username or parsed.password:
        raise EntityIntelConfigurationError("La URL de Signal no admite credenciales embebidas.")
    if parsed.query or parsed.fragment:
        raise EntityIntelConfigurationError("La URL base de Signal no admite query ni fragmento.")
    hostname = (parsed.hostname or "").lower()
    if not hostname or hostname not in allowed_hosts:
        raise EntityIntelConfigurationError("El host de Signal no está en la allowlist.")
    if transport is not None:
        return
    try:
        addresses = {
            item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise EntityIntelConfigurationError(
            "No se pudo resolver el host Signal permitido."
        ) from exc
    if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
        raise EntityIntelConfigurationError("Signal resuelve a una red no pública.")


def _provider_problem(response: httpx.Response) -> EntityIntelProviderError:
    code = "entity_intel_provider_error"
    detail = "Signal no pudo completar la consulta de entidad."
    errors: Any = None
    content_type = response.headers.get("Content-Type", "")
    if "json" in content_type:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            code_value = payload.get("code") or payload.get("type")
            if isinstance(code_value, str) and code_value:
                code = code_value.rsplit("/", 1)[-1].replace("-", "_")[:120]
            detail_value = payload.get("detail") or payload.get("title")
            if isinstance(detail_value, str) and detail_value:
                detail = detail_value[:500]
            errors = payload.get("errors")
    retryable = response.status_code == 429 or response.status_code >= 500
    return EntityIntelProviderError(
        status_code=503 if retryable else response.status_code,
        code=code,
        detail=detail,
        retryable=retryable,
        errors=errors,
    )


class EntityIntelClient:
    """HTTP client for the Signal entity intelligence provisional contract."""

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
            raise EntityIntelConfigurationError("Falta la clave de API de Signal para entidades.")
        _safe_host_allowed(base_url=base_url, allowed_hosts=allowed_hosts, transport=transport)
        self._client = httpx.Client(
            base_url=f"{base_url.rstrip('/')}/",
            timeout=httpx.Timeout(read_timeout, connect=connect_timeout),
            follow_redirects=False,
            transport=transport,
        )
        self._api_key = api_key

    def _get(
        self,
        path: str,
        *,
        params: dict[str, str],
        external_tenant_id: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json", "X-API-Key": self._api_key}
        if external_tenant_id:
            headers["X-OPN-External-Tenant-ID"] = external_tenant_id
        try:
            response = self._client.get(path, params=params, headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise EntityIntelProviderError(
                status_code=503,
                code="entity_intel_provider_unavailable",
                detail="Signal no está disponible temporalmente.",
                retryable=True,
            ) from exc
        if response.is_redirect:
            raise EntityIntelProviderError(
                status_code=502,
                code="entity_intel_redirect_rejected",
                detail="Signal devolvió una redirección no permitida.",
            )
        if response.status_code >= 400:
            raise _provider_problem(response)
        if "json" not in response.headers.get("Content-Type", ""):
            raise EntityIntelProviderError(
                status_code=502,
                code="entity_intel_invalid_content_type",
                detail="Signal devolvió un formato no compatible.",
            )
        if len(response.content) > ENTITY_INTEL_MAX_BYTES:
            raise EntityIntelProviderError(
                status_code=502,
                code="entity_intel_response_too_large",
                detail="Signal devolvió una respuesta demasiado grande.",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise EntityIntelProviderError(
                status_code=502,
                code="entity_intel_invalid_json",
                detail="Signal devolvió JSON no válido.",
            ) from exc
        if not isinstance(payload, dict):
            raise EntityIntelProviderError(
                status_code=502,
                code="entity_intel_invalid_payload",
                detail="Signal devolvió una respuesta inesperada.",
            )
        return payload

    def suggest(self, *, query: str, kind: EntityKind, limit: int) -> dict[str, Any]:
        payload = self._get(
            "api/v1/registry/suggest",
            params={"q": query, "kind": kind, "limit": str(limit)},
        )
        suggestions = payload.get("suggestions", [])
        if not isinstance(suggestions, list):
            raise EntityIntelProviderError(
                status_code=502,
                code="entity_intel_invalid_suggestions",
                detail="Signal devolvió sugerencias con un formato inesperado.",
            )
        return {
            "kind": str(payload.get("kind") or kind),
            "suggestions": [str(item)[:300] for item in suggestions if isinstance(item, str)],
            "cached_seconds": ENTITY_INTEL_CACHE_TTL_SECONDS,
        }

    def graph(
        self,
        *,
        name: str,
        kind: EntityKind,
        depth: int,
        active_only: bool,
        external_tenant_id: str,
    ) -> dict[str, Any]:
        payload = self._get(
            "api/v1/oracle/entity/graph",
            params={
                "name": name,
                "type": kind,
                "depth": str(depth),
                "active_only": "true" if active_only else "false",
            },
            external_tenant_id=external_tenant_id,
        )
        nodes = payload.get("nodes", [])
        edges = payload.get("edges", [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise EntityIntelProviderError(
                status_code=502,
                code="entity_intel_invalid_graph",
                detail="Signal devolvió un grafo con formato inesperado.",
            )
        return {
            "center": payload.get("center"),
            "nodes": [item for item in nodes if isinstance(item, dict)],
            "edges": [item for item in edges if isinstance(item, dict)],
            "truncated": bool(payload.get("truncated", False)),
            "note": payload.get("note") if isinstance(payload.get("note"), str) else None,
            "cached_seconds": ENTITY_INTEL_CACHE_TTL_SECONDS,
        }

    def close(self) -> None:
        self._client.close()


def entity_intel_client_from_config(
    *,
    transport: httpx.BaseTransport | None = None,
) -> EntityIntelClient:
    allowed_hosts = frozenset(
        item.strip().lower()
        for item in current_app.config["SIGNAL_AI_ALLOWED_HOSTS"].split(",")
        if item.strip()
    )
    return EntityIntelClient(
        base_url=current_app.config["SIGNAL_AI_BASE_URL"],
        api_key=current_app.config["SIGNAL_AI_API_KEY"],
        allowed_hosts=allowed_hosts,
        connect_timeout=current_app.config["SIGNAL_CONNECT_TIMEOUT_SECONDS"],
        read_timeout=current_app.config["SIGNAL_AI_TIMEOUT_SECONDS"],
        transport=transport,
    )


def resolve_signal_external_tenant_id() -> str:
    connection = db.session.scalar(
        select(IntegrationConnection)
        .where(
            IntegrationConnection.tenant_id == g.active_tenant_id,
            IntegrationConnection.provider == "signal-avanza",
            IntegrationConnection.status == "active",
        )
        .order_by(IntegrationConnection.updated_at.desc(), IntegrationConnection.created_at.desc())
        .limit(1)
    )
    if connection is None:
        raise EntityIntelProviderError(
            status_code=409,
            code="signal_connection_missing",
            detail="Configura una conexión activa con Signal antes de consultar entidades.",
        )
    metadata = (
        connection.connection_metadata if isinstance(connection.connection_metadata, dict) else {}
    )
    for key in ("external_tenant_id", "signal_external_tenant_id", "tenant_external_id"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(connection.tenant_id)


def cached_suggest(*, tenant_id: str, query: str, kind: EntityKind, limit: int) -> dict[str, Any]:
    key = ("suggest", tenant_id, query.casefold(), kind, limit)
    cached = _CACHE.get(key)
    if cached is not None:
        return {**cached, "cache_hit": True}
    client = entity_intel_client_from_config()
    try:
        value = client.suggest(query=query, kind=kind, limit=limit)
    finally:
        client.close()
    _CACHE.set(key, value)
    return {**value, "cache_hit": False}


def cached_graph(
    *,
    tenant_id: str,
    name: str,
    kind: EntityKind,
    depth: int,
    active_only: bool,
    external_tenant_id: str,
) -> dict[str, Any]:
    key = ("graph", tenant_id, name.casefold(), kind, depth, active_only, external_tenant_id)
    cached = _CACHE.get(key)
    if cached is not None:
        return {**cached, "cache_hit": True}
    client = entity_intel_client_from_config()
    try:
        value = client.graph(
            name=name,
            kind=kind,
            depth=depth,
            active_only=active_only,
            external_tenant_id=external_tenant_id,
        )
    finally:
        client.close()
    _CACHE.set(key, value)
    return {**value, "cache_hit": False}
