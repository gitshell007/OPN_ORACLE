"""Tenant-admin Signal connection and monitor lifecycle API."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Any
from urllib.parse import urlparse

from apiflask import APIBlueprint
from flask import current_app, g, jsonify, request
from flask_login import current_user
from pydantic import ValidationError
from sqlalchemy import select

from opn_oracle.auth.permissions import recent_auth_required, require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db
from opn_oracle.integrations.models import IntegrationOutboxEvent, SignalMonitorConfigVersion
from opn_oracle.integrations.service import (
    IdempotencyConflict,
    canonical_hash,
    lock_idempotency_key,
    monitor_spec_from_payload,
    stage_dossier_monitor_create,
    stage_outbox,
    store_credential,
    watchlist_config_from_spec,
)
from opn_oracle.jobs.service import enqueue_job
from opn_oracle.oracle.models import SignalMonitor, StrategicDossier, Watchlist
from opn_oracle.oracle.policy import dossier_accessible
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.platform.models import IntegrationConnection

bp = APIBlueprint("signal_integrations", __name__, url_prefix="/api/v1")

# Back-compat aliases for tests/callers that imported private helpers.
_monitor_spec_from_payload = monitor_spec_from_payload
_watchlist_config = watchlist_config_from_spec


def _monitor_validation_problem(error: ValidationError) -> Any:
    messages = [str(item.get("msg", "Configuración no válida.")) for item in error.errors()]
    detail = "; ".join(messages[:3]) or "Configuración del monitor no válida."
    return problem_response(
        422,
        detail=f"Configuración del monitor no válida: {detail}",
        code="signal_monitor_config_invalid",
    )


def _connection_payload(item: IntegrationConnection) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "provider": item.provider,
        "name": item.name,
        "status": item.status,
        "adapter_mode": item.adapter_mode,
        "api_version": item.api_version,
        "base_url": item.base_url,
        "circuit_state": item.circuit_state,
        "last_health_at": item.last_health_at.isoformat() if item.last_health_at else None,
        "last_success_at": item.last_success_at.isoformat() if item.last_success_at else None,
        "last_error": item.last_error,
        "version": item.version,
    }


def _get_tenant_connection(connection_id: uuid.UUID) -> IntegrationConnection | None:
    return db.session.scalar(
        select(IntegrationConnection)
        .where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.tenant_id == g.active_tenant_id,
            IntegrationConnection.provider == "signal-avanza",
        )
        .with_for_update()
    )


def _deactivate_other_active_connections(tenant_id: uuid.UUID, *, keep_id: uuid.UUID) -> list[str]:
    """Disable every other active signal-avanza connection for the tenant.

    Exactly one active connection is allowed; callers hold the keep row locked.
    """
    others = list(
        db.session.scalars(
            select(IntegrationConnection)
            .where(
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.provider == "signal-avanza",
                IntegrationConnection.status == "active",
                IntegrationConnection.id != keep_id,
            )
            .with_for_update()
        )
    )
    deactivated: list[str] = []
    for row in others:
        row.status = "disabled"
        row.version += 1
        deactivated.append(str(row.id))
    return deactivated


def _signal_environment_identity(url: str) -> str | None:
    """Environment key: hostname + non-default port. Paths are ignored.

    ``https://signal-dev.example/api/v1/oracle`` and
    ``https://signal-dev.example`` are the same environment. A non-standard
    port (e.g. ``:8443``) is part of the identity; default 443/80 are not.

    Never raises: invalid port or unparseable URL returns ``None`` so callers
    can fail closed without a 500.
    """
    try:
        parsed = urlparse(str(url).strip())
    except Exception:
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    try:
        port = parsed.port
    except ValueError:
        # e.g. :abc or :99999 — not a usable environment identity
        return None
    scheme = (parsed.scheme or "").lower()
    if port is not None:
        default_port = 443 if scheme == "https" else 80 if scheme == "http" else None
        if default_port is None or port != default_port:
            return f"{host}:{port}"
    return host


def _parse_optional_base_url(raw: Any) -> tuple[str | None, Any | None]:
    """Normalize optional Signal ``base_url`` or return a 422 problem.

    Empty / null remains allowed (mock or host-default modes). A non-empty
    value must be an http(s) URL with a hostname and a valid port if present.
    Malformed values never skip the guardian via a 500.
    """
    if raw is None:
        return None, None
    if not isinstance(raw, str):
        return None, problem_response(
            422,
            detail="base_url debe ser una cadena URL o null.",
            code="validation_failed",
        )
    text = raw.strip()
    if text == "":
        return None, None
    if len(text) > 1000:
        return None, problem_response(
            422,
            detail="base_url supera la longitud máxima permitida.",
            code="validation_failed",
        )
    try:
        parsed = urlparse(text)
        # Force port validation (ValueError on non-integer / out-of-range).
        _ = parsed.port
    except ValueError:
        return None, problem_response(
            422,
            detail="base_url no es una URL válida (puerto o formato incorrecto).",
            code="validation_failed",
        )
    except Exception:
        return None, problem_response(
            422,
            detail="base_url no es una URL válida.",
            code="validation_failed",
        )
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        return None, problem_response(
            422,
            detail="base_url debe usar http o https.",
            code="validation_failed",
        )
    if not (parsed.hostname or "").strip():
        return None, problem_response(
            422,
            detail="base_url debe incluir un nombre de host válido.",
            code="validation_failed",
        )
    return text[:1000], None


def _parse_confirm_cross_environment(
    payload: dict[str, Any],
) -> tuple[bool | None, Any | None]:
    """Strict JSON boolean for ``confirm_cross_environment``.

    Only the boolean ``true`` authorizes a cross-environment change.
    ``false`` or an absent field means not confirmed (422 when cross-env).
    Any non-boolean (``"true"``, ``"false"``, ``1``, ``[]``, ``{}``) is
    ``validation_failed`` and never authorizes — ``bool("false")`` is True
    in Python and must not be used.
    """
    if "confirm_cross_environment" not in payload:
        return False, None
    value = payload["confirm_cross_environment"]
    if value is True:
        return True, None
    if value is False:
        return False, None
    return None, problem_response(
        422,
        detail=(
            "confirm_cross_environment debe ser un booleano JSON "
            "(true o false), no una cadena ni otro tipo."
        ),
        code="validation_failed",
    )


def _requires_cross_environment_confirmation(base_url: str | None) -> bool:
    """True when the target is not the Signal this deploy was configured for.

    Deliberately does NOT key off ``APP_ENV``: oracle-dev runs with
    ``APP_ENV=production`` (see docs/operations/DEV_NATIVE_DEPLOY.md), so an
    environment-based guard is inert on the very host it was meant to protect.
    The reliable signal is ``SIGNAL_AVANZA_BASE_URL`` — the Signal this deploy
    was pointed at. Comparison uses hostname (+ non-default port), not path:
    configured ``…/api/v1/oracle`` and a connection root on the same host are
    the same environment.

    Unparseable / invalid-port URLs fail closed (require confirmation) and must
    be rejected earlier by ``_parse_optional_base_url`` before persist/activate.
    """
    if not base_url or not str(base_url).strip():
        return False
    candidate = str(base_url).strip()
    try:
        parsed = urlparse(candidate)
        host = (parsed.hostname or "").lower()
        # Touch .port so invalid ports cannot silently skip host checks.
        _ = parsed.port
    except ValueError:
        return True
    except Exception:
        return True
    if not host or host in {"localhost", "127.0.0.1"} or host.endswith(".local"):
        return False
    expected = str(current_app.config.get("SIGNAL_AVANZA_BASE_URL") or "").strip()
    if expected:
        candidate_key = _signal_environment_identity(candidate)
        expected_key = _signal_environment_identity(expected)
        # Fail closed if either side cannot be identified as a host.
        if candidate_key is None or expected_key is None:
            return True
        return candidate_key != expected_key
    # No expected URL configured: any remote https target needs confirmation.
    return candidate.lower().startswith("https://")


def _is_platform_super_admin() -> bool:
    return getattr(current_user, "platform_role", None) == "super_admin"


def _enforce_cross_environment_authorization(
    base_url: str | None, *, confirmed: bool
) -> Any | None:
    """Gate cross-environment Signal targets to platform super_admin + confirm.

    Returns a problem response to short-circuit the handler, or None when allowed.
    ``confirmed`` must already be a real bool from
    ``_parse_confirm_cross_environment`` — never ``bool(payload.get(...))``.
    """
    if not _requires_cross_environment_confirmation(base_url):
        return None
    if not _is_platform_super_admin():
        return problem_response(
            403,
            detail=(
                "Apuntar Signal a un destino distinto del configurado en este "
                "despliegue requiere superadministración de plataforma."
            ),
            code="signal_cross_environment_platform_required",
        )
    if not confirmed:
        return problem_response(
            422,
            detail=(
                "La URL de Signal no coincide con el entorno de este despliegue. "
                "Confirma explícitamente con confirm_cross_environment=true si es intencional."
            ),
            code="signal_cross_environment_confirmation_required",
        )
    return None


def _cross_env_audit_actor() -> dict[str, Any]:
    """Identity of who authorized a cross-environment Signal change."""
    return {
        "user_id": str(current_user.id),
        "platform_role": getattr(current_user, "platform_role", None),
        "email_hash": hashlib.sha256(
            str(getattr(current_user, "email", "")).encode("utf-8")
        ).hexdigest()[:16],
    }


def _monitor_dossier(monitor: SignalMonitor) -> StrategicDossier | None:
    return db.session.scalar(
        select(StrategicDossier)
        .join(Watchlist, Watchlist.dossier_id == StrategicDossier.id)
        .where(
            Watchlist.id == monitor.watchlist_id,
            Watchlist.tenant_id == monitor.tenant_id,
            StrategicDossier.tenant_id == monitor.tenant_id,
        )
    )


def _dispatch(event: IntegrationOutboxEvent) -> None:
    from opn_oracle.integrations.tasks import dispatch_outbox

    dispatch_outbox.apply_async(
        kwargs={"event_id": str(event.id), "tenant_id": str(event.tenant_id)}, queue="signals"
    )


@bp.get("/integrations/signal-avanza")
@require_permission("tenant.integrations.manage")
def list_connections() -> Any:
    items = db.session.scalars(
        select(IntegrationConnection).where(
            IntegrationConnection.tenant_id == g.active_tenant_id,
            IntegrationConnection.provider == "signal-avanza",
            IntegrationConnection.provider == "signal-avanza",
        )
    )
    return jsonify({"items": [_connection_payload(item) for item in items]})


@bp.post("/integrations/signal-avanza")
@require_permission("tenant.integrations.manage")
@recent_auth_required
def create_connection() -> Any:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return problem_response(
            422, detail="El cuerpo debe ser un objeto JSON.", code="validation_failed"
        )
    mode = str(payload.get("adapter_mode", "mock"))
    if mode not in {"mock", "http"}:
        return problem_response(422, detail="adapter_mode no válido.", code="validation_failed")
    if mode == "http" and not (
        current_app.config["SIGNAL_AVANZA_ENABLED"]
        and current_app.config["SIGNAL_AVANZA_CONTRACT_CONFIRMED"]
    ):
        return problem_response(
            409,
            detail="El contrato HTTP Signal no está confirmado.",
            code="signal_contract_unconfirmed",
        )
    base_url, base_url_error = _parse_optional_base_url(payload.get("base_url"))
    if base_url_error is not None:
        return base_url_error
    confirmed, confirm_error = _parse_confirm_cross_environment(payload)
    if confirm_error is not None:
        return confirm_error
    assert confirmed is not None
    cross_env = _requires_cross_environment_confirmation(base_url)
    denied = _enforce_cross_environment_authorization(base_url, confirmed=confirmed)
    if denied is not None:
        return denied
    status = "active" if mode == "mock" else "pending"
    connection = IntegrationConnection(
        tenant_id=g.active_tenant_id,
        provider="signal-avanza",
        name=str(payload.get("name", "default"))[:100],
        status=status,
        adapter_mode=mode,
        base_url=base_url,
        api_version=str(payload.get("api_version", "2026-07-01"))[:30],
        subscription_key=secrets.token_urlsafe(24),
    )
    db.session.add(connection)
    db.session.flush()
    deactivated: list[str] = []
    if status == "active":
        deactivated = _deactivate_other_active_connections(
            g.active_tenant_id, keep_id=connection.id
        )
    try:
        if payload.get("api_token"):
            store_credential(
                connection=connection, kind="api_token", secret=str(payload["api_token"])
            )
        if payload.get("webhook_secret"):
            store_credential(
                connection=connection, kind="webhook_secret", secret=str(payload["webhook_secret"])
            )
    except RuntimeError as exc:
        db.session.rollback()
        return problem_response(503, detail=str(exc), code="integration_keyring_unavailable")
    audit_meta: dict[str, Any] = {
        "adapter_mode": mode,
        "base_url": base_url,
        "status": status,
        "deactivated_connection_ids": deactivated,
        "cross_environment_confirmed": cross_env,
        "actor_platform_role": getattr(current_user, "platform_role", None),
    }
    if cross_env:
        audit_meta["authorized_by"] = _cross_env_audit_actor()
    append_audit_event(
        db.session,
        action="integration.signal.create",
        resource_type="integration_connection",
        resource_id=connection.id,
        result="success",
        metadata=audit_meta,
    )
    db.session.commit()
    return jsonify(_connection_payload(connection)), 201


@bp.patch("/integrations/signal-avanza/<uuid:connection_id>")
@require_permission("tenant.integrations.manage")
@recent_auth_required
def update_connection(connection_id: uuid.UUID) -> Any:
    """Edit destination settings without recreating the connection."""
    connection = _get_tenant_connection(connection_id)
    if connection is None:
        return problem_response(
            404, detail="Integración no encontrada.", code="integration_not_found"
        )
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return problem_response(
            422, detail="El cuerpo debe ser un objeto JSON.", code="validation_failed"
        )
    before = {
        "base_url": connection.base_url,
        "api_version": connection.api_version,
        "adapter_mode": connection.adapter_mode,
        "name": connection.name,
    }
    if "name" in payload:
        connection.name = str(payload.get("name") or connection.name)[:100]
    if "api_version" in payload:
        connection.api_version = str(payload.get("api_version") or connection.api_version)[:30]
    if "adapter_mode" in payload:
        mode = str(payload.get("adapter_mode") or "")
        if mode not in {"mock", "http"}:
            return problem_response(422, detail="adapter_mode no válido.", code="validation_failed")
        if mode == "http" and not (
            current_app.config["SIGNAL_AVANZA_ENABLED"]
            and current_app.config["SIGNAL_AVANZA_CONTRACT_CONFIRMED"]
        ):
            return problem_response(
                409,
                detail="El contrato HTTP Signal no está confirmado.",
                code="signal_contract_unconfirmed",
            )
        connection.adapter_mode = mode
    if "base_url" in payload:
        parsed_url, base_url_error = _parse_optional_base_url(payload.get("base_url"))
        if base_url_error is not None:
            return base_url_error
        connection.base_url = parsed_url
    # Stored base_url must still be valid before any cross-env gate / persist.
    if connection.base_url is not None:
        _, stored_url_error = _parse_optional_base_url(connection.base_url)
        if stored_url_error is not None:
            return stored_url_error
    confirmed, confirm_error = _parse_confirm_cross_environment(payload)
    if confirm_error is not None:
        return confirm_error
    assert confirmed is not None
    cross_env = _requires_cross_environment_confirmation(connection.base_url)
    denied = _enforce_cross_environment_authorization(connection.base_url, confirmed=confirmed)
    if denied is not None:
        return denied
    after = {
        "base_url": connection.base_url,
        "api_version": connection.api_version,
        "adapter_mode": connection.adapter_mode,
        "name": connection.name,
    }
    if before == after:
        return jsonify(_connection_payload(connection))
    connection.version += 1
    audit_meta: dict[str, Any] = {
        "before": before,
        "after": after,
        "cross_environment_confirmed": cross_env,
        "actor_platform_role": getattr(current_user, "platform_role", None),
    }
    if cross_env:
        audit_meta["authorized_by"] = _cross_env_audit_actor()
    append_audit_event(
        db.session,
        action="integration.signal.update",
        resource_type="integration_connection",
        resource_id=connection.id,
        result="success",
        metadata=audit_meta,
    )
    db.session.commit()
    return jsonify(_connection_payload(connection))


@bp.post("/integrations/signal-avanza/<uuid:connection_id>/activate")
@require_permission("tenant.integrations.manage")
@recent_auth_required
def activate_connection(connection_id: uuid.UUID) -> Any:
    """Make this connection the sole active Signal connection for the tenant.

    Also reactivates a disabled/pending/error connection. Previous actives are
    disabled in the same transaction.

    Cross-environment destinations reuse
    ``_enforce_cross_environment_authorization`` on the connection's stored
    ``base_url`` and optional body ``confirm_cross_environment`` (ORA-XENV-ACTIVATE).
    """
    connection = _get_tenant_connection(connection_id)
    if connection is None:
        return problem_response(
            404, detail="Integración no encontrada.", code="integration_not_found"
        )
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    elif not isinstance(payload, dict):
        return problem_response(
            422, detail="El cuerpo debe ser un objeto JSON.", code="validation_failed"
        )
    if connection.base_url is not None:
        _, base_url_error = _parse_optional_base_url(connection.base_url)
        if base_url_error is not None:
            return base_url_error
    confirmed, confirm_error = _parse_confirm_cross_environment(payload)
    if confirm_error is not None:
        return confirm_error
    assert confirmed is not None
    cross_env = _requires_cross_environment_confirmation(connection.base_url)
    denied = _enforce_cross_environment_authorization(
        connection.base_url,
        confirmed=confirmed,
    )
    if denied is not None:
        return denied
    previous_status = connection.status
    deactivated = _deactivate_other_active_connections(g.active_tenant_id, keep_id=connection.id)
    connection.status = "active"
    if previous_status != "active":
        connection.version += 1
    audit_meta: dict[str, Any] = {
        "previous_status": previous_status,
        "new_status": "active",
        "deactivated_connection_ids": deactivated,
        "deactivated_count": len(deactivated),
        "base_url": connection.base_url,
        "cross_environment_confirmed": cross_env,
        "actor_platform_role": getattr(current_user, "platform_role", None),
    }
    if cross_env:
        audit_meta["authorized_by"] = _cross_env_audit_actor()
    append_audit_event(
        db.session,
        action="integration.signal.activate",
        resource_type="integration_connection",
        resource_id=connection.id,
        result="success",
        metadata=audit_meta,
    )
    db.session.commit()
    return jsonify(_connection_payload(connection))


@bp.post("/integrations/signal-avanza/<uuid:connection_id>/rotate")
@bp.post("/integrations/signal-avanza/<uuid:connection_id>/rotate-secret")
@require_permission("tenant.integrations.manage")
@recent_auth_required
def rotate_connection(connection_id: uuid.UUID) -> Any:
    connection = db.session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.tenant_id == g.active_tenant_id,
            IntegrationConnection.provider == "signal-avanza",
        )
    )
    if connection is None:
        return problem_response(
            404, detail="Integración no encontrada.", code="integration_not_found"
        )
    payload = request.get_json(silent=True) or {}
    kind = str(payload.get("kind", ""))
    secret = str(payload.get("secret", ""))
    if kind not in {"api_token", "webhook_secret"} or len(secret) < 16:
        return problem_response(422, detail="Credencial no válida.", code="validation_failed")
    store_credential(connection=connection, kind=kind, secret=secret)
    append_audit_event(
        db.session,
        action="integration.signal.rotate",
        resource_type="integration_connection",
        resource_id=connection.id,
        result="success",
        metadata={"credential_kind": kind},
    )
    db.session.commit()
    return jsonify({"status": "rotated"})


@bp.post("/integrations/signal-avanza/<uuid:connection_id>/disable")
@require_permission("tenant.integrations.manage")
@recent_auth_required
def disable_connection(connection_id: uuid.UUID) -> Any:
    connection = _get_tenant_connection(connection_id)
    if connection is None:
        return problem_response(
            404, detail="Integración no encontrada.", code="integration_not_found"
        )
    previous_status = connection.status
    connection.status = "disabled"
    connection.version += 1
    append_audit_event(
        db.session,
        action="integration.signal.disable",
        resource_type="integration_connection",
        resource_id=connection.id,
        result="success",
        metadata={
            "previous_status": previous_status,
            "new_status": "disabled",
        },
    )
    db.session.commit()
    return jsonify(_connection_payload(connection))


@bp.post("/integrations/signal-avanza/test")
@require_permission("tenant.integrations.manage")
def test_connection() -> Any:
    payload = request.get_json(silent=True) or {}
    try:
        connection_id = uuid.UUID(str(payload.get("connection_id", "")))
    except ValueError:
        return problem_response(422, detail="connection_id no válido.", code="validation_failed")
    connection = db.session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.tenant_id == g.active_tenant_id,
            IntegrationConnection.provider == "signal-avanza",
        )
    )
    if connection is None:
        return problem_response(
            404, detail="Integración no encontrada.", code="integration_not_found"
        )
    key = (
        request.headers.get("Idempotency-Key")
        or f"connection-test:{connection.id}:{connection.version}"
    )
    event = stage_outbox(
        connection=connection,
        monitor=None,
        event_type="connection.test",
        payload={"connection_id": str(connection.id)},
        idempotency_key=key,
    )
    db.session.commit()
    _dispatch(event)
    return jsonify({"outbox_event_id": str(event.id), "status": event.status}), 202


@bp.post("/integrations/signal-avanza/<uuid:connection_id>/reconcile")
@require_permission("tenant.integrations.manage")
def reconcile_connection(connection_id: uuid.UUID) -> Any:
    connection = db.session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.tenant_id == g.active_tenant_id,
            IntegrationConnection.provider == "signal-avanza",
        )
    )
    if connection is None:
        return problem_response(
            404, detail="Integración no encontrada.", code="integration_not_found"
        )
    events = list(
        db.session.scalars(
            select(IntegrationOutboxEvent)
            .where(
                IntegrationOutboxEvent.connection_id == connection.id,
                IntegrationOutboxEvent.tenant_id == connection.tenant_id,
                IntegrationOutboxEvent.status.in_(("pending", "retrying")),
            )
            .limit(100)
        )
    )
    for event in events:
        _dispatch(event)
    return jsonify({"requeued": len(events)}), 202


@bp.get("/dossiers/<uuid:dossier_id>/signal-monitors")
@require_permission("signal.read")
def list_dossier_monitors(dossier_id: uuid.UUID) -> Any:
    dossier = db.session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id, StrategicDossier.tenant_id == g.active_tenant_id
        )
    )
    if dossier is None or not dossier_accessible(
        db.session(), dossier, current_user.id, write=False
    ):
        return problem_response(404, detail="Expediente no encontrado.", code="dossier_not_found")
    monitors = db.session.execute(
        select(SignalMonitor, Watchlist)
        .join(Watchlist, Watchlist.id == SignalMonitor.watchlist_id)
        .where(
            Watchlist.dossier_id == dossier.id,
            SignalMonitor.tenant_id == dossier.tenant_id,
        )
    )
    return jsonify(
        {
            "items": [
                {
                    "id": str(item.id),
                    "name": watchlist.name,
                    "provider": item.provider,
                    "status": item.status,
                    "connection_id": str(item.connection_id) if item.connection_id else None,
                    "external_id": item.external_id,
                    "desired_status": item.desired_status,
                    "observed_status": item.observed_status,
                    "last_synced_at": item.last_synced_at,
                    "last_error": item.last_error,
                }
                for item, watchlist in monitors
            ]
        }
    )


@bp.post("/dossiers/<uuid:dossier_id>/signal-monitors")
@require_permission("signal.review")
def create_dossier_monitor(dossier_id: uuid.UUID) -> Any:
    dossier = db.session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id, StrategicDossier.tenant_id == g.active_tenant_id
        )
    )
    if dossier is None or not dossier_accessible(
        db.session(), dossier, current_user.id, write=True
    ):
        return problem_response(404, detail="Expediente no encontrado.", code="dossier_not_found")
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return problem_response(
            422, detail="El cuerpo debe ser un objeto JSON.", code="validation_failed"
        )
    key = request.headers.get("Idempotency-Key", "")
    if len(key) < 8:
        return problem_response(
            422, detail="Idempotency-Key es obligatoria.", code="validation_failed"
        )
    try:
        connection_id = uuid.UUID(str(payload.get("connection_id", "")))
    except ValueError:
        return problem_response(422, detail="connection_id no válido.", code="validation_failed")
    connection = db.session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.tenant_id == dossier.tenant_id,
            IntegrationConnection.provider == "signal-avanza",
            IntegrationConnection.status == "active",
        )
    )
    if connection is None:
        return problem_response(422, detail="Conexión no válida.", code="validation_failed")
    try:
        requested_spec = _monitor_spec_from_payload(
            payload,
            oracle_monitor_id="pending-monitor",
            desired_status="active",
        )
    except ValidationError as error:
        return _monitor_validation_problem(error)
    watchlist_name = str(payload.get("name", "Monitor Signal"))[:200]
    try:
        monitor, event, duplicate = stage_dossier_monitor_create(
            dossier=dossier,
            connection=connection,
            name=watchlist_name,
            spec=requested_spec,
            idempotency_key=key,
            created_by_user_id=current_user.id,
        )
    except IdempotencyConflict:
        return problem_response(
            409,
            detail="Idempotency-Key ya usada con otra solicitud.",
            code="idempotency_conflict",
        )
    db.session.commit()
    if not duplicate:
        _dispatch(event)
    return jsonify(
        {
            "id": str(monitor.id),
            "outbox_event_id": str(event.id),
            **({"duplicate": True} if duplicate else {}),
        }
    ), 202


@bp.get("/signal-monitors/<uuid:monitor_id>/health")
@require_permission("signal.read")
def monitor_health(monitor_id: uuid.UUID) -> Any:
    monitor = db.session.scalar(
        select(SignalMonitor).where(
            SignalMonitor.id == monitor_id, SignalMonitor.tenant_id == g.active_tenant_id
        )
    )
    dossier = _monitor_dossier(monitor) if monitor else None
    if (
        monitor is None
        or dossier is None
        or not dossier_accessible(db.session(), dossier, current_user.id, write=False)
    ):
        return problem_response(404, detail="Monitor no encontrado.", code="monitor_not_found")
    return jsonify(
        {
            "monitor_id": str(monitor.id),
            "desired_status": monitor.desired_status,
            "observed_status": monitor.observed_status,
            "last_synced_at": monitor.last_synced_at,
            "last_error": monitor.last_error,
        }
    )


@bp.patch("/signal-monitors/<uuid:monitor_id>")
@require_permission("signal.review")
def update_monitor(monitor_id: uuid.UUID) -> Any:
    raw_version = request.headers.get("If-Match", "").removeprefix('W/"').removesuffix('"')
    try:
        expected_version = int(raw_version)
    except ValueError:
        expected_version = 0
    if expected_version < 1:
        return problem_response(
            428, detail="If-Match es obligatorio.", code="precondition_required"
        )
    monitor = db.session.scalar(
        select(SignalMonitor)
        .where(
            SignalMonitor.id == monitor_id,
            SignalMonitor.tenant_id == g.active_tenant_id,
        )
        .with_for_update()
    )
    dossier = _monitor_dossier(monitor) if monitor else None
    if (
        monitor is None
        or dossier is None
        or not dossier_accessible(db.session(), dossier, current_user.id, write=True)
    ):
        return problem_response(404, detail="Monitor no encontrado.", code="monitor_not_found")
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return problem_response(
            422, detail="El cuerpo debe ser un objeto JSON.", code="validation_failed"
        )
    key = request.headers.get("Idempotency-Key", "")
    if len(key) < 8:
        return problem_response(
            422, detail="Idempotency-Key es obligatoria.", code="validation_failed"
        )
    connection = db.session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == monitor.connection_id,
            IntegrationConnection.tenant_id == monitor.tenant_id,
            IntegrationConnection.provider == "signal-avanza",
        )
    )
    if connection is None:
        return problem_response(
            409, detail="Conexión no disponible.", code="monitor_connection_missing"
        )
    watchlist = db.session.get(Watchlist, monitor.watchlist_id)
    assert watchlist is not None
    current_config = db.session.scalar(
        select(SignalMonitorConfigVersion.snapshot)
        .where(
            SignalMonitorConfigVersion.tenant_id == monitor.tenant_id,
            SignalMonitorConfigVersion.monitor_id == monitor.id,
        )
        .order_by(SignalMonitorConfigVersion.version.desc())
        .limit(1)
    )
    try:
        requested_spec = _monitor_spec_from_payload(
            payload,
            oracle_monitor_id=str(monitor.id),
            desired_status=monitor.desired_status,
            defaults=current_config or watchlist.query_config,
        )
    except ValidationError as error:
        return _monitor_validation_problem(error)
    intention_hash = canonical_hash(
        {
            "operation": "monitor.update",
            "tenant_id": str(monitor.tenant_id),
            "monitor_id": str(monitor.id),
            "config": _watchlist_config(requested_spec),
        }
    )
    lock_idempotency_key(tenant_id=monitor.tenant_id, idempotency_key=key)
    existing_event = db.session.scalar(
        select(IntegrationOutboxEvent).where(
            IntegrationOutboxEvent.tenant_id == monitor.tenant_id,
            IntegrationOutboxEvent.idempotency_key == key,
        )
    )
    if existing_event is not None:
        existing_version = int(existing_event.payload.get("config_version", monitor.version))
        if existing_event.intention_hash != intention_hash:
            return problem_response(
                409,
                detail="Idempotency-Key ya usada con otra solicitud.",
                code="idempotency_conflict",
            )
        return jsonify(
            {
                "id": str(monitor.id),
                "version": existing_version,
                "outbox_event_id": str(existing_event.id),
                "duplicate": True,
            }
        ), 202
    if monitor.version != expected_version:
        return problem_response(
            409,
            detail="El monitor fue modificado por otro proceso.",
            code="version_conflict",
        )
    monitor.version += 1
    watchlist.query_config = _watchlist_config(requested_spec)
    watchlist.cadence = requested_spec.cadence
    watchlist.version += 1
    snapshot = {
        **requested_spec.model_dump(mode="json"),
        "oracle_watchlist_name": watchlist.name,
        "config_version": monitor.version,
    }
    db.session.add(
        SignalMonitorConfigVersion(
            tenant_id=monitor.tenant_id,
            monitor_id=monitor.id,
            version=monitor.version,
            snapshot=snapshot,
            snapshot_hash=canonical_hash(snapshot),
            created_by_user_id=current_user.id,
        )
    )
    event = stage_outbox(
        connection=connection,
        monitor=monitor,
        event_type="monitor.update",
        payload={**snapshot, "external_id": monitor.external_id},
        idempotency_key=key,
        intention_hash=intention_hash,
    )
    db.session.commit()
    _dispatch(event)
    return jsonify(
        {"id": str(monitor.id), "version": monitor.version, "outbox_event_id": str(event.id)}
    ), 202


@bp.post("/signal-monitors/<uuid:monitor_id>/<action>")
@require_permission("signal.review")
def monitor_action(monitor_id: uuid.UUID, action: str) -> Any:
    if action not in {"pause", "resume", "sync"}:
        return problem_response(404, detail="Acción no encontrada.", code="not_found")
    monitor = db.session.scalar(
        select(SignalMonitor).where(
            SignalMonitor.id == monitor_id,
            SignalMonitor.tenant_id == g.active_tenant_id,
        )
    )
    if monitor is None:
        return problem_response(404, detail="Monitor no encontrado.", code="monitor_not_found")
    dossier = _monitor_dossier(monitor)
    if dossier is None or not dossier_accessible(
        db.session(), dossier, current_user.id, write=True
    ):
        return problem_response(404, detail="Monitor no encontrado.", code="monitor_not_found")
    key = request.headers.get("Idempotency-Key", "")
    if len(key) < 8:
        return problem_response(
            422, detail="Idempotency-Key es obligatoria.", code="validation_failed"
        )
    if action == "sync":
        job = enqueue_job(
            "oracle.signal.sync_monitor",
            payload={"monitor_id": str(monitor.id)},
            idempotency_key=key,
            requested_by_user_id=current_user.id,
            resource_type="signal_monitor",
            resource_id=monitor.id,
        )
        return jsonify({"job_id": str(job.id), "status": job.status}), 202
    connection = db.session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == monitor.connection_id,
            IntegrationConnection.tenant_id == monitor.tenant_id,
        )
    )
    if connection is None:
        return problem_response(
            409, detail="Monitor sin conexión válida.", code="monitor_connection_missing"
        )
    monitor.desired_status = "paused" if action == "pause" else "active"
    try:
        event = stage_outbox(
            connection=connection,
            monitor=monitor,
            event_type=f"monitor.{action}",
            payload={"monitor_id": str(monitor.id), "external_id": monitor.external_id},
            idempotency_key=key,
        )
    except IdempotencyConflict as exc:
        return problem_response(409, detail=str(exc), code="idempotency_conflict")
    db.session.commit()
    _dispatch(event)
    return jsonify(
        {
            "monitor_id": str(monitor.id),
            "desired_status": monitor.desired_status,
            "outbox_event_id": str(event.id),
        }
    ), 202
