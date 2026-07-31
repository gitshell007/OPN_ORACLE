#!/usr/bin/env python3
"""Validate the living roadmap and generate its standalone HTML dashboard.

The JSON roadmap is authoritative. The HTML is deliberately generated without a
network dependency so it can be opened directly from the filesystem.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


STATUS_LABELS = {
    "idea": "Idea",
    "proposed": "Propuesto",
    "needs_definition": "Necesita definición",
    "approved": "Aprobado",
    "ready": "Listo",
    "in_progress": "En desarrollo",
    "blocked": "Bloqueado",
    "implemented": "Implementado",
    "under_review": "En revisión",
    "validated": "Validado",
    "deployed": "Desplegado",
    "rejected": "Descartado",
    "deferred": "Diferido",
}
STATUS_WEIGHT = {
    "idea": 0,
    "proposed": 5,
    "needs_definition": 10,
    "approved": 20,
    "ready": 25,
    "in_progress": 50,
    "blocked": 20,
    "implemented": 75,
    "under_review": 80,
    "validated": 90,
    "deployed": 100,
    "rejected": 0,
    "deferred": 0,
}
PRIORITY_WEIGHT = {"P0": 4, "P1": 3, "P2": 2, "P3": 1}
FINISHED_STATES = {"implemented", "under_review", "validated", "deployed"}

REQUIRED_PROJECT_FIELDS = {
    "id",
    "name",
    "description",
    "version",
    "created_at",
    "updated_at",
    "progress_percent",
    "business_objectives",
    "product_principles",
    "current_scope",
    "out_of_scope",
}
REQUIRED_MODULE_FIELDS = {
    "id",
    "name",
    "description",
    "status",
    "progress_percent",
    "dependencies",
    "risks",
    "feature_ids",
}
REQUIRED_FEATURE_FIELDS = {
    "id",
    "module_id",
    "title",
    "description",
    "problem",
    "business_objective",
    "user_value",
    "user_types",
    "status",
    "priority",
    "progress_percent",
    "complexity",
    "technical_risk",
    "dependencies",
    "blockers",
    "acceptance_criteria",
    "functional_requirements",
    "non_functional_requirements",
    "security_requirements",
    "multi_tenant_requirements",
    "audit_requirements",
    "impact",
    "related_files",
    "related_migrations",
    "related_tests",
    "implementation_evidence",
    "related_decisions",
    "comments",
    "next_action",
    "created_at",
    "updated_at",
    "completed_at",
    "history",
}
IMPACT_KEYS = {"frontend", "backend", "database", "celery", "redis", "signal", "reports", "permissions"}


class ValidationFailure(Exception):
    """Raised when the roadmap cannot safely produce a dashboard."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationFailure([f"No existe el roadmap: {path}"]) from exc
    except json.JSONDecodeError as exc:
        raise ValidationFailure([f"JSON inválido en {path}:{exc.lineno}:{exc.colno}: {exc.msg}"]) from exc
    if not isinstance(value, dict):
        raise ValidationFailure(["El roadmap debe tener un objeto JSON en la raíz."])
    return value


def markdown_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return set(re.findall(r"^##\s+(ORC-ADR-\d+)\b", path.read_text(encoding="utf-8"), re.MULTILINE))


def local_reference(root: Path, reference: str) -> Path | None:
    if reference.startswith("command:") or reference.startswith("external:"):
        return None
    if re.match(r"^https?://", reference):
        return None
    return root / reference


def validate(data: dict[str, Any], root: Path, decisions_path: Path, output_path: Path | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    project = data.get("project")
    if not isinstance(project, dict):
        errors.append("project debe ser un objeto.")
        project = {}
    missing = sorted(REQUIRED_PROJECT_FIELDS - project.keys())
    if missing:
        errors.append(f"project no contiene: {', '.join(missing)}")
    states = data.get("allowed_states")
    if not isinstance(states, list) or set(states) != set(STATUS_LABELS):
        errors.append("allowed_states debe contener exactamente los 13 estados normalizados.")
    modules = data.get("modules")
    features = data.get("features")
    edges = data.get("dependencies")
    if not isinstance(modules, list) or not modules:
        errors.append("modules debe ser una lista no vacía.")
        modules = []
    if not isinstance(features, list) or not features:
        errors.append("features debe ser una lista no vacía.")
        features = []
    if not isinstance(edges, list):
        errors.append("dependencies debe ser una lista.")
        edges = []

    all_ids: dict[str, str] = {}
    module_by_id: dict[str, dict[str, Any]] = {}
    feature_by_id: dict[str, dict[str, Any]] = {}
    for collection_name, collection in (("module", modules), ("feature", features), ("edge", edges)):
        for item in collection:
            if not isinstance(item, dict):
                errors.append(f"Cada elemento de {collection_name}s debe ser un objeto.")
                continue
            identifier = item.get("id")
            if not isinstance(identifier, str) or not identifier.strip():
                errors.append(f"{collection_name} sin id estable: {item!r}")
                continue
            if identifier in all_ids:
                errors.append(f"ID duplicado {identifier} ({all_ids[identifier]} y {collection_name}).")
            all_ids[identifier] = collection_name
            if collection_name == "module":
                module_by_id[identifier] = item
            elif collection_name == "feature":
                feature_by_id[identifier] = item

    for module in modules:
        if not isinstance(module, dict):
            continue
        identifier = module.get("id", "<sin id>")
        missing = sorted(REQUIRED_MODULE_FIELDS - module.keys())
        if missing:
            errors.append(f"Módulo {identifier} no contiene: {', '.join(missing)}")
        status = module.get("status")
        if status not in STATUS_LABELS:
            errors.append(f"Módulo {identifier} tiene estado inválido: {status!r}")
        for feature_id in module.get("feature_ids", []):
            if feature_id not in feature_by_id:
                errors.append(f"Módulo {identifier} referencia feature inexistente {feature_id}.")

    decision_ids = markdown_ids(decisions_path)
    for feature in features:
        if not isinstance(feature, dict):
            continue
        identifier = feature.get("id", "<sin id>")
        missing = sorted(REQUIRED_FEATURE_FIELDS - feature.keys())
        if missing:
            errors.append(f"Feature {identifier} no contiene: {', '.join(missing)}")
        status = feature.get("status")
        if status not in STATUS_LABELS:
            errors.append(f"Feature {identifier} tiene estado inválido: {status!r}")
        module_id = feature.get("module_id")
        if module_id not in module_by_id:
            errors.append(f"Feature {identifier} referencia módulo inexistente {module_id!r}.")
        if feature.get("priority") not in {"P0", "P1", "P2", "P3"}:
            errors.append(f"Feature {identifier} tiene prioridad inválida: {feature.get('priority')!r}")
        if feature.get("complexity") not in {"XS", "S", "M", "L", "XL"}:
            errors.append(f"Feature {identifier} tiene complejidad inválida: {feature.get('complexity')!r}")
        progress = feature.get("progress_percent")
        if not isinstance(progress, (int, float)) or not 0 <= progress <= 100:
            errors.append(f"Feature {identifier} tiene progress_percent fuera de 0..100.")
        impact = feature.get("impact")
        if not isinstance(impact, dict) or set(impact) != IMPACT_KEYS:
            errors.append(f"Feature {identifier} debe declarar exactamente los impactos {sorted(IMPACT_KEYS)}.")
        criteria = feature.get("acceptance_criteria")
        if not isinstance(criteria, list) or not criteria:
            errors.append(f"Feature {identifier} no tiene criterios de aceptación.")
        for dependency in feature.get("dependencies", []):
            if dependency not in all_ids:
                errors.append(f"Feature {identifier} referencia dependencia inexistente {dependency}.")
        for decision in feature.get("related_decisions", []):
            if decision not in decision_ids:
                errors.append(f"Feature {identifier} referencia decisión inexistente {decision}.")
        if status in FINISHED_STATES and not feature.get("implementation_evidence"):
            errors.append(f"Feature {identifier} está {status} sin evidencias de implementación.")
        if status == "validated":
            tests = feature.get("related_tests", [])
            has_test_evidence = any(item.get("type") == "test" for item in feature.get("implementation_evidence", []) if isinstance(item, dict))
            if not tests or not has_test_evidence:
                errors.append(f"Feature {identifier} está validated sin pruebas/evidencia de test.")
        if status == "deployed":
            has_deploy = any(item.get("type") == "deployment" for item in feature.get("implementation_evidence", []) if isinstance(item, dict))
            if not has_deploy:
                errors.append(f"Feature {identifier} está deployed sin evidencia de deployment.")
        for field in ("related_files", "related_migrations", "related_tests"):
            for reference in feature.get(field, []):
                if not isinstance(reference, str):
                    errors.append(f"Feature {identifier} tiene referencia no textual en {field}.")
                    continue
                path = local_reference(root, reference)
                if path is not None and path.resolve() != (output_path.resolve() if output_path else None) and not path.exists():
                    errors.append(f"Feature {identifier} referencia {field} inexistente: {reference}")
        for evidence in feature.get("implementation_evidence", []):
            if not isinstance(evidence, dict) or not evidence.get("type") or not evidence.get("path"):
                errors.append(f"Feature {identifier} contiene evidencia incompleta.")
                continue
            path = local_reference(root, str(evidence["path"]))
            if path is not None and path.resolve() != (output_path.resolve() if output_path else None) and not path.exists():
                errors.append(f"Feature {identifier} contiene evidencia inexistente: {evidence['path']}")

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source, target = edge.get("from"), edge.get("to")
        if source not in all_ids or target not in all_ids:
            errors.append(f"Dependencia {edge.get('id', '<sin id>')} apunta a {source!r} -> {target!r} inexistente.")
        if source == target:
            errors.append(f"Dependencia {edge.get('id', '<sin id>')} no puede apuntarse a sí misma.")

    listed_features = {feature_id for module in modules for feature_id in module.get("feature_ids", []) if isinstance(module, dict)}
    unlisted_features = sorted(set(feature_by_id) - listed_features)
    if unlisted_features:
        errors.append(f"Features no asignadas a un módulo: {', '.join(unlisted_features)}")
    module_progress = {module_id: round(sum(feature_by_id[feature_id].get("progress_percent", 0) for feature_id in module.get("feature_ids", [])) / max(len(module.get("feature_ids", [])), 1)) for module_id, module in module_by_id.items()}
    project_progress = round(sum(item.get("progress_percent", 0) for item in features) / max(len(features), 1))
    stated_progress = project.get("progress_percent")
    if isinstance(stated_progress, (int, float)) and abs(float(stated_progress) - project_progress) > 12:
        warnings.append(f"project.progress_percent={stated_progress} difiere del cálculo por features={project_progress}; el dashboard usará el cálculo.")
    for module_id, calculated in module_progress.items():
        stated = module_by_id[module_id].get("progress_percent")
        if isinstance(stated, (int, float)) and abs(float(stated) - calculated) > 18:
            warnings.append(f"{module_id}.progress_percent={stated} difiere del cálculo={calculated}; el dashboard usará el cálculo.")
    return errors, warnings


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def status_badge(status: str) -> str:
    return f'<span class="status status-{esc(status)}">{esc(STATUS_LABELS.get(status, status))}</span>'


def priority_badge(priority: str) -> str:
    return f'<span class="priority priority-{esc(priority)}">{esc(priority)}</span>'


def list_html(values: list[Any], empty: str = "Sin registrar") -> str:
    if not values:
        return f'<span class="muted">{esc(empty)}</span>'
    return "<ul>" + "".join(f"<li>{esc(value)}</li>" for value in values) + "</ul>"


def markdown_sections(text: str) -> list[tuple[str, str, str]]:
    matches = list(re.finditer(r"^##\s+(.+)$", text, re.MULTILINE))
    result: list[tuple[str, str, str]] = []
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : body_end].strip()
        identifier = title.split(" — ", 1)[0].strip()
        result.append((identifier, title, body))
    return result


def markdown_as_pre(text: str) -> str:
    return f'<div class="doc-sheet"><pre>{esc(text.strip())}</pre></div>'


def decision_cards(text: str) -> str:
    cards: list[str] = []
    for identifier, title, body in markdown_sections(text):
        fields: list[str] = []
        for line in body.splitlines():
            match = re.match(r"^-\s+([^:]+):\s*(.*)$", line)
            if match:
                fields.append(f"<dt>{esc(match.group(1))}</dt><dd>{esc(match.group(2))}</dd>")
        cards.append(f'<article class="decision-card" id="{esc(identifier)}"><div class="eyebrow">{esc(identifier)}</div><h3>{esc(title.split(" — ", 1)[-1])}</h3><dl>{"".join(fields)}</dl></article>')
    return "".join(cards) or '<p class="muted">No hay decisiones registradas.</p>'


