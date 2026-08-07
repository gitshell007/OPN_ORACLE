"""Contractual RT-08/09/10 runtime catalog for Oracle (MDEV-08).

Hashes are copied from verified Signal manifests (prompt_sha256 + schema_sha256).
Never invent SHA-256 from string seeds. Missing/mismatched hashes fail closed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# Verified from Signal worktree manifests (mdev/08-reports-durable · 65edd44):
# app/services/ai_tasks/report_custom_*/RT-0{8,9,10}_MANIFEST.json
_SIGNAL_VERIFIED_MANIFESTS: dict[str, dict[str, str]] = {
    "RT-08": {
        "task_key": "report_custom_brief_plan",
        "runtime_id": "RT-08",
        "prompt_sha256": "d9ebd175f23dcb0f83f1ad43b45ecac0afe9990a64cd5bd21c2223e067c84e7f",
        "schema_sha256": "949a1b57b628246594ffc169d77a7cb676a11d90fa43a5910ab455920e7028f7",
        "prompt_version": "1.0.3",
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
        "prompt_version": "1.0.2",
        "schema_version": "custom_report_review.v1",
    },
}

_ROLE_TO_RUNTIME = {
    "plan": "RT-08",
    "writer": "RT-09",
    "review": "RT-10",
}


class RuntimeCatalogError(ValueError):
    """Observable fail-closed catalog/hash error."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _is_sha256_hex(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value.lower())
    )


def _compose_runtime_hash(manifest: dict[str, str]) -> str:
    """Stable contractual runtime hash from verified prompt+schema digests (not a seed string)."""

    payload = {
        "runtime_id": manifest["runtime_id"],
        "task_key": manifest["task_key"],
        "prompt_sha256": manifest["prompt_sha256"],
        "schema_sha256": manifest["schema_sha256"],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_contractual_runtime_catalog(
    *,
    catalog_path: Path | None = None,
) -> dict[str, dict[str, str]]:
    """Load and validate the contractual catalog.

    Built-in verified manifests are the default. An optional external catalog file
    may override only if every required hash is present and valid hex.
    """

    catalog = {k: dict(v) for k, v in _SIGNAL_VERIFIED_MANIFESTS.items()}
    if catalog_path is not None and catalog_path.is_file():
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeCatalogError(
                "Catálogo contractual inválido (no object).",
                code="runtime_catalog_invalid",
            )
        for runtime_id, entry in raw.items():
            if not isinstance(entry, dict):
                raise RuntimeCatalogError(
                    f"Entrada de catálogo inválida: {runtime_id}",
                    code="runtime_catalog_invalid",
                )
            for key in ("task_key", "runtime_id", "prompt_sha256", "schema_sha256"):
                if key not in entry:
                    raise RuntimeCatalogError(
                        f"Catálogo incompleto: {runtime_id}.{key}",
                        code="runtime_catalog_incomplete",
                    )
            if not _is_sha256_hex(entry["prompt_sha256"]) or not _is_sha256_hex(
                entry["schema_sha256"]
            ):
                raise RuntimeCatalogError(
                    f"Hash no contractual en catálogo: {runtime_id}",
                    code="runtime_catalog_hash_invalid",
                )
            catalog[str(runtime_id)] = {
                "task_key": str(entry["task_key"]),
                "runtime_id": str(entry.get("runtime_id") or runtime_id),
                "prompt_sha256": str(entry["prompt_sha256"]).lower(),
                "schema_sha256": str(entry["schema_sha256"]).lower(),
                "prompt_version": str(entry.get("prompt_version") or ""),
                "schema_version": str(entry.get("schema_version") or ""),
            }

    for runtime_id, entry in catalog.items():
        if not _is_sha256_hex(entry.get("prompt_sha256")) or not _is_sha256_hex(
            entry.get("schema_sha256")
        ):
            raise RuntimeCatalogError(
                f"Manifest {runtime_id} sin hashes verificados.",
                code="runtime_manifest_missing",
            )
        entry["runtime_sha256"] = _compose_runtime_hash(entry)
    return catalog


def resolve_frozen_runtime_hashes(
    options: dict[str, Any] | None = None,
    *,
    catalog: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    """Return plan/writer/review runtime hashes from the contractual catalog only.

    If ``options`` already carries hashes, they must match the catalog exactly.
    Never fabricates SHA-256 from seed strings.
    """

    cat = catalog if catalog is not None else load_contractual_runtime_catalog()
    out: dict[str, str] = {}
    option_keys = {
        "plan": "plan_runtime_sha256",
        "writer": "writer_runtime_sha256",
        "review": "review_runtime_sha256",
    }
    nested = options.get("runtime_sha256") if isinstance(options, dict) else None
    nested_map = nested if isinstance(nested, dict) else {}

    for role, runtime_id in _ROLE_TO_RUNTIME.items():
        entry = cat.get(runtime_id)
        if entry is None or not _is_sha256_hex(entry.get("runtime_sha256")):
            raise RuntimeCatalogError(
                f"Manifest/hash contractual ausente para {runtime_id}.",
                code="runtime_manifest_missing",
            )
        catalog_hash = str(entry["runtime_sha256"]).lower()
        claimed: str | None = None
        if isinstance(options, dict):
            raw = options.get(option_keys[role])
            if _is_sha256_hex(raw):
                claimed = str(raw).lower()
            nested_raw = nested_map.get(role)
            if claimed is None and _is_sha256_hex(nested_raw):
                claimed = str(nested_raw).lower()
        if claimed is not None and claimed != catalog_hash:
            raise RuntimeCatalogError(
                f"Hash runtime {runtime_id} no coincide con catálogo contractual.",
                code="runtime_hash_mismatch",
            )
        out[role] = catalog_hash
    return out


def catalog_manifest_bundle() -> dict[str, Any]:
    """Full verified bundle for audit/snapshot freeze."""

    cat = load_contractual_runtime_catalog()
    return {
        "source": "signal_verified_manifests_contractual_v1",
        "runtimes": cat,
        "frozen_runtime_sha256": {
            "plan": cat["RT-08"]["runtime_sha256"],
            "writer": cat["RT-09"]["runtime_sha256"],
            "review": cat["RT-10"]["runtime_sha256"],
        },
    }
