"""Contract tests memory.v1 REWORK — Oracle."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from opn_oracle.integrations.memory_contract_v1 import (
    CoverageManifestV1,
    TenantCredentialBinding,
    build_scope,
    contract_root,
    coverage_from_failure,
    degradation_policy,
    is_legitimate_empty_success,
    llm_allowlist_from_citations,
    load_error_catalog,
    load_fixture,
    load_manifest,
    materialize_signal_item_to_evidence,
    resolve_effective_mode,
    revoke_binding,
    rotate_binding,
    should_call_signal,
    should_inject_into_llm,
    verify_contract_hashes,
)

DOSSIER_A = "11111111-1111-4111-8111-111111111111"
DOSSIER_B = "22222222-2222-4222-8222-222222222222"


def test_shared_contract_hashes_and_openapi() -> None:
    cs = verify_contract_hashes()
    assert len(cs) == 64
    assert cs == load_manifest()["content_set_sha256"]
    spec = json.loads((contract_root() / "openapi.memory.v1.json").read_text())
    assert spec.get("openapi", "").startswith("3.1")
    assert "/memory/v1/retrieve" in spec.get("paths", {})
    assert "ErrorEnvelope" in spec.get("components", {}).get("schemas", {})
    try:
        from openapi_spec_validator import validate as oas_validate

        oas_validate(spec)
    except ImportError:
        pass


def test_scope_and_two_dossiers() -> None:
    scope = build_scope(
        consumer_id=14,
        external_tenant_id="tenant-a",
        dossier_id=DOSSIER_A,
    )
    assert scope["scope_type"] == "dossier"
    doc = load_fixture("same_source_two_dossiers.json")
    ids = {b["scope"]["scope_id"] for b in doc["bindings"]}
    assert ids == {DOSSIER_A, DOSSIER_B}


def test_modes_and_citability() -> None:
    eff = resolve_effective_mode(
        host_memory_context_mode="disabled",
        connection_healthy=True,
        tenant_mode="augment",
    )
    assert eff.mode == "disabled"
    assert should_call_signal("shadow")
    assert not should_inject_into_llm("shadow")
    item = load_fixture("retrieval_item_example.json")
    cit = materialize_signal_item_to_evidence(
        item,
        tenant_id="tenant-a",
        dossier_id=DOSSIER_A,
        evidence_id="ev1",
    )
    assert llm_allowlist_from_citations([cit]) == ["ev1"]


def test_coverage_failure_not_empty_success() -> None:
    cov = coverage_from_failure(
        requested=["retrieval"],
        code="upstream_timeout",
        retryable=True,
    )
    assert cov.failed
    assert not is_legitimate_empty_success(cov)
    ok = CoverageManifestV1(requested=["retrieval"], consulted=["stub"], failed=[])
    assert is_legitimate_empty_success(ok)


def test_degradation_and_credentials() -> None:
    codes = {e["error_code"] for e in load_error_catalog()["errors"]}
    assert "tenant_not_allowed" in codes
    policy = degradation_policy("augment", "upstream_timeout")
    assert policy["on_error"] == "degrade_to_oracle_memory_mark_coverage_failed"
    tenant_a = TenantCredentialBinding(
        "tenant-a",
        "c1",
        "opn-oracle-dev",
        "tenant-a",
        ("memory:read",),
    )
    tenant_b = TenantCredentialBinding(
        "tenant-b",
        "c2",
        "opn-oracle-dev",
        "tenant-b",
        ("memory:read",),
    )
    rotated = rotate_binding(tenant_a, new_connection_id="c1b")
    assert rotated.integration_connection_id == "c1b"
    assert tenant_b.integration_connection_id == "c2"
    assert revoke_binding(rotated).revoked


def test_strict_extra_on_coverage() -> None:
    with pytest.raises(ValidationError):
        CoverageManifestV1(requested=[], failed=[], unknown=1)  # type: ignore[call-arg]
