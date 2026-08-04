"""SV2-SANEO-UNIFORME · facts sin evidence_ids: un solo punto, todos los agentes."""

from __future__ import annotations

import json
import uuid

import pytest
from pydantic import ValidationError

from opn_oracle.ai.provider import (
    AGENTS_WITH_STRICT_FACTS,
    DEFAULT_MIN_GROUNDED_FACTS,
    MIN_GROUNDED_FACTS_BY_AGENT,
    MIN_GROUNDED_FACTS_FOR_QUALITY,
    QUALITY_DEGRADED_CONFIDENCE_CAP,
    UncitedFactsError,
    _sanitize_uncited_facts_json,
    min_grounded_facts_for_agent,
)
from opn_oracle.ai.schemas import (
    AGENT_SCHEMAS,
    ActorAnalysisOutput,
    EntityResolutionOutput,
    OpportunityAnalysisOutput,
    RiskAnalysisOutput,
)


# Agentes de demo/SV2 con facts[] estricto (batería parametrizada del camino uniforme).
STRICT_FACTS_DEMO_AGENTS = (
    "actor_partnership",
    "opportunity",
    "risk",
    "entity_resolution",
    "dossier_situation_summary",
)

# Esquemas sin facts[]: el saneo no debe mutar ni fallar.
NO_FACTS_AGENTS = (
    "dossier_completion_wizard",
    "tender_search_wizard",
    "report_custom_brief_plan",
)


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


def _minimal_facts_payload(agent: str, *, facts: list[dict], confidence: int = 80) -> dict:
    """Payload mínimo con facts[] para ejercitar el saneo (no necesita schema completo)."""

    base = {
        "facts": facts,
        "inferences": [],
        "recommendations": [],
        "confidence": confidence,
        "open_questions": [],
        "warnings": [],
    }
    if agent == "entity_resolution":
        base.update(
            {
                "decision": "match",
                "matched_actor_id": str(uuid.uuid4()),
                "rationale": "Mismo CIF",
            }
        )
    elif agent == "dossier_situation_summary":
        # SituationFact usa ``text``; el saneo acepta statement o text en previews.
        converted = []
        for item in facts:
            row = dict(item)
            if "text" not in row and "statement" in row:
                row["text"] = row.pop("statement")
            converted.append(row)
        base = {
            "headline": "Situación demo",
            "executive_summary": "Resumen ejecutivo de prueba.",
            "situation_status": "stable",
            "facts": converted,
            "inferences": [],
            "material_changes": [],
            "opportunities": [],
            "risks": [],
            "relevant_actors": [],
            "deadlines_and_milestones": [],
            "decisions_required": [],
            "recommended_actions": [],
            "knowledge_gaps": [],
            "open_questions": [],
            "confidence": confidence,
            "evidence_coverage": {
                "cited_items": 1,
                "available_items": 3,
                "limitations": [],
            },
            "warnings": [],
        }
    return base


# ---------------------------------------------------------------------------
# Inventario
# ---------------------------------------------------------------------------


def test_inventory_covers_agent_schemas_with_facts() -> None:
    """Todo agente Oracle con facts[] estricto (salvo RT-07) está en el inventario."""

    # dossier_question_answer hereda AgentOutput/Fact pero se consume por RT-07.
    assert "dossier_question_answer" not in AGENTS_WITH_STRICT_FACTS
    for agent in NO_FACTS_AGENTS:
        assert agent not in AGENTS_WITH_STRICT_FACTS
        assert agent in AGENT_SCHEMAS
    for agent in STRICT_FACTS_DEMO_AGENTS:
        assert agent in AGENTS_WITH_STRICT_FACTS
        assert agent in MIN_GROUNDED_FACTS_BY_AGENT
    assert set(MIN_GROUNDED_FACTS_BY_AGENT) == AGENTS_WITH_STRICT_FACTS
    assert MIN_GROUNDED_FACTS_FOR_QUALITY == DEFAULT_MIN_GROUNDED_FACTS == 2
    assert min_grounded_facts_for_agent("entity_resolution") == 1
    assert min_grounded_facts_for_agent("opportunity") == 2
    assert min_grounded_facts_for_agent("unknown_future_agent") == DEFAULT_MIN_GROUNDED_FACTS


