"""Deterministic safety metrics for offline AI regression fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from opn_oracle.ai.schemas import AgentOutput


@dataclass(frozen=True, slots=True)
class EvalMetrics:
    schema_pass: bool
    evidence_coverage: float
    unsupported_claim_rate: float
    classification_accuracy: float
    human_acceptance: float | None
    latency_ms: int
    cost_micros: int


def calculate_metrics(
    output: AgentOutput,
    *,
    allowed_evidence_ids: set[str],
    predicted_classification: str,
    expected_classification: str,
    accepted: bool | None,
    latency_ms: int,
    cost_micros: int,
) -> EvalMetrics:
    """Calculate explicit, bounded metrics without invoking a provider."""
    citations: list[list[str]] = [
        [str(item) for item in claim.evidence_ids] for claim in output.facts
    ] + [[str(item) for item in claim.evidence_ids] for claim in output.inferences]

    def nested_citations(value: Any, *, root: bool = False) -> list[list[str]]:
        if isinstance(value, BaseModel):
            found: list[list[str]] = []
            for name in type(value).model_fields:
                if root and name in {"facts", "inferences"}:
                    continue
                child = getattr(value, name)
                if name == "evidence_ids" and isinstance(child, list):
                    found.append([str(item) for item in child])
                else:
                    found.extend(nested_citations(child))
            return found
        if isinstance(value, (list, tuple)):
            return [item for child in value for item in nested_citations(child)]
        if isinstance(value, dict):
            return [item for child in value.values() for item in nested_citations(child)]
        return []

    citations.extend(nested_citations(output, root=True))
    cited = [item for claim_citations in citations for item in claim_citations]
    supported = [item for item in cited if item in allowed_evidence_ids]
    coverage = len(supported) / len(cited) if cited else 1.0
    unsupported_claims = sum(
        not claim_citations or not set(claim_citations).issubset(allowed_evidence_ids)
        for claim_citations in citations
    )
    unsupported_rate = unsupported_claims / len(citations) if citations else 0.0
    return EvalMetrics(
        schema_pass=True,
        evidence_coverage=coverage,
        unsupported_claim_rate=unsupported_rate,
        classification_accuracy=float(predicted_classification == expected_classification),
        human_acceptance=None if accepted is None else float(accepted),
        latency_ms=max(0, latency_ms),
        cost_micros=max(0, cost_micros),
    )
