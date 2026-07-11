"""Tenant-admin Signal connection and monitor lifecycle API."""

from __future__ import annotations

import secrets
import uuid
from typing import Any

from apiflask import APIBlueprint
from flask import g, jsonify, request
from flask_login import current_user
from sqlalchemy import select

from opn_oracle.auth.permissions import recent_auth_required, require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db
from opn_oracle.integrations.models import IntegrationOutboxEvent, SignalMonitorConfigVersion
from opn_oracle.integrations.service import (
    IdempotencyConflict,
    canonical_hash,
    lock_idempotency_key,
    stage_outbox,
    store_credential,
)
from opn_oracle.jobs.service import enqueue_job
from opn_oracle.oracle.models import SignalMonitor, StrategicDossier, Watchlist
from opn_oracle.oracle.policy import dossier_accessible
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.platform.models import IntegrationConnection

bp = APIBlueprint("signal_integrations", __name__, url_prefix="/api/v1")


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
    mode = str(payload.get("adapter_mode", "mock"))
    if mode == "http" and not (
        __import__("flask").current_app.config["SIGNAL_AVANZA_ENABLED"]
        and __import__("flask").current_app.config["SIGNAL_AVANZA_CONTRACT_CONFIRMED"]
    ):
        return problem_response(
            409,
            detail="El contrato HTTP Signal no está confirmado.",
            code="signal_contract_unconfirmed",
        )
    connection = IntegrationConnection(
        tenant_id=g.active_tenant_id,
        provider="signal-avanza",
        name=str(payload.get("name", "default"))[:100],
        status="active" if mode == "mock" else "pending",
        adapter_mode=mode,
        base_url=payload.get("base_url"),
        api_version=str(payload.get("api_version", "2026-07-01"))[:30],
        subscription_key=secrets.token_urlsafe(24),
    )
    db.session.add(connection)
    db.session.flush()
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
    append_audit_event(
        db.session,
        action="integration.signal.create",
        resource_type="integration_connection",
        resource_id=connection.id,
        result="success",
        metadata={"adapter_mode": mode},
    )
    db.session.commit()
    return jsonify(_connection_payload(connection)), 201


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
    connection.status = "disabled"
    connection.version += 1
    append_audit_event(
        db.session,
        action="integration.signal.disable",
        resource_type="integration_connection",
        resource_id=connection.id,
        result="success",
        metadata={},
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
    monitors = db.session.scalars(
        select(SignalMonitor)
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
                    "connection_id": str(item.connection_id) if item.connection_id else None,
                    "external_id": item.external_id,
                    "desired_status": item.desired_status,
                    "observed_status": item.observed_status,
                    "last_synced_at": item.last_synced_at,
                    "last_error": item.last_error,
                }
                for item in monitors
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
    query = str(payload.get("query", "")).strip()
    if not query:
        return problem_response(422, detail="query es obligatoria.", code="validation_failed")
    cadence = str(payload.get("cadence", "daily"))[:50]
    watchlist_name = str(payload.get("name", "Monitor Signal"))[:200]
    intention_hash = canonical_hash(
        {
            "operation": "monitor.create",
            "tenant_id": str(dossier.tenant_id),
            "dossier_id": str(dossier.id),
            "connection_id": str(connection.id),
            "name": watchlist_name,
            "query": query,
            "cadence": cadence,
        }
    )
    lock_idempotency_key(tenant_id=dossier.tenant_id, idempotency_key=key)
    existing_event = db.session.scalar(
        select(IntegrationOutboxEvent).where(
            IntegrationOutboxEvent.tenant_id == dossier.tenant_id,
            IntegrationOutboxEvent.idempotency_key == key,
        )
    )
    if existing_event is not None:
        if existing_event.intention_hash != intention_hash:
            return problem_response(
                409,
                detail="Idempotency-Key ya usada con otra solicitud.",
                code="idempotency_conflict",
            )
        return jsonify(
            {
                "id": str(existing_event.monitor_id),
                "outbox_event_id": str(existing_event.id),
                "duplicate": True,
            }
        ), 202
    watchlist = Watchlist(
        tenant_id=dossier.tenant_id,
        dossier_id=dossier.id,
        name=watchlist_name,
        query_config={"query": query},
        cadence=cadence,
        status="active",
    )
    db.session.add(watchlist)
    db.session.flush()
    monitor = SignalMonitor(
        tenant_id=dossier.tenant_id,
        watchlist_id=watchlist.id,
        connection_id=connection.id,
        provider="signal-avanza",
        status="active",
        desired_status="active",
        observed_status="pending",
    )
    db.session.add(monitor)
    db.session.flush()
    snapshot = {
        "oracle_monitor_id": str(monitor.id),
        "query": query,
        "status": "active",
        "cadence": watchlist.cadence,
        "source_types": ["news", "company_signal", "official_publication"],
        "oracle_watchlist_name": watchlist_name,
    }
    db.session.add(
        SignalMonitorConfigVersion(
            tenant_id=dossier.tenant_id,
            monitor_id=monitor.id,
            version=1,
            snapshot=snapshot,
            snapshot_hash=canonical_hash(snapshot),
            created_by_user_id=current_user.id,
        )
    )
    event = stage_outbox(
        connection=connection,
        monitor=monitor,
        event_type="monitor.create",
        payload=snapshot,
        idempotency_key=key,
        intention_hash=intention_hash,
    )
    db.session.commit()
    _dispatch(event)
    return jsonify({"id": str(monitor.id), "outbox_event_id": str(event.id)}), 202


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
    query = str(payload.get("query", "")).strip()
    key = request.headers.get("Idempotency-Key", "")
    if not query or len(key) < 8:
        return problem_response(
            422, detail="query e Idempotency-Key son obligatorios.", code="validation_failed"
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
    intention_hash = canonical_hash(
        {
            "operation": "monitor.update",
            "tenant_id": str(monitor.tenant_id),
            "monitor_id": str(monitor.id),
            "query": query,
            "status": monitor.desired_status,
            "cadence": watchlist.cadence,
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
    watchlist.query_config = {"query": query}
    watchlist.version += 1
    snapshot = {
        "client_monitor_id": str(monitor.id),
        "query": query,
        "status": monitor.desired_status,
        "cadence": watchlist.cadence,
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
