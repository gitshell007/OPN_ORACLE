"""Immutable prompt registry loaded from package resources."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib.resources import files

from opn_oracle.ai.schemas import AGENT_SCHEMAS, AgentOutput


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
    schema: type[AgentOutput]
    changelog: str


PURPOSES = {
    "intake": "Estructurar un expediente sin convertir hipótesis en hechos.",
    "signal_triage": "Evaluar una señal dentro de un expediente.",
    "entity_resolution": "Proponer resolución de entidad sin merges temerarios.",
    "opportunity": "Analizar una oportunidad candidata.",
    "risk": "Analizar un riesgo candidato sin dramatización.",
    "actor_partnership": "Priorizar un actor sin perfilado sensible.",
    "meeting_briefing": "Preparar una reunión con hechos e hipótesis separados.",
    "report_writer": "Redactar un informe trazable.",
    "memory_curator": "Actualizar memoria viva sin borrar historia.",
    "evidence_reviewer": "Revisar groundedness y seguridad de un output.",
    "weekly_change": "Resumir cambios estratégicos del periodo.",
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
    "memory_curator": ("tenant_id", "dossier_id", "baseline", "changes", "allowed_evidence_ids"),
    "evidence_reviewer": ("tenant_id", "dossier_id", "candidate_output", "allowed_evidence_ids"),
    "weekly_change": (
        "tenant_id",
        "dossier_id",
        "period_start",
        "period_end",
        "allowed_evidence_ids",
    ),
}


class PromptRegistry:
    def __init__(self, model: str = "mock-oracle-v1") -> None:
        root = files("opn_oracle.ai.prompts")
        self.system = root.joinpath("common/system_v1.md").read_text(encoding="utf-8")
        self._items: dict[tuple[str, str], PromptDefinition] = {}
        for name, schema in AGENT_SCHEMAS.items():
            key = (name, "v1")
            if key in self._items:
                raise ValueError(f"Prompt duplicado: {name}/v1")
            text = root.joinpath(f"{name}/v1.md").read_text(encoding="utf-8")
            for section in ("## Tarea", "## Reglas", "## Contrato de salida"):
                if section not in text:
                    raise ValueError(f"Prompt incompleto {name}/v1: falta {section}")
            combined = self.system + "\n\n" + text
            item = PromptDefinition(
                name=name,
                version="v1",
                purpose=PURPOSES[name],
                input_contract=INPUT_CONTRACTS[name],
                output_schema_name=schema.__name__,
                classification="internal",
                model=model,
                temperature=0.0,
                max_output_tokens=2000,
                text=combined,
                sha256=hashlib.sha256(combined.encode()).digest(),
                schema=schema,
                changelog="v1: contrato inicial derivado del runtime canónico de Fase 09.",
            )
            self._items[key] = item

    def get(self, name: str, version: str = "v1") -> PromptDefinition:
        try:
            return self._items[(name, version)]
        except KeyError as error:
            raise KeyError(f"Prompt no registrado: {name}/{version}") from error

    def all(self) -> tuple[PromptDefinition, ...]:
        return tuple(self._items.values())
