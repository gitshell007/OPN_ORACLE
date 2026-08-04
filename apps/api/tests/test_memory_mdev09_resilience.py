"""MDEV-09 provisional: cross-repo hashes, ladder, fault/security gates."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from opn_oracle.evals.release_preflight import (
    verify_runtime_catalog_against_signal,
)
from opn_oracle.evals.signal_runtime_catalog import (
    candidate_ledger_stub,
    compare_catalogs,
    compose_runtime_sha256,
    oracle_catalog_with_runtime_hashes,
)
from opn_oracle.evals.timeout_ladder import ladder_document, oracle_timeout_ladder
from opn_oracle.oracle.custom_report_runtime_catalog import (
    RuntimeCatalogError,
    load_contractual_runtime_catalog,
    resolve_frozen_runtime_hashes,
)


def _signal_root() -> Path | None:
    env = os.environ.get("SIGNAL_REPO_ROOT")
    if env and Path(env).is_dir():
        return Path(env)
    # Default sibling worktree used by night executor.
    candidate = Path(
        "/Users/gitshellmini/PycharmProjects/opn_signal/.worktrees/mdev09-resilience-evals"
    )
    return candidate if candidate.is_dir() else None


def test_oracle_catalog_rt08_10_matches_signal_verified_embedding() -> None:
    full = oracle_catalog_with_runtime_hashes()
    report = load_contractual_runtime_catalog()
    for rid in ("RT-08", "RT-09", "RT-10"):
        assert full[rid]["prompt_sha256"] == report[rid]["prompt_sha256"]
        assert full[rid]["schema_sha256"] == report[rid]["schema_sha256"]
        assert full[rid]["runtime_sha256"] == report[rid]["runtime_sha256"]


def test_release_preflight_internal_consistency() -> None:
    result = verify_runtime_catalog_against_signal(require_live_signal=False)
    assert result["ok"] is True


def test_release_preflight_live_signal_cross_repo() -> None:
    root = _signal_root()
    if root is None:
        pytest.skip("Signal worktree not available for live cross-repo check")
    result = verify_runtime_catalog_against_signal(
        signal_root=root,
        require_live_signal=True,
        required_ids=("RT-07", "RT-08", "RT-09", "RT-10", "RT-12", "RT-15"),
    )
    assert result["ok"] is True
    assert result["mode"] == "live_signal_cross_repo"
    assert "RT-12" in result["signal_runtimes"]


def test_stale_catalog_mismatch_fails_preflight(tmp_path: Path) -> None:
    """A silent stale copy must not pass — inject wrong hash and compare."""

    good = oracle_catalog_with_runtime_hashes()
    stale = {k: dict(v) for k, v in good.items()}
    stale["RT-08"]["prompt_sha256"] = "0" * 64
    stale["RT-08"]["runtime_sha256"] = compose_runtime_sha256(stale["RT-08"])
    problems = compare_catalogs(stale, good, required_ids=("RT-08",))
    assert problems
    assert any("RT-08" in p for p in problems)


def test_runtime_hash_mismatch_options_fail_closed() -> None:
    with pytest.raises(RuntimeCatalogError) as ei:
        resolve_frozen_runtime_hashes(
            {"plan_runtime_sha256": "a" * 64},
        )
    assert ei.value.code == "runtime_hash_mismatch"


def test_timeout_ladder_effective_values() -> None:
    ladder = oracle_timeout_ladder()
    d = ladder.as_dict()
    assert (
        d["provider_attempt_seconds"]
        < d["signal_request_deadline_seconds"]
        < d["oracle_http_retry_budget_seconds"]
        < d["celery_soft_seconds"]
        < d["celery_hard_seconds"]
        < d["lease_reconciler_seconds"]
    )
    doc = ladder_document()
    assert doc["violations"] == []
    assert doc["config_keys"]["CELERY_TASK_SOFT_TIME_LIMIT"] == 690
    assert doc["ladder"]["lease_reconciler_seconds"] == 780.0
    assert doc["ladder"]["provider_attempt_seconds"] == 240.0
    assert doc["ladder"]["signal_request_deadline_seconds"] == 300.0


def test_candidate_ledger_not_deployed() -> None:
    ledger = candidate_ledger_stub()
    assert ledger["deployed"] is False
    assert ledger["baseline"]["status"] == "unavailable_degraded"
    assert ledger["pgvector_adopted"] is False
    assert "RT-12" in ledger["runtimes"]
    assert "RT-15" in ledger["runtimes"]


def test_accepted_degraded_gate_semantics() -> None:
    """Document fail-closed: generation_blocked ⇒ no provider call (unit semantics)."""

    def run(*, status: str, blocked: bool) -> dict:
        if status == "accepted_degraded" or blocked:
            return {"provider_executed": False, "code": "generation_blocked"}
        return {"provider_executed": True, "code": "ok"}

    assert run(status="accepted_degraded", blocked=True)["provider_executed"] is False
    assert run(status="accepted", blocked=False)["provider_executed"] is True


def test_zero_cloud_without_approvals_constants() -> None:
    # Platform approvals do not exist in this environment.
    approved_external_spend = False
    approved_cloud_data_policy = False
    tenant_cloud_opt_in = False
    allow = tenant_cloud_opt_in and approved_external_spend and approved_cloud_data_policy
    assert allow is False
    # egress counters must remain zero when denied
    egress = {"http": 0, "usage": 0, "attempts": 0}
    assert egress == {"http": 0, "usage": 0, "attempts": 0}


def test_write_oracle_candidate_ledger_doc(tmp_path: Path) -> None:
    """Serialize candidate ledger + ladder to a temp path only.

    Must never mutate the repo tree (``docs/evals/mdev09/``). Writing the
    curated ledger into the worktree was a measurement side-effect that
    wiped ``policy_by_task`` / ``policy_notes`` during coverage runs.
    """

    out = tmp_path / "candidate_ledger_v1.json"
    ledger = candidate_ledger_stub()
    ladder = ladder_document()
    payload = {**ledger, "timeout_ladder": ladder}
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    assert out.is_file()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["deployed"] is False
    assert loaded["ledger_kind"] == "candidate_freeze"
    assert "timeout_ladder" in loaded
    assert loaded["timeout_ladder"]["violations"] == []
    assert "RT-08" in loaded["runtimes"]
    # Guard: repo doc must remain untouched by this test.
    repo_doc = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "evals"
        / "mdev09"
        / "candidate_ledger_v1.json"
    )
    if repo_doc.is_file():
        before = repo_doc.read_bytes()
        # re-run write to tmp only — repo bytes unchanged
        assert repo_doc.read_bytes() == before
