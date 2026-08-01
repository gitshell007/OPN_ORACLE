"""MDEV-05 Oracle → Signal bilateral memory outbox (provisional, flags OFF).

Reuses IntegrationOutboxEvent. Never sends blobs/secrets/internal paths.
Default OFF: MEMORY_BILATERAL_OUTBOX_ENABLED.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select

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
