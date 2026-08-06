from __future__ import annotations

from typing import Any

import pytest

from opn_oracle.ai.tender_search_wizard import postvalidate_tender_search_plan
from opn_oracle.oracle.procurement_search_preview import (
    SearchPlanExecutionError,
    build_search_probes,
    execute_search_plan,
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

    assert result["translation_version"] == "tender-search-plan-to-signal-v3"
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
        "34144210",
        "35811100",
        "35110000",
        "18100000",
    ]
    assert result["unprobed_chips"] == [
        {"kind": "term", "value": "epis", "label": None},
        {"kind": "term", "value": "emergencias", "label": None},
        {"kind": "cpv", "value": "18444111", "label": "Cascos de protección"},
    ]
    assert result["semantics"]["merged_results"] is False
    assert result["semantics"]["buyers_applied"] is False
    assert result["semantics"]["geographies_applied"] is False
    assert all(call["buyer"] is None for call in calls)
    assert all(call["region"] is None for call in calls)
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
    # La vigilancia conserva una sola señal rara para reducir ruido; Signal combina tokens con OR.
    assert payload["keywords"] == ["epis"]
    assert payload["filters"] == {
        "scope": "active",
        "cpv": "34144210",
        "min_amount": "10000",
    }
    all_payload = saved_search_payload(name="Todas", plan=_plan(scope="all"))
    assert all_payload["filters"]["scope"] == "active"
    assert "buyer" not in all_payload["filters"]
    assert "region" not in all_payload["filters"]
    with pytest.raises(SearchPlanExecutionError, match="históricas"):
        saved_search_payload(name="Histórico", plan=_plan(scope="historical"))


@pytest.mark.unit
def test_saved_search_prefers_lexically_relevant_cpv() -> None:
    payload = saved_search_payload(
        name="Defensa",
        plan=_plan(
            include_terms=["blindados", "militares"],
            synonyms=[],
            candidate_cpv=[
                {"code": "35110000", "label": "Equipo de extinción de incendios"},
                {"code": "35400000", "label": "Vehículos militares y sus partes"},
                {"code": "35700000", "label": "Sistemas electrónicos militares"},
            ],
            min_amount=None,
        ),
    )
    assert payload["keywords"] == ["blindados"]
    assert payload["filters"]["cpv"] == "35400000"
    assert "buyer" not in payload["filters"]


@pytest.mark.unit
def test_execute_search_plan_drops_closed_and_expired_when_scope_active() -> None:
    def loader(**query: Any) -> dict[str, Any]:
        assert query.get("active") is True
        assert query.get("scope") == "active"
        return {
            "total": 4,
            "limit": 100,
            "offset": 0,
            "items": [
                {
                    "folder_id": "open-1",
                    "title": "Abierta",
                    "status": "PUB",
                    "is_active": True,
                    "deadline": "2099-12-31T12:00:00Z",
                },
                {
                    "folder_id": "awarded-1",
                    "title": "Ya adjudicada",
                    "status": "ADJ",
                    "is_active": True,
                    "deadline": "2099-12-31T12:00:00Z",
                },
                {
                    "folder_id": "resolved-1",
                    "title": "Resuelta",
                    "status": "RES",
                    "is_active": False,
                    "deadline": "2020-01-01T12:00:00Z",
                },
                {
                    "folder_id": "expired-1",
                    "title": "Plazo pasado",
                    "status": "PUB",
                    "is_active": True,
                    "deadline": "2020-06-01T12:00:00Z",
                },
            ],
        }

    result = execute_search_plan(
        tenant_id="tenant-a",
        plan=_plan(
            include_terms=["blindados"],
            synonyms=[],
            candidate_cpv=[{"code": "35400000", "label": "Vehículos militares"}],
            min_amount=None,
            scope="active",
        ),
        tender_loader=loader,
        result_limit=25,
    )
    ids = [item["folder_id"] for item in result["results"]["items"]]
    assert ids == ["open-1"]
    assert result["results"]["total"] == 1