def progress_cards(text: str) -> str:
    cards: list[str] = []
    for identifier, title, body in markdown_sections(text):
        lines = [line[2:].strip() for line in body.splitlines() if line.startswith("- ")]
        cards.append(f'<article class="progress-card" id="progress-{esc(identifier)}"><div class="eyebrow">{esc(identifier)}</div><h3>{esc(title.split(" — ", 1)[-1])}</h3>{list_html(lines)}</article>')
    return "".join(cards) or '<p class="muted">No hay historial registrado.</p>'


def graph_svg(data: dict[str, Any]) -> str:
    modules = data["modules"]
    features = data["features"]
    feature_by_id = {item["id"]: item for item in features}
    positions: dict[str, tuple[int, int, int, int]] = {}
    width = 1500
    lane_height = 146
    left = 246
    node_width = 180
    node_height = 78
    for lane, module in enumerate(modules):
        y = 24 + lane * lane_height
        positions[module["id"]] = (22, y + 18, 204, 46)
        for index, feature_id in enumerate(module["feature_ids"]):
            x = left + index * 202
            positions[feature_id] = (x, y, node_width, node_height)
    height = 48 + len(modules) * lane_height
    lines: list[str] = []
    for edge in data["dependencies"]:
        source, target = positions.get(edge["from"]), positions.get(edge["to"])
        if source is None or target is None:
            continue
        x1, y1, w1, h1 = source
        x2, y2, _, _ = target
        lines.append(f'<path class="edge edge-{esc(edge["kind"])}" d="M{x1 + w1},{y1 + h1 / 2} C{x1 + w1 + 36},{y1 + h1 / 2} {x2 - 36},{y2 + node_height / 2} {x2},{y2 + node_height / 2}" />')
    nodes: list[str] = []
    for module in modules:
        x, y, w, h = positions[module["id"]]
        nodes.append(f'<a class="graph-module" href="#module-{esc(module["id"])}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12"/><text x="{x + 14}" y="{y + 21}">{esc(module["id"])}</text><text class="module-label" x="{x + 14}" y="{y + 39}">{esc(module["name"][:25])}</text></a>')
    for feature in features:
        x, y, w, h = positions[feature["id"]]
        title = feature["title"][:29]
        nodes.append(f'<a class="graph-node status-node-{esc(feature["status"])}" href="#feature-{esc(feature["id"])}" onclick="selectFeature(\'{esc(feature["id"])}\'); return false;"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12"/><text class="node-id" x="{x + 12}" y="{y + 19}">{esc(feature["id"])}</text><text class="node-title" x="{x + 12}" y="{y + 42}">{esc(title)}</text><text class="node-status" x="{x + 12}" y="{y + 62}">{esc(STATUS_LABELS[feature["status"]])}</text></a>')
    return f'<div class="graph-scroll"><svg class="roadmap-graph" viewBox="0 0 {width} {height}" role="img" aria-label="Mapa de módulos, funcionalidades y dependencias">{"".join(lines)}{"".join(nodes)}</svg></div>'


def feature_card(feature: dict[str, Any], module_name: str) -> str:
    evidence = feature.get("implementation_evidence", [])
    evidence_html = "<ul>" + "".join(f'<li><span class="evidence-type">{esc(item.get("type", "evidence"))}</span> <code>{esc(item.get("path", ""))}</code> — {esc(item.get("claim", ""))}</li>' for item in evidence) + "</ul>" if evidence else '<span class="muted">Sin evidencias.</span>'
    criteria_html = "<ul class=criteria>" + "".join(f'<li class="criterion-{esc(item.get("status", "unknown"))}"><span>{esc(item.get("status", "unknown"))}</span> {esc(item.get("text", ""))}</li>' for item in feature.get("acceptance_criteria", [])) + "</ul>"
    searchable = " ".join([feature["id"], feature["title"], feature["description"], feature["status"], feature["priority"], feature["complexity"], module_name, feature.get("next_action", "")]).lower()
    return f'''<article class="feature-card" id="feature-{esc(feature["id"])}" data-feature-id="{esc(feature["id"])}" data-status="{esc(feature["status"])}" data-priority="{esc(feature["priority"])}" data-complexity="{esc(feature["complexity"])}" data-module="{esc(feature["module_id"])}" data-blocked="{"true" if feature.get("blockers") else "false"}" data-has-tests="{"true" if feature.get("related_tests") else "false"}" data-has-criteria="{"true" if feature.get("acceptance_criteria") else "false"}" data-search="{esc(searchable)}">
      <div class="feature-head"><div><span class="eyebrow">{esc(feature["id"])} · {esc(module_name)}</span><h3>{esc(feature["title"])}</h3></div><div class="badge-stack">{status_badge(feature["status"])} {priority_badge(feature["priority"])}<span class="complexity">{esc(feature["complexity"])}</span></div></div>
      <p class="feature-description">{esc(feature["description"])}</p>
      <div class="feature-meta"><span>Avance <strong>{feature.get("progress_percent", 0)}%</strong></span><span>Riesgo <strong>{esc(feature.get("technical_risk", "—"))}</strong></span><span>Actualizado <strong>{esc(feature.get("updated_at", "—"))}</strong></span></div>
      <div class="progress-track"><span style="width:{max(0, min(100, feature.get("progress_percent", 0)))}%"></span></div>
      <div class="feature-grid"><div><h4>Criterios de aceptación</h4>{criteria_html}</div><div><h4>Evidencias</h4>{evidence_html}</div><div><h4>Próxima acción</h4><p>{esc(feature.get("next_action", "—"))}</p><h4>Dependencias</h4>{list_html(feature.get("dependencies", []))}</div></div>
      <details><summary>Requisitos, impacto y comentarios</summary><div class="detail-columns"><div><h4>Requisitos funcionales</h4>{list_html(feature.get("functional_requirements", []))}<h4>No funcionales</h4>{list_html(feature.get("non_functional_requirements", []))}<h4>Seguridad</h4>{list_html(feature.get("security_requirements", []))}</div><div><h4>Multi-tenant</h4>{list_html(feature.get("multi_tenant_requirements", []))}<h4>Auditoría</h4>{list_html(feature.get("audit_requirements", []))}<h4>Bloqueos</h4>{list_html(feature.get("blockers", []))}</div><div><h4>Impacto técnico</h4>{"".join(f"<p><strong>{esc(key)}:</strong> {esc(value)}</p>" for key, value in feature.get("impact", {}).items())}</div></div><p class="comment">{esc(feature.get("comments", ""))}</p></details>
    </article>'''


