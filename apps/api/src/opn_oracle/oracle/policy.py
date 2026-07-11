"""Resource-level authorization and tenant membership invariants."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, exists, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from opn_oracle.oracle.links import DossierCollaborator
from opn_oracle.oracle.models import StrategicDossier
from opn_oracle.platform.models import MembershipRole, Role, TenantMembership


def active_membership_exists(session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return bool(
        session.scalar(
            select(
                exists().where(
                    TenantMembership.tenant_id == tenant_id,
                    TenantMembership.user_id == user_id,
                    TenantMembership.status == "active",
                )
            )
        )
    )


def is_tenant_admin(session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return bool(
        session.scalar(
            select(
                exists()
                .where(
                    TenantMembership.tenant_id == tenant_id,
                    TenantMembership.user_id == user_id,
                    TenantMembership.status == "active",
                )
                .where(MembershipRole.membership_id == TenantMembership.id)
                .where(MembershipRole.role_id == Role.id)
                .where(Role.key.in_(("owner", "admin")))
            )
        )
    )


def dossier_accessible(
    session: Session,
    dossier: StrategicDossier,
    user_id: uuid.UUID,
    *,
    write: bool,
) -> bool:
    if not active_membership_exists(session, dossier.tenant_id, user_id):
        return False
    if dossier.owner_user_id == user_id or is_tenant_admin(session, dossier.tenant_id, user_id):
        return True
    roles = (
        ("owner", "editor", "collaborator")
        if write
        else (
            "owner",
            "editor",
            "collaborator",
            "viewer",
        )
    )
    return bool(
        session.scalar(
            select(
                exists().where(
                    DossierCollaborator.tenant_id == dossier.tenant_id,
                    DossierCollaborator.dossier_id == dossier.id,
                    DossierCollaborator.user_id == user_id,
                    DossierCollaborator.role.in_(roles),
                )
            )
        )
    )


def dossier_manageable(session: Session, dossier: StrategicDossier, user_id: uuid.UUID) -> bool:
    return active_membership_exists(session, dossier.tenant_id, user_id) and (
        dossier.owner_user_id == user_id or is_tenant_admin(session, dossier.tenant_id, user_id)
    )


def accessible_dossier_query(
    query: Select[tuple[StrategicDossier]],
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Select[tuple[StrategicDossier]]:
    return query.where(dossier_access_clause(tenant_id=tenant_id, user_id=user_id))


def dossier_access_clause(*, tenant_id: uuid.UUID, user_id: uuid.UUID) -> ColumnElement[bool]:
    admin = (
        select(Role.id)
        .join(MembershipRole, MembershipRole.role_id == Role.id)
        .join(TenantMembership, TenantMembership.id == MembershipRole.membership_id)
        .where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
            Role.key.in_(("owner", "admin")),
        )
        .exists()
    )
    collaborator = (
        select(DossierCollaborator.user_id)
        .where(
            DossierCollaborator.tenant_id == tenant_id,
            DossierCollaborator.dossier_id == StrategicDossier.id,
            DossierCollaborator.user_id == user_id,
        )
        .exists()
    )
    return (StrategicDossier.tenant_id == tenant_id) & or_(
        StrategicDossier.owner_user_id == user_id, collaborator, admin
    )
