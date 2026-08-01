"""Flask BFF for dossier memory profile / health / test (MDEV-04 REWORK-2)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from apiflask import APIBlueprint
from flask import current_app, g, jsonify, request
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.orm import Session

from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db
from opn_oracle.integrations.memory_context import capability_payload
from opn_oracle.integrations.memory_http_client import (
    ALLOWED_CLASSIFICATIONS,
    ALLOWED_KINDS,
    ALLOWED_SOURCES,
    HttpxTransport,
    MemoryHttpError,
    MockTransport,
)
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
from opn_oracle.platform.models import IntegrationConnection

bp = APIBlueprint("memory_settings", __name__, url_prefix="/api/v1")


def _session() -> Session:
    # Flask-SQLAlchemy scoped_session is Session-compatible at runtime.
    return db.session()


def _tenant_id() -> uuid.UUID:
    return uuid.UUID(str(g.active_tenant_id))


def _etag(version: int, cfg: dict[str, Any]) -> str:
    raw = json.dumps({"v": version, "p": cfg}, sort_keys=True, separators=(",", ":"))
    return f'W/"dmp-v{version}-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"'


def _validate_connection_for_tenant(
    session: Session, tenant_id: uuid.UUID, connection_id: uuid.UUID | None
) -> IntegrationConnection | None:
    if connection_id is None:
        return None
    conn = session.get(IntegrationConnection, connection_id)
    if (
        conn is None
        or conn.tenant_id != tenant_id
        or conn.provider != "signal-avanza"
        or conn.status != "active"
    ):
        return None
    return conn


def _load_profile(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    connection_id: uuid.UUID | None,
) -> DossierMemoryProfile | None:
    q = select(DossierMemoryProfile).where(
        DossierMemoryProfile.tenant_id == tenant_id,
        DossierMemoryProfile.dossier_id == dossier_id,
    )
    if connection_id is None:
        q = q.where(DossierMemoryProfile.connection_id.is_(None))
    else:
        q = q.where(DossierMemoryProfile.connection_id == connection_id)
    return session.scalar(q)


def _effective_defaults(
    *, tenant_id: uuid.UUID, dossier_id: uuid.UUID, connection_id: uuid.UUID | None
) -> dict[str, Any]:
    cfg = default_profile_payload()
    return {
        "id": None,
        "tenant_id": str(tenant_id),
        "dossier_id": str(dossier_id),
        "connection_id": str(connection_id) if connection_id else None,
        "mode": "disabled",
        "mode_label_es": "Desactivada",
        "version": 0,
        "etag": _etag(0, cfg),
        "sources": cfg["sources"],
        "kinds": cfg["kinds"],
        "classifications_allowed": cfg["classifications_allowed"],
        "token_budget": cfg["token_budget"],
        "limit": cfg["limit"],
        "status": "ephemeral_default",
        "provenance": "effective_default_not_persisted",
        "last_test_at": None,
        "last_test_status": None,
        "last_error": None,
        "last_coverage": None,
        "updated_at": None,
        "persisted": False,
        "publisher_reliable": False,
        "actions_reliable": False,
        "deferred_blockers": ["RACE-MDEV02-003", "DB-MDEV02-001", "SEC-MDEV03-001"],
    }


def _load_accessible_dossier(
    session: Session, dossier_id: uuid.UUID, *, write: bool
) -> StrategicDossier | None:
    tenant_id = _tenant_id()
    dossier = session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == tenant_id,
        )
    )
    if dossier is None or not dossier_accessible(session, dossier, current_user.id, write=write):
        return None
    return dossier


@bp.get("/dossiers/<uuid:dossier_id>/memory/profile")
@require_permission("dossier.read")
def get_memory_profile(dossier_id: uuid.UUID) -> Any:
    """Read profile. Does NOT create/commit rows (no GET side effects)."""
    session = _session()
    dossier = _load_accessible_dossier(session, dossier_id, write=False)
    if dossier is None:
        return problem_response(404, detail="Expediente no encontrado.", code="dossier_not_found")
    tenant_id = dossier.tenant_id
    conn_id = request.args.get("connection_id")
    connection_uuid = uuid.UUID(conn_id) if conn_id else None
    if (
        connection_uuid is not None
        and _validate_connection_for_tenant(session, tenant_id, connection_uuid) is None
    ):
        return problem_response(404, detail="Conexión no encontrada.", code="connection_not_found")
    row = _load_profile(
        session, tenant_id=tenant_id, dossier_id=dossier_id, connection_id=connection_uuid
    )
    if row is None:
        body = _effective_defaults(
            tenant_id=tenant_id, dossier_id=dossier_id, connection_id=connection_uuid
        )
        r = jsonify(body)
        r.headers["ETag"] = body["etag"]
        return r
    body = profile_to_public(row)
    body["persisted"] = True
    r = jsonify(body)
    r.headers["ETag"] = row.etag
    return r


@bp.put("/dossiers/<uuid:dossier_id>/memory/profile")
@require_permission("dossier.write")
def put_memory_profile(dossier_id: uuid.UUID) -> Any:
    session = _session()
    dossier = _load_accessible_dossier(session, dossier_id, write=True)
    if dossier is None:
        return problem_response(404, detail="Expediente no encontrado.", code="dossier_not_found")
    tenant_id = dossier.tenant_id

    if_match = request.headers.get("If-Match") or request.headers.get("if-match")
    if not if_match:
        return problem_response(428, detail="If-Match ETag required.", code="precondition_required")

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return problem_response(422, detail="body must be object.", code="schema_validation_failed")

    conn_id = payload.get("connection_id")
    connection_uuid = uuid.UUID(str(conn_id)) if conn_id else None
    if (
        connection_uuid is not None
        and _validate_connection_for_tenant(session, tenant_id, connection_uuid) is None
    ):
        return problem_response(404, detail="Conexión no encontrada.", code="connection_not_found")

    row = _load_profile(
        session, tenant_id=tenant_id, dossier_id=dossier_id, connection_id=connection_uuid
    )
    ephemeral = _effective_defaults(
        tenant_id=tenant_id, dossier_id=dossier_id, connection_id=connection_uuid
    )
    current_etag = row.etag if row is not None else ephemeral["etag"]
    if str(if_match) != str(current_etag):
        return problem_response(
            409, detail="ETag mismatch; reload and retry.", code="etag_conflict"
        )

    mode = str(payload.get("mode") or (row.mode if row else "disabled")).strip().lower()
    if mode not in {"disabled", "shadow", "augment"}:
        return problem_response(422, detail="invalid mode.", code="schema_validation_failed")

    cfg = dict((row.profile_config if row else None) or default_profile_payload())
    cfg["mode"] = mode
    for key, allowed in (
        ("sources", ALLOWED_SOURCES),
        ("kinds", ALLOWED_KINDS),
        ("classifications_allowed", ALLOWED_CLASSIFICATIONS),
    ):
        if key in payload:
            if not isinstance(payload[key], list):
                return problem_response(
                    422, detail=f"{key} must be list.", code="schema_validation_failed"
                )
            cleaned: list[str] = []
            for x in payload[key]:
                s = str(x)
                if s not in allowed:
                    return problem_response(
                        422,
                        detail=f"{key} value not allowed.",
                        code="schema_validation_failed",
                    )
                cleaned.append(s)
            cfg[key] = cleaned
    if "token_budget" in payload:
        try:
            tb = int(payload["token_budget"])
            if not (0 <= tb <= 128000):
                raise ValueError
            cfg["token_budget"] = tb
        except (TypeError, ValueError):
            return problem_response(
                422, detail="invalid token_budget.", code="schema_validation_failed"
            )
    if "limit" in payload:
        try:
            lim = int(payload["limit"])
            if not (1 <= lim <= 100):
                raise ValueError
            cfg["limit"] = lim
        except (TypeError, ValueError):
            return problem_response(422, detail="invalid limit.", code="schema_validation_failed")

    before = {
        "etag": current_etag,
        "mode": row.mode if row else None,
        "version": row.version if row else 0,
    }
    if row is None:
        row = DossierMemoryProfile(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            dossier_id=dossier_id,
            connection_id=connection_uuid,
            mode=mode,
            version=1,
            etag=_etag(1, cfg),
            profile_config=cfg,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    else:
        row.mode = mode
        row.version = int(row.version) + 1
        row.profile_config = cfg
        row.etag = _etag(row.version, cfg)
        row.updated_at = datetime.now(UTC)
    session.add(row)
    append_audit_event(
        session,
        action="dossier.memory_profile.update",
        resource_type="dossier_memory_profile",
        resource_id=row.id,
        result="success",
        dossier_id=dossier_id,
        metadata={
            "before": before,
            "after": {"etag": row.etag, "mode": row.mode, "version": row.version},
        },
    )
    session.commit()
    body = profile_to_public(row)
    body["persisted"] = True
    r = jsonify(body)
    r.headers["ETag"] = row.etag
    return r


@bp.get("/dossiers/<uuid:dossier_id>/memory/effective")
@require_permission("dossier.read")
def memory_effective(dossier_id: uuid.UUID) -> Any:
    session = _session()
    dossier = _load_accessible_dossier(session, dossier_id, write=False)
    if dossier is None:
        return problem_response(404, detail="Expediente no encontrado.", code="dossier_not_found")
    tenant_id = dossier.tenant_id
    row = _load_profile(session, tenant_id=tenant_id, dossier_id=dossier_id, connection_id=None)
    host_mode = str(current_app.config.get("MEMORY_CONTEXT_MODE", "disabled") or "disabled")
    if row is None:
        pub = _effective_defaults(tenant_id=tenant_id, dossier_id=dossier_id, connection_id=None)
    else:
        pub = profile_to_public(row)
        pub["persisted"] = True
    pub["capability"] = capability_payload(
        host_mode=host_mode, connection_healthy=host_mode in {"http", "mock"}
    )
    return jsonify(pub)


@bp.get("/memory/capability")
@require_permission("dossier.read")
def memory_capability() -> Any:
    host_mode = str(current_app.config.get("MEMORY_CONTEXT_MODE", "disabled") or "disabled")
    return jsonify(
        capability_payload(host_mode=host_mode, connection_healthy=host_mode in {"http", "mock"})
    )


@bp.post("/dossiers/<uuid:dossier_id>/memory/test-connection")
@require_permission("dossier.write")
def memory_test_connection(dossier_id: uuid.UUID) -> Any:
    """Test connection. MockTransport only via MEMORY_CONTEXT_TEST_TRANSPORT or mock mode."""
    session = _session()
    dossier = _load_accessible_dossier(session, dossier_id, write=True)
    if dossier is None:
        return problem_response(404, detail="Expediente no encontrado.", code="dossier_not_found")
    tenant_id = dossier.tenant_id

    row = _load_profile(session, tenant_id=tenant_id, dossier_id=dossier_id, connection_id=None)
    host_mode = str(current_app.config.get("MEMORY_CONTEXT_MODE", "disabled") or "disabled")

    if host_mode == "disabled":
        if row is not None:
            row.last_test_at = datetime.now(UTC)
            row.last_test_status = "host_disabled"
            row.last_error = "MEMORY_CONTEXT_MODE=disabled"
            session.commit()
        return jsonify(
            {
                "ok": False,
                "status": "host_disabled",
                "synthetic": False,
                "publisher_reliable": False,
                "message": "Host memory disabled",
            }
        )

    try:
        conn = resolve_signal_memory_connection(session, tenant_id=tenant_id)
        test_transport = current_app.config.get("MEMORY_CONTEXT_TEST_TRANSPORT")
        synthetic = False
        if test_transport is not None:
            transport = test_transport
            synthetic = True
        elif host_mode == "mock":
            transport = MockTransport()
            synthetic = True
        else:
            transport = HttpxTransport()
            synthetic = False

        client = build_client_for_connection(
            conn,
            transport=transport,
            require_https=not synthetic,
        )
        external = str(getattr(g, "external_tenant_id", None) or tenant_id)
        health = client.health(external_tenant_id=external)
        if row is not None:
            row.last_test_at = datetime.now(UTC)
            row.last_test_status = "ok_synthetic" if synthetic else "ok"
            row.last_error = None
            row.last_coverage = {
                "health": health.get("status"),
                "publisher_degraded": True,
                "synthetic": synthetic,
            }
            session.commit()
        return jsonify(
            {
                "ok": True,
                "status": "ok",
                "synthetic": synthetic,
                "engine_enabled": health.get("engine_enabled"),
                "publisher_reliable": False,
                "message": (
                    "Synthetic test transport (test-only)"
                    if synthetic
                    else "Connection test completed (publisher degraded — Signal debt)"
                ),
            }
        )
    except MemoryHttpError as exc:
        if row is not None:
            row.last_test_at = datetime.now(UTC)
            row.last_test_status = "error"
            row.last_error = f"{exc.code}:{exc.message}"[:500]
            session.commit()
        return problem_response(
            502 if exc.retryable else 400,
            detail=exc.message,
            code=exc.code,
        )
    except Exception as exc:  # connection_conflict / missing secret etc.
        if row is not None:
            row.last_test_at = datetime.now(UTC)
            row.last_test_status = "error"
            row.last_error = str(exc)[:500]
            session.commit()
        return problem_response(400, detail=str(exc), code="memory_connection_error")
