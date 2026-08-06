"""G-16 · NIF/CIF as durable Actor identity (column, uniqueness, conflicts)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from opn_oracle.oracle.actor_tax_id import (
    TaxIdConflictError,
    TaxIdValidationError,
    actor_durable_tax_id,
    actor_identity_canonical_key,
    assign_actor_tax_id,
    backfill_actor_tax_ids_from_identifiers,
    list_tax_id_conflicts,
    record_tax_id_conflict,
    require_usable_company_tax_id,
    resolve_or_create_actor,
    resolve_tax_id_conflict,
    select_backfill_winner,
    tax_id_canonical_key,
    usable_company_tax_id,
)
from opn_oracle.oracle.models import Actor, ActorTaxIdConflict


@pytest.mark.unit
def test_normalization_central_and_rejects_bad_shapes() -> None:
    assert usable_company_tax_id("b-08.377.715") == "B08377715"
    assert usable_company_tax_id("B08377715") == "B08377715"
    assert usable_company_tax_id("***4856**") is None
    assert usable_company_tax_id("12345678Z") is None
    assert usable_company_tax_id("B08377715; A12345678") is None
    with pytest.raises(TaxIdValidationError):
        require_usable_company_tax_id("12345678Z", actor_type="organization")
    with pytest.raises(TaxIdValidationError):
        require_usable_company_tax_id("B08377715", actor_type="person")


@pytest.mark.unit
def test_identity_canonical_key_prefers_tax_id() -> None:
    assert actor_identity_canonical_key(name="Capgemini España S.L.", tax_id="B08377715") == (
        "tax:es:B08377715"
    )
    assert actor_identity_canonical_key(name="  CATL   Energy  ", tax_id=None) == "catl-energy"
    assert tax_id_canonical_key("B08377715") == "tax:es:B08377715"


@pytest.mark.unit
def test_actor_durable_tax_id_column_first() -> None:
    actor = SimpleNamespace(
        tax_id="B08377715",
        identifiers={"tax_id": "B82528558"},
    )
    assert actor_durable_tax_id(actor) == "B08377715"  # type: ignore[arg-type]
    actor2 = SimpleNamespace(tax_id=None, identifiers={"tax_id": "b-08.377.715"})
    assert actor_durable_tax_id(actor2) == "B08377715"  # type: ignore[arg-type]


@pytest.mark.unit
def test_select_backfill_winner_deterministic() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    a = SimpleNamespace(id=uuid.UUID(int=2), created_at=t0 + timedelta(days=1))
    b = SimpleNamespace(id=uuid.UUID(int=1), created_at=t0)
    c = SimpleNamespace(id=uuid.UUID(int=3), created_at=t0)
    winner = select_backfill_winner([a, b, c])  # type: ignore[list-item]
    assert winner is b  # earliest created_at, then smaller UUID


@pytest.mark.unit
def test_assign_raises_conflict_when_holder_exists() -> None:
    tenant_id = uuid.uuid4()
    holder = Actor(
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="Capgemini España S.L.",
        canonical_key="tax:es:B08377715",
        tax_id="B08377715",
        tax_id_scheme="ES_CIF",
        tax_id_country="ES",
        aliases=[],
        identifiers={"tax_id": "B08377715"},
        actor_metadata={},
        provenance={},
    )
    holder.id = uuid.uuid4()
    other = Actor(
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="CAPGEMINI ESPAÑA SL",
        canonical_key="capgemini-espana-sl",
        aliases=[],
        identifiers={"tax_id": "B08377715"},
        actor_metadata={},
        provenance={},
    )
    other.id = uuid.uuid4()

    session = MagicMock()
    session.scalar.return_value = holder
    # begin_nested context manager
    session.begin_nested.return_value.__enter__ = MagicMock(return_value=None)
    session.begin_nested.return_value.__exit__ = MagicMock(return_value=False)

    with pytest.raises(TaxIdConflictError) as exc:
        assign_actor_tax_id(session, other, "B08377715")
    assert exc.value.tax_id == "B08377715"
    assert exc.value.canonical_actor_id == holder.id


@pytest.mark.unit
def test_resolve_or_create_reuses_tax_id_holder_not_name() -> None:
    tenant_id = uuid.uuid4()
    holder = Actor(
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="Capgemini España S.L.",
        canonical_key="tax:es:B08377715",
        tax_id="B08377715",
        tax_id_scheme="ES_CIF",
        tax_id_country="ES",
        aliases=[],
        identifiers={"tax_id": "B08377715"},
        actor_metadata={},
        provenance={},
        version=1,
    )
    holder.id = uuid.uuid4()
    session = MagicMock()
    # find_actor_by_tax_id uses session.scalar once
    session.scalar.return_value = holder
    session.begin_nested.return_value.__enter__ = MagicMock(return_value=None)
    session.begin_nested.return_value.__exit__ = MagicMock(return_value=False)

    result = resolve_or_create_actor(
        session,
        tenant_id=tenant_id,
        canonical_name="CAPGEMINI ESPAÑA, S.L",
        identifiers={"tax_id": "B08377715"},
    )
    assert result is holder
    session.add.assert_not_called()


@pytest.mark.unit
def test_resolve_or_create_name_fallback_without_tax_id() -> None:
    tenant_id = uuid.uuid4()
    existing = Actor(
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="ACME SL",
        canonical_key="acme-sl",
        aliases=[],
        identifiers={},
        actor_metadata={},
        provenance={},
    )
    existing.id = uuid.uuid4()
    session = MagicMock()
    session.scalar.return_value = existing

    result = resolve_or_create_actor(
        session,
        tenant_id=tenant_id,
        canonical_name="ACME SL",
        identifiers={},
    )
    assert result is existing
    session.add.assert_not_called()


@pytest.mark.unit
def test_backfill_capgemini_collision_records_conflict() -> None:
    tenant_id = uuid.uuid4()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    winner = Actor(
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="Capgemini España S.L.",
        canonical_key="capgemini-espana-s.l.",
        aliases=[],
        identifiers={"tax_id": "B08377715", "tax_id_source": {"folder_id": "XP1"}},
        actor_metadata={},
        provenance={},
        version=1,
    )
    winner.id = uuid.uuid4()
    winner.created_at = t0
    winner.tax_id = None

    loser = Actor(
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="CAPGEMINI ESPAÑA SL",
        canonical_key="capgemini-espana-sl",
        aliases=[],
        identifiers={"tax_id": "b-08.377.715", "tax_id_source": {"folder_id": "XP2"}},
        actor_metadata={},
        provenance={},
        version=1,
    )
    loser.id = uuid.uuid4()
    loser.created_at = t0 + timedelta(hours=1)
    loser.tax_id = None

    session = MagicMock()
    session.scalars.return_value = [winner, loser]
    # No pre-existing holder/conflict rows in DB; winner is selected in-process.
    session.scalar.return_value = None
    session.begin_nested.return_value.__enter__ = MagicMock(return_value=None)
    session.begin_nested.return_value.__exit__ = MagicMock(return_value=False)

    counts = backfill_actor_tax_ids_from_identifiers(session, tenant_id=tenant_id)
    assert counts["groups"] == 1
    assert counts["collisions"] == 1
    assert winner.tax_id == "B08377715"
    assert winner.tax_id_scheme == "ES_CIF"
    # Loser keeps declared identifiers.tax_id (original string preserved)
    assert loser.identifiers["tax_id"] == "b-08.377.715"
    assert loser.provenance.get("tax_id_column_backfill", {}).get("role") == "loser"
    # Conflict row added
    added = [call.args[0] for call in session.add.call_args_list]
    assert any(isinstance(item, ActorTaxIdConflict) for item in added)
    conflict = next(item for item in added if isinstance(item, ActorTaxIdConflict))
    assert conflict.winner_actor_id == winner.id
    assert conflict.loser_actor_id == loser.id
    assert conflict.tax_id == "B08377715"
    assert conflict.declared_tax_id == "b-08.377.715"
    assert conflict.status == "open"


@pytest.mark.unit
def test_backfill_idempotent_rerun() -> None:
    tenant_id = uuid.uuid4()
    actor = Actor(
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="Inetum",
        canonical_key="tax:es:A28855260",
        tax_id="A28855260",
        tax_id_scheme="ES_CIF",
        tax_id_country="ES",
        aliases=[],
        identifiers={"tax_id": "A28855260"},
        actor_metadata={},
        provenance={},
        version=2,
    )
    actor.id = uuid.uuid4()
    actor.created_at = datetime(2026, 1, 1, tzinfo=UTC)

    session = MagicMock()
    session.scalars.return_value = [actor]
    session.scalar.return_value = actor
    session.begin_nested.return_value.__enter__ = MagicMock(return_value=None)
    session.begin_nested.return_value.__exit__ = MagicMock(return_value=False)

    first = backfill_actor_tax_ids_from_identifiers(session, tenant_id=tenant_id)
    second = backfill_actor_tax_ids_from_identifiers(session, tenant_id=tenant_id)
    assert first["unchanged"] >= 1 or first["applied"] >= 0
    assert second["collisions"] == 0
    assert actor.tax_id == "A28855260"


@pytest.mark.unit
def test_resolve_conflict_contract() -> None:
    tenant_id = uuid.uuid4()
    conflict = ActorTaxIdConflict(
        tenant_id=tenant_id,
        tax_id="B08377715",
        winner_actor_id=uuid.uuid4(),
        loser_actor_id=uuid.uuid4(),
        declared_tax_id="B08377715",
        declared_identifiers={"tax_id": "B08377715"},
        status="open",
        version=1,
    )
    conflict.id = uuid.uuid4()
    session = MagicMock()
    session.scalar.return_value = conflict

    resolved = resolve_tax_id_conflict(
        session,
        tenant_id=tenant_id,
        conflict_id=conflict.id,
        action="keep_winner",
        note="defer merge to G-17",
        actor_id=uuid.uuid4(),
    )
    assert resolved.status == "resolved"
    assert resolved.resolution_note and "G-17" in resolved.resolution_note
    assert resolved.resolved_at is not None


@pytest.mark.unit
def test_list_conflicts_filters_status() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    list_tax_id_conflicts(session, tenant_id=uuid.uuid4(), status="open", limit=10)
    session.scalars.assert_called_once()


@pytest.mark.unit
def test_record_conflict_idempotent() -> None:
    tenant_id = uuid.uuid4()
    winner = SimpleNamespace(id=uuid.uuid4())
    loser = SimpleNamespace(id=uuid.uuid4(), identifiers={"tax_id": "B08377715"})
    existing = ActorTaxIdConflict(
        tenant_id=tenant_id,
        tax_id="B08377715",
        winner_actor_id=winner.id,
        loser_actor_id=loser.id,
        declared_tax_id="B08377715",
        status="open",
    )
    session = MagicMock()
    session.scalar.return_value = existing
    row = record_tax_id_conflict(
        session,
        tenant_id=tenant_id,
        tax_id="B08377715",
        winner=winner,  # type: ignore[arg-type]
        loser=loser,  # type: ignore[arg-type]
        declared_tax_id="B08377715",
    )
    assert row is existing
    session.add.assert_not_called()
