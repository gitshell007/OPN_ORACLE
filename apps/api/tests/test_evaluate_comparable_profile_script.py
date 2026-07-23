from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.evaluate_comparable_profile import (  # noqa: E402
    _evaluate_arbitrary_plan,
    _read_plan_json,
)

from opn_oracle.oracle.competitive_procurement import AwardHistory  # noqa: E402


def _history() -> AwardHistory:
    rows: list[dict[str, Any]] = []
    for index in range(10):
        rows.append(
            {
                "folder_id": f"F-{index}",
                "award_date": f"2025-01-{index + 1:02d}",
                "cpv": "34144210" if index != 9 else "35111100",
                "title": (
                    "Vehículo de extinción de incendios"
                    if index != 9
                    else "Equipos respiratorios de protección"
                ),
                "buyer": "Consorcio",
                "winner": "ACME SEGURIDAD",
            }
        )
    return AwardHistory(
        rows=tuple(rows),
        provider_total=len(rows),
        truncated=False,
        provider_company_norm="ACME SEGURIDAD",
    )


@pytest.mark.unit
def test_read_plan_json_accepts_inline_plan_and_artifact_envelope(tmp_path: Path) -> None:
    direct = _read_plan_json('{"include_terms": ["incendios"]}')
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(
        json.dumps(
            {
                "output": {
                    "include_terms": ["respiratorios"],
                    "candidate_cpv": [{"code": "35111100"}],
                }
            }
        ),
        encoding="utf-8",
    )

    wrapped = _read_plan_json(str(artifact_path))

    assert direct == {"include_terms": ["incendios"]}
    assert wrapped["include_terms"] == ["respiratorios"]
    assert wrapped["candidate_cpv"] == [{"code": "35111100"}]


@pytest.mark.unit
def test_arbitrary_plan_uses_same_holdout_and_reports_invalid_cpv() -> None:
    result = _evaluate_arbitrary_plan(
        _history(),
        plan={
            "candidate_cpv": [{"code": "35111100"}, {"code": "99999999"}],
            "include_terms": ["vehículo extinción"],
            "synonyms": {"vehículo": ["camión de extinción"]},
            "exclude_terms": [],
        },
    )

    assert result["holdout_contracts"] == 2
    assert result["normalized_plan"]["candidate_cpv"] == ["35111100"]
    assert result["discarded_candidate_cpv"] == [
        {"raw": "99999999", "reason": "not_in_cpv_taxonomy"}
    ]
    assert result["recall"]["cpv"]["hits"] == 1
    assert result["recall"]["terms"]["hits"] == 1
    assert result["recall"]["combined"] == {
        "hits": 2,
        "denominator_holdout_contracts": 2,
        "recall_percent": "100.0",
    }


@pytest.mark.unit
def test_multiword_chip_is_folded_to_tokens_and_exclusion_is_not_scored() -> None:
    result = _evaluate_arbitrary_plan(
        _history(),
        plan={
            "candidate_cpv": ["35111100"],
            "include_terms": ["vehículo rescate"],
            "synonyms": [],
            "exclude_terms": ["equipos respiratorios"],
        },
    )

    assert result["normalized_plan"]["include_and_synonym_terms"] == [
        "rescate",
        "vehiculo",
    ]
    assert result["normalized_plan"]["exclude_terms"] == ["equipos", "respiratorios"]
    assert result["recall"]["terms"]["hits"] == 1
    assert result["recall"]["combined"]["hits"] == 2
