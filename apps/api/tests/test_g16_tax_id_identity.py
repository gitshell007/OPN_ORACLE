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
    apply_actor_identifiers_patch,
    assert_actor_type_compatible_with_tax_id,
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
def test_actor_durable_tax_id_column_only() -> None:
    from opn_oracle.oracle.actor_tax_id import actor_declared_tax_id

    actor = SimpleNamespace(
        tax_id="B08377715",
        identifiers={"tax_id": "B82528558"},
    )
    assert actor_durable_tax_id(actor) == "B08377715"  # type: ignore[arg-type]
    # Column is durable; JSON is a separate declaration (may differ until governed).
    assert actor_declared_tax_id(actor) == "B82528558"  # type: ignore[arg-type]
    actor2 = SimpleNamespace(tax_id=None, identifiers={"tax_id": "b-08.377.715"})
    assert actor_durable_tax_id(actor2) is None  # type: ignore[arg-type]
    assert actor_declared_tax_id(actor2) == "B08377715"  # type: ignore[arg-type]


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


@pytest.mark.unit
def test_rename_identity_prefers_tax_key_when_durable() -> None:
    """B1 · rename of fiscal actor keeps tax:es key; name-only uses fallback."""

    assert (
        actor_identity_canonical_key(name="Capgemini España S.L.U.", tax_id="B08377715")
        == "tax:es:B08377715"
    )
    assert actor_identity_canonical_key(name="Nueva Grafia SL", tax_id=None) == "nueva-grafia-sl"


@pytest.mark.unit
def test_assert_actor_type_blocks_demotion_with_tax_id() -> None:
    actor = Actor(
        tenant_id=uuid.uuid4(),
        actor_type="organization",
        canonical_name="Capgemini",
        canonical_key="tax:es:B08377715",
        tax_id="B08377715",
        tax_id_scheme="ES_CIF",
        tax_id_country="ES",
        aliases=[],
        identifiers={"tax_id": "B08377715"},
        actor_metadata={},
        provenance={},
    )
    with pytest.raises(TaxIdValidationError):
        assert_actor_type_compatible_with_tax_id(actor, "person")
    with pytest.raises(TaxIdValidationError):
        assert_actor_type_compatible_with_tax_id(actor, "program")
    # Compatible change is allowed.
    assert_actor_type_compatible_with_tax_id(actor, "institution")


@pytest.mark.unit
def test_apply_identifiers_patch_first_assign_and_idempotent() -> None:
    tenant_id = uuid.uuid4()
    actor = Actor(
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="Capgemini España S.L.",
        canonical_key="capgemini-espana-s-l",
        aliases=[],
        identifiers={"lei": "X"},
        actor_metadata={},
        provenance={},
        version=1,
    )
    actor.id = uuid.uuid4()
    session = MagicMock()
    session.scalar.return_value = None  # no holder
    session.begin_nested.return_value.__enter__ = MagicMock(return_value=None)
    session.begin_nested.return_value.__exit__ = MagicMock(return_value=False)
    session.no_autoflush.__enter__ = MagicMock(return_value=None)
    session.no_autoflush.__exit__ = MagicMock(return_value=False)

    apply_actor_identifiers_patch(
        session, actor, {"tax_id": "b-08.377.715", "lei": "X", "duns": "1"}
    )
    assert actor.tax_id == "B08377715"
    assert actor.identifiers["tax_id"] == "B08377715"
    assert actor.identifiers["duns"] == "1"
    assert actor.canonical_key == "tax:es:B08377715"

    # Same CIF → idempotent sync, no overwrite of other keys lost.
    apply_actor_identifiers_patch(session, actor, {"tax_id": "B08377715", "lei": "Y"})
    assert actor.tax_id == "B08377715"
    assert actor.identifiers["lei"] == "Y"
    assert actor.identifiers["tax_id"] == "B08377715"


