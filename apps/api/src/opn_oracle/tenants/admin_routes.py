"""Tenant-scoped membership and role administration."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from apiflask import APIBlueprint
from flask import current_app, g, request
from flask_login import current_user
from sqlalchemy import delete, func, select, update

from opn_oracle.auth.permissions import recent_auth_required, require_permission
from opn_oracle.auth.tokens import hash_token, stable_invitation_token
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db
from opn_oracle.jobs.service import publish_job, stage_job
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.platform.models import (
    AuditEvent,
    Invitation,
    MembershipRole,
    Role,
    TenantMembership,
    User,
    UserSession,
)

bp = APIBlueprint(
    "tenant_admin", __name__, url_prefix="/api/v1/tenant-admin", tag="Administración de tenant"
)


def _payload() -> dict[str, Any]:
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


def _membership(member_id: UUID) -> TenantMembership | None:
    return db.session.scalar(
        select(TenantMembership).where(
            TenantMembership.id == member_id, TenantMembership.tenant_id == g.active_tenant_id
        )
    )


def _owner_count() -> int:
    return int(
        db.session.scalar(
            select(func.count())
            .select_from(TenantMembership)
            .join(MembershipRole, MembershipRole.membership_id == TenantMembership.id)
            .join(Role, Role.id == MembershipRole.role_id)
            .where(
                TenantMembership.tenant_id == g.active_tenant_id,
                TenantMembership.status == "active",
                Role.key == "owner",
            )
        )
        or 0
    )


def _lock_owners() -> None:
    """Serialize last-owner checks for the active tenant."""

    db.session.execute(
        select(TenantMembership.id)
        .join(MembershipRole, MembershipRole.membership_id == TenantMembership.id)
        .join(Role, Role.id == MembershipRole.role_id)
        .where(
            TenantMembership.tenant_id == g.active_tenant_id,
            TenantMembership.status == "active",
            Role.key == "owner",
        )
        .with_for_update(of=TenantMembership)
    ).all()


@bp.get("/members")
@require_permission("tenant.users.manage")
def list_members() -> dict[str, Any]:
    rows = db.session.execute(
        select(TenantMembership, User)
        .join(User, User.id == TenantMembership.user_id)
        .where(TenantMembership.tenant_id == g.active_tenant_id)
        .order_by(User.display_name)
    ).all()
    role_rows = db.session.execute(
        select(MembershipRole.membership_id, Role.key)
        .join(
            Role,
            (Role.id == MembershipRole.role_id) & (Role.tenant_id == MembershipRole.tenant_id),
        )
        .where(MembershipRole.tenant_id == g.active_tenant_id)
        .order_by(Role.key)
    ).all()
    roles_by_membership: dict[UUID, list[str]] = {}
    for membership_id, role_key in role_rows:
        roles_by_membership.setdefault(membership_id, []).append(role_key)
    return {
        "items": [
            {
                "id": str(member.id),
                "user_id": str(user.id),
                "email": user.email,
                "display_name": user.display_name,
                "status": member.status,
                "roles": roles_by_membership.get(member.id, []),
            }
            for member, user in rows
        ]
    }


@bp.post("/members")
@recent_auth_required
@require_permission("tenant.users.manage")
def invite_member() -> tuple[Any, int]:
    payload = _payload()
    email = str(payload.get("email", "")).strip().casefold()
    role_key = str(payload.get("role", "viewer"))
    if "@" not in email or role_key not in {
        "owner",
        "admin",
        "editor",
        "analyst",
        "viewer",
        "auditor",
    }:
        return problem_response(422, detail="Email o rol no válido.", code="validation_error")[:2]
    user = db.session.scalar(select(User).where(User.email == email))
    if user is not None and user.status in {"disabled", "locked"}:
        return problem_response(
            409, detail="La cuenta requiere revisión antes de invitarla.", code="user_unavailable"
        )[:2]
    if user is None:
        user = User(
            email=email,
            display_name=str(payload.get("name") or email.split("@", 1)[0])[:200],
            status="invited",
        )
        db.session.add(user)
        db.session.flush()
    membership = db.session.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == g.active_tenant_id, TenantMembership.user_id == user.id
        )
    )
    if membership is None:
        membership = TenantMembership(
            tenant_id=g.active_tenant_id,
            user_id=user.id,
            status="invited",
            invited_at=datetime.now(UTC),
        )
        db.session.add(membership)
        db.session.flush()
    elif membership.status in {"active", "revoked", "suspended"}:
        return problem_response(
            409,
            detail="La membership ya existe o requiere reactivación explícita.",
            code="membership_unavailable",
        )[:2]
    role = db.session.scalar(
        select(Role).where(Role.tenant_id == g.active_tenant_id, Role.key == role_key)
    )
    assert role is not None
    if db.session.get(MembershipRole, (g.active_tenant_id, membership.id, role.id)) is None:
        db.session.add(
            MembershipRole(
                tenant_id=g.active_tenant_id, membership_id=membership.id, role_id=role.id
            )
        )
    db.session.execute(
        update(Invitation)
        .where(
            Invitation.membership_id == membership.id,
            Invitation.used_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    invitation_id = uuid4()
    invitation = Invitation(
        id=invitation_id,
        tenant_id=g.active_tenant_id,
        membership_id=membership.id,
        token_hash=hash_token(
            stable_invitation_token(
                invitation_id=invitation_id,
                secret_key=current_app.config["SECRET_KEY"],
            )
        ),
        expires_at=datetime.now(UTC) + timedelta(hours=current_app.config["INVITATION_TTL_HOURS"]),
        invited_by_user_id=current_user.id,
    )
    db.session.add(invitation)
    job = stage_job(
        "notifications.send_email",
        payload={"kind": "invitation", "invitation_id": str(invitation.id)},
        idempotency_key=f"invitation-email:{invitation.id}",
        requested_by_user_id=current_user.id,
        resource_type="invitation",
        resource_id=invitation.id,
    )
    append_audit_event(
        db.session,
        action="tenant.member.invited",
        resource_type="membership",
        resource_id=membership.id,
        result="success",
        metadata={"email_hash": hashlib.sha256(email.encode()).hexdigest(), "role": role_key},
    )
    db.session.commit()
    publish_job(job)
    return {"id": str(membership.id)}, 201


@bp.patch("/members/<uuid:member_id>")
@recent_auth_required
@require_permission("tenant.users.manage")
def patch_member(member_id: UUID) -> tuple[Any, int] | dict[str, str]:
    member = _membership(member_id)
    status = str(_payload().get("status", ""))
    if member is None or status not in {"active", "suspended"}:
        return problem_response(404, detail="Membership no encontrada.", code="not_found")[:2]
    if member.status not in {"active", "suspended"}:
        return problem_response(
            409,
            detail="Una invitación solo puede activarse aceptando su token.",
            code="invalid_membership_transition",
        )[:2]
    _lock_owners()
    is_owner = db.session.scalar(
        select(func.count())
        .select_from(MembershipRole)
        .join(Role, Role.id == MembershipRole.role_id)
        .where(MembershipRole.membership_id == member.id, Role.key == "owner")
    )
    if status == "suspended" and is_owner and _owner_count() <= 1:
        return problem_response(
            409, detail="No se puede suspender el último propietario.", code="last_owner"
        )[:2]
    member.status = status
    db.session.execute(
        update(UserSession)
        .where(
            UserSession.user_id == member.user_id,
            UserSession.active_tenant_id == g.active_tenant_id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    append_audit_event(
        db.session,
        action="tenant.member.status_changed",
        resource_type="membership",
        resource_id=member.id,
        result="success",
        metadata={"status": status},
    )
    db.session.commit()
    return {"status": status}


@bp.delete("/members/<uuid:member_id>")
@recent_auth_required
@require_permission("tenant.users.manage")
def remove_member(member_id: UUID) -> tuple[Any, int] | tuple[str, int]:
    member = _membership(member_id)
    if member is None:
        return problem_response(404, detail="Membership no encontrada.", code="not_found")[:2]
    _lock_owners()
    is_owner = db.session.scalar(
        select(func.count())
        .select_from(MembershipRole)
        .join(Role, Role.id == MembershipRole.role_id)
        .where(MembershipRole.membership_id == member.id, Role.key == "owner")
    )
    if is_owner and _owner_count() <= 1:
        return problem_response(
            409, detail="No se puede eliminar el último propietario.", code="last_owner"
        )[:2]
    member.status = "revoked"
    db.session.execute(
        update(UserSession)
        .where(
            UserSession.user_id == member.user_id,
            UserSession.active_tenant_id == g.active_tenant_id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    append_audit_event(
        db.session,
        action="tenant.member.removed",
        resource_type="membership",
        resource_id=member.id,
        result="success",
    )
    db.session.commit()
    return "", 204


@bp.post("/members/<uuid:member_id>/resend-invite")
@recent_auth_required
@require_permission("tenant.users.manage")
def resend_invite(member_id: UUID) -> tuple[Any, int] | tuple[str, int]:
    member = _membership(member_id)
    if member is None or member.status != "invited":
        return problem_response(404, detail="Invitación no encontrada.", code="not_found")[:2]
    db.session.execute(
        update(Invitation)
        .where(
            Invitation.membership_id == member.id,
            Invitation.used_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    invitation_id = uuid4()
    invitation = Invitation(
        id=invitation_id,
        tenant_id=g.active_tenant_id,
        membership_id=member.id,
        token_hash=hash_token(
            stable_invitation_token(
                invitation_id=invitation_id,
                secret_key=current_app.config["SECRET_KEY"],
            )
        ),
        expires_at=datetime.now(UTC) + timedelta(hours=current_app.config["INVITATION_TTL_HOURS"]),
        invited_by_user_id=current_user.id,
    )
    db.session.add(invitation)
    job = stage_job(
        "notifications.send_email",
        payload={"kind": "invitation", "invitation_id": str(invitation.id)},
        idempotency_key=f"invitation-email:{invitation.id}",
        requested_by_user_id=current_user.id,
        resource_type="invitation",
        resource_id=invitation.id,
    )
    append_audit_event(
        db.session,
        action="tenant.invitation.reissued",
        resource_type="membership",
        resource_id=member.id,
        result="success",
    )
    db.session.commit()
    publish_job(job)
    return "", 204


@bp.get("/roles")
@require_permission("tenant.users.manage")
def list_roles() -> dict[str, Any]:
    rows = db.session.scalars(
        select(Role).where(Role.tenant_id == g.active_tenant_id).order_by(Role.name)
    )
    return {
        "items": [
            {"id": str(row.id), "key": row.key, "name": row.name, "description": row.description}
            for row in rows
        ]
    }


@bp.patch("/members/<uuid:member_id>/roles")
@recent_auth_required
@require_permission("tenant.users.manage")
def replace_roles(member_id: UUID) -> tuple[Any, int] | dict[str, Any]:
    member, keys = _membership(member_id), _payload().get("roles", [])
    if member is None or not isinstance(keys, list) or not keys:
        return problem_response(
            422, detail="Membership y roles son obligatorios.", code="validation_error"
        )[:2]
    roles = list(
        db.session.scalars(
            select(Role).where(
                Role.tenant_id == g.active_tenant_id, Role.key.in_([str(key) for key in keys])
            )
        )
    )
    if len(roles) != len(set(keys)):
        return problem_response(
            422, detail="Uno o más roles no son válidos.", code="validation_error"
        )[:2]
    _lock_owners()
    had_owner = bool(
        db.session.scalar(
            select(func.count())
            .select_from(MembershipRole)
            .join(Role, Role.id == MembershipRole.role_id)
            .where(MembershipRole.membership_id == member.id, Role.key == "owner")
        )
    )
    if had_owner and "owner" not in keys and _owner_count() <= 1:
        return problem_response(
            409, detail="No se puede retirar el último propietario.", code="last_owner"
        )[:2]
    db.session.execute(delete(MembershipRole).where(MembershipRole.membership_id == member.id))
    db.session.add_all(
        MembershipRole(tenant_id=g.active_tenant_id, membership_id=member.id, role_id=role.id)
        for role in roles
    )
    db.session.execute(
        update(UserSession)
        .where(
            UserSession.user_id == member.user_id,
            UserSession.active_tenant_id == g.active_tenant_id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    append_audit_event(
        db.session,
        action="tenant.member.roles_changed",
        resource_type="membership",
        resource_id=member.id,
        result="success",
        metadata={"roles": sorted(str(key) for key in keys)},
    )
    db.session.commit()
    return {"roles": sorted(str(key) for key in keys)}


@bp.get("/audit")
@require_permission("audit.read")
def tenant_audit() -> dict[str, Any]:
    rows = db.session.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == g.active_tenant_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(200)
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "action": row.action,
                "result": row.result,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }
