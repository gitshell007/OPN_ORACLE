"""Provider boundary for local, structured and auditable AI execution."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, TypeVar
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


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
    provider: str | None = None
    model: str | None = None
    fallback_used: bool = False
    safe_fallback_used: bool = False


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
        if request.agent == "dossier_situation_summary":
            output = schema.model_validate(
                {
                    "headline": "Situacion sintetica del expediente",
                    "executive_summary": (
                        "Analisis determinista sujeto a revision humana. "
                        "La cobertura depende de las evidencias disponibles."
                    ),
                    "situation_status": "advancing" if evidence else "uncertain",
                    "facts": (
                        [
                            {
                                "text": "Hay al menos una evidencia autorizada en el snapshot.",
                                "evidence_ids": [evidence[0]],
                            }
                        ]
                        if evidence
                        else []
                    ),
                    "inferences": [],
                    "material_changes": [],
                    "opportunities": [],
                    "risks": [],
                    "relevant_actors": [],
                    "deadlines_and_milestones": [],
                    "decisions_required": [],
                    "recommended_actions": [
                        {
                            "action": "Revisar el analisis asistido con la persona responsable.",
                            "rationale": "El proveedor mock no ejecuta acciones ni decide.",
                            "priority": "medium",
                        }
                    ],
                    "knowledge_gaps": [] if evidence else ["Falta evidencia suficiente."],
                    "open_questions": [] if evidence else ["Que fuentes deben incorporarse?"],
                    "confidence": confidence,
                    "evidence_coverage": {
                        "cited_items": 1 if evidence else 0,
                        "available_items": len(evidence),
                        "limitations": [] if evidence else ["Sin evidencias citables."],
                    },
                    "warnings": ["Resultado generado por proveedor mock determinista."],
                }
            )
            fingerprint = hashlib.sha256((self.seed + request.agent).encode()).digest()
            return LLMResult(
                output,
                100 + fingerprint[0],
                50 + fingerprint[1],
                0,
                1,
                provider="mock",
                model=self.model,
            )
        if request.agent == "tender_search_wizard":
            from opn_oracle.oracle.comparable_procurement import title_terms

            description = str(request.context.get("description") or "").strip()
            accepted = request.context.get("accepted_plan")
            feedback = request.context.get("feedback_digest")
            if (
                request.context.get("mode") == "replan"
                and isinstance(accepted, dict)
                and isinstance(feedback, dict)
            ):
                accepted_terms = [
                    str(item) for item in accepted.get("include_terms", []) if isinstance(item, str)
                ]
                accepted_exclusions = [
                    str(item) for item in accepted.get("exclude_terms", []) if isinstance(item, str)
                ]
                rejected_digest = feedback.get("exclusion_candidates")
                rejected_candidates = rejected_digest if isinstance(rejected_digest, dict) else {}
                reinforced_digest = feedback.get("reinforcement_candidates")
                reinforced_candidates = (
                    reinforced_digest if isinstance(reinforced_digest, dict) else {}
                )
                rejected = [
                    str(item.get("value"))
                    for item in rejected_candidates.get("terms", [])
                    if isinstance(item, dict) and item.get("value")
                ]
                reinforced = [
                    str(item.get("value"))
                    for item in reinforced_candidates.get("terms", [])
                    if isinstance(item, dict) and item.get("value")
                ]
                rejected_keys = {item.casefold() for item in rejected}
                include_terms = [
                    item for item in accepted_terms if item.casefold() not in rejected_keys
                ]
                include_terms = list(dict.fromkeys([*include_terms, *reinforced]))[:50]
                exclude_terms = list(dict.fromkeys([*accepted_exclusions, *rejected]))[:50]

                rejected_cpvs = {
                    str(item.get("code"))
                    for item in rejected_candidates.get("cpvs", [])
                    if isinstance(item, dict) and item.get("code")
                }
                accepted_cpvs = [
                    item
                    for item in accepted.get("candidate_cpv", [])
                    if isinstance(item, dict)
                    and item.get("code")
                    and str(item.get("code")) not in rejected_cpvs
                ]
                reinforced_cpvs = [
                    {"code": str(item.get("code")), "label": None}
                    for item in reinforced_candidates.get("cpvs", [])
                    if isinstance(item, dict) and item.get("code")
                ]
                candidate_cpv = list(
                    {
                        str(item["code"]): {
                            "code": str(item["code"]),
                            "label": item.get("label"),
                        }
                        for item in [*accepted_cpvs, *reinforced_cpvs]
                    }.values()
                )[:50]
                output = schema.model_validate(
                    {
                        **accepted,
                        "include_terms": include_terms,
                        "exclude_terms": exclude_terms,
                        "candidate_cpv": candidate_cpv,
                        "min_amount": _decimal_or_none(accepted.get("min_amount")),
                        "max_amount": _decimal_or_none(accepted.get("max_amount")),
                        "assumptions": [
                            *[
                                str(item)
                                for item in accepted.get("assumptions", [])
                                if isinstance(item, str)
                            ],
                            (
                                "Revisión explícita basada en el digest determinista "
                                "del feedback acumulado."
                            ),
                        ][:20],
                        "discarded_count": 0,
                        "discarded_reasons": {},
                    }
                )
                fingerprint = hashlib.sha256((self.seed + request.agent).encode()).digest()
                return LLMResult(
                    output,
                    100 + fingerprint[0],
                    50 + fingerprint[1],
                    0,
                    1,
                    provider="mock",
                    model=self.model,
                )
            comparable_profile = request.context.get("comparable_profile")
            grounding = comparable_profile if isinstance(comparable_profile, dict) else {}
            top_cpvs = grounding.get("top_cpvs")
            top_terms = grounding.get("top_terms")
            top_buyers = grounding.get("top_buyers")
            measured_terms = [
                str(item.get("term"))
                for item in (top_terms if isinstance(top_terms, list) else [])
                if isinstance(item, dict) and item.get("term")
            ]
            terms = measured_terms[:20] or sorted(title_terms(description))[:20]
            output = schema.model_validate(
                {
                    "intent_summary": (
                        f"Buscar contratación pública relacionada con: {description[:500]}"
                        if description
                        else "Definir una búsqueda de contratación pública revisable."
                    ),
                    "include_terms": terms,
                    "synonyms": [],
                    "exclude_terms": [],
                    "candidate_cpv": [
                        {"code": str(item.get("code")), "label": None}
                        for item in (top_cpvs if isinstance(top_cpvs, list) else [])[:20]
                        if isinstance(item, dict) and item.get("code")
                    ],
                    "buyers": [
                        str(item.get("buyer"))
                        for item in (top_buyers if isinstance(top_buyers, list) else [])[:10]
                        if isinstance(item, dict) and item.get("buyer")
                    ],
                    "geographies": [],
                    "scope": "active",
                    "min_amount": None,
                    "max_amount": None,
                    "assumptions": (
                        [
                            "El perfil de la comparable orienta candidatos, pero no demuestra "
                            "las capacidades de la empresa usuaria."
                        ]
                        if grounding
                        else ["No se aportó una comparable medida."]
                    ),
                    "questions": ["¿Qué geografías y organismos compradores deben priorizarse?"],
                    "confidence": 70 if grounding else 45,
                    "discarded_count": 0,
                    "discarded_reasons": {},
                }
            )
            fingerprint = hashlib.sha256((self.seed + request.agent).encode()).digest()
            return LLMResult(
                output,
                100 + fingerprint[0],
                50 + fingerprint[1],
                0,
                1,
                provider="mock",
                model=self.model,
            )
        if request.agent == "dossier_completion_wizard":
            snapshot = request.context.get("completion_snapshot", {})
            counts = snapshot.get("counts", {}) if isinstance(snapshot, dict) else {}
            dossier = snapshot.get("dossier", {}) if isinstance(snapshot, dict) else {}
            has_monitors = int(counts.get("monitors") or 0) > 0
            has_procurement = int(counts.get("procurement_items") or 0) > 0
            has_actors = int(counts.get("actors") or 0) > 0
            has_opportunities = int(counts.get("opportunities") or 0) > 0
            has_risks = int(counts.get("risks") or 0) > 0
            has_hypotheses = int(counts.get("hypotheses") or 0) > 0
            goal = str(dossier.get("strategic_goal") or "")
            vehicle_keywords = [
                "vehículos de emergencia",
                "camiones de bomberos",
                "autoescala",
                "autobomba",
                "contratación pública",
            ]
            output = schema.model_validate(
                {
                    "summary": (
                        "El expediente tiene objetivo, pero necesita vigilancia, referencias de "
                        "contratación y actores para convertirse en un radar operativo."
                    ),
                    "confidence": 72,
                    "warnings": ["Resultado generado por proveedor mock determinista."],
                    "section_diagnostics": [
                        {
                            "section": "goal",
                            "status": "ok" if goal else "incomplete",
                            "explanation": (
                                "El objetivo orienta el análisis; conviene acotar ámbito y "
                                "tipo de vehículo."
                                if goal
                                else "Falta un objetivo que guíe las recomendaciones."
                            ),
                        },
                        {
                            "section": "signals",
                            "status": "ok" if has_monitors else "empty",
                            "explanation": (
                                "Hay vigilancia configurada; las señales dependerán de la "
                                "sincronización."
                                if has_monitors
                                else "No hay monitores activos que alimenten señales al expediente."
                            ),
                        },
                        {
                            "section": "procurement",
                            "status": "ok" if has_procurement else "empty",
                            "explanation": (
                                "Ya hay licitaciones o adjudicaciones fijadas."
                                if has_procurement
                                else (
                                    "Sin referencias fijadas, Oracle no puede comparar "
                                    "adjudicatarios ni organismos."
                                )
                            ),
                        },
                        {
                            "section": "opportunities",
                            "status": "ok" if has_opportunities else "empty",
                            "explanation": (
                                "Ya hay oportunidades estratégicas abiertas."
                                if has_opportunities
                                else "Aún no hay oportunidades derivadas de señales o fuentes."
                            ),
                        },
                        {
                            "section": "risks",
                            "status": "ok" if has_risks else "empty",
                            "explanation": (
                                "Ya hay riesgos estratégicos registrados."
                                if has_risks
                                else "Aún no hay riesgos explícitos que proteger o vigilar."
                            ),
                        },
                        {
                            "section": "actors",
                            "status": "ok" if has_actors else "empty",
                            "explanation": (
                                "Hay actores vinculados al expediente."
                                if has_actors
                                else (
                                    "Faltan competidores, organismos compradores y posibles socios."
                                )
                            ),
                        },
                        {
                            "section": "hypotheses",
                            "status": "ok" if has_hypotheses else "empty",
                            "explanation": (
                                "Ya hay hipótesis para contrastar."
                                if has_hypotheses
                                else "Faltan hipótesis de trabajo que guíen la vigilancia."
                            ),
                        },
                    ],
                    "questions": [
                        {
                            "id": "scope.geography",
                            "question": "¿Qué ámbito geográfico quieres vigilar primero?",
                            "why_it_matters": (
                                "Evita ruido y permite ajustar geografía del monitor y "
                                "búsquedas de licitación."
                            ),
                            "expected_input": (
                                "Ej.: España, Aragón, Comunidad Valenciana, Unión Europea."
                            ),
                        },
                        {
                            "id": "scope.vehicle_type",
                            "question": (
                                "¿Qué tipo de vehículo de emergencia te interesa priorizar?"
                            ),
                            "why_it_matters": (
                                "Las keywords cambian si buscas autobombas, autoescalas, "
                                "ambulancias o vehículos ligeros."
                            ),
                            "expected_input": (
                                "Ej.: autobombas forestales, autoescalas, vehículos de mando."
                            ),
                        },
                        {
                            "id": "scope.buyers",
                            "question": (
                                "¿Hay órganos de contratación o administraciones que debamos "
                                "seguir sí o sí?"
                            ),
                            "why_it_matters": (
                                "Ayuda a fijar licitaciones relevantes y a detectar "
                                "compradores recurrentes."
                            ),
                            "expected_input": (
                                "Ej.: ayuntamientos, consorcios provinciales, diputaciones."
                            ),
                        },
                    ],
                    "recommended_actions": [
                        {
                            "kind": "create_signal_monitor",
                            "title": "Crear una vigilancia de vehículos de emergencia",
                            "rationale": "Sin monitor no entrarán señales nuevas al expediente.",
                            "prefill": {
                                "name": "Vehículos de emergencia y licitaciones",
                                "query": "licitación vehículos de emergencia bomberos",
                                "keywords": vehicle_keywords,
                                "source_types": ["official_publication", "news"],
                                "languages": ["es"],
                                "geographies": ["ES"],
                                "cadence": "daily",
                            },
                        },
                        {
                            "kind": "pin_procurement",
                            "title": "Buscar licitaciones y adjudicaciones fijables",
                            "rationale": (
                                "Las referencias fijadas serán la base citable para comparar "
                                "competencia."
                            ),
                            "prefill": {
                                "procurement_query": (
                                    "vehículos emergencia bomberos autobomba autoescala"
                                ),
                                "procurement_kind": "tender",
                            },
                        },
                        {
                            "kind": "create_actor",
                            "title": "Añadir adjudicatarios habituales como competidores",
                            "rationale": (
                                "El mapa de actores permite entender quién compite o influye "
                                "en el mercado."
                            ),
                            "prefill": {
                                "title": "Adjudicatario relevante",
                                "actor_type": "organization",
                                "tags": ["fabricante", "contratación pública"],
                                "roles": ["competidor", "adjudicatario habitual"],
                            },
                        },
                    ],
                }
            )
            fingerprint = hashlib.sha256((self.seed + request.agent).encode()).digest()
            return LLMResult(
                output,
                100 + fingerprint[0],
                50 + fingerprint[1],
                0,
                1,
                provider="mock",
                model=self.model,
            )
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
                "top_opportunities": ["Priorizar una oportunidad verificable del expediente."],
                "top_risks": ["Revisar un riesgo relevante antes de decidir."],
                "recommended_actions": ["Contrastar el informe con la persona responsable."],
            },
            "competitive_procurement_intelligence": {
                "title": "Inteligencia competitiva mock",
                "executive_summary": "Agregados deterministas sujetos a revisión.",
                "sections": [
                    {
                        "heading": str(heading),
                        "paragraphs": [
                            {
                                "text": "Interpretación sintética del agregado calculado.",
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
                "source_index": [],
                "top_opportunities": ["Explorar organismos con concentración compradora."],
                "top_risks": ["No interpretar adjudicaciones ganadas como tasa de éxito."],
                "recommended_actions": ["Revisar la estrategia comercial con los agregados."],
            },
            "entity_dossier_intelligence": {
                "title": "Informe de entidad mock",
                "executive_summary": "Síntesis preliminar de la ficha agregada de entidad.",
                "sections": [
                    {
                        "heading": str(heading),
                        "paragraphs": [
                            {
                                "text": (
                                    "Interpretación sintética de la ficha agregada y sus límites."
                                ),
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
                "source_index": [],
                "warnings": [
                    (
                        "Las fechas BORME son de publicación; homónimos, grafo y "
                        "noticias requieren revisión humana."
                    )
                ],
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
        return LLMResult(
            output,
            100 + fingerprint[0],
            50 + fingerprint[1],
            0,
            1,
            provider="mock",
            model=self.model,
        )

    def embed(self, texts: list[str]) -> EmbeddingResult:
        vectors = [
            [int.from_bytes(hashlib.sha256(text.encode()).digest()[:2], "big") / 65535]
            for text in texts
        ]
        return EmbeddingResult(vectors, self.model)

    def health(self) -> ProviderHealth:
        return ProviderHealth("healthy", self.model)


class OllamaLLMProvider:
    """Local Ollama adapter with schema-constrained responses and no cloud fallback."""

    def __init__(self, *, base_url: str, model: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.model = model
        self.timeout_seconds = timeout_seconds

    def generate_structured(self, request: LLMRequest, schema: type[T]) -> LLMResult:
        payload = {
            "model": request.model,
            "stream": False,
            "format": schema.model_json_schema(),
            "options": {"temperature": 0, "num_predict": request.max_output_tokens},
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"{request.task_prompt}\n\n"
                        "Contexto autorizado (JSON):\n"
                        f"{json.dumps(request.context, ensure_ascii=False, separators=(',', ':'))}"
                    ),
                },
            ],
        }
        if request.agent == "tender_search_wizard":
            # Ollama/qwen3.5:9b rejects this schema grammar before inference, while
            # JSON mode plus thinking disabled returns JSON that still passes the
            # mandatory Pydantic validation below. Keep both overrides task-local.
            payload["format"] = "json"
            payload["think"] = False
        started = time.monotonic()
        try:
            response = httpx.post(
                urljoin(self.base_url, "api/chat"),
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            content = body["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("message.content no es texto")
            output = schema.model_validate_json(content)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise AIUnavailable("Ollama no devolvió una respuesta estructurada válida.") from error
        elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
        return LLMResult(
            output=output,
            input_tokens=_non_negative_int(body.get("prompt_eval_count")),
            output_tokens=_non_negative_int(body.get("eval_count")),
            # Ollama local has no coste API imputable; infrastructure cost stays outside
            # this ledger.
            cost_micros=0,
            latency_ms=_non_negative_int(body.get("total_duration"), divisor=1_000_000)
            or elapsed_ms,
            provider="ollama",
            model=request.model,
        )

    def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult([], self.model)
        try:
            response = httpx.post(
                urljoin(self.base_url, "api/embed"),
                json={"model": self.model, "input": texts},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            vectors = response.json()["embeddings"]
            if not isinstance(vectors, list) or not all(isinstance(item, list) for item in vectors):
                raise TypeError("embeddings no válido")
            normalized = [[float(value) for value in item] for item in vectors]
            return EmbeddingResult(normalized, self.model)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise AIUnavailable("Ollama no devolvió embeddings válidos.") from error

    def health(self) -> ProviderHealth:
        try:
            response = httpx.get(urljoin(self.base_url, "api/tags"), timeout=self.timeout_seconds)
            response.raise_for_status()
        except httpx.HTTPError:
            return ProviderHealth("unavailable", self.model)
        return ProviderHealth("healthy", self.model)


def _validate_allowed_evidence(output: BaseModel, allowed_values: list[str]) -> None:
    """Reject model citations that are not part of the authorized context snapshot."""

    allowed: set[uuid.UUID] = set()
    for value in allowed_values:
        try:
            allowed.add(uuid.UUID(value))
        except ValueError:
            continue

    def nested_ids(value: Any) -> set[uuid.UUID]:
        if isinstance(value, BaseModel):
            cited: set[uuid.UUID] = set()
            for name in type(value).model_fields:
                child = getattr(value, name)
                if name == "evidence_ids" and isinstance(child, list):
                    cited.update(item for item in child if isinstance(item, uuid.UUID))
                else:
                    cited.update(nested_ids(child))
            return cited
        if isinstance(value, (list, tuple)):
            return {item for child in value for item in nested_ids(child)}
        if isinstance(value, dict):
            return {item for child in value.values() for item in nested_ids(child)}
        return set()

    unauthorized = nested_ids(output) - allowed
    if unauthorized:
        raise ValueError(
            "El JSON candidato cita evidence_ids no autorizados; elimina los bloques afectados."
        )


def _strip_unauthorized_evidence_blocks(output: T, allowed_values: list[str]) -> T:
    """Drop complete claim blocks that cite evidence outside the snapshot.

    This is a last-resort safety net after the governed model has already received one
    repair attempt. Keeping the surrounding claim without its citation would turn an
    unsupported statement into a seemingly valid one, so the whole block is removed.
    """

    allowed = set(allowed_values)
    dropped = object()

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            evidence = value.get("evidence_ids")
            if isinstance(evidence, list) and any(str(item) not in allowed for item in evidence):
                return dropped
            cleaned: dict[str, Any] = {}
            for key, child in value.items():
                candidate = clean(child)
                if candidate is not dropped:
                    cleaned[key] = candidate
            return cleaned
        if isinstance(value, list):
            cleaned_items = [clean(item) for item in value]
            return [item for item in cleaned_items if item is not dropped]
        return value

    payload = clean(output.model_dump(mode="json"))
    if not isinstance(payload, dict):
        raise ValueError("No se pudo sanear la salida estructurada.")
    warnings = payload.get("warnings")
    if isinstance(warnings, list):
        warning = "Se omitieron bloques con citas no autorizadas por el expediente."
        if warning not in warnings:
            warnings.append(warning)
    # Modo JSON, no modo Python: `payload` viene de model_dump(mode="json"), así que
    # los evidence_ids supervivientes son cadenas y los contratos IA son estrictos
    # (strict=True), que en modo Python exige instancias UUID. Validar aquí en modo
    # Python hacía reventar esta red de seguridad justo cuando actúa —con citas no
    # autorizadas que depurar—, tirando el informe entero en lugar de salvarlo.
    return type(output).model_validate_json(json.dumps(payload))


def _safe_empty_evidence_summary(request: LLMRequest, schema: type[T]) -> T:
    if request.agent != "dossier_situation_summary":
        raise ValueError("No existe fallback seguro para este contrato IA.")
    return schema.model_validate(
        {
            "headline": "Evidencia insuficiente para completar el análisis",
            "executive_summary": (
                "El expediente no dispone todavía de evidencias vinculadas suficientes para "
                "publicar hechos, cambios, oportunidades o riesgos trazables."
            ),
            "situation_status": "uncertain",
            "facts": [],
            "inferences": [],
            "material_changes": [],
            "opportunities": [],
            "risks": [],
            "relevant_actors": [],
            "deadlines_and_milestones": [],
            "decisions_required": [],
            "recommended_actions": [
                {
                    "action": "Vincular evidencias verificables al expediente",
                    "rationale": (
                        "El análisis necesita fuentes autorizadas para producir conclusiones "
                        "trazables."
                    ),
                    "priority": "high",
                }
            ],
            "knowledge_gaps": ["No hay evidencias vinculadas al expediente."],
            "open_questions": [
                "¿Qué documentos o señales verificables deben sustentar el análisis?"
            ],
            "confidence": 0,
            "evidence_coverage": {
                "cited_items": 0,
                "available_items": 0,
                "limitations": ["No hay evidencia autorizada disponible."],
            },
            "warnings": [
                "El modelo no produjo una salida publicable y se aplicó un fallback seguro."
            ],
        }
    )


def _normalize_signal_candidate_json(
    request: LLMRequest, raw_output: str, allowed_evidence_ids: list[str]
) -> str:
    """Coerce common LLM shape drift before strict schema validation.

    The provider still validates with Pydantic afterwards. This adapter only handles
    recoverable report-writer drift observed with governed local models: strings where
    small objects are expected, missing optional operational lists, invalid priorities,
    and unsafe or absent evidence ids. It never turns an uncited claim into a fact.
    """

    if request.agent not in {
        "report_writer",
        "competitive_procurement_intelligence",
        "entity_dossier_intelligence",
    }:
        return raw_output
    try:
        candidate = json.loads(raw_output)
    except ValueError:
        return raw_output
    if not isinstance(candidate, dict):
        return raw_output

    allowed = set(allowed_evidence_ids)

    def as_text(value: Any, fallback: str = "") -> str:
        if isinstance(value, str):
            text = value.strip()
        elif value is None:
            text = ""
        else:
            text = str(value).strip()
        return text or fallback

    def as_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if value in (None, ""):
            return []
        return [value]

    def as_string_list(value: Any) -> list[str]:
        return [text for item in as_list(value) if (text := as_text(item))]

    def as_confidence(value: Any, fallback: int = 60) -> int:
        try:
            return max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return fallback

    def evidence_ids(value: Any) -> list[str]:
        cleaned: list[str] = []
        for item in as_list(value):
            try:
                parsed = str(uuid.UUID(str(item)))
            except (TypeError, ValueError):
                continue
            if parsed in allowed and parsed not in cleaned:
                cleaned.append(parsed)
        return cleaned

    def fact_items(value: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in as_list(value):
            if isinstance(item, dict):
                statement = as_text(item.get("statement") or item.get("text"))
                ids = evidence_ids(item.get("evidence_ids"))
            else:
                statement = as_text(item)
                ids = []
            if statement and ids:
                items.append({"statement": statement, "evidence_ids": ids})
        return items

    def inference_items(value: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in as_list(value):
            if isinstance(item, dict):
                statement = as_text(item.get("statement") or item.get("text"))
                reasoning = as_text(
                    item.get("reasoning_summary") or item.get("rationale"), statement
                )
                confidence = as_confidence(item.get("confidence"))
                ids = evidence_ids(item.get("evidence_ids"))
            else:
                statement = as_text(item)
                reasoning = statement
                confidence = 50
                ids = []
            if statement and reasoning:
                items.append(
                    {
                        "statement": statement,
                        "reasoning_summary": reasoning,
                        "confidence": confidence,
                        "evidence_ids": ids,
                    }
                )
        return items

    def recommendation_items(value: Any) -> list[dict[str, Any]]:
        allowed_priorities = {"low", "medium", "high", "critical"}
        items: list[dict[str, Any]] = []
        for item in as_list(value):
            if isinstance(item, dict):
                action = as_text(item.get("action") or item.get("text"))
                rationale = as_text(
                    item.get("rationale") or item.get("reasoning_summary"),
                    "Recomendación generada a partir del contexto autorizado.",
                )
                priority = as_text(item.get("priority"), "medium")
            else:
                action = as_text(item)
                rationale = "Recomendación generada a partir del contexto autorizado."
                priority = "medium"
            if priority not in allowed_priorities:
                priority = "medium"
            if action:
                items.append({"action": action, "rationale": rationale, "priority": priority})
        return items

    def paragraph_item(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            text = as_text(value.get("text") or value.get("statement"))
            kind = as_text(value.get("kind"), "inference")
            confidence = as_confidence(value.get("confidence"))
            ids = evidence_ids(value.get("evidence_ids"))
        else:
            text = as_text(value)
            kind = "inference"
            confidence = 50
            ids = []
        if kind not in {"fact", "inference", "recommendation", "decision"}:
            kind = "inference"
        if kind == "fact" and not ids:
            kind = "inference"
            confidence = min(confidence, 70)
        if not text:
            return None
        return {"text": text, "kind": kind, "confidence": confidence, "evidence_ids": ids}

    def section_items(value: Any) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        for item in as_list(value):
            if isinstance(item, dict):
                heading = as_text(item.get("heading") or item.get("title"), "Sección")
                paragraphs = [
                    paragraph
                    for raw_paragraph in as_list(item.get("paragraphs") or item.get("content"))
                    if (paragraph := paragraph_item(raw_paragraph)) is not None
                ]
            else:
                heading = "Sección"
                paragraph = paragraph_item(item)
                paragraphs = [paragraph] if paragraph else []
            sections.append({"heading": heading, "paragraphs": paragraphs})
        return sections

    sections = section_items(candidate.get("sections"))
    warnings = as_string_list(candidate.get("warnings"))
    normalized: dict[str, Any] = {
        "facts": fact_items(candidate.get("facts")),
        "inferences": inference_items(candidate.get("inferences")),
        "recommendations": recommendation_items(candidate.get("recommendations")),
        "confidence": as_confidence(candidate.get("confidence")),
        "open_questions": as_string_list(candidate.get("open_questions")),
        "warnings": warnings,
        "title": as_text(candidate.get("title"), "Informe estratégico"),
        "executive_summary": as_text(
            candidate.get("executive_summary"),
            "Síntesis generada a partir del contexto autorizado.",
        ),
        "sections": sections,
        "top_opportunities": as_string_list(candidate.get("top_opportunities")),
        "top_risks": as_string_list(candidate.get("top_risks")),
        "recommended_actions": as_string_list(candidate.get("recommended_actions")),
        "decisions_required": as_string_list(candidate.get("decisions_required")),
        # Reporting builds the authoritative source index from the final cited claims
        # and the immutable snapshot. Model-provided entries are intentionally ignored.
        "source_index": [],
    }
    if sections and not any(
        paragraph["evidence_ids"] for section in sections for paragraph in section["paragraphs"]
    ):
        warnings.append(
            "El informe no contiene párrafos citados; se publica como análisis inferencial."
        )
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


class SignalGovernedLLMProvider:
    """Adapter for Signal's governed `/api/v1/ai/run` proxy."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        consumer: str = "opn-oracle",
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.consumer = consumer

    def generate_structured(self, request: LLMRequest, schema: type[T]) -> LLMResult:
        schema_json = json.dumps(
            schema.model_json_schema(), ensure_ascii=False, separators=(",", ":")
        )
        context_json = json.dumps(request.context, ensure_ascii=False, separators=(",", ":"))
        allowed_evidence_ids = [
            str(item) for item in request.context.get("allowed_evidence_ids", [])
        ]
        allowed_evidence_json = json.dumps(
            allowed_evidence_ids, ensure_ascii=False, separators=(",", ":")
        )
        evidence_rule = (
            "Los únicos evidence_ids permitidos son: "
            f"{allowed_evidence_json}. No inventes ni copies otros UUID. "
            "Si la lista está vacía, deja vacías todas las secciones cuyos elementos "
            "exijan evidence_ids."
        )
        body: dict[str, Any] = {
            "task_key": request.agent,
            "input": {
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"{request.system_prompt}\n\n"
                            f"{evidence_rule}\n\n"
                            "Devuelve exclusivamente JSON válido que cumpla este esquema: "
                            f"{schema_json}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"{request.task_prompt}\n\nContexto autorizado (JSON):\n{context_json}"
                        ),
                    },
                ],
                "format": "json",
                "max_output_tokens": request.max_output_tokens,
            },
        }
        started = time.monotonic()
        safe_fallback_used = False
        payload = self._run(body)
        normalized_output = _signal_output(payload)
        normalized_output = _normalize_signal_candidate_json(
            request, normalized_output, allowed_evidence_ids
        )
        usage = _usage(payload)
        try:
            output = schema.model_validate_json(normalized_output)
            _validate_allowed_evidence(output, allowed_evidence_ids)
            if request.agent == "dossier_situation_summary" and not allowed_evidence_ids:
                output = _safe_empty_evidence_summary(request, schema)
                safe_fallback_used = True
        except ValueError as validation_error:
            repair_errors: list[dict[str, Any]]
            if isinstance(validation_error, ValidationError):
                repair_errors = [
                    dict(item)
                    for item in validation_error.errors(
                        include_input=False,
                        include_url=False,
                    )
                ]
            else:
                repair_errors = [{"type": "invalid_json", "msg": str(validation_error)[:1000]}]
            repair_errors_json = json.dumps(
                repair_errors, ensure_ascii=False, separators=(",", ":")
            )
            repair_body = {
                **body,
                "input": {
                    **body["input"],
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Eres un reparador de JSON. Devuelve exclusivamente un objeto JSON "
                                "válido que cumpla exactamente el esquema, sin Markdown ni campos "
                                "adicionales. Conserva el significado y no inventes evidence_ids. "
                                f"{evidence_rule} "
                                f"Esquema: {schema_json}"
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                "Repara este JSON candidato:\n"
                                f"{normalized_output}\n\n"
                                "Errores de validación (JSON):\n"
                                f"{repair_errors_json}"
                            ),
                        },
                    ],
                },
            }
            payload = self._run(repair_body)
            repaired_usage = _usage(payload)
            usage = {
                "input_tokens": _usage_tokens(usage, "input")
                + _usage_tokens(repaired_usage, "input"),
                "output_tokens": _usage_tokens(usage, "output")
                + _usage_tokens(repaired_usage, "output"),
                "cost_micros": _non_negative_int(usage.get("cost_micros"))
                + _non_negative_int(repaired_usage.get("cost_micros")),
            }
            try:
                repaired_raw_output = _normalize_signal_candidate_json(
                    request, _signal_output(payload), allowed_evidence_ids
                )
                repaired_output = schema.model_validate_json(repaired_raw_output)
            except ValueError:
                if allowed_evidence_ids:
                    raise
                output = _safe_empty_evidence_summary(request, schema)
                safe_fallback_used = True
            else:
                try:
                    _validate_allowed_evidence(repaired_output, allowed_evidence_ids)
                except ValueError:
                    try:
                        output = _strip_unauthorized_evidence_blocks(
                            repaired_output, allowed_evidence_ids
                        )
                        _validate_allowed_evidence(output, allowed_evidence_ids)
                    except ValueError:
                        if allowed_evidence_ids:
                            raise
                        output = _safe_empty_evidence_summary(request, schema)
                        safe_fallback_used = True
                else:
                    output = repaired_output
        elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
        return LLMResult(
            output=output,
            input_tokens=_usage_tokens(usage, "input"),
            output_tokens=_usage_tokens(usage, "output"),
            cost_micros=_non_negative_int(usage.get("cost_micros") or payload.get("cost_micros")),
            latency_ms=_non_negative_int(payload.get("latency_ms")) or elapsed_ms,
            provider=str(payload.get("provider") or payload.get("actual_provider") or "signal"),
            model=str(payload.get("model") or payload.get("actual_model") or request.model),
            fallback_used=bool(payload.get("fallback_used", False)),
            safe_fallback_used=safe_fallback_used,
        )

    def _run(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(
                urljoin(self.base_url, "api/v1/ai/run"),
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise AIUnavailable("Signal no esta disponible para ejecutar IA.") from error
        if not isinstance(payload, dict):
            raise AIUnavailable("Signal devolvio una respuesta IA sin JSON estructurado.")
        return payload

    def embed(self, texts: list[str]) -> EmbeddingResult:
        del texts
        raise AIUnavailable("Embeddings gobernados por Signal no estan habilitados.")

    def health(self) -> ProviderHealth:
        return ProviderHealth("configured", "signal-governed")


def _non_negative_int(value: Any, *, divisor: int = 1) -> int:
    try:
        return max(0, int(value) // divisor)
    except (TypeError, ValueError):
        return 0


def _usage(payload: dict[str, Any]) -> dict[str, Any]:
    usage = payload.get("usage", {})
    return usage if isinstance(usage, dict) else {}


def _usage_tokens(usage: dict[str, Any], direction: str) -> int:
    primary = f"{direction}_tokens"
    fallback = "prompt_tokens" if direction == "input" else "completion_tokens"
    return _non_negative_int(usage.get(primary) or usage.get(fallback))


def _signal_output(payload: dict[str, Any]) -> str:
    result_payload = payload.get("result")
    if not isinstance(result_payload, dict):
        raise AIUnavailable("Signal devolvio una respuesta IA sin JSON estructurado.")
    # Signal reenvía la respuesta cruda del proveedor upstream, y su forma cambia con
    # el proveedor: Ollama devuelve `message.content` (chat) o `response` (generate),
    # mientras que OpenRouter/OpenAI devuelve `choices[0].message.content`. Sin la rama
    # OpenAI, cambiar la task a OpenRouter hacía que Oracle no encontrara el contenido y
    # fallara con "AIUnavailable" pese a un 200 real del modelo.
    message = result_payload.get("message")
    output_payload = message.get("content") if isinstance(message, dict) else None
    output_payload = output_payload or result_payload.get("response")
    if not isinstance(output_payload, str):
        choices = result_payload.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            choice_message = choices[0].get("message")
            if isinstance(choice_message, dict):
                output_payload = choice_message.get("content")
    if not isinstance(output_payload, str):
        raise AIUnavailable("Signal devolvio una respuesta IA sin JSON estructurado.")
    normalized = output_payload.strip()
    if normalized.startswith("```"):
        normalized = normalized.split("\n", 1)[1] if "\n" in normalized else ""
        if normalized.endswith("```"):
            normalized = normalized[:-3].strip()
    return normalized


def provider_from_config(config: dict[str, Any]) -> LLMProvider:
    if config["AI_MODE"] == "mock" and config["AI_ENABLED"]:
        return MockLLMProvider(config["AI_MOCK_SEED"], config["AI_DEFAULT_MODEL"])
    if config["AI_MODE"] == "signal" and config["AI_ENABLED"]:
        parsed = urlparse(str(config["SIGNAL_AI_BASE_URL"]))
        allowed_hosts = {
            item.strip().lower()
            for item in str(config["SIGNAL_AI_ALLOWED_HOSTS"]).split(",")
            if item.strip()
        }
        if not parsed.hostname or parsed.hostname.lower() not in allowed_hosts:
            raise AIUnavailable("El host de Signal IA no esta permitido.")
        return SignalGovernedLLMProvider(
            base_url=str(config["SIGNAL_AI_BASE_URL"]),
            api_key=str(config["SIGNAL_AI_API_KEY"]),
            timeout_seconds=float(config["SIGNAL_AI_TIMEOUT_SECONDS"]),
        )
    if config["AI_MODE"] == "ollama" and config["AI_ENABLED"]:
        return OllamaLLMProvider(
            base_url=config["OLLAMA_BASE_URL"],
            model=config["AI_DEFAULT_MODEL"],
            timeout_seconds=float(config["OLLAMA_TIMEOUT_SECONDS"]),
        )
    return DisabledLLMProvider()
