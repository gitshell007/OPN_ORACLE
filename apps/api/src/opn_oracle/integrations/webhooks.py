"""Public, signed Signal webhook receiver with durable encrypted inbox."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from apiflask import APIBlueprint
from flask import current_app, jsonify, request
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db, limiter
from opn_oracle.integrations.crypto import IntegrationKeyring
from opn_oracle.integrations.models import IntegrationInboxEvent
from opn_oracle.integrations.service import active_secrets
from opn_oracle.integrations.signal_avanza import verify_webhook_signature
from opn_oracle.platform.models import IntegrationConnection
from opn_oracle.tenants.context import TenantContext, tenant_context

bp = APIBlueprint("signal_webhooks", __name__, url_prefix="/api/v1")


def inbox_aad(tenant_id: uuid.UUID, connection_id: uuid.UUID, event_id: str) -> bytes:
    return f"opn-oracle|inbox|{tenant_id}|{connection_id}|{event_id}".encode()


def _resolve_subscription(subscription_key: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    if db.engine.dialect.name == "postgresql":
        row = db.session.execute(
            text("SELECT tenant_id,connection_id FROM oracle_resolve_signal_subscription(:key)"),
            {"key": subscription_key},
        ).one_or_none()
        db.session.rollback()
        return None if row is None else (row.tenant_id, row.connection_id)
    connection = db.session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.subscription_key == subscription_key,
            IntegrationConnection.provider == "signal-avanza",
            IntegrationConnection.status == "active",
        )
    )
    db.session.rollback()
    return None if connection is None else (connection.tenant_id, connection.id)


@bp.post("/integrations/signal-avanza/webhooks/v1/<subscription_key>")
@limiter.limit("120/minute")
def webhook(subscription_key: str) -> Any:
    if request.mimetype != "application/json":
        return problem_response(
            415, detail="Content-Type no permitido.", code="invalid_content_type"
        )
    maximum = current_app.config["SIGNAL_WEBHOOK_MAX_BODY_BYTES"]
    if request.content_length is not None and request.content_length > maximum:
        return problem_response(413, detail="Payload demasiado grande.", code="payload_too_large")
    raw = request.stream.read(maximum + 1)
    if len(raw) > maximum:
        return problem_response(413, detail="Payload demasiado grande.", code="payload_too_large")
    resolved = _resolve_subscription(subscription_key)
    if resolved is None:
        return problem_response(
            404, detail="Suscripción no encontrada.", code="subscription_not_found"
        )
    tenant_id, connection_id = resolved
    timestamp = request.headers.get("X-Opn-Signal-Timestamp", "")
    signature = request.headers.get("X-Opn-Signal-Signature-V2", "")
    try:
        preliminary = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return problem_response(400, detail="JSON no válido.", code="invalid_json")
    event_id = str(preliminary.get("event_id", "")) if isinstance(preliminary, dict) else ""
    if not event_id or len(event_id) > 240:
        return problem_response(400, detail="Event ID no válido.", code="invalid_event_id")
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=None)):
        connection = db.session.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.id == connection_id,
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.status == "active",
            )
        )
        if connection is None:
            return problem_response(
                404, detail="Suscripción no encontrada.", code="subscription_not_found"
            )
        secrets = active_secrets(connection, "webhook_secret")
        if not secrets or not verify_webhook_signature(
            raw_body=raw,
            timestamp=timestamp,
            signature=signature,
            secrets=secrets,
            now=datetime.now(UTC),
            tolerance_seconds=current_app.config["SIGNAL_WEBHOOK_TOLERANCE_SECONDS"],
        ):
            return problem_response(401, detail="Firma no válida.", code="invalid_signature")
        envelope = preliminary
        if not isinstance(envelope, dict) or envelope.get("event_id") != event_id:
            return problem_response(422, detail="Envelope no válido.", code="invalid_envelope")
        existing = db.session.scalar(
            select(IntegrationInboxEvent).where(
                IntegrationInboxEvent.connection_id == connection.id,
                IntegrationInboxEvent.provider_event_id == event_id,
            )
        )
        if existing is not None:
            if existing.raw_hash != hashlib.sha256(raw).digest():
                return problem_response(
                    409,
                    detail="El event ID ya existe con otro payload.",
                    code="webhook_replay_conflict",
                )
            if existing.status in {"queued", "failed"}:
                from opn_oracle.integrations.tasks import process_inbox

                process_inbox.apply_async(
                    kwargs={"inbox_id": str(existing.id), "tenant_id": str(tenant_id)},
                    queue="signals",
                )
            return jsonify({"status": "accepted", "duplicate": True}), 202
        keyring: IntegrationKeyring | None = current_app.extensions.get("integration_keyring")
        if keyring is None:
            return problem_response(
                503, detail="Cifrado no disponible.", code="encryption_unavailable"
            )
        encrypted = keyring.encrypt(
            raw.decode("utf-8"), aad=inbox_aad(tenant_id, connection.id, event_id)
        )
        inbox = IntegrationInboxEvent(
            tenant_id=tenant_id,
            connection_id=connection.id,
            provider_event_id=event_id,
            event_type=str(envelope.get("event_type", "unknown"))[:100],
            raw_ciphertext=encrypted.ciphertext,
            raw_nonce=encrypted.nonce,
            key_version=encrypted.key_version,
            raw_hash=hashlib.sha256(raw).digest(),
            safe_headers={
                "signature_version": "v2",
                "timestamp": timestamp,
            },
            status="queued",
        )
        try:
            db.session.add(inbox)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({"status": "accepted", "duplicate": True}), 202
        from opn_oracle.integrations.tasks import process_inbox

        process_inbox.apply_async(
            kwargs={"inbox_id": str(inbox.id), "tenant_id": str(tenant_id)}, queue="signals"
        )
        return jsonify({"status": "accepted", "duplicate": False}), 202
