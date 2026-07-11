"""Pure, versioned and explainable Oracle scoring."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

ALGORITHM_VERSION = "oracle-scoring-v1"

OPPORTUNITY_WEIGHTS: dict[str, float] = {
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
RISK_WEIGHTS: dict[str, float] = {
    "impact": 0.35,
    "likelihood": 0.25,
    "velocity": 0.20,
    "exposure": 0.10,
    "uncertainty": 0.10,
    "controllability": -0.10,
}
SIGNAL_WEIGHTS: dict[str, float] = {
    "relevance": 0.30,
    "novelty": 0.20,
    "strategic_impact": 0.20,
    "source_credibility": 0.15,
    "confidence": 0.15,
}
ACTOR_PRIORITY_WEIGHTS: dict[str, float] = {
    "influence": 0.25,
    "relevance_to_dossier": 0.20,
    "relationship_strength": 0.15,
    "accessibility": 0.15,
    "strategic_alignment": 0.15,
    "recent_activity": 0.10,
}


@dataclass(frozen=True, slots=True)
class ScoreResult:
    score: int
    components: dict[str, int]
    weights: dict[str, float]
    explanation: str
    evidence_ids: tuple[str, ...]
    confidence: int
    calculated_at: str
    algorithm_version: str = ALGORITHM_VERSION
    human_override: int | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _score(
    components: Mapping[str, int],
    weights: Mapping[str, float],
    *,
    evidence_ids: tuple[str, ...] = (),
    override: int | None = None,
    calculated_at: datetime | None = None,
) -> ScoreResult:
    normalized: dict[str, int] = {}
    for key in weights:
        value = int(components.get(key, 0))
        if not 0 <= value <= 100:
            raise ValueError(f"{key} debe estar entre 0 y 100.")
        normalized[key] = value
    if override is not None and not 0 <= override <= 100:
        raise ValueError("El override debe estar entre 0 y 100.")
    positive = sum(
        value * max(weight, 0) for key, weight in weights.items() for value in [normalized[key]]
    )
    negative = sum(
        value * abs(min(weight, 0))
        for key, weight in weights.items()
        for value in [normalized[key]]
    )
    calculated = max(0, min(100, round(positive - negative)))
    final = override if override is not None else calculated
    confidence = normalized.get("confidence", round(sum(normalized.values()) / len(normalized)))
    contributions = ", ".join(
        f"{key}={normalized[key]}x{weight:+.2f}" for key, weight in weights.items()
    )
    explanation = f"{ALGORITHM_VERSION}: {contributions}; calculado={calculated}"
    if override is not None:
        explanation += f"; override humano={override}"
    return ScoreResult(
        score=final,
        components=normalized,
        weights=dict(weights),
        explanation=explanation,
        evidence_ids=evidence_ids,
        confidence=confidence,
        calculated_at=(calculated_at or datetime.now(UTC)).isoformat(),
        human_override=override,
    )


def score_opportunity(
    components: Mapping[str, int],
    *,
    evidence_ids: tuple[str, ...] = (),
    override: int | None = None,
    calculated_at: datetime | None = None,
    weights: Mapping[str, float] | None = None,
) -> ScoreResult:
    return _score(
        components,
        weights or OPPORTUNITY_WEIGHTS,
        evidence_ids=evidence_ids,
        override=override,
        calculated_at=calculated_at,
    )


def score_risk(
    components: Mapping[str, int],
    *,
    evidence_ids: tuple[str, ...] = (),
    override: int | None = None,
    calculated_at: datetime | None = None,
    weights: Mapping[str, float] | None = None,
) -> ScoreResult:
    return _score(
        components,
        weights or RISK_WEIGHTS,
        evidence_ids=evidence_ids,
        override=override,
        calculated_at=calculated_at,
    )


def score_signal(
    components: Mapping[str, int], *, weights: Mapping[str, float] | None = None
) -> ScoreResult:
    return _score(components, weights or SIGNAL_WEIGHTS)


def score_actor_priority(
    components: Mapping[str, int], *, weights: Mapping[str, float] | None = None
) -> ScoreResult:
    return _score(components, weights or ACTOR_PRIORITY_WEIGHTS)


def aggregate_dossier_scores(
    opportunity_scores: list[int], risk_scores: list[int]
) -> dict[str, int]:
    """Mean aggregates; health rewards opportunity while subtracting risk pressure."""

    opportunity = (
        round(sum(opportunity_scores) / len(opportunity_scores)) if opportunity_scores else 0
    )
    risk = round(sum(risk_scores) / len(risk_scores)) if risk_scores else 0
    health = max(0, min(100, round(50 + opportunity * 0.5 - risk * 0.5)))
    return {"opportunity_score": opportunity, "risk_score": risk, "health_score": health}
