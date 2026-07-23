from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from opn_oracle.oracle.comparable_procurement import (
    TITLE_TERM_METHOD_VERSION,
    build_comparable_profile,
    comparable_names_from_pinned_awards,
    evaluate_comparable_history,
    profile_from_history,
)
from opn_oracle.oracle.competitive_procurement import AwardHistory
from opn_oracle.oracle.cpv_taxonomy import (
    fold_search_text,
    load_cpv_taxonomy,
    normalize_cpv_code,
    suggest_cpv_codes,
)


def _award_rows() -> list[dict[str, Any]]:
    return [
        {
            "folder_id": "A",
            "award_amount": "100",
            "award_date": "0001-01-01",
            "buyer": "Consorcio Norte",
            "cpv": "34144210",
            "is_ute": False,
            "source_url": "https://example.test/A",
            "title": "Suministro de vehículos de extinción de incendios",
            "winner": "ACME SEGURIDAD SA",
        },
        {
            "folder_id": "B",
            "award_amount": "200",
            "award_date": "2024-01-10",
            "buyer": "Consorcio Norte",
            "cpv": "34144210-3",
            "is_ute": False,
            "source_url": "https://example.test/B",
            "title": "Suministro de vehículos de extinción y rescate",
            "winner": "ACME SEGURIDAD SA",
        },
        {
            "folder_id": "C",
            "award_amount": None,
            "award_date": "2029-02-10",
            "buyer": "Ayuntamiento Sur",
            "cpv": ["35111100"],
            "is_ute": True,
            "source_url": "https://example.test/C",
            "title": "Servicio de mantenimiento de equipos respiratorios",
            "winner": "ACME SEGURIDAD SA Y SOCIO INDUSTRIAL SL UTE",
        },
        {
            "folder_id": "D",
            "award_amount": "50",
            "award_date": "fecha-invalida",
            "buyer": "Ayuntamiento Sur",
            "cpv": "CPV 999",
            "is_ute": False,
            "source_url": "https://example.test/D",
            "title": "Contrato de servicio de mantenimiento respiratorio",
            "winner": "ACME SEGURIDAD SA",
        },
        {
            "folder_id": "",
            "award_amount": "999",
            "award_date": None,
            "buyer": "Ignorado",
            "cpv": "99999999",
            "title": "Fila sin expediente",
            "winner": "ACME SEGURIDAD SA",
        },
    ]


def _history(*, total: int = 9, truncated: bool = True) -> AwardHistory:
    return AwardHistory(
        rows=tuple(_award_rows()),
        provider_total=total,
        truncated=truncated,
        provider_company_norm="ACME SEGURIDAD",
    )


@pytest.mark.unit
def test_cpv_taxonomy_loads_offline_and_normalizes_observed_signal_format() -> None:
    taxonomy = load_cpv_taxonomy()

    assert len(taxonomy.codes) == 9_454
    assert taxonomy.version == "2008"
    assert taxonomy.language == "es"
    assert normalize_cpv_code("34144210") == "34144210"
    assert normalize_cpv_code("34144210-3") == "34144210"
    assert normalize_cpv_code("34144210, 35111100") is None
    assert normalize_cpv_code("CPV 34144210") is None
    assert taxonomy.label("34144210") == "Vehículos de extinción de incendios"
    assert taxonomy.label("99999999") is None


@pytest.mark.unit
def test_cpv_suggestions_match_official_prefix_and_accent_folded_label() -> None:
    by_code = suggest_cpv_codes("341442", limit=5)
    by_label = suggest_cpv_codes("extincion de incendios", limit=5)

    assert by_code
    assert all(code.startswith("341442") for code, _label in by_code)
    assert ("34144210", "Vehículos de extinción de incendios") in by_code
    assert ("34144210", "Vehículos de extinción de incendios") in by_label
    assert all("extincion de incendios" in fold_search_text(label) for _code, label in by_label)
    assert len(suggest_cpv_codes("de", limit=20)) == 20


