"""CSRF, durable session validation and tenant request context."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from flask import Flask, Response, g, request, session
from flask.typing import ResponseReturnValue
from flask_login import current_user, logout_user

from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db, login_manager
from opn_oracle.platform.models import Tenant, TenantMembership, User, UserSession
from opn_oracle.tenants.context import TenantContext, tenant_context

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def session_hash(session_id: str) -> bytes:
    return hashlib.sha256(session_id.encode("utf-8")).digest()


def rotate_session_id() -> None:
    interface = __import__("flask").current_app.session_interface
    regenerate = getattr(interface, "regenerate", None)
    if regenerate is None:
        raise RuntimeError("El backend de sesión no soporta rotación segura de session ID.")
    before = str(getattr(session, "sid", ""))
    if not before or not session:
        raise RuntimeError("No se puede rotar una sesión vacía o sin identificador opaco.")
    regenerate(session)
    after = str(getattr(session, "sid", ""))
    if not after or hmac.compare_digest(before, after):
        raise RuntimeError("El backend de sesión no rotó el session ID; operación cancelada.")


def renew_csrf() -> str:
    token = secrets.token_urlsafe(32)
    session["csrf_token"] = token
    return token


def revoke_current_session() -> None:
    record_id = session.get("user_session_id")
    if record_id:
        record = db.session.get(UserSession, UUID(record_id))
        if record is not None and record.revoked_at is None:
            record.revoked_at = datetime.now(UTC)
            db.session.commit()
    logout_user()
    session.clear()


def init_auth_runtime(app: Flask) -> None:
    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        try:
            return db.session.get(User, UUID(user_id))
        except ValueError:
            return None

    @login_manager.unauthorized_handler
    def unauthorized() -> tuple[Response, int, object]:
        return problem_response(401, detail="Debes iniciar sesión.", code="authentication_required")

    @login_manager.needs_refresh_handler
    def needs_refresh() -> tuple[Response, int, object]:
        return problem_response(
            401,
            detail="Vuelve a introducir tu contraseña para continuar.",
            code="fresh_login_required",
        )

    @app.before_request
    def protect_csrf_and_install_identity() -> ResponseReturnValue | None:
        csrf_exempt = request.endpoint == "signal_webhooks.webhook"
        if request.url_rule is not None and request.method in MUTATING_METHODS and not csrf_exempt:
            expected = session.get("csrf_token", "")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not expected or not supplied or not hmac.compare_digest(expected, supplied):
                return problem_response(
                    403, detail="Token CSRF ausente o no válido.", code="csrf_failed"
                )
            origin = request.headers.get("Origin")
            if origin and origin.rstrip("/") != app.config["FRONTEND_ORIGIN"].rstrip("/"):
                return problem_response(
                    403, detail="Origen de la solicitud no válido.", code="csrf_origin_failed"
                )

        if not current_user.is_authenticated:
            return None
        now = datetime.now(UTC)
        user_id = current_user.id
        user_status = current_user.status
        record_id = session.get("user_session_id")
        raw_sid = str(getattr(session, "sid", ""))
        record = None
        if record_id:
            try:
                record = db.session.get(UserSession, UUID(record_id))
            except ValueError:
                record = None
        if (
            record is None
            or record.revoked_at is not None
            or record.user_id != user_id
            or not hmac.compare_digest(record.session_hash, session_hash(raw_sid))
            or now >= record.idle_expires_at
            or now >= record.absolute_expires_at
            or user_status != "active"
        ):
            logout_user()
            session.clear()
            return problem_response(
                401, detail="La sesión ha caducado o fue revocada.", code="session_expired"
            )

        tenant_id = record.active_tenant_id
        db.session.rollback()
        context_manager = tenant_context(TenantContext(tenant_id=tenant_id, actor_id=user_id))
        context_manager.__enter__()
        g.auth_tenant_context_manager = context_manager
        record = db.session.get(UserSession, UUID(record_id))
        assert record is not None
        if tenant_id is not None:
            tenant = db.session.get(Tenant, tenant_id)
            membership = db.session.scalar(
                __import__("sqlalchemy")
                .select(TenantMembership)
                .where(
                    TenantMembership.tenant_id == tenant_id,
                    TenantMembership.user_id == user_id,
                    TenantMembership.status == "active",
                )
            )
            if tenant is None or tenant.status != "active" or membership is None:
                revoke_current_session()
                return problem_response(
                    401, detail="El acceso al tenant ya no está disponible.", code="session_expired"
                )
        record.last_seen_at = now
        record.idle_expires_at = min(
            now + timedelta(minutes=app.config["SESSION_IDLE_MINUTES"]),
            record.absolute_expires_at,
        )
        db.session.commit()
        g.active_tenant_id = tenant_id
        return None

    @app.teardown_request
    def remove_identity_context(error: BaseException | None) -> None:
        manager = getattr(g, "auth_tenant_context_manager", None)
        if manager is not None:
            manager.__exit__(
                type(error) if error else None, error, error.__traceback__ if error else None
            )
