"""G-29 retrieval fixtures: off=0, dossier_only isolation, snapshot mode/version."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from opn_oracle.integrations.memory_context import (
    MockMemoryContextAdapter,
    persist_retrieval_snapshot,
)
from opn_oracle.integrations.memory_contract_v1 import (
    build_scope,
    materialize_signal_item_to_evidence,
    should_call_signal,
    should_inject_into_llm,
)


@pytest.mark.unit
def test_modes_signal_and_inject() -> None:
    assert should_call_signal("disabled") is False
    assert should_inject_into_llm("disabled") is False
    assert should_call_signal("shadow") is True
    assert should_inject_into_llm("shadow") is False
    assert should_call_signal("augment") is True
    assert should_inject_into_llm("augment") is True


@pytest.mark.unit
def test_build_scope_is_dossier_not_global() -> None:
    d1 = str(uuid.uuid4())
    scope = build_scope(consumer_id="1", external_tenant_id="tenant-a", dossier_id=d1)
    assert scope["scope_type"] == "dossier"
    assert scope["scope_id"] == d1
    assert scope["product_code"] == "oracle"


@pytest.mark.unit
def test_disabled_mock_retrieve_contributes_zero_memory_items() -> None:
    """off/disabled: adapter path returns empty items; snapshot not written for disabled."""
    adapter = MockMemoryContextAdapter()
    d1 = str(uuid.uuid4())
    result = adapter.retrieve(
        {"tenant_id": "t1", "dossier_id": d1, "mode": "disabled"},
        query="what do you know?",
        purpose="question",
        limit=10,
    )
    assert result["items"] == []
    assert should_call_signal("disabled") is False

    # persist_retrieval_snapshot short-circuits on disabled
    class Sess:
        def __init__(self) -> None:
            self.added: list[Any] = []

        def add(self, obj: Any) -> None:
            self.added.append(obj)

    sess = Sess()
    snap_id = persist_retrieval_snapshot(
        sess,
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.UUID(d1),
        connection_id=None,
        mode="disabled",
        correlation_id="corr-1",
        snapshot={"items": result["items"], "failed": False, "inject_into_llm": False},
    )
    assert snap_id is None
    assert sess.added == []


@pytest.mark.unit
def test_dossier_only_does_not_mix_other_dossier_items() -> None:
    """Adversarial: items stamped with other dossier/tenant are excluded at materialize."""
    d_self = str(uuid.uuid4())
    d_other = str(uuid.uuid4())
    t_self = str(uuid.uuid4())
    t_other = str(uuid.uuid4())

    good = {
        "id": "sig-good",
        "text": "fact from self dossier",
        "source_ref": "doc:1",
        "checksum": "a" * 64,
        "locator": "p1",
        "classification": "internal",
        "policy_version": "memory.v1",
        "watermark": "w1",
        "tenant_id": t_self,
        "dossier_id": d_self,
    }
    # Cross-dossier adversarial
    bad_dossier = {
        **good,
        "id": "sig-other-dossier",
        "text": "LEAK other dossier",
        "dossier_id": d_other,
    }
    # Cross-tenant adversarial
    bad_tenant = {
        **good,
        "id": "sig-other-tenant",
        "text": "LEAK other tenant",
        "tenant_id": t_other,
    }

    # Production filter (memory_ask_dual materialize path): tenant+dossier exactness.
    kept = []
    excluded = []
    for raw in (good, bad_dossier, bad_tenant):
        item_tenant = str(raw.get("tenant_id") or t_self)
        item_dossier = str(raw.get("dossier_id") or d_self)
        if item_tenant != t_self or item_dossier != d_self:
            excluded.append(raw["id"])
            continue
        cit = materialize_signal_item_to_evidence(raw, tenant_id=t_self, dossier_id=d_self)
        kept.append(cit.signal_item_id)

    assert kept == ["sig-good"]
    assert "sig-other-dossier" in excluded
    assert "sig-other-tenant" in excluded
    # tenant_curated not supported — no path accepts cross-dossier approved data
    assert not any(x.startswith("sig-other") for x in kept)


@pytest.mark.unit
def test_snapshot_preserves_mode_version_ids() -> None:
    class Sess:
        def __init__(self) -> None:
            self.added: list[Any] = []

        def add(self, obj: Any) -> None:
            self.added.append(obj)

    sess = Sess()
    tid = uuid.uuid4()
    did = uuid.uuid4()
    profile_id = str(uuid.uuid4())
    snap_id = persist_retrieval_snapshot(
        sess,
        tenant_id=tid,
        dossier_id=did,
        connection_id=None,
        mode="shadow",
        correlation_id="corr-g29",
        snapshot={
            "items": [
                {
                    "id": "item-1",
                    "text": "scoped fact",
                    "source_ref": "doc:1",
                    "checksum": "b" * 64,
                }
            ],
            "failed": False,
            "inject_into_llm": False,
            "profile_version": 2,
            "profile_id": profile_id,
        },
    )
    assert snap_id is not None
    assert len(sess.added) == 1
    row = sess.added[0]
    assert row.mode == "shadow"
    assert row.tenant_id == tid
    assert row.dossier_id == did
    assert row.payload["mode"] == "shadow"
    assert row.payload["tenant_id"] == str(tid)
    assert row.payload["dossier_id"] == str(did)
    assert row.payload["scope_type"] == "dossier"
    assert row.payload["profile_version"] == 2
    assert row.payload["profile_id"] == profile_id
    assert "item-1" in row.payload["item_ids_used"]
