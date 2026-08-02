"""MDEV-05 Oracle → Signal bilateral memory outbox (provisional, flags OFF).

Reuses IntegrationOutboxEvent. Never sends blobs/secrets/internal paths.
Default OFF: MEMORY_BILATERAL_OUTBOX_ENABLED.

SV2-BRIDGE: document.ready stages document.version.ready envelopes; publisher
dispatches via oracle.signal.dispatch_outbox (memory.bilateral.* branch).
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from opn_oracle.extensions import db
from opn_oracle.integrations.models import IntegrationOutboxEvent
from opn_oracle.integrations.service import stage_outbox
from opn_oracle.platform.models import IntegrationConnection

MemoryEventType = Literal[
    "scope.dossier.upsert",
    "intent.revision.accepted",
    "intent.revision.superseded",
    "document.version.ready",
    "evidence.snapshot.update",
    "memory.tombstone",
]

EVENT_TYPES: frozenset[str] = frozenset(
    {
        "scope.dossier.upsert",
        "intent.revision.accepted",
        "intent.revision.superseded",
        "document.version.ready",
        "evidence.snapshot.update",
        "memory.tombstone",
    }
)

FLAG = "MEMORY_BILATERAL_OUTBOX_ENABLED"
MAX_TEXT = 8000
MAX_ITEMS = 50


def bilateral_outbox_enabled(env: dict[str, str] | None = None) -> bool:
    src = env if env is not None else os.environ
    return str(src.get(FLAG, "0")).strip().lower() in {"1", "true", "yes", "on"}


def _sha(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_envelope(
    *,
    event_type: MemoryEventType,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    external_tenant_id: str,
    items: list[dict[str, Any]] | None = None,
    intent_revision_id: str | None = None,
    requirement_ids: list[str] | None = None,
    classification: str = "internal",
    correlation_id: str | None = None,
    idempotency_key: str | None = None,
    tombstone_origin_id: str | None = None,
) -> dict[str, Any]:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unsupported event_type: {event_type}")
    clean_items: list[dict[str, Any]] = []
    for it in (items or [])[:MAX_ITEMS]:
        text = str(it.get("text") or it.get("content") or "")[:MAX_TEXT]
        origin_id = str(it.get("origin_id") or it.get("id") or uuid.uuid4())
        # never include path, blob, secret
        for banned in ("blob", "path", "secret", "token", "api_key", "password"):
            if banned in it:
                raise ValueError(f"forbidden field in item: {banned}")
        clean_items.append(
            {
                "origin_id": origin_id,
                "title": str(it.get("title") or "")[:300],
                "text": text,
                "checksum": str(it.get("checksum") or _sha({"o": origin_id, "t": text})),
                "kind": str(it.get("kind") or "chunk")[:40],
                "parser_version": str(it.get("parser_version") or "parser.v1"),
                "chunker_version": str(it.get("chunker_version") or "chunker.v1"),
                "locator": str(it.get("locator") or f"oracle://doc/{origin_id}")[:200],
            }
        )
    corr = correlation_id or f"ora_mem_{uuid.uuid4().hex[:16]}"
    idem = idempotency_key or f"{event_type}:{dossier_id}:{_sha(clean_items)[:24]}"
    envelope = {
        "api_version": "memory.v1",
        "event_type": event_type,
        "schema_version": "bilateral_ingest.v1",
        "tenant_id": str(tenant_id),
        "dossier_id": str(dossier_id),
        "external_tenant_id": str(external_tenant_id),
        "classification": classification,
        "correlation_id": corr,
        "idempotency_key": idem,
        "intent_revision_id": intent_revision_id,
        "requirement_ids": list(requirement_ids or [])[:20],
        "items": clean_items,
        "tombstone_origin_id": tombstone_origin_id,
        "created_at": datetime.now(UTC).isoformat(),
        "checksum": _sha(
            {
                "event_type": event_type,
                "dossier_id": str(dossier_id),
                "items": clean_items,
                "tombstone": tombstone_origin_id,
            }
        ),
        # honest debt markers (never claim publisher reliable)
        "publisher_degraded": True,
        "memory_profile_degraded": True,
    }
    return envelope


def stage_memory_event(
    *,
    connection: IntegrationConnection,
    event_type: MemoryEventType,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    external_tenant_id: str,
    items: list[dict[str, Any]] | None = None,
    intent_revision_id: str | None = None,
    requirement_ids: list[str] | None = None,
    classification: str = "internal",
    correlation_id: str | None = None,
    idempotency_key: str | None = None,
    tombstone_origin_id: str | None = None,
    force: bool = False,
) -> IntegrationOutboxEvent | dict[str, Any]:
    """Stage durable outbox event. If flag OFF and not force, return disabled status."""
    if not force and not bilateral_outbox_enabled():
        return {
            "status": "disabled",
            "ok": False,
            "error_code": "bilateral_outbox_disabled",
            "flag": FLAG,
            "event_type": event_type,
        }
    envelope = build_envelope(
        event_type=event_type,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        external_tenant_id=external_tenant_id,
        items=items,
        intent_revision_id=intent_revision_id,
        requirement_ids=requirement_ids,
        classification=classification,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        tombstone_origin_id=tombstone_origin_id,
    )
    # payload for outbox is the envelope destined to Signal /memory/v1/ingest/bilateral
    return stage_outbox(
        connection=connection,
        monitor=None,
        event_type=f"memory.bilateral.{event_type}",
        payload={
            "target_path": "/api/v1/memory/v1/ingest/bilateral",
            "envelope": envelope,
            # no secrets
        },
        idempotency_key=envelope["idempotency_key"],
        correlation_id=envelope["correlation_id"],
    )


def list_memory_outbox_safe(
    *, tenant_id: uuid.UUID, dossier_id: uuid.UUID | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Public activity view: status/error/retry only — never raw sensitive payload text."""
    q = select(IntegrationOutboxEvent).where(
        IntegrationOutboxEvent.tenant_id == tenant_id,
        IntegrationOutboxEvent.event_type.like("memory.bilateral.%"),
    )
    rows = db.session.scalars(
        q.order_by(IntegrationOutboxEvent.created_at.desc()).limit(limit)
    ).all()
    out: list[dict[str, Any]] = []
    for row in rows:
        payload: dict[str, Any] = row.payload if isinstance(row.payload, dict) else {}
        raw_env = payload.get("envelope")
        env: dict[str, Any] = raw_env if isinstance(raw_env, dict) else {}
        if dossier_id is not None and str(env.get("dossier_id")) != str(dossier_id):
            continue
        last_err = row.last_error
        safe_err = last_err[:300] if isinstance(last_err, str) else None
        out.append(
            {
                "id": str(row.id),
                "event_type": row.event_type,
                "status": row.status,
                "attempts": row.attempts,
                "max_attempts": row.max_attempts,
                "next_attempt_at": (
                    row.next_attempt_at.isoformat() if row.next_attempt_at else None
                ),
                "last_error": safe_err,
                "correlation_id": row.correlation_id,
                "idempotency_key": row.idempotency_key,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                # safe metadata only
                "envelope_event_type": env.get("event_type"),
                "dossier_id": env.get("dossier_id"),
                "item_count": len(env.get("items") or []),
                "checksum": env.get("checksum"),
                "publisher_degraded": True,
            }
        )
    return out


