"""Small tenant-safe repositories used by authentication and platform services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import Select, select, text
from sqlalchemy.orm import Session

from opn_oracle.platform.models import (
    MembershipRole,
    RolePermission,
    Tenant,
    TenantMembership,
)
from opn_oracle.tenants.context import TenantContext, get_tenant_context, require_tenant_id

ModelT = TypeVar("ModelT")


class TenantScopedRepository(Generic[ModelT]):
    def __init__(self, session: Session, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    def scoped_select(self) -> Select[tuple[ModelT]]:
        tenant_id = require_tenant_id()
        return select(self.model).where(self.model.tenant_id == tenant_id)  # type: ignore[attr-defined]

    def get(self, resource_id: UUID) -> ModelT | None:
        return self.session.scalar(
            self.scoped_select().where(self.model.id == resource_id)  # type: ignore[attr-defined]
        )


@dataclass(frozen=True, slots=True)
class MembershipSummary:
    membership_id: UUID
    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    membership_status: str


class TenantRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_active(self) -> Tenant | None:
        tenant_id = require_tenant_id()
        return self.session.scalar(
            select(Tenant).where(Tenant.id == tenant_id, Tenant.status == "active")
        )

    def get_active_by_id(self, tenant_id: UUID) -> Tenant | None:
        if tenant_id != require_tenant_id():
            return None
        return self.session.scalar(
            select(Tenant).where(Tenant.id == tenant_id, Tenant.status == "active")
        )

    def get_active_by_slug(self, slug: str) -> Tenant | None:
        tenant_id = require_tenant_id()
        return self.session.scalar(
            select(Tenant).where(
                Tenant.id == tenant_id,
                Tenant.slug == slug.strip().lower(),
                Tenant.status == "active",
            )
        )

    def memberships_for_authenticated_actor(self, actor_id: UUID) -> list[MembershipSummary]:
        rows = self.session.execute(
            text("SELECT * FROM oracle_actor_memberships(:actor_id)"),
            {"actor_id": actor_id},
        ).mappings()
        return [MembershipSummary(**dict(row)) for row in rows]


class TenantResolutionError(RuntimeError):
    """Raised when an authenticated actor cannot activate the requested tenant."""


class ActiveTenantResolver:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = TenantRepository(session)

    def resolve(
        self, *, actor_id: UUID, tenant_id: UUID | None = None, slug: str | None = None
    ) -> TenantContext:
        current = get_tenant_context(required=False)
        if current is None or current.actor_id != actor_id or current.tenant_id is not None:
            raise TenantResolutionError("La resolución exige identidad pre-tenant validada.")
        if self.session.new or self.session.dirty or self.session.deleted:
            raise TenantResolutionError("La resolución exige una Session limpia.")
        if (tenant_id is None) == (slug is None):
            raise TenantResolutionError("Indica exactamente tenant_id o slug.")
        normalized_slug = slug.strip().lower() if slug else None
        memberships = self.repository.memberships_for_authenticated_actor(actor_id)
        selected = next(
            (
                membership
                for membership in memberships
                if membership.membership_status == "active"
                and (tenant_id is None or membership.tenant_id == tenant_id)
                and (normalized_slug is None or membership.tenant_slug == normalized_slug)
            ),
            None,
        )
        if selected is None:
            self.session.rollback()
            raise TenantResolutionError("No existe una membership activa para el tenant.")
        # The SECURITY DEFINER lookup ran under an actor-only transaction. It must end before
        # callers install the returned tenant context on this Session.
        self.session.rollback()
        return TenantContext(tenant_id=selected.tenant_id, actor_id=actor_id)


class PermissionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def has_permission(self, user_id: UUID, permission: str) -> bool:
        tenant_id = require_tenant_id()
        statement = (
            select(RolePermission.permission_key)
            .join(
                MembershipRole,
                (MembershipRole.role_id == RolePermission.role_id)
                & (MembershipRole.tenant_id == RolePermission.tenant_id),
            )
            .join(
                TenantMembership,
                (TenantMembership.id == MembershipRole.membership_id)
                & (TenantMembership.tenant_id == MembershipRole.tenant_id),
            )
            .where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.user_id == user_id,
                TenantMembership.status == "active",
                RolePermission.permission_key == permission,
            )
            .limit(1)
        )
        return self.session.scalar(statement) is not None
