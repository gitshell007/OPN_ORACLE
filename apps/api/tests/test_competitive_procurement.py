from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from opn_oracle.ai.registry import PromptRegistry
from opn_oracle.integrations.procurement import ProcurementProviderError
from opn_oracle.oracle.competitive_procurement import (
    COMPETITIVE_PROCUREMENT_AGENT,
    PAGE_THROTTLE_SECONDS,
    RATE_LIMIT_MAX_RETRIES,
    build_competitive_procurement_analysis,
    fetch_award_history,
    pinned_award_winners,
)
from opn_oracle.reporting.registry import ReportTemplateRegistry


class FakeProcurementClient:
    def __init__(
        self,
        rows: list[dict[str, Any]],
        tenders: dict[str, dict[str, Any] | None],
    ) -> None:
        self.rows = rows
        self.tenders = tenders
        self.award_calls: list[tuple[str | None, int, int]] = []
        self.tender_calls: list[str] = []

    def awards(
        self,
        *,
        company: str | None,
        buyer: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        assert buyer is None
        self.award_calls.append((company, limit, offset))
        return {
            "company_norm": "ITURRI",
            "total": len(self.rows),
            "items": self.rows[offset : offset + limit],
        }

    def tender_by_folder(self, *, folder_id: str) -> dict[str, Any]:
        self.tender_calls.append(folder_id)
        tender = self.tenders[folder_id]
        if tender is None:
            raise ProcurementProviderError(
                status_code=404,
                code="not_found",
                detail="No existe licitación.",
            )
        return {"item": tender}


def test_fetch_award_history_paginates_and_declares_cap() -> None:
    client = FakeProcurementClient(
        [{"folder_id": f"F-{index}"} for index in range(7)],
        {},
    )

    naps: list[float] = []
    history = fetch_award_history(
        client,
        company_name="ITURRI, S.A",
        max_rows=5,
        page_size=2,
        sleeper=naps.append,
    )

    assert len(history.rows) == 5
    assert history.provider_total == 7
    assert history.truncated is True
    assert history.provider_company_norm == "ITURRI"
    assert client.award_calls == [
        ("ITURRI, S.A", 2, 0),
        ("ITURRI, S.A", 2, 2),
        ("ITURRI, S.A", 1, 4),
    ]
    # Ritmo entre páginas: una pausa tras cada página que no cierra el corpus.
    assert naps == [PAGE_THROTTLE_SECONDS, PAGE_THROTTLE_SECONDS]


class RateLimitedClient(FakeProcurementClient):
    """Devuelve 429 en las primeras `flaky` llamadas de cada offset nuevo."""

    def __init__(self, rows: list[dict[str, Any]], flaky: int) -> None:
        super().__init__(rows, {})
        self.flaky = flaky
        self.failures: dict[int, int] = {}

    def awards(
        self, *, company: str | None, buyer: str | None, limit: int, offset: int
    ) -> dict[str, Any]:
        served = self.failures.get(offset, 0)
        if served < self.flaky:
            self.failures[offset] = served + 1
            raise ProcurementProviderError(
                status_code=429,
                code="rate_limited",
                detail="Too Many Requests",
                retryable=True,
            )
        return super().awards(company=company, buyer=buyer, limit=limit, offset=offset)


def test_fetch_award_history_waits_out_429_within_the_page_loop() -> None:
    client = RateLimitedClient([{"folder_id": f"F-{index}"} for index in range(4)], flaky=2)
    naps: list[float] = []

    history = fetch_award_history(
        client,
        company_name="ITURRI, S.A",
        max_rows=4,
        page_size=2,
        sleeper=naps.append,
    )

    # El 429 se resuelve en el mismo offset: el corpus se completa sin reiniciar el job.
    assert len(history.rows) == 4
    # Backoff creciente por cada 429 (dos por página), más el ritmo entre páginas.
    assert naps == [1.5, 3.0, PAGE_THROTTLE_SECONDS, 1.5, 3.0]


def test_fetch_award_history_gives_up_after_persistent_429() -> None:
    client = RateLimitedClient([{"folder_id": "F-0"}], flaky=99)
    naps: list[float] = []

    with pytest.raises(ProcurementProviderError) as excinfo:
        fetch_award_history(
            client,
            company_name="ITURRI, S.A",
            max_rows=1,
            page_size=1,
            sleeper=naps.append,
        )

    assert excinfo.value.status_code == 429
    assert len(naps) == RATE_LIMIT_MAX_RETRIES


def test_fetch_award_history_does_not_swallow_other_provider_errors() -> None:
    class BrokenClient(FakeProcurementClient):
        def awards(self, **kwargs: Any) -> dict[str, Any]:
            raise ProcurementProviderError(
                status_code=503,
                code="unavailable",
                detail="Signal no está disponible temporalmente.",
                retryable=True,
            )

    naps: list[float] = []
    with pytest.raises(ProcurementProviderError) as excinfo:
        fetch_award_history(
            BrokenClient([], {}),
            company_name="ITURRI, S.A",
            sleeper=naps.append,
        )

    assert excinfo.value.status_code == 503
    assert naps == []


def test_aggregates_are_python_calculated_and_low_discount_coverage_is_suppressed() -> None:
    rows = [
        {
            "folder_id": "A",
            "lot_id": "1",
            "buyer": "Organismo Norte",
            "winner": "ITURRI, S.A",
            "award_amount": 80,
            "award_date": "2026-01-10",
            "is_ute": False,
        },
        {
            "folder_id": "B",
            "lot_id": "1",
            "buyer": "Organismo Norte",
            "winner": "ITURRI SA Y SOCIO INDUSTRIAL SL UTE",
            "award_amount": 120,
            "award_date": "2026-02-10",
            "is_ute": True,
        },
        {
            "folder_id": "C",
            "lot_id": "1",
            "buyer": "Organismo Sur",
            "winner": "ITURRI, S.A",
            "award_amount": 100,
            "award_date": "2026-03-10",
            "is_ute": False,
        },
        {
            "folder_id": "C",
            "lot_id": "2",
            "buyer": "Organismo Sur",
            "winner": "ITURRI, S.A",
            "award_amount": 50,
            "award_date": "2026-03-10",
            "is_ute": False,
        },
    ]
    client = FakeProcurementClient(
        rows,
        {
            "A": {"amount": 100},
            "B": None,
            "C": {"amount": 200},
        },
    )

    analysis = build_competitive_procurement_analysis(
        client,
        company_name="ITURRI, S.A",
        max_rows=100,
        page_size=2,
    )

    corpus = analysis["corpus"]
    assert corpus["unique_contracts"] == 3
    assert corpus["period_start"] == "2026-01-10"
    assert corpus["period_end"] == "2026-03-10"
    assert "no todas las ofertas presentadas" in analysis["scope_warning"]
    assert analysis["buyer_concentration"][0] == {
        "buyer": "Organismo Norte",
        "contracts": 2,
        "denominator_contracts": 3,
        "contract_share_percent": "66.7",
        "contracts_with_amount": 2,
        "total_awarded_eur": "200.00",
        "median_awarded_eur": "100.00",
    }
    assert analysis["amount_distribution"]["median_awarded_eur"] == "120.00"
    assert analysis["amount_distribution"]["mean_awarded_eur"] == "116.67"

    discount = analysis["discount_coverage"]
    assert discount["computed_contracts"] == 2
    assert discount["denominator_contracts"] == 3
    assert discount["coverage_percent"] == "66.7"
    assert discount["computable"] is False
    assert discount["mean_discount_percent"] is None
    assert discount["median_discount_percent"] is None
    assert discount["non_computable_reasons"]["tender_not_found"] == 1
    assert "sesgo de supervivencia" in discount["reason"]

    ute = analysis["ute_partners"]
    assert ute["verified"] is False
    assert ute["confidence"] == "low"
    assert ute["partners"] == [
        {
            "name": "SOCIO INDUSTRIAL SL",
            "contracts": 1,
            "denominator_ute_contracts": 1,
        }
    ]


def test_discount_is_only_published_with_declared_high_coverage_and_sample() -> None:
    rows = [
        {
            "folder_id": folder_id,
            "buyer": "Organismo",
            "winner": "ITURRI, S.A",
            "award_amount": award_amount,
            "award_date": f"2026-04-0{index}",
        }
        for index, (folder_id, award_amount) in enumerate(
            (("A", 80), ("B", 90), ("C", 70)),
            start=1,
        )
    ]
    client = FakeProcurementClient(
        rows,
        {
            "A": {"amount": 100},
            "B": {"amount": 100},
            "C": {"amount": 100},
        },
    )

    discount = build_competitive_procurement_analysis(
        client,
        company_name="ITURRI, S.A",
    )["discount_coverage"]

    assert discount["computable"] is True
    assert discount["computed_contracts"] == 3
    assert discount["denominator_contracts"] == 3
    assert discount["coverage_percent"] == "100.0"
    assert discount["mean_discount_percent"] == "20.0"
    assert discount["median_discount_percent"] == "20.0"
    assert discount["reason"] is None


def test_pinned_winners_are_exact_and_task_contract_is_registered() -> None:
    items = [
        SimpleNamespace(
            kind="award",
            snapshot={
                "winner": "ITURRI, S.A",
                "entries": [
                    {"winner": "ITURRI, S.A"},
                    {"winner": "ITURRI SA Y SOCIO SL UTE"},
                ],
            },
        ),
        SimpleNamespace(kind="tender", snapshot={"winner": "No debe entrar"}),
    ]

    assert pinned_award_winners(items) == (
        "ITURRI, S.A",
        "ITURRI SA Y SOCIO SL UTE",
    )
    prompt = PromptRegistry().get(COMPETITIVE_PROCUREMENT_AGENT)
    assert prompt.version == "v1"
    assert prompt.output_schema_name == "ReportOutput"
    assert prompt.max_output_tokens == 5000
    template = ReportTemplateRegistry().get("competitive_procurement")
    assert template.sections[0] == "Cobertura y límites"
