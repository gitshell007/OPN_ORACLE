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
    provider: str | None = None
    model: str | None = None
    fallback_used: bool = False


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
        body = {
            "task_key": request.agent,
            "input": {
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"{request.system_prompt}\n\n"
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
        try:
            response = httpx.post(
                urljoin(self.base_url, "api/v1/ai/run"),
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as error:
            raise AIUnavailable("Signal no esta disponible para ejecutar IA.") from error
        result_payload = payload.get("result")
        if not isinstance(result_payload, dict):
            raise AIUnavailable("Signal devolvio una respuesta IA sin JSON estructurado.")
        message = result_payload.get("message")
        output_payload = message.get("content") if isinstance(message, dict) else None
        output_payload = output_payload or result_payload.get("response")
        if not isinstance(output_payload, str):
            raise AIUnavailable("Signal devolvio una respuesta IA sin JSON estructurado.")
        usage = payload.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
        return LLMResult(
            output=schema.model_validate_json(output_payload),
            input_tokens=_non_negative_int(usage.get("input_tokens") or usage.get("prompt_tokens")),
            output_tokens=_non_negative_int(
                usage.get("output_tokens") or usage.get("completion_tokens")
            ),
            cost_micros=_non_negative_int(usage.get("cost_micros") or payload.get("cost_micros")),
            latency_ms=_non_negative_int(payload.get("latency_ms")) or elapsed_ms,
            provider=str(payload.get("provider") or payload.get("actual_provider") or "signal"),
            model=str(payload.get("model") or payload.get("actual_model") or request.model),
            fallback_used=bool(payload.get("fallback_used", False)),
        )

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