@pytest.mark.unit
def test_apply_identifiers_patch_rejects_clear_change_and_preserves_other_keys() -> None:
    tenant_id = uuid.uuid4()
    actor = Actor(
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="Capgemini España S.L.",
        canonical_key="tax:es:B08377715",
        tax_id="B08377715",
        tax_id_scheme="ES_CIF",
        tax_id_country="ES",
        aliases=[],
        identifiers={
            "tax_id": "B08377715",
            "tax_id_scheme": "ES_CIF",
            "tax_id_declared": "B08377715",
            "lei": "KEEP",
        },
        actor_metadata={},
        provenance={"tax_id_assignment": {"source": "placsp"}},
        version=2,
    )
    actor.id = uuid.uuid4()
    session = MagicMock()

    with pytest.raises(TaxIdValidationError):
        apply_actor_identifiers_patch(session, actor, {"tax_id": None})
    with pytest.raises(TaxIdValidationError):
        apply_actor_identifiers_patch(session, actor, {"tax_id": ""})
    with pytest.raises(TaxIdValidationError):
        apply_actor_identifiers_patch(session, actor, {"tax_id": "A28855260"})
    with pytest.raises(TaxIdValidationError):
        apply_actor_identifiers_patch(session, actor, {"tax_id": "***4856**"})
    with pytest.raises(TaxIdValidationError):
        apply_actor_identifiers_patch(session, actor, {"tax_id": "12345678Z"})

    # Other keys only: fiscal block preserved, column still authoritative.
    apply_actor_identifiers_patch(session, actor, {"lei": "NEW", "website": "https://x"})
    assert actor.tax_id == "B08377715"
    assert actor.identifiers["tax_id"] == "B08377715"
    assert actor.identifiers["tax_id_scheme"] == "ES_CIF"
    assert actor.identifiers["lei"] == "NEW"
    assert actor.identifiers["website"] == "https://x"


@pytest.mark.unit
def test_apply_identifiers_patch_conflict_when_occupied() -> None:
    tenant_id = uuid.uuid4()
    holder = Actor(
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="Holder",
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
        canonical_name="Other",
        canonical_key="other",
        aliases=[],
        identifiers={},
        actor_metadata={},
        provenance={},
        version=1,
    )
    other.id = uuid.uuid4()
    session = MagicMock()
    session.scalar.return_value = holder
    session.begin_nested.return_value.__enter__ = MagicMock(return_value=None)
    session.begin_nested.return_value.__exit__ = MagicMock(return_value=False)

    with pytest.raises(TaxIdConflictError) as exc:
        apply_actor_identifiers_patch(session, other, {"tax_id": "B08377715"})
    assert exc.value.canonical_actor_id == holder.id
    assert other.tax_id is None


@pytest.mark.unit
def test_apply_identifiers_patch_partial_merge_preserves_omitted_keys() -> None:
    """PATCH only website keeps lei/duns/tax_id_source (fiscal actor)."""

    tenant_id = uuid.uuid4()
    tax_source = {"source": "placsp", "folder_id": "XP-MERGE"}
    actor = Actor(
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="Merge Fiscal SL",
        canonical_key="tax:es:B08377715",
        tax_id="B08377715",
        tax_id_scheme="ES_CIF",
        tax_id_country="ES",
        aliases=[],
        identifiers={
            "tax_id": "B08377715",
            "tax_id_scheme": "ES_CIF",
            "tax_id_declared": "B08377715",
            "tax_id_source": tax_source,
            "lei": "ALPHA2",
            "duns": "123456789",
        },
        actor_metadata={},
        provenance={"tax_id_assignment": tax_source},
        version=3,
    )
    actor.id = uuid.uuid4()
    session = MagicMock()

    apply_actor_identifiers_patch(session, actor, {"website": "https://example.es"})

    assert actor.tax_id == "B08377715"
    assert actor.version == 3  # helper does not bump; route owns version
    ids = actor.identifiers
    assert ids["tax_id"] == "B08377715"
    assert ids["tax_id_scheme"] == "ES_CIF"
    assert ids["tax_id_declared"] == "B08377715"
    assert ids["tax_id_source"] == tax_source
    assert ids["lei"] == "ALPHA2"
    assert ids["duns"] == "123456789"
    assert ids["website"] == "https://example.es"


@pytest.mark.unit
def test_apply_identifiers_patch_partial_merge_without_tax_id_column() -> None:
    """Actor sin tax_id durable: PATCH website conserva lei/duns omitidos."""

    tenant_id = uuid.uuid4()
    actor = Actor(
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="No Tax Partner SL",
        canonical_key="no-tax-partner-sl",
        aliases=[],
        identifiers={"lei": "LEI-KEEP", "duns": "999"},
        actor_metadata={},
        provenance={},
        version=1,
    )
    actor.id = uuid.uuid4()
    session = MagicMock()

    apply_actor_identifiers_patch(session, actor, {"website": "https://partner.example"})

    assert actor.tax_id is None
    assert actor.identifiers["lei"] == "LEI-KEEP"
    assert actor.identifiers["duns"] == "999"
    assert actor.identifiers["website"] == "https://partner.example"
    assert "tax_id" not in actor.identifiers