def checklist_html(data: dict[str, Any]) -> str:
    features = {item["id"]: item for item in data["features"]}
    modules = []
    for module in data["modules"]:
        cards = "".join(feature_card(features[item], module["name"]) for item in module["feature_ids"])
        modules.append(f'<details class="module-group" id="module-{esc(module["id"])}" open><summary><span><strong>{esc(module["id"])}</strong> {esc(module["name"])}</span><span class="module-summary">{len(module["feature_ids"])} features · {esc(module.get("readiness", ""))}</span></summary><div class="module-progress"><span style="width:{data["calculated_module_progress"][module["id"]]}%"></span></div><div class="module-features">{cards}</div></details>')
    return "".join(modules)


def summary_html(data: dict[str, Any]) -> str:
    features = data["features"]
    counts = Counter(feature["status"] for feature in features)
    critical = [feature for feature in features if feature["priority"] == "P0" and feature["status"] not in {"validated", "deployed"}]
    blocked = [feature for feature in features if feature["status"] == "blocked" or feature.get("blockers")]
    latest = sorted(features, key=lambda item: item.get("updated_at", ""), reverse=True)[:6]
    risk_items = [feature for feature in features if feature.get("technical_risk") == "high" or feature.get("blockers")]
    status_rows = "".join(f'<div class="status-row"><span>{esc(STATUS_LABELS[state])}</span><strong>{counts.get(state, 0)}</strong><span class="bar"><i style="width:{round(counts.get(state, 0) / max(len(features), 1) * 100)}%"></i></span></div>' for state in STATUS_LABELS if counts.get(state, 0))
    module_rows = "".join(f'<div class="module-row"><span>{esc(module["name"])}</span><span class="bar"><i style="width:{data["calculated_module_progress"][module["id"]]}%"></i></span><strong>{data["calculated_module_progress"][module["id"]]}%</strong></div>' for module in data["modules"])
    latest_html = "".join(f'<li><a href="#feature-{esc(feature["id"])}" onclick="selectFeature(\'{esc(feature["id"])}\'); return false;"><strong>{esc(feature["id"])}</strong> {esc(feature["title"])}</a><span>{status_badge(feature["status"])}</span></li>' for feature in latest)
    critical_html = "".join(f'<li><a href="#feature-{esc(feature["id"])}" onclick="selectFeature(\'{esc(feature["id"])}\'); return false;">{esc(feature["id"])} — {esc(feature["title"])}</a></li>' for feature in critical) or '<li class="muted">No hay P0 fuera de validación/despliegue.</li>'
    blocked_html = "".join(f'<li><a href="#feature-{esc(feature["id"])}" onclick="selectFeature(\'{esc(feature["id"])}\'); return false;">{esc(feature["id"])} — {esc(feature.get("blockers", ["Estado bloqueado"])[0])}</a></li>' for feature in blocked) or '<li class="muted">No hay bloqueos registrados.</li>'
    risks_html = "".join(f'<li><strong>{esc(feature["id"])}</strong> {esc((feature.get("blockers") or [feature["title"]])[0])}</li>' for feature in risk_items[:7]) or '<li class="muted">Sin riesgos explícitos.</li>'
    return f'''<section class="hero-grid"><div class="hero-card"><div class="eyebrow">OPN ORACLE · SNAPSHOT VIVO</div><h2>Dirección estratégica con evidencia.</h2><p>Un mapa operativo del producto real: qué existe, qué está validado, qué necesita revisión y qué no debe afirmarse todavía.</p><div class="hero-progress"><strong>{data["calculated_project_progress"]}%</strong><span>avance agregado por funcionalidad</span></div><div class="progress-track large"><span style="width:{data["calculated_project_progress"]}%"></span></div></div><div class="signal-card"><div class="eyebrow">LECTURA DE HOY</div><h3>{len(features)} funcionalidades · {len(data["modules"])} módulos</h3><p>{len(blocked)} con bloqueo o riesgo declarado · {len(critical)} P0 requieren atención.</p><div class="mini-stats"><span><strong>{counts.get("validated", 0)}</strong> validadas</span><span><strong>{counts.get("deployed", 0)}</strong> desplegadas</span><span><strong>{counts.get("under_review", 0)}</strong> en revisión</span></div></div></section><section class="kpi-grid"><div class="kpi"><span>Bloqueos</span><strong>{len(blocked)}</strong><small>requieren decisión o fuente</small></div><div class="kpi"><span>P0 abiertos</span><strong>{len(critical)}</strong><small>antes de ampliar alcance</small></div><div class="kpi"><span>Validado/desplegado</span><strong>{counts.get("validated", 0) + counts.get("deployed", 0)}</strong><small>con evidencia en roadmap</small></div><div class="kpi"><span>Riesgo técnico alto</span><strong>{sum(1 for item in features if item.get("technical_risk") == "high")}</strong><small>vigilar en planificación</small></div></section><section class="dashboard-grid"><div class="panel"><div class="panel-heading"><div><div class="eyebrow">ESTADO</div><h3>Distribución del trabajo</h3></div></div>{status_rows}</div><div class="panel"><div class="panel-heading"><div><div class="eyebrow">PREPARACIÓN</div><h3>Por módulo</h3></div></div>{module_rows}</div></section><section class="dashboard-grid"><div class="panel"><div class="panel-heading"><div><div class="eyebrow">SEÑALES DE ATENCIÓN</div><h3>Elementos críticos</h3></div></div><ul class="activity-list">{critical_html}</ul><h4>Bloqueos</h4><ul class="activity-list">{blocked_html}</ul></div><div class="panel"><div class="panel-heading"><div><div class="eyebrow">CONTINUIDAD</div><h3>Últimos avances</h3></div></div><ul class="activity-list">{latest_html}</ul><h4>Riesgos principales</h4><ul class="activity-list">{risks_html}</ul></div></section>'''


