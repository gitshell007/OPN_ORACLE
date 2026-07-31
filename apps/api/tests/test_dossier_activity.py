"""Unit tests for dossier activity product-state mapping (MEMSOL-04)."""

from __future__ import annotations

from types import SimpleNamespace

from opn_oracle.oracle.activity import (
    _product_state_from_job,
    _product_state_from_monitor,
    _product_state_from_procurement,
    _product_state_from_watchlist,
    _safe_error,
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
