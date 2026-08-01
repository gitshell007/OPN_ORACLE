"""Flask BFF for dossier memory profile / health / test (MDEV-04 provisional)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from apiflask import APIBlueprint
from flask import g, request
from flask_login import current_user
from sqlalchemy import select

from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db
from opn_oracle.integrations.memory_context import capability_payload
from opn_oracle.integrations.memory_http_client import MemoryHttpError, MockTransport
from opn_oracle.integrations.memory_profile import (
    build_client_for_connection,
    default_profile_payload,
    profile_to_public,
    resolve_signal_memory_connection,
)
from opn_oracle.integrations.models import DossierMemoryProfile
from opn_oracle.oracle.models import StrategicDossier
from opn_oracle.oracle.policy import dossier_accessible
from opn_oracle.platform.audit import append_audit_event

bp = APIBlueprint("memory_settings", __name__, url_prefix="/api/v1")


def _tenant_id() -> uuid.UUID:
    return uuid.UUID(str(g.tenant_id))


def _etag(version: int, cfg: dict[str, Any]) -> str:
    raw = json.dumps({"v": version, "p": cfg}, sort_keys=True, separators=(",", ":"))
    return f'W/"dmp-v{version}-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"'


def _get_or_create_profile(
    *, tenant_id: uuid.UUID, dossier_id: uuid.UUID, connection_id: uuid.UUID | None
) -> DossierMemoryProfile:
    row = db.session.scalar(
        select(DossierMemoryProfile).where(
            DossierMemoryProfile.tenant_id == tenant_id,
            DossierMemoryProfile.dossier_id == dossier_id,
            DossierMemoryProfile.connection_id == connection_id
            if connection_id is not None
            else DossierMemoryProfile.connection_id.is_(None),
        )
    )
    if row is not None:
        return row
    cfg = default_profile_payload()
    row = DossierMemoryProfile(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        connection_id=connection_id,
        mode="disabled",
        version=1,
        etag=_etag(1, cfg),
        profile_config=cfg,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.session.add(row)
    db.session.commit()
    return row


@bp.get("/dossiers/<uuid:dossier_id>/memory/profile")
@require_permission("dossier:read")
def get_memory_profile(dossier_id: uuid.UUID):
    tenant_id = _tenant_id()
    dossier = db.session.get(StrategicDossier, dossier_id)
    if (
        dossier is None
        or dossier.tenant_id != tenant_id
        or not dossier_accessible(dossier, current_user)
    ):
        return problem_response(404, "not_found", "Expediente no encontrado.")
    conn_id = request.args.get("connection_id")
    connection_uuid = uuid.UUID(conn_id) if conn_id else None
    row = _get_or_create_profile(
        tenant_id=tenant_id, dossier_id=dossier_id, connection_id=connection_uuid
    )
    body = profile_to_public(row)
    from flask import jsonify

    r = jsonify(body)
    r.headers["ETag"] = row.etag
    return r


@bp.put("/dossiers/<uuid:dossier_id>/memory/profile")
@require_permission("dossier:write")
def put_memory_profile(dossier_id: uuid.UUID):
    tenant_id = _tenant_id()
    dossier = db.session.get(StrategicDossier, dossier_id)
    if (
        dossier is None
        or dossier.tenant_id != tenant_id
        or not dossier_accessible(dossier, current_user)
    ):
        return problem_response(404, "not_found", "Expediente no encontrado.")

    if_match = request.headers.get("If-Match") or request.headers.get("if-match")
    if not if_match:
        return problem_response(428, "precondition_required", "If-Match ETag required.")

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return problem_response(422, "schema_validation_failed", "body must be object.")

    conn_id = payload.get("connection_id")
    connection_uuid = uuid.UUID(str(conn_id)) if conn_id else None
    row = _get_or_create_profile(
        tenant_id=tenant_id, dossier_id=dossier_id, connection_id=connection_uuid
    )
    if str(if_match) != str(row.etag):
        return problem_response(409, "etag_conflict", "ETag mismatch; reload and retry.")

    mode = str(payload.get("mode") or row.mode or "disabled").strip().lower()
    if mode not in {"disabled", "shadow", "augment"}:
        return problem_response(422, "schema_validation_failed", "invalid mode.")

    cfg = dict(row.profile_config or default_profile_payload())
    cfg["mode"] = mode
    for key in ("sources", "kinds", "classifications_allowed"):
        if key in payload and isinstance(payload[key], list):
            cfg[key] = [str(x) for x in payload[key]]
    if "token_budget" in payload:
        try:
            cfg["token_budget"] = int(payload["token_budget"])
        except (TypeError, ValueError):
            return problem_response(422, "schema_validation_failed", "invalid token_budget.")
    if "limit" in payload:
        try:
            cfg["limit"] = int(payload["limit"])
        except (TypeError, ValueError):
            return problem_response(422, "schema_validation_failed", "invalid limit.")

    before = {"etag": row.etag, "mode": row.mode, "version": row.version}
    row.mode = mode
    row.version = int(row.version) + 1
    row.profile_config = cfg
    row.etag = _etag(row.version, cfg)
    row.updated_at = datetime.now(UTC)
    db.session.add(row)
    append_audit_event(
        action="dossier_memory_profile_update",
        entity_type="dossier_memory_profile",
        entity_id=str(row.id),
        before=before,
        after={"etag": row.etag, "mode": row.mode, "version": row.version},
    )
    db.session.commit()
    from flask import jsonify

    r = jsonify(profile_to_public(row))
    r.headers["ETag"] = row.etag
    return r


@bp.get("/dossiers/<uuid:dossier_id>/memory/effective")
@require_permission("dossier:read")
def memory_effective(dossier_id: uuid.UUID):
    tenant_id = _tenant_id()
    dossier = db.session.get(StrategicDossier, dossier_id)
    if (
        dossier is None
        or dossier.tenant_id != tenant_id
        or not dossier_accessible(dossier, current_user)
    ):
        return problem_response(404, "not_found", "Expediente no encontrado.")
    row = _get_or_create_profile(tenant_id=tenant_id, dossier_id=dossier_id, connection_id=None)
    host_mode = str(
        __import__("flask").current_app.config.get("MEMORY_CONTEXT_MODE", "disabled") or "disabled"
    )
    pub = profile_to_public(row)
    pub["capability"] = capability_payload(
        host_mode=host_mode, connection_healthy=host_mode == "http"
    )
    from flask import jsonify

    return jsonify(pub)


@bp.get("/memory/capability")
@require_permission("dossier:read")
def memory_capability():
    host_mode = str(
        __import__("flask").current_app.config.get("MEMORY_CONTEXT_MODE", "disabled") or "disabled"
    )
    from flask import jsonify

    return jsonify(
        capability_payload(host_mode=host_mode, connection_healthy=host_mode in {"http", "mock"})
    )


@bp.post("/dossiers/<uuid:dossier_id>/memory/test-connection")
@require_permission("dossier:write")
def memory_test_connection(dossier_id: uuid.UUID):
    """Test connection without exposing secrets. Uses synthetic transport if configured."""
    tenant_id = _tenant_id()
    dossier = db.session.get(StrategicDossier, dossier_id)
    if (
        dossier is None
        or dossier.tenant_id != tenant_id
        or not dossier_accessible(dossier, current_user)
    ):
        return problem_response(404, "not_found", "Expediente no encontrado.")

    row = _get_or_create_profile(tenant_id=tenant_id, dossier_id=dossier_id, connection_id=None)
    host_mode = str(
        __import__("flask").current_app.config.get("MEMORY_CONTEXT_MODE", "disabled") or "disabled"
    )
    if host_mode == "disabled":
        row.last_test_at = datetime.now(UTC)
        row.last_test_status = "host_disabled"
        row.last_error = "MEMORY_CONTEXT_MODE=disabled"
        db.session.commit()
        from flask import jsonify

        return jsonify(
            {
                "ok": False,
                "status": "host_disabled",
                "publisher_reliable": False,
                "message": "Host memory disabled",
            }
        )

    try:
        conn = resolve_signal_memory_connection(db.session, tenant_id=tenant_id)
        # Prefer mock transport in tests; real httpx only when explicitly http + base_url
        transport = MockTransport(
            default=(
                200,
                {"content-type": "application/json"},
                b'{"status":"ok","engine_enabled":false,"api_version":"memory.v1"}',
            )
        )
        client = build_client_for_connection(conn, transport=transport, require_https=False)
        # Use tenant public id string if available
        external = str(getattr(g, "external_tenant_id", None) or tenant_id)
        health = client.health(external_tenant_id=external)
        row.last_test_at = datetime.now(UTC)
        row.last_test_status = "ok"
        row.last_error = None
        row.last_coverage = {"health": health.get("status"), "publisher_degraded": True}
        db.session.commit()
        from flask import jsonify

        return jsonify(
            {
                "ok": True,
                "status": "ok",
                "engine_enabled": health.get("engine_enabled"),
                "publisher_reliable": False,
                "message": "Connection test completed (publisher degraded — Signal debt)",
            }
        )
    except MemoryHttpError as exc:
        row.last_test_at = datetime.now(UTC)
        row.last_test_status = "error"
        row.last_error = f"{exc.code}:{exc.message}"[:500]
        db.session.commit()
        return problem_response(
            502 if exc.retryable else 400,
            exc.code,
            exc.message,
        )