def resolve_memory_connection_for_tenant(
    session: Session, *, tenant_id: uuid.UUID
) -> IntegrationConnection | None:
    """Active signal-avanza http/mock connection for bilateral publish (single preferred)."""
    rows = list(
        session.scalars(
            select(IntegrationConnection).where(
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.provider == "signal-avanza",
                IntegrationConnection.status == "active",
            )
        ).all()
    )
    if not rows:
        return None
    # Prefer http adapter when multiple
    http_rows = [r for r in rows if str(r.adapter_mode or "") == "http"]
    pool = http_rows or rows
    return pool[0]


def external_tenant_from_connection(connection: IntegrationConnection) -> str:
    meta = (
        connection.connection_metadata
        if isinstance(getattr(connection, "connection_metadata", None), dict)
        else {}
    )
    return str(
        meta.get("external_tenant_id")
        or meta.get("signal_external_tenant_id")
        or connection.tenant_id
        or ""
    ).strip()


def items_from_document_chunks(
    chunks: list[Any],
    *,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    title: str = "",
    parser_version: str = "parser.v1",
    chunker_version: str = "chunker.v1",
) -> list[dict[str, Any]]:
    """Map DocumentChunk rows → bilateral envelope items (no paths/blobs/secrets)."""
    items: list[dict[str, Any]] = []
    for ch in chunks[:MAX_ITEMS]:
        text = str(getattr(ch, "text_content", None) or getattr(ch, "text", None) or "")[
            :MAX_TEXT
        ]
        origin = str(getattr(ch, "id", None) or f"{document_id}:{getattr(ch, 'sequence', 0)}")
        locator_obj = getattr(ch, "locator", None)
        if isinstance(locator_obj, dict):
            locator = (
                f"oracle://doc/{document_id}/v/{version_id}/seq/{getattr(ch, 'sequence', 0)}"
            )
        else:
            locator = f"oracle://doc/{document_id}/v/{version_id}/seq/{getattr(ch, 'sequence', 0)}"
        items.append(
            {
                "origin_id": origin,
                "title": (title or f"document {document_id}")[:300],
                "text": text,
                "checksum": str(getattr(ch, "checksum", None) or _sha({"o": origin, "t": text})),
                "kind": "chunk",
                "parser_version": parser_version[:40],
                "chunker_version": chunker_version[:40],
                "locator": locator[:200],
                "source_type": "document",
            }
        )
    if not items:
        # Still stage a document-level item so Signal receives an envelope
        origin = f"{document_id}:{version_id}"
        items.append(
            {
                "origin_id": origin,
                "title": (title or f"document {document_id}")[:300],
                "text": f"document_ready document_id={document_id} version_id={version_id}",
                "checksum": _sha({"o": origin}),
                "kind": "document",
                "parser_version": parser_version[:40],
                "chunker_version": chunker_version[:40],
                "locator": f"oracle://doc/{document_id}/v/{version_id}"[:200],
                "source_type": "document",
            }
        )
    return items