# ---------------------------------------------------------------------------
# Camino uniforme parametrizado por agente
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent", STRICT_FACTS_DEMO_AGENTS)
def test_uncited_fact_is_dropped_with_visible_warning(agent: str) -> None:
    eid = str(uuid.uuid4())
    payload = _minimal_facts_payload(
        agent,
        facts=[
            {"statement": "Adjudicación PLACSP con importe real.", "evidence_ids": [eid]},
            {"statement": "Afirmación sin citas del modelo.", "evidence_ids": []},
            {"statement": "Otra sin citas.", "evidence_ids": []},
            {"statement": "Segunda adjudicación citada.", "evidence_ids": [eid]},
        ],
        confidence=80,
    )
    cleaned = _sanitize_uncited_facts_json(json.dumps(payload), agent=agent)
    data = json.loads(cleaned)
    assert len(data["facts"]) == 2
    assert all(item["evidence_ids"] for item in data["facts"])
    assert any("Se retiraron 2 fact(s) sin evidence_ids" in w for w in data["warnings"])
    # ≥ min del agente (todos estos min ∈ {1,2} y quedan 2) → no degrada
    assert data["confidence"] == 80
    if agent == "entity_resolution":
        assert data["decision"] == "match"


@pytest.mark.parametrize("agent", STRICT_FACTS_DEMO_AGENTS)
def test_all_uncited_facts_fail_with_explicit_message_not_schema(agent: str) -> None:
    payload = _minimal_facts_payload(
        agent,
        facts=[
            {"statement": "Sin citas A", "evidence_ids": []},
            {"statement": "Sin citas B", "evidence_ids": []},
        ],
    )
    with pytest.raises(UncitedFactsError, match="el modelo no citó nada"):
        _sanitize_uncited_facts_json(json.dumps(payload), agent=agent)


@pytest.mark.parametrize(
    "agent,schema",
    [
        ("actor_partnership", ActorAnalysisOutput),
        ("opportunity", OpportunityAnalysisOutput),
        ("risk", RiskAnalysisOutput),
        ("entity_resolution", EntityResolutionOutput),
    ],
)
def test_schema_too_short_is_the_pre_fix_death_mode(agent: str, schema: type) -> None:
    """Documenta el flake: model_validate muere en too_short sin el saneo."""

    eid = str(uuid.uuid4())
    if agent == "actor_partnership":
        payload = _base_actor_payload(
            facts=[
                {"statement": "Hecho con cita", "evidence_ids": [eid]},
                {"statement": "Hecho vacío", "evidence_ids": []},
            ]
        )
    elif agent == "entity_resolution":
        payload = {
            "facts": [
                {"statement": "Hecho con cita", "evidence_ids": [eid]},
                {"statement": "Hecho vacío", "evidence_ids": []},
            ],
            "inferences": [],
            "recommendations": [],
            "confidence": 80,
            "open_questions": [],
            "warnings": [],
            "decision": "match",
            "matched_actor_id": str(uuid.uuid4()),
            "rationale": "CIF",
        }
    elif agent == "opportunity":
        payload = {
            "facts": [
                {"statement": "Hecho con cita", "evidence_ids": [eid]},
                {"statement": "Hecho vacío", "evidence_ids": []},
            ],
            "inferences": [],
            "recommendations": [],
            "confidence": 80,
            "open_questions": [],
            "warnings": [],
            "title": "Oportunidad demo",
            "recommendation": "investigate",
            "scores": {
                "strategic_fit": 50,
                "urgency": 50,
                "expected_value": 50,
                "actionability": 50,
                "relationship_leverage": 50,
                "timing": 50,
                "confidence": 50,
                "execution_effort": 50,
                "blocking_risk": 50,
                "overall": 50,
            },
        }
    else:  # risk
        payload = {
            "facts": [
                {"statement": "Hecho con cita", "evidence_ids": [eid]},
                {"statement": "Hecho vacío", "evidence_ids": []},
            ],
            "inferences": [],
            "recommendations": [],
            "confidence": 80,
            "open_questions": [],
            "warnings": [],
            "title": "Riesgo demo",
            "recommended_status": "watch",
            "scores": {
                "impact": 50,
                "likelihood": 50,
                "velocity": 50,
                "exposure": 50,
                "uncertainty": 50,
                "controllability": 50,
                "overall": 50,
            },
        }
    with pytest.raises(ValidationError) as exc:
        schema.model_validate_json(json.dumps(payload))
    assert "evidence_ids" in str(exc.value)
    assert "too_short" in str(exc.value)


