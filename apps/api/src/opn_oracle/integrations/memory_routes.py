"""Flask BFF for dossier memory profile / health / test (MDEV-04 REWORK-2 + G-29)."""

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
    OPERATIONAL_MODES,
    SERVER_DEFAULT_MEMORY_MODE,
    build_client_for_connection,
    create_dossier_memory_profile,
    default_profile_payload,
    effective_resolution_to_public,
    legacy_missing_payload,
    profile_config_fingerprint,
    profile_to_public,
    resolve_effective_dossier_memory_profile,
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


def _apply_cfg_from_payload(
    base_cfg: dict[str, Any], payload: dict[str, Any], mode: str
) -> tuple[dict[str, Any] | None, Any]:
    """Merge validated fields into cfg. Returns (cfg, error_response|None)."""
    cfg = dict(base_cfg)
    cfg["mode"] = mode
    for key, allowed in (
        ("sources", ALLOWED_SOURCES),
        ("kinds", ALLOWED_KINDS),
        ("classifications_allowed", ALLOWED_CLASSIFICATIONS),
    ):
        if key in payload:
            if not isinstance(payload[key], list):
                return None, problem_response(
                    422, detail=f"{key} must be list.", code="schema_validation_failed"
                )
            cleaned: list[str] = []
            for x in payload[key]:
                s = str(x)
                if s not in allowed:
                    return None, problem_response(
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
            return None, problem_response(
                422, detail="invalid token_budget.", code="schema_validation_failed"
            )
    if "limit" in payload:
        try:
            lim = int(payload["limit"])
            if not (1 <= lim <= 100):
                raise ValueError
            cfg["limit"] = lim
        except (TypeError, ValueError):
            return None, problem_response(
                422, detail="invalid limit.", code="schema_validation_failed"
            )
    cfg["status"] = "active"
    if "config_source" not in cfg or cfg.get("config_source") in {
        "server_policy",
        "legacy_missing",
        None,
    }:
        cfg["config_source"] = "user"
    cfg["scope_type"] = "dossier"
    cfg["uses_tenant_curated"] = False
    cfg["uses_global_memory"] = False
    return cfg, None


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
        body = legacy_missing_payload(
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
    """Update the product **default** profile only (connection_id IS NULL).

    Body ``connection_id`` is ignored for write targeting so an arbitrary
    connection cannot create a parallel product profile. Connection-bound
    overrides are deferred product capability (no silent create path here).
    """
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

    # Client cannot force tenant_id via body.
    if "tenant_id" in payload and str(payload.get("tenant_id")) != str(tenant_id):
        return problem_response(
            422, detail="tenant_id cannot be forced.", code="schema_validation_failed"
        )

    # Product PUT always targets default profile. Ignore body.connection_id so it
    # cannot spawn a second row (connection overrides are deferred / not product).
    ignored_connection_id = bool(payload.get("connection_id"))

    row = _load_profile(
        session, tenant_id=tenant_id, dossier_id=dossier_id, connection_id=None
    )
    legacy = legacy_missing_payload(
        tenant_id=tenant_id, dossier_id=dossier_id, connection_id=None
    )
    current_etag = row.etag if row is not None else legacy["etag"]
    if str(if_match) != str(current_etag):
        return problem_response(
            409, detail="ETag mismatch; reload and retry.", code="etag_conflict"
        )

    # Optional version CAS (in addition to ETag).
    if "expected_version" in payload and row is not None:
        try:
            expected = int(payload["expected_version"])
        except (TypeError, ValueError):
            return problem_response(
                422, detail="invalid expected_version.", code="schema_validation_failed"
            )
        if expected != int(row.version):
            return problem_response(
                409,
                detail="Version mismatch; reload and retry.",
                code="version_conflict",
            )

    mode = str(payload.get("mode") or (row.mode if row else SERVER_DEFAULT_MEMORY_MODE)).strip().lower()
    if mode not in OPERATIONAL_MODES:
        return problem_response(422, detail="invalid mode.", code="schema_validation_failed")

    base_cfg = dict((row.profile_config if row else None) or default_profile_payload())
    cfg, err = _apply_cfg_from_payload(base_cfg, payload, mode)
    if err is not None:
        return err
    assert cfg is not None

    # Identical retry: same fingerprint → no version bump, no audit inflation.
    if row is not None:
        current_fp = profile_config_fingerprint(dict(row.profile_config or {}), str(row.mode))
        desired_fp = profile_config_fingerprint(cfg, mode)
        if current_fp == desired_fp:
            body = profile_to_public(row)
            body["persisted"] = True
            body["idempotent_replay"] = True
            body["connection_id"] = None
            if ignored_connection_id:
                body["ignored_body_connection_id"] = True
            r = jsonify(body)
            r.headers["ETag"] = row.etag
            return r

    before = {
        "etag": current_etag,
        "mode": row.mode if row else None,
        "version": row.version if row else 0,
        "fingerprint": (
            profile_config_fingerprint(dict(row.profile_config or {}), str(row.mode))
            if row is not None
            else None
        ),
    }
    if row is None:
        # Materialize default profile via PUT (also covered by materialize endpoint).
        row = create_dossier_memory_profile(
            session,
            tenant_id=tenant_id,
            dossier_id=dossier_id,
            connection_id=None,
            mode=mode,
            provenance="user_materialize_via_put",
            config_source="user",
        )
        # Apply full cfg after create defaults.
        row.mode = mode
        row.profile_config = cfg
        row.etag = _etag(int(row.version), cfg)
        row.updated_at = datetime.now(UTC)
    else:
        row.mode = mode
        row.version = int(row.version) + 1
        row.profile_config = cfg
        row.etag = _etag(row.version, cfg)
        row.updated_at = datetime.now(UTC)
    # Hard guarantee: product path never binds connection_id on PUT.
    row.connection_id = None
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
            "after": {
                "etag": row.etag,
                "mode": row.mode,
                "version": row.version,
                "connection_id": None,
                "fingerprint": profile_config_fingerprint(cfg, mode),
            },
            "ignored_body_connection_id": ignored_connection_id,
            "actor_reason": str(payload.get("reason") or payload.get("motivo") or "")[:500] or None,
        },
    )
    session.commit()
    body = profile_to_public(row)
    body["persisted"] = True
    if ignored_connection_id:
        body["ignored_body_connection_id"] = True
    r = jsonify(body)
    r.headers["ETag"] = row.etag
    return r


