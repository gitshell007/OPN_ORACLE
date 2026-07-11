from __future__ import annotations

from datetime import UTC, datetime

import pytest

from opn_oracle.oracle.scoring import (
    ACTOR_PRIORITY_WEIGHTS,
    ALGORITHM_VERSION,
    OPPORTUNITY_WEIGHTS,
    RISK_WEIGHTS,
    SIGNAL_WEIGHTS,
    aggregate_dossier_scores,
    score_actor_priority,
    score_opportunity,
    score_risk,
    score_signal,
)


@pytest.mark.unit
def test_scoring_weights_are_the_product_contract() -> None:
    assert OPPORTUNITY_WEIGHTS == {
        "strategic_fit": 0.25,
        "urgency": 0.15,
        "expected_value": 0.15,
        "actionability": 0.15,
        "relationship_leverage": 0.10,
        "timing": 0.10,
        "confidence": 0.10,
        "effort": -0.10,
        "blocking_risk": -0.10,
    }
    assert RISK_WEIGHTS == {
        "impact": 0.35,
        "likelihood": 0.25,
        "velocity": 0.20,
        "exposure": 0.10,
        "uncertainty": 0.10,
        "controllability": -0.10,
    }
    assert SIGNAL_WEIGHTS == {
        "relevance": 0.30,
        "novelty": 0.20,
        "strategic_impact": 0.20,
        "source_credibility": 0.15,
        "confidence": 0.15,
    }
    assert ACTOR_PRIORITY_WEIGHTS == {
        "influence": 0.25,
        "relevance_to_dossier": 0.20,
        "relationship_strength": 0.15,
        "accessibility": 0.15,
        "strategic_alignment": 0.15,
        "recent_activity": 0.10,
    }


@pytest.mark.unit
def test_scores_are_deterministic_explainable_and_overridable() -> None:
    now = datetime(2026, 7, 1, tzinfo=UTC)
    opportunity = score_opportunity({key: 70 for key in OPPORTUNITY_WEIGHTS}, calculated_at=now)
    risk = score_risk({key: 60 for key in RISK_WEIGHTS}, calculated_at=now, override=42)
    signal = score_signal({key: 80 for key in SIGNAL_WEIGHTS})
    actor = score_actor_priority({key: 50 for key in ACTOR_PRIORITY_WEIGHTS})
    assert opportunity.algorithm_version == ALGORITHM_VERSION
    assert opportunity.score == 56
    assert risk.score == 42 and risk.human_override == 42
    assert signal.score == 80 and actor.score == 50
    assert "oracle-scoring-v1" in opportunity.explanation
    assert opportunity.calculated_at == now.isoformat()


@pytest.mark.unit
def test_custom_weights_validation_and_aggregate() -> None:
    custom = {key: 0.0 for key in OPPORTUNITY_WEIGHTS} | {"strategic_fit": 1.0}
    assert score_opportunity({key: 50 for key in custom}, weights=custom).score == 50
    assert aggregate_dossier_scores([80, 60], [20, 40]) == {
        "opportunity_score": 70,
        "risk_score": 30,
        "health_score": 70,
    }
    with pytest.raises(ValueError):
        score_signal({key: 101 for key in SIGNAL_WEIGHTS})
