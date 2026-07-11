"""Session-based JSON authentication API."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from apiflask import APIBlueprint
from flask import current_app, g, request, session
from flask_login import (
    confirm_login,
    current_user,
    login_required,
    login_user,
)
from sqlalchemy import select, text, update

from opn_oracle.auth.passwords import PasswordHasher, PasswordPolicy, PasswordPolicyError
from opn_oracle.auth.permissions import current_permissions, recent_auth_required
from opn_oracle.auth.runtime import (
    renew_csrf,
    revoke_current_session,
    rotate_session_id,
    session_hash,
)
from opn_oracle.auth.tokens import hash_token
from opn_oracle.common.errors import problem_response
from opn_oracle.common.request_context import get_correlation_id, get_request_id
from opn_oracle.extensions import db, limiter
from opn_oracle.jobs.service import stage_job
from opn_oracle.platform.audit import append_audit_event, append_global_audit_event
from opn_oracle.platform.models import (
    Invitation,
    MembershipRole,
    PasswordResetToken,
    Role,
    Tenant,
    TenantMembership,
    User,
    UserSession,
)
from opn_oracle.tenants.context import (
    TenantContext,
    actor_context,
    get_tenant_context,
    tenant_context,
)

bp = APIBlueprint("auth", __name__, url_prefix="/api/v1/auth", tag="Autenticación")
DUMMY_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$eWZ4RWtzSllTNE12alV3TQ$"
    "hOB0rfR0BsNQNmF3Qk5xQb2PBGlKIj7JaPNbU6NEl2U"
)


def _json() -> dict[str, Any]:
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


def _hasher() -> PasswordHasher:
    return PasswordHasher(
        PasswordPolicy(
            current_app.config["PASSWORD_MIN_LENGTH"], current_app.config["PASSWORD_MAX_BYTES"]
        )
    )


def _audit(
    action: str,
    result: str,
    *,
    metadata: dict[str, Any] | None = None,
    resource_id: UUID | None = None,
    allow_global: bool = False,
) -> None:
    context = get_tenant_context(required=False)
    if allow_global or context is None or context.tenant_id is None:
        append_global_audit_event(
            db.session,
            action=action,
            resource_type="authentication",
            result=result,
            actor_id=current_user.id if current_user.is_authenticated else None,
            resource_id=resource_id,
            metadata=metadata,
            request_id=get_request_id(),
            correlation_id=get_correlation_id(),
        )
        return
    append_audit_event(
        db.session,
        action=action,
        resource_type="authentication",
        resource_id=resource_id,
        result=result,
        metadata=metadata,
        request_id=get_request_id(),
        correlation_id=get_correlation_id(),
        allow_global=False,
    )


def _membership_choices(user_id: UUID) -> list[dict[str, Any]]:
    if db.engine.dialect.name == "postgresql":
        db.session.rollback()
        with actor_context(user_id):
            pg_rows = (
                db.session.execute(
                    text(
                        "SELECT membership_id, tenant_id, tenant_slug, tenant_name, "
                        "membership_status FROM oracle_actor_memberships(:actor)"
                    ),
                    {"actor": user_id},
                )
                .mappings()
                .all()
            )
            db.session.rollback()
        return sorted(
            (dict(row) for row in pg_rows if row["membership_status"] == "active"),
            key=lambda row: (str(row["tenant_name"]).casefold(), str(row["tenant_id"])),
        )
    sqlite_rows = db.session.execute(
        select(
            TenantMembership.id,
            Tenant.id.label("tenant_id"),
            Tenant.slug.label("tenant_slug"),
            Tenant.name.label("tenant_name"),
            TenantMembership.status.label("membership_status"),
        )
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
            Tenant.status == "active",
        )
    ).mappings()
    return sorted(
        (dict(row) for row in sqlite_rows),
        key=lambda row: (str(row["tenant_name"]).casefold(), str(row["tenant_id"])),
    )


def _create_session(
    user: User, tenant_id: UUID | None, *, upgraded_password_hash: str | None = None
) -> UserSession:
    user_id = user.id
    rotate_session_id()
    session.clear()
    login_user(user, fresh=True, remember=False)
    session["reauthenticated_at"] = time.time()
    renew_csrf()
    now = datetime.now(UTC)
    raw_sid = str(getattr(session, "sid", ""))
    record = UserSession(
        user_id=user_id,
        active_tenant_id=tenant_id,
        session_hash=session_hash(raw_sid),
        created_at=now,
        last_seen_at=now,
        idle_expires_at=now + timedelta(minutes=current_app.config["SESSION_IDLE_MINUTES"]),
        absolute_expires_at=now + timedelta(hours=current_app.config["SESSION_ABSOLUTE_HOURS"]),
        user_agent_summary=(request.user_agent.string or "")[:255] or None,
        ip_address=request.remote_addr,
    )
    # Login and membership resolution run pre-tenant. Start a fresh transaction so
    # PostgreSQL receives the selected tenant/actor before any durable write.
    db.session.rollback()
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=user_id)):
        db.session.add(record)
        _audit("auth.login.success", "success", resource_id=user.id)
        user_values: dict[str, Any] = {"last_login_at": now}
        if upgraded_password_hash is not None:
            user_values["password_hash"] = upgraded_password_hash
        db.session.execute(update(User).where(User.id == user_id).values(**user_values))
        db.session.commit()
    session["user_session_id"] = str(record.id)
    session["active_tenant_id"] = str(tenant_id) if tenant_id else None
    return record


@bp.get("/csrf")
def csrf() -> dict[str, str]:
    return {"csrf_token": renew_csrf()}


@bp.post("/login")
@limiter.limit("10/minute")
def login() -> Any:
    payload = _json()
    email = str(payload.get("email", "")).strip().casefold()[:320]
    password = str(payload.get("password", ""))
    identity_key = "opn-oracle:login:" + hashlib.sha256(email.encode()).hexdigest()
    redis = current_app.extensions["oracle_redis"]
    failures = int(redis.get(identity_key) or 0)
    if failures >= current_app.config["AUTH_MAX_FAILURES"]:
        _audit(
            "auth.login.locked",
            "denied",
            metadata={"identity_hash": hashlib.sha256(email.encode()).hexdigest()},
            allow_global=True,
        )
        db.session.commit()
        response, status, headers = problem_response(
            429, detail="Demasiados intentos. Inténtalo más tarde.", code="login_temporarily_locked"
        )
        return (
            response,
            status,
            {**headers, "Retry-After": str(current_app.config["AUTH_LOCK_SECONDS"])},
        )
    user = db.session.scalar(select(User).where(User.email == email)) if email else None
    valid = _hasher().verify(user.password_hash if user else DUMMY_HASH, password)
    if user is None or not valid or user.status != "active":
        pipe = redis.pipeline()
        pipe.incr(identity_key).expire(
            identity_key, current_app.config["AUTH_LOCK_SECONDS"]
        ).execute()
        _audit(
            "auth.login.failure",
            "failure",
            metadata={"identity_hash": hashlib.sha256(email.encode()).hexdigest()},
            allow_global=True,
        )
        db.session.commit()
        return problem_response(401, detail="Credenciales no válidas.", code="invalid_credentials")[
            :2
        ]
    choices = _membership_choices(user.id)
    if not choices and user.platform_role != "super_admin":
        _audit(
            "auth.login.failure",
            "failure",
            metadata={"identity_hash": hashlib.sha256(email.encode()).hexdigest()},
            allow_global=True,
        )
        db.session.commit()
        return problem_response(401, detail="Credenciales no válidas.", code="invalid_credentials")[
            :2
        ]
    requested = str(payload.get("tenant_id", ""))
    selected = (
        next((row for row in choices if str(row["tenant_id"]) == requested), None)
        if requested
        else (choices[0] if len(choices) == 1 else None)
    )
    if selected is None and choices and user.platform_role != "super_admin":
        return problem_response(
            409,
            detail="Selecciona una organización válida.",
            code="tenant_selection_required",
            errors={
                "memberships": [
                    {
                        "tenant_id": str(row["tenant_id"]),
                        "tenant_slug": row["tenant_slug"],
                        "tenant_name": row["tenant_name"],
                    }
                    for row in choices
                ]
            },
        )[:2]
    redis.delete(identity_key)
    upgraded_password_hash = (
        _hasher().hash(password)
        if user.password_hash and _hasher().needs_rehash(user.password_hash)
        else None
    )
    tenant_id = UUID(str(selected["tenant_id"])) if selected else None
    record = _create_session(user, tenant_id, upgraded_password_hash=upgraded_password_hash)
    return {
        "session_id": str(record.id),
        "requires_tenant_selection": bool(choices and selected is None),
    }


@bp.post("/logout")
@login_required
def logout() -> tuple[str, int]:
    _audit("auth.logout", "success", resource_id=current_user.id)
    db.session.commit()
    revoke_current_session()
    return "", 204


def _memberships_and_permissions() -> tuple[list[dict[str, Any]], frozenset[str]]:
    user_id = current_user.id
    active = getattr(g, "active_tenant_id", None)
    choices = _membership_choices(user_id)
    permissions = current_permissions(user_id, active) if active else frozenset()
    return choices, permissions


@bp.get("/me")
@login_required
def me() -> dict[str, Any]:
    choices, permissions = _memberships_and_permissions()
    active = getattr(g, "active_tenant_id", None)
    roles: list[str] = []
    if active:
        roles = list(
            db.session.scalars(
                select(Role.key)
                .join(MembershipRole, MembershipRole.role_id == Role.id)
                .join(TenantMembership, TenantMembership.id == MembershipRole.membership_id)
                .where(
                    TenantMembership.user_id == current_user.id,
                    TenantMembership.tenant_id == active,
                )
            )
        )
    return {
        "user": {
            "id": str(current_user.id),
            "email": current_user.email,
            "display_name": current_user.display_name,
            "platform_role": current_user.platform_role,
        },
        "active_tenant_id": str(active) if active else None,
        "memberships": [
            {**row, "membership_id": str(row["membership_id"]), "tenant_id": str(row["tenant_id"])}
            for row in choices
        ],
        "roles": sorted(roles),
        "permissions": sorted(permissions),
    }


@bp.post("/reauthenticate")
@login_required
@limiter.limit("5/minute")
def reauthenticate() -> tuple[Any, int] | dict[str, str]:
    if not _hasher().verify(current_user.password_hash, str(_json().get("password", ""))):
        return problem_response(401, detail="Credenciales no válidas.", code="invalid_credentials")[
            :2
        ]
    confirm_login()
    session["reauthenticated_at"] = time.time()
    rotate_session_id()
    renew_csrf()
    record = db.session.get(UserSession, UUID(session["user_session_id"]))
    if record:
        record.session_hash = session_hash(str(getattr(session, "sid", "")))
        db.session.commit()
    return {"status": "fresh"}


@bp.post("/change-password")
@recent_auth_required
def change_password() -> tuple[Any, int] | tuple[str, int]:
    payload = _json()
    hasher = _hasher()
    if not hasher.verify(current_user.password_hash, str(payload.get("current_password", ""))):
        return problem_response(401, detail="Credenciales no válidas.", code="invalid_credentials")[
            :2
        ]
    try:
        current_user.password_hash = hasher.hash(str(payload.get("new_password", "")))
    except PasswordPolicyError as error:
        return problem_response(422, detail=str(error), code="password_policy")[:2]
    current_user.password_changed_at = datetime.now(UTC)
    current_id = UUID(session["user_session_id"])
    if current_app.config["REVOKE_OTHER_SESSIONS_ON_PASSWORD_CHANGE"]:
        db.session.execute(
            update(UserSession)
            .where(
                UserSession.user_id == current_user.id,
                UserSession.id != current_id,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
    _audit("auth.password.changed", "success", resource_id=current_user.id)
    db.session.commit()
    rotate_session_id()
    record = db.session.get(UserSession, current_id)
    if record:
        record.session_hash = session_hash(str(getattr(session, "sid", "")))
        db.session.commit()
    renew_csrf()
    return "", 204


@bp.post("/forgot-password")
@limiter.limit("5/hour")
def forgot_password() -> tuple[str, int]:
    email = str(_json().get("email", "")).strip().casefold()[:320]
    user = db.session.scalar(select(User).where(User.email == email)) if email else None
    if user and user.status == "active":
        tenant_id = db.session.scalar(
            select(TenantMembership.tenant_id)
            .where(TenantMembership.user_id == user.id, TenantMembership.status == "active")
            .order_by(TenantMembership.created_at)
            .limit(1)
        )
        if tenant_id is not None:
            db.session.rollback()
            with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=None)):
                job = stage_job(
                    "notifications.send_email",
                    payload={"kind": "password_reset", "user_id": str(user.id)},
                    idempotency_key=f"password-reset:{user.id}:{get_request_id()}",
                    correlation_id=get_correlation_id(),
                    request_id=get_request_id(),
                )
                append_audit_event(
                    db.session,
                    action="auth.password_reset.queued",
                    resource_type="background_job",
                    resource_id=job.id,
                    result="success",
                    request_id=get_request_id(),
                    correlation_id=get_correlation_id(),
                )
                db.session.commit()
    return "", 204


@bp.post("/reset-password")
@limiter.limit("5/hour")
def reset_password() -> tuple[Any, int] | tuple[str, int]:
    payload = _json()
    token_hash = hash_token(str(payload.get("token", "")))
    reset = db.session.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == token_hash)
        .with_for_update()
    )
    now = datetime.now(UTC)
    if reset is None or reset.used_at or reset.revoked_at or reset.expires_at <= now:
        return problem_response(
            400, detail="El enlace no es válido o ha caducado.", code="invalid_reset_token"
        )[:2]
    user = db.session.get(User, reset.user_id)
    if user is None or user.status != "active":
        return problem_response(
            400, detail="El enlace no es válido o ha caducado.", code="invalid_reset_token"
        )[:2]
    try:
        user.password_hash = _hasher().hash(str(payload.get("new_password", "")))
    except PasswordPolicyError as error:
        return problem_response(422, detail=str(error), code="password_policy")[:2]
    reset.used_at = now
    user.password_changed_at = now
    db.session.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    _audit("auth.password_reset.used", "success", resource_id=user.id, allow_global=True)
    db.session.commit()
    return "", 204


@bp.post("/accept-invitation")
@limiter.limit("10/hour")
def accept_invitation() -> tuple[Any, int] | tuple[str, int]:
    payload = _json()
    digest = hash_token(str(payload.get("token", "")))
    resolved: Mapping[str, Any] | None
    if db.engine.dialect.name == "postgresql":
        resolved = cast(
            Mapping[str, Any] | None,
            (
                db.session.execute(
                    text("SELECT * FROM oracle_resolve_invitation(:token_hash)"),
                    {"token_hash": digest},
                )
                .mappings()
                .first()
            ),
        )
    else:
        invite = db.session.scalar(
            select(Invitation).where(
                Invitation.token_hash == digest,
                Invitation.used_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > datetime.now(UTC),
            )
        )
        resolved = (
            {
                "invitation_id": invite.id,
                "tenant_id": invite.tenant_id,
                "membership_id": invite.membership_id,
            }
            if invite
            else None
        )
    if resolved is None:
        return problem_response(
            400, detail="La invitación no es válida o ha caducado.", code="invalid_invitation"
        )[:2]
    tenant_id, membership_id = (
        UUID(str(resolved["tenant_id"])),
        UUID(str(resolved["membership_id"])),
    )
    db.session.rollback()
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=None)):
        invitation = db.session.scalar(
            select(Invitation)
            .where(Invitation.id == UUID(str(resolved["invitation_id"])))
            .with_for_update()
        )
        membership = db.session.scalar(
            select(TenantMembership).where(TenantMembership.id == membership_id).with_for_update()
        )
        now = datetime.now(UTC)
        if (
            invitation is None
            or membership is None
            or invitation.used_at is not None
            or invitation.revoked_at is not None
            or invitation.expires_at <= now
            or membership.status != "invited"
        ):
            return problem_response(
                400,
                detail="La invitación no es válida o ha caducado.",
                code="invalid_invitation",
            )[:2]
        user = db.session.get(User, membership.user_id)
        if user is None or user.status in {"disabled", "locked"}:
            return problem_response(
                400,
                detail="La invitación no es válida o ha caducado.",
                code="invalid_invitation",
            )[:2]
        if user.password_hash is None:
            try:
                user.password_hash = _hasher().hash(str(payload.get("new_password", "")))
            except PasswordPolicyError as error:
                return problem_response(422, detail=str(error), code="password_policy")[:2]
            user.password_changed_at = now
        user.status = "active"
        user.email_verified_at = user.email_verified_at or now
        membership.status = "active"
        membership.accepted_at = now
        invitation.used_at = now
        append_audit_event(
            db.session,
            action="tenant.invitation.used",
            resource_type="membership",
            resource_id=membership.id,
            result="success",
            metadata={},
        )
        db.session.commit()
    return "", 204


@bp.get("/sessions")
@login_required
def sessions_list() -> dict[str, Any]:
    rows = db.session.scalars(
        select(UserSession)
        .where(UserSession.user_id == current_user.id)
        .order_by(UserSession.created_at.desc())
    )
    current_id = session.get("user_session_id")
    return {
        "items": [
            {
                "id": str(row.id),
                "current": str(row.id) == current_id,
                "active_tenant_id": str(row.active_tenant_id) if row.active_tenant_id else None,
                "created_at": row.created_at.isoformat(),
                "last_seen_at": row.last_seen_at.isoformat(),
                "expires_at": row.absolute_expires_at.isoformat(),
                "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
                "user_agent": row.user_agent_summary,
            }
            for row in rows
        ]
    }


@bp.delete("/sessions/<uuid:session_id>")
@recent_auth_required
def revoke_session(session_id: UUID) -> tuple[Any, int] | tuple[str, int]:
    record = db.session.scalar(
        select(UserSession).where(
            UserSession.id == session_id, UserSession.user_id == current_user.id
        )
    )
    if record is None:
        return problem_response(404, detail="Sesión no encontrada.", code="not_found")[:2]
    if str(record.id) == session.get("user_session_id"):
        revoke_current_session()
    else:
        record.revoked_at = datetime.now(UTC)
        _audit("auth.session.revoked", "success", resource_id=record.id)
        db.session.commit()
    return "", 204


@bp.post("/sessions/revoke-others")
@recent_auth_required
def revoke_others() -> tuple[str, int]:
    current_id = UUID(session["user_session_id"])
    db.session.execute(
        update(UserSession)
        .where(
            UserSession.user_id == current_user.id,
            UserSession.id != current_id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    _audit("auth.sessions.others_revoked", "success", resource_id=current_user.id)
    db.session.commit()
    return "", 204


@bp.post("/switch-tenant")
@login_required
def switch_tenant() -> tuple[Any, int] | dict[str, str]:
    actor_id = current_user.id
    session_record_id = UUID(session["user_session_id"])
    try:
        target = UUID(str(_json().get("tenant_id", "")))
    except ValueError:
        return problem_response(422, detail="Tenant no válido.", code="validation_error")[:2]
    choices = _membership_choices(actor_id)
    if not any(UUID(str(row["tenant_id"])) == target for row in choices):
        return problem_response(
            403, detail="No tienes acceso a ese tenant.", code="permission_denied"
        )[:2]
    db.session.rollback()
    with tenant_context(TenantContext(tenant_id=target, actor_id=actor_id)):
        record = db.session.get(UserSession, session_record_id)
        assert record is not None
        record.active_tenant_id = target
        _audit("auth.session.tenant_switched", "success", resource_id=target)
        db.session.commit()
    session["active_tenant_id"] = str(target)
    rotate_session_id()
    renew_csrf()
    with tenant_context(TenantContext(tenant_id=target, actor_id=actor_id)):
        record = db.session.get(UserSession, session_record_id)
        assert record is not None
        record.session_hash = session_hash(str(getattr(session, "sid", "")))
        db.session.commit()
    return {"active_tenant_id": str(target)}
