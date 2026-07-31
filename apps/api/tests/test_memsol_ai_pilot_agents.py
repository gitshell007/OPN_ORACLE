"""Structural + schema fixtures for MEMSOL AI pilot agents (no paid providers)."""

from __future__ import annotations

from opn_oracle.ai.evals import calculate_metrics
from opn_oracle.ai.registry import PromptRegistry
from opn_oracle.ai.schemas import (
    DossierQuestionAnswerOutput,
    ReportCustomBriefPlanOutput,
)


def test_pilot_agents_registered_with_strict_prompts() -> None:
    registry = PromptRegistry("mock-oracle-v1")
    for name in ("dossier_question_answer", "report_custom_brief_plan"):
        prompt = registry.get(name)
        assert prompt.name == name
        assert prompt.version == "v1"
        assert "## Tarea" in prompt.text
        assert "## Reglas" in prompt.text
        assert "## Contrato de salida" in prompt.text
        assert prompt.requires_evidence_review is False


def test_dossier_question_answer_schema_and_eval_fixture() -> None:
    import uuid

    evidence = uuid.UUID("11111111-1111-4111-8111-111111111111")
    output = DossierQuestionAnswerOutput.model_validate(
        {
            "answer_text": "Hay una mención autorizada al contrato marco.",
            "citations": [{"evidence_id": str(evidence), "quote": "contrato marco"}],
            "facts": [
                {
                    "statement": "Contrato marco citado.",
                    "evidence_ids": [evidence],
                }
            ],
            "inferences": [],
            "recommendations": [],
            "confidence": 70,
            "open_questions": [],
            "warnings": [],
        }
    )
    metrics = calculate_metrics(
        output,
        allowed_evidence_ids={str(evidence)},
        predicted_classification="public",
        expected_classification="public",
        accepted=None,
        latency_ms=12,
        cost_micros=0,
    )
    assert metrics.schema_pass is True
    assert metrics.evidence_coverage == 1.0
    assert metrics.unsupported_claim_rate == 0.0


def test_report_custom_brief_plan_schema_fixture() -> None:
    plan = ReportCustomBriefPlanOutput.model_validate(
        {
            "version": "custom_brief_plan.v1",
            "audience": "equipo del expediente",
            "scope": "brief sintético de piloto",
            "period": "sin fijar",
            "sections": [
                {"id": "executive", "title": "Resumen ejecutivo", "required": True},
                {"id": "evidence", "title": "Evidencias", "required": True},
            ],
            "formats": ["html", "json"],
            "notes": ["requiere aceptación"],
            "confidence": 60,
            "open_questions": [],
            "warnings": [],
        }
    )
    assert plan.version == "custom_brief_plan.v1"
    assert len(plan.sections) == 2
