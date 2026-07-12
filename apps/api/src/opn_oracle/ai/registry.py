"""Immutable prompt registry loaded from package resources."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib.resources import files

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
    "dossier_situation_summary": "Sintetizar la situación actual trazable de un expediente.",
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
    "dossier_situation_summary": (
        "tenant_id",
        "dossier_id",
        "snapshot",
        "allowed_evidence_ids",
    ),
}

PROMPT_VERSIONS = {
    name: (("v1", "v2", "v3", "v4", "v5") if name == "dossier_situation_summary" else ("v1",))
    for name in AGENT_SCHEMAS
}


def _max_output_tokens(name: str, version: str) -> int:
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
                changelog = (
                    {
                        "v1": "v1: contrato inicial derivado del runtime canónico de Fase 09.",
                        "v2": "v2: salida compacta y completa para modelos locales.",
                        "v3": "v3: parte ejecutivo acotado para inferencia local fiable.",
                        "v4": "v4: cierre JSON breve con margen de terminación medido.",
                        "v5": "v5: presupuesto completo para el contrato ejecutivo de 18 bloques.",
                    }[version]
                    if name == "dossier_situation_summary"
                    else "v1: contrato inicial derivado del runtime canónico de Fase 09."
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