@pytest.mark.parametrize(
    "agent,min_expected",
    [
        ("actor_partnership", 2),
        ("opportunity", 2),
        ("risk", 2),
        ("meeting_briefing", 2),
        ("dossier_situation_summary", 1),
        ("entity_resolution", 1),
    ],
)
def test_below_minimum_grounded_facts_degrades_when_under_agent_min(
    agent: str, min_expected: int
) -> None:
    """Con 1 fact fundado: degrada solo si min del agente es 2; min=1 no degrada."""

    eid = str(uuid.uuid4())
    payload = _minimal_facts_payload(
        agent,
        facts=[
            {"statement": "Único fact fundado", "evidence_ids": [eid]},
            {"statement": "Basura sin cita", "evidence_ids": []},
            {"statement": "Más basura", "evidence_ids": []},
        ],
        confidence=90,
    )
    cleaned = _sanitize_uncited_facts_json(json.dumps(payload), agent=agent)
    data = json.loads(cleaned)
    assert len(data["facts"]) == 1
    assert min_grounded_facts_for_agent(agent) == min_expected
    if min_expected > 1:
        assert data["confidence"] == QUALITY_DEGRADED_CONFIDENCE_CAP
        assert any("needs_review" in w for w in data["warnings"])
        assert any(f"mínimo razonable={min_expected}" in w for w in data["warnings"])
        assert any(f"agente={agent}" in w for w in data["warnings"])
        if agent == "entity_resolution":
            # min=1 → este branch no aplica; cubierto abajo
            pass
    else:
        # min=1: un fact fundado es suficiente → no degrada
        assert data["confidence"] == 90
        assert not any("needs_review" in w for w in data["warnings"])
        if agent == "entity_resolution":
            assert data["decision"] == "match"


def test_entity_resolution_zero_grounded_still_fails() -> None:
    payload = _minimal_facts_payload(
        "entity_resolution",
        facts=[{"statement": "Sin cita", "evidence_ids": []}],
    )
    with pytest.raises(UncitedFactsError, match="el modelo no citó nada"):
        _sanitize_uncited_facts_json(json.dumps(payload), agent="entity_resolution")


def test_entity_resolution_match_downgrades_only_when_zero_would_fail_not_with_one() -> None:
    """Regresión del 110: con min=1 ya no se fuerza needs_review por un solo fact."""

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
    assert data["decision"] == "match"
    assert data["confidence"] == 85
    assert len(data["facts"]) == 1


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
    ActorAnalysisOutput.model_validate_json(cleaned)


def test_empty_facts_list_untouched() -> None:
    """Si el modelo no emitió facts, no hay nada que sanear ni fallar."""

    payload = _base_actor_payload(facts=[])
    raw = json.dumps(payload)
    assert _sanitize_uncited_facts_json(raw, agent="actor_partnership") == raw


@pytest.mark.parametrize("agent", NO_FACTS_AGENTS)
def test_agents_without_facts_are_noop(agent: str) -> None:
    """Wizards/plan: no forzar saneo aunque alguien meta un facts[] espurio."""

    raw = json.dumps(
        {
            "summary": "wizard",
            "confidence": 70,
            "facts": [{"statement": "no debería tocarse", "evidence_ids": []}],
        }
    )
    assert _sanitize_uncited_facts_json(raw, agent=agent) == raw


def test_dossier_question_answer_not_in_uniform_path() -> None:
    """RT-07 fail-closed: no mutar validated_output vía este saneo."""

    raw = json.dumps(
        {
            "facts": [{"statement": "x", "evidence_ids": []}],
            "confidence": 50,
            "warnings": [],
        }
    )
    assert _sanitize_uncited_facts_json(raw, agent="dossier_question_answer") == raw