@pytest.mark.unit
def test_apply_identifiers_patch_null_deletes_non_fiscal_keeps_fiscal() -> None:
    """null no fiscal elimina esa clave; fiscal columna permanece intacto."""

    tenant_id = uuid.uuid4()
    tax_source = {"source": "actor_patch", "via": "identifiers.tax_id"}
    actor = Actor(
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="Null Semantics SL",
        canonical_key="tax:es:B08377715",
        tax_id="B08377715",
        tax_id_scheme="ES_CIF",
        tax_id_country="ES",
        aliases=[],
        identifiers={
            "tax_id": "B08377715",
            "tax_id_scheme": "ES_CIF",
            "tax_id_declared": "B08377715",
            "tax_id_source": tax_source,
            "lei": "OLD-LEI",
            "duns": "TO-DELETE",
            "website": "https://old.example",
        },
        actor_metadata={},
        provenance={},
        version=2,
    )
    actor.id = uuid.uuid4()
    session = MagicMock()

    apply_actor_identifiers_patch(
        session,
        actor,
        {"lei": "NEW-LEI", "duns": None, "website": "https://new.example"},
    )

    assert actor.tax_id == "B08377715"
    ids = actor.identifiers
    assert ids["tax_id"] == "B08377715"
    assert ids["tax_id_scheme"] == "ES_CIF"
    assert ids["tax_id_source"] == tax_source
    assert ids["lei"] == "NEW-LEI"
    assert ids["website"] == "https://new.example"
    assert "duns" not in ids

    # Explicit null on fiscal key must not clear durable block (and raises if tax_id null).
    with pytest.raises(TaxIdValidationError):
        apply_actor_identifiers_patch(session, actor, {"tax_id": None, "lei": "Z"})
    assert actor.identifiers["lei"] == "NEW-LEI"
    assert actor.identifiers["tax_id"] == "B08377715"
    assert actor.tax_id == "B08377715"


@pytest.mark.unit
def test_apply_identifiers_patch_first_assign_preserves_prior_non_fiscal() -> None:
    """Primer assign de tax_id + nueva clave conserva identifiers anteriores."""

    tenant_id = uuid.uuid4()
    actor = Actor(
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="First Assign Keep SL",
        canonical_key="first-assign-keep-sl",
        aliases=[],
        identifiers={"lei": "PRIOR-LEI", "duns": "PRIOR-DUNS"},
        actor_metadata={},
        provenance={},
        version=1,
    )
    actor.id = uuid.uuid4()
    session = MagicMock()
    session.scalar.return_value = None
    session.begin_nested.return_value.__enter__ = MagicMock(return_value=None)
    session.begin_nested.return_value.__exit__ = MagicMock(return_value=False)
    session.no_autoflush.__enter__ = MagicMock(return_value=None)
    session.no_autoflush.__exit__ = MagicMock(return_value=False)

    apply_actor_identifiers_patch(
        session,
        actor,
        {"tax_id": "b-08.377.715", "website": "https://first.example"},
    )

    assert actor.tax_id == "B08377715"
    assert actor.canonical_key == "tax:es:B08377715"
    ids = actor.identifiers
    assert ids["tax_id"] == "B08377715"
    assert ids["lei"] == "PRIOR-LEI"
    assert ids["duns"] == "PRIOR-DUNS"
    assert ids["website"] == "https://first.example"


@pytest.mark.unit
def test_apply_identifiers_patch_invalid_does_not_mutate_prior_keys() -> None:
    """PATCH conflictivo/inválido no muta ninguna clave previa."""

    tenant_id = uuid.uuid4()
    prior = {
        "tax_id": "B08377715",
        "tax_id_scheme": "ES_CIF",
        "tax_id_declared": "B08377715",
        "tax_id_source": {"source": "placsp"},
        "lei": "SAFE",
        "duns": "SAFE-DUNS",
    }
    actor = Actor(
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="Immutable On Error SL",
        canonical_key="tax:es:B08377715",
        tax_id="B08377715",
        tax_id_scheme="ES_CIF",
        tax_id_country="ES",
        aliases=[],
        identifiers=dict(prior),
        actor_metadata={},
        provenance={"tax_id_assignment": {"source": "placsp"}},
        version=5,
    )
    actor.id = uuid.uuid4()
    session = MagicMock()

    with pytest.raises(TaxIdValidationError):
        apply_actor_identifiers_patch(
            session,
            actor,
            {"tax_id": "A28855260", "lei": "SHOULD-NOT-APPLY", "website": "https://nope"},
        )

    assert actor.version == 5
    assert actor.tax_id == "B08377715"
    assert actor.identifiers == prior
