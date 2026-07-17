"""Immutable loader for the supported report templates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import resources
from typing import Any


@dataclass(frozen=True, slots=True)
class ReportTemplate:
    key: str
    version: str
    label: str
    report_type: str
    input_contract: dict[str, Any]
    sections: tuple[str, ...]
    evidence_policy: str
    output_schema: str
    permissions: dict[str, str]
    formats: tuple[str, ...]
    changelog: tuple[str, ...]
    sha256: bytes

    def public_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "version": self.version,
            "label": self.label,
            "report_type": self.report_type,
            "input_contract": self.input_contract,
            "sections": list(self.sections),
            "evidence_policy": self.evidence_policy,
            "output_schema": self.output_schema,
            "permissions": self.permissions,
            "formats": list(self.formats),
            "changelog": list(self.changelog),
            "sha256": self.sha256.hex(),
        }


EXPECTED_TEMPLATES = frozenset(
    {
        "executive_dossier",
        "opportunity",
        "risk",
        "tender",
        "meeting_briefing",
        "weekly_change",
        "actors",
        "action_plan",
        "competitive_procurement",
        "entity_intelligence",
    }
)


class ReportTemplateRegistry:
    def __init__(self) -> None:
        self._templates = self._load()

    @staticmethod
    def _load() -> dict[str, ReportTemplate]:
        package = resources.files("opn_oracle.reporting.templates")
        loaded: dict[str, ReportTemplate] = {}
        for resource in sorted(package.iterdir(), key=lambda item: item.name):
            if not resource.name.endswith(".json"):
                continue
            raw = resource.read_bytes()
            payload = json.loads(raw)
            key, version = str(payload["key"]), str(payload["version"])
            if key in loaded or resource.name != f"{key}.{version}.json":
                raise RuntimeError("Registro de templates de informe inválido.")
            if payload.get("output_schema") != "ReportOutput/v1":
                raise RuntimeError("Schema de template de informe no permitido.")
            formats = tuple(str(value) for value in payload.get("formats", []))
            if not formats or not set(formats).issubset({"html", "pdf", "json"}):
                raise RuntimeError("Formatos de template de informe inválidos.")
            loaded[key] = ReportTemplate(
                key=key,
                version=version,
                label=str(payload["label"]),
                report_type=str(payload["report_type"]),
                input_contract=dict(payload["input_contract"]),
                sections=tuple(str(value) for value in payload["sections"]),
                evidence_policy=str(payload["evidence_policy"]),
                output_schema=str(payload["output_schema"]),
                permissions={str(k): str(v) for k, v in payload["permissions"].items()},
                formats=formats,
                changelog=tuple(str(value) for value in payload["changelog"]),
                sha256=hashlib.sha256(raw).digest(),
            )
        if loaded.keys() != EXPECTED_TEMPLATES:
            raise RuntimeError("El registro de templates de informe v1 está incompleto.")
        return loaded

    def get(self, key: str, version: str = "v1") -> ReportTemplate:
        template = self._templates.get(key)
        if template is None or template.version != version:
            raise KeyError("Template de informe no disponible.")
        return template

    def list(self) -> tuple[ReportTemplate, ...]:
        return tuple(self._templates[key] for key in sorted(self._templates))