def next_work_html(data: dict[str, Any]) -> str:
    features = []
    for feature in data["features"]:
        if feature["status"] in {"validated", "deployed", "rejected"}:
            continue
        score = PRIORITY_WEIGHT.get(feature["priority"], 0) * 20 + (100 - feature.get("progress_percent", 0)) + (20 if feature.get("blockers") else 0) + (10 if feature.get("technical_risk") == "high" else 0)
        features.append((score, feature))
    features.sort(key=lambda item: (-item[0], item[1]["id"]))
    cards = []
    for order, (score, feature) in enumerate(features[:10], start=1):
        cards.append(f'<article class="next-card"><div class="next-order">{order:02d}</div><div><div class="eyebrow">{esc(feature["id"])} · {esc(feature["priority"])} · esfuerzo {esc(feature["complexity"])}</div><h3><a href="#feature-{esc(feature["id"])}" onclick="selectFeature(\'{esc(feature["id"])}\'); return false;">{esc(feature["title"])}</a></h3><p>{esc(feature.get("next_action", "Sin próxima acción"))}</p><div class="tag-row">{status_badge(feature["status"])} <span>riesgo {esc(feature.get("technical_risk", "—"))}</span>{"<span>bloqueado</span>" if feature.get("blockers") else ""}</div></div></article>')
    return "".join(cards) or '<p class="muted">No hay trabajo abierto en el snapshot.</p>'