@bp.post("/dossiers/<uuid:dossier_id>/memory/profile/materialize")
@require_permission("dossier.write")
def materialize_memory_profile(dossier_id: uuid.UUID) -> Any:
    """Idempotent, audited materialization of legacy_missing **default** profiles.

    Does not silent-backfill on GET. Re-call returns existing row without
    version inflation when already persisted. Body connection_id is ignored;
    only the default profile (connection_id NULL) is materialized.
    """
    session = _session()
    dossier = _load_accessible_dossier(session, dossier_id, write=True)
    if dossier is None:
        return problem_response(404, detail="Expediente no encontrado.", code="dossier_not_found")
    tenant_id = dossier.tenant_id
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    ignored_connection_id = bool(payload.get("connection_id"))

    row = _load_profile(
        session, tenant_id=tenant_id, dossier_id=dossier_id, connection_id=None
    )
    if row is not None:
        body = profile_to_public(row)
        body["persisted"] = True
        body["idempotent_replay"] = True
        body["materialized"] = False
        if ignored_connection_id:
            body["ignored_body_connection_id"] = True
        r = jsonify(body)
        r.headers["ETag"] = row.etag
        return r

    # Server policy only — body cannot force mode on materialize.
    row = create_dossier_memory_profile(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        connection_id=None,
        mode=SERVER_DEFAULT_MEMORY_MODE,
        provenance="legacy_materialize",
        config_source="server_policy",
    )
    append_audit_event(
        session,
        action="dossier.memory_profile.materialize",
        resource_type="dossier_memory_profile",
        resource_id=row.id,
        result="success",
        dossier_id=dossier_id,
        metadata={
            "before": {"status": "legacy_missing", "version": 0},
            "after": {"mode": row.mode, "version": row.version, "etag": row.etag},
            "actor_reason": str(payload.get("reason") or payload.get("motivo") or "")[:500] or None,
        },
    )
    session.commit()
    body = profile_to_public(row)
    body["persisted"] = True
    body["materialized"] = True
    body["idempotent_replay"] = False
    if ignored_connection_id:
        body["ignored_body_connection_id"] = True
    r = jsonify(body)
    r.headers["ETag"] = row.etag
    r.status_code = 201
    return r


