"""Platform-superadmin tenant lifecycle API."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from apiflask import APIBlueprint
from flask import current_app, request
from flask_login import current_user
from sqlalchemy import select, text, update

from opn_oracle.auth.permissions import recent_auth_required, require_platform_admin
from opn_oracle.auth.tokens import hash_token, stable_invitation_token
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db
from opn_oracle.jobs.service import publish_job, stage_job
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.platform.models import (
    AuditEvent,
    Invitation,
    MembershipRole,
    Tenant,
    TenantMembership,
    User,
    UserSession,
    Workspace,
)
from opn_oracle.platform.rbac import seed_system_roles
from opn_oracle.tenants.context import TenantContext, tenant_context

bp = APIBlueprint("platform", __name__, url_prefix="/api/v1/platform", tag="Plataforma")


def _payload() -> dict[str, Any]:
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:63]


@bp.get("/tenants")
@require_platform_admin
def list_tenants() -> dict[str, Any]:
    rows = db.session.scalars(select(Tenant).order_by(Tenant.name))
    return {
        "items": [
            {
                "id": str(row.id),
                "slug": row.slug,
                "name": row.name,
                "status": row.status,
                "plan": row.plan,
            }
            for row in rows
        ]
    }


@bp.post("/tenants")
@recent_auth_required
@require_platform_admin
def create_tenant() -> tuple[Any, int]:
    payload = _payload()
    name, slug = (
        str(payload.get("name", "")).strip(),
        _slug(str(payload.get("slug") or payload.get("name", ""))),
    )
    if len(name) < 2 or not slug:
        return problem_response(
            422, detail="Nombre y slug son obligatorios.", code="validation_error"
        )[:2]
    actor_id = current_user.id
    tenant = Tenant(
        id=uuid.uuid4(), name=name, slug=slug, status="active", plan=payload.get("plan")
    )
    db.session.rollback()
    with tenant_context(
        TenantContext(
            tenant_id=tenant.id,
            actor_id=actor_id,
            platform_access=True,
            access_reason="Creación de tenant",
        )
    ):
        db.session.add(tenant)
        db.session.add(
            Workspace(
                tenant_id=tenant.id,
                slug="principal",
                name="Principal",
                status="active",
                is_default=True,
            )
        )
        seed_system_roles(db.session, tenant.id)
        append_audit_event(
            db.session,
            action="platform.tenant.created",
            resource_type="tenant",
            resource_id=tenant.id,
            result="success",
            metadata={"slug": slug},
        )
        db.session.commit()
    return {
        "id": str(tenant.id),
        "slug": tenant.slug,
        "name": tenant.name,
        "status": tenant.status,
    }, 201


@bp.get("/tenants/<uuid:tenant_id>")
@require_platform_admin
def get_tenant(tenant_id: UUID) -> tuple[Any, int] | dict[str, Any]:
    row = db.session.get(Tenant, tenant_id)
    if row is None:
        return problem_response(404, detail="Tenant no encontrado.", code="not_found")[:2]
    return {
        "id": str(row.id),
        "slug": row.slug,
        "name": row.name,
        "status": row.status,
        "plan": row.plan,
        "locale": row.locale,
        "timezone": row.timezone,
    }


@bp.patch("/tenants/<uuid:tenant_id>")
@recent_auth_required
@require_platform_admin
def patch_tenant(tenant_id: UUID) -> tuple[Any, int] | dict[str, Any]:
    row = db.session.get(Tenant, tenant_id)
    if row is None:
        return problem_response(404, detail="Tenant no encontrado.", code="not_found")[:2]
    payload = _payload()
    if "name" in payload and str(payload["name"]).strip():
        row.name = str(payload["name"]).strip()[:200]
    if "plan" in payload:
        row.plan = str(payload["plan"])[:50] if payload["plan"] else None
    db.session.commit()
    return {"id": str(row.id), "name": row.name, "status": row.status}


def _set_tenant_status(tenant_id: UUID, status: str) -> tuple[Any, int] | tuple[str, int]:
    actor_id = current_user.id
    row = db.session.get(Tenant, tenant_id)
    if row is None:
        return problem_response(404, detail="Tenant no encontrado.", code="not_found")[:2]
    row.status = status
    db.session.flush()
    db.session.execute(
        update(UserSession)
        .where(UserSession.active_tenant_id == tenant_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    db.session.commit()
    db.session.rollback()
    with tenant_context(
        TenantContext(
            tenant_id=tenant_id,
            actor_id=actor_id,
            platform_access=True,
            access_reason=f"Cambio de estado a {status}",
        )
    ):
        append_audit_event(
            db.session,
            action=f"platform.tenant.{status}",
            resource_type="tenant",
            resource_id=tenant_id,
            result="success",
        )
        db.session.commit()
    return "", 204


@bp.post("/tenants/<uuid:tenant_id>/suspend")
@recent_auth_required
@require_platform_admin
def suspend_tenant(tenant_id: UUID) -> tuple[Any, int] | tuple[str, int]:
    return _set_tenant_status(tenant_id, "suspended")


@bp.post("/tenants/<uuid:tenant_id>/reactivate")
@recent_auth_required
@require_platform_admin
def reactivate_tenant(tenant_id: UUID) -> tuple[Any, int] | tuple[str, int]:
    return _set_tenant_status(tenant_id, "active")


@bp.post("/tenants/<uuid:tenant_id>/invite-owner")
@recent_auth_required
@require_platform_admin
def invite_owner(tenant_id: UUID) -> tuple[Any, int]:
    payload = _payload()
    email, name, actor_id = (
        str(payload.get("email", "")).strip().casefold(),
        str(payload.get("name", "")).strip(),
        current_user.id,
    )
    tenant = db.session.get(Tenant, tenant_id)
    if tenant is None or tenant.status != "active" or "@" not in email:
        return problem_response(422, detail="Tenant o email no válido.", code="validation_error")[
            :2
        ]
    db.session.rollback()
    with tenant_context(
        TenantContext(
            tenant_id=tenant_id,
            actor_id=actor_id,
            platform_access=True,
            access_reason="Invitar propietario",
        )
    ):
        user = db.session.scalar(select(User).where(User.email == email))
        if user is not None and user.status in {"disabled", "locked"}:
            return problem_response(
                409,
                detail="La cuenta requiere revisión antes de invitarla.",
                code="user_unavailable",
            )[:2]
        if user is None:
            user = User(email=email, display_name=name or email.split("@", 1)[0], status="invited")
            db.session.add(user)
            db.session.flush()
        membership = db.session.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == tenant_id, TenantMembership.user_id == user.id
            )
        )
        if membership is None:
            membership = TenantMembership(
                tenant_id=tenant_id, user_id=user.id, status="invited", invited_at=datetime.now(UTC)
            )
            db.session.add(membership)
            db.session.flush()
        elif membership.status in {"active", "suspended", "revoked"}:
            return problem_response(
                409,
                detail="La membership ya existe o requiere reactivación explícita.",
                code="membership_unavailable",
            )[:2]
        owner = db.session.scalar(
            select(__import__("opn_oracle.platform.models", fromlist=["Role"]).Role).where(
                __import__("opn_oracle.platform.models", fromlist=["Role"]).Role.tenant_id
                == tenant_id,
                __import__("opn_oracle.platform.models", fromlist=["Role"]).Role.key == "owner",
            )
        )
        assert owner is not None
        if db.session.get(MembershipRole, (tenant_id, membership.id, owner.id)) is None:
            db.session.add(
                MembershipRole(tenant_id=tenant_id, membership_id=membership.id, role_id=owner.id)
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
        expires_at = datetime.now(UTC) + timedelta(hours=current_app.config["INVITATION_TTL_HOURS"])
        invitation_id = uuid.uuid4()
        invitation = Invitation(
            id=invitation_id,
            tenant_id=tenant_id,
            membership_id=membership.id,
            token_hash=hash_token(
                stable_invitation_token(
                    invitation_id=invitation_id,
                    secret_key=current_app.config["SECRET_KEY"],
                )
            ),
            expires_at=expires_at,
            invited_by_user_id=actor_id,
        )
        db.session.add(invitation)
        job = stage_job(
            "notifications.send_email",
            payload={"kind": "invitation", "invitation_id": str(invitation.id)},
            idempotency_key=f"invitation-email:{invitation.id}",
            resource_type="invitation",
            resource_id=invitation.id,
        )
        append_audit_event(
            db.session,
            action="tenant.member.invited",
            resource_type="membership",
            resource_id=membership.id,
            result="success",
            metadata={"email_hash": __import__("hashlib").sha256(email.encode()).hexdigest()},
        )
        db.session.commit()
        membership_id = membership.id
        publish_job(job)
    return {"membership_id": str(membership_id)}, 201


@bp.get("/users")
@require_platform_admin
def list_users() -> dict[str, Any]:
    rows = db.session.scalars(select(User).order_by(User.created_at.desc()).limit(200))
    return {
        "items": [
            {
                "id": str(row.id),
                "email": row.email,
                "display_name": row.display_name,
                "status": row.status,
                "platform_role": row.platform_role,
            }
            for row in rows
        ]
    }


@bp.get("/audit")
@require_platform_admin
def platform_audit() -> dict[str, Any]:
    if db.engine.dialect.name == "postgresql":
        global_rows = db.session.execute(
            text("SELECT * FROM oracle_read_global_audit(200)")
        ).mappings()
        return {
            "items": [
                {
                    "id": str(row["id"]),
                    "action": row["action"],
                    "result": row["result"],
                    "created_at": row["created_at"].isoformat(),
                }
                for row in global_rows
            ]
        }
    audit_rows = db.session.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id.is_(None))
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
            for row in audit_rows
        ]
    }
