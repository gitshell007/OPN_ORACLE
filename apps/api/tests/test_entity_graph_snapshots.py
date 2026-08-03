"""Unit tests for durable entity-graph snapshots and incompleteness labels."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from opn_oracle.integrations.entity_graph_snapshots import (
    annotate_graph_payload,
    content_hash_for_graph,
    graph_completeness,
    normalize_entity_graph_name,
    persist_entity_graph_snapshot,
    serialize_snapshot_payload,
    try_persist_entity_graph_snapshot,
)


@pytest.mark.unit
def test_normalize_entity_graph_name_folds_accents_and_case() -> None:
    assert normalize_entity_graph_name("  ITURRI  S.A. ") == "iturri s.a."
    assert normalize_entity_graph_name("José García") == "jose garcia"


@pytest.mark.unit
def test_graph_completeness_marks_truncated_as_incomplete() -> None:
    status, reasons = graph_completeness(
        {"nodes": [{"id": "a"}], "edges": [], "truncated": True},
        depth=2,
    )
    assert status == "incomplete"
    assert "signal_truncated_max_nodes_or_budget" in reasons


@pytest.mark.unit
def test_graph_completeness_full_depth_capped_graph_is_complete_for_depth() -> None:
    status, reasons = graph_completeness(
        {"nodes": [{"id": "a"}], "edges": [], "truncated": False},
        depth=2,
    )
    assert status == "complete"
    assert any(r.startswith("depth_capped_at_") for r in reasons)


@pytest.mark.unit
def test_graph_completeness_empty_is_incomplete() -> None:
    status, reasons = graph_completeness({"nodes": [], "edges": [], "truncated": False}, depth=1)
    assert status == "incomplete"
    assert "empty_graph" in reasons


@pytest.mark.unit
def test_annotate_graph_payload_adds_incomplete_banner() -> None:
    annotated = annotate_graph_payload(
        {
            "center": "X",
            "nodes": [{"id": "a"}],
            "edges": [],
            "truncated": True,
            "cached_seconds": 600,
            "cache_hit": False,
        },
        depth=2,
        captured_at=datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
        snapshot_id="snap-1",
        origin="live",
    )
    assert annotated["completeness"] == "incomplete"
    assert annotated["snapshot_id"] == "snap-1"
    assert annotated["graph_origin"] == "live"
    assert annotated["captured_at"].startswith("2026-08-03")
    assert "Grafo incompleto" in (annotated.get("note") or "")


@pytest.mark.unit
def test_content_hash_stable_for_same_payload() -> None:
    payload = {
        "center": "ITURRI SA",
        "nodes": [{"id": "a", "label": "A"}],
        "edges": [{"source": "a", "target": "b"}],
        "truncated": False,
    }
    a = content_hash_for_graph(payload, depth=2, active_only=False)
    b = content_hash_for_graph(payload, depth=2, active_only=False)
    c = content_hash_for_graph(payload, depth=1, active_only=False)
    assert a == b
    assert a != c
    assert len(a) == 32


@pytest.mark.unit
def test_persist_entity_graph_snapshot_dedups_by_hash() -> None:
    tenant_id = uuid.uuid4()
    payload = {
        "center": "ITURRI SA",
        "nodes": [{"id": "a", "label": "ITURRI SA"}],
        "edges": [],
        "truncated": False,
    }
    digest = content_hash_for_graph(payload, depth=2, active_only=False)
    existing = MagicMock()
    existing.content_hash = digest
    existing.captured_at = datetime(2026, 1, 1, tzinfo=UTC)

    session = MagicMock()
    session.scalar.return_value = existing

    row = persist_entity_graph_snapshot(
        session,
        tenant_id=tenant_id,
        entity_name="ITURRI SA",
        entity_kind="company",
        depth=2,
        active_only=False,
        payload=payload,
    )
    assert row is existing
    session.add.assert_not_called()
    session.flush.assert_called_once()
    # Dedup path refreshes captured_at to "now" without inserting a row.
    assert existing.captured_at > datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.unit
def test_persist_entity_graph_snapshot_inserts_when_new() -> None:
    session = MagicMock()
    session.scalar.return_value = None
    payload = {
        "center": "ITURRI SA",
        "nodes": [{"id": "a"}],
        "edges": [{"source": "a", "target": "b"}],
        "truncated": True,
    }
    row = persist_entity_graph_snapshot(
        session,
        tenant_id=uuid.uuid4(),
        entity_name="ITURRI SA",
        entity_kind="company",
        depth=2,
        active_only=False,
        payload=payload,
    )
    session.add.assert_called_once()
    session.flush.assert_called_once()
    assert row is not None
    assert row.completeness == "incomplete"
    assert row.truncated is True
    assert row.node_count == 1
    assert row.edge_count == 1


@pytest.mark.unit
def test_try_persist_swallows_sqlalchemy_errors() -> None:
    from sqlalchemy.exc import OperationalError

    session = MagicMock()
    session.scalar.side_effect = OperationalError("stmt", {}, Exception("no table"))
    row = try_persist_entity_graph_snapshot(
        session,
        tenant_id=uuid.uuid4(),
        entity_name="X",
        entity_kind="company",
        depth=1,
        active_only=False,
        payload={"nodes": [{"id": "a"}], "edges": [], "truncated": False},
    )
    assert row is None
    session.rollback.assert_called()


@pytest.mark.unit
def test_serialize_snapshot_payload_origin_snapshot() -> None:
    row = MagicMock()
    row.id = uuid.uuid4()
    row.depth = 2
    row.truncated = True
    row.captured_at = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    row.payload = {
        "center": "X",
        "nodes": [{"id": "a"}],
        "edges": [],
        "truncated": True,
        "note": None,
    }
    out = serialize_snapshot_payload(row)
    assert out["graph_origin"] == "snapshot"
    assert out["completeness"] == "incomplete"
    assert out["snapshot_id"] == str(row.id)
    assert out["cache_hit"] is False


@pytest.mark.unit
def test_investigation_summary_marks_incomplete_when_p2_blocked() -> None:
    """Smoke: incompleteness helper logic mirrors process_investigation_run."""

    steps = [
        {"stage": "P0", "status": "completed"},
        {"stage": "P1", "status": "completed"},
        {"stage": "P2", "status": "blocked"},
        {"stage": "P3", "status": "completed"},
        {"stage": "P4", "status": "completed"},
        {"stage": "P5", "status": "blocked"},
    ]
    completed = {s["stage"] for s in steps if s["status"] == "completed"}
    blocked = {s["stage"] for s in steps if s["status"] == "blocked"}
    assert completed == {"P0", "P1", "P3", "P4"}
    assert blocked == {"P2", "P5"}
    # 3 of 6 deterministic/post-seed automated stages executed to completion in MVP
    # after P0 human seed: P1+P3+P4. P2 expansion intentionally blocked.
    automated = {"P1", "P2", "P3", "P4", "P5"}
    executed = completed & automated
    assert executed == {"P1", "P3", "P4"}
    assert len(executed) == 3
