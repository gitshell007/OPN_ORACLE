"""MDEV-05 Oracle bilateral memory outbox unit tests."""

from __future__ import annotations

import uuid

import pytest

from opn_oracle.integrations.memory_outbox import (
    bilateral_outbox_enabled,
    build_envelope,
    stage_memory_event,
)


def test_flag_default_off(monkeypatch):
    monkeypatch.delenv("MEMORY_BILATERAL_OUTBOX_ENABLED", raising=False)
    assert bilateral_outbox_enabled() is False


def test_build_envelope_document_ready():
    tenant = uuid.uuid4()
    dossier = uuid.uuid4()
    env = build_envelope(
        event_type="document.version.ready",
        tenant_id=tenant,
        dossier_id=dossier,
        external_tenant_id="ext-1",
        items=[{"origin_id": "d1", "text": "hola mundo", "title": "Doc"}],
        intent_revision_id="rev-1",
        requirement_ids=["req-a"],
        classification="internal",
    )
    assert env["api_version"] == "memory.v1"
    assert env["event_type"] == "document.version.ready"
    assert env["publisher_degraded"] is True
    assert env["memory_profile_degraded"] is True
    assert env["items"][0]["text"] == "hola mundo"
    assert "blob" not in env["items"][0]
    assert env["checksum"]


def test_build_envelope_rejects_secrets():
    with pytest.raises(ValueError, match="forbidden"):
        build_envelope(
            event_type="document.version.ready",
            tenant_id=uuid.uuid4(),
            dossier_id=uuid.uuid4(),
            external_tenant_id="ext",
            items=[{"origin_id": "x", "text": "t", "secret": "nope"}],
        )


def test_stage_disabled_returns_status(monkeypatch):
    monkeypatch.setenv("MEMORY_BILATERAL_OUTBOX_ENABLED", "0")

    class Conn:
        id = uuid.uuid4()
        tenant_id = uuid.uuid4()

    result = stage_memory_event(
        connection=Conn(),  # type: ignore[arg-type]
        event_type="scope.dossier.upsert",
        tenant_id=Conn.tenant_id,
        dossier_id=uuid.uuid4(),
        external_tenant_id="ext",
        items=[{"origin_id": "s1", "text": "scope meta"}],
    )
    assert isinstance(result, dict)
    assert result["status"] == "disabled"
    assert result["error_code"] == "bilateral_outbox_disabled"


def test_tombstone_envelope():
    env = build_envelope(
        event_type="memory.tombstone",
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        external_tenant_id="ext",
        items=[],
        tombstone_origin_id="doc-9",
    )
    assert env["tombstone_origin_id"] == "doc-9"
    assert env["event_type"] == "memory.tombstone"


def test_all_event_types_build():
    for et in (
        "scope.dossier.upsert",
        "intent.revision.accepted",
        "intent.revision.superseded",
        "document.version.ready",
        "evidence.snapshot.update",
        "memory.tombstone",
    ):
        env = build_envelope(
            event_type=et,  # type: ignore[arg-type]
            tenant_id=uuid.uuid4(),
            dossier_id=uuid.uuid4(),
            external_tenant_id="ext",
            items=[{"origin_id": "o", "text": "t"}] if et != "memory.tombstone" else [],
            tombstone_origin_id="o" if et == "memory.tombstone" else None,
        )
        assert env["event_type"] == et
