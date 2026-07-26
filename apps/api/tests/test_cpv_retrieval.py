from __future__ import annotations

import pytest

from opn_oracle.oracle.cpv_retrieval import (
    merge_cpv_candidates,
    retrieve_cpv_for_text,
)
from opn_oracle.oracle.cpv_taxonomy import load_cpv_taxonomy


@pytest.mark.unit
def test_retrieval_finds_specific_defense_families_without_sector_rules() -> None:
    items = retrieve_cpv_for_text(
        "Vehículos militares blindados y sistemas electrónicos para el ejército."
    )

    codes = [item["code"] for item in items]
    assert codes[0].startswith("354")
    assert any(code.startswith("357") for code in codes)


@pytest.mark.unit
def test_retrieval_reserves_a_top_four_probe_for_representative_parent_market() -> None:
    items = retrieve_cpv_for_text(
        "licitacion vehiculos militares y componentes para el ministerio de defensa"
    )

    assert "35400000" in [item["code"] for item in items[:4]]


@pytest.mark.unit
def test_retrieval_keeps_specific_code_when_parent_does_not_represent_the_query() -> None:
    items = retrieve_cpv_for_text("Vehículos de extinción de incendios para bomberos.")

    assert items[0]["code"] == "34144210"


@pytest.mark.unit
def test_retrieval_finds_firefighting_market_without_military_injection() -> None:
    items = retrieve_cpv_for_text(
        "Equipos de extinción de incendios, EPIs y vehículos para bomberos."
    )

    codes = [item["code"] for item in items]
    assert codes[0] == "34144210"
    assert any(code.startswith("3511") for code in codes)
    assert not any(code.startswith(("354", "357")) for code in codes)


@pytest.mark.unit
def test_retrieval_energy_ignores_generic_vehicle_maintenance_families() -> None:
    items = retrieve_cpv_for_text(
        "Energía renovable, instalaciones eléctricas y mantenimiento energético."
    )

    codes = [item["code"] for item in items]
    assert "09330000" in codes
    assert not any(code.startswith(("501", "502", "503", "504", "505")) for code in codes)


@pytest.mark.unit
def test_retrieval_keeps_ambiguous_procurement_text_bounded_and_empty() -> None:
    assert retrieve_cpv_for_text("suministros varios") == []


@pytest.mark.unit
def test_retrieval_accepts_official_numeric_prefix() -> None:
    items = retrieve_cpv_for_text("354", limit=3)

    assert len(items) == 3
    assert all(item["code"].startswith("354") for item in items)


@pytest.mark.unit
def test_merge_unites_ai_and_retrieval_with_canonical_labels_and_cap() -> None:
    merged, added = merge_cpv_candidates(
        [
            {"code": "18100000", "label": "Etiqueta no canónica"},
            {"code": "99999999", "label": None},
        ],
        text="Ropa de trabajo y equipos de protección personal.",
        limit=5,
    )

    taxonomy = load_cpv_taxonomy()
    assert len(merged) <= 5
    assert any(item["code"] == "18100000" for item in merged)
    assert all(item["label"] == taxonomy.codes[item["code"]] for item in merged)
    assert all(item["code"] != "99999999" for item in merged)
    assert added > 0
