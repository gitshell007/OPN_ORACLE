"""Unit tests for versioned dossier intent (MEMSOL-03)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from opn_oracle.oracle.intent import (
    IntentConflict,
    IntentNotFound,
    IntentValidationError,
    _parse_draft_fields,
    accept_revision,
    compute_intent_content_hash,
    create_draft,
    create_offering,
    create_requirement,
    get_current_intent,
    list_offerings,
    list_requirements,
    reject_revision,
    serialize_intent_revision,
    update_draft,
)
from opn_oracle.tenants.context import TenantContext, TenantContextMissing, tenant_context


def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_key": "market",
        "schema_version": "v1",
        "request_text": "Evaluar entrada al mercado de almacenamiento en ES y US",
        "structured_spec": {
            "own_offer": "Integración de BESS",
            "decision_to_make": "Entrar o no en 12 meses",
            "geographies": ["ES", "US"],
        },
        "source_refs": [{"kind": "profile_config", "ref": "market.v1"}],
    }
    base.update(overrides)
    return base


def test_content_hash_is_stable_and_sensitive_to_payload() -> None:
    first = compute_intent_content_hash(
        schema_key="market",
        schema_version="v1",
        request_text="hola",
        structured_spec={"a": 1, "b": 2},
    )
    second = compute_intent_content_hash(
        schema_key="market",
        schema_version="v1",
        request_text="hola",
        structured_spec={"b": 2, "a": 1},
    )
    third = compute_intent_content_hash(
        schema_key="market",
        schema_version="v1",
        request_text="hola!",
        structured_spec={"a": 1, "b": 2},
    )
    assert first == second
    assert len(first) == 64
    assert first != third
    assert first == first.lower()


def test_parse_draft_rejects_invalid_schema_and_empty_text() -> None:
    with pytest.raises(IntentValidationError) as invalid_key:
        _parse_draft_fields(_payload(schema_key="unknown"))
    assert "schema_key" in invalid_key.value.errors

    with pytest.raises(IntentValidationError) as empty_text:
        _parse_draft_fields(_payload(request_text="   "))
    assert "request_text" in empty_text.value.errors

    with pytest.raises(IntentValidationError) as bad_version:
        _parse_draft_fields(_payload(schema_version="1"))
    assert "schema_version" in bad_version.value.errors


def test_service_requires_tenant_context() -> None:
    session = MagicMock()
    with pytest.raises(TenantContextMissing):
        create_draft(
            session,
            dossier_id=uuid.uuid4(),
            payload=_payload(),
            actor_id=uuid.uuid4(),
        )


def _revision(
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    status: str = "draft",
    version: int = 1,
    row_version: int = 1,
) -> SimpleNamespace:
    fields = _parse_draft_fields(_payload())
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        version=version,
        schema_key=fields["schema_key"],
        schema_version=fields["schema_version"],
        request_text=fields["request_text"],
        structured_spec=fields["structured_spec"],
        status=status,
        content_hash=fields["content_hash"],
        source_refs=fields["source_refs"],
        proposed_by_user_id=uuid.uuid4(),
        accepted_by_user_id=None,
        accepted_at=None,
        row_version=row_version,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_accept_supersedes_previous_and_sets_current(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    previous = _revision(tenant_id=tenant_id, dossier_id=dossier_id, status="accepted", version=1)
    draft = _revision(tenant_id=tenant_id, dossier_id=dossier_id, status="draft", version=2)
    dossier = SimpleNamespace(
        id=dossier_id,
        tenant_id=tenant_id,
        status="active",
        current_intent_revision_id=previous.id,
    )
    session = MagicMock()
    # get_revision -> draft; _load_dossier -> dossier; previous accepted query
    session.scalar.side_effect = [draft, dossier, previous]
    audits: list[str] = []

    def _audit(*_args: Any, **kwargs: Any) -> None:
        audits.append(str(kwargs.get("action")))

    monkeypatch.setattr("opn_oracle.oracle.intent.append_audit_event", _audit)

    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=actor_id)):
        accepted = accept_revision(session, revision_id=draft.id, actor_id=actor_id)

    assert accepted.status == "accepted"
    assert accepted.accepted_by_user_id == actor_id
    assert accepted.accepted_at is not None
    assert previous.status == "superseded"
    assert dossier.current_intent_revision_id == draft.id
    assert "intent.accepted" in audits
    assert "intent.superseded" in audits
    # Accept must not schedule external automation side-effects.
    assert not any("monitor" in action for action in audits)
    session.commit.assert_called_once()


def test_accept_rejects_non_draft() -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    accepted = _revision(tenant_id=tenant_id, dossier_id=dossier_id, status="accepted")
    session = MagicMock()
    session.scalar.return_value = accepted
    with (
        tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())),
        pytest.raises(IntentConflict),
    ):
        accept_revision(session, revision_id=accepted.id, actor_id=uuid.uuid4())


def test_update_draft_version_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    draft = _revision(tenant_id=tenant_id, dossier_id=dossier_id, row_version=2)
    session = MagicMock()
    session.scalar.return_value = draft
    monkeypatch.setattr("opn_oracle.oracle.intent.append_audit_event", lambda *a, **k: None)
    with (
        tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())),
        pytest.raises(IntentConflict, match="cambió"),
    ):
        update_draft(
            session,
            revision_id=draft.id,
            payload={"request_text": "texto actualizado"},
            expected_row_version=1,
            actor_id=uuid.uuid4(),
        )


def test_update_draft_bumps_row_version(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    draft = _revision(tenant_id=tenant_id, dossier_id=dossier_id, row_version=1)
    session = MagicMock()
    session.scalar.return_value = draft
    monkeypatch.setattr("opn_oracle.oracle.intent.append_audit_event", lambda *a, **k: None)
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        updated = update_draft(
            session,
            revision_id=draft.id,
            payload={"request_text": "texto actualizado del draft"},
            expected_row_version=1,
            actor_id=uuid.uuid4(),
        )
    assert updated.row_version == 2
    assert updated.request_text == "texto actualizado del draft"
    assert updated.status == "draft"
    session.commit.assert_called_once()


def test_reject_draft_is_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    draft = _revision(tenant_id=tenant_id, dossier_id=dossier_id)
    session = MagicMock()
    session.scalar.return_value = draft
    monkeypatch.setattr("opn_oracle.oracle.intent.append_audit_event", lambda *a, **k: None)
    actor_id = uuid.uuid4()
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=actor_id)):
        rejected = reject_revision(session, revision_id=draft.id, actor_id=actor_id)
        assert rejected.status == "rejected"
        with pytest.raises(IntentConflict):
            reject_revision(session, revision_id=draft.id, actor_id=actor_id)


def test_get_current_intent_scopes_to_tenant() -> None:
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    dossier_id = uuid.uuid4()
    session = MagicMock()
    session.scalar.return_value = None
    with (
        tenant_context(TenantContext(tenant_id=tenant_a, actor_id=uuid.uuid4())),
        pytest.raises(IntentNotFound),
    ):
        get_current_intent(session, dossier_id)
    # tenant_b context with missing dossier also isolates
    with (
        tenant_context(TenantContext(tenant_id=tenant_b, actor_id=uuid.uuid4())),
        pytest.raises(IntentNotFound),
    ):
        get_current_intent(session, dossier_id)


def test_serialize_exposes_contract_fields() -> None:
    tenant_id = uuid.uuid4()
    revision = _revision(tenant_id=tenant_id, dossier_id=uuid.uuid4())
    payload = serialize_intent_revision(revision)  # type: ignore[arg-type]
    assert payload["status"] == "draft"
    assert payload["schema_key"] == "market"
    assert len(payload["content_hash"]) == 64
    assert payload["version"] == 1
    assert payload["row_version"] == 1


def test_create_requirement_persists_validated_intake_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, dossier_id, intent_id = (uuid.uuid4() for _ in range(3))
    dossier = SimpleNamespace(id=dossier_id, current_intent_revision_id=intent_id)
    session = MagicMock()
    monkeypatch.setattr("opn_oracle.oracle.intent._load_dossier", lambda *_args: dossier)
    monkeypatch.setattr("opn_oracle.oracle.intent.get_revision", lambda *_args: object())
    monkeypatch.setattr("opn_oracle.oracle.intent.append_audit_event", lambda *a, **k: None)

    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        requirement = create_requirement(
            session,
            dossier_id=dossier_id,
            actor_id=uuid.uuid4(),
            payload={
                "class": "market_scan",
                "priority": "high",
                "question": "¿Qué competidores operan en Estados Unidos?",
                "decision_to_support": "Priorizar entrada de mercado.",
                "scope": {"geographies": ["US"]},
                "exclusions": {"sources": ["rumours"]},
                "success_criteria": ["Tres actores con evidencia"],
                "intent_revision_id": str(intent_id),
            },
        )

    assert requirement.tenant_id == tenant_id
    assert requirement.intent_revision_id == intent_id
    assert requirement.requirement_class == "market_scan"
    assert requirement.success_criteria == ["Tres actores con evidencia"]
    session.add.assert_called_once_with(requirement)
    session.commit.assert_called_once()


def test_create_offering_persists_validated_product_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, dossier_id, intent_id = (uuid.uuid4() for _ in range(3))
    dossier = SimpleNamespace(id=dossier_id, current_intent_revision_id=intent_id)
    session = MagicMock()
    monkeypatch.setattr("opn_oracle.oracle.intent._load_dossier", lambda *_args: dossier)
    monkeypatch.setattr("opn_oracle.oracle.intent.get_revision", lambda *_args: object())
    monkeypatch.setattr("opn_oracle.oracle.intent.append_audit_event", lambda *a, **k: None)

    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        offering = create_offering(
            session,
            dossier_id=dossier_id,
            actor_id=uuid.uuid4(),
            payload={
                "name": "Plataforma de almacenamiento",
                "aliases": ["BESS", "  "],
                "taxonomies": {"cpv": ["31422000"]},
                "description": "Oferta para almacenamiento energético.",
                "status": "active",
                "intent_revision_id": str(intent_id),
            },
        )

    assert offering.tenant_id == tenant_id
    assert offering.intent_revision_id == intent_id
    assert offering.aliases == ["BESS"]
    assert offering.taxonomies == {"cpv": ["31422000"]}
    session.add.assert_called_once_with(offering)
    session.commit.assert_called_once()


@pytest.mark.parametrize(
    ("factory", "payload"),
    [
        (create_requirement, {"class": "invalid"}),
        (create_requirement, {"class": "market_scan", "priority": "invalid"}),
        (create_requirement, {"class": "market_scan", "status": "invalid"}),
        (create_offering, {"name": ""}),
        (create_offering, {"name": "Oferta", "aliases": "invalid"}),
        (create_offering, {"name": "Oferta", "taxonomies": "invalid"}),
    ],
)
def test_intake_rejects_invalid_requirement_and_offering_payloads(
    monkeypatch: pytest.MonkeyPatch,
    factory: Any,
    payload: dict[str, Any],
) -> None:
    tenant_id, dossier_id = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(
        "opn_oracle.oracle.intent._load_dossier",
        lambda *_args: SimpleNamespace(id=dossier_id, current_intent_revision_id=None),
    )
    with (
        tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())),
        pytest.raises(IntentValidationError),
    ):
        factory(MagicMock(), dossier_id=dossier_id, actor_id=uuid.uuid4(), payload=payload)


def test_list_intake_resources_scopes_to_active_tenant() -> None:
    tenant_id, dossier_id = uuid.uuid4(), uuid.uuid4()
    session = MagicMock()
    session.scalars.return_value = [SimpleNamespace(id=uuid.uuid4())]
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        assert len(list_requirements(session, dossier_id)) == 1
        assert len(list_offerings(session, dossier_id)) == 1


def test_create_draft_assigns_monotonic_version(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    dossier = SimpleNamespace(
        id=dossier_id,
        tenant_id=tenant_id,
        status="active",
        current_intent_revision_id=None,
    )
    session = MagicMock()
    # _load_dossier, _next_version max
    session.scalar.side_effect = [dossier, 3]
    created: list[Any] = []

    def _add(obj: Any) -> None:
        created.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(UTC)
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = datetime.now(UTC)

    session.add.side_effect = _add
    monkeypatch.setattr("opn_oracle.oracle.intent.append_audit_event", lambda *a, **k: None)

    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=actor_id)):
        revision = create_draft(
            session,
            dossier_id=dossier_id,
            payload=_payload(),
            actor_id=actor_id,
        )
    assert revision.version == 4
    assert revision.status == "draft"
    assert revision.proposed_by_user_id == actor_id
    assert revision.tenant_id == tenant_id
    session.commit.assert_called_once()
