from __future__ import annotations

from opn_oracle.oracle.actor_candidates import (
    actor_canonical_key,
    clean_labels,
    extract_signal_entities,
)


def test_actor_candidate_normalization_is_deterministic() -> None:
    assert actor_canonical_key("  CATL   Energy  ") == "catl-energy"
    assert clean_labels(["Fabricante", " fabricante ", "Baterías", ""]) == [
        "Fabricante",
        "Baterías",
    ]


def test_signal_entity_extraction_combines_provider_payload_and_text() -> None:
    entities = extract_signal_entities(
        [{"type": "person", "name": "Ana Torres"}],
        raw_payload={"analysis": {"companies": [{"name": "Northvolt", "type": "company"}]}},
        title="Mercado de baterías en Europa",
        summary=(
            "CATL defiende su planta de baterías en Zaragoza con una inversión de 4.100 "
            "millones de euros junto a Stellantis."
        ),
    )

    by_name = {entity["name"]: entity for entity in entities}
    assert set(by_name) == {"Ana Torres", "Northvolt", "CATL", "Stellantis"}
    assert by_name["Ana Torres"]["type"] == "person"
    assert by_name["Northvolt"]["extraction_method"] == "payload"
    assert by_name["CATL"]["extraction_method"] == "text_pattern"
    assert by_name["Stellantis"]["type"] == "organization"


def test_signal_entity_extraction_recovers_coordinated_partner() -> None:
    entities = extract_signal_entities(
        [{"type": "company", "name": "Stellantis"}],
        raw_payload=None,
        title=(
            "Puesta de la primera piedra en la gigafactoría de baterías de Stellantis "
            "en Figueruelas"
        ),
        summary=(
            "Stellantis y CATL marcan el inicio de la construcción de la gigafactoría "
            "de baterías en Figueruelas."
        ),
    )

    by_name = {entity["name"]: entity for entity in entities}
    assert {"Stellantis", "CATL"} <= set(by_name)
    assert by_name["CATL"]["type"] == "organization"


def test_signal_entity_extraction_bridges_coordination_without_trigger_verb() -> None:
    entities = extract_signal_entities(
        [{"type": "company", "name": "Stellantis"}],
        raw_payload=None,
        title="",
        summary="Stellantis y CATL sellan su acuerdo para la gigafactoría de Figueruelas.",
    )

    by_name = {entity["name"]: entity for entity in entities}
    assert "CATL" in by_name
    assert by_name["CATL"]["extraction_method"] == "text_coordination"


def test_signal_entity_extraction_ignores_coordination_without_confirmed_anchor() -> None:
    entities = extract_signal_entities(
        [],
        raw_payload=None,
        title="",
        summary="Industria y Comercio publican una guía sobre movilidad.",
    )

    assert entities == []


def test_signal_entity_extraction_deduplicates_provider_over_payload() -> None:
    entities = extract_signal_entities(
        [{"type": "company", "name": "CATL"}],
        raw_payload={"entities": ["CATL"]},
        title="CATL anuncia una inversión",
        summary="",
    )

    assert entities == [
        {
            "name": "CATL",
            "type": "organization",
            "tags": [],
            "extraction_method": "provider",
        }
    ]