@pytest.mark.unit
def test_execute_search_plan_merges_unique_folder_ids() -> None:
    calls: list[dict[str, Any]] = []

    def loader(**query: Any) -> dict[str, Any]:
        calls.append(query)
        if query.get("cpv") == "35400000":
            return {
                "total": 2,
                "limit": 20,
                "offset": 0,
                "items": [
                    {"folder_id": "A", "title": "Repuestos TOA"},
                    {"folder_id": "B", "title": "ATP"},
                ],
            }
        if query.get("keywords") == "blindados":
            return {
                "total": 1,
                "limit": 20,
                "offset": 0,
                "items": [
                    {"folder_id": "A", "title": "Repuestos TOA"},
                    {"folder_id": "C", "title": "Otro"},
                ],
            }
        return {"total": 0, "limit": 20, "offset": 0, "items": []}

    result = execute_search_plan(
        tenant_id="tenant-a",
        plan=_plan(
            include_terms=["blindados"],
            synonyms=[],
            candidate_cpv=[{"code": "35400000", "label": "Vehículos militares y sus partes"}],
            buyers=["Ministerio de Defensa"],
            geographies=["España"],
            min_amount=None,
        ),
        tender_loader=loader,
        result_limit=25,
    )
    items = result["results"]["items"]
    ids = [item["folder_id"] for item in items]
    assert ids == ["A", "B", "C"]
    assert len(ids) == 3
    assert len(set(ids)) == 3
    # Buyer del plan no se envía a Signal (evita 0 hits).
    assert all(call["buyer"] is None for call in calls)
    assert all(call["region"] is None for call in calls)
    assert result["results"]["total"] == 3
    assert result["results"]["semantics"]["merged_results"] is True


@pytest.mark.unit
def test_execute_search_plan_promotes_relevant_cpv_before_probe_budget() -> None:
    called_cpvs: list[str] = []

    def loader(**query: Any) -> dict[str, Any]:
        cpv = query.get("cpv")
        if isinstance(cpv, str):
            called_cpvs.append(cpv)
        return {"total": 0, "limit": 20, "offset": 0, "items": []}

    result = execute_search_plan(
        tenant_id="tenant-a",
        plan=_plan(
            include_terms=["vehiculos", "incendios", "bomberos"],
            synonyms=[],
            candidate_cpv=[
                {"code": "18100000", "label": "Ropa de trabajo"},
                {"code": "35110000", "label": "Equipo de extinción de incendios"},
                {"code": "18444111", "label": "Cascos de protección"},
                {"code": "45000000", "label": "Trabajos de construcción"},
                {"code": "34144210", "label": "Vehículos de extinción de incendios"},
            ],
            min_amount=None,
        ),
        tender_loader=loader,
    )

    assert called_cpvs == ["34144210", "35110000", "18100000", "18444111"]
    assert result["unprobed_chips"] == [
        {"kind": "cpv", "value": "45000000", "label": "Trabajos de construcción"}
    ]


@pytest.mark.unit
def test_execute_search_plan_probes_representative_parent_market_in_top_four() -> None:
    called_cpvs: list[str] = []

    def loader(**query: Any) -> dict[str, Any]:
        if isinstance(query.get("cpv"), str):
            called_cpvs.append(query["cpv"])
        return {"total": 0, "limit": 20, "offset": 0, "items": []}

    plan = postvalidate_tender_search_plan(
        _plan(
            intent_summary="Necesidad institucional pendiente de concretar.",
            include_terms=["licitacion"],
            synonyms=[],
            candidate_cpv=[],
            min_amount=None,
            discarded_count=0,
            discarded_reasons={},
        ),
        enrich_cpvs=True,
        source_text=("licitacion vehiculos militares y componentes para el ministerio de defensa"),
    )
    candidate_codes = [item["code"] for item in plan["candidate_cpv"]]

    execute_search_plan(
        tenant_id="tenant-a",
        plan=plan,
        tender_loader=loader,
    )

    assert "35400000" in candidate_codes[:4]
    assert "35400000" in called_cpvs
    assert called_cpvs.index("35400000") < 4


