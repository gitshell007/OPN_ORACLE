"""DossierMemoryProfile + connection resolution (MDEV-04 / G-29 honest profile).

Engine-supported modes only: disabled | shadow | augment.
Retrieval is always dossier-scoped (scope_type=dossier). There is no global,
cross-tenant or tenant_curated memory mode in the motor — do not advertise them.

Effective profile SSOT (G-29 correctivo):
  Product path uses ONLY the default profile (connection_id IS NULL).
  Rows bound to connection_id are schema-legacy / deferred product capability:
  they are never selected for conversation retrieval or /memory/effective mode.
  PUT /memory/profile always updates the default row; body.connection_id cannot
  create a parallel product profile.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
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

# Product resolution sources (shared by jobs, /memory/effective, UI).
RESOLUTION_DEFAULT_PROFILE = "default_profile"
RESOLUTION_LEGACY_MISSING = "legacy_missing"
# Documented deferred: connection-bound rows exist in schema but are not product-selected.
RESOLUTION_DEFERRED_CONNECTION_OVERRIDES = "connection_override_deferred"

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


def normalize_operational_mode(raw: Any) -> OracleMemoryMode:
    """Fail-closed: unknown/missing → disabled. Never invents augment."""
    mode = str(raw or "").strip().lower()
    if mode in OPERATIONAL_MODES:
        return mode  # type: ignore[return-value]
    return SERVER_DEFAULT_MEMORY_MODE


@dataclass(frozen=True)
class EffectiveMemoryResolution:
    """Single product view of which memory profile/mode applies.

    Shared by conversation jobs, GET /memory/effective, and UI projection.
    """

    mode: OracleMemoryMode
    profile_id: str | None
    version: int | None
    scope_type: str
    resolution_source: str
    persisted: bool
    state: str
    profile_config: dict[str, Any] = field(default_factory=dict)
    row: Any | None = None
    connection_id: None = None  # product path always uses default (NULL)
    deferred_connection_profile_count: int = 0
    deferred_connection_profiles: list[dict[str, Any]] = field(default_factory=list)
    reason_es: str = ""

    def identity_fields(self) -> dict[str, Any]:
        """Shared fields for answer/snapshot/audit/UI consistency."""
        return {
            "memory_mode": self.mode,
            "memory_profile_id": self.profile_id,
            "memory_profile_version": self.version,
            "memory_scope_type": self.scope_type,
            "resolution_source": self.resolution_source,
        }


def load_default_dossier_memory_profile(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
) -> Any | None:
    """Load the product default profile (connection_id IS NULL). No write."""
    from opn_oracle.integrations.models import DossierMemoryProfile

    return session.scalar(
        select(DossierMemoryProfile).where(
            DossierMemoryProfile.tenant_id == tenant_id,
            DossierMemoryProfile.dossier_id == dossier_id,
            DossierMemoryProfile.connection_id.is_(None),
        )
    )


def list_deferred_connection_memory_profiles(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
) -> list[Any]:
    """Connection-bound rows: schema-allowed but not product-selected."""
    from opn_oracle.integrations.models import DossierMemoryProfile

    return list(
        session.scalars(
            select(DossierMemoryProfile).where(
                DossierMemoryProfile.tenant_id == tenant_id,
                DossierMemoryProfile.dossier_id == dossier_id,
                DossierMemoryProfile.connection_id.is_not(None),
            )
        ).all()
    )


def resolve_effective_dossier_memory_profile(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
) -> EffectiveMemoryResolution:
    """Domain SSOT for effective memory mode/profile.

    Precedence (product, explicit):
      1. Default profile (connection_id IS NULL) → resolution_source=default_profile
      2. No default row → disabled, resolution_source=legacy_missing (no write)

    Connection-bound profiles are NEVER selected. They are counted/listed as
    deferred so UI/API can show they exist without silent divergence from jobs.

    Callers: process_dossier_question_answer, GET /memory/effective (and UI via it).
    """
    deferred_rows = list_deferred_connection_memory_profiles(
        session, tenant_id=tenant_id, dossier_id=dossier_id
    )
    deferred_public = [
        {
            "id": str(r.id),
            "connection_id": str(r.connection_id) if r.connection_id else None,
            "mode": normalize_operational_mode(
                (r.profile_config or {}).get("mode") if r.profile_config else r.mode
            ),
            "version": int(r.version),
            "status": "deferred_connection_override",
            "product_supported": False,
            "note_es": (
                "Override ligado a connection_id: capacidad diferida. "
                "No participa en el modo efectivo del producto."
            ),
        }
        for r in deferred_rows
    ]
    deferred_count = len(deferred_rows)

    row = load_default_dossier_memory_profile(session, tenant_id=tenant_id, dossier_id=dossier_id)
    if row is None:
        cfg = default_profile_payload(
            provenance="legacy_missing",
            config_source="legacy_missing",
            mode="disabled",
        )
        return EffectiveMemoryResolution(
            mode="disabled",
            profile_id=None,
            version=None,
            scope_type="dossier",
            resolution_source=RESOLUTION_LEGACY_MISSING,
            persisted=False,
            state="legacy_missing",
            profile_config=cfg,
            row=None,
            deferred_connection_profile_count=deferred_count,
            deferred_connection_profiles=deferred_public,
            reason_es=(
                "Sin perfil default persistido (legacy_missing). "
                "Modo efectivo disabled; no se usa memoria ni se escribe en lectura."
                + (
                    f" Hay {deferred_count} override(s) por conexión diferidos (no seleccionados)."
                    if deferred_count
                    else ""
                )
            ),
        )

    cfg = dict(row.profile_config or {})
    mode = normalize_operational_mode(cfg.get("mode") or row.mode)
    # Fail-closed honesty: never report augment/shadow without a real profile identity.
    profile_id = str(row.id)
    version = int(row.version)
    if mode in {"augment", "shadow"} and (not profile_id or version < 1):
        mode = "disabled"

    return EffectiveMemoryResolution(
        mode=mode,
        profile_id=profile_id,
        version=version,
        scope_type="dossier",
        resolution_source=RESOLUTION_DEFAULT_PROFILE,
        persisted=True,
        state=str(cfg.get("status") or "active"),
        profile_config=cfg,
        row=row,
        deferred_connection_profile_count=deferred_count,
        deferred_connection_profiles=deferred_public,
        reason_es=(
            "Perfil default del expediente (connection_id nulo)."
            + (
                f" {deferred_count} override(s) por conexión existen pero están diferidos "
                f"({RESOLUTION_DEFERRED_CONNECTION_OVERRIDES})."
                if deferred_count
                else ""
            )
        ),
    )


def effective_resolution_to_public(
    resolution: EffectiveMemoryResolution,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
) -> dict[str, Any]:
    """Build public DTO for /memory/effective from a shared resolution.

    Distinguishes configured_profile (default row management surface) from
    effective_profile (what jobs/UI must use). With current precedence they
    share the same mode; structure is ready if authorized overrides return later.
    """
    if resolution.row is not None:
        configured = profile_to_public(resolution.row)
        configured["persisted"] = True
    else:
        configured = legacy_missing_payload(
            tenant_id=tenant_id, dossier_id=dossier_id, connection_id=None
        )

    # Effective view mirrors the mode actually used by retrieval/jobs.
    effective = dict(configured)
    effective["mode"] = resolution.mode
    effective["mode_label_es"] = MODE_ES.get(resolution.mode, resolution.mode)
    effective["id"] = resolution.profile_id
    effective["version"] = resolution.version if resolution.version is not None else 0
    effective["persisted"] = resolution.persisted
    effective["state"] = resolution.state
    effective["status"] = (
        "legacy_missing"
        if resolution.resolution_source == RESOLUTION_LEGACY_MISSING
        else configured.get("status")
    )
    effective["resolution_source"] = resolution.resolution_source
    effective["scope"] = memory_scope_payload(
        dossier_id=dossier_id,
        mode=resolution.mode,
        sources=list(resolution.profile_config.get("sources") or configured.get("sources") or []),
        kinds=list(resolution.profile_config.get("kinds") or configured.get("kinds") or []),
        classifications_allowed=list(
            resolution.profile_config.get("classifications_allowed")
            or configured.get("classifications_allowed")
            or []
        ),
    )
    effective["scope_type"] = resolution.scope_type

    # Top-level SSOT fields (answer/snapshot/UI share these names).
    body = dict(effective)
    body["configured_profile"] = configured
    body["effective_profile"] = {
        "id": resolution.profile_id,
        "mode": resolution.mode,
        "mode_label_es": MODE_ES.get(resolution.mode, resolution.mode),
        "version": resolution.version,
        "scope_type": resolution.scope_type,
        "resolution_source": resolution.resolution_source,
        "persisted": resolution.persisted,
        "state": resolution.state,
        "connection_id": None,
    }
    body["resolution_source"] = resolution.resolution_source
    body["resolution_reason_es"] = resolution.reason_es
    body["deferred_connection_profiles"] = list(resolution.deferred_connection_profiles)
    body["deferred_connection_profile_count"] = resolution.deferred_connection_profile_count
    body["profiles_diverge"] = (
        str(configured.get("mode")) != str(resolution.mode)
        or str(configured.get("id")) != str(resolution.profile_id)
        or int(configured.get("version") or 0) != int(resolution.version or 0)
    )
    return body


def profile_to_public(row: Any) -> dict[str, Any]:
    """Public DTO — never includes secrets/provider/model."""
    cfg = dict(row.profile_config or {})
    mode = normalize_operational_mode(cfg.get("mode") or row.mode)
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
        "scope_type": "dossier",
        "last_test_at": row.last_test_at.isoformat() if row.last_test_at else None,
        "last_test_status": row.last_test_status,
        "last_error": row.last_error,
        "last_coverage": row.last_coverage,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "available_modes": sorted(OPERATIONAL_MODES),
        # Profile DTO describes configuration only — never invent host health.
        # `publisher_reliable` is projected by memory_effective() from capability_payload().
    }
