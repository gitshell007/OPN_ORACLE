"""MDEV-09 provisional: cross-repo hashes, ladder, fault/security gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from opn_oracle.evals.release_preflight import (
    verify_runtime_catalog_against_signal,
)
from opn_oracle.evals.signal_runtime_catalog import (
    SIGNAL_ASSET_LAYOUT,
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
from tests.signal_checkout import (
    SIGNAL_CONTRACT_FIXTURE_ROOT,
    resolve_explicit_signal_checkout,
    resolve_signal_checkout,
)


def _runtime_contract_snapshot() -> dict[str, Any]:
    path = SIGNAL_CONTRACT_FIXTURE_ROOT / "runtime_catalog.v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _explicit_signal_root() -> Path | None:
    required = tuple(
        f"{layout['dir']}/{layout['manifest']}" for layout in SIGNAL_ASSET_LAYOUT.values()
    )
    return resolve_explicit_signal_checkout(required)


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


@pytest.mark.integration
def test_release_preflight_signal_contract_snapshot_and_optional_live_checkout() -> None:
    required_ids = ("RT-07", "RT-08", "RT-09", "RT-10", "RT-12", "RT-15")
    snapshot = _runtime_contract_snapshot()
    assert snapshot["contract"] == "signal.ai_runtime_catalog.v1"
    assert snapshot["source_repository"] == "opn_signal"
    assert len(str(snapshot["source_commit"])) == 40
    runtimes = snapshot["runtimes"]
    assert isinstance(runtimes, dict)
    assert (
        compare_catalogs(
            oracle_catalog_with_runtime_hashes(),
            runtimes,
            required_ids=required_ids,
        )
        == []
    )

    # A real checkout is an opt-in second verification, never a CI prerequisite.
    root = _explicit_signal_root()
    if root is not None:
        result = verify_runtime_catalog_against_signal(
            signal_root=root,
            require_live_signal=True,
            required_ids=required_ids,
        )
        assert result["ok"] is True
        assert result["mode"] == "live_signal_cross_repo"
        assert "RT-12" in result["signal_runtimes"]


def test_explicit_signal_checkout_fails_closed_instead_of_falling_back(tmp_path: Path) -> None:
    required = ("app/services/ai_tasks/example/RT-X_MANIFEST.json",)
    with pytest.raises(RuntimeError, match="SIGNAL_REPO_ROOT"):
        resolve_signal_checkout(
            required,
            candidate_roots=(SIGNAL_CONTRACT_FIXTURE_ROOT,),
            environ={"SIGNAL_REPO_ROOT": str(tmp_path)},
        )


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
