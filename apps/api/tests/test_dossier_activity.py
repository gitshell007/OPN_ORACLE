"""Unit tests for dossier activity product-state mapping (MEMSOL-04)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from opn_oracle.oracle.activity import (
    _product_state_from_job,
    _product_state_from_monitor,
    _product_state_from_procurement,
    _product_state_from_watchlist,
    _safe_error,
    assess_collection_honesty,
)


def test_monitor_error_is_needs_attention() -> None:
    monitor = SimpleNamespace(
        observed_status="active",
        status="error",
        desired_status="active",
        last_error="timeout",
    )
    assert _product_state_from_monitor(monitor) == "needs_attention"


def test_monitor_paused() -> None:
    monitor = SimpleNamespace(
        observed_status="paused",
        status="paused",
        desired_status="paused",
        last_error=None,
    )
    assert _product_state_from_monitor(monitor) == "paused"


def test_watchlist_requires_review_is_prepared() -> None:
    watchlist = SimpleNamespace(status="active", query_config={"requires_review": True})
    assert _product_state_from_watchlist(watchlist) == "prepared"


def test_procurement_error_and_disabled() -> None:
    bad = SimpleNamespace(deleted_at=None, last_error_code="x", enabled=True)
    assert _product_state_from_procurement(bad) == "needs_attention"
    paused = SimpleNamespace(deleted_at=None, last_error_code=None, enabled=False)
    assert _product_state_from_procurement(paused) == "paused"


def test_job_states() -> None:
    assert _product_state_from_job(SimpleNamespace(status="queued")) == "pending"
    assert _product_state_from_job(SimpleNamespace(status="running")) == "running"
    assert _product_state_from_job(SimpleNamespace(status="failed")) == "needs_attention"


def test_safe_error_truncates() -> None:
    assert _safe_error(None) is None
    assert _safe_error("  a  b  ") == "a b"
    long = "x" * 500
    assert len(_safe_error(long, limit=10) or "") == 10


# --- SV2-VIGILANCIA-VERDAD: three collection states from Signal health fields ---


def test_collection_absent_without_monitor() -> None:
    h = assess_collection_honesty(has_monitor=False, snapshot=None, snapshot_available=False)
    assert h.collection_state == "absent"
    assert h.degraded is True
    assert h.degraded_reason is not None
    assert "SIGNAL-MONITOR-ABSENT" in h.degraded_reason


def test_collection_not_collecting_when_last_run_null() -> None:
    """Monitor exists, health ok, but never ran → not green active."""
    h = assess_collection_honesty(
        has_monitor=True,
        snapshot_available=True,
        snapshot={
            "status": "active",
            "last_run_at": None,
            "health": {"state": "ok", "last_error_code": None},
        },
    )
    assert h.collection_state == "not_collecting"
    assert h.degraded is True
    assert h.provider_last_run_at is None
    assert h.provider_health_state == "ok"
    assert h.degraded_reason is not None
    assert "SIGNAL-COLLECTION-NEVER" in h.degraded_reason


def test_collection_not_collecting_when_health_degraded() -> None:
    h = assess_collection_honesty(
        has_monitor=True,
        snapshot_available=True,
        snapshot={
            "status": "active",
            "last_run_at": datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
            "health": {
                "state": "degraded",
                "last_error_code": "skipped_all_targets_disabled",
            },
        },
    )
    assert h.collection_state == "not_collecting"
    assert h.degraded is True
    assert "SIGNAL-COLLECTION-UNHEALTHY" in (h.degraded_reason or "")
    assert h.provider_health_error_code == "skipped_all_targets_disabled"


def test_collection_collecting_when_last_run_and_health_ok() -> None:
    h = assess_collection_honesty(
        has_monitor=True,
        snapshot_available=True,
        snapshot={
            "status": "active",
            "last_run_at": "2026-08-03T12:00:00+00:00",
            "health": {"state": "ok", "last_error_code": None},
        },
    )
    assert h.collection_state == "collecting"
    assert h.degraded is False
    assert h.degraded_reason is None
    assert h.provider_last_run_at == "2026-08-03T12:00:00+00:00"


def test_collection_unknown_when_signal_unreachable() -> None:
    h = assess_collection_honesty(has_monitor=True, snapshot=None, snapshot_available=False)
    assert h.collection_state == "unknown"
    assert h.degraded is True
    assert "SIGNAL-COLLECTION-UNKNOWN" in (h.degraded_reason or "")


def test_collection_unknown_when_health_state_missing() -> None:
    """Do not invent health: missing state → unknown, never clean active."""
    h = assess_collection_honesty(
        has_monitor=True,
        snapshot_available=True,
        snapshot={"status": "active", "last_run_at": None, "health": {}},
    )
    assert h.collection_state == "unknown"
    assert h.degraded is True


def test_regression_monitor_without_collection_is_not_clean_active() -> None:
    """Third return of the bug: monitor present + no collection must not map to active."""
    h = assess_collection_honesty(
        has_monitor=True,
        snapshot_available=True,
        snapshot={
            "status": "active",
            "last_run_at": None,
            "health": {"state": "ok"},
        },
    )
    # product_state mapping rule used by activity read model
    product_state = "active"
    if product_state == "active" and h.collection_state != "collecting":
        product_state = "needs_attention"
    assert product_state == "needs_attention"
    assert h.collection_state != "collecting"
    assert h.degraded is True
