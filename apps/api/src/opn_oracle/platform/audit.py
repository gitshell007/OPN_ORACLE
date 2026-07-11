"""Append-only audit creation with recursive secret redaction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import text

from opn_oracle.common.logging import sanitize
from opn_oracle.platform.models import AuditEvent
from opn_oracle.tenants.context import TenantContextMissing, get_tenant_context


def sanitize_audit_metadata(value: Any, *, key: str = "") -> Any:
    return sanitize(value, key=key or None)


def append_audit_event(
    session: Any,
    *,
    action: str,
    resource_type: str,
    result: str,
    metadata: Mapping[str, Any] | None = None,
    resource_id: UUID | None = None,
    request_id: str | None = None,
    correlation_id: str | None = None,
    dossier_id: UUID | None = None,
    allow_global: bool = False,
) -> AuditEvent:
    context = get_tenant_context(required=False)
    if (context is None or context.tenant_id is None) and not allow_global:
        raise TenantContextMissing(
            "Un evento global requiere allow_global=True en un flujo de plataforma explícito."
        )
    event = AuditEvent(
        tenant_id=context.tenant_id if context else None,
        actor_type="user" if context and context.actor_id else "service",
        actor_id=context.actor_id if context else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        result=result,
        request_id=request_id,
        correlation_id=correlation_id,
        dossier_id=dossier_id,
        event_metadata=sanitize_audit_metadata(metadata or {}),
    )
    session.add(event)
    return event


def append_global_audit_event(
    session: Any,
    *,
    action: str,
    resource_type: str,
    result: str,
    actor_id: UUID | None = None,
    resource_id: UUID | None = None,
    metadata: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> None:
    """Append a narrow global auth/platform audit through the hardened DB boundary."""

    safe_metadata = sanitize_audit_metadata(metadata or {})
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        session.execute(
            text(
                "SELECT oracle_append_global_audit(:action,:resource_type,:result,:actor_id,"
                ":resource_id,CAST(:metadata AS jsonb),:request_id,:correlation_id)"
            ),
            {
                "action": action,
                "resource_type": resource_type,
                "result": result,
                "actor_id": actor_id,
                "resource_id": resource_id,
                "metadata": __import__("json").dumps(safe_metadata),
                "request_id": request_id,
                "correlation_id": correlation_id,
            },
        )
        return
    session.add(
        AuditEvent(
            tenant_id=None,
            actor_type="user" if actor_id else "service",
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            request_id=request_id,
            correlation_id=correlation_id,
            event_metadata=safe_metadata,
        )
    )
