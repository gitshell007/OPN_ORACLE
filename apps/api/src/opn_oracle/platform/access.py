"""Explicit, audited platform-superadmin access to one tenant at a time."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from opn_oracle.platform.audit import append_audit_event
from opn_oracle.platform.models import Tenant, User
from opn_oracle.tenants.context import TenantContext, get_tenant_context, tenant_context


class PlatformAccessDenied(RuntimeError):
    """Raised without revealing whether the actor or target exists."""


def authorize_platform_tenant_access(
    session: Session, *, actor_id: UUID, target_tenant_id: UUID, reason: str
) -> TenantContext:
    current = get_tenant_context(required=False)
    normalized_reason = reason.strip()
    if current is None or current.actor_id != actor_id or current.tenant_id is not None:
        raise PlatformAccessDenied("Se requiere identidad pre-tenant validada.")
    if session.new or session.dirty or session.deleted:
        raise PlatformAccessDenied("El acceso de plataforma exige una Session limpia.")
    if len(normalized_reason) < 8:
        raise PlatformAccessDenied("El motivo de acceso es obligatorio y debe ser específico.")
    user = session.scalar(
        select(User).where(
            User.id == actor_id,
            User.status == "active",
            User.platform_role == "super_admin",
        )
    )
    target = session.scalar(
        select(Tenant).where(Tenant.id == target_tenant_id, Tenant.status == "active")
    )
    if user is None or target is None:
        session.rollback()
        raise PlatformAccessDenied("Acceso de plataforma no autorizado.")

    # Finish the global validation transaction before installing a tenant-bound context.
    session.rollback()
    context = TenantContext(
        tenant_id=target_tenant_id,
        actor_id=actor_id,
        access_reason=normalized_reason,
        platform_access=True,
    )
    with tenant_context(context):
        append_audit_event(
            session,
            action="platform.tenant_access.authorized",
            resource_type="tenant",
            resource_id=target_tenant_id,
            result="success",
            metadata={"reason": normalized_reason, "access_mode": "platform_super_admin"},
        )
        session.commit()
    return context
