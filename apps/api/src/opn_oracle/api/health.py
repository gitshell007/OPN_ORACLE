"""Liveness and readiness endpoints."""

from __future__ import annotations

from typing import Any, Protocol

from apiflask import APIBlueprint
from flask import current_app
from sqlalchemy import text

from opn_oracle.common.responses import HealthSchema
from opn_oracle.extensions import db

bp = APIBlueprint("health", __name__, tag="Health")
READINESS_RESPONSES: dict[int | str, dict[str, str | dict[str, dict[str, Any]]]] = {
    503: {
        "description": "Una dependencia crítica no está disponible",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Health"}}},
    }
}


class DependencyProbe(Protocol):
    def __call__(self) -> None: ...


def probe_database() -> None:
    timeout_ms = max(1, round(current_app.config["DEPENDENCY_TIMEOUT_SECONDS"] * 1000))
    try:
        db.session.execute(
            text("SELECT set_config('statement_timeout', :timeout, true)"),
            {"timeout": f"{timeout_ms}ms"},
        )
        db.session.execute(text("SELECT 1"))
    except Exception:
        db.session.rollback()
        raise


def probe_redis() -> None:
    client: Any = current_app.extensions["oracle_redis"]
    client.ping()


def _probes() -> dict[str, DependencyProbe]:
    configured = current_app.extensions.get("readiness_probes")
    if configured is not None:
        return dict(configured)
    return {"database": probe_database, "redis": probe_redis}


@bp.get("/health/live")
@bp.output(HealthSchema)
def live() -> dict[str, str]:
    """Report process liveness without calling dependencies."""

    return {"status": "ok"}


@bp.get("/health/ready")
@bp.doc(responses=READINESS_RESPONSES)
@bp.output(HealthSchema)
def ready() -> tuple[dict[str, Any], int] | dict[str, Any]:
    """Report whether PostgreSQL and Redis accept short probes."""

    dependencies: dict[str, dict[str, str]] = {}
    healthy = True
    for name, probe in _probes().items():
        try:
            probe()
            dependencies[name] = {"status": "ok"}
        except Exception:  # dependency details must never escape the endpoint
            healthy = False
            dependencies[name] = {"status": "unavailable"}
            current_app.logger.warning("readiness_dependency_unavailable: %s", name)
    payload = {"status": "ok" if healthy else "unavailable", "dependencies": dependencies}
    return payload if healthy else (payload, 503)