@pytest.mark.unit
def test_profile_aggregates_only_observed_award_fields_and_discloses_anomalies() -> None:
    measured_at = datetime(2026, 7, 23, 17, 30, tzinfo=UTC)
    profile = profile_from_history(
        _history(),
        company_name="Acme Seguridad, S.A.",
        measured_at=measured_at,
    )

    assert profile["measured_at"] == "2026-07-23T17:30:00+00:00"
    assert profile["measurement_contract"]["llm_calls"] == 0
    assert profile["measurement_contract"]["regions_inferred"] is False
    assert profile["measurement_contract"]["dates_repaired"] is False
    assert profile["identity_basis"] == {
        "oracle_normalized_name": "ACME SEGURIDAD S A",
        "oracle_company_core": "ACME SEGURIDAD",
        "legal_identity_verified": False,
    }
    assert profile["corpus"] == {
        "provider_total_rows": 9,
        "analyzed_rows": 5,
        "row_cap": 2_000,
        "truncated": True,
        "aggregated_contracts": 4,
        "ignored_rows_without_folder_id": 1,
    }
    assert profile["award_date_window"]["raw_observed_start"] == "0001-01-01"
    assert profile["award_date_window"]["raw_observed_end"] == "2029-02-10"
    assert profile["award_date_window"]["rows_with_invalid_date"] == 1
    assert profile["award_date_window"]["rows_without_date"] == 1

    cpvs = profile["frequent_cpvs"]
    assert cpvs["signal_format_observed"] == "XXXXXXXX"
    assert cpvs["contracts_with_normalized_cpv"] == 3
    assert cpvs["contracts_without_normalized_cpv"] == 1
    assert cpvs["items"][0] == {
        "code": "34144210",
        "label": "Vehículos de extinción de incendios",
        "taxonomy_match": True,
        "contracts": 2,
        "denominator_contracts": 4,
        "share_percent": "50.0",
        "raw_examples": ["34144210", "34144210-3"],
    }
    assert cpvs["invalid_or_unrecognized"] == [{"raw_value": "CPV 999", "contracts": 1}]

    assert profile["buyers"][0]["buyer"] == "Consorcio Norte"
    assert profile["buyers"][0]["contracts"] == 2
    assert profile["amount_distribution"]["median_awarded_eur"] == "100.00"
    assert profile["amount_distribution"]["contracts_without_amount"] == 1
    terms = profile["title_terms"]
    assert terms["method_version"] == TITLE_TERM_METHOD_VERSION
    assert terms["items"][0]["term"] in {"extincion", "vehiculos"}
    assert all(
        item["term"] not in {"ayuntamiento", "basado", "contrato", "servicio", "suministro"}
        for item in terms["items"]
    )
    assert profile["ute_participation"]["ute_contracts"] == 1
    assert profile["ute_participation"]["partners"][0]["name"] == "SOCIO INDUSTRIAL SL"


class _FakeAwardsClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str | None, int, int]] = []

    def awards(
        self,
        *,
        company: str | None,
        buyer: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        assert buyer is None
        self.calls.append((company, limit, offset))
        return {
            "company_norm": "ACME SEGURIDAD",
            "total": len(self.rows),
            "items": self.rows[offset : offset + limit],
        }

    def tender_by_folder(self, *, folder_id: str) -> dict[str, Any]:
        raise AssertionError(f"No debe consultar pliegos: {folder_id}")


@pytest.mark.unit
def test_profile_fetches_paginated_awards_without_tender_or_llm_calls() -> None:
    client = _FakeAwardsClient(_award_rows())

    profile = build_comparable_profile(
        client,
        company_name="Acme Seguridad",
        max_rows=5,
        page_size=2,
        sleeper=lambda _delay: None,
    )

    assert profile["corpus"]["analyzed_rows"] == 5
    assert client.calls == [
        ("Acme Seguridad", 2, 0),
        ("Acme Seguridad", 2, 2),
        ("Acme Seguridad", 1, 4),
    ]


@pytest.mark.unit
def test_temporal_evaluation_uses_oldest_80_percent_and_keeps_invalid_dates_visible() -> None:
    rows: list[dict[str, Any]] = []
    for index in range(10):
        rows.append(
            {
                "folder_id": f"F-{index}",
                "award_date": f"202{index // 2}-01-{index + 1:02d}",
                "cpv": "34144210" if index != 9 else "35111100",
                "title": (
                    "Suministro de vehículo de extinción"
                    if index != 9
                    else "Mantenimiento de equipos respiratorios"
                ),
                "buyer": "Consorcio",
                "winner": "ACME SEGURIDAD SA",
                "is_ute": False,
            }
        )
    rows.extend(
        [
            {
                "folder_id": "UNDATED",
                "award_date": "fecha-rota",
                "cpv": "34144210",
                "title": "Vehículo de extinción",
                "buyer": "Consorcio",
                "winner": "ACME SEGURIDAD SA",
            },
            {
                "folder_id": "MISSING-DATE",
                "award_date": None,
                "cpv": "34144210",
                "title": "Vehículo de extinción",
                "buyer": "Consorcio",
                "winner": "ACME SEGURIDAD SA",
            },
        ]
    )
    history = AwardHistory(
        rows=tuple(rows),
        provider_total=len(rows),
        truncated=False,
        provider_company_norm="ACME SEGURIDAD",
    )

    result = evaluate_comparable_history(
        history,
        company_name="Acme Seguridad",
        cpv_top_k=1,
        term_top_k=2,
    )

    assert result["temporal_split"]["training_contracts"] == 8
    assert result["temporal_split"]["holdout_contracts"] == 2
    assert result["temporal_split"]["holdout_start"] == "2024-01-09"
    assert result["temporal_split"]["holdout_end"] == "2024-01-10"
    assert result["corpus"]["undated_contracts_excluded_from_split"] == 2
    assert result["corpus"]["rows_with_invalid_date"] == 1
    assert result["corpus"]["rows_without_date"] == 1
    assert result["recall"]["cpv"] == {
        "hits": 1,
        "denominator_holdout_contracts": 2,
        "recall_percent": "50.0",
    }
    assert result["recall"]["combined"]["hits"] == 1


@pytest.mark.unit
def test_comparable_candidates_reuse_exact_pinned_award_winners() -> None:
    items = [
        SimpleNamespace(
            kind="award",
            snapshot={"winner": "ACME, S.A.", "entries": [{"winner": "ACME Y SOCIO UTE"}]},
        ),
        SimpleNamespace(kind="tender", snapshot={"winner": "No entra"}),
    ]

    assert comparable_names_from_pinned_awards(items) == ("ACME, S.A.", "ACME Y SOCIO UTE")
