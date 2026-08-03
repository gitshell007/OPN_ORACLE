"""Unit tests for dossier profile_config exposure in AI context."""

from __future__ import annotations

from types import SimpleNamespace

from opn_oracle.ai.context import _profile_summary


def test_profile_summary_exposes_market_fields() -> None:
    dossier = SimpleNamespace(
        profile_config={
            "version": "market.v1",
            "own_offer": "Baterías",
            "decision_to_make": "Entrar o no",
            "competitors": [{"name": "Gamma"}, {"name": "Delta"}],
            "barriers": ["Permisos"],
            "keywords": ["almacenamiento"],
            "segments": ["utility"],
            "channels": [],
            "target_buyers": [],
            "partners": [],
            "regulators": [],
            "success_indicators": [],
            "horizon": "Q4",
        }
    )
    summary = _profile_summary(dossier)  # type: ignore[arg-type]
    assert summary["version"] == "market.v1"
    assert summary["own_offer"] == "Baterías"
    assert summary["competitors"] == ["Gamma", "Delta"]
    assert summary["barriers"] == ["Permisos"]
    assert summary["keywords"] == ["almacenamiento"]


def test_profile_summary_exposes_competitive_fields() -> None:
    dossier = SimpleNamespace(
        profile_config={
            "version": "competitive-intelligence.v1",
            "own_offer": "Producto",
            "business_objective": "Ganar cuota",
            "competitors": [{"name": "Rival"}],
            "cpv": ["90910000"],
            "keywords": ["limpieza"],
            "geographies": ["ES"],
            "segments": [],
            "target_buyers": [],
            "sources": ["PLACSP"],
            "participation_criteria": "ISO",
            "exclusion_criteria": "",
            "success_indicators": [],
            "horizon": "",
        }
    )
    summary = _profile_summary(dossier)  # type: ignore[arg-type]
    assert summary["version"] == "competitive-intelligence.v1"
    assert summary["own_offer"] == "Producto"
    assert summary["competitors"] == ["Rival"]
    assert summary["cpv"] == ["90910000"]
    assert summary["business_objective"] == "Ganar cuota"
