"""DossierMemoryProfile + connection resolution (MDEV-04 / G-29 honest profile).

Engine-supported modes only: disabled | shadow | augment.
Retrieval is always dossier-scoped (scope_type=dossier). There is no global,
cross-tenant or tenant_curated memory mode in the motor — do not advertise them.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from opn_oracle.integrations.memory_http_client import (
    DEFAULT_ALLOWED_HOSTS,
    MemoryClientConfig,
    MemoryHttpError,
    SignalMemoryHttpClient,
    Transport,
)
from opn_oracle.integrations.service import active_secrets
from opn_oracle.platform.models import IntegrationConnection

OracleMemoryMode = Literal["disabled", "shadow", "augment"]
OPERATIONAL_MODES: frozenset[str] = frozenset({"disabled", "shadow", "augment"})

# Server-side default policy for new dossiers (fail-closed). Not client-overridable on create.
SERVER_DEFAULT_MEMORY_MODE: OracleMemoryMode = "disabled"

MODE_ES = {
    "disabled": "Desactivada",
    "shadow": "Solo observar",
    "augment": "Usar para responder",
}

MODE_SCOPE_ES = {
    "disabled": "Este expediente no usa memoria de Signal. No recuerda ni recupera contexto.",
    "shadow": (
        "Recupera memoria solo de este expediente (mismo tenant) para observación; "
        "no inyecta en la respuesta."
    ),
    "augment": (
        "Usa memoria solo de este expediente (mismo tenant) para responder. "
        "No mezcla otros expedientes ni otros tenants."
    ),
}


def _now() -> datetime:
    return datetime.now(UTC)


def _etag(version: int, payload: dict[str, Any]) -> str:
    raw = json.dumps({"v": version, "p": payload}, sort_keys=True, separators=(",", ":"))
    return f'W/"dmp-v{version}-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"'


def resolve_signal_memory_connection(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    preferred_connection_id: uuid.UUID | None = None,
) -> IntegrationConnection:
    """Deterministic active signal-avanza connection for tenant.

    Rule: prefer preferred_connection_id if active; else single active connection;
    if multiple without preference → conflict.
    """
    q: Select[tuple[IntegrationConnection]] = select(IntegrationConnection).where(
        IntegrationConnection.tenant_id == tenant_id,
        IntegrationConnection.provider == "signal-avanza",
        IntegrationConnection.status == "active",
    )
    rows = list(session.scalars(q).all())
    if not rows:
        raise MemoryHttpError("connection_missing", "no active Signal connection", retryable=False)
    if preferred_connection_id is not None:
        for r in rows:
            if r.id == preferred_connection_id:
                return r
        raise MemoryHttpError(
            "connection_missing", "preferred connection not active", retryable=False
        )
    if len(rows) > 1:
        raise MemoryHttpError(
            "connection_conflict",
            "multiple active Signal connections; select one",
            retryable=False,
        )
    return rows[0]


def build_client_for_connection(
    connection: IntegrationConnection,
    *,
    transport: Transport,
    allowed_hosts: frozenset[str] | None = None,
    require_https: bool = True,
) -> SignalMemoryHttpClient:
    secrets = active_secrets(connection, "api_token", limit=1)
    if not secrets:
        raise MemoryHttpError(
            "credential_missing", "no active api_token credential", retryable=False
        )
    base = str(connection.base_url or "").strip()
    if not base:
        raise MemoryHttpError("base_url_missing", "connection base_url empty", retryable=False)
    cfg = MemoryClientConfig(
        base_url=base,
        api_token=secrets[0],
        allowed_hosts=allowed_hosts or DEFAULT_ALLOWED_HOSTS,
        require_https=require_https,
    )
    return SignalMemoryHttpClient(cfg, transport)


def default_profile_payload(
    *,
    provenance: str = "server_policy_on_create",
    config_source: str = "server_policy",
    mode: str | None = None,
) -> dict[str, Any]:
    """Server-owned defaults for a persisted DossierMemoryProfile."""
    resolved = str(mode or SERVER_DEFAULT_MEMORY_MODE).strip().lower()
    if resolved not in OPERATIONAL_MODES:
        resolved = SERVER_DEFAULT_MEMORY_MODE
    return {
        "mode": resolved,
        "sources": ["document", "signal"],
        "kinds": ["fact", "chunk", "summary"],
        "classifications_allowed": ["public", "internal"],
        "token_budget": 4000,
        "limit": 20,
        "status": "active",
        "provenance": provenance,
        "config_source": config_source,
        "scope_type": "dossier",
        "uses_tenant_curated": False,
        "uses_global_memory": False,
    }


def memory_scope_payload(
    *,
    dossier_id: uuid.UUID | str,
    mode: str,
    sources: list[str] | None = None,
    kinds: list[str] | None = None,
    classifications_allowed: list[str] | None = None,
) -> dict[str, Any]:
    """Honest, non-secret scope descriptor for API/UI.

    The motor only supports dossier-scoped retrieval (build_scope scope_type=dossier).
    tenant_curated / global / cross-tenant are explicitly false.
    """
    m = str(mode or "disabled").strip().lower()
    if m not in OPERATIONAL_MODES:
        m = "disabled"
    src = list(sources or [])
    knd = list(kinds or [])
    cls = list(classifications_allowed or [])
    return {
        "scope_type": "dossier",
        "scope_id": str(dossier_id),
        "dossier_only": True,
        "uses_tenant_curated": False,
        "uses_global_memory": False,
        "cross_tenant": False,
        "included_sources": src,
        "included_kinds": knd,
        "included_classifications": cls,
        "exclusions": [
            "other_dossiers",
            "other_tenants",
            "global_memory",
            "tenant_curated_cross_dossier",
        ],
        "summary_es": MODE_SCOPE_ES.get(m, MODE_SCOPE_ES["disabled"]),
        "retrieval_when_enabled": "dossier_scoped_signal_memory_v1",
    }


def legacy_missing_payload(
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    connection_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Read-only view for dossiers created before G-29 without a profile row.

    GET must not write. Callers may POST materialize (audited, idempotent).
    """
    cfg = default_profile_payload(
        provenance="legacy_missing",
        config_source="legacy_missing",
        mode="disabled",
    )
    cfg["status"] = "legacy_missing"
    return {
        "id": None,
        "tenant_id": str(tenant_id),
        "dossier_id": str(dossier_id),
        "connection_id": str(connection_id) if connection_id else None,
        "mode": "disabled",
        "mode_label_es": MODE_ES["disabled"],
        "version": 0,
        "etag": _etag(0, cfg),
        "sources": cfg["sources"],
        "kinds": cfg["kinds"],
        "classifications_allowed": cfg["classifications_allowed"],
        "token_budget": cfg["token_budget"],
        "limit": cfg["limit"],
        "status": "legacy_missing",
        "state": "legacy_missing",
        "provenance": "legacy_missing",
        "config_source": "legacy_missing",
        "scope": memory_scope_payload(
            dossier_id=dossier_id,
            mode="disabled",
            sources=cfg["sources"],
            kinds=cfg["kinds"],
            classifications_allowed=cfg["classifications_allowed"],
        ),
        "last_test_at": None,
        "last_test_status": None,
        "last_error": None,
        "last_coverage": None,
        "updated_at": None,
        "persisted": False,
        "available_modes": sorted(OPERATIONAL_MODES),
        "message_es": (
            "Este expediente no tiene perfil de memoria persistido (legado). "
            "No se ha escrito nada en esta lectura. Materializa el perfil para "
            "activarlo de forma explícita."
        ),
    }