CSS = r"""
:root{--ink:#17202b;--muted:#687483;--line:#dce3ea;--paper:#f4f7f9;--card:#fff;--navy:#14283d;--teal:#00a89b;--gold:#c8973e;--red:#c94f54;--blue:#3778b8;--purple:#7355aa;--shadow:0 14px 36px rgba(23,32,43,.08);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);line-height:1.48}a{color:#145b83;text-decoration:none}a:hover{text-decoration:underline}button,select,input{font:inherit}button{cursor:pointer}.app-shell{min-height:100vh}.topbar{background:linear-gradient(110deg,#10263b,#1b3c52);color:#fff;padding:28px clamp(18px,4vw,62px);display:flex;justify-content:space-between;gap:24px;align-items:flex-end}.brand-mark{letter-spacing:.16em;font-size:12px;font-weight:800;color:#bfe8e2}.topbar h1{font-size:clamp(25px,4vw,42px);line-height:1.05;margin:8px 0 0;font-weight:720}.topbar p{margin:8px 0 0;color:#c8d6de}.top-meta{text-align:right;font-size:12px;color:#bdd0d8}.top-meta strong{display:block;color:#fff;font-size:15px;margin-bottom:6px}.tabbar{display:flex;gap:4px;overflow:auto;padding:12px clamp(18px,4vw,62px);background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}.tabbar button{border:0;background:transparent;padding:10px 12px;border-radius:8px;color:#5d6b78;white-space:nowrap}.tabbar button:hover,.tabbar button.active{background:#e7f4f2;color:#076e67;font-weight:700}.main{max-width:1550px;margin:0 auto;padding:28px clamp(18px,4vw,62px) 70px}.tab-panel{display:none}.tab-panel.active{display:block}.hero-grid,.dashboard-grid{display:grid;grid-template-columns:1.25fr .75fr;gap:18px;margin-bottom:18px}.hero-card,.signal-card,.panel,.kpi,.feature-card,.decision-card,.progress-card,.next-card{background:var(--card);border:1px solid var(--line);box-shadow:var(--shadow);border-radius:16px}.hero-card{padding:28px;background:radial-gradient(circle at 85% 10%,rgba(0,168,155,.16),transparent 38%),#fff}.signal-card{padding:28px;background:linear-gradient(135deg,#fdfaf2,#fff)}.hero-card h2{font-size:clamp(28px,4vw,48px);line-height:1.06;max-width:680px;margin:10px 0}.hero-card p{max-width:660px;color:var(--muted)}.eyebrow{font-size:10px;letter-spacing:.13em;text-transform:uppercase;font-weight:800;color:#788692}.hero-progress{display:flex;align-items:baseline;gap:12px;margin-top:26px}.hero-progress strong{font-size:44px;color:var(--teal)}.hero-progress span,.muted,small{color:var(--muted);font-size:13px}.signal-card h3{font-size:22px;margin:10px 0}.signal-card p{color:var(--muted)}.mini-stats{display:flex;gap:18px;flex-wrap:wrap;margin-top:30px;color:var(--muted);font-size:12px}.mini-stats strong{display:block;color:var(--ink);font-size:25px}.progress-track{height:7px;background:#e9eef1;border-radius:99px;overflow:hidden;margin-top:10px}.progress-track span{display:block;height:100%;background:linear-gradient(90deg,var(--teal),#68c5ad);border-radius:inherit}.progress-track.large{height:10px}.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px}.kpi{padding:18px}.kpi span{display:block;color:var(--muted);font-size:12px}.kpi strong{display:block;font-size:31px;margin:6px 0}.kpi small{font-size:11px}.panel{padding:22px}.panel-heading{display:flex;justify-content:space-between;margin-bottom:16px}.panel h3,.panel h4{margin:0}.panel h4{margin-top:20px;font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}.status-row,.module-row{display:grid;grid-template-columns:150px 38px 1fr;align-items:center;gap:10px;font-size:13px;margin:9px 0}.status-row strong{text-align:right}.bar{height:8px;border-radius:99px;background:#edf1f3;overflow:hidden}.bar i{display:block;height:100%;background:var(--teal);border-radius:inherit}.module-row{grid-template-columns:minmax(100px,1fr) 1.3fr 42px}.module-row strong{font-size:12px;text-align:right}.activity-list{list-style:none;padding:0;margin:0}.activity-list li{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid #edf1f3;font-size:13px}.activity-list li:last-child{border-bottom:0}.activity-list .status{flex:none}.filters{display:grid;grid-template-columns:2fr repeat(4,1fr);gap:10px;padding:16px;background:#fff;border:1px solid var(--line);border-radius:14px;margin-bottom:18px}.filters input,.filters select{width:100%;border:1px solid #cfd8df;background:#fff;border-radius:8px;padding:10px 11px;color:var(--ink)}.filter-checks{grid-column:1/-1;display:flex;gap:18px;flex-wrap:wrap;color:var(--muted);font-size:13px}.filter-checks label{display:flex;gap:7px;align-items:center}.filter-summary{display:flex;justify-content:space-between;gap:12px;margin:8px 0 14px;color:var(--muted);font-size:13px}.module-group{margin-bottom:16px}.module-group>summary{list-style:none;display:flex;justify-content:space-between;gap:16px;align-items:center;padding:17px 19px;background:var(--navy);color:#fff;border-radius:14px;cursor:pointer}.module-group>summary::-webkit-details-marker{display:none}.module-summary{font-size:12px;color:#bdd0d8;text-align:right}.module-progress{height:4px;background:#d9e2e6;margin:0 13px}.module-progress span{display:block;height:100%;background:var(--gold)}.module-features{padding-top:13px}.feature-card{padding:20px;margin:12px 0;scroll-margin-top:80px}.feature-card.focus-target{outline:3px solid rgba(0,168,155,.45);box-shadow:0 0 0 6px rgba(0,168,155,.1)}.feature-head{display:flex;justify-content:space-between;gap:18px}.feature-head h3{margin:5px 0 0;font-size:20px}.badge-stack{display:flex;gap:7px;align-items:flex-start;flex-wrap:wrap;justify-content:flex-end}.status,.priority,.complexity,.tag-row span{display:inline-flex;align-items:center;border-radius:99px;padding:4px 9px;font-size:11px;font-weight:750;white-space:nowrap}.status{background:#edf2f4;color:#52616d}.status-validated{background:#dcf4e9;color:#167046}.status-deployed{background:#e0e9f9;color:#295790}.status-implemented{background:#e9e3f8;color:#5e408f}.status-under_review{background:#fff0cf;color:#946b20}.status-in_progress{background:#d9f4f1;color:#087b73}.status-blocked{background:#fde2e3;color:#a53e47}.status-deferred,.status-rejected{background:#eceff1;color:#66727c}.priority{background:#f3f6f8;color:#41505d}.priority-P0{color:#9d373f;background:#fde4e5}.priority-P1{color:#8a631e;background:#fff1d4}.complexity{background:#eef4f7;color:#566978}.feature-description{color:var(--muted);max-width:900px;margin:12px 0}.feature-meta{display:flex;gap:20px;flex-wrap:wrap;color:var(--muted);font-size:12px}.feature-meta strong{color:var(--ink)}.feature-grid,.detail-columns{display:grid;grid-template-columns:1fr 1.25fr 1fr;gap:18px;margin-top:18px}.feature-grid h4,.detail-columns h4{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#76838e;margin:0 0 7px}.feature-grid ul,.detail-columns ul,.criteria{padding-left:18px;margin:0;font-size:13px}.feature-grid li,.detail-columns li{margin:4px 0}.criterion-met span{color:#167046}.criterion-partial span{color:#a06d15}.criterion-pending span{color:#a53e47}.evidence-type{font-size:10px;text-transform:uppercase;color:#8b6824;font-weight:800}.feature-card details{margin-top:18px;border-top:1px solid #edf1f3;padding-top:13px}.feature-card summary{cursor:pointer;font-size:13px;color:#4c6572;font-weight:700}.detail-columns p{margin:6px 0;font-size:12px}.comment{font-size:12px;color:var(--muted);border-left:3px solid var(--gold);padding-left:10px}.graph-scroll{overflow:auto;background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow);padding:14px}.roadmap-graph{min-width:1050px;width:100%;height:auto}.roadmap-graph .edge{fill:none;stroke:#b7c8d0;stroke-width:2;stroke-dasharray:5 5}.roadmap-graph .edge-blocks{stroke:var(--red)}.roadmap-graph .edge-quality_gate{stroke:var(--gold)}.graph-module rect{fill:#edf4f5;stroke:#a9c4c6;stroke-width:1.5}.graph-module text{font-size:10px;fill:#4c6470}.graph-module .module-label{font-size:12px;font-weight:700;fill:var(--ink)}.graph-node rect{fill:#fff;stroke:#b8c5cd;stroke-width:1.5}.status-node-blocked rect{fill:#fff4f4;stroke:var(--red)}.status-node-in_progress rect{fill:#effcfb;stroke:var(--teal)}.status-node-implemented rect{fill:#f5f1fc;stroke:var(--purple)}.status-node-validated rect{fill:#effaf4;stroke:#39a56d}.status-node-deployed rect{fill:#eff4fd;stroke:var(--blue)}.graph-node:hover rect{stroke-width:3}.graph-node text{pointer-events:none}.node-id{font-size:10px;fill:#6d7b86}.node-title{font-size:12px;font-weight:750;fill:var(--ink)}.node-status{font-size:10px;fill:#71808a}.architecture-flow{display:flex;gap:8px;align-items:stretch;overflow:auto;margin-bottom:20px}.architecture-flow .flow-node{min-width:155px;flex:1;background:#fff;border:1px solid var(--line);border-radius:12px;padding:15px;box-shadow:var(--shadow)}.architecture-flow .arrow{align-self:center;color:var(--teal);font-size:22px}.doc-sheet{background:#fff;border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:var(--shadow);overflow:auto}.doc-sheet pre{font:13px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;margin:0;color:#34434e}.decision-grid,.progress-grid,.next-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.decision-card,.progress-card{padding:20px}.decision-card h3,.progress-card h3{font-size:18px;margin:7px 0 15px}.decision-card dl{display:grid;grid-template-columns:145px 1fr;gap:8px;margin:0;font-size:13px}.decision-card dt{font-weight:800;color:#657681}.decision-card dd{margin:0;color:var(--muted)}.progress-card li{margin:6px 0;font-size:13px}.next-card{display:flex;gap:18px;padding:19px}.next-order{font-size:26px;font-weight:800;color:var(--gold);min-width:35px}.next-card h3{margin:6px 0;font-size:18px}.next-card p{color:var(--muted);font-size:13px}.tag-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;color:var(--muted);font-size:12px}.empty-state{padding:35px;text-align:center;color:var(--muted);background:#fff;border:1px dashed #cbd6dc;border-radius:14px}.footer{max-width:1550px;margin:0 auto;padding:0 clamp(18px,4vw,62px) 35px;color:#82909a;font-size:12px}@media(max-width:1000px){.hero-grid,.dashboard-grid{grid-template-columns:1fr}.kpi-grid{grid-template-columns:repeat(2,1fr)}.filters{grid-template-columns:1fr 1fr}.feature-grid,.detail-columns{grid-template-columns:1fr 1fr}.topbar{align-items:flex-start;flex-direction:column}.top-meta{text-align:left}}@media(max-width:650px){.main{padding-top:18px}.kpi-grid{grid-template-columns:1fr 1fr;gap:9px}.kpi{padding:13px}.kpi strong{font-size:24px}.filters{grid-template-columns:1fr}.feature-head{display:block}.badge-stack{justify-content:flex-start;margin-top:12px}.feature-grid,.detail-columns,.decision-grid,.progress-grid{grid-template-columns:1fr}.status-row{grid-template-columns:125px 25px 1fr}.module-group>summary{display:block}.module-summary{display:block;text-align:left;margin-top:7px}.tabbar{padding-left:10px;padding-right:10px}.architecture-flow{display:block}.architecture-flow .arrow{display:block;text-align:center;transform:rotate(90deg);height:25px}}
"""


