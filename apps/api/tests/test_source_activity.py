"""Unit tests for official gazette source activity counting and parsing."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from opn_oracle.platform.source_activity import (
    _collect_identifiers,
    _section_counts,
    fetch_official_sumario,
)


def test_collect_and_section_counts_for_borme_payload() -> None:
    payload = {
        "data": {
            "sumario": {
                "diario": [
                    {
                        "sumario_diario": {
                            "identificador": "BORME-S-2026-141",
                            "seccion": [
                                {
                                    "item": [
                                        {"identificador": "BORME-A-2026-141-03"},
                                        {"identificador": "BORME-A-2026-141-04"},
                                        {"identificador": "BORME-B-2026-141"},
                                    ]
                                }
                            ],
                        }
                    }
                ]
            }
        }
    }
    identifiers = _collect_identifiers(payload)
    assert "BORME-S-2026-141" in identifiers
    content = [item for item in identifiers if item.startswith(("BORME-A-", "BORME-B-"))]
    assert len(content) == 3
    counts = _section_counts(identifiers, source="borme")
    assert counts["A"] == 2
    assert counts["B"] == 1
    assert counts["S"] == 1


def test_fetch_official_sumario_not_published_on_404() -> None:
    error = HTTPError(
        url="https://www.boe.es/datosabiertos/api/borme/sumario/20260725",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=None,
    )
    with patch("opn_oracle.platform.source_activity.urlopen", side_effect=error):
        result = fetch_official_sumario("borme", date(2026, 7, 25))
    assert result["status"] == "not_published"
    assert result["item_count"] == 0


def test_fetch_official_sumario_counts_content_items() -> None:
    body = (
        b'{"status":{"code":"200"},"data":{"sumario":{"diario":[{"sumario_diario":{'
        b'"identificador":"BORME-S-2026-140","items":['
        b'{"identificador":"BORME-A-2026-140-01"},{"identificador":"BORME-A-2026-140-02"}'
        b"]}}]}}}"
    )
    response = MagicMock()
    response.read.return_value = body
    response.status = 200
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    with patch("opn_oracle.platform.source_activity.urlopen", return_value=response):
        result = fetch_official_sumario("borme", date(2026, 7, 24))
    assert result["status"] == "published"
    assert result["item_count"] == 2
    assert result["section_counts"]["A"] == 2
    assert result["official_identifier"] == "BORME-S-2026-140"
