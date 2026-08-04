"""SV2-PRIORIZA-FLAKE · facts sin evidence_ids se retiran antes del schema."""

from __future__ import annotations

import json
import uuid

import pytest
from pydantic import ValidationError

from opn_oracle.ai.provider import (
    MIN_GROUNDED_FACTS_FOR_QUALITY,
    QUALITY_DEGRADED_CONFIDENCE_CAP,
    UncitedFactsError,
    _sanitize_uncited_facts_json,
)
from opn_oracle.ai.schemas import ActorAnalysisOutput


def _base_actor_payload(*, facts: list[dict], confidence: int = 80) -> dict:
    return {
        "facts": facts,
        "inferences": [],
        "recommendations": [],
        "confidence": confidence,
        "open_questions": [],
        "warnings": [],
        "actor_id": None,
        "roles": [],
        "scores": {
            "influence": 50,
            "relevance": 50,
            "relationship_strength": 40,
            "accessibility": 40,
            "strategic_alignment": 50,
            "recent_activity": 60,
            "overall_priority": 45,
        },
        "confirmed_relationships": [],
        "inferred_relationships": [],
        "observable_interests": [],
        "information_gaps": [],
        "relationships": [],
        "engagement_actions": [],
    }


def test_uncited_fact_is_dropped_with_visible_warning() -> None:
    eid = str(uuid.uuid4())
    payload = _base_actor_payload(
        facts=[
            {"statement": "Adjudicación PLACSP con importe real.", "evidence_ids": [eid]},
            {"statement": "Afirmación sin citas del modelo.", "evidence_ids": []},
            {"statement": "Otra sin citas.", "evidence_ids": []},
            {
                "statement": "Segunda adjudicación citada.",
                "evidence_ids": [eid],
            },
        ],
        confidence=80,
    )
    raw = json.dumps(payload)
    cleaned = _sanitize_uncited_facts_json(raw, agent="actor_partnership")
    data = json.loads(cleaned)
    assert len(data["facts"]) == 2
    assert all(item["evidence_ids"] for item in data["facts"])
    assert any("Se retiraron 2 fact(s) sin evidence_ids" in w for w in data["warnings"])
    assert any("Afirmación sin citas" in w for w in data["warnings"])
    # mínimo razonable cubierto → no degrada
    assert data["confidence"] == 80
    ActorAnalysisOutput.model_validate_json(cleaned)


def test_all_uncited_facts_fail_with_explicit_message_not_schema() -> None:
    payload = _base_actor_payload(
        facts=[
            {"statement": "Sin citas A", "evidence_ids": []},
            {"statement": "Sin citas B", "evidence_ids": []},
        ]
    )
    with pytest.raises(UncitedFactsError, match="el modelo no citó nada"):
        _sanitize_uncited_facts_json(json.dumps(payload), agent="actor_partnership")


def test_schema_too_short_is_the_pre_fix_death_mode() -> None:
    """Documenta el flake: model_validate muere en too_short sin el saneo."""

    payload = _base_actor_payload(
        facts=[
            {
                "statement": "Hecho con cita",
                "evidence_ids": [str(uuid.uuid4())],
            },
            {"statement": "Hecho vacío", "evidence_ids": []},
        ]
    )
    with pytest.raises(ValidationError) as exc:
        ActorAnalysisOutput.model_validate_json(json.dumps(payload))
    assert "evidence_ids" in str(exc.value)
    assert "too_short" in str(exc.value)


def test_below_minimum_grounded_facts_degrades_confidence() -> None:
    eid = str(uuid.uuid4())
    payload = _base_actor_payload(
        facts=[
            {"statement": "Único fact fundado", "evidence_ids": [eid]},
            {"statement": "Basura sin cita", "evidence_ids": []},
            {"statement": "Más basura", "evidence_ids": []},
        ],
        confidence=90,
    )
    cleaned = _sanitize_uncited_facts_json(json.dumps(payload), agent="actor_partnership")
    data = json.loads(cleaned)
    assert len(data["facts"]) == 1
    assert data["confidence"] == QUALITY_DEGRADED_CONFIDENCE_CAP
    assert any("needs_review" in w for w in data["warnings"])
    assert any(
        f"mínimo razonable={MIN_GROUNDED_FACTS_FOR_QUALITY}" in w for w in data["warnings"]
    )
    ActorAnalysisOutput.model_validate_json(cleaned)


def test_entity_resolution_match_downgrades_to_needs_review_when_thin() -> None:
    eid = str(uuid.uuid4())
    payload = {
        "facts": [
            {"statement": "Solo un CIF citado", "evidence_ids": [eid]},
            {"statement": "Sin cita", "evidence_ids": []},
        ],
        "inferences": [],
        "recommendations": [],
        "confidence": 85,
        "open_questions": [],
        "warnings": [],
        "decision": "match",
        "matched_actor_id": str(uuid.uuid4()),
        "rationale": "Mismo CIF",
    }
    cleaned = _sanitize_uncited_facts_json(json.dumps(payload), agent="entity_resolution")
    data = json.loads(cleaned)
    assert data["decision"] == "needs_review"
    assert data["confidence"] == QUALITY_DEGRADED_CONFIDENCE_CAP


def test_missing_evidence_ids_key_is_treated_as_uncited() -> None:
    eid = str(uuid.uuid4())
    payload = _base_actor_payload(
        facts=[
            {"statement": "Con cita", "evidence_ids": [eid]},
            {"statement": "Clave ausente"},  # type: ignore[dict-item]
            {"statement": "Segunda con cita", "evidence_ids": [eid]},
        ]
    )
    cleaned = _sanitize_uncited_facts_json(json.dumps(payload), agent="actor_partnership")
    data = json.loads(cleaned)
    assert len(data["facts"]) == 2
    assert any("Se retiraron 1 fact(s)" in w for w in data["warnings"])


def test_empty_facts_list_untouched() -> None:
    """Si el modelo no emitió facts, no hay nada que sanear ni fallar."""

    payload = _base_actor_payload(facts=[])
    raw = json.dumps(payload)
    assert _sanitize_uncited_facts_json(raw, agent="actor_partnership") == raw