def render_html(data: dict[str, Any], decisions: str, progress: str, architecture: str) -> str:
    counts = Counter(item["status"] for item in data["features"])
    embedded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    architecture_flow = '''<div class="architecture-flow"><span class="flow-node"><strong>Navegador</strong><br><small>Vector / React</small></span><span class="arrow">→</span><span class="flow-node"><strong>Flask / API</strong><br><small>auth · tenant · dominio</small></span><span class="arrow">→</span><span class="flow-node"><strong>PostgreSQL</strong><br><small>fuente de verdad</small></span><span class="arrow">→</span><span class="flow-node"><strong>Celery + Redis</strong><br><small>jobs · sesiones · colas</small></span><span class="arrow">→</span><span class="flow-node"><strong>Signal / IA</strong><br><small>adapters y policy</small></span></div>'''
    return f'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>OPN Oracle · Development Dashboard</title><style>{CSS}</style></head>
<body><div class="app-shell"><header class="topbar"><div><div class="brand-mark">OPN · ORACLE</div><h1>Development Command Center</h1><p>Sistema vivo de planificación, desarrollo y auditoría.</p></div><div class="top-meta"><strong>{esc(data["project"]["version"])}</strong><span>Actualizado {esc(data["project"]["updated_at"])} · {esc(data["project"]["audit"]["branch_observed"])}</span></div></header>
<nav class="tabbar" aria-label="Secciones del dashboard"><button class="active" data-tab="summary">Resumen ejecutivo</button><button data-tab="checklist">Checklist</button><button data-tab="graph">Grafo / mapa</button><button data-tab="architecture">Arquitectura</button><button data-tab="decisions">Decisiones</button><button data-tab="history">Historial</button><button data-tab="next">Próximo trabajo</button></nav>
<main class="main"><section class="tab-panel active" id="tab-summary">{summary_html(data)}</section><section class="tab-panel" id="tab-checklist"><div class="section-heading"><div class="eyebrow">TRABAJO TRAZABLE</div><h2>Checklist funcional</h2><p>Filtra y ordena el snapshot sin modificar la fuente JSON.</p></div><div class="filters"><input id="filter-text" type="search" placeholder="Buscar por ID, título, descripción o acción…" aria-label="Buscar funcionalidades"><select id="filter-status"><option value="">Todos los estados</option>{"".join(f'<option value="{esc(state)}">{esc(label)}</option>' for state, label in STATUS_LABELS.items())}</select><select id="filter-priority"><option value="">Todas las prioridades</option><option>P0</option><option>P1</option><option>P2</option><option>P3</option></select><select id="filter-module"><option value="">Todos los módulos</option>{"".join(f'<option value="{esc(module["id"])}">{esc(module["name"])} </option>' for module in data["modules"])}</select><select id="filter-complexity"><option value="">Todas las complejidades</option>{"".join(f'<option>{value}</option>' for value in ["XS","S","M","L","XL"])}</select><select id="sort-features"><option value="priority">Orden: prioridad</option><option value="progress">Orden: avance</option><option value="updated">Orden: actualizado</option><option value="status">Orden: estado</option></select><div class="filter-checks"><label><input id="filter-blocked" type="checkbox"> Solo bloqueados</label><label><input id="filter-no-tests" type="checkbox"> Sin pruebas</label><label><input id="filter-no-criteria" type="checkbox"> Sin criterios</label></div></div><div class="filter-summary"><span id="filter-result">Mostrando todas las funcionalidades</span><button class="text-button" id="clear-filters" type="button">Limpiar filtros</button></div><div id="checklist-content">{checklist_html(data)}</div></section><section class="tab-panel" id="tab-graph"><div class="section-heading"><div class="eyebrow">DEPENDENCIAS Y ESTADO</div><h2>Mapa operativo del proyecto</h2><p>Selecciona un nodo para localizar su tarjeta en el checklist. Los colores representan estados y los trazos muestran dependencias.</p></div><div class="legend"><span class="status status-in_progress">En desarrollo</span><span class="status status-blocked">Bloqueado</span><span class="status status-implemented">Implementado</span><span class="status status-validated">Validado</span><span class="status status-deployed">Desplegado</span></div>{graph_svg(data)}</section><section class="tab-panel" id="tab-architecture"><div class="section-heading"><div class="eyebrow">FRONTERAS Y FLUJOS</div><h2>Arquitectura viva</h2><p>La vista distingue responsabilidades, procesos asíncronos, seguridad, tenant y puntos de auditoría.</p></div>{architecture_flow}{markdown_as_pre(architecture)}</section><section class="tab-panel" id="tab-decisions"><div class="section-heading"><div class="eyebrow">REGISTRO DE DECISIONES</div><h2>Decisiones que gobiernan el desarrollo</h2><p>Las decisiones detalladas viven en <code>docs/development/oracle-decisions.md</code>.</p></div><div class="decision-grid">{decision_cards(decisions)}</div></section><section class="tab-panel" id="tab-history"><div class="section-heading"><div class="eyebrow">MEMORIA ENTRE SESIONES</div><h2>Historial de progreso</h2><p>Snapshots y cambios con estado anterior, nuevo, pruebas y trabajo pendiente.</p></div><div class="progress-grid">{progress_cards(progress)}</div></section><section class="tab-panel" id="tab-next"><div class="section-heading"><div class="eyebrow">ORDEN RECOMENDADO</div><h2>Próximo trabajo</h2><p>Priorización calculada desde prioridad, avance, bloqueos y riesgo técnico. Es una recomendación, no una autorización automática.</p></div><div class="next-grid">{next_work_html(data)}</div></section></main><footer class="footer">Fuente: <code>docs/development/oracle-roadmap.json</code> · Generado de forma determinista por <code>scripts/generate-development-dashboard.py</code> · Datos calculados: {len(data["features"])} funcionalidades · {sum(counts.values())} estados.</footer></div>
<script>const ROADMAP={embedded};const labels={json.dumps(STATUS_LABELS, ensure_ascii=False)};const tabs=[...document.querySelectorAll('[data-tab]')];function activateTab(name){{tabs.forEach(button=>button.classList.toggle('active',button.dataset.tab===name));document.querySelectorAll('.tab-panel').forEach(panel=>panel.classList.toggle('active',panel.id==='tab-'+name));}}tabs.forEach(button=>button.addEventListener('click',()=>activateTab(button.dataset.tab)));function selectFeature(id){{activateTab('checklist');document.querySelectorAll('.feature-card.focus-target').forEach(card=>card.classList.remove('focus-target'));const card=document.getElementById('feature-'+id);if(!card)return;const group=card.closest('.module-group');if(group)group.open=true;card.classList.add('focus-target');setTimeout(()=>card.scrollIntoView({{behavior:'smooth',block:'center'}}),30);}}const controls=['filter-text','filter-status','filter-priority','filter-module','filter-complexity','sort-features','filter-blocked','filter-no-tests','filter-no-criteria'].map(id=>document.getElementById(id));function applyFilters(){{const text=document.getElementById('filter-text').value.trim().toLowerCase();const status=document.getElementById('filter-status').value;const priority=document.getElementById('filter-priority').value;const module=document.getElementById('filter-module').value;const complexity=document.getElementById('filter-complexity').value;const blocked=document.getElementById('filter-blocked').checked;const noTests=document.getElementById('filter-no-tests').checked;const noCriteria=document.getElementById('filter-no-criteria').checked;const sort=document.getElementById('sort-features').value;const cards=[...document.querySelectorAll('.feature-card')];cards.sort((a,b)=>{{const fa=ROADMAP.features.find(item=>item.id===a.dataset.featureId);const fb=ROADMAP.features.find(item=>item.id===b.dataset.featureId);if(sort==='progress')return Number(fb.progress_percent)-Number(fa.progress_percent);if(sort==='updated')return String(fb.updated_at).localeCompare(String(fa.updated_at));if(sort==='status')return String(fa.status).localeCompare(String(fb.status));return ({json.dumps(PRIORITY_WEIGHT)}[fb.priority]||0)-({json.dumps(PRIORITY_WEIGHT)}[fa.priority]||0)||fa.id.localeCompare(fb.id);}});cards.forEach(card=>card.parentElement.appendChild(card));let shown=0;cards.forEach(card=>{{const matches=(!text||card.dataset.search.includes(text))&&(!status||card.dataset.status===status)&&(!priority||card.dataset.priority===priority)&&(!module||card.dataset.module===module)&&(!complexity||card.dataset.complexity===complexity)&&(!blocked||card.dataset.blocked==='true')&&(!noTests||card.dataset.hasTests==='false')&&(!noCriteria||card.dataset.hasCriteria==='false');card.hidden=!matches;if(matches)shown++;}});document.querySelectorAll('.module-group').forEach(group=>{{group.hidden=!group.querySelector('.feature-card:not([hidden])');}});document.getElementById('filter-result').textContent='Mostrando '+shown+' de '+cards.length+' funcionalidades';}}controls.forEach(control=>control.addEventListener(control.type==='checkbox'?'change':'input',applyFilters));document.getElementById('clear-filters').addEventListener('click',()=>{{controls.forEach(control=>{{if(control.type==='checkbox')control.checked=false;else control.value='';}});applyFilters();}});</script></body></html>'''


def prepare_data(data: dict[str, Any]) -> dict[str, Any]:
    data = json.loads(json.dumps(data, ensure_ascii=False))
    features = data["features"]
    data["calculated_project_progress"] = round(sum(item.get("progress_percent", 0) for item in features) / max(len(features), 1))
    data["calculated_module_progress"] = {}
    for module in data["modules"]:
        values = [next(item["progress_percent"] for item in features if item["id"] == feature_id) for feature_id in module["feature_ids"]]
        data["calculated_module_progress"][module["id"]] = round(sum(values) / max(len(values), 1))
    return data


def generate(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    roadmap_path = (root / args.roadmap).resolve()
    decisions_path = (root / args.decisions).resolve()
    progress_path = (root / args.progress).resolve()
    architecture_path = (root / args.architecture).resolve()
    output_path = (root / args.output).resolve()
    data = read_json(roadmap_path)
    errors, warnings = validate(data, root, decisions_path, output_path)
    if errors:
        print("Roadmap inválido; no se ha sobrescrito el dashboard:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 2
    for warning in warnings:
        print(f"Aviso: {warning}", file=sys.stderr)
    prepared = prepare_data(data)
    if args.check:
        print(f"OK: {roadmap_path.relative_to(root)} válido; {len(data['features'])} funcionalidades, progreso calculado {prepared['calculated_project_progress']}%.")
        return 0
    decisions = decisions_path.read_text(encoding="utf-8")
    progress = progress_path.read_text(encoding="utf-8")
    architecture = architecture_path.read_text(encoding="utf-8")
    rendered = render_html(prepared, decisions, progress, architecture)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output_path.parent, prefix=f".{output_path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(rendered)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output_path)
    try:
        display_output = str(output_path.relative_to(root))
    except ValueError:
        display_output = str(output_path)
    print(f"Generado: {display_output}")
    print(f"Funcionalidades: {len(data['features'])} · módulos: {len(data['modules'])} · progreso calculado: {prepared['calculated_project_progress']}%")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]), help="Raíz del repositorio")
    parser.add_argument("--roadmap", default="docs/development/oracle-roadmap.json")
    parser.add_argument("--decisions", default="docs/development/oracle-decisions.md")
    parser.add_argument("--progress", default="docs/development/oracle-progress.md")
    parser.add_argument("--architecture", default="docs/development/oracle-architecture.md")
    parser.add_argument("--output", default="docs/development/oracle-development-dashboard.html")
    parser.add_argument("--check", action="store_true", help="Valida sin escribir el dashboard")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(generate(parse_args(sys.argv[1:])))
