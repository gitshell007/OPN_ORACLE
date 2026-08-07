"""ALTA-HONESTA: market profile accepts honest competitor intent."""

from __future__ import annotations

import pytest

from opn_oracle.oracle.service import DomainValidationError, _validated_market_profile


def test_market_profile_known_requires_names() -> None:
    with pytest.raises(DomainValidationError, match="al menos un nombre"):
        _validated_market_profile(
            {
                "own_offer": "Oferta",
                "decision_to_make": "Decidir entrada",
                "competitors": [],
                "competitors_knowledge": "known",
            }
        )


def test_market_profile_unknown_allows_empty_competitors() -> None:
    profile = _validated_market_profile(
        {
            "own_offer": "Colaboración científica",
            "decision_to_make": "Encontrar grupos sin inventar rivales",
            "competitors": [],
            "competitors_knowledge": "unknown",
            "partners": ["CNRS"],
        }
    )
    assert profile["version"] == "market.v1"
    assert profile["competitors"] == []
    assert profile["competitors_knowledge"] == "unknown"
    assert profile["partners"] == ["CNRS"]


def test_market_profile_not_seeking_strips_false_names() -> None:
    profile = _validated_market_profile(
        {
            "own_offer": "Oferta",
            "decision_to_make": "Solo partners",
            "competitors": [{"name": "Laboratorio mentido como rival"}],
            "competitors_knowledge": "not_seeking",
        }
    )
    assert profile["competitors"] == []
    assert profile["competitors_knowledge"] == "not_seeking"


def test_market_profile_legacy_names_default_to_known() -> None:
    profile = _validated_market_profile(
        {
            "own_offer": "Oferta",
            "decision_to_make": "Entrar",
            "competitors": [{"name": "Gamma"}],
        }
    )
    assert profile["competitors_knowledge"] == "known"
    assert profile["competitors"][0]["name"] == "Gamma"


def test_market_profile_empty_without_intent_rejected() -> None:
    with pytest.raises(DomainValidationError, match="conoces competidores"):
        _validated_market_profile(
            {
                "own_offer": "Oferta",
                "decision_to_make": "Decidir",
                "competitors": [],
            }
        )
