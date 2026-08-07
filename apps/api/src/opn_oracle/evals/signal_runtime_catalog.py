"""Frozen Signal-verified runtime catalog for Oracle release preflight (MDEV-09).

Hashes verified against Signal assets at MDEV-09 materialization time.
A mismatch against live Signal manifests fails the release preflight.
Never accept a silent stale copy.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# Verified from Signal mdev/09-resilience-evals (base 6a4432a + RT-12/15).
SIGNAL_VERIFIED_RUNTIMES: dict[str, dict[str, str]] = {
    "RT-07": {
        "task_key": "dossier_question_answer",
        "runtime_id": "RT-07",
        "prompt_sha256": "092da4fe2021c6a4ec2e2ef46bcf8b173db9000ccc2f3f558af086ac60ebe407",
        "schema_sha256": "fa7663159d647627368490b694bf055b0289e998e87baef16617e17cfa8b666d",
        "prompt_version": "1.0.0",
        "schema_version": "dossier_question_answer.v1",
    },
    "RT-08": {
        "task_key": "report_custom_brief_plan",
        "runtime_id": "RT-08",
        "prompt_sha256": "d9ebd175f23dcb0f83f1ad43b45ecac0afe9990a64cd5bd21c2223e067c84e7f",
        "schema_sha256": "949a1b57b628246594ffc169d77a7cb676a11d90fa43a5910ab455920e7028f7",
        "prompt_version": "1.0.2",
        "schema_version": "custom_brief_plan.v1",
    },
    "RT-09": {
        "task_key": "report_custom_writer",
        "runtime_id": "RT-09",
        "prompt_sha256": "6aa4f0e1cc175b2afef0c2c7feda2d058d125f7fab42ba10fce2a5d5e45e262c",
        "schema_sha256": "e80bfa4f2e3bd211af6de9eb6d9840081bf93873b2c60cca164039cec4ff77c5",
        "prompt_version": "1.0.2",
        "schema_version": "custom_report_writer.v1",
    },
    "RT-10": {
        "task_key": "report_custom_review",
        "runtime_id": "RT-10",
        "prompt_sha256": "4699d12b0d51188b5cbdf0a3ef320983c0cf3893d515b2dccc1d3bbab4a5b5ea",
        "schema_sha256": "921c5a06ec686f975de01b0bec0556857cc1c2b2cc9e8121240d94c412a44710",
        "prompt_version": "1.0.1",
        "schema_version": "custom_report_review.v1",
    },
    "RT-12": {
        "task_key": "eval_corpus_grounded",
        "runtime_id": "RT-12",
        "prompt_sha256": "40ce008da9788c5c9ccf64546a7ca708e6eac4e05daec161f2d4f74acec05156",
        "schema_sha256": "8dd7f4fd6211bcc647cc47c229770321fbbe7c7223256086e438dfd7f8b1924e",
        "prompt_version": "1.0.0",
        "schema_version": "eval_corpus_grounded.v1",
    },
    "RT-15": {
        "task_key": "security_local_gate",
        "runtime_id": "RT-15",
        "prompt_sha256": "9ca12202e2573ca560dc1defba3ca775a04a20588750822dcf174c130921dddf",
        "schema_sha256": "e58be46736e4ca07c2de8b0ed9d12da326337f6c7cb7d3bd543c35097c5202d9",
        "prompt_version": "1.0.0",
        "schema_version": "security_local_gate.v1",
    },
}

# Relative paths under a Signal repo root for live verification.
SIGNAL_ASSET_LAYOUT: dict[str, dict[str, str]] = {
    "RT-07": {
        "dir": "app/services/ai_tasks/dossier_question_answer",
        "manifest": "RT-07_MANIFEST.json",
    },
    "RT-08": {
        "dir": "app/services/ai_tasks/report_custom_brief_plan",
        "manifest": "RT-08_MANIFEST.json",
    },
    "RT-09": {
        "dir": "app/services/ai_tasks/report_custom_writer",
        "manifest": "RT-09_MANIFEST.json",
    },
    "RT-10": {
        "dir": "app/services/ai_tasks/report_custom_review",
        "manifest": "RT-10_MANIFEST.json",
    },
    "RT-12": {
        "dir": "app/services/ai_tasks/eval_corpus_grounded",
        "manifest": "RT-12_MANIFEST.json",
    },
    "RT-15": {
        "dir": "app/services/ai_tasks/security_local_gate",
        "manifest": "RT-15_MANIFEST.json",
    },
}


def compose_runtime_sha256(manifest: dict[str, str]) -> str:
    payload = {
        "runtime_id": manifest["runtime_id"],
        "task_key": manifest["task_key"],
        "prompt_sha256": manifest["prompt_sha256"],
        "schema_sha256": manifest["schema_sha256"],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def oracle_catalog_with_runtime_hashes() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for rid, entry in SIGNAL_VERIFIED_RUNTIMES.items():
        e = dict(entry)
        e["runtime_sha256"] = compose_runtime_sha256(e)
        out[rid] = e
    return out


def load_signal_manifests_from_root(signal_root: Path) -> dict[str, dict[str, str]]:
    """Load live Signal manifests and recompute hashes from prompt/schema files."""

    result: dict[str, dict[str, str]] = {}
    for rid, layout in SIGNAL_ASSET_LAYOUT.items():
        base = signal_root / layout["dir"]
        man_path = base / layout["manifest"]
        if not man_path.is_file():
            raise FileNotFoundError(f"missing Signal manifest for {rid}: {man_path}")
        man = json.loads(man_path.read_text(encoding="utf-8"))
        prompt_path = base / Path(str(man["prompt_path"])).name
        schema_path = base / Path(str(man["schema_path"])).name
        prompt_sha = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema_sha = hashlib.sha256(
            json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if prompt_sha != man.get("prompt_sha256"):
            raise ValueError(f"Signal asset drift {rid}: prompt_sha256 mismatch")
        if schema_sha != man.get("schema_sha256"):
            raise ValueError(f"Signal asset drift {rid}: schema_sha256 mismatch")
        entry = {
            "task_key": str(man["task_key"]),
            "runtime_id": str(man["runtime_id"]),
            "prompt_sha256": prompt_sha,
            "schema_sha256": schema_sha,
            "prompt_version": str(man.get("prompt_version") or ""),
            "schema_version": str(man.get("schema_version") or ""),
        }
        entry["runtime_sha256"] = compose_runtime_sha256(entry)
        result[rid] = entry
    return result


def compare_catalogs(
    oracle_cat: dict[str, dict[str, str]],
    signal_cat: dict[str, dict[str, str]],
    *,
    required_ids: tuple[str, ...] = ("RT-07", "RT-08", "RT-09", "RT-10"),
) -> list[str]:
    """Return list of mismatch descriptions (empty = OK)."""

    problems: list[str] = []
    for rid in required_ids:
        o = oracle_cat.get(rid)
        s = signal_cat.get(rid)
        if o is None:
            problems.append(f"{rid}: missing in Oracle catalog")
            continue
        if s is None:
            problems.append(f"{rid}: missing in Signal assets")
            continue
        for key in ("prompt_sha256", "schema_sha256", "runtime_sha256", "task_key"):
            if str(o.get(key, "")).lower() != str(s.get(key, "")).lower():
                problems.append(f"{rid}.{key}: oracle={o.get(key)} signal={s.get(key)}")
    return problems


def candidate_ledger_stub() -> dict[str, Any]:
    """Candidate freeze only — not deployed state."""

    cat = oracle_catalog_with_runtime_hashes()
    return {
        "ledger_kind": "candidate_freeze",
        "deployed": False,
        "phase": "MDEV-09-PROVISIONAL",
        "runtimes": cat,
        "baseline": {
            "status": "unavailable_degraded",
            "reason": "durable memory blocked (MDEV-05/08)",
        },
        "policy_default": "local_only",
        "pgvector_adopted": False,
    }
