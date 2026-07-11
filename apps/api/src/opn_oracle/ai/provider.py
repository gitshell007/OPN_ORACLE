"""Provider boundary; no external provider is enabled in phase 09."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class AIUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LLMRequest:
    agent: str
    model: str
    system_prompt: str
    task_prompt: str
    context: dict[str, Any]
    max_output_tokens: int
    classification: str


@dataclass(frozen=True, slots=True)
class LLMResult:
    output: BaseModel
    input_tokens: int
    output_tokens: int
    cost_micros: int
    latency_ms: int


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    status: str
    model: str | None = None


class LLMProvider(Protocol):
    def generate_structured(self, request: LLMRequest, schema: type[T]) -> LLMResult: ...
    def embed(self, texts: list[str]) -> EmbeddingResult: ...
    def health(self) -> ProviderHealth: ...


class DisabledLLMProvider:
    def generate_structured(self, request: LLMRequest, schema: type[T]) -> LLMResult:
        del request, schema
        raise AIUnavailable("El análisis IA no está habilitado.")

    def embed(self, texts: list[str]) -> EmbeddingResult:
        del texts
        raise AIUnavailable("Embeddings no habilitados.")

    def health(self) -> ProviderHealth:
        return ProviderHealth("disabled")


class MockLLMProvider:
    """Deterministic, offline provider for development, CI and evals."""

    def __init__(self, seed: str, model: str = "mock-oracle-v1") -> None:
        self.seed, self.model = seed, model

    def generate_structured(self, request: LLMRequest, schema: type[T]) -> LLMResult:
        evidence = request.context.get("allowed_evidence_ids", [])
        evidence = [uuid.UUID(str(item)) for item in evidence]
        evidence_payload = {
            str(item.get("id")): item
            for item in request.context.get("evidence", [])
            if isinstance(item, dict) and item.get("id")
        }
        confidence = 70 if evidence else 25
        base: dict[str, Any] = {
            "facts": (
                [{"statement": "Hecho sintético verificable.", "evidence_ids": [evidence[0]]}]
                if evidence
                else []
            ),
            "inferences": [],
            "recommendations": [
                {
                    "action": "Revisar el análisis con una persona responsable.",
                    "rationale": "El mock no ejecuta acciones externas.",
                    "priority": "medium",
                }
            ],
            "confidence": confidence,
            "open_questions": [] if evidence else ["Falta evidencia suficiente."],
            "warnings": ["Resultado generado por proveedor mock determinista."],
        }
        extras: dict[str, dict[str, Any]] = {
            "intake": {
                "proposed_title": "Expediente propuesto",
                "proposed_description": "Borrador sujeto a revisión.",
                "dossier_type": "custom",
            },
            "signal_triage": {
                "category": "other",
                "recommended_status": "reviewed",
                "scores": {
                    "relevance": confidence,
                    "novelty": 50,
                    "strategic_impact": 50,
                    "source_credibility": confidence,
                    "confidence": confidence,
                    "overall": confidence,
                },
                "why_it_matters": "Requiere revisión humana.",
            },
            "entity_resolution": {
                "decision": "needs_review",
                "matched_actor_id": None,
                "rationale": "No se realiza merge automático.",
            },
            "opportunity": {
                "title": "Oportunidad candidata",
                "recommendation": "investigate",
                "scores": {
                    "strategic_fit": 50,
                    "urgency": 50,
                    "expected_value": 50,
                    "actionability": 50,
                    "relationship_leverage": 50,
                    "timing": 50,
                    "confidence": confidence,
                    "execution_effort": 50,
                    "blocking_risk": 50,
                    "overall": 50,
                },
            },
            "risk": {
                "title": "Riesgo candidato",
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
            },
            "actor_partnership": {
                "actor_id": None,
                "scores": {
                    "influence": 50,
                    "relevance": 50,
                    "relationship_strength": 50,
                    "accessibility": 50,
                    "strategic_alignment": 50,
                    "recent_activity": 50,
                    "overall_priority": 50,
                },
            },
            "meeting_briefing": {
                "meeting_objective": "Validar objetivos",
                "minimum_outcome": "Aclarar preguntas",
                "ideal_outcome": "Acordar siguiente paso",
            },
            "report_writer": {
                "title": "Informe mock",
                "executive_summary": "Resumen sujeto a revisión.",
                "sections": [
                    {
                        "heading": str(heading),
                        "paragraphs": [
                            {
                                "text": "Contenido sintético sujeto a revisión.",
                                "kind": "inference",
                                "confidence": confidence,
                                "evidence_ids": [],
                            }
                        ],
                    }
                    for heading in request.context.get("requested_scope", {}).get(
                        "required_sections", []
                    )
                ],
                "source_index": (
                    [
                        {
                            "evidence_id": evidence[0],
                            "label": "Evidencia del snapshot",
                            "locator": str(
                                evidence_payload.get(str(evidence[0]), {}).get(
                                    "locator", "Snapshot Oracle"
                                )
                            ),
                        }
                    ]
                    if evidence
                    else []
                ),
            },
            "memory_curator": {"living_summary": "Sin cambios confirmados.", "what_changed": []},
            "evidence_reviewer": {
                "verdict": "pass_with_warnings",
                "unsupported_claims": [],
                "required_corrections": [],
            },
            "weekly_change": {
                "period_start": datetime(2026, 1, 1, tzinfo=UTC),
                "period_end": datetime(2026, 1, 8, tzinfo=UTC),
                "coverage_summary": "Cobertura mock.",
            },
        }
        output = schema.model_validate(base | extras[request.agent])
        fingerprint = hashlib.sha256((self.seed + request.agent).encode()).digest()
        return LLMResult(output, 100 + fingerprint[0], 50 + fingerprint[1], 0, 1)

    def embed(self, texts: list[str]) -> EmbeddingResult:
        vectors = [
            [int.from_bytes(hashlib.sha256(text.encode()).digest()[:2], "big") / 65535]
            for text in texts
        ]
        return EmbeddingResult(vectors, self.model)

    def health(self) -> ProviderHealth:
        return ProviderHealth("healthy", self.model)


def provider_from_config(config: dict[str, Any]) -> LLMProvider:
    if config["AI_MODE"] == "mock" and config["AI_ENABLED"]:
        return MockLLMProvider(config["AI_MOCK_SEED"], config["AI_DEFAULT_MODEL"])
    return DisabledLLMProvider()
