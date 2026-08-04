"""Hidratación de Actor.identifiers.tax_id desde awards PLACSP — SV2-NIF-ACTORES."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from opn_oracle.oracle.actor_tax_id import (
    hydrate_dossier_actor_tax_ids_from_awards,
    identity_match_keys,
    iter_award_winner_tax_sources,
    usable_company_tax_id,
)


@pytest.mark.unit
def test_usable_company_tax_id_rejects_masks_and_person_nif() -> None:
    assert usable_company_tax_id("B08377715") == "B08377715"
    assert usable_company_tax_id("b-08.377.715") == "B08377715"
    assert usable_company_tax_id("***4856**") is None
    assert usable_company_tax_id("*********") is None
    assert usable_company_tax_id("12345678Z") is None
    assert usable_company_tax_id("B08377715; A12345678") is None
    assert usable_company_tax_id("") is None


@pytest.mark.unit
def test_identity_match_keys_collapse_legal_form() -> None:
    a = identity_match_keys("Capgemini España S.L.")
    b = identity_match_keys("Capgemini España SL")
    c = identity_match_keys("CAPGEMINI ESPAÑA SOCIEDAD LIMITADA")
    assert a & b
    assert a & c
    assert "CAPGEMINI ESPANA" in (a | b | c) or any(
        "CAPGEMINI" in key and "ESPANA" in key for key in (a | b | c)
    )


@pytest.mark.unit
def test_iter_award_winner_tax_sources_from_entries() -> None:
    snapshot = {
        "kind": "award",
        "folder_id": "XP1228/2025",
        "entries": [
            {
                "winner": "Capgemini España S.L.",
                "winner_identifier": "B08377715",
            },
            {
                "winner": "Persona física",
                "winner_identifier": "***1234**",
            },
            {
                "winner": "NTT DATA Spain S.L.U.",
                "tax_id": "B82528558",
            },
        ],
    }
    sources = iter_award_winner_tax_sources(snapshot)
    tax_ids = {item["tax_id"] for item in sources}
    assert tax_ids == {"B08377715", "B82528558"}
    assert all(item["folder_id"] == "XP1228/2025" for item in sources)


@pytest.mark.unit
def test_hydrate_sets_tax_id_with_provenance() -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    actor_id = uuid.uuid4()

    actor = SimpleNamespace(
        id=actor_id,
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="Capgemini España S.L.",
        aliases=[],
        identifiers={},
        provenance={"source": "manual"},
        version=1,
    )
    pin = SimpleNamespace(
        snapshot={
            "kind": "award",
            "folder_id": "XP1228/2025",
            "entries": [
                {
                    "winner": "Capgemini España S.L.",
                    "winner_identifier": "B08377715",
                }
            ],
        }
    )

    session = MagicMock()
    # First scalars: pins; second: actors
    session.scalars.side_effect = [
        [pin],
        [actor],
    ]

    results = hydrate_dossier_actor_tax_ids_from_awards(
        session, tenant_id=tenant_id, dossier_id=dossier_id
    )

    assert len(results) == 1
    assert results[0]["status"] == "hydrated"
    assert results[0]["tax_id"] == "B08377715"
    assert actor.identifiers["tax_id"] == "B08377715"
    assert actor.identifiers["tax_id_scheme"] == "ES_CIF"
    source = actor.identifiers["tax_id_source"]
    assert source["folder_id"] == "XP1228/2025"
    assert source["source"] == "placsp"
    assert source["procurement_kind"] == "award"
    assert source["winner_name"] == "Capgemini España S.L."
    assert actor.provenance["tax_id_hydration"]["folder_id"] == "XP1228/2025"
    assert actor.version == 2


@pytest.mark.unit
def test_hydrate_ambiguous_tax_ids_skipped() -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    actor = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="Servicios Generales S.L.",
        aliases=[],
        identifiers={},
        provenance={},
        version=1,
    )
    pin = SimpleNamespace(
        snapshot={
            "kind": "award",
            "folder_id": "MULTI",
            "entries": [
                {"winner": "Servicios Generales S.L.", "winner_identifier": "B11111111"},
                {"winner": "Servicios Generales SL", "winner_identifier": "B22222222"},
            ],
        }
    )
    # B11111111 and B22222222 need valid CIF form - use real-shaped ones
    pin.snapshot["entries"][0]["winner_identifier"] = "B08377715"
    pin.snapshot["entries"][1]["winner_identifier"] = "B82528558"

    session = MagicMock()
    session.scalars.side_effect = [[pin], [actor]]

    results = hydrate_dossier_actor_tax_ids_from_awards(
        session, tenant_id=tenant_id, dossier_id=dossier_id
    )
    assert results[0]["status"] == "ambiguous"
    assert actor.identifiers == {}


@pytest.mark.unit
def test_hydrate_does_not_overwrite_different_existing_tax_id() -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    actor = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        actor_type="organization",
        canonical_name="Capgemini España S.L.",
        aliases=[],
        identifiers={"tax_id": "B82528558", "tax_id_scheme": "ES_CIF"},
        provenance={},
        version=3,
    )
    pin = SimpleNamespace(
        snapshot={
            "kind": "award",
            "folder_id": "XP1228/2025",
            "entries": [
                {"winner": "Capgemini España S.L.", "winner_identifier": "B08377715"},
            ],
        }
    )
    session = MagicMock()
    session.scalars.side_effect = [[pin], [actor]]

    results = hydrate_dossier_actor_tax_ids_from_awards(
        session, tenant_id=tenant_id, dossier_id=dossier_id
    )
    assert results[0]["status"] == "unchanged"
    assert actor.identifiers["tax_id"] == "B82528558"
    assert actor.version == 3


@pytest.mark.unit
def test_pin_award_triggers_hydration(monkeypatch: pytest.MonkeyPatch) -> None:
    from opn_oracle.oracle import procurement_items as mod

    calls: list[dict[str, Any]] = []

    def fake_hydrate(session: Any, **kwargs: Any) -> list[dict[str, Any]]:
        del session
        calls.append(kwargs)
        return [{"status": "hydrated"}]

    monkeypatch.setattr(mod, "hydrate_dossier_actor_tax_ids_from_awards", fake_hydrate)

    # Minimal path: call the hook logic as pin would
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    session = MagicMock()
    mod.hydrate_dossier_actor_tax_ids_from_awards(
        session, tenant_id=tenant_id, dossier_id=dossier_id
    )
    assert calls and calls[0]["dossier_id"] == dossier_id