def create_dossier_memory_profile(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    connection_id: uuid.UUID | None = None,
    mode: str | None = None,
    provenance: str = "server_policy_on_create",
    config_source: str = "server_policy",
) -> Any:
    """Insert an explicit DossierMemoryProfile on the caller's session (no commit).

    Used by create_dossier (atomic alta) and materialize. Mode is always
    server-policy unless an authorized update path supplies an operational mode.
    """
    from opn_oracle.integrations.models import DossierMemoryProfile

    resolved = str(mode or SERVER_DEFAULT_MEMORY_MODE).strip().lower()
    if resolved not in OPERATIONAL_MODES:
        resolved = SERVER_DEFAULT_MEMORY_MODE
    cfg = default_profile_payload(
        provenance=provenance,
        config_source=config_source,
        mode=resolved,
    )
    version = 1
    now = _now()
    row = DossierMemoryProfile(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        connection_id=connection_id,
        mode=resolved,
        version=version,
        etag=_etag(version, cfg),
        profile_config=cfg,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    return row


def profile_config_fingerprint(cfg: dict[str, Any], mode: str) -> dict[str, Any]:
    """Comparable subset for identical-retry detection (no etag/version)."""
    return {
        "mode": str(mode).strip().lower(),
        "sources": list(cfg.get("sources") or []),
        "kinds": list(cfg.get("kinds") or []),
        "classifications_allowed": list(cfg.get("classifications_allowed") or []),
        "token_budget": int(cfg.get("token_budget") or 4000),
        "limit": int(cfg.get("limit") or 20),
    }


def profile_to_public(row: Any) -> dict[str, Any]:
    """Public DTO — never includes secrets/provider/model."""
    cfg = dict(row.profile_config or {})
    mode = str(cfg.get("mode") or row.mode or "disabled")
    if mode not in OPERATIONAL_MODES:
        mode = "disabled"
    sources = list(cfg.get("sources") or [])
    kinds = list(cfg.get("kinds") or [])
    classifications = list(cfg.get("classifications_allowed") or [])
    status = str(cfg.get("status") or "active")
    config_source = str(cfg.get("config_source") or cfg.get("provenance") or "user")
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "dossier_id": str(row.dossier_id),
        "connection_id": str(row.connection_id) if row.connection_id else None,
        "mode": mode,
        "mode_label_es": MODE_ES.get(mode, mode),
        "version": int(row.version),
        "etag": row.etag,
        "sources": sources,
        "kinds": kinds,
        "classifications_allowed": classifications,
        "token_budget": int(cfg.get("token_budget") or 4000),
        "limit": int(cfg.get("limit") or 20),
        "status": status,
        "state": status if status == "legacy_missing" else "active",
        "provenance": cfg.get("provenance") or "tenant_default",
        "config_source": config_source,
        "scope": memory_scope_payload(
            dossier_id=row.dossier_id,
            mode=mode,
            sources=sources,
            kinds=kinds,
            classifications_allowed=classifications,
        ),
        "last_test_at": row.last_test_at.isoformat() if row.last_test_at else None,
        "last_test_status": row.last_test_status,
        "last_error": row.last_error,
        "last_coverage": row.last_coverage,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "available_modes": sorted(OPERATIONAL_MODES),
        # Profile DTO describes configuration only — never invent host health.
        # `publisher_reliable` is projected by memory_effective() from capability_payload().
    }
