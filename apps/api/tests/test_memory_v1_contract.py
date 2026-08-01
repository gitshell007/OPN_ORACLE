"""Contract tests memory.v1 (MDEV-01) — Oracle side."""

from __future__ import annotations

import copy

import pytest

from opn_oracle.integrations.memory_contract_v1 import (
    TenantCredentialBinding,
    build_scope,
    degradation_policy,
    llm_allowlist_from_citations,
    load_error_catalog,
    load_fixture,
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


def test_shared_contract_hashes():
    cs = verify_contract_hashes()
    assert len(cs) == 64


def test_scope_canonical():
    s = build_scope(consumer_id=14, external_tenant_id="tenant-a", dossier_id=DOSSIER_A)
    assert s == {
        "tenant_key": "c:14|t:tenant-a",
        "product_code": "oracle",
        "scope_type": "dossier",
        "scope_id": DOSSIER_A,
    }
    with pytest.raises(ValueError):
        build_scope(consumer_id=14, external_tenant_id="tenant-a", dossier_id="bad")


def test_same_source_two_dossiers_fixture():
    doc = load_fixture("same_source_two_dossiers.json")
    ids = {b["scope"]["scope_id"] for b in doc["bindings"]}
    assert ids == {DOSSIER_A, DOSSIER_B}
    assert doc["bindings"][0]["memory_source_id"] != doc["bindings"][1]["memory_source_id"]


def test_modes_precedence_and_injection():
    eff = resolve_effective_mode(
        host_memory_context_mode="disabled",
        connection_healthy=True,
        tenant_mode="augment",
    )
    assert eff.mode == "disabled"
    assert should_call_signal(eff.mode) is False

    eff2 = resolve_effective_mode(
        host_memory_context_mode="http",
        connection_healthy=True,
        tenant_mode="shadow",
        dossier_mode=None,
    )
    assert eff2.mode == "shadow"
    assert should_call_signal("shadow") is True
    assert should_inject_into_llm("shadow") is False

    eff3 = resolve_effective_mode(
        host_memory_context_mode="http",
        connection_healthy=True,
        tenant_mode="shadow",
        dossier_mode="augment",
    )
    assert eff3.mode == "augment"
    assert should_inject_into_llm("augment") is True


def test_citability_materialization_and_allowlist():
    item = load_fixture("retrieval_item_example.json")
    cit = materialize_signal_item_to_evidence(
        item,
        tenant_id="tenant-a",
        dossier_id=DOSSIER_A,
        evidence_id="ev-fixed-1",
    )
    assert cit.oracle_evidence_id == "ev-fixed-1"
    assert cit.signal_item_id == item["id"]
    allow = llm_allowlist_from_citations([cit])
    assert allow == ["ev-fixed-1"]
    assert item["id"] not in allow

    bad = copy.deepcopy(item)
    del bad["checksum"]
    with pytest.raises(ValueError):
        materialize_signal_item_to_evidence(bad, tenant_id="t", dossier_id=DOSSIER_A)


def test_degradation_policy_closed():
    cat = load_error_catalog()
    codes = {e["error_code"] for e in cat["errors"]}
    assert "tenant_not_allowed" in codes
    d = degradation_policy("augment", "upstream_timeout")
    assert d["on_error"] == "degrade_to_oracle_memory_mark_coverage_failed"
    d2 = degradation_policy("augment", "tenant_not_allowed")
    assert d2["retryable"] is False
    d3 = degradation_policy("shadow", "upstream_5xx")
    assert d3["inject"] is False


def test_credential_per_tenant_rotation_isolation():
    a = TenantCredentialBinding(
        tenant_id="tenant-a",
        integration_connection_id="conn-a1",
        signal_consumer_slug="opn-oracle-dev",
        bound_external_tenant_id="tenant-a",
        scopes=("memory:read", "memory:write", "ai:run"),
    )
    b = TenantCredentialBinding(
        tenant_id="tenant-b",
        integration_connection_id="conn-b1",
        signal_consumer_slug="opn-oracle-dev",
        bound_external_tenant_id="tenant-b",
        scopes=("memory:read", "memory:write", "ai:run"),
    )
    a2 = rotate_binding(a, new_connection_id="conn-a2")
    assert a2.integration_connection_id == "conn-a2"
    assert b.integration_connection_id == "conn-b1"  # isolation
    revoked = revoke_binding(a2)
    assert revoked.revoked is True
    with pytest.raises(ValueError):
        rotate_binding(revoked, new_connection_id="x")


def test_mutating_error_catalog_code_breaks_lookup_expectation():
    cat = load_error_catalog()
    mutated = copy.deepcopy(cat)
    mutated["errors"] = [e for e in mutated["errors"] if e["error_code"] != "tenant_not_allowed"]
    codes = {e["error_code"] for e in mutated["errors"]}
    assert "tenant_not_allowed" not in codes


def test_stub_retrieve_fixture_shape():
    body = load_fixture("retrieve_response_stub.json")
    assert body["api_version"] == "memory.v1"
    assert body["items"] == []
    assert body["coverage_manifest"]["version"] == "coverage_manifest.v1"
    assert body["scope"]["scope_type"] == "dossier"
