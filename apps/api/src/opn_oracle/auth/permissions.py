"""Authoritative backend permission checks."""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast
from uuid import UUID

from flask import current_app, g, session
from flask_login import current_user
from sqlalchemy import select

from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db
from opn_oracle.platform.models import MembershipRole, RolePermission, TenantMembership

P = ParamSpec("P")
R = TypeVar("R")


def current_permissions(user_id: UUID, tenant_id: UUID) -> frozenset[str]:
    values = db.session.scalars(
        select(RolePermission.permission_key)
        .join(MembershipRole, MembershipRole.role_id == RolePermission.role_id)
        .join(TenantMembership, TenantMembership.id == MembershipRole.membership_id)
        .where(
            TenantMembership.user_id == user_id,
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.status == "active",
        )
    )
    return frozenset(values)


def require_permission(permission: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> Any:
            if not current_user.is_authenticated:
                return problem_response(
                    401, detail="Debes iniciar sesión.", code="authentication_required"
                )
            tenant_id = getattr(g, "active_tenant_id", None)
            if tenant_id is None or permission not in current_permissions(
                current_user.id, tenant_id
            ):
                return problem_response(
                    403, detail="No tienes permiso para esta acción.", code="permission_denied"
                )
            return function(*args, **kwargs)

        return cast(Callable[P, R], wrapped)

    return decorator


def require_platform_admin(function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> Any:
        if not current_user.is_authenticated:
            return problem_response(
                401, detail="Debes iniciar sesión.", code="authentication_required"
            )
        if current_user.platform_role != "super_admin":
            return problem_response(
                403, detail="Acceso reservado a plataforma.", code="permission_denied"
            )
        return function(*args, **kwargs)

    return cast(Callable[P, R], wrapped)


def recent_auth_required(function: Callable[P, R]) -> Callable[P, R]:
    """Require password confirmation within the sensitive-action TTL."""

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> Any:
        if not current_user.is_authenticated:
            return problem_response(
                401, detail="Debes iniciar sesión.", code="authentication_required"
            )
        confirmed_at = float(session.get("reauthenticated_at", 0.0))
        ttl = current_app.config["SENSITIVE_REAUTH_MINUTES"] * 60
        if confirmed_at <= 0 or time.time() - confirmed_at > ttl:
            return problem_response(
                401,
                detail="Vuelve a introducir tu contraseña para continuar.",
                code="recent_auth_required",
            )
        return function(*args, **kwargs)

    return cast(Callable[P, R], wrapped)