@pytest.mark.unit
def test_firefighting_plan_does_not_promote_military_cpv_for_vehicle_token() -> None:
    called_cpvs: list[str] = []

    def loader(**query: Any) -> dict[str, Any]:
        if isinstance(query.get("cpv"), str):
            called_cpvs.append(query["cpv"])
        return {"total": 0, "items": []}

    execute_search_plan(
        tenant_id="tenant-a",
        plan=_plan(
            include_terms=["vehiculos", "incendios", "bomberos"],
            synonyms=[],
            candidate_cpv=[
                {"code": "18100000", "label": "Ropa de trabajo"},
                {"code": "35110000", "label": "Equipo de extinción de incendios"},
                {"code": "18444111", "label": "Cascos de protección"},
                {"code": "34144210", "label": "Vehículos de extinción de incendios"},
                {"code": "35400000", "label": "Vehículos militares y sus partes"},
            ],
            min_amount=None,
        ),
        tender_loader=loader,
    )

    assert called_cpvs[0] == "34144210"
    assert "35400000" not in called_cpvs


@pytest.mark.unit
def test_execute_search_plan_counts_distinct_probes_not_duplicate_provider_rows() -> None:
    def loader(**query: Any) -> dict[str, Any]:
        if query.get("cpv") == "18100000":
            return {
                "total": 3,
                "items": [
                    {"folder_id": "A", "title": "Duplicado"},
                    {"folder_id": "A", "title": "Duplicado"},
                    {"folder_id": "B", "title": "Coincide en dos sondas"},
                ],
            }
        if query.get("keywords") == "proteccion":
            return {
                "total": 1,
                "items": [{"folder_id": "B", "title": "Coincide en dos sondas"}],
            }
        return {"total": 0, "items": []}

    result = execute_search_plan(
        tenant_id="tenant-a",
        plan=_plan(
            include_terms=["proteccion"],
            synonyms=[],
            candidate_cpv=[{"code": "18100000", "label": "Ropa de trabajo"}],
            min_amount=None,
        ),
        tender_loader=loader,
    )

    assert [item["folder_id"] for item in result["results"]["items"]] == ["B", "A"]
    assert result["results"]["total"] == 2


@pytest.mark.unit
def test_clothing_intent_excludes_clear_sports_changing_room_construction() -> None:
    def loader(**_query: Any) -> dict[str, Any]:
        return {
            "total": 2,
            "items": [
                {
                    "folder_id": "facility-noise",
                    "title": "Mejora de los vestuarios del polideportivo de La Encarnación",
                    "cpv": ["45212200"],
                },
                {
                    "folder_id": "clothing-match",
                    "title": "Suministro de vestuario laboral y uniformes",
                    "cpv": ["18110000"],
                },
            ],
        }

    result = execute_search_plan(
        tenant_id="tenant-a",
        plan=_plan(
            intent_summary="Compra de vestuario y ropa laboral",
            include_terms=["vestuario"],
            synonyms=["ropa laboral"],
            candidate_cpv=[{"code": "18110000", "label": "Ropa de trabajo"}],
            min_amount=None,
        ),
        tender_loader=loader,
    )

    assert [item["folder_id"] for item in result["results"]["items"]] == ["clothing-match"]
    precision = result["results"]["semantics"]["precision_filter"]
    assert precision == {
        "version": "procurement-intent-precision-v1",
        "excluded": 1,
        "reason_counts": {"intent_mismatch_clothing_vs_facility": 1},
    }


@pytest.mark.unit
def test_sports_changing_room_intent_keeps_facility_result() -> None:
    def loader(**_query: Any) -> dict[str, Any]:
        return {
            "total": 1,
            "items": [
                {
                    "folder_id": "facility-match",
                    "title": "Reforma de vestuarios del polideportivo municipal",
                    "cpv": ["45212200"],
                }
            ],
        }

    result = execute_search_plan(
        tenant_id="tenant-a",
        plan=_plan(
            intent_summary="Reforma de vestuarios de un polideportivo",
            include_terms=["vestuarios", "polideportivo"],
            synonyms=[],
            candidate_cpv=[
                {
                    "code": "45212200",
                    "label": "Trabajos de construcción de instalaciones deportivas",
                }
            ],
            min_amount=None,
        ),
        tender_loader=loader,
    )

    assert [item["folder_id"] for item in result["results"]["items"]] == ["facility-match"]
    assert result["results"]["semantics"]["precision_filter"]["excluded"] == 0
