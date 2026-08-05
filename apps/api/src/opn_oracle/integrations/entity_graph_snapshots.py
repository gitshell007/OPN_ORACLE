"""Durable memory for entity-intel societal graphs.

The live ficha 360º path historically only kept a process-local TTL cache
(600s).  That means the client pays for re-queries and loses the map when the
modal closes.  This module persists the *already computed* Signal graph with a
capture timestamp so the same tenant can reopen it without recalculating, and
always labels incomplete maps (truncated / depth-capped) explicitly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

from opn_oracle.extensions import Base
from opn_oracle.platform.models import TimestampMixin, UUIDPrimaryKeyMixin

logger = logging.getLogger(__name__)

ENTITY_GRAPH_SNAPSHOT_SOURCE = "signal_live"
_MAX_LIST = 20


class EntityGraphSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entity_graph_snapshots"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_entity_graph_snapshots_id_tenant"),
        CheckConstraint(
            "entity_kind IN ('company','person')",
            name="entity_graph_snapshot_kind",
        ),
        CheckConstraint("depth BETWEEN 1 AND 2", name="entity_graph_snapshot_depth"),
        CheckConstraint(
            "completeness IN ('complete','incomplete')",
            name="entity_graph_snapshot_completeness",
        ),
        CheckConstraint("node_count >= 0", name="entity_graph_snapshot_nodes"),
        CheckConstraint("edge_count >= 0", name="entity_graph_snapshot_edges"),
        CheckConstraint(
            "octet_length(content_hash)=32",
            name="entity_graph_snapshot_hash",
        ),
        CheckConstraint(
            "jsonb_typeof(payload)='object'",
            name="entity_graph_snapshot_payload",
        ),
        CheckConstraint(
            "jsonb_typeof(incompleteness_reasons)='array'",
            name="entity_graph_snapshot_reasons",
        ),
        Index(
            "ix_entity_graph_snapshots_lookup",
            "tenant_id",
            "normalized_name",
            "entity_kind",
            "captured_at",
        ),
        Index("ix_entity_graph_snapshots_hash", "tenant_id", "content_hash"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    entity_name: Mapped[str] = mapped_column(String(300), nullable=False)
    entity_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    active_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completeness: Mapped[str] = mapped_column(String(20), nullable=False)
    incompleteness_reasons: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, default=ENTITY_GRAPH_SNAPSHOT_SOURCE
    )


ENTITY_GRAPH_SNAPSHOT_MODELS = (EntityGraphSnapshot,)


def normalize_entity_graph_name(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name.strip())
    without_marks = "".join(char for char in folded if not unicodedata.combining(char))
    collapsed = re.sub(r"\s+", " ", without_marks).strip().casefold()
    return collapsed[:300]


def graph_completeness(
    payload: Mapping[str, Any],
    *,
    depth: int,
    max_depth_cap: int = 2,
) -> tuple[str, list[str]]:
    """Return (complete|incomplete, reasons). Never invents a full map."""

    reasons: list[str] = []
    truncated = bool(payload.get("truncated"))
    if truncated:
        reasons.append("signal_truncated_max_nodes_or_budget")
    if depth >= max_depth_cap:
        reasons.append(f"depth_capped_at_{max_depth_cap}_api_and_provider_default")
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or len(nodes) == 0:
        reasons.append("empty_graph")
    note = payload.get("note")
    if isinstance(note, str) and note.strip():
        # Provider notes often explain partial coverage; surface them as reason keys.
        reasons.append("provider_note_present")
    if reasons:
        # depth_capped alone is informational when the graph is full at that depth.
        # Only treat as incomplete when truncated, empty, or a provider note is set.
        depth_reason = f"depth_capped_at_{max_depth_cap}_api_and_provider_default"
        hard = [reason for reason in reasons if reason != depth_reason]
        if hard:
            return "incomplete", reasons
        # Full graph at the hard depth cap is still complete *for that depth*, but we
        # keep the depth_capped reason so the UI can say expansion beyond is blocked.
        return "complete", reasons
    return "complete", []


def _canonical_graph_bytes(payload: Mapping[str, Any], *, depth: int, active_only: bool) -> bytes:
    raw_nodes = payload.get("nodes")
    raw_edges = payload.get("edges")
    body: dict[str, Any] = {
        "center": payload.get("center"),
        "nodes": raw_nodes if isinstance(raw_nodes, list) else [],
        "edges": raw_edges if isinstance(raw_edges, list) else [],
        "truncated": bool(payload.get("truncated")),
        "note": payload.get("note") if isinstance(payload.get("note"), str) else None,
        "depth": depth,
        "active_only": active_only,
    }
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def content_hash_for_graph(payload: Mapping[str, Any], *, depth: int, active_only: bool) -> bytes:
    return hashlib.sha256(
        _canonical_graph_bytes(payload, depth=depth, active_only=active_only)
    ).digest()


def annotate_graph_payload(
    payload: Mapping[str, Any],
    *,
    depth: int,
    captured_at: datetime | None = None,
    snapshot_id: str | None = None,
    origin: str = "live",
) -> dict[str, Any]:
    completeness, reasons = graph_completeness(payload, depth=depth)
    now = captured_at or datetime.now(UTC)
    annotated = dict(payload)
    annotated["completeness"] = completeness
    annotated["incompleteness_reasons"] = reasons
    annotated["captured_at"] = now.isoformat()
    annotated["graph_origin"] = origin
    annotated["requested_depth"] = depth
    if snapshot_id is not None:
        annotated["snapshot_id"] = snapshot_id
    if completeness == "incomplete":
        existing_note = annotated.get("note") if isinstance(annotated.get("note"), str) else None
        incomplete_banner = (
            "Grafo incompleto: no representa el mapa societario completo. "
            "Motivos: " + ", ".join(reasons) + "."
        )
        if existing_note:
            annotated["note"] = f"{existing_note} {incomplete_banner}"
        else:
            annotated["note"] = incomplete_banner
    return annotated


def persist_entity_graph_snapshot(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    entity_name: str,
    entity_kind: str,
    depth: int,
    active_only: bool,
    payload: Mapping[str, Any],
) -> EntityGraphSnapshot | None:
    """Insert a snapshot row. Returns None when persistence is unavailable."""

    raw_nodes = payload.get("nodes")
    raw_edges = payload.get("edges")
    nodes: list[Any] = raw_nodes if isinstance(raw_nodes, list) else []
    edges: list[Any] = raw_edges if isinstance(raw_edges, list) else []
    completeness, reasons = graph_completeness(payload, depth=depth)
    digest = content_hash_for_graph(payload, depth=depth, active_only=active_only)
    captured_at = datetime.now(UTC)
    # Dedup identical content for the same tenant+name+depth within the same hash.
    existing = session.scalar(
        select(EntityGraphSnapshot).where(
            EntityGraphSnapshot.tenant_id == tenant_id,
            EntityGraphSnapshot.normalized_name == normalize_entity_graph_name(entity_name),
            EntityGraphSnapshot.entity_kind == entity_kind,
            EntityGraphSnapshot.depth == depth,
            EntityGraphSnapshot.active_only == active_only,
            EntityGraphSnapshot.content_hash == digest,
        )
    )
    if existing is not None:
        # Refresh captured_at so "last seen" advances without duplicating rows.
        existing.captured_at = captured_at
        existing.updated_at = captured_at
        session.flush()
        return cast(EntityGraphSnapshot | None, existing)

    store_nodes: list[dict[Any, Any]] = [item for item in nodes if isinstance(item, dict)]
    store_edges: list[dict[Any, Any]] = [item for item in edges if isinstance(item, dict)]
    store_payload: dict[str, Any] = {
        "center": payload.get("center"),
        "nodes": store_nodes,
        "edges": store_edges,
        "truncated": bool(payload.get("truncated")),
        "note": payload.get("note") if isinstance(payload.get("note"), str) else None,
    }
    row = EntityGraphSnapshot(
        tenant_id=tenant_id,
        entity_name=entity_name.strip()[:300],
        entity_kind=entity_kind,
        normalized_name=normalize_entity_graph_name(entity_name),
        depth=depth,
        active_only=active_only,
        truncated=bool(payload.get("truncated")),
        completeness=completeness,
        incompleteness_reasons=list(reasons),
        node_count=len(store_payload["nodes"]),
        edge_count=len(store_payload["edges"]),
        captured_at=captured_at,
        content_hash=digest,
        payload=store_payload,
        source=ENTITY_GRAPH_SNAPSHOT_SOURCE,
    )
    session.add(row)
    session.flush()
    return row


def try_persist_entity_graph_snapshot(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    entity_name: str,
    entity_kind: str,
    depth: int,
    active_only: bool,
    payload: Mapping[str, Any],
) -> EntityGraphSnapshot | None:
    """Best-effort persist: never fails the live graph response."""

    try:
        row = persist_entity_graph_snapshot(
            session,
            tenant_id=tenant_id,
            entity_name=entity_name,
            entity_kind=entity_kind,
            depth=depth,
            active_only=active_only,
            payload=payload,
        )
        session.commit()
        return row
    except SQLAlchemyError:
        logger.exception(
            "entity_graph_snapshot_persist_failed tenant=%s name=%s",
            tenant_id,
            entity_name[:80],
        )
        try:
            session.rollback()
        except SQLAlchemyError:
            logger.exception("entity_graph_snapshot_rollback_failed")
        return None


def list_entity_graph_snapshots(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    entity_name: str,
    entity_kind: str,
    limit: int = 10,
) -> list[EntityGraphSnapshot]:
    capped = max(1, min(limit, _MAX_LIST))
    return list(
        session.scalars(
            select(EntityGraphSnapshot)
            .where(
                EntityGraphSnapshot.tenant_id == tenant_id,
                EntityGraphSnapshot.normalized_name == normalize_entity_graph_name(entity_name),
                EntityGraphSnapshot.entity_kind == entity_kind,
            )
            .order_by(EntityGraphSnapshot.captured_at.desc())
            .limit(capped)
        )
    )


def get_entity_graph_snapshot(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    snapshot_id: uuid.UUID,
) -> EntityGraphSnapshot | None:
    return cast(
        EntityGraphSnapshot | None,
        session.scalar(
            select(EntityGraphSnapshot).where(
                EntityGraphSnapshot.id == snapshot_id,
                EntityGraphSnapshot.tenant_id == tenant_id,
            )
        ),
    )


def serialize_snapshot_meta(row: EntityGraphSnapshot) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "entity_name": row.entity_name,
        "entity_kind": row.entity_kind,
        "depth": row.depth,
        "active_only": row.active_only,
        "truncated": row.truncated,
        "completeness": row.completeness,
        "incompleteness_reasons": list(row.incompleteness_reasons or []),
        "node_count": row.node_count,
        "edge_count": row.edge_count,
        "captured_at": row.captured_at.isoformat(),
        "source": row.source,
    }


def serialize_snapshot_payload(row: EntityGraphSnapshot) -> dict[str, Any]:
    payload = dict(row.payload or {})
    payload.setdefault("nodes", [])
    payload.setdefault("edges", [])
    payload.setdefault("truncated", row.truncated)
    annotated = annotate_graph_payload(
        payload,
        depth=row.depth,
        captured_at=row.captured_at,
        snapshot_id=str(row.id),
        origin="snapshot",
    )
    annotated["cached_seconds"] = 0
    annotated["cache_hit"] = False
    return annotated