def stage_document_ready_memory(
    *,
    session: Session,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    chunks: list[Any],
    title: str = "",
    classification: str = "internal",
    parser_version: str = "parser.v1",
    chunker_version: str = "chunker.v1",
    connection: IntegrationConnection | None = None,
) -> IntegrationOutboxEvent | dict[str, Any]:
    """Pre-commit stage of document.version.ready. No-op dict when flag OFF / no IC."""
    if not bilateral_outbox_enabled():
        return {
            "status": "disabled",
            "ok": False,
            "error_code": "bilateral_outbox_disabled",
            "flag": FLAG,
            "event_type": "document.version.ready",
        }
    conn = connection or resolve_memory_connection_for_tenant(session, tenant_id=tenant_id)
    if conn is None:
        return {
            "status": "skipped",
            "ok": False,
            "error_code": "connection_missing",
            "event_type": "document.version.ready",
        }
    external = external_tenant_from_connection(conn)
    if not external:
        return {
            "status": "skipped",
            "ok": False,
            "error_code": "external_tenant_missing",
            "event_type": "document.version.ready",
        }
    items = items_from_document_chunks(
        chunks,
        document_id=document_id,
        version_id=version_id,
        title=title,
        parser_version=parser_version,
        chunker_version=chunker_version,
    )
    # Idempotency: one publish per document version (reprocess = new version_id)
    idem = f"document.version.ready:{document_id}:{version_id}"
    return stage_memory_event(
        connection=conn,
        event_type="document.version.ready",
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        external_tenant_id=external,
        items=items,
        classification=classification,
        idempotency_key=idem,
        correlation_id=f"ora_doc_{document_id.hex[:12]}_{version_id.hex[:8]}",
    )


def dispatch_memory_outbox_event(event: IntegrationOutboxEvent) -> None:
    """Post-commit publish for a staged memory bilateral outbox row."""
    from opn_oracle.integrations.tasks import dispatch_outbox

    dispatch_outbox.apply_async(
        kwargs={"event_id": str(event.id), "tenant_id": str(event.tenant_id)},
        queue="signals",
    )


