"""Unit tests for platform procurement ranking aggregation."""

from __future__ import annotations

from opn_oracle.platform.procurement_analytics import (
    aggregate_tenders,
    amount_bucket_label,
    parse_amount,
)


def test_parse_amount_accepts_european_and_plain_formats() -> None:
    assert parse_amount("1.234,50") == 1234.5
    assert parse_amount("83000.00") == 83000.0
    assert parse_amount(45000) == 45000.0
    assert parse_amount(None) is None
    assert parse_amount("n/d") is None


def test_amount_bucket_label_covers_ranges() -> None:
    assert amount_bucket_label(10_000) == "Menos de 15.000 EUR"
    assert amount_bucket_label(25_000) == "15.000 - 50.000 EUR"
    assert amount_bucket_label(6_000_000) == "Mas de 5 M EUR"
    assert amount_bucket_label(None) == "Importe no publicado"


def test_aggregate_tenders_ranks_cpv_buyers_and_buckets() -> None:
    items = [
        {
            "title": "Servicio de limpieza hospitalaria urgente",
            "buyer": "Servicio Andaluz de Salud",
            "region": "Andalucía",
            "cpv": ["90910000", "85110000"],
            "amount": "45000",
            "canonical_status": "open",
        },
        {
            "title": "Suministro de material sanitario",
            "buyer": "Servicio Andaluz de Salud",
            "region": "Andalucía",
            "cpv": ["33140000"],
            "amount": 120_000,
            "status": "Open",
        },
        {
            "title": "Limpieza de dependencias municipales",
            "buyer": "Ayuntamiento de Sevilla",
            "region": "Andalucía",
            "cpv": ["90910000"],
            "amount": "8000,00",
            "canonical_status": "open",
        },
        {
            "title": "Consultoría sin importe",
            "buyer": "Ministerio de Hacienda",
            "region": "Madrid",
            "cpv": ["79400000"],
            "amount": None,
            "canonical_status": "open",
        },
    ]
    result = aggregate_tenders(items, top_n=10, sort_by="count", direction="desc")
    assert result["sample_size"] == 4
    assert result["with_amount"] == 3
    assert result["top_buyers"][0]["key"] == "Servicio Andaluz de Salud"
    assert result["top_buyers"][0]["count"] == 2
    top_cpv = {row["key"]: row["count"] for row in result["top_cpv"]}
    assert top_cpv["90910000"] == 2
    buckets = {row["label"]: row["count"] for row in result["amount_buckets"]}
    assert buckets["Menos de 15.000 EUR"] == 1
    assert buckets["15.000 - 50.000 EUR"] == 1
    assert buckets["50.000 - 200.000 EUR"] == 1
    assert buckets["Importe no publicado"] == 1
    by_amount = aggregate_tenders(items, top_n=5, sort_by="amount_sum", direction="desc")
    assert by_amount["top_buyers"][0]["key"] == "Servicio Andaluz de Salud"
    assert by_amount["top_buyers"][0]["amount_sum"] == 165_000.0
