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

from opn_oracle.ai.policy_defaults import default_ai_policy
from opn_oracle.auth.permissions import recent_auth_required, require_platform_admin
from opn_oracle.auth.tokens import hash_token, stable_invitation_token
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db
from opn_oracle.jobs.service import publish_job, stage_job
from opn_oracle.platform.audit import append_audit_event, append_global_audit_event
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
        db.session.add(default_ai_policy(tenant.id, current_app.config))
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


def _parse_day(value: str | None) -> Any:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


@bp.get("/source-activity")
@require_platform_admin
def platform_source_activity() -> Any:
    """Daily official gazette activity (BORME/BOE) for platform operators."""

    from opn_oracle.platform.source_activity import list_source_activity, serialize_activity

    source = (request.args.get("source") or "").strip().lower() or None
    search = (request.args.get("q") or "").strip() or None
    sort = (request.args.get("sort") or "activity_date").strip()
    direction = (request.args.get("direction") or "desc").strip().lower()
    if direction not in {"asc", "desc"}:
        direction = "desc"
    date_from = _parse_day(request.args.get("from"))
    date_to = _parse_day(request.args.get("to"))
    if request.args.get("from") and date_from is None:
        return problem_response(
            422, detail="from debe ser una fecha YYYY-MM-DD.", code="invalid_from"
        )[:2]
    if request.args.get("to") and date_to is None:
        return problem_response(422, detail="to debe ser una fecha YYYY-MM-DD.", code="invalid_to")[
            :2
        ]

    rows = list_source_activity(
        db.session,
        source=source,
        search=search,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        direction=direction,
    )
    published = sum(1 for row in rows if row.status == "published")
    items_total = sum(int(row.item_count) for row in rows if row.status == "published")
    return {
        "items": [serialize_activity(row) for row in rows],
        "meta": {
            "total": len(rows),
            "published_days": published,
            "item_count_sum": items_total,
            "sources": ["borme", "boe"],
        },
    }


@bp.get("/procurement-analytics")
@require_platform_admin
def platform_procurement_analytics() -> Any:
    """Ranked PLACSP market snapshot for platform operators (open tenders sample)."""

    from opn_oracle.integrations.procurement import (
        ProcurementConfigurationError,
        ProcurementProviderError,
    )
    from opn_oracle.platform.procurement_analytics import build_procurement_analytics

    def _int_arg(name: str, default: int, *, minimum: int, maximum: int) -> int | Any:
        raw = request.args.get(name)
        if raw is None or raw == "":
            return default
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return problem_response(
                422,
                detail=f"{name} debe ser un entero.",
                code=f"invalid_{name}",
            )[:2]
        return max(minimum, min(maximum, value))

    sample_size = _int_arg("sample_size", 300, minimum=50, maximum=10_000)
    if not isinstance(sample_size, int):
        return sample_size
    top_n = _int_arg("top_n", 25, minimum=5, maximum=100)
    if not isinstance(top_n, int):
        return top_n
    sort_by = (request.args.get("sort") or "count").strip()
    if sort_by not in {"count", "amount_sum"}:
        sort_by = "count"
    direction = (request.args.get("direction") or "desc").strip().lower()
    if direction not in {"asc", "desc"}:
        direction = "desc"
    scope = (request.args.get("scope") or "active").strip().lower()
    if scope not in {"active", "all"}:
        scope = "active"
    try:
        return build_procurement_analytics(
            sample_size=sample_size,
            top_n=top_n,
            sort_by=sort_by,
            direction=direction,
            scope=scope,
        )
    except ProcurementConfigurationError as exc:
        return problem_response(
            503,
            detail=str(exc),
            code="procurement_not_configured",
        )[:2]
    except ProcurementProviderError as exc:
        return problem_response(
            exc.status_code if 400 <= exc.status_code < 600 else 502,
            detail=exc.detail,
            code=exc.code,
        )[:2]


@bp.post("/source-activity/refresh")
@require_platform_admin
def platform_source_activity_refresh() -> Any:
    """Manually re-check recent BORME/BOE sumarios and persist the activity log."""

    from opn_oracle.platform.source_activity import poll_source_activity, serialize_activity

    payload = _payload()
    lookback = payload.get("lookback_days", 14)
    try:
        lookback_days = int(lookback)
    except (TypeError, ValueError):
        return problem_response(
            422, detail="lookback_days debe ser un entero.", code="invalid_lookback"
        )[:2]
    lookback_days = max(1, min(lookback_days, 60))
    rows = poll_source_activity(db.session, lookback_days=lookback_days)
    append_global_audit_event(
        db.session,
        action="platform.source_activity.refreshed",
        resource_type="platform_source_activity",
        result="success",
        actor_id=current_user.id if current_user.is_authenticated else None,
        metadata={"lookback_days": lookback_days, "rows": len(rows)},
    )
    db.session.commit()
    return {
        "refreshed": len(rows),
        "items": [serialize_activity(row) for row in rows[:50]],
    }
