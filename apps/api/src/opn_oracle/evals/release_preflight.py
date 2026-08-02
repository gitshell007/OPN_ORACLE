"""Release preflight: Oracle catalog must match Signal assets (MDEV-09)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from opn_oracle.evals.signal_runtime_catalog import (
    compare_catalogs,
    load_signal_manifests_from_root,
    oracle_catalog_with_runtime_hashes,
)
from opn_oracle.oracle.custom_report_runtime_catalog import (
    load_contractual_runtime_catalog,
)


class ReleasePreflightError(RuntimeError):
    def __init__(self, message: str, *, code: str = "release_preflight_failed") -> None:
        super().__init__(message)
        self.code = code


def _resolve_signal_root(explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        return explicit
    env = os.environ.get("SIGNAL_REPO_ROOT") or os.environ.get("OPN_SIGNAL_ROOT")
    if env:
        p = Path(env)
        if p.is_dir():
            return p
    return None


def verify_runtime_catalog_against_signal(
    *,
    signal_root: Path | None = None,
    require_live_signal: bool = False,
    required_ids: tuple[str, ...] = ("RT-07", "RT-08", "RT-09", "RT-10"),
) -> dict[str, Any]:
    """Fail closed on hash mismatch between Oracle catalogs and Signal assets.

    When Signal root is unavailable and require_live_signal is False, still
    verifies Oracle custom-report catalog (RT-08/09/10) against the frozen
    MDEV-09 Signal-verified embedding (prevents stale silent accept of a
    divergent hardcoded copy).
    """

    oracle_full = oracle_catalog_with_runtime_hashes()
    # Contractual report catalog (existing MDEV-08 module) must match RT-08/09/10.
    report_cat = load_contractual_runtime_catalog()
    report_problems = compare_catalogs(
        {
            rid: {
                "task_key": report_cat[rid]["task_key"],
                "runtime_id": report_cat[rid]["runtime_id"],
                "prompt_sha256": report_cat[rid]["prompt_sha256"],
                "schema_sha256": report_cat[rid]["schema_sha256"],
                "runtime_sha256": report_cat[rid]["runtime_sha256"],
            }
            for rid in ("RT-08", "RT-09", "RT-10")
            if rid in report_cat
        },
        {rid: oracle_full[rid] for rid in ("RT-08", "RT-09", "RT-10")},
        required_ids=("RT-08", "RT-09", "RT-10"),
    )
    if report_problems:
        raise ReleasePreflightError(
            "Oracle custom_report catalog stale vs Signal-verified: " + "; ".join(report_problems),
            code="runtime_catalog_stale",
        )

    root = _resolve_signal_root(signal_root)
    live: dict[str, Any] = {"signal_root": str(root) if root else None, "live": False}
    if root is None:
        if require_live_signal:
            raise ReleasePreflightError(
                "SIGNAL_REPO_ROOT not set; cannot verify live Signal assets",
                code="signal_root_missing",
            )
        return {
            "ok": True,
            "mode": "oracle_internal_consistency",
            "required_ids": list(required_ids),
            "live": live,
            "mismatches": [],
        }

    try:
        signal_cat = load_signal_manifests_from_root(root)
    except (OSError, ValueError, KeyError) as exc:
        raise ReleasePreflightError(
            f"failed to load Signal assets: {exc}", code="signal_assets_unreadable"
        ) from exc

    problems = compare_catalogs(oracle_full, signal_cat, required_ids=required_ids)
    # Also verify RT-12/15 if present in both
    optional = tuple(rid for rid in ("RT-12", "RT-15") if rid in oracle_full and rid in signal_cat)
    if optional:
        problems.extend(compare_catalogs(oracle_full, signal_cat, required_ids=optional))

    if problems:
        raise ReleasePreflightError(
            "runtime hash mismatch Oracle vs Signal (stale copy rejected): " + "; ".join(problems),
            code="runtime_hash_mismatch",
        )
    live["live"] = True
    return {
        "ok": True,
        "mode": "live_signal_cross_repo",
        "required_ids": list(required_ids) + list(optional),
        "live": live,
        "mismatches": [],
        "signal_runtimes": sorted(signal_cat.keys()),
    }
