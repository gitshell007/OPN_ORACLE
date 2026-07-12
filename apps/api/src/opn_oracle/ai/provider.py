"""Provider boundary for local, structured and auditable AI execution."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel, ValidationError

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


def _strip_unauthorized_evidence_blocks(
    output: T, allowed_values: list[str]
) -> T:
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
    return type(output).model_validate(payload)


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
                output = schema.model_validate_json(_signal_output(payload))
                _validate_allowed_evidence(output, allowed_evidence_ids)
            except ValueError:
                try:
                    output = _strip_unauthorized_evidence_blocks(
                        output, allowed_evidence_ids
                    )
                    _validate_allowed_evidence(output, allowed_evidence_ids)
                except (UnboundLocalError, ValueError):
                    if allowed_evidence_ids:
                        raise
                    output = _safe_empty_evidence_summary(request, schema)
                    safe_fallback_used = True
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
    message = result_payload.get("message")
    output_payload = message.get("content") if isinstance(message, dict) else None
    output_payload = output_payload or result_payload.get("response")
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
