"""Server-side proxy for Signal entity intelligence endpoints.

The browser must never talk to Signal directly.  This module keeps the
provider key, tenant mapping, allowlist and short cache inside Flask.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import time
import unicodedata
import uuid
from dataclasses import dataclass
from threading import RLock
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from flask import current_app, g
from sqlalchemy import select

from opn_oracle.common.web_mentions import filter_entity_web_mentions
from opn_oracle.extensions import db
from opn_oracle.platform.models import IntegrationConnection

EntityKind = Literal["company", "person"]
EntityRegistryView = Literal["current", "history"]
GraphRoleCategory = Literal[
    "governance",
    "representation",
    "audit",
    "ownership",
    "liquidation",
    "other",
]

ENTITY_INTEL_CACHE_TTL_SECONDS = 600
ENTITY_INTEL_MAX_BYTES = 2_000_000
ENTITY_INTEL_REGISTRY_FETCH_SIZE = 1_000
ENTITY_INTEL_REGISTRY_MAX_EVENTS = 10_000


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


@dataclass(frozen=True, slots=True)
class CanonicalGraphRole:
    label: str
    key: str
    category: GraphRoleCategory


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

_PERSON_PARTICLE_TOKENS = {"DE", "DEL", "LA", "LOS", "LAS", "SAN", "MC", "O'"}

_GRAPH_ROLE_ALIASES: dict[str, CanonicalGraphRole] = {
    "adm unico": CanonicalGraphRole(
        label="Administrador único",
        key="administrador_unico",
        category="governance",
    ),
    "administrador unico": CanonicalGraphRole(
        label="Administrador único",
        key="administrador_unico",
        category="governance",
    ),
    "adm solid": CanonicalGraphRole(
        label="Administrador solidario",
        key="administrador_solidario",
        category="governance",
    ),
    "administrador solidario": CanonicalGraphRole(
        label="Administrador solidario",
        key="administrador_solidario",
        category="governance",
    ),
    "adm mancom": CanonicalGraphRole(
        label="Administrador mancomunado",
        key="administrador_mancomunado",
        category="governance",
    ),
    "administrador mancomunado": CanonicalGraphRole(
        label="Administrador mancomunado",
        key="administrador_mancomunado",
        category="governance",
    ),
    "administrador": CanonicalGraphRole(
        label="Administrador",
        key="administrador",
        category="governance",
    ),
    "consejero": CanonicalGraphRole(
        label="Consejero",
        key="consejero",
        category="governance",
    ),
    "consejero delegado": CanonicalGraphRole(
        label="Consejero delegado",
        key="consejero_delegado",
        category="governance",
    ),
    "presidente": CanonicalGraphRole(
        label="Presidente",
        key="presidente",
        category="governance",
    ),
    "vicepresidente": CanonicalGraphRole(
        label="Vicepresidente",
        key="vicepresidente",
        category="governance",
    ),
    "secretario": CanonicalGraphRole(
        label="Secretario",
        key="secretario",
        category="governance",
    ),
    "vicesecretario": CanonicalGraphRole(
        label="Vicesecretario",
        key="vicesecretario",
        category="governance",
    ),
    "apoderado": CanonicalGraphRole(
        label="Apoderado",
        key="apoderado",
        category="representation",
    ),
    "apoderada": CanonicalGraphRole(
        label="Apoderado",
        key="apoderado",
        category="representation",
    ),
    "auditor": CanonicalGraphRole(
        label="Auditor",
        key="auditor",
        category="audit",
    ),
    "socio unico": CanonicalGraphRole(
        label="Socio único",
        key="socio_unico",
        category="ownership",
    ),
    "socio": CanonicalGraphRole(
        label="Socio",
        key="socio",
        category="ownership",
    ),
    "liquidador": CanonicalGraphRole(
        label="Liquidador",
        key="liquidador",
        category="liquidation",
    ),
}


def _clean_graph_role(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    clean = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()
    return clean or None


def _graph_role_alias_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in decomposed if unicodedata.category(character) != "Mn"
    )
    return re.sub(r"[\W_]+", " ", without_marks.casefold()).strip()


def _canonical_graph_role(value: str) -> CanonicalGraphRole:
    structural_key = _graph_role_alias_key(value)
    explicit = _GRAPH_ROLE_ALIASES.get(structural_key)
    if explicit is not None:
        return explicit
    stable_key = structural_key.replace(" ", "_")
    if not stable_key:
        codepoints = "_".join(
            f"u{ord(character):x}" for character in value if not character.isspace()
        )
        stable_key = f"other_{codepoints}" if codepoints else "other"
    return CanonicalGraphRole(
        label=value,
        key=stable_key,
        category="other",
    )


def _graph_source_roles(edge: dict[str, Any]) -> list[str]:
    values: list[Any] = [edge.get("role")]
    roles = edge.get("roles")
    values.extend(roles if isinstance(roles, list) else [roles])
    source_roles: list[str] = []
    for value in values:
        clean = _clean_graph_role(value)
        if clean is not None and clean not in source_roles:
            source_roles.append(clean)
    return source_roles


def _graph_edge_with_role_contract(edge: dict[str, Any]) -> dict[str, Any]:
    source_roles = _graph_source_roles(edge)
    normalized: list[CanonicalGraphRole] = []
    seen_keys: set[str] = set()
    for source_role in source_roles:
        role = _canonical_graph_role(source_role)
        if role.key in seen_keys:
            continue
        seen_keys.add(role.key)
        normalized.append(role)
    if not normalized:
        normalized = [CanonicalGraphRole(label="Relación", key="relacion", category="other")]
    return {
        **edge,
        "role": normalized[0].label,
        "roles": [role.label for role in normalized],
        "role_keys": [role.key for role in normalized],
        "role_categories": [role.category for role in normalized],
        "source_roles": source_roles,
    }


def _graph_payload_with_role_contract(payload: dict[str, Any]) -> dict[str, Any]:
    edges = payload.get("edges")
    if not isinstance(edges, list):
        return payload
    return {
        **payload,
        "edges": [_graph_edge_with_role_contract(item) for item in edges if isinstance(item, dict)],
    }


def _normalize_person_query(value: str) -> str:
    cleaned = re.sub(r"[,;:/\\()\[\]{}\"“”]+", " ", value.upper())
    cleaned = re.sub(r"(?<!\w)[.]+|[.]+(?!\w)", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _person_name_units(value: str) -> list[str]:
    tokens = _normalize_person_query(value).split()
    units: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "DE" and index + 2 < len(tokens) and tokens[index + 1] == "LA":
            units.append(" ".join(tokens[index : index + 3]))
            index += 3
            continue
        if token in _PERSON_PARTICLE_TOKENS and index + 1 < len(tokens):
            units.append(" ".join(tokens[index : index + 2]))
            index += 2
            continue
        units.append(token)
        index += 1
    return units


def person_name_variants(query: str) -> list[str]:
    """Return plausible Signal registry variants for Spanish personal names.

    We cap variants at three upstream calls. For four or five units we use the
    third slot for the common compound-name rotation (``JUAN CARLOS`` moved
    behind the surnames) instead of the inverse two-last-units rotation; that
    preserves the most likely Spanish input shape under the call budget.
    """

    if "," in query:
        normalized_with_comma = _normalize_person_query(query)
        return [normalized_with_comma] if normalized_with_comma else []

    units = _person_name_units(query)
    if not units:
        return []
    candidates: list[str] = [" ".join(units)]
    if 2 <= len(units) <= 5:
        candidates.append(" ".join([*units[1:], units[0]]))
    if 4 <= len(units) <= 5:
        candidates.append(" ".join([*units[2:], *units[:2]]))
    elif 3 <= len(units) <= 5:
        candidates.append(" ".join([*units[-2:], *units[:-2]]))

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        value = re.sub(r"\s+", " ", candidate).strip()
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
        if len(deduped) >= 3:
            break
    return deduped


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
        # httpx.RequestError, no solo timeout/red: RemoteProtocolError, LocalProtocolError,
        # DecodingError, ProxyError, TooManyRedirects y UnsupportedProtocol NO son subclases
        # de las anteriores y se escapaban crudas. Un corte de keep-alive ('Server
        # disconnected') mataba el job como fallo permanente en vez de degradar a error de
        # proveedor reintentable.
        except httpx.RequestError as exc:
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

    def _suggest_once(self, *, query: str, kind: EntityKind, limit: int) -> dict[str, Any]:
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

    def suggest(self, *, query: str, kind: EntityKind, limit: int) -> dict[str, Any]:
        if kind != "person":
            return self._suggest_once(query=query, kind=kind, limit=limit)

        variants = person_name_variants(query) or [query]
        merged: list[str] = []
        seen: set[str] = set()
        first_error: EntityIntelProviderError | None = None
        successful_calls = 0
        for index, variant in enumerate(variants):
            try:
                payload = self._suggest_once(query=variant, kind=kind, limit=limit)
            except EntityIntelProviderError as exc:
                if first_error is None:
                    first_error = exc
                continue
            successful_calls += 1
            for suggestion in payload["suggestions"]:
                key = re.sub(r"\s+", " ", suggestion).strip().casefold()
                if key and key not in seen:
                    seen.add(key)
                    merged.append(suggestion)
                if len(merged) >= limit:
                    break
            if index == 0 and merged:
                break
            if len(merged) >= limit:
                break

        if successful_calls == 0 and first_error is not None:
            raise first_error
        return {
            "kind": kind,
            "suggestions": merged[:limit],
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
        normalized = _graph_payload_with_role_contract(payload)
        return {
            "center": normalized.get("center"),
            "nodes": [item for item in nodes if isinstance(item, dict)],
            "edges": normalized["edges"],
            "truncated": bool(normalized.get("truncated", False)),
            "note": (normalized.get("note") if isinstance(normalized.get("note"), str) else None),
            "cached_seconds": ENTITY_INTEL_CACHE_TTL_SECONDS,
        }

    def registry(
        self,
        *,
        name: str,
        kind: EntityKind,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        payload = self._get(
            f"api/v1/registry/{kind}",
            params={"name": name, "limit": str(limit), "offset": str(offset)},
        )
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise EntityIntelProviderError(
                status_code=502,
                code="entity_intel_invalid_registry",
                detail="Signal devolvió el registro con un formato inesperado.",
            )
        normalized = dict(payload)
        normalized["items"] = [item for item in items if isinstance(item, dict)]
        normalized["cached_seconds"] = ENTITY_INTEL_CACHE_TTL_SECONDS
        return normalized

    def dossier(
        self,
        *,
        name: str,
        kind: EntityKind,
        external_tenant_id: str,
    ) -> dict[str, Any]:
        payload = self._get(
            "api/v1/oracle/entity/dossier",
            params={"name": name, "type": kind},
            external_tenant_id=external_tenant_id,
        )
        entity = payload.get("entity")
        sections = payload.get("sections")
        if not isinstance(entity, dict) or not isinstance(sections, dict):
            raise EntityIntelProviderError(
                status_code=502,
                code="entity_intel_invalid_dossier",
                detail="Signal devolvió la ficha de entidad con un formato inesperado.",
            )
        for value in sections.values():
            if not isinstance(value, dict) or not isinstance(value.get("ok"), bool):
                raise EntityIntelProviderError(
                    status_code=502,
                    code="entity_intel_invalid_dossier_section",
                    detail="Signal devolvió una sección de entidad con un formato inesperado.",
                )
        normalized_sections = dict(sections)
        graph_section = normalized_sections.get("graph")
        if isinstance(graph_section, dict) and graph_section.get("ok") is True:
            graph_data = graph_section.get("data")
            if isinstance(graph_data, dict):
                normalized_sections["graph"] = {
                    **graph_section,
                    "data": _graph_payload_with_role_contract(graph_data),
                }
        news_section = normalized_sections.get("news")
        if isinstance(news_section, dict) and news_section.get("ok") is True:
            news_data = news_section.get("data")
            if isinstance(news_data, dict):
                normalized_sections["news"] = {
                    **news_section,
                    "data": filter_entity_web_mentions(
                        news_data,
                        entity_name=str(entity.get("name") or name),
                        entity_kind=kind,
                    ),
                }
        return {
            **payload,
            "entity": entity,
            "sections": normalized_sections,
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


def resolve_signal_external_tenant_id_for_tenant(tenant_id: uuid.UUID) -> str:
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


def resolve_signal_external_tenant_id() -> str:
    return resolve_signal_external_tenant_id_for_tenant(g.active_tenant_id)


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


def cached_registry(
    *,
    tenant_id: str,
    name: str,
    kind: EntityKind,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    key = ("registry", tenant_id, name.casefold(), kind, limit, offset)
    cached = _CACHE.get(key)
    if cached is not None:
        return {**cached, "cache_hit": True}
    client = entity_intel_client_from_config()
    try:
        value = client.registry(name=name, kind=kind, limit=limit, offset=offset)
    finally:
        client.close()
    _CACHE.set(key, value)
    return {**value, "cache_hit": False}


def _registry_text(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    without_marks = "".join(
        character for character in text if unicodedata.category(character) != "Mn"
    )
    return without_marks.casefold().strip()


def _registry_counterpart(item: dict[str, Any], kind: EntityKind) -> str:
    key = "person" if kind == "company" else "company"
    return str(item.get(key) or "").strip()


def _registry_relationship_key(item: dict[str, Any], kind: EntityKind) -> tuple[str, str]:
    return (
        _registry_text(_registry_counterpart(item, kind)),
        _registry_text(item.get("role")),
    )


def _registry_item_with_contract(item: dict[str, Any], kind: EntityKind) -> dict[str, Any]:
    counterpart_kind: EntityKind | None = "company" if kind == "person" else None
    return {
        **item,
        "counterpart": _registry_counterpart(item, kind),
        "counterpart_kind": counterpart_kind,
        "counterpart_kind_verified": counterpart_kind is not None,
    }


def build_registry_view(
    payload: dict[str, Any],
    *,
    kind: EntityKind,
    view: EntityRegistryView,
    limit: int,
    offset: int,
    query: str = "",
    province: str = "",
    sort: str = "-date",
    history_complete: bool = True,
) -> dict[str, Any]:
    """Build a stable, honest view over a complete Signal registry history.

    Signal rows are ordered newest-first. The first row for a counterpart+role
    is therefore the current relationship state; historical rows remain events
    and never inherit that state.
    """

    raw_items = payload.get("items", [])
    items = [
        _registry_item_with_contract(item, kind) for item in raw_items if isinstance(item, dict)
    ]
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        key = _registry_relationship_key(item, kind)
        if key == ("", "") or key in latest:
            continue
        latest[key] = item

    active_items = [
        {**item, "relationship_status": "active"}
        for item in latest.values()
        if _registry_text(item.get("action")) != "cese"
    ]
    ended_total = sum(1 for item in latest.values() if _registry_text(item.get("action")) == "cese")
    candidates = active_items if view == "current" else items

    normalized_query = _registry_text(query)
    normalized_province = _registry_text(province)
    if normalized_query:
        candidates = [
            item
            for item in candidates
            if normalized_query
            in _registry_text(
                " ".join(
                    str(item.get(key) or "")
                    for key in (
                        "counterpart",
                        "company",
                        "person",
                        "role",
                        "action",
                        "province",
                        "date",
                    )
                )
            )
        ]
    if normalized_province:
        candidates = [
            item
            for item in candidates
            if _registry_text(item.get("province")) == normalized_province
        ]

    sort_descending = sort.startswith("-")
    sort_key = sort.removeprefix("-")
    sort_field = {
        "counterpart": "counterpart",
        "role": "role",
        "province": "province",
        "date": "date",
    }.get(sort_key, "date")
    candidates = sorted(
        candidates,
        key=lambda item: (
            _registry_text(item.get(sort_field)),
            _registry_text(item.get("counterpart")),
        ),
        reverse=sort_descending,
    )

    source_total = payload.get("total")
    if not isinstance(source_total, int) or source_total < len(items):
        source_total = len(items)
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else None
    company_act_total = profile.get("total_acts") if profile else None
    if not isinstance(company_act_total, int) or company_act_total < 0:
        company_act_total = None
    provinces = sorted(
        {
            str(item.get("province")).strip()
            for item in items
            if str(item.get("province") or "").strip()
        },
        key=_registry_text,
    )
    total = len(candidates)
    return {
        **{key: value for key, value in payload.items() if key != "items"},
        "view": view,
        "total": total,
        "source_total": source_total,
        "items": candidates[offset : offset + limit],
        "available_provinces": provinces,
        "summary": {
            "history_events": source_total,
            "received_events": len(items),
            "history_complete": history_complete,
            "current_relationships": len(active_items),
            "ended_relationships": ended_total,
            "company_acts": company_act_total,
        },
        "cached_seconds": ENTITY_INTEL_CACHE_TTL_SECONDS,
    }


def cached_registry_view(
    *,
    tenant_id: str,
    name: str,
    kind: EntityKind,
    view: EntityRegistryView,
    limit: int,
    offset: int,
    query: str = "",
    province: str = "",
    sort: str = "-date",
) -> dict[str, Any]:
    corpus_key = ("registry-corpus", tenant_id, name.casefold(), kind)
    cached_corpus = _CACHE.get(corpus_key)
    cache_hit = cached_corpus is not None
    if cached_corpus is None:
        client = entity_intel_client_from_config()
        try:
            first = client.registry(
                name=name,
                kind=kind,
                limit=ENTITY_INTEL_REGISTRY_FETCH_SIZE,
                offset=0,
            )
            all_items = list(first.get("items", []))
            source_total = first.get("total")
            expected_total = source_total if isinstance(source_total, int) else len(all_items)
            while (
                len(all_items) < expected_total
                and len(all_items) < ENTITY_INTEL_REGISTRY_MAX_EVENTS
            ):
                page = client.registry(
                    name=name,
                    kind=kind,
                    limit=min(
                        ENTITY_INTEL_REGISTRY_FETCH_SIZE,
                        ENTITY_INTEL_REGISTRY_MAX_EVENTS - len(all_items),
                    ),
                    offset=len(all_items),
                )
                page_items = page.get("items", [])
                if not page_items:
                    break
                all_items.extend(page_items)
            cached_corpus = {
                **first,
                "items": all_items,
                "history_complete": len(all_items) >= expected_total,
            }
        finally:
            client.close()
        _CACHE.set(corpus_key, cached_corpus)
    result = build_registry_view(
        cached_corpus,
        kind=kind,
        view=view,
        limit=limit,
        offset=offset,
        query=query,
        province=province,
        sort=sort,
        history_complete=bool(cached_corpus.get("history_complete", True)),
    )
    return {**result, "cache_hit": cache_hit}


def cached_dossier(
    *,
    tenant_id: str,
    name: str,
    kind: EntityKind,
    external_tenant_id: str,
) -> dict[str, Any]:
    key = ("dossier", tenant_id, name.casefold(), kind, external_tenant_id)
    cached = _CACHE.get(key)
    if cached is not None:
        return {**cached, "cache_hit": True}
    client = entity_intel_client_from_config()
    try:
        value = client.dossier(
            name=name,
            kind=kind,
            external_tenant_id=external_tenant_id,
        )
    finally:
        client.close()
    _CACHE.set(key, value)
    return {**value, "cache_hit": False}
