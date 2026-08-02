"""DossierMemoryProfile + connection resolution (MDEV-04 provisional)."""

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

MODE_ES = {
    "disabled": "Desactivada",
    "shadow": "Solo observar",
    "augment": "Usar para responder",
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


def default_profile_payload() -> dict[str, Any]:
    return {
        "mode": "disabled",
        "sources": ["document", "signal"],
        "kinds": ["fact", "chunk", "summary"],
        "classifications_allowed": ["public", "internal"],
        "token_budget": 4000,
        "limit": 20,
        "status": "active",
        "provenance": "tenant_default",
    }


def profile_to_public(row: Any) -> dict[str, Any]:
    """Public DTO — never includes secrets/provider/model."""
    cfg = dict(row.profile_config or {})
    mode = str(cfg.get("mode") or row.mode or "disabled")
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "dossier_id": str(row.dossier_id),
        "connection_id": str(row.connection_id) if row.connection_id else None,
        "mode": mode,
        "mode_label_es": MODE_ES.get(mode, mode),
        "version": int(row.version),
        "etag": row.etag,
        "sources": cfg.get("sources") or [],
        "kinds": cfg.get("kinds") or [],
        "classifications_allowed": cfg.get("classifications_allowed") or [],
        "token_budget": int(cfg.get("token_budget") or 4000),
        "limit": int(cfg.get("limit") or 20),
        "status": cfg.get("status") or "active",
        "provenance": cfg.get("provenance") or "tenant_default",
        "last_test_at": row.last_test_at.isoformat() if row.last_test_at else None,
        "last_test_status": row.last_test_status,
        "last_error": row.last_error,
        "last_coverage": row.last_coverage,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deferred_blockers": [
            "RACE-MDEV02-003",
            "DB-MDEV02-001",
            "SEC-MDEV03-001",
        ],
        "publisher_reliable": False,
        "actions_reliable": False,
    }
