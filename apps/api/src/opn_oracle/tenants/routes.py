"""Minimal tenant-scoped catalogs for product workflows."""

from __future__ import annotations

from typing import Any

from apiflask import APIBlueprint
from flask import g
from sqlalchemy import func, select

from opn_oracle.auth.permissions import require_permission
from opn_oracle.extensions import db
from opn_oracle.platform.models import TenantMembership, User

bp = APIBlueprint(
    "tenant_catalogs",
    __name__,
    url_prefix="/api/v1",
    tag="Catálogos del tenant",
)


@bp.get("/assignable-users")
@require_permission("report.generate")
def list_assignable_users() -> dict[str, Any]:
    """Return only active identities needed by assignment controls.

    ``report.generate`` keeps this catalog available to every user who can
    submit a report without exposing the administrative membership directory.
    The standard task-author roles also own this permission, so the same
    minimal catalog can be reused by task assignment controls.
    """

    rows = db.session.execute(
        select(User.id, User.display_name)
        .join(TenantMembership, TenantMembership.user_id == User.id)
        .where(
            TenantMembership.tenant_id == g.active_tenant_id,
            TenantMembership.status == "active",
            User.status == "active",
        )
        .order_by(func.lower(User.display_name), User.id)
    ).all()
    return {
        "items": [
            {"id": str(user_id), "display_name": display_name} for user_id, display_name in rows
        ]
    }
