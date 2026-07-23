from __future__ import annotations

from typing import Any

import pytest

from opn_oracle.oracle.procurement_search_preview import (
    SearchPlanExecutionError,
    build_search_probes,
    preview_search_plan,
    saved_search_payload,
)


def _plan(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "intent_summary": "Equipos de protección y vehículos de emergencia.",
        "include_terms": ["proteccion", "bomberos", "vehiculos", "incendios", "epis"],
        "synonyms": ["emergencias"],
        "exclude_terms": ["juguete"],
        "candidate_cpv": [
            {"code": "18100000", "label": "Ropa de trabajo"},
            {"code": "34144210", "label": "Vehículos de extinción de incendios"},
            {"code": "35110000", "label": "Equipo de extinción de incendios"},
            {"code": "35811100", "label": "Uniformes para el cuerpo de bomberos"},
            {"code": "18444111", "label": "Cascos de protección"},
        ],
        "buyers": ["Ayuntamiento de ejemplo", "Consorcio de emergencias"],
        "geographies": ["España", "Andalucía"],
        "scope": "active",
        "min_amount": 10_000,
        "max_amount": None,
        "assumptions": [],
        "questions": [],
        "confidence": 80,
    }
    value.update(overrides)
    return value


@pytest.mark.unit
def test_search_probe_budget_is_visible_and_never_merges_results() -> None:
    calls: list[dict[str, Any]] = []

    def loader(**query: Any) -> dict[str, Any]:
        calls.append(query)
        marker = query.get("keywords") or query.get("cpv")
        return {
            "total": len(calls),
            "limit": query["limit"],
            "offset": query["offset"],
            "items": [{"title": marker}],
            "cached_seconds": 90,
            "cache_hit": False,
        }

    result = preview_search_plan(
        tenant_id="tenant-a",
        plan=_plan(),
        tender_loader=loader,
    )

    assert result["provider_requests"] == 8
    assert result["probe_budget"] == {
        "total": 8,
        "term_limit": 4,
        "cpv_limit": 4,
        "selected": 8,
        "skipped": 3,
    }
    assert [block["chip"]["value"] for block in result["probes"]] == [
        "proteccion",
        "bomberos",
        "vehiculos",
        "incendios",
        "18100000",
        "34144210",
        "35110000",
        "35811100",
    ]
    assert result["unprobed_chips"] == [
        {"kind": "term", "value": "epis", "label": None},
        {"kind": "term", "value": "emergencias", "label": None},
        {"kind": "cpv", "value": "18444111", "label": "Cascos de protección"},
    ]
    assert result["semantics"]["merged_results"] is False
    assert all(call["buyer"] == "Ayuntamiento de ejemplo" for call in calls)
    assert all(call["region"] == "España" for call in calls)
    assert all(call["active"] is True for call in calls)


@pytest.mark.unit
def test_search_probe_selection_requires_a_searchable_chip() -> None:
    with pytest.raises(SearchPlanExecutionError, match="término o un CPV"):
        build_search_probes(_plan(include_terms=[], synonyms=[], candidate_cpv=[]))


@pytest.mark.unit
def test_historical_preview_fails_without_calling_signal() -> None:
    called = False

    def loader(**query: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return query

    with pytest.raises(SearchPlanExecutionError, match="históricas"):
        preview_search_plan(
            tenant_id="tenant-a",
            plan=_plan(scope="historical"),
            tender_loader=loader,
        )
    assert called is False


@pytest.mark.unit
def test_saved_search_translation_is_active_only_and_bounded() -> None:
    payload = saved_search_payload(name="Emergencias", plan=_plan())

    assert payload["name"] == "Emergencias"
    assert payload["keywords"] == [
        "proteccion",
        "bomberos",
        "vehiculos",
        "incendios",
        "epis",
        "emergencias",
    ]
    assert payload["filters"] == {
        "scope": "active",
        "cpv": "18100000",
        "buyer": "Ayuntamiento de ejemplo",
        "region": "España",
        "min_amount": "10000",
    }
    with pytest.raises(SearchPlanExecutionError, match="solo conserva"):
        saved_search_payload(name="Histórico", plan=_plan(scope="all"))