def publish_memory_bilateral_envelope(
    *,
    connection: IntegrationConnection,
    envelope: dict[str, Any],
    target_path: str = "/api/v1/memory/v1/ingest/bilateral",
    durable_path: str = "/api/v1/memory/v1/ingest",
    dual_write_durable: bool = True,
) -> dict[str, Any]:
    """HTTP publish of staged envelope using IC credential (keyring via memory_profile).

    Primary: bilateral contract path.
    Dual-write: durable /ingest so retrieve/extract see real rows (Signal bilateral is
    provisional in-process store; durable path materializes sources/chunks/jobs).
    """
    from opn_oracle.integrations.memory_http_client import HttpxTransport, MemoryHttpError
    from opn_oracle.integrations.memory_profile import build_client_for_connection
    from opn_oracle.integrations.signal_avanza import SignalTemporaryError

    transport = HttpxTransport()
    client = build_client_for_connection(connection, transport=transport, require_https=True)
    external = str(envelope.get("external_tenant_id") or external_tenant_from_connection(connection))
    dossier_id = str(envelope.get("dossier_id") or "")
    corr = str(envelope.get("correlation_id") or "")
    idem = str(envelope.get("idempotency_key") or "")

    results: dict[str, Any] = {"bilateral": None, "durable": None}

    # 1) Durable materialization first (sources/chunks/extract jobs in Signal BD).
    if dual_write_durable:
        durable_body = {
            "dossier_id": dossier_id,
            "items": [
                {
                    "origin_id": it.get("origin_id"),
                    "title": it.get("title"),
                    "text": it.get("text"),
                    "checksum": it.get("checksum"),
                    "kind": it.get("kind") or "chunk",
                    "source_type": it.get("source_type") or "document",
                }
                for it in (envelope.get("items") or [])
                if isinstance(it, dict)
            ],
        }
        try:
            d_status, d_body = client.post_json(
                durable_path,
                external_tenant_id=external,
                dossier_id=dossier_id or None,
                body=durable_body,
                correlation_id=corr or None,
                idempotency_key=f"durable:{idem}" if idem else None,
            )
            results["durable"] = {
                "http_status": d_status,
                "ok": True,
                "accepted": d_body.get("accepted"),
                "status": d_body.get("status"),
            }
        except MemoryHttpError as exc:
            results["durable"] = {
                "http_status": exc.http_status,
                "ok": False,
                "error_code": exc.code,
                "retryable": exc.retryable,
            }
            if exc.retryable:
                raise SignalTemporaryError(f"durable ingest temporary: {exc.code}") from exc
            raise

    # 2) Bilateral contract path (provisional in-process on Signal; flags may be OFF).
    try:
        b_status, b_body = client.post_json(
            target_path,
            external_tenant_id=external,
            dossier_id=dossier_id or None,
            body=envelope,
            correlation_id=corr or None,
            idempotency_key=idem or None,
        )
        results["bilateral"] = {
            "http_status": b_status,
            "ok": True,
            "body_keys": list(b_body.keys()),
        }
    except MemoryHttpError as exc:
        results["bilateral"] = {
            "http_status": exc.http_status,
            "ok": False,
            "error_code": exc.code,
            "retryable": exc.retryable,
        }
        # If durable already succeeded, treat bilateral flag-OFF as soft debt (not fail outbox).
        durable_ok = bool((results.get("durable") or {}).get("ok"))
        if durable_ok:
            pass
        elif exc.retryable:
            raise SignalTemporaryError(f"bilateral publish temporary: {exc.code}") from exc
        else:
            raise

    bilateral_ok = bool((results.get("bilateral") or {}).get("ok"))
    durable_ok = bool((results.get("durable") or {}).get("ok")) if dual_write_durable else True
    if dual_write_durable and durable_ok:
        return {
            "status": "delivered",
            "paths": results,
            "primary": "durable",
            "bilateral_soft_fail": not bilateral_ok,
        }
    if bilateral_ok:
        return {"status": "delivered", "paths": results, "primary": "bilateral"}
    raise SignalTemporaryError("memory publish incomplete")
