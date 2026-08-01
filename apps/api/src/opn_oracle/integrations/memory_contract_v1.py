"""Contratos memory.v1 REWORK — Oracle (paridad con Signal)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

API_VERSION = "memory.v1"
_TENANT_KEY_RE = re.compile(r"^c:[^|]+\|t:[^|]+$")
OracleMemoryMode = Literal["disabled", "shadow", "augment"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def contract_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "docs" / "contracts" / "memory_v1" / "CONTRACT_MANIFEST.json"
        if candidate.is_file():
            return candidate.parent
    raise FileNotFoundError("memory_v1 contract not found")


def load_manifest() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((contract_root() / "CONTRACT_MANIFEST.json").read_text(encoding="utf-8")),
    )


def load_fixture(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((contract_root() / "fixtures" / name).read_text(encoding="utf-8")),
    )


def load_error_catalog() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((contract_root() / "error_catalog.json").read_text(encoding="utf-8")),
    )


def verify_contract_hashes() -> str:
    man = load_manifest()
    root = contract_root()
    lines: list[str] = []
    for rel, expected in sorted(man["files"].items()):
        data = (root / rel).read_bytes()
        h = hashlib.sha256(data).hexdigest()
        if h != expected:
            raise AssertionError(f"hash mismatch {rel}")
        lines.append(f"{h}  {rel}\n")
    cs = hashlib.sha256("".join(lines).encode()).hexdigest()
    if cs != man["content_set_sha256"]:
        raise AssertionError("content_set mismatch")
    return cs


def build_scope(
    *, consumer_id: int | str, external_tenant_id: str, dossier_id: str
) -> dict[str, str]:
    dossier = str(uuid.UUID(str(dossier_id)))
    tenant_key = f"c:{str(consumer_id).strip()}|t:{str(external_tenant_id).strip()}"
    if not _TENANT_KEY_RE.match(tenant_key):
        raise ValueError("invalid tenant_key")
    return {
        "tenant_key": tenant_key,
        "product_code": "oracle",
        "scope_type": "dossier",
        "scope_id": dossier,
    }


@dataclass(frozen=True)
class EffectiveMemoryMode:
    mode: OracleMemoryMode
    provenance: str
    host_mode: str
    connection_healthy: bool
    tenant_mode: OracleMemoryMode
    dossier_mode: OracleMemoryMode | None


def resolve_effective_mode(
    *,
    host_memory_context_mode: str,
    connection_healthy: bool,
    tenant_mode: OracleMemoryMode,
    dossier_mode: OracleMemoryMode | None = None,
) -> EffectiveMemoryMode:
    """Fail-closed host gate.

    Only host mode ``http`` may elevate to tenant/dossier shadow|augment.
    Unknown, empty, typo, or host-level ``shadow``/``augment`` resolve to
    **disabled** — never shadow/augment. ``disabled``/``mock`` stay disabled.
    Master switch (caller) still prevails via connection_healthy=False.
    """
    host = str(host_memory_context_mode or "").strip().lower() or "disabled"
    if host in {"disabled", "mock"} or not connection_healthy:
        return EffectiveMemoryMode(
            "disabled", "host_or_connection", host, connection_healthy, tenant_mode, dossier_mode
        )
    if host != "http":
        # typo / unknown / accidental shadow|augment as host mode → disabled
        return EffectiveMemoryMode(
            "disabled", "host_invalid", host, connection_healthy, tenant_mode, dossier_mode
        )
    mode: OracleMemoryMode = dossier_mode or tenant_mode
    return EffectiveMemoryMode(
        mode,
        "dossier_override" if dossier_mode else "tenant",
        host,
        connection_healthy,
        tenant_mode,
        dossier_mode,
    )


def should_call_signal(mode: OracleMemoryMode) -> bool:
    return mode in {"shadow", "augment"}


def should_inject_into_llm(mode: OracleMemoryMode) -> bool:
    return mode == "augment"


@dataclass(frozen=True)
class MaterializedCitation:
    oracle_evidence_id: str
    signal_item_id: str
    source_ref: str
    checksum: str
    exact_excerpt: str
    classification: str
    locator: str
    occurred_at: str | None
    policy_version: str
    watermark: str
    tenant_id: str
    dossier_id: str


def materialize_signal_item_to_evidence(
    item: dict[str, Any],
    *,
    tenant_id: str,
    dossier_id: str,
    evidence_id: str | None = None,
) -> MaterializedCitation:
    required = [
        "id",
        "text",
        "source_ref",
        "checksum",
        "locator",
        "classification",
        "policy_version",
        "watermark",
    ]
    for k in required:
        if k not in item or item[k] in (None, ""):
            raise ValueError(f"retrieval item missing {k}")
    return MaterializedCitation(
        oracle_evidence_id=evidence_id or str(uuid.uuid4()),
        signal_item_id=str(item["id"]),
        source_ref=str(item["source_ref"]),
        checksum=str(item["checksum"]),
        exact_excerpt=str(item["text"])[:8000],
        classification=str(item["classification"]),
        locator=str(item["locator"]),
        occurred_at=item.get("occurred_at"),
        policy_version=str(item["policy_version"]),
        watermark=str(item["watermark"]),
        tenant_id=str(tenant_id),
        dossier_id=str(uuid.UUID(str(dossier_id))),
    )


def llm_allowlist_from_citations(citations: list[MaterializedCitation]) -> list[str]:
    return [c.oracle_evidence_id for c in citations]


def degradation_policy(mode: OracleMemoryMode, error_code: str) -> dict[str, Any]:
    non_retry = {
        "missing_api_key",
        "invalid_api_key",
        "tenant_not_allowed",
        "dossier_not_allowed",
        "dossier_not_authorized",
        "credential_tenant_mismatch",
        "schema_validation_failed",
        "unsupported_api_version",
    }
    retryable = error_code in {
        "rate_limit_exceeded",
        "memory_engine_disabled",
        "upstream_timeout",
        "upstream_5xx",
        "backend_unavailable",
    }
    if mode == "disabled":
        return {"call_signal": False, "inject": False, "audit": False, "retryable": False}
    if mode == "shadow":
        return {
            "call_signal": True,
            "inject": False,
            "audit": True,
            "retryable": retryable and error_code not in non_retry,
            "on_error": "audit_only_continue_oracle_structured",
        }
    if error_code in non_retry:
        return {
            "call_signal": True,
            "inject": False,
            "audit": True,
            "retryable": False,
            "on_error": "config_failure_no_blind_retry",
        }
    return {
        "call_signal": True,
        "inject": not retryable,
        "audit": True,
        "retryable": retryable,
        "on_error": "degrade_to_oracle_memory_mark_coverage_failed",
    }


@dataclass(frozen=True)
class TenantCredentialBinding:
    tenant_id: str
    integration_connection_id: str
    signal_consumer_slug: str
    bound_external_tenant_id: str
    scopes: tuple[str, ...]
    revoked: bool = False


def rotate_binding(
    existing: TenantCredentialBinding, *, new_connection_id: str
) -> TenantCredentialBinding:
    if existing.revoked:
        raise ValueError("cannot rotate revoked binding")
    return TenantCredentialBinding(
        tenant_id=existing.tenant_id,
        integration_connection_id=new_connection_id,
        signal_consumer_slug=existing.signal_consumer_slug,
        bound_external_tenant_id=existing.bound_external_tenant_id,
        scopes=existing.scopes,
        revoked=False,
    )


def revoke_binding(existing: TenantCredentialBinding) -> TenantCredentialBinding:
    return TenantCredentialBinding(
        tenant_id=existing.tenant_id,
        integration_connection_id=existing.integration_connection_id,
        signal_consumer_slug=existing.signal_consumer_slug,
        bound_external_tenant_id=existing.bound_external_tenant_id,
        scopes=existing.scopes,
        revoked=True,
    )


class CoverageFailedEntry(StrictModel):
    code: str
    retryable: bool
    detail: str | None = None


class CoverageManifestV1(StrictModel):
    version: Literal["coverage_manifest.v1"] = "coverage_manifest.v1"
    requested: list[str] = Field(default_factory=list)
    consulted: list[str] = Field(default_factory=list)
    failed: list[CoverageFailedEntry] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)
    used: list[str] = Field(default_factory=list)
    truncated: bool = False
    truncation_notes: list[str] = Field(default_factory=list)
    cutoff_at: str | None = None
    token_budget: int = 0
    token_used_estimate: int = 0


def coverage_from_failure(
    *, requested: list[str], code: str, retryable: bool, detail: str | None = None
) -> CoverageManifestV1:
    return CoverageManifestV1(
        requested=list(requested),
        failed=[CoverageFailedEntry(code=code, retryable=retryable, detail=detail)],
    )


def is_legitimate_empty_success(coverage: CoverageManifestV1) -> bool:
    return not coverage.failed