@bp.get("/dossiers/<uuid:dossier_id>/memory/effective")
@require_permission("dossier.read")
def memory_effective(dossier_id: uuid.UUID) -> Any:
    """Effective profile + host health. Shared SSOT with conversation jobs.

    Uses ``resolve_effective_dossier_memory_profile`` (same function as ask/answer).
    Returns configured_profile vs effective_profile; connection overrides are
    listed as deferred, never silently selected.
    """
    session = _session()
    dossier = _load_accessible_dossier(session, dossier_id, write=False)
    if dossier is None:
        return problem_response(404, detail="Expediente no encontrado.", code="dossier_not_found")
    tenant_id = dossier.tenant_id
    resolution = resolve_effective_dossier_memory_profile(
        session, tenant_id=tenant_id, dossier_id=dossier_id
    )
    pub = effective_resolution_to_public(
        resolution, tenant_id=tenant_id, dossier_id=dossier_id
    )
    host_mode = str(current_app.config.get("MEMORY_CONTEXT_MODE", "disabled") or "disabled")
    # Single source of truth: capability owns host health; project UI fields from it.
    capability = capability_payload(
        host_mode=host_mode, connection_healthy=host_mode in {"http", "mock"}
    )
    pub["capability"] = capability
    pub["publisher_reliable"] = capability["publisher_reliable"]
    pub["publisher_status"] = capability["publisher_status"]
    # Prefer profile-level message when legacy; otherwise host capability message.
    if pub.get("status") != "legacy_missing":
        pub["message"] = capability["message"]
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

    row = _load_profile(
        session, tenant_id=tenant_id, dossier_id=dossier_id, connection_id=None
    )
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
            # Health probe succeeded: do not stamp publisher_degraded on a green path.
            # (CAS/fencing/requeue closed 2026-08-02; hardcoding lied to Ask + profile UI.)
            row.last_coverage = {
                "health": health.get("status"),
                "publisher_degraded": False,
                "synthetic": synthetic,
            }
            session.commit()
        return jsonify(
            {
                "ok": True,
                "status": "ok",
                "synthetic": synthetic,
                "engine_enabled": health.get("engine_enabled"),
                "publisher_reliable": True,
                "message": (
                    "Synthetic test transport (test-only)"
                    if synthetic
                    else "Connection test completed"
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


@bp.get("/dossiers/<uuid:dossier_id>/memory/outbox")
@require_permission("dossier.read")
def memory_outbox_activity(dossier_id: uuid.UUID) -> Any:
    """Safe outbox status for bilateral memory events (no payload secrets)."""
    from opn_oracle.integrations.memory_outbox import list_memory_outbox_safe

    session = _session()
    dossier = _load_accessible_dossier(session, dossier_id, write=False)
    if dossier is None:
        return problem_response(404, detail="Expediente no encontrado.", code="dossier_not_found")
    items = list_memory_outbox_safe(tenant_id=dossier.tenant_id, dossier_id=dossier_id)
    return jsonify(
        {
            "dossier_id": str(dossier_id),
            "items": items,
            "publisher_degraded": True,
            "bilateral_outbox_enabled": __import__(
                "opn_oracle.integrations.memory_outbox", fromlist=["bilateral_outbox_enabled"]
            ).bilateral_outbox_enabled(),
        }
    )
