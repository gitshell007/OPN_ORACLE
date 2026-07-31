"""Geografía de expediente: ISO 3166-1 alpha-2 global (no solo UE-27)."""

from __future__ import annotations

import pytest

from opn_oracle.oracle.service import DomainValidationError, _geography_codes


def test_geography_accepts_eu_and_non_eu_iso_alpha2() -> None:
    assert _geography_codes(["es", "DE", "us", "MX"]) == ["ES", "DE", "US", "MX"]


def test_geography_rejects_non_iso_alpha2() -> None:
    with pytest.raises(DomainValidationError, match="ISO 3166-1 alpha-2"):
        _geography_codes(["ES", "USA", "12"])


def test_geography_empty_is_allowed() -> None:
    assert _geography_codes([]) == []
    assert _geography_codes(None) == []
