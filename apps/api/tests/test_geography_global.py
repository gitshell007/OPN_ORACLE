"""Geografía de expediente: ISO 3166-1 alpha-2 e ISO 3166-2 (ámbito global + CCAA)."""

from __future__ import annotations

import pytest

from opn_oracle.oracle.service import (
    DomainValidationError,
    _geography_codes,
    geography_codes_for_signal,
)


def test_geography_accepts_eu_and_non_eu_iso_alpha2() -> None:
    assert _geography_codes(["es", "DE", "us", "MX"]) == ["ES", "DE", "US", "MX"]


def test_geography_accepts_iso_3166_2_subdivisions() -> None:
    assert _geography_codes(["es-vc", "ES-MD", "DE"]) == ["ES-VC", "ES-MD", "DE"]


def test_geography_rejects_non_iso_codes() -> None:
    with pytest.raises(DomainValidationError, match="ISO 3166-1 alpha-2 o ISO 3166-2"):
        _geography_codes(["ES", "USA", "12"])
    with pytest.raises(DomainValidationError, match="no válidos: ES-, XXXX"):
        _geography_codes(["ES-", "XXXX"])


def test_geography_empty_is_allowed() -> None:
    assert _geography_codes([]) == []
    assert _geography_codes(None) == []


def test_geography_codes_for_signal_flattens_subdivisions() -> None:
    assert geography_codes_for_signal(["ES-VC", "ES-MD", "DE", "es"]) == ["ES", "DE"]
    assert geography_codes_for_signal(["ES-VC", "ES"]) == ["ES"]
    assert geography_codes_for_signal([]) == []
    assert geography_codes_for_signal(None) == []
