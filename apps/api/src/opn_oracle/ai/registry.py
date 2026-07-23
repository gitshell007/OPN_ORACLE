"""Immutable prompt registry loaded from package resources."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel

from opn_oracle.ai.schemas import AGENT_SCHEMAS


@dataclass(frozen=True, slots=True)
class PromptDefinition:
    name: str
    version: str
    purpose: str
    input_contract: tuple[str, ...]
    output_schema_name: str
    classification: str
    model: str
    temperature: float
    max_output_tokens: int
    text: str
    sha256: bytes
    schema: type[BaseModel]
    changelog: str
    requires_evidence_review: bool
    evidence_review_failure_policy: EvidenceReviewFailurePolicy


EvidenceReviewFailurePolicy = Literal["not_required", "reject_output", "strip_claims"]


PURPOSES = {
    "intake": "Estructurar un expediente sin convertir hipótesis en hechos.",
    "signal_triage": "Evaluar una señal dentro de un expediente.",
    "entity_resolution": "Proponer resolución de entidad sin merges temerarios.",
    "opportunity": "Analizar una oportunidad candidata.",
    "risk": "Analizar un riesgo candidato sin dramatización.",
    "actor_partnership": "Priorizar un actor sin perfilado sensible.",
    "meeting_briefing": "Preparar una reunión con hechos e hipótesis separados.",
    "report_writer": "Redactar un informe trazable.",
    "competitive_procurement_intelligence": (
        "Interpretar agregados de contratación calculados por Oracle sin rehacer aritmética."
    ),
    "entity_dossier_intelligence": (
        "Interpretar la ficha agregada de una entidad sin convertir límites de fuente en certeza."
    ),
    "memory_curator": "Actualizar memoria viva sin borrar historia.",
    "evidence_reviewer": "Revisar groundedness y seguridad de un output.",
    "weekly_change": "Resumir cambios estratégicos del periodo.",
    "dossier_situation_summary": "Sintetizar la situación actual trazable de un expediente.",
    "dossier_completion_wizard": (
        "Diagnosticar la completitud de un expediente y proponer preguntas y acciones ejecutables."
    ),
    "tender_search_wizard": (
        "Proponer un plan de búsqueda de licitaciones revisable sin ejecutar ni aceptar búsquedas."
    ),
}

INPUT_CONTRACTS = {
    "intake": ("tenant_id", "dossier_id", "source_text", "allowed_evidence_ids"),
    "signal_triage": ("tenant_id", "dossier_id", "signal", "allowed_evidence_ids"),
    "entity_resolution": (
        "tenant_id",
        "dossier_id",
        "entity",
        "candidates",
        "allowed_evidence_ids",
    ),
    "opportunity": ("tenant_id", "dossier_id", "candidate", "allowed_evidence_ids"),
    "risk": ("tenant_id", "dossier_id", "candidate", "allowed_evidence_ids"),
    "actor_partnership": ("tenant_id", "dossier_id", "actor", "allowed_evidence_ids"),
    "meeting_briefing": ("tenant_id", "dossier_id", "meeting", "allowed_evidence_ids"),
    "report_writer": ("tenant_id", "dossier_id", "report_scope", "allowed_evidence_ids"),
    "competitive_procurement_intelligence": (
        "tenant_id",
        "dossier_id",
        "computed_analysis",
        "allowed_evidence_ids",
    ),
    "entity_dossier_intelligence": (
        "tenant_id",
        "entity",
        "entity_dossier",
        "computed_metrics",
        "source_limits",
        "allowed_evidence_ids",
    ),
    "memory_curator": ("tenant_id", "dossier_id", "baseline", "changes", "allowed_evidence_ids"),
    "evidence_reviewer": ("tenant_id", "dossier_id", "candidate_output", "allowed_evidence_ids"),
    "weekly_change": (
        "tenant_id",
        "dossier_id",
        "period_start",
        "period_end",
        "allowed_evidence_ids",
    ),
    "dossier_situation_summary": (
        "tenant_id",
        "dossier_id",
        "snapshot",
        "allowed_evidence_ids",
    ),
    "dossier_completion_wizard": (
        "tenant_id",
        "dossier_id",
        "completion_snapshot",
        "previous_rounds",
        "answers",
        "allowed_evidence_ids",
    ),
    "tender_search_wizard": (
        "tenant_id",
        "mode",
        "description",
        "comparable",
        "comparable_profile",
        "accepted_plan",
        "feedback_digest",
        "allowed_evidence_ids",
    ),
}

# Qué agentes pasan por `evidence_reviewer` tras generar. Se indexa DIRECTAMENTE (sin
# `.get`) a propósito: un agente nuevo que olvide declararse revienta al construir el
# registro en vez de saltarse el control en silencio.
#
# Las tres excepciones están razonadas y no son un descuido:
#   - `dossier_completion_wizard` (D-039): afirma AUSENCIAS ("faltan actores"), y no se
#     puede citar evidencia de lo que no existe. Su control es determinista, contra los
#     recuentos reales del expediente.
#   - `entity_dossier_intelligence` (D-040): el revisor solo recibe los claims y los
#     extractos citados, pero el informe se redacta desde un corpus mucho más rico
#     (grafo, noticias, patentes, CNMV, contratación). Juzgaba con menos contexto que el
#     escritor y rechazaba sistemáticamente afirmaciones que SÍ están respaldadas por el
#     corpus. Su control es `validate_evidence` sobre la allowlist de citas.
#   - `tender_search_wizard`: propone filtros candidatos, no afirmaciones sobre hechos.
#     Oracle valida de forma determinista CPV y términos y ninguna propuesta se acepta,
#     ejecuta o guarda sin una acción humana posterior.
EVIDENCE_REVIEW_REQUIRED = {
    "intake": True,
    "signal_triage": True,
    "entity_resolution": True,
    "opportunity": True,
    "risk": True,
    "actor_partnership": True,
    "meeting_briefing": True,
    "report_writer": True,
    "competitive_procurement_intelligence": True,
    "entity_dossier_intelligence": False,
    "memory_curator": True,
    "evidence_reviewer": False,
    "weekly_change": True,
    "dossier_situation_summary": True,
    "dossier_completion_wizard": False,
    "tender_search_wizard": False,
}

# Respuesta al veredicto `fail`, declarada por agente y consultada directamente. Los informes
# publicables conservan rechazo duro. Solo el resumen nocturno puede retirar quirúrgicamente
# claims objetados y continuar, porque mantiene visible el recorte y se regenera automáticamente.
EVIDENCE_REVIEW_FAILURE_POLICY: dict[str, EvidenceReviewFailurePolicy] = {
    "intake": "reject_output",
    "signal_triage": "reject_output",
    "entity_resolution": "reject_output",
    "opportunity": "reject_output",
    "risk": "reject_output",
    "actor_partnership": "reject_output",
    "meeting_briefing": "reject_output",
    "report_writer": "reject_output",
    "competitive_procurement_intelligence": "reject_output",
    "entity_dossier_intelligence": "not_required",
    "memory_curator": "reject_output",
    "evidence_reviewer": "not_required",
    "weekly_change": "reject_output",
    "dossier_situation_summary": "strip_claims",
    "dossier_completion_wizard": "not_required",
    "tender_search_wizard": "not_required",
}

PROMPT_VERSIONS = {
    name: (
        ("v1", "v2", "v3", "v4", "v5")
        if name == "dossier_situation_summary"
        else ("v1", "v2", "v3", "v4", "v5")
        if name == "report_writer"
        else ("v1", "v2", "v3")
        if name == "entity_dossier_intelligence"
        else ("v1", "v2")
        if name
        in {
            "meeting_briefing",
            "weekly_change",
            "competitive_procurement_intelligence",
            "tender_search_wizard",
        }
        else ("v1",)
    )
    for name in AGENT_SCHEMAS
}


def _max_output_tokens(name: str, version: str) -> int:
    if name == "report_writer" and version in {"v2", "v3", "v4", "v5"}:
        return 6500
    if name == "meeting_briefing" and version == "v2":
        return 3500
    if name == "weekly_change" and version == "v2":
        return 4200
    if name == "competitive_procurement_intelligence":
        return 16000 if version == "v2" else 5000
    if name == "entity_dossier_intelligence":
        # Sincronizado con la config gobernada de esta task en Signal (16000). El informe
        # de entidad cita evidencia BORME/noticias, así que su salida es larga: con 5000 y
        # con 8000 se truncaba a media palabra y ReportOutput fallaba con "Invalid JSON: EOF".
        # Signal pisa este valor para tareas gobernadas, pero mandarlo correcto evita que el
        # límite real dependa de ese parche.
        return 16000
    if name == "dossier_completion_wizard":
        return 4500
    if name == "tender_search_wizard":
        return 3000
    if name != "dossier_situation_summary":
        return 2000
    return {"v1": 3000, "v2": 2000, "v3": 1600, "v4": 1900, "v5": 2600}[version]


class PromptRegistry:
    def __init__(self, model: str = "mock-oracle-v1") -> None:
        root = files("opn_oracle.ai.prompts")
        self.system = root.joinpath("common/system_v1.md").read_text(encoding="utf-8")
        self._items: dict[tuple[str, str], PromptDefinition] = {}
        for name, schema in AGENT_SCHEMAS.items():
            for version in PROMPT_VERSIONS[name]:
                key = (name, version)
                if key in self._items:
                    raise ValueError(f"Prompt duplicado: {name}/{version}")
                text = root.joinpath(f"{name}/{version}.md").read_text(encoding="utf-8")
                for section in ("## Tarea", "## Reglas", "## Contrato de salida"):
                    if section not in text:
                        raise ValueError(f"Prompt incompleto {name}/{version}: falta {section}")
                combined = self.system + "\n\n" + text
                if name == "entity_dossier_intelligence":
                    changelog = {
                        "v1": "v1: contrato inicial derivado del runtime canónico de Fase 09.",
                        "v2": ("v2: informe ejecutivo redactado con contratación pública."),
                        "v3": (
                            "v3: menciones web atribuibles sustituyen la falsa cobertura "
                            "de noticias."
                        ),
                    }[version]
                elif name == "competitive_procurement_intelligence":
                    changelog = {
                        "v1": "v1: contrato inicial de inteligencia competitiva PLACSP.",
                        "v2": (
                            "v2: informe ejecutivo analítico con materialidad y límites al final."
                        ),
                    }[version]
                elif name == "tender_search_wizard":
                    changelog = {
                        "v1": "v1: propuesta inicial revisable con grounding comparable medido.",
                        "v2": (
                            "v2: añade replanificación explícita desde plan aceptado y "
                            "digest determinista de feedback."
                        ),
                    }[version]
                else:
                    changelog = (
                        {
                            "v1": "v1: contrato inicial derivado del runtime canónico de Fase 09.",
                            "v2": "v2: salida compacta y completa para modelos locales.",
                            "v3": "v3: parte ejecutivo acotado para inferencia local fiable.",
                            "v4": "v4: cierre JSON breve con margen de terminación medido.",
                            "v5": (
                                "v5: presupuesto completo para el contrato ejecutivo de 18 bloques."
                            ),
                        }[version]
                        if name == "dossier_situation_summary"
                        else (
                            {
                                "v1": (
                                    "v1: contrato inicial derivado del runtime canónico de Fase 09."
                                ),
                                "v2": (
                                    "v2: contrato compacto y presupuesto ajustado para "
                                    "Signal/Ollama local."
                                ),
                                "v3": (
                                    "v3: párrafos factuales con evidencia obligatoria y "
                                    "contrato compacto."
                                ),
                                "v4": (
                                    "v4: las citas en prosa usan índices legibles; los UUID "
                                    "quedan fuera de la salida de negocio."
                                ),
                                "v5": (
                                    "v5: informe ejecutivo con materialidad y campos de cierre."
                                ),
                            }[version]
                        )
                    )
                item = PromptDefinition(
                    name=name,
                    version=version,
                    purpose=PURPOSES[name],
                    input_contract=INPUT_CONTRACTS[name],
                    output_schema_name=schema.__name__,
                    classification="internal",
                    model=model,
                    temperature=0.0,
                    max_output_tokens=_max_output_tokens(name, version),
                    text=combined,
                    sha256=hashlib.sha256(combined.encode()).digest(),
                    schema=schema,
                    changelog=changelog,
                    requires_evidence_review=EVIDENCE_REVIEW_REQUIRED[name],
                    evidence_review_failure_policy=EVIDENCE_REVIEW_FAILURE_POLICY[name],
                )
                self._items[key] = item

    def get(self, name: str, version: str | None = None) -> PromptDefinition:
        selected_version = version or PROMPT_VERSIONS.get(name, ("v1",))[-1]
        try:
            return self._items[(name, selected_version)]
        except KeyError as error:
            raise KeyError(f"Prompt no registrado: {name}/{selected_version}") from error

    def all(self) -> tuple[PromptDefinition, ...]:
        return tuple(self._items.values())
