#!/usr/bin/env python3
"""Ishtar Memory: sistema vivo y editable de planificación para cualquier proyecto.

Fuente única de verdad: ``docs/ishtar_memory/roadmap.json``.
El dashboard HTML es siempre un artefacto generado.

Comandos:
    python scripts/ishtar_memory.py validate
    python scripts/ishtar_memory.py generate
    python scripts/ishtar_memory.py check
    python scripts/ishtar_memory.py serve [--port 8765]

Comandos auxiliares (uso desde el repositorio, no desde el navegador):
    init, add-task, move-task, set-status, add-prompt, migrate

Solo biblioteca estándar. Sin red, sin CDN, sin base de datos externa.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import errno
import hmac
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = "1.0.0"
DEFAULT_PORT = 8765
MAX_REQUEST_BYTES = 2 * 1024 * 1024
ACTIVITY_EMBED_LIMIT = 800

ALLOWED_STATUSES = ["pending", "in_progress", "blocked", "done"]
ALLOWED_PRIORITIES = ["low", "medium", "high", "critical"]

STATUS_LABELS = {
    "pending": "Pendiente",
    "in_progress": "En progreso",
    "blocked": "Bloqueada",
    "done": "Realizada",
}
PRIORITY_LABELS = {
    "low": "Baja",
    "medium": "Media",
    "high": "Alta",
    "critical": "Crítica",
}

ACTIVITY_ACTIONS = [
    "task_created",
    "task_updated",
    "task_moved",
    "task_status_changed",
    "task_completion_overridden",
    "prompt_created",
    "prompt_revised",
    "prompt_archived",
    "comment_created",
    "evidence_created",
    "dashboard_generated",
]

TASK_ID_RE = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{3,}$")
PROMPT_ID_RE = re.compile(r"^.+-P\d{3,}$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
UNSAFE_PATH_RE = re.compile(r"(^/)|(^[A-Za-z]:)|(\.\.)")


# --------------------------------------------------------------------------- #
# Rutas
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Paths:
    """Rutas del sistema, siempre relativas a la raíz del repositorio."""

    root: Path

    @property
    def memory_dir(self) -> Path:
        return self.root / "docs" / "ishtar_memory"

    @property
    def config(self) -> Path:
        return self.memory_dir / "project-config.json"

    @property
    def roadmap(self) -> Path:
        return self.memory_dir / "roadmap.json"

    @property
    def schema(self) -> Path:
        return self.memory_dir / "roadmap.schema.json"

    @property
    def activity(self) -> Path:
        return self.memory_dir / "activity.jsonl"

    @property
    def dashboard(self) -> Path:
        return self.memory_dir / "dashboard.html"

    @property
    def decisions(self) -> Path:
        return self.memory_dir / "decisions.md"

    @property
    def progress(self) -> Path:
        return self.memory_dir / "progress.md"

    @property
    def architecture(self) -> Path:
        return self.memory_dir / "architecture.md"

    @property
    def lock(self) -> Path:
        return self.memory_dir / ".ishtar.lock"


def repository_root(start: Path | None = None) -> Path:
    """Devuelve la raíz del repositorio que contiene este script."""
    here = (start or Path(__file__).resolve()).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / ".git").exists():
            return candidate
    return Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #


class IshtarError(RuntimeError):
    """Error de negocio del sistema, con código estable para la API."""

    def __init__(self, code: str, message: str, *, status: int = 400, **metadata: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.metadata = metadata


def now_iso() -> str:
    """Marca temporal ISO-8601 en UTC, con segundos."""
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def slugify(value: str, *, fallback: str = "proyecto") -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug or fallback


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise IshtarError("FILE_NOT_FOUND", f"No existe {path.name}.", status=404) from None
    except json.JSONDecodeError as exc:
        raise IshtarError(
            "INVALID_JSON", f"{path.name} no es JSON válido: {exc}", status=422
        ) from None


def atomic_write_text(path: Path, content: str) -> None:
    """Escribe de forma atómica: temporal + fsync + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp",
        delete=False,
    )
    tmp_path = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, dump_json(data))


class FileLock:
    """Bloqueo de escritura entre procesos (CLI y servidor local)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            import fcntl

            fcntl.flock(self._fd, fcntl.LOCK_EX)
        except (ImportError, OSError) as exc:  # pragma: no cover - plataformas sin flock
            if isinstance(exc, OSError) and exc.errno not in (errno.EINVAL, errno.ENOTSUP):
                raise
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._fd is None:
            return
        try:
            import fcntl

            fcntl.flock(self._fd, fcntl.LOCK_UN)
        except (ImportError, OSError):  # pragma: no cover
            pass
        os.close(self._fd)
        self._fd = None


# --------------------------------------------------------------------------- #
# Configuración del proyecto
# --------------------------------------------------------------------------- #


def detect_project(root: Path) -> dict[str, str]:
    """Detecta identidad del proyecto sin adivinar funcionalidades."""
    name = root.name
    slug = slugify(name)
    identifier = re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-") or "PROYECTO"
    return {"id": identifier, "name": name, "slug": slug, "task_prefix": "GEN"}


def default_config(root: Path) -> dict[str, Any]:
    detected = detect_project(root)
    return {
        "schema_version": SCHEMA_VERSION,
        "project": {
            "id": detected["id"],
            "name": detected["name"],
            "slug": detected["slug"],
            "task_prefix": detected["task_prefix"],
            "description": "",
        },
        "ui": {
            "dashboard_title": "Development Command Center",
            "default_collapsed_depth": 2,
            "locale": "es-ES",
        },
        "features": {
            "manual_status_updates": True,
            "task_prompt_registry": True,
            "automatic_prompt_recording": False,
        },
    }


def load_config(paths: Paths) -> dict[str, Any]:
    config = read_json(paths.config)
    if not isinstance(config, dict):
        raise IshtarError("INVALID_CONFIG", "project-config.json debe ser un objeto.", status=422)
    return config


def empty_roadmap(project_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "state_revision": 1,
        "project_id": project_id,
        "sequences": {"task": 0, "activity": 0},
        "settings": {
            "allowed_statuses": list(ALLOWED_STATUSES),
            "allowed_priorities": list(ALLOWED_PRIORITIES),
        },
        "tasks": [],
    }


def load_roadmap(paths: Paths) -> dict[str, Any]:
    roadmap = read_json(paths.roadmap)
    if not isinstance(roadmap, dict):
        raise IshtarError("INVALID_ROADMAP", "roadmap.json debe ser un objeto.", status=422)
    return roadmap


# --------------------------------------------------------------------------- #
# Modelo de tareas
# --------------------------------------------------------------------------- #


def new_task(
    task_id: str,
    title: str,
    *,
    parent_id: str | None = None,
    description: str = "",
    objective: str = "",
    priority: str = "medium",
) -> dict[str, Any]:
    stamp = now_iso()
    return {
        "id": task_id,
        "title": title,
        "description": description,
        "objective": objective,
        "status": "pending",
        "priority": priority,
        "parent_id": parent_id,
        "children": [],
        "dependencies": [],
        "acceptance_criteria": [],
        "comments": [],
        "evidence": [],
        "related_files": [],
        "tests": [],
        "prompt_records": [],
        "blocked_reason": None,
        "completion_override": None,
        "created_at": stamp,
        "updated_at": stamp,
        "completed_at": None,
    }


def iter_tasks(
    tasks: list[dict[str, Any]], parent: dict[str, Any] | None = None, depth: int = 0
) -> Iterator[tuple[dict[str, Any], dict[str, Any] | None, int]]:
    """Recorre el árbol en profundidad conservando el orden manual."""
    for task in tasks:
        yield task, parent, depth
        children = task.get("children")
        if isinstance(children, list):
            yield from iter_tasks(children, task, depth + 1)


def all_tasks(roadmap: dict[str, Any]) -> list[dict[str, Any]]:
    return [task for task, _parent, _depth in iter_tasks(roadmap.get("tasks", []))]


def find_task(roadmap: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task, _parent, _depth in iter_tasks(roadmap.get("tasks", [])):
        if task.get("id") == task_id:
            return task
    raise IshtarError("TASK_NOT_FOUND", f"La tarea {task_id} no existe.", status=404)


def find_task_container(
    roadmap: dict[str, Any], task_id: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Devuelve la lista que contiene la tarea y su padre."""

    def walk(
        siblings: list[dict[str, Any]], parent: dict[str, Any] | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None] | None:
        for task in siblings:
            if task.get("id") == task_id:
                return siblings, parent
            found = walk(task.get("children") or [], task)
            if found:
                return found
        return None

    result = walk(roadmap.get("tasks", []), None)
    if result is None:
        raise IshtarError("TASK_NOT_FOUND", f"La tarea {task_id} no existe.", status=404)
    return result


def descendant_ids(task: dict[str, Any]) -> set[str]:
    return {child.get("id") for child, _p, _d in iter_tasks(task.get("children") or [])}


def next_task_id(roadmap: dict[str, Any], prefix: str, group: str) -> str:
    """Genera un ID único y estable dentro del grupo indicado."""
    group_clean = re.sub(r"[^A-Z0-9]+", "", group.upper()) or "TSK"
    stem = f"{prefix.upper()}-{group_clean}-"
    used = {task.get("id", "") for task in all_tasks(roadmap)}
    highest = 0
    for identifier in used:
        if identifier.startswith(stem):
            tail = identifier[len(stem) :]
            if tail.isdigit():
                highest = max(highest, int(tail))
    candidate_number = highest + 1
    while f"{stem}{candidate_number:03d}" in used:
        candidate_number += 1
    return f"{stem}{candidate_number:03d}"


def next_prompt_id(task: dict[str, Any]) -> str:
    """Los IDs de prompts nunca se reutilizan, ni siquiera tras archivar."""
    records = task.get("prompt_records") or []
    highest = 0
    for record in records:
        identifier = str(record.get("id", ""))
        _, _, tail = identifier.rpartition("-P")
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{task['id']}-P{highest + 1:03d}"


def completion_warnings(task: dict[str, Any]) -> list[str]:
    """Elementos pendientes que desaconsejan marcar la tarea como realizada."""
    warnings: list[str] = []
    pending_children = [
        child for child in (task.get("children") or []) if child.get("status") != "done"
    ]
    if pending_children:
        warnings.append(
            f"{len(pending_children)} subtarea(s) sin marcar como realizadas: "
            + ", ".join(str(child.get("id")) for child in pending_children[:5])
        )
    criteria = task.get("acceptance_criteria") or []
    unmet = [item for item in criteria if isinstance(item, dict) and not item.get("met")]
    if unmet:
        warnings.append(f"{len(unmet)} criterio(s) de aceptación sin cumplir.")
    tests = task.get("tests") or []
    failing = [
        item
        for item in tests
        if isinstance(item, dict) and item.get("result") not in (None, "", "passed")
    ]
    if failing:
        warnings.append(f"{len(failing)} prueba(s) sin superar.")
    if task.get("status") == "blocked" or task.get("blocked_reason"):
        warnings.append("La tarea tiene un bloqueo activo registrado.")
    if not task.get("evidence"):
        warnings.append("La tarea no tiene evidencias registradas.")
    return warnings


# --------------------------------------------------------------------------- #
# Actividad
# --------------------------------------------------------------------------- #


def read_activity(paths: Paths) -> list[dict[str, Any]]:
    if not paths.activity.exists():
        return []
    events: list[dict[str, Any]] = []
    for number, line in enumerate(paths.activity.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise IshtarError(
                "INVALID_ACTIVITY", f"activity.jsonl línea {number} no es JSON válido: {exc}",
                status=422,
            ) from None
        if not isinstance(event, dict):
            raise IshtarError(
                "INVALID_ACTIVITY", f"activity.jsonl línea {number} no es un objeto.", status=422
            )
        events.append(event)
    return events


def next_event_id(paths: Paths, roadmap: dict[str, Any] | None = None) -> tuple[str, int]:
    highest = 0
    if roadmap is not None:
        sequences = roadmap.get("sequences") or {}
        if isinstance(sequences.get("activity"), int):
            highest = max(highest, sequences["activity"])
    if paths.activity.exists():
        for line in reversed(paths.activity.read_text(encoding="utf-8").splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                identifier = str(json.loads(stripped).get("event_id", ""))
            except json.JSONDecodeError:
                break
            digits = identifier.rpartition("-")[2]
            if digits.isdigit():
                highest = max(highest, int(digits))
            break
    number = highest + 1
    return f"EVT-{number:06d}", number


def append_activity(
    paths: Paths,
    *,
    action: str,
    actor: str = "user",
    source: str = "cli",
    task_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    roadmap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Añade un evento al registro cronológico. Nunca guarda el texto del prompt."""
    event_id, number = next_event_id(paths, roadmap)
    event = {
        "event_id": event_id,
        "timestamp": now_iso(),
        "actor": actor,
        "source": source,
        "action": action,
        "task_id": task_id,
        "before": before or {},
        "after": after or {},
        "metadata": metadata or {},
    }
    paths.activity.parent.mkdir(parents=True, exist_ok=True)
    with open(paths.activity, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    if roadmap is not None:
        roadmap.setdefault("sequences", {})["activity"] = number
    return event


# --------------------------------------------------------------------------- #
# Validación
# --------------------------------------------------------------------------- #


@dataclass
class Issue:
    level: str
    code: str
    message: str
    task_id: str | None = None


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, code: str, message: str, task_id: str | None = None) -> None:
        self.issues.append(Issue("error", code, message, task_id))

    def warn(self, code: str, message: str, task_id: str | None = None) -> None:
        self.issues.append(Issue("warning", code, message, task_id))


def _valid_iso(value: Any) -> bool:
    return isinstance(value, str) and bool(ISO_DATE_RE.match(value))


def _validate_prompts(task: dict[str, Any], report: ValidationReport, seen: set[str]) -> None:
    records = task.get("prompt_records")
    if not isinstance(records, list):
        report.error("PROMPTS_NOT_LIST", "prompt_records debe ser una lista.", task.get("id"))
        return
    for record in records:
        if not isinstance(record, dict):
            report.error("PROMPT_NOT_OBJECT", "Cada prompt debe ser un objeto.", task.get("id"))
            continue
        prompt_id = record.get("id")
        if not isinstance(prompt_id, str) or not PROMPT_ID_RE.match(prompt_id):
            report.error("PROMPT_ID_INVALID", f"ID de prompt inválido: {prompt_id!r}", task.get("id"))
        elif prompt_id in seen:
            report.error("PROMPT_ID_DUPLICATE", f"ID de prompt duplicado: {prompt_id}", task.get("id"))
        else:
            seen.add(prompt_id)
        if not str(record.get("title") or "").strip():
            report.error("PROMPT_TITLE_EMPTY", f"El prompt {prompt_id} no tiene título.", task.get("id"))
        if not str(record.get("prompt_text") or "").strip():
            report.error("PROMPT_TEXT_EMPTY", f"El prompt {prompt_id} no tiene texto.", task.get("id"))
        history = record.get("revision_history")
        if not isinstance(history, list):
            report.error("PROMPT_HISTORY_INVALID", f"revision_history inválido en {prompt_id}.", task.get("id"))
        else:
            for index, revision in enumerate(history, 1):
                if not isinstance(revision, dict):
                    report.error("PROMPT_REVISION_INVALID", f"Revisión {index} inválida en {prompt_id}.", task.get("id"))
                    continue
                missing = [key for key in ("revision", "prompt_text", "changed_at") if key not in revision]
                if missing:
                    report.error(
                        "PROMPT_REVISION_INCOMPLETE",
                        f"Revisión {index} de {prompt_id} sin {', '.join(missing)}.",
                        task.get("id"),
                    )
        for key in ("created_at", "updated_at"):
            if not _valid_iso(record.get(key)):
                report.error("PROMPT_DATE_INVALID", f"{key} inválido en {prompt_id}.", task.get("id"))
        archived = record.get("archived_at")
        if archived is not None and not _valid_iso(archived):
            report.error("PROMPT_DATE_INVALID", f"archived_at inválido en {prompt_id}.", task.get("id"))


def validate(
    config: dict[str, Any], roadmap: dict[str, Any], activity: list[dict[str, Any]]
) -> ValidationReport:
    """Comprueba configuración, árbol, tareas, prompts, dependencias y actividad."""
    report = ValidationReport()

    project = config.get("project")
    if not isinstance(project, dict):
        report.error("CONFIG_PROJECT_MISSING", "project-config.json sin bloque 'project'.")
    else:
        for key in ("id", "name", "slug", "task_prefix"):
            if not str(project.get(key) or "").strip():
                report.error("CONFIG_FIELD_MISSING", f"project.{key} vacío en project-config.json.")

    if roadmap.get("schema_version") != SCHEMA_VERSION:
        report.error(
            "ROADMAP_SCHEMA_VERSION",
            f"schema_version debe ser {SCHEMA_VERSION}, encontrado {roadmap.get('schema_version')!r}.",
        )
    revision = roadmap.get("state_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        report.error("ROADMAP_REVISION_INVALID", "state_revision debe ser un entero positivo.")
    if isinstance(project, dict) and roadmap.get("project_id") != project.get("id"):
        report.error(
            "ROADMAP_PROJECT_MISMATCH",
            "roadmap.project_id no coincide con project-config.json.",
        )

    settings = roadmap.get("settings") or {}
    statuses = settings.get("allowed_statuses") or ALLOWED_STATUSES
    priorities = settings.get("allowed_priorities") or ALLOWED_PRIORITIES
    if list(statuses) != ALLOWED_STATUSES:
        report.error("SETTINGS_STATUSES", "allowed_statuses no coincide con los estados soportados.")
    if list(priorities) != ALLOWED_PRIORITIES:
        report.error("SETTINGS_PRIORITIES", "allowed_priorities no coincide con las prioridades soportadas.")

    tasks = roadmap.get("tasks")
    if not isinstance(tasks, list):
        report.error("TASKS_NOT_LIST", "roadmap.tasks debe ser una lista.")
        return report

    seen_task_ids: set[str] = set()
    seen_prompt_ids: set[str] = set()
    known_ids: set[str] = set()

    for task, parent, _depth in iter_tasks(tasks):
        task_id = task.get("id")
        if not isinstance(task_id, str) or not TASK_ID_RE.match(task_id):
            report.error("TASK_ID_INVALID", f"ID de tarea inválido: {task_id!r}", task_id if isinstance(task_id, str) else None)
            continue
        if task_id in seen_task_ids:
            report.error("TASK_ID_DUPLICATE", f"ID de tarea duplicado: {task_id}", task_id)
        seen_task_ids.add(task_id)
        known_ids.add(task_id)

    for task, parent, _depth in iter_tasks(tasks):
        task_id = task.get("id") if isinstance(task.get("id"), str) else None
        if not str(task.get("title") or "").strip():
            report.error("TASK_TITLE_EMPTY", f"La tarea {task_id} no tiene título.", task_id)

        status = task.get("status")
        if status not in ALLOWED_STATUSES:
            report.error("TASK_STATUS_INVALID", f"Estado inválido en {task_id}: {status!r}", task_id)
        priority = task.get("priority")
        if priority not in ALLOWED_PRIORITIES:
            report.error("TASK_PRIORITY_INVALID", f"Prioridad inválida en {task_id}: {priority!r}", task_id)

        expected_parent = parent.get("id") if parent else None
        if task.get("parent_id") != expected_parent:
            report.error(
                "TASK_PARENT_MISMATCH",
                f"parent_id de {task_id} es {task.get('parent_id')!r} pero está contenida en {expected_parent!r}.",
                task_id,
            )
        if task.get("parent_id") is not None and task.get("parent_id") not in known_ids:
            report.error("TASK_PARENT_MISSING", f"El padre de {task_id} no existe.", task_id)
        if task_id and task_id in descendant_ids(task):
            report.error("TASK_CYCLE", f"La tarea {task_id} es descendiente de sí misma.", task_id)

        if not isinstance(task.get("children"), list):
            report.error("TASK_CHILDREN_INVALID", f"children de {task_id} debe ser una lista.", task_id)

        dependencies = task.get("dependencies")
        if not isinstance(dependencies, list):
            report.error("TASK_DEPENDENCIES_INVALID", f"dependencies de {task_id} debe ser una lista.", task_id)
        else:
            for dependency in dependencies:
                if dependency not in known_ids:
                    report.error("DEPENDENCY_MISSING", f"{task_id} depende de {dependency!r}, que no existe.", task_id)
                elif dependency == task_id:
                    report.error("DEPENDENCY_SELF", f"{task_id} no puede depender de sí misma.", task_id)

        if status == "blocked" and not str(task.get("blocked_reason") or "").strip():
            report.error("BLOCKED_WITHOUT_REASON", f"{task_id} está bloqueada sin motivo.", task_id)

        for key in ("created_at", "updated_at"):
            if not _valid_iso(task.get(key)):
                report.error("TASK_DATE_INVALID", f"{key} inválido en {task_id}.", task_id)
        completed_at = task.get("completed_at")
        if status == "done" and not _valid_iso(completed_at):
            report.error("TASK_COMPLETED_AT_MISSING", f"{task_id} está realizada sin completed_at.", task_id)
        if status != "done" and completed_at is not None:
            report.error("TASK_COMPLETED_AT_UNEXPECTED", f"{task_id} no está realizada pero tiene completed_at.", task_id)

        override = task.get("completion_override")
        if override is not None:
            if not isinstance(override, dict) or not str(override.get("reason") or "").strip():
                report.error("OVERRIDE_INVALID", f"completion_override de {task_id} sin motivo.", task_id)
            else:
                report.warn(
                    "TASK_DONE_WITH_WARNINGS",
                    f"{task_id} está realizada manualmente con elementos pendientes.",
                    task_id,
                )
        if status == "done" and override is None:
            for warning in completion_warnings(task):
                report.warn("TASK_DONE_PENDING_ITEM", f"{task_id}: {warning}", task_id)

        for reference in task.get("related_files") or []:
            if not isinstance(reference, str) or UNSAFE_PATH_RE.search(reference):
                report.error("UNSAFE_FILE_REFERENCE", f"Referencia de archivo insegura en {task_id}: {reference!r}", task_id)

        _validate_prompts(task, report, seen_prompt_ids)

    for index, event in enumerate(activity, 1):
        for key in ("event_id", "timestamp", "action"):
            if not str(event.get(key) or "").strip():
                report.error("ACTIVITY_MALFORMED", f"Evento {index} sin {key}.")
        if event.get("action") not in ACTIVITY_ACTIONS:
            report.warn("ACTIVITY_UNKNOWN_ACTION", f"Evento {index} con acción desconocida: {event.get('action')!r}")
        if not _valid_iso(event.get("timestamp")):
            report.error("ACTIVITY_TIMESTAMP_INVALID", f"Evento {index} con timestamp inválido.")
        referenced = event.get("task_id")
        if referenced and referenced not in known_ids:
            report.warn("ACTIVITY_TASK_UNKNOWN", f"Evento {index} referencia la tarea inexistente {referenced}.")

    return report


# --------------------------------------------------------------------------- #
# Métricas
# --------------------------------------------------------------------------- #


def compute_metrics(roadmap: dict[str, Any], activity: list[dict[str, Any]]) -> dict[str, Any]:
    tasks = roadmap.get("tasks", [])
    flat = all_tasks(roadmap)
    by_status = {status: 0 for status in ALLOWED_STATUSES}
    prompts_total = 0
    prompts_active = 0
    without_prompts = 0
    overrides = 0
    for task in flat:
        status = task.get("status")
        if status in by_status:
            by_status[status] += 1
        records = task.get("prompt_records") or []
        prompts_total += len(records)
        prompts_active += len([r for r in records if not r.get("archived_at")])
        if not records:
            without_prompts += 1
        if task.get("completion_override"):
            overrides += 1

    updates = [task.get("updated_at") for task in flat if _valid_iso(task.get("updated_at"))]
    timestamps = [event.get("timestamp") for event in activity if _valid_iso(event.get("timestamp"))]
    last_update = max([*updates, *timestamps], default=None)

    done = by_status["done"]
    total = len(flat)
    return {
        "project_id": roadmap.get("project_id"),
        "state_revision": roadmap.get("state_revision"),
        "total_tasks": total,
        "root_tasks": len(tasks),
        "by_status": by_status,
        "prompts_total": prompts_total,
        "prompts_active": prompts_active,
        "prompts_archived": prompts_total - prompts_active,
        "tasks_without_prompts": without_prompts if total else 0,
        "completion_overrides": overrides,
        "progress_percent": round(done * 100 / total) if total else 0,
        "activity_events": len(activity),
        "last_update": last_update,
    }


def branch_progress(roadmap: dict[str, Any]) -> list[dict[str, Any]]:
    """Progreso calculado por rama raíz. Nunca cambia el estado del padre."""
    branches: list[dict[str, Any]] = []
    for root in roadmap.get("tasks", []):
        nodes = [root, *[child for child, _p, _d in iter_tasks(root.get("children") or [])]]
        done = len([node for node in nodes if node.get("status") == "done"])
        children = [child for child, _p, _d in iter_tasks(root.get("children") or [])]
        children_done = len([child for child in children if child.get("status") == "done"])
        branches.append(
            {
                "id": root.get("id"),
                "title": root.get("title"),
                "status": root.get("status"),
                "total": len(nodes),
                "done": done,
                "children_total": len(children),
                "children_done": children_done,
                "percent": round(done * 100 / len(nodes)) if nodes else 0,
            }
        )
    return branches


# --------------------------------------------------------------------------- #
# Transacciones
# --------------------------------------------------------------------------- #


def check_revision(roadmap: dict[str, Any], expected: Any) -> None:
    if expected is None:
        return
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise IshtarError("VALIDATION_ERROR", "expected_revision debe ser un entero.", status=422)
    current = roadmap.get("state_revision")
    if expected != current:
        raise IshtarError(
            "REVISION_CONFLICT",
            "El estado del proyecto ha cambiado. Actualiza los datos antes de guardar.",
            status=409,
            current_revision=current,
            expected_revision=expected,
        )


class Transaction:
    """Lee, valida, escribe atómicamente y registra actividad, o no aplica nada."""

    def __init__(self, paths: Paths, *, source: str = "cli", actor: str = "user") -> None:
        self.paths = paths
        self.source = source
        self.actor = actor
        self._lock = FileLock(paths.lock)
        self.roadmap: dict[str, Any] = {}
        self._pending: list[dict[str, Any]] = []

    def __enter__(self) -> "Transaction":
        self._lock.__enter__()
        try:
            self.roadmap = load_roadmap(self.paths)
        except BaseException:
            self._lock.__exit__()
            raise
        return self

    def record(
        self,
        action: str,
        *,
        task_id: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._pending.append(
            {
                "action": action,
                "task_id": task_id,
                "before": before,
                "after": after,
                "metadata": metadata,
            }
        )

    def commit(self) -> dict[str, Any]:
        config = load_config(self.paths)
        report = validate(config, self.roadmap, [])
        if not report.ok:
            details = "; ".join(issue.message for issue in report.errors[:5])
            raise IshtarError(
                "VALIDATION_ERROR",
                f"El cambio dejaría el roadmap inválido: {details}",
                status=422,
                errors=[issue.message for issue in report.errors],
            )
        self.roadmap["state_revision"] = int(self.roadmap.get("state_revision", 1)) + 1
        for event in self._pending:
            append_activity(
                self.paths,
                action=event["action"],
                actor=self.actor,
                source=self.source,
                task_id=event["task_id"],
                before=event["before"],
                after=event["after"],
                metadata=event["metadata"],
                roadmap=self.roadmap,
            )
        atomic_write_json(self.paths.roadmap, self.roadmap)
        self._pending.clear()
        return self.roadmap

    def __exit__(self, exc_type: object, *_rest: object) -> None:
        self._lock.__exit__()


# --------------------------------------------------------------------------- #
# Operaciones
# --------------------------------------------------------------------------- #


def op_set_status(
    transaction: Transaction,
    task_id: str,
    status: str,
    *,
    override_reason: str | None = None,
    blocked_reason: str | None = None,
) -> dict[str, Any]:
    """Cambia el estado manualmente. El usuario conserva la decisión final."""
    if status not in ALLOWED_STATUSES:
        raise IshtarError("INVALID_STATUS", f"Estado no permitido: {status!r}", status=422)
    task = find_task(transaction.roadmap, task_id)
    previous = task.get("status")

    if status == "blocked":
        reason = (blocked_reason or task.get("blocked_reason") or "").strip()
        if not reason:
            raise IshtarError(
                "BLOCKED_REQUIRES_REASON",
                "Indica el motivo del bloqueo para marcar la tarea como bloqueada.",
                status=422,
            )
        task["blocked_reason"] = reason
    elif previous == "blocked":
        task["blocked_reason"] = None

    if status == "done":
        warnings = completion_warnings(task)
        reason = (override_reason or "").strip()
        if warnings and not reason and not task.get("completion_override"):
            raise IshtarError(
                "COMPLETION_REQUIRES_OVERRIDE",
                "Esta tarea todavía contiene elementos pendientes.",
                status=409,
                warnings=warnings,
            )
        if warnings and reason:
            task["completion_override"] = {
                "reason": reason,
                "created_at": now_iso(),
                "actor": transaction.actor,
            }
            transaction.record(
                "task_completion_overridden",
                task_id=task_id,
                after={"reason": reason},
                metadata={"warnings": warnings},
            )
        task["completed_at"] = now_iso()
    else:
        task["completed_at"] = None
        if previous == "done":
            task["completion_override"] = None

    task["status"] = status
    task["updated_at"] = now_iso()
    transaction.record(
        "task_status_changed",
        task_id=task_id,
        before={"status": previous},
        after={"status": status},
    )
    return task


def op_add_prompt(transaction: Transaction, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Registra el texto literal del prompt bajo un ID propio y estable."""
    task = find_task(transaction.roadmap, task_id)
    title = str(payload.get("title") or "").strip()
    text = str(payload.get("prompt_text") or "")
    if not title:
        raise IshtarError("VALIDATION_ERROR", "El prompt necesita un título.", status=422)
    if not text.strip():
        raise IshtarError("VALIDATION_ERROR", "El prompt necesita un texto.", status=422)

    stamp = now_iso()
    record = {
        "id": next_prompt_id(task),
        "title": title,
        "prompt_text": text,
        "purpose": str(payload.get("purpose") or ""),
        "tool_or_model": str(payload.get("tool_or_model") or ""),
        "tags": [str(tag).strip() for tag in (payload.get("tags") or []) if str(tag).strip()],
        "notes": str(payload.get("notes") or ""),
        "result_summary": str(payload.get("result_summary") or ""),
        "related_files": [
            str(item).strip() for item in (payload.get("related_files") or []) if str(item).strip()
        ],
        "revision_history": [],
        "created_at": stamp,
        "updated_at": stamp,
        "archived_at": None,
    }
    task.setdefault("prompt_records", []).append(record)
    task["updated_at"] = stamp
    transaction.record(
        "prompt_created",
        task_id=task_id,
        after={"prompt_id": record["id"], "title": title},
        metadata={"characters": len(text)},
    )
    return record


def find_prompt(task: dict[str, Any], prompt_id: str) -> dict[str, Any]:
    for record in task.get("prompt_records") or []:
        if record.get("id") == prompt_id:
            return record
    raise IshtarError("PROMPT_NOT_FOUND", f"El prompt {prompt_id} no existe.", status=404)


def op_revise_prompt(
    transaction: Transaction, task_id: str, prompt_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Nunca sobrescribe un prompt sin conservar la versión anterior."""
    task = find_task(transaction.roadmap, task_id)
    record = find_prompt(task, prompt_id)
    stamp = now_iso()
    new_text = payload.get("prompt_text")

    if new_text is not None and str(new_text) != record.get("prompt_text"):
        if not str(new_text).strip():
            raise IshtarError("VALIDATION_ERROR", "El prompt necesita un texto.", status=422)
        history = record.setdefault("revision_history", [])
        history.append(
            {
                "revision": len(history) + 1,
                "prompt_text": record.get("prompt_text", ""),
                "changed_at": stamp,
                "change_reason": str(payload.get("change_reason") or ""),
                "actor": transaction.actor,
            }
        )
        record["prompt_text"] = str(new_text)

    for key in ("title", "purpose", "tool_or_model", "notes", "result_summary"):
        if key in payload and payload[key] is not None:
            value = str(payload[key])
            if key == "title" and not value.strip():
                raise IshtarError("VALIDATION_ERROR", "El prompt necesita un título.", status=422)
            record[key] = value.strip() if key == "title" else value
    for key in ("tags", "related_files"):
        if key in payload and payload[key] is not None:
            record[key] = [str(item).strip() for item in payload[key] if str(item).strip()]

    record["updated_at"] = stamp
    task["updated_at"] = stamp
    transaction.record(
        "prompt_revised",
        task_id=task_id,
        after={"prompt_id": prompt_id, "title": record.get("title")},
        metadata={"revisions": len(record.get("revision_history") or [])},
    )
    return record


def op_archive_prompt(transaction: Transaction, task_id: str, prompt_id: str) -> dict[str, Any]:
    """Archiva sin eliminar: el prompt permanece en el JSON."""
    task = find_task(transaction.roadmap, task_id)
    record = find_prompt(task, prompt_id)
    stamp = now_iso()
    record["archived_at"] = stamp
    record["updated_at"] = stamp
    task["updated_at"] = stamp
    transaction.record(
        "prompt_archived",
        task_id=task_id,
        after={"prompt_id": prompt_id, "title": record.get("title")},
    )
    return record


def op_add_task(
    transaction: Transaction,
    *,
    title: str,
    group: str,
    parent_id: str | None = None,
    description: str = "",
    objective: str = "",
    priority: str = "medium",
    task_id: str | None = None,
) -> dict[str, Any]:
    roadmap = transaction.roadmap
    config = load_config(transaction.paths)
    prefix = str((config.get("project") or {}).get("task_prefix") or "GEN")
    identifier = task_id or next_task_id(roadmap, prefix, group)
    if any(task.get("id") == identifier for task in all_tasks(roadmap)):
        raise IshtarError("TASK_ID_DUPLICATE", f"El ID {identifier} ya existe.", status=422)

    task = new_task(
        identifier,
        title,
        parent_id=parent_id,
        description=description,
        objective=objective,
        priority=priority,
    )
    if parent_id:
        parent = find_task(roadmap, parent_id)
        parent.setdefault("children", []).append(task)
        parent["updated_at"] = now_iso()
    else:
        roadmap.setdefault("tasks", []).append(task)

    sequences = roadmap.setdefault("sequences", {})
    sequences["task"] = int(sequences.get("task", 0)) + 1
    transaction.record(
        "task_created",
        task_id=identifier,
        after={"title": title, "parent_id": parent_id},
    )
    return task


def op_move_task(transaction: Transaction, task_id: str, new_parent_id: str | None) -> dict[str, Any]:
    """Mover conserva el ID y todos los descendientes."""
    roadmap = transaction.roadmap
    task = find_task(roadmap, task_id)
    if new_parent_id == task_id:
        raise IshtarError("TASK_CYCLE", "Una tarea no puede ser su propio padre.", status=422)
    if new_parent_id and new_parent_id in descendant_ids(task):
        raise IshtarError(
            "TASK_CYCLE", "Una tarea no puede moverse dentro de su propia descendencia.", status=422
        )

    siblings, _parent = find_task_container(roadmap, task_id)
    previous_parent = task.get("parent_id")
    siblings.remove(task)
    task["parent_id"] = new_parent_id
    if new_parent_id:
        find_task(roadmap, new_parent_id).setdefault("children", []).append(task)
    else:
        roadmap.setdefault("tasks", []).append(task)
    task["updated_at"] = now_iso()
    transaction.record(
        "task_moved",
        task_id=task_id,
        before={"parent_id": previous_parent},
        after={"parent_id": new_parent_id},
    )
    return task


# --------------------------------------------------------------------------- #
# Dashboard: estilos
# --------------------------------------------------------------------------- #

_CSS = r"""
*, *::before, *::after { box-sizing: border-box; }
:root {
  --bg: #0b0f16; --bg-soft: #111725; --panel: #151d2c; --panel-2: #1a2334;
  --line: #24304a; --line-soft: #1c2537;
  --text: #e8edf7; --muted: #97a3ba; --faint: #6c7a93;
  --accent: #6ea8fe; --accent-soft: rgba(110,168,254,.14);
  --pending: #8b98ad; --progress: #f0b232; --blocked: #f2555a; --done: #3fb27f;
  --low: #6c7a93; --medium: #6ea8fe; --high: #f0b232; --critical: #f2555a;
  --radius: 12px; --radius-sm: 8px;
  --shadow: 0 18px 48px rgba(0,0,0,.45);
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, Helvetica, Arial, sans-serif;
}
@media (prefers-color-scheme: light) {
  :root {
    --bg: #f4f6fb; --bg-soft: #ffffff; --panel: #ffffff; --panel-2: #f7f9fd;
    --line: #dde3ee; --line-soft: #e8edf6;
    --text: #16203a; --muted: #5a6883; --faint: #7d8aa3;
    --accent: #2f6fdd; --accent-soft: rgba(47,111,221,.10);
    --pending: #77839a; --progress: #b9791a; --blocked: #cf3239; --done: #1f855a;
    --low: #7d8aa3; --medium: #2f6fdd; --high: #b9791a; --critical: #cf3239;
    --shadow: 0 14px 36px rgba(22,32,58,.14);
  }
}
html, body { height: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: var(--sans); font-size: 14px; line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
a { color: var(--accent); }
button { font: inherit; color: inherit; cursor: pointer; }
h1, h2, h3, h4 { margin: 0; font-weight: 650; letter-spacing: -.01em; }

/* ---------- cabecera ---------- */
.shell { max-width: 1400px; margin: 0 auto; padding: 22px 24px 64px; }
header.top {
  display: flex; flex-wrap: wrap; gap: 16px; align-items: center;
  justify-content: space-between; padding-bottom: 18px;
}
.brand { display: flex; align-items: center; gap: 13px; }
.sigil {
  width: 40px; height: 40px; border-radius: 11px; display: grid; place-items: center;
  background: linear-gradient(150deg, var(--accent), #a06ffe);
  color: #fff; font-weight: 700; font-size: 15px; letter-spacing: .04em;
  box-shadow: 0 6px 18px rgba(110,168,254,.32);
}
.brand h1 { font-size: 17px; }
.brand .sub { color: var(--muted); font-size: 12px; }
.head-right { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.mode-badge {
  display: inline-flex; align-items: center; gap: 7px; padding: 6px 12px;
  border-radius: 999px; border: 1px solid var(--line); background: var(--panel);
  font-size: 12px; font-weight: 600;
}
.mode-badge .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--pending); }
.mode-badge.edit { border-color: rgba(63,178,127,.5); color: var(--done); }
.mode-badge.edit .dot { background: var(--done); }
.mode-note {
  border: 1px solid var(--line); background: var(--panel); border-radius: var(--radius);
  padding: 11px 14px; color: var(--muted); font-size: 13px; margin-bottom: 16px;
}
.mode-note code { font-family: var(--mono); color: var(--text); background: var(--panel-2);
  padding: 2px 6px; border-radius: 5px; border: 1px solid var(--line-soft); }

/* ---------- pestañas ---------- */
nav.tabs {
  display: flex; gap: 4px; overflow-x: auto; border-bottom: 1px solid var(--line);
  margin-bottom: 18px; padding-bottom: 0;
}
nav.tabs button {
  background: none; border: 0; border-bottom: 2px solid transparent; color: var(--muted);
  padding: 10px 14px; font-size: 13px; font-weight: 600; white-space: nowrap; border-radius: 0;
}
nav.tabs button:hover { color: var(--text); }
nav.tabs button[aria-selected="true"] { color: var(--text); border-bottom-color: var(--accent); }
nav.tabs .count {
  font-size: 11px; color: var(--faint); background: var(--panel-2);
  border: 1px solid var(--line-soft); border-radius: 999px; padding: 0 6px; margin-left: 6px;
}
section.tab[hidden] { display: none; }

/* ---------- tarjetas ---------- */
.grid { display: grid; gap: 14px; }
.grid.kpi { grid-template-columns: repeat(auto-fit, minmax(158px, 1fr)); }
.grid.two { grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
.card {
  background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius);
  padding: 15px 16px;
}
.card h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); margin-bottom: 12px; }
.kpi .label { font-size: 12px; color: var(--muted); }
.kpi .value { font-size: 27px; font-weight: 680; letter-spacing: -.02em; margin-top: 3px; }
.kpi .value small { font-size: 13px; color: var(--faint); font-weight: 500; }
.meta-list { display: grid; gap: 8px; }
.meta-row { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; }
.meta-row dt { color: var(--muted); }
.meta-row dd { margin: 0; font-weight: 600; text-align: right; word-break: break-word; }

.bar { height: 6px; border-radius: 999px; background: var(--panel-2); overflow: hidden; border: 1px solid var(--line-soft); }
.bar > span { display: block; height: 100%; background: var(--done); }
.branch { display: grid; gap: 6px; padding: 10px 0; border-bottom: 1px solid var(--line-soft); }
.branch:last-child { border-bottom: 0; }
.branch .line1 { display: flex; justify-content: space-between; gap: 10px; font-size: 13px; }
.branch .line2 { font-size: 12px; color: var(--muted); }

/* ---------- distintivos ---------- */
.badge {
  display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 650;
  padding: 2px 8px; border-radius: 999px; border: 1px solid var(--line); background: var(--panel-2);
  white-space: nowrap;
}
.badge .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.badge.s-pending { color: var(--pending); }
.badge.s-in_progress { color: var(--progress); }
.badge.s-blocked { color: var(--blocked); }
.badge.s-done { color: var(--done); }
.badge.p-low { color: var(--low); } .badge.p-medium { color: var(--medium); }
.badge.p-high { color: var(--high); } .badge.p-critical { color: var(--critical); }
.badge.warn { color: var(--progress); border-color: rgba(240,178,50,.42); }
.tid { font-family: var(--mono); font-size: 12px; color: var(--accent); font-weight: 600; }

/* ---------- filtros ---------- */
.filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; align-items: center; }
input[type="text"], input[type="search"], select, textarea {
  background: var(--panel); border: 1px solid var(--line); color: var(--text);
  border-radius: var(--radius-sm); padding: 7px 10px; font: inherit; outline: none;
}
input:focus, select:focus, textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.filters input[type="search"] { min-width: 240px; flex: 1 1 240px; }
.btn {
  background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius-sm);
  padding: 7px 12px; font-size: 13px; font-weight: 600;
}
.btn:hover { border-color: var(--accent); }
.btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn.primary:hover { filter: brightness(1.08); }
.btn.ghost { background: transparent; }
.btn.tiny { padding: 3px 8px; font-size: 11.5px; }
.btn[disabled] { opacity: .45; cursor: not-allowed; }
.btn[disabled]:hover { border-color: var(--line); }

/* ---------- checklist ---------- */
.tree { display: grid; gap: 7px; }
.node { border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel); }
.node.depth-1 { margin-left: 20px; } .node.depth-2 { margin-left: 40px; }
.node.depth-3 { margin-left: 60px; } .node.depth-4 { margin-left: 80px; }
.node.depth-5 { margin-left: 100px; } .node.depth-6 { margin-left: 116px; }
.node.hit { border-color: var(--accent); }
.row1 { display: flex; align-items: center; gap: 9px; padding: 9px 12px 3px; flex-wrap: wrap; }
.row2 { display: flex; align-items: center; gap: 9px; padding: 0 12px 9px 12px; flex-wrap: wrap;
  font-size: 12px; color: var(--muted); }
.twisty {
  background: none; border: 1px solid var(--line); border-radius: 6px; width: 21px; height: 21px;
  display: grid; place-items: center; font-size: 10px; color: var(--muted); flex: none; padding: 0;
}
.twisty.leaf { visibility: hidden; }
.title { font-weight: 600; flex: 1 1 220px; min-width: 0; }
.seg { display: inline-flex; border: 1px solid var(--line); border-radius: 999px; overflow: hidden; }
.seg button { background: transparent; border: 0; padding: 3px 9px; font-size: 11.5px;
  font-weight: 600; color: var(--muted); border-radius: 0; }
.seg button:hover:not([disabled]) { background: var(--panel-2); color: var(--text); }
.seg button[aria-pressed="true"] { background: var(--accent-soft); color: var(--accent); }
.seg button[disabled] { opacity: .45; cursor: not-allowed; }
.detail { border-top: 1px solid var(--line-soft); padding: 12px; display: grid; gap: 13px; }
.detail[hidden] { display: none; }
.detail h4 { font-size: 11px; text-transform: uppercase; letter-spacing: .07em; color: var(--faint); margin-bottom: 5px; }
.detail p { margin: 0; font-size: 13px; }
.detail ul { margin: 0; padding-left: 18px; font-size: 13px; display: grid; gap: 3px; }
.detail .cols { display: grid; gap: 13px; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); }
.chip { display: inline-block; font-family: var(--mono); font-size: 11.5px; background: var(--panel-2);
  border: 1px solid var(--line-soft); border-radius: 6px; padding: 1px 6px; margin: 2px 3px 0 0; }
.empty { color: var(--muted); font-size: 13px; padding: 26px 16px; text-align: center;
  border: 1px dashed var(--line); border-radius: var(--radius); background: var(--panel); }
.empty strong { display: block; color: var(--text); margin-bottom: 5px; font-size: 14px; }

/* ---------- tablas ---------- */
.table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel); }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--line-soft); vertical-align: top; }
th { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); font-weight: 650;
  position: sticky; top: 0; background: var(--panel-2); }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:hover { background: var(--panel-2); }

/* ---------- grafo ---------- */
.graph-wrap { display: grid; grid-template-columns: minmax(0,1fr) 300px; gap: 14px; align-items: start; }
@media (max-width: 900px) { .graph-wrap { grid-template-columns: minmax(0,1fr); } }
.graph-canvas { border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel);
  overflow: hidden; position: relative; min-height: 460px; }
.graph-canvas svg { display: block; width: 100%; height: 560px; cursor: grab; touch-action: none; }
.graph-canvas svg.dragging { cursor: grabbing; }
.gnode rect { stroke-width: 1.4px; }
.gnode text { font-family: var(--sans); pointer-events: none; }
.gnode { cursor: pointer; }
.glink { fill: none; stroke: var(--line); stroke-width: 1.6px; }
.gdep { fill: none; stroke: var(--progress); stroke-width: 1.4px; stroke-dasharray: 5 4; opacity: .85; }
.graph-tools { position: absolute; right: 10px; top: 10px; display: flex; gap: 6px; }
.legend { display: flex; flex-wrap: wrap; gap: 10px; font-size: 12px; color: var(--muted); margin-top: 10px; }
.legend span { display: inline-flex; align-items: center; gap: 5px; }
.legend i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }

/* ---------- modal ---------- */
.backdrop {
  position: fixed; inset: 0; background: rgba(4,7,12,.68); backdrop-filter: blur(3px);
  display: grid; place-items: center; padding: 22px; z-index: 60;
}
.backdrop[hidden] { display: none; }
.modal {
  background: var(--bg-soft); border: 1px solid var(--line); border-radius: 14px;
  box-shadow: var(--shadow); width: min(880px, 100%); max-height: min(88vh, 900px);
  display: flex; flex-direction: column; overflow: hidden;
}
.modal.narrow { width: min(560px, 100%); }
.modal header {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;
  padding: 15px 17px; border-bottom: 1px solid var(--line);
}
.modal header h2 { font-size: 15px; }
.modal header .sub { color: var(--muted); font-size: 12px; margin-top: 2px; }
.modal .body { padding: 15px 17px; overflow: auto; display: grid; gap: 14px; }
.modal footer { padding: 12px 17px; border-top: 1px solid var(--line);
  display: flex; gap: 9px; justify-content: flex-end; flex-wrap: wrap; }
.x { background: none; border: 1px solid var(--line); border-radius: 8px; width: 28px; height: 28px;
  display: grid; place-items: center; color: var(--muted); flex: none; padding: 0; }
.modal-tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); padding: 0 17px; }
.modal-tabs button { background: none; border: 0; border-bottom: 2px solid transparent;
  padding: 9px 12px; font-size: 13px; font-weight: 600; color: var(--muted); border-radius: 0; }
.modal-tabs button[aria-selected="true"] { color: var(--text); border-bottom-color: var(--accent); }
.field { display: grid; gap: 5px; }
.field label { font-size: 12px; font-weight: 600; color: var(--muted); }
.field .hint { font-size: 11.5px; color: var(--faint); }
.field textarea { min-height: 190px; font-family: var(--mono); font-size: 12.5px; line-height: 1.55;
  resize: vertical; tab-size: 2; white-space: pre; overflow-wrap: normal; overflow-x: auto; }
.field.req label::after { content: " *"; color: var(--blocked); }
.two-col { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }
pre.prompt-text {
  margin: 0; font-family: var(--mono); font-size: 12.5px; line-height: 1.55; white-space: pre-wrap;
  word-break: break-word; background: var(--panel-2); border: 1px solid var(--line);
  border-radius: var(--radius-sm); padding: 12px; max-height: 380px; overflow: auto;
}
.prompt-item { border: 1px solid var(--line); border-radius: var(--radius-sm); padding: 10px 12px;
  display: grid; gap: 7px; background: var(--panel); }
.prompt-item.archived { opacity: .62; }
.prompt-item .pl1 { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.prompt-item .pl2 { font-size: 12px; color: var(--muted); }
.prompt-item .acts { display: flex; gap: 6px; flex-wrap: wrap; }
.toast {
  position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%);
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 10px 16px; font-size: 13px; box-shadow: var(--shadow); z-index: 90; max-width: 90vw;
}
.toast[hidden] { display: none; }
.toast.err { border-color: var(--blocked); color: var(--blocked); }
.toast.ok { border-color: var(--done); color: var(--done); }
.md h2 { font-size: 16px; margin: 18px 0 8px; }
.md h3 { font-size: 14px; margin: 15px 0 6px; }
.md p { margin: 0 0 9px; font-size: 13.5px; }
.md ul { margin: 0 0 10px; padding-left: 19px; font-size: 13.5px; }
.md pre { background: var(--panel-2); border: 1px solid var(--line); border-radius: 8px;
  padding: 11px; overflow: auto; font-family: var(--mono); font-size: 12.5px; margin: 0 0 11px; }
.md code { font-family: var(--mono); font-size: 12.5px; background: var(--panel-2);
  border: 1px solid var(--line-soft); border-radius: 5px; padding: 1px 5px; }
.md pre code { border: 0; background: none; padding: 0; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
"""


# --------------------------------------------------------------------------- #
# Dashboard: aplicación
# --------------------------------------------------------------------------- #

_JS_CORE = r"""
'use strict';
// Ishtar Memory. Todo el contenido se pinta con textContent o createTextNode:
// nunca se interpreta HTML ni se ejecuta JavaScript procedente de los datos.
var BOOT = JSON.parse(document.getElementById('ishtar-data').textContent);
var S = {
  mode: 'read', csrf: null, revision: BOOT.state_revision,
  roadmap: BOOT.roadmap, activity: BOOT.activity, metrics: BOOT.metrics,
  branches: BOOT.branches, config: BOOT.config, docs: BOOT.docs,
  open: {}, tab: 'summary', modalTask: null, modalTab: 'history',
  showArchived: false, filters: {}, selected: null, dirty: false
};
var STATUS = ['pending', 'in_progress', 'blocked', 'done'];
var STATUS_LABEL = { pending: 'Pendiente', in_progress: 'En progreso', blocked: 'Bloqueada', done: 'Realizada' };
var PRIORITY_LABEL = { low: 'Baja', medium: 'Media', high: 'Alta', critical: 'Crítica' };

function el(tag, attrs, kids) {
  var node = document.createElement(tag);
  if (attrs) Object.keys(attrs).forEach(function (k) {
    var v = attrs[k];
    if (v === null || v === undefined || v === false) return;
    if (k === 'text') { node.textContent = String(v); }
    else if (k === 'cls') { node.className = String(v); }
    else if (k === 'on') { Object.keys(v).forEach(function (ev) { node.addEventListener(ev, v[ev]); }); }
    else if (k === 'data') { Object.keys(v).forEach(function (d) { node.dataset[d] = String(v[d]); }); }
    else { node.setAttribute(k, v === true ? '' : String(v)); }
  });
  (kids || []).forEach(function (kid) {
    if (kid === null || kid === undefined || kid === false) return;
    node.appendChild(typeof kid === 'string' ? document.createTextNode(kid) : kid);
  });
  return node;
}
function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
function $(sel) { return document.querySelector(sel); }
function fmtDate(iso) {
  if (!iso) return '—';
  var d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  return d.toLocaleDateString(S.config.locale || 'es-ES') + ' ' +
    d.toLocaleTimeString(S.config.locale || 'es-ES', { hour: '2-digit', minute: '2-digit' });
}
function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

function flatten(tasks, parent, depth, out) {
  out = out || []; depth = depth || 0;
  (tasks || []).forEach(function (t) {
    out.push({ task: t, parent: parent || null, depth: depth });
    flatten(t.children || [], t, depth + 1, out);
  });
  return out;
}
function allTasks() { return flatten(S.roadmap.tasks).map(function (r) { return r.task; }); }
function taskById(id) {
  var found = null;
  allTasks().forEach(function (t) { if (t.id === id) found = t; });
  return found;
}
function activePrompts(task) {
  return (task.prompt_records || []).filter(function (p) { return !p.archived_at; });
}
function statusBadge(status) {
  return el('span', { cls: 'badge s-' + status }, [el('span', { cls: 'dot' }), STATUS_LABEL[status] || status]);
}
function priorityBadge(p) {
  return el('span', { cls: 'badge p-' + p, title: 'Prioridad' }, ['Prioridad ' + (PRIORITY_LABEL[p] || p).toLowerCase()]);
}

/* ---------- avisos ---------- */
var toastTimer = null;
function toast(message, kind) {
  var node = $('#toast');
  node.className = 'toast' + (kind ? ' ' + kind : '');
  node.textContent = message;
  node.hidden = false;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { node.hidden = true; }, kind === 'err' ? 7000 : 3600);
}

/* ---------- API local ---------- */
function api(method, path, body) {
  var headers = { 'Accept': 'application/json' };
  if (body) headers['Content-Type'] = 'application/json';
  if (S.csrf) headers['X-Ishtar-CSRF'] = S.csrf;
  return fetch(path, {
    method: method, headers: headers, credentials: 'same-origin',
    body: body ? JSON.stringify(body) : undefined
  }).then(function (res) {
    return res.json().catch(function () { return { ok: false, error: { code: 'BAD_RESPONSE', message: 'Respuesta ilegible del servidor.' } }; })
      .then(function (data) { return { status: res.status, data: data }; });
  });
}
function applyState(data) {
  if (!data) return;
  if (data.roadmap) S.roadmap = data.roadmap;
  if (data.activity) S.activity = data.activity;
  if (data.metrics) S.metrics = data.metrics;
  if (data.branches) S.branches = data.branches;
  if (typeof data.state_revision === 'number') S.revision = data.state_revision;
  renderAll();
}
function refresh() {
  return api('GET', '/api/bootstrap').then(function (r) {
    if (r.data && r.data.ok) { S.csrf = r.data.csrf_token; applyState(r.data); }
    return r;
  });
}
function write(method, path, body, onOk) {
  body = body || {};
  body.expected_revision = S.revision;
  return api(method, path, body).then(function (r) {
    if (r.data && r.data.ok) {
      applyState(r.data);
      if (onOk) onOk(r.data);
      return r.data;
    }
    var err = (r.data && r.data.error) || { code: 'UNKNOWN', message: 'Error desconocido.' };
    if (err.code === 'REVISION_CONFLICT') {
      refresh().then(function () {
        toast('El estado del proyecto ha cambiado. Datos actualizados: revisa y repite el cambio.', 'err');
      });
      return null;
    }
    var e = new Error(err.message); e.code = err.code; e.meta = err;
    throw e;
  });
}

/* ---------- pestañas ---------- */
function setTab(name) {
  S.tab = name;
  document.querySelectorAll('nav.tabs button').forEach(function (b) {
    b.setAttribute('aria-selected', String(b.dataset.tab === name));
  });
  document.querySelectorAll('section.tab').forEach(function (s) { s.hidden = s.dataset.tab !== name; });
  if (name === 'graph') drawGraph();
}

/* ---------- resumen ---------- */
function kpi(label, value, extra) {
  return el('div', { cls: 'card kpi' }, [
    el('div', { cls: 'label', text: label }),
    el('div', { cls: 'value' }, [String(value), extra ? el('small', { text: ' ' + extra }) : null])
  ]);
}
function renderSummary() {
  var m = S.metrics, host = $('#tab-summary');
  clear(host);
  host.appendChild(el('div', { cls: 'grid kpi' }, [
    kpi('Tareas totales', m.total_tasks, m.total_tasks ? '· ' + plural(m.root_tasks, 'raíz', 'raíces') : ''),
    kpi('Pendientes', m.by_status.pending),
    kpi('En progreso', m.by_status.in_progress),
    kpi('Bloqueadas', m.by_status.blocked),
    kpi('Realizadas', m.by_status.done, m.total_tasks ? '· ' + m.progress_percent + ' %' : ''),
    kpi('Prompts registrados', m.prompts_total, m.prompts_archived ? '· ' + m.prompts_archived + ' arch.' : '')
  ]));

  var facts = el('div', { cls: 'card' }, [el('h3', { text: 'Proyecto' })]);
  var dl = el('dl', { cls: 'meta-list' });
  [
    ['Nombre', S.config.project_name],
    ['Identificador', S.config.project_id],
    ['Prefijo de tareas', S.config.task_prefix],
    ['Revisión del estado', String(m.state_revision)],
    ['Última actualización', fmtDate(m.last_update)],
    ['Tareas sin prompts', String(m.tasks_without_prompts)],
    ['Realizadas manualmente', String(m.completion_overrides)],
    ['Eventos registrados', String(m.activity_events)]
  ].forEach(function (row) {
    dl.appendChild(el('div', { cls: 'meta-row' }, [el('dt', { text: row[0] }), el('dd', { text: row[1] || '—' })]));
  });
  facts.appendChild(dl);

  var branchCard = el('div', { cls: 'card' }, [el('h3', { text: 'Progreso por rama' })]);
  if (!S.branches.length) {
    branchCard.appendChild(el('p', { cls: 'empty', text: 'Todavía no hay ramas registradas.' }));
  } else {
    S.branches.forEach(function (b) {
      branchCard.appendChild(el('div', { cls: 'branch' }, [
        el('div', { cls: 'line1' }, [
          el('span', {}, [el('span', { cls: 'tid', text: b.id }), ' ', b.title]),
          statusBadge(b.status)
        ]),
        el('div', { cls: 'bar' }, [el('span', { style: 'width:' + b.percent + '%' })]),
        el('div', { cls: 'line2', text: 'Estado manual: ' + (STATUS_LABEL[b.status] || b.status) +
          ' · Subtareas realizadas: ' + b.children_done + ' de ' + b.children_total +
          ' · Progreso calculado: ' + b.percent + ' %' })
      ]));
    });
  }

  var recent = el('div', { cls: 'card' }, [el('h3', { text: 'Últimos cambios' })]);
  var last = S.activity.slice(-8).reverse();
  if (!last.length) {
    recent.appendChild(el('p', { cls: 'empty', text: 'Todavía no se han registrado cambios.' }));
  } else {
    last.forEach(function (e) {
      recent.appendChild(el('div', { cls: 'branch' }, [
        el('div', { cls: 'line1' }, [
          el('span', {}, [e.task_id ? el('span', { cls: 'tid', text: e.task_id }) : el('span', { cls: 'tid', text: '—' }), ' ', actionLabel(e.action)]),
          el('span', { cls: 'badge', text: fmtDate(e.timestamp) })
        ])
      ]));
    });
  }
  host.appendChild(el('div', { cls: 'grid two', style: 'margin-top:14px' }, [facts, branchCard]));
  host.appendChild(el('div', { cls: 'grid', style: 'margin-top:14px' }, [recent]));
}

var ACTION_LABEL = {
  task_created: 'Tarea creada', task_updated: 'Tarea actualizada', task_moved: 'Tarea movida',
  task_status_changed: 'Cambio de estado', task_completion_overridden: 'Realizada manualmente',
  prompt_created: 'Prompt añadido', prompt_revised: 'Prompt revisado', prompt_archived: 'Prompt archivado',
  comment_created: 'Comentario añadido', evidence_created: 'Evidencia añadida',
  dashboard_generated: 'Dashboard regenerado'
};
function actionLabel(a) { return ACTION_LABEL[a] || a; }
"""

_JS_CHECKLIST = r"""
/* ---------- checklist ---------- */
function readFilters() {
  return {
    text: ($('#f-text').value || '').trim().toLowerCase(),
    status: $('#f-status').value,
    priority: $('#f-priority').value,
    special: $('#f-special').value
  };
}
function matches(task, f) {
  if (f.status && task.status !== f.status) return false;
  if (f.priority && task.priority !== f.priority) return false;
  if (f.special === 'with_prompts' && !(task.prompt_records || []).length) return false;
  if (f.special === 'without_prompts' && (task.prompt_records || []).length) return false;
  if (f.special === 'blocked' && task.status !== 'blocked') return false;
  if (f.special === 'override' && !task.completion_override) return false;
  if (f.text) {
    var hay = [task.id, task.title, task.description, task.objective].join(' ').toLowerCase();
    if (hay.indexOf(f.text) === -1) return false;
  }
  return true;
}
function visibleSet(f) {
  // Una tarea se muestra si coincide o si alguno de sus descendientes coincide.
  var keep = {};
  function walk(task, ancestors) {
    var self = matches(task, f);
    var kids = (task.children || []).map(function (c) { return walk(c, ancestors.concat([task.id])); });
    var any = self || kids.some(Boolean);
    if (any) { keep[task.id] = true; ancestors.forEach(function (a) { keep[a] = true; }); }
    return any;
  }
  (S.roadmap.tasks || []).forEach(function (t) { walk(t, []); });
  return keep;
}
function segControl(task) {
  var wrap = el('div', { cls: 'seg', role: 'group', 'aria-label': 'Estado de ' + task.id });
  [['pending', 'Pendiente'], ['in_progress', 'En progreso'], ['done', 'Realizada']].forEach(function (pair) {
    wrap.appendChild(el('button', {
      type: 'button', text: pair[1], 'aria-pressed': String(task.status === pair[0]),
      disabled: S.mode !== 'edit', title: S.mode === 'edit' ? 'Marcar como ' + pair[1].toLowerCase() : 'Modo consulta',
      on: { click: function () { requestStatus(task, pair[0]); } }
    }));
  });
  var more = el('button', {
    type: 'button', text: '⋯', 'aria-label': 'Más estados para ' + task.id,
    disabled: S.mode !== 'edit', 'aria-pressed': String(task.status === 'blocked'),
    on: { click: function () { openBlockedDialog(task); } }
  });
  wrap.appendChild(more);
  return wrap;
}
function nodeRow(entry, keep) {
  var task = entry.task;
  var kids = task.children || [];
  var opened = S.open[task.id] !== undefined ? S.open[task.id] : entry.depth < (S.config.default_collapsed_depth || 2);
  var node = el('div', { cls: 'node depth-' + Math.min(entry.depth, 6) + (S.selected === task.id ? ' hit' : ''), id: 'node-' + task.id });

  var twisty = el('button', {
    cls: 'twisty' + (kids.length ? '' : ' leaf'), type: 'button', text: opened ? '▾' : '▸',
    'aria-expanded': String(opened), 'aria-label': (opened ? 'Contraer ' : 'Expandir ') + task.id,
    on: { click: function () { S.open[task.id] = !opened; renderChecklist(); } }
  });
  var doneKids = kids.filter(function (c) { return c.status === 'done'; }).length;
  var criteria = task.acceptance_criteria || [];
  var metCriteria = criteria.filter(function (c) { return c && c.met; }).length;
  var prompts = task.prompt_records || [];

  node.appendChild(el('div', { cls: 'row1' }, [
    twisty,
    el('span', { cls: 'tid', text: task.id }),
    el('span', { cls: 'title', text: task.title }),
    statusBadge(task.status),
    priorityBadge(task.priority),
    task.completion_override ? el('span', { cls: 'badge warn', title: task.completion_override.reason,
      text: 'Realizada manualmente con elementos pendientes' }) : null
  ]));

  var bits = [];
  if (kids.length) bits.push(plural(kids.length, 'subtarea', 'subtareas') + ' · ' + doneKids + '/' + kids.length + ' realizadas');
  if (criteria.length) bits.push(metCriteria + '/' + criteria.length + ' criterios');
  bits.push(plural(prompts.length, 'prompt', 'prompts'));
  bits.push('actualizada ' + fmtDate(task.updated_at));

  var detailOpen = !!S.open['d:' + task.id];
  node.appendChild(el('div', { cls: 'row2' }, [
    el('span', { text: bits.join(' · ') }),
    el('span', { style: 'flex:1' }),
    segControl(task),
    el('button', { cls: 'btn tiny', type: 'button', text: 'Prompts · ' + prompts.length,
      on: { click: function () { openPromptModal(task.id); } } }),
    el('button', { cls: 'btn tiny ghost', type: 'button', text: detailOpen ? 'Ocultar detalle' : 'Ver detalle',
      on: { click: function () { S.open['d:' + task.id] = !detailOpen; renderChecklist(); } } }),
    el('button', { cls: 'btn tiny ghost', type: 'button', text: 'Copiar ID',
      on: { click: function () { copyText(task.id, 'ID copiado: ' + task.id); } } }),
    el('button', { cls: 'btn tiny ghost', type: 'button', text: 'Enfocar rama',
      on: { click: function () { focusBranch(task.id); } } })
  ]));

  if (detailOpen) node.appendChild(taskDetail(task));
  var out = [node];
  if (opened) {
    kids.forEach(function (child) {
      if (keep && !keep[child.id]) return;
      out = out.concat(nodeRow({ task: child, depth: entry.depth + 1 }, keep));
    });
  }
  return out;
}
function listBlock(title, items, mapper) {
  if (!items || !items.length) return null;
  return el('div', {}, [
    el('h4', { text: title }),
    el('ul', {}, items.map(function (i) { return el('li', { text: mapper(i) }); }))
  ]);
}
function taskDetail(task) {
  var d = el('div', { cls: 'detail' });
  if (task.description) d.appendChild(el('div', {}, [el('h4', { text: 'Descripción' }), el('p', { text: task.description })]));
  if (task.objective) d.appendChild(el('div', {}, [el('h4', { text: 'Objetivo' }), el('p', { text: task.objective })]));
  if (task.blocked_reason) d.appendChild(el('div', {}, [el('h4', { text: 'Bloqueo' }), el('p', { text: task.blocked_reason })]));
  if (task.completion_override) {
    d.appendChild(el('div', {}, [el('h4', { text: 'Motivo del cierre manual' }),
      el('p', { text: task.completion_override.reason + ' (' + fmtDate(task.completion_override.created_at) + ')' })]));
  }

  var cols = el('div', { cls: 'cols' });
  var criteria = listBlock('Criterios de aceptación', task.acceptance_criteria, function (c) {
    if (typeof c === 'string') return '• ' + c;
    return (c.met ? '✔ ' : '○ ') + (c.text || c.title || JSON.stringify(c));
  });
  if (criteria) cols.appendChild(criteria);
  var deps = listBlock('Dependencias', task.dependencies, function (x) { return String(x); });
  if (deps) cols.appendChild(deps);
  var comments = listBlock('Comentarios', task.comments, function (c) {
    return typeof c === 'string' ? c : ((c.author ? c.author + ': ' : '') + (c.text || ''));
  });
  if (comments) cols.appendChild(comments);
  var evidence = listBlock('Evidencias', task.evidence, function (e) {
    return typeof e === 'string' ? e : ((e.type ? '[' + e.type + '] ' : '') + (e.path || '') + (e.claim ? ' — ' + e.claim : ''));
  });
  if (evidence) cols.appendChild(evidence);
  var tests = listBlock('Pruebas', task.tests, function (t) {
    return typeof t === 'string' ? t : ((t.command || t.path || '') + (t.result ? ' → ' + t.result : ''));
  });
  if (tests) cols.appendChild(tests);
  if (cols.childNodes.length) d.appendChild(cols);

  if ((task.related_files || []).length) {
    var files = el('div', {}, [el('h4', { text: 'Archivos relacionados' })]);
    task.related_files.forEach(function (f) { files.appendChild(el('span', { cls: 'chip', text: f })); });
    d.appendChild(files);
  }

  var recent = (task.prompt_records || []).slice(-3).reverse();
  var promptBlock = el('div', {}, [el('h4', { text: 'Prompts recientes' })]);
  if (!recent.length) {
    promptBlock.appendChild(el('p', { text: 'Esta tarea todavía no tiene prompts registrados.' }));
  } else {
    recent.forEach(function (p) {
      promptBlock.appendChild(el('div', {}, [
        el('span', { cls: 'chip', text: p.id }), ' ',
        el('span', { text: p.title + ' · ' + fmtDate(p.created_at) + (p.archived_at ? ' · archivado' : '') })
      ]));
    });
  }
  d.appendChild(promptBlock);

  var history = S.activity.filter(function (e) {
    return e.task_id === task.id && e.action === 'task_status_changed';
  }).slice(-6).reverse();
  var hist = el('div', {}, [el('h4', { text: 'Historial de estado' })]);
  if (!history.length) {
    hist.appendChild(el('p', { text: 'Sin cambios de estado registrados.' }));
  } else {
    hist.appendChild(el('ul', {}, history.map(function (e) {
      var from = (e.before && e.before.status) || '—', to = (e.after && e.after.status) || '—';
      return el('li', { text: fmtDate(e.timestamp) + ': ' + (STATUS_LABEL[from] || from) + ' → ' + (STATUS_LABEL[to] || to) });
    })));
  }
  d.appendChild(hist);
  return d;
}
function renderChecklist() {
  var host = $('#tree');
  clear(host);
  var f = readFilters();
  var filtering = !!(f.text || f.status || f.priority || f.special);
  var keep = filtering ? visibleSet(f) : null;
  var roots = (S.roadmap.tasks || []).filter(function (t) { return !keep || keep[t.id]; });

  if (!(S.roadmap.tasks || []).length) {
    host.appendChild(el('div', { cls: 'empty' }, [
      el('strong', { text: 'Todavía no hay tareas registradas.' }),
      el('span', { text: 'El árbol se construirá progresivamente a partir de las instrucciones del usuario.' })
    ]));
    $('#checklist-count').textContent = '';
    return;
  }
  if (!roots.length) {
    host.appendChild(el('div', { cls: 'empty' }, [el('strong', { text: 'Ningún elemento coincide con los filtros.' })]));
  }
  roots.forEach(function (t) {
    nodeRow({ task: t, depth: 0 }, keep).forEach(function (n) { host.appendChild(n); });
  });
  var shown = keep ? Object.keys(keep).length : allTasks().length;
  $('#checklist-count').textContent = shown + ' de ' + allTasks().length + ' elementos';
}
function focusBranch(id) {
  S.selected = id;
  var task = taskById(id);
  S.open[id] = true;
  (function openAncestors(target) {
    flatten(S.roadmap.tasks).forEach(function (row) {
      if (row.task.id === target && row.parent) { S.open[row.parent.id] = true; openAncestors(row.parent.id); }
    });
  })(id);
  if (task) (task.children || []).forEach(function (c) { S.open[c.id] = true; });
  setTab('checklist');
  renderChecklist();
  var node = document.getElementById('node-' + id);
  if (node) node.scrollIntoView({ block: 'center', behavior: 'smooth' });
}
function copyText(text, okMessage) {
  function fallback() {
    var ta = document.createElement('textarea');
    ta.value = text; ta.setAttribute('readonly', '');
    ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    var done = false;
    try { done = document.execCommand('copy'); } catch (e) { done = false; }
    document.body.removeChild(ta);
    toast(done ? okMessage : 'No se pudo copiar automáticamente. Selecciona el texto y cópialo.', done ? 'ok' : 'err');
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(function () { toast(okMessage, 'ok'); }, fallback);
  } else { fallback(); }
}
"""

_JS_MODALS = r"""
/* ---------- diálogos genéricos ---------- */
function closeDialog() {
  var back = $('#dialog-backdrop');
  back.hidden = true;
  clear($('#dialog-host'));
}
function openDialog(opts) {
  var host = $('#dialog-host');
  clear(host);
  var modal = el('div', { cls: 'modal narrow', role: 'dialog', 'aria-modal': 'true', 'aria-label': opts.title });
  modal.appendChild(el('header', {}, [
    el('div', {}, [el('h2', { text: opts.title }), opts.subtitle ? el('div', { cls: 'sub', text: opts.subtitle }) : null]),
    el('button', { cls: 'x', type: 'button', text: '✕', 'aria-label': 'Cerrar', on: { click: closeDialog } })
  ]));
  var body = el('div', { cls: 'body' });
  (opts.body || []).forEach(function (n) { body.appendChild(n); });
  modal.appendChild(body);
  modal.appendChild(el('footer', {}, (opts.actions || []).map(function (a) {
    return el('button', { cls: 'btn' + (a.primary ? ' primary' : ''), type: 'button', text: a.label, on: { click: a.onClick } });
  })));
  host.appendChild(modal);
  $('#dialog-backdrop').hidden = false;
  var first = modal.querySelector('textarea, input, button.primary');
  if (first) first.focus();
}

/* ---------- cambio de estado ---------- */
function requestStatus(task, status) {
  if (S.mode !== 'edit') { toast('Modo consulta: inicia el modo de edición local para guardar cambios.', 'err'); return; }
  if (task.status === status) return;
  write('PATCH', '/api/tasks/' + encodeURIComponent(task.id) + '/status', { status: status }, function () {
    toast(task.id + ' → ' + STATUS_LABEL[status], 'ok');
  }).catch(function (err) {
    if (err.code === 'COMPLETION_REQUIRES_OVERRIDE') { openOverrideDialog(task, err.meta.warnings || []); return; }
    if (err.code === 'BLOCKED_REQUIRES_REASON') { openBlockedDialog(task); return; }
    toast(err.message, 'err');
  });
}
function openOverrideDialog(task, warnings) {
  var reason = el('textarea', { rows: '3', style: 'min-height:80px;font-family:var(--sans);white-space:pre-wrap',
    placeholder: 'Motivo por el que se marca como realizada' });
  openDialog({
    title: 'Esta tarea todavía contiene elementos pendientes',
    subtitle: task.id + ' · ' + task.title,
    body: [
      el('p', { text: 'Puedes cancelar el cambio o marcarla manualmente como realizada indicando un motivo.' }),
      el('ul', {}, warnings.map(function (w) { return el('li', { text: w }); })),
      el('div', { cls: 'field req' }, [el('label', { text: 'Motivo' }), reason])
    ],
    actions: [
      { label: 'Cancelar', onClick: closeDialog },
      { label: 'Marcar como realizada', primary: true, onClick: function () {
        var value = (reason.value || '').trim();
        if (!value) { toast('Indica un motivo para continuar.', 'err'); return; }
        write('PATCH', '/api/tasks/' + encodeURIComponent(task.id) + '/status',
          { status: 'done', override_reason: value }, function () {
            closeDialog(); toast(task.id + ' marcada manualmente como realizada.', 'ok');
          }).catch(function (e) { toast(e.message, 'err'); });
      } }
    ]
  });
}
function openBlockedDialog(task) {
  if (S.mode !== 'edit') { toast('Modo consulta: inicia el modo de edición local para guardar cambios.', 'err'); return; }
  var reason = el('textarea', { rows: '3', style: 'min-height:80px;font-family:var(--sans);white-space:pre-wrap',
    placeholder: 'Motivo del bloqueo' });
  reason.value = task.blocked_reason || '';
  var actions = [{ label: 'Cancelar', onClick: closeDialog }];
  if (task.status === 'blocked') {
    actions.push({ label: 'Quitar bloqueo', onClick: function () {
      write('PATCH', '/api/tasks/' + encodeURIComponent(task.id) + '/status', { status: 'in_progress' }, function () {
        closeDialog(); toast(task.id + ' → En progreso', 'ok');
      }).catch(function (e) { toast(e.message, 'err'); });
    } });
  }
  actions.push({ label: 'Marcar como bloqueada', primary: true, onClick: function () {
    var value = (reason.value || '').trim();
    if (!value) { toast('Indica el motivo del bloqueo.', 'err'); return; }
    write('PATCH', '/api/tasks/' + encodeURIComponent(task.id) + '/status',
      { status: 'blocked', blocked_reason: value }, function () {
        closeDialog(); toast(task.id + ' → Bloqueada', 'ok');
      }).catch(function (e) { toast(e.message, 'err'); });
  } });
  openDialog({ title: 'Bloquear tarea', subtitle: task.id + ' · ' + task.title,
    body: [el('div', { cls: 'field req' }, [el('label', { text: 'Motivo del bloqueo' }), reason,
      el('span', { cls: 'hint', text: 'Una tarea bloqueada sin motivo no supera la validación.' })])],
    actions: actions });
}

/* ---------- modal de prompts ---------- */
function closePromptModal(force) {
  if (S.dirty && !force) {
    if (!window.confirm('Hay cambios sin guardar en el formulario. ¿Cerrar de todos modos?')) return;
  }
  S.dirty = false; S.modalTask = null;
  $('#prompt-backdrop').hidden = true;
  clear($('#prompt-host'));
}
function openPromptModal(taskId, tab) {
  S.modalTask = taskId;
  S.modalTab = tab || 'history';
  S.dirty = false;
  renderPromptModal();
  $('#prompt-backdrop').hidden = false;
}
function renderPromptModal() {
  var task = taskById(S.modalTask);
  if (!task) { closePromptModal(true); return; }
  var host = $('#prompt-host');
  clear(host);
  var modal = el('div', { cls: 'modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Prompts de ' + task.id });
  modal.appendChild(el('header', {}, [
    el('div', {}, [
      el('h2', { text: 'Prompts · ' + task.id }),
      el('div', { cls: 'sub', text: task.title })
    ]),
    el('button', { cls: 'x', type: 'button', text: '✕', 'aria-label': 'Cerrar', on: { click: function () { closePromptModal(); } } })
  ]));
  var tabs = el('div', { cls: 'modal-tabs' });
  [['history', 'Historial'], ['add', 'Añadir prompt']].forEach(function (pair) {
    tabs.appendChild(el('button', {
      type: 'button', text: pair[1], 'aria-selected': String(S.modalTab === pair[0]),
      on: { click: function () {
        if (S.modalTab === 'add' && pair[0] !== 'add' && S.dirty &&
            !window.confirm('Hay cambios sin guardar en el formulario. ¿Continuar?')) return;
        S.dirty = false; S.modalTab = pair[0]; renderPromptModal();
      } }
    }));
  });
  modal.appendChild(tabs);
  var body = el('div', { cls: 'body' });
  if (S.modalTab === 'history') promptHistoryView(body, task);
  else if (S.modalTab === 'add') promptFormView(body, task, null);
  else if (S.modalTab.indexOf('view:') === 0) promptDetailView(body, task, S.modalTab.slice(5));
  else if (S.modalTab.indexOf('edit:') === 0) promptFormView(body, task, S.modalTab.slice(5));
  modal.appendChild(body);
  modal.appendChild(el('footer', {}, [
    el('button', { cls: 'btn ghost', type: 'button', text: 'Cerrar', on: { click: function () { closePromptModal(); } } })
  ]));
  host.appendChild(modal);
}
function promptHistoryView(body, task) {
  var records = (task.prompt_records || []).filter(function (p) { return S.showArchived || !p.archived_at; });
  body.appendChild(el('div', { cls: 'filters' }, [
    el('label', { style: 'display:flex;gap:6px;align-items:center;font-size:13px;color:var(--muted)' }, [
      el('input', { type: 'checkbox', checked: S.showArchived || null,
        on: { change: function (ev) { S.showArchived = ev.target.checked; renderPromptModal(); } } }),
      'Mostrar prompts archivados'
    ]),
    el('span', { style: 'flex:1' }),
    el('button', { cls: 'btn tiny primary', type: 'button', text: 'Añadir prompt',
      on: { click: function () { S.modalTab = 'add'; renderPromptModal(); } } })
  ]));
  if (!records.length) {
    body.appendChild(el('div', { cls: 'empty' }, [
      el('strong', { text: 'Esta tarea todavía no tiene prompts registrados.' })
    ]));
    return;
  }
  records.slice().reverse().forEach(function (p) {
    body.appendChild(el('div', { cls: 'prompt-item' + (p.archived_at ? ' archived' : '') }, [
      el('div', { cls: 'pl1' }, [
        el('span', { cls: 'tid', text: p.id }),
        el('strong', { text: p.title }),
        p.archived_at ? el('span', { cls: 'badge', text: 'Archivado' }) : el('span', { cls: 'badge s-done', text: 'Activo' }),
        (p.revision_history || []).length ? el('span', { cls: 'badge', text: plural(p.revision_history.length, 'revisión', 'revisiones') }) : null
      ]),
      el('div', { cls: 'pl2', text: fmtDate(p.created_at) + (p.tool_or_model ? ' · ' + p.tool_or_model : '') +
        ((p.tags || []).length ? ' · ' + p.tags.join(', ') : '') }),
      el('div', { cls: 'acts' }, [
        el('button', { cls: 'btn tiny', type: 'button', text: 'Ver',
          on: { click: function () { S.modalTab = 'view:' + p.id; renderPromptModal(); } } }),
        el('button', { cls: 'btn tiny', type: 'button', text: 'Copiar',
          on: { click: function () { copyText(p.prompt_text, 'Prompt ' + p.id + ' copiado.'); } } }),
        el('button', { cls: 'btn tiny', type: 'button', text: 'Revisar', disabled: S.mode !== 'edit' || !!p.archived_at,
          on: { click: function () { S.modalTab = 'edit:' + p.id; renderPromptModal(); } } }),
        el('button', { cls: 'btn tiny', type: 'button', text: 'Archivar', disabled: S.mode !== 'edit' || !!p.archived_at,
          on: { click: function () { archivePrompt(task, p); } } })
      ])
    ]));
  });
}
function promptDetailView(body, task, promptId) {
  var p = (task.prompt_records || []).filter(function (r) { return r.id === promptId; })[0];
  if (!p) { S.modalTab = 'history'; renderPromptModal(); return; }
  body.appendChild(el('div', { cls: 'filters' }, [
    el('button', { cls: 'btn tiny ghost', type: 'button', text: '← Volver a la lista',
      on: { click: function () { S.modalTab = 'history'; renderPromptModal(); } } }),
    el('span', { style: 'flex:1' }),
    el('button', { cls: 'btn tiny', type: 'button', text: 'Copiar prompt',
      on: { click: function () { copyText(p.prompt_text, 'Prompt ' + p.id + ' copiado.'); } } })
  ]));
  var dl = el('dl', { cls: 'meta-list' });
  [['ID', p.id], ['Título', p.title], ['Finalidad', p.purpose], ['Herramienta o modelo', p.tool_or_model],
   ['Etiquetas', (p.tags || []).join(', ')], ['Creado', fmtDate(p.created_at)], ['Actualizado', fmtDate(p.updated_at)],
   ['Estado', p.archived_at ? 'Archivado el ' + fmtDate(p.archived_at) : 'Activo'],
   ['Notas', p.notes], ['Resumen del resultado', p.result_summary]
  ].forEach(function (row) {
    if (!row[1]) return;
    dl.appendChild(el('div', { cls: 'meta-row' }, [el('dt', { text: row[0] }), el('dd', { text: row[1] })]));
  });
  body.appendChild(el('div', { cls: 'card' }, [el('h3', { text: 'Metadatos' }), dl]));
  // El texto va en <pre> con textContent: nunca se interpreta como HTML.
  body.appendChild(el('div', {}, [el('h4', { text: 'Texto del prompt' }), el('pre', { cls: 'prompt-text', text: p.prompt_text })]));
  if ((p.related_files || []).length) {
    var files = el('div', {}, [el('h4', { text: 'Archivos relacionados' })]);
    p.related_files.forEach(function (f) { files.appendChild(el('span', { cls: 'chip', text: f })); });
    body.appendChild(files);
  }
  var history = p.revision_history || [];
  var hist = el('div', {}, [el('h4', { text: 'Versiones anteriores (' + history.length + ')' })]);
  if (!history.length) hist.appendChild(el('p', { text: 'Este prompt no tiene revisiones.' }));
  history.slice().reverse().forEach(function (rev) {
    hist.appendChild(el('div', { cls: 'prompt-item' }, [
      el('div', { cls: 'pl2', text: 'Revisión ' + rev.revision + ' · ' + fmtDate(rev.changed_at) +
        (rev.change_reason ? ' · ' + rev.change_reason : '') }),
      el('pre', { cls: 'prompt-text', text: rev.prompt_text })
    ]));
  });
  body.appendChild(hist);
}
function promptFormView(body, task, promptId) {
  var existing = promptId ? (task.prompt_records || []).filter(function (r) { return r.id === promptId; })[0] : null;
  var f = {};
  function field(key, label, opts) {
    opts = opts || {};
    var input = opts.area
      ? el('textarea', { placeholder: opts.placeholder || '', spellcheck: 'false' })
      : el('input', { type: 'text', placeholder: opts.placeholder || '' });
    if (existing) {
      var v = existing[key];
      input.value = Array.isArray(v) ? v.join(', ') : (v || '');
    }
    input.addEventListener('input', function () { S.dirty = true; if (opts.counter) updateCounter(); });
    if (opts.area) {
      input.addEventListener('keydown', function (ev) {
        if (ev.key !== 'Tab') return;           // el textarea admite tabulaciones literales
        ev.preventDefault();
        var start = input.selectionStart, end = input.selectionEnd;
        input.value = input.value.slice(0, start) + '\t' + input.value.slice(end);
        input.selectionStart = input.selectionEnd = start + 1;
        S.dirty = true; if (opts.counter) updateCounter();
      });
    }
    f[key] = input;
    var wrap = el('div', { cls: 'field' + (opts.required ? ' req' : '') }, [
      el('label', { text: label }), input,
      opts.hint ? el('span', { cls: 'hint', text: opts.hint }) : null
    ]);
    return wrap;
  }
  var counter = el('span', { cls: 'hint', text: '0 caracteres' });
  function updateCounter() {
    var value = f.prompt_text.value || '';
    counter.textContent = value.length + ' caracteres · ' + value.split('\n').length + ' líneas';
  }

  body.appendChild(el('div', { cls: 'filters' }, [
    el('button', { cls: 'btn tiny ghost', type: 'button', text: '← Volver a la lista',
      on: { click: function () {
        if (S.dirty && !window.confirm('Hay cambios sin guardar en el formulario. ¿Continuar?')) return;
        S.dirty = false; S.modalTab = 'history'; renderPromptModal();
      } } }),
    el('span', { style: 'flex:1' }),
    el('span', { cls: 'hint', text: existing ? 'Revisando ' + existing.id : 'Nuevo prompt para ' + task.id })
  ]));
  body.appendChild(field('title', 'Título', { required: true, placeholder: 'Título del prompt' }));
  var textField = field('prompt_text', 'Texto completo del prompt', {
    required: true, area: true, counter: true,
    placeholder: 'Pega aquí el texto literal. Se conservan saltos de línea, Markdown y bloques de código.'
  });
  textField.appendChild(counter);
  body.appendChild(textField);
  body.appendChild(el('div', { cls: 'two-col' }, [
    field('purpose', 'Finalidad'),
    field('tool_or_model', 'Herramienta o modelo', { placeholder: 'Codex, Claude, revisión manual…' })
  ]));
  body.appendChild(el('div', { cls: 'two-col' }, [
    field('tags', 'Etiquetas', { hint: 'Separadas por comas' }),
    field('related_files', 'Archivos relacionados', { hint: 'Rutas relativas separadas por comas' })
  ]));
  body.appendChild(field('notes', 'Notas', { area: true }));
  body.appendChild(field('result_summary', 'Resumen del resultado', { area: true }));
  if (existing) body.appendChild(field('change_reason', 'Motivo de la modificación', { hint: 'Se guarda junto a la versión anterior.' }));
  updateCounter();

  var save = el('button', { cls: 'btn primary', type: 'button', disabled: S.mode !== 'edit',
    text: existing ? 'Guardar revisión' : 'Guardar prompt',
    on: { click: function () { submitPrompt(task, existing, f); } } });
  body.appendChild(el('div', { style: 'display:flex;gap:9px;justify-content:flex-end' }, [
    S.mode !== 'edit' ? el('span', { cls: 'hint', text: 'Modo consulta: inicia el modo de edición local para guardar.' }) : null,
    save
  ]));
}
function splitList(value) {
  return (value || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
}
function submitPrompt(task, existing, f) {
  var payload = {
    title: (f.title.value || '').trim(),
    prompt_text: f.prompt_text.value || '',
    purpose: f.purpose.value || '',
    tool_or_model: f.tool_or_model.value || '',
    tags: splitList(f.tags.value),
    notes: f.notes.value || '',
    result_summary: f.result_summary.value || '',
    related_files: splitList(f.related_files.value)
  };
  if (!payload.title) { toast('El prompt necesita un título.', 'err'); f.title.focus(); return; }
  if (!payload.prompt_text.trim()) { toast('El prompt necesita un texto.', 'err'); f.prompt_text.focus(); return; }
  var base = '/api/tasks/' + encodeURIComponent(task.id) + '/prompts';
  var request;
  if (existing) {
    payload.change_reason = (f.change_reason.value || '').trim();
    request = write('PATCH', base + '/' + encodeURIComponent(existing.id), payload);
  } else {
    request = write('POST', base, payload);
  }
  request.then(function (data) {
    if (!data) return;
    S.dirty = false;
    S.modalTab = 'history';
    renderPromptModal();
    toast(existing ? 'Revisión guardada en ' + existing.id : 'Prompt registrado con ID ' + (data.prompt && data.prompt.id), 'ok');
  }).catch(function (e) { toast(e.message, 'err'); });
}
function archivePrompt(task, prompt) {
  if (!window.confirm('¿Archivar ' + prompt.id + '? Se conserva en el roadmap y podrá consultarse con el filtro de archivados.')) return;
  write('POST', '/api/tasks/' + encodeURIComponent(task.id) + '/prompts/' + encodeURIComponent(prompt.id) + '/archive', {},
    function () { renderPromptModal(); toast(prompt.id + ' archivado.', 'ok'); }
  ).catch(function (e) { toast(e.message, 'err'); });
}
"""

_JS_VIEWS = r"""
/* ---------- vista global de prompts ---------- */
function allPromptRows() {
  var rows = [];
  allTasks().forEach(function (task) {
    (task.prompt_records || []).forEach(function (p) { rows.push({ task: task, prompt: p }); });
  });
  return rows.sort(function (a, b) { return String(b.prompt.created_at).localeCompare(String(a.prompt.created_at)); });
}
function renderPrompts() {
  var host = $('#prompts-body');
  clear(host);
  var rows = allPromptRows();
  var taskSel = $('#p-task'), current = taskSel.value;
  clear(taskSel);
  taskSel.appendChild(el('option', { value: '', text: 'Todas las tareas' }));
  allTasks().forEach(function (t) {
    if (!(t.prompt_records || []).length) return;
    taskSel.appendChild(el('option', { value: t.id, text: t.id + ' · ' + t.title }));
  });
  taskSel.value = current || '';

  var text = ($('#p-text').value || '').trim().toLowerCase();
  var tag = ($('#p-tag').value || '').trim().toLowerCase();
  var model = ($('#p-model').value || '').trim().toLowerCase();
  var date = ($('#p-date').value || '').trim();
  var archived = $('#p-archived').value;

  var filtered = rows.filter(function (r) {
    var p = r.prompt;
    if (taskSel.value && r.task.id !== taskSel.value) return false;
    if (archived === 'active' && p.archived_at) return false;
    if (archived === 'archived' && !p.archived_at) return false;
    if (tag && (p.tags || []).join(' ').toLowerCase().indexOf(tag) === -1) return false;
    if (model && String(p.tool_or_model || '').toLowerCase().indexOf(model) === -1) return false;
    if (date && String(p.created_at || '').slice(0, 10) !== date) return false;
    if (text) {
      var hay = [p.id, p.title, p.purpose, p.notes, p.result_summary, p.prompt_text, r.task.title].join(' ').toLowerCase();
      if (hay.indexOf(text) === -1) return false;
    }
    return true;
  });

  $('#prompts-count').textContent = filtered.length + ' de ' + rows.length + ' prompts';
  if (!rows.length) {
    host.appendChild(el('div', { cls: 'empty' }, [
      el('strong', { text: 'Todavía no hay prompts registrados.' }),
      el('span', { text: 'Los prompts se añaden desde el modal de cada tarea en modo edición.' })
    ]));
    return;
  }
  var table = el('table');
  table.appendChild(el('thead', {}, [el('tr', {}, [
    'Prompt', 'Tarea', 'Título', 'Fecha', 'Modelo', 'Etiquetas', 'Estado', 'Rev.', ''
  ].map(function (h) { return el('th', { text: h }); }))]));
  var tbody = el('tbody');
  filtered.forEach(function (r) {
    var p = r.prompt;
    tbody.appendChild(el('tr', {}, [
      el('td', {}, [el('span', { cls: 'tid', text: p.id })]),
      el('td', {}, [el('span', { cls: 'tid', text: r.task.id })]),
      el('td', {}, [el('div', { text: p.title }), el('div', { cls: 'pl2', style: 'color:var(--muted);font-size:12px', text: r.task.title })]),
      el('td', { text: fmtDate(p.created_at) }),
      el('td', { text: p.tool_or_model || '—' }),
      el('td', { text: (p.tags || []).join(', ') || '—' }),
      el('td', {}, [p.archived_at ? el('span', { cls: 'badge', text: 'Archivado' }) : el('span', { cls: 'badge s-done', text: 'Activo' })]),
      el('td', { text: String((p.revision_history || []).length) }),
      el('td', {}, [el('button', { cls: 'btn tiny', type: 'button', text: 'Abrir',
        on: { click: function () { openPromptModal(r.task.id, 'view:' + p.id); } } })])
    ]));
  });
  table.appendChild(tbody);
  host.appendChild(el('div', { cls: 'table-wrap' }, [table]));
}

/* ---------- actividad ---------- */
function renderActivity() {
  var host = $('#activity-body');
  clear(host);
  var filter = $('#a-action').value;
  var events = S.activity.slice().reverse().filter(function (e) { return !filter || e.action === filter; });
  $('#activity-count').textContent = events.length + ' de ' + S.activity.length + ' eventos';
  if (!S.activity.length) {
    host.appendChild(el('div', { cls: 'empty' }, [el('strong', { text: 'Todavía no se han registrado cambios.' })]));
    return;
  }
  var table = el('table');
  table.appendChild(el('thead', {}, [el('tr', {}, ['Evento', 'Fecha', 'Acción', 'Tarea', 'Origen', 'Detalle']
    .map(function (h) { return el('th', { text: h }); }))]));
  var tbody = el('tbody');
  events.forEach(function (e) {
    var detail = [];
    if (e.before && e.before.status) detail.push((STATUS_LABEL[e.before.status] || e.before.status) + ' →');
    if (e.after && e.after.status) detail.push(STATUS_LABEL[e.after.status] || e.after.status);
    if (e.after && e.after.prompt_id) detail.push(e.after.prompt_id + (e.after.title ? ' · ' + e.after.title : ''));
    if (e.after && e.after.reason) detail.push('Motivo: ' + e.after.reason);
    if (e.after && e.after.title && !(e.after.prompt_id)) detail.push(e.after.title);
    tbody.appendChild(el('tr', {}, [
      el('td', {}, [el('span', { cls: 'tid', text: e.event_id })]),
      el('td', { text: fmtDate(e.timestamp) }),
      el('td', { text: actionLabel(e.action) }),
      el('td', {}, [e.task_id ? el('span', { cls: 'tid', text: e.task_id }) : document.createTextNode('—')]),
      el('td', { text: e.source || '—' }),
      el('td', { text: detail.join(' ') || '—' })
    ]));
  });
  table.appendChild(tbody);
  host.appendChild(el('div', { cls: 'table-wrap' }, [table]));
}

/* ---------- grafo / mindmap ---------- */
var GVIEW = { x: 0, y: 0, k: 1 };
var STATUS_FILL = { pending: '#8b98ad', in_progress: '#f0b232', blocked: '#f2555a', done: '#3fb27f' };
function svgEl(name, attrs) {
  var node = document.createElementNS('http://www.w3.org/2000/svg', name);
  Object.keys(attrs || {}).forEach(function (k) {
    if (attrs[k] === null || attrs[k] === undefined) return;
    node.setAttribute(k, String(attrs[k]));
  });
  return node;
}
function layout() {
  var nodes = [], links = [], row = 0;
  function walk(task, depth, parent) {
    var opened = S.open['g:' + task.id] !== false;
    var node = { id: task.id, task: task, depth: depth, y: 0, x: depth * 230 + 30 };
    nodes.push(node);
    var kids = task.children || [];
    if (kids.length && opened) {
      var ys = [];
      kids.forEach(function (child) { ys.push(walk(child, depth + 1, node)); });
      node.y = (ys[0] + ys[ys.length - 1]) / 2;
    } else {
      node.y = row * 52 + 34; row += 1;
    }
    if (parent) links.push({ from: parent, to: node });
    node.collapsed = kids.length && !opened;
    return node.y;
  }
  (S.roadmap.tasks || []).forEach(function (t) { walk(t, 0, null); row += 1; });
  var index = {};
  nodes.forEach(function (n) { index[n.id] = n; });
  var deps = [];
  nodes.forEach(function (n) {
    (n.task.dependencies || []).forEach(function (d) {
      if (index[d]) deps.push({ from: index[d], to: n });
    });
  });
  return { nodes: nodes, links: links, deps: deps, height: row * 52 + 70 };
}
function drawGraph() {
  var host = $('#graph-svg');
  clear(host);
  if (!(S.roadmap.tasks || []).length) {
    $('#graph-empty').hidden = false;
    return;
  }
  $('#graph-empty').hidden = true;
  var g = layout();
  var width = Math.max(900, Math.max.apply(null, g.nodes.map(function (n) { return n.x; })) + 260);
  host.setAttribute('viewBox', '0 0 ' + width + ' ' + Math.max(420, g.height));
  var root = svgEl('g', { transform: 'translate(' + GVIEW.x + ',' + GVIEW.y + ') scale(' + GVIEW.k + ')' });
  host.appendChild(root);

  g.links.forEach(function (l) {
    var x1 = l.from.x + 190, y1 = l.from.y, x2 = l.to.x, y2 = l.to.y, mid = (x1 + x2) / 2;
    root.appendChild(svgEl('path', { class: 'glink', d: 'M' + x1 + ',' + y1 + ' C' + mid + ',' + y1 + ' ' + mid + ',' + y2 + ' ' + x2 + ',' + y2 }));
  });
  g.deps.forEach(function (l) {
    var x1 = l.from.x + 190, y1 = l.from.y + 10, x2 = l.to.x, y2 = l.to.y + 10;
    root.appendChild(svgEl('path', { class: 'gdep', 'marker-end': 'url(#arrow)',
      d: 'M' + x1 + ',' + y1 + ' C' + (x1 + 60) + ',' + (y1 + 34) + ' ' + (x2 - 60) + ',' + (y2 + 34) + ' ' + x2 + ',' + y2 }));
  });
  var defs = svgEl('defs');
  var marker = svgEl('marker', { id: 'arrow', viewBox: '0 0 8 8', refX: '7', refY: '4', markerWidth: '6', markerHeight: '6', orient: 'auto' });
  marker.appendChild(svgEl('path', { d: 'M0,0 L8,4 L0,8 z', fill: '#f0b232' }));
  defs.appendChild(marker);
  host.insertBefore(defs, root);

  g.nodes.forEach(function (n) {
    var task = n.task;
    var group = svgEl('g', { class: 'gnode', tabindex: '0', role: 'button' });
    group.appendChild(svgEl('title')).textContent = task.id + ' · ' + task.title;
    var selected = S.selected === task.id;
    group.appendChild(svgEl('rect', {
      x: n.x, y: n.y - 17, width: 190, height: 36, rx: 9,
      fill: 'var(--panel-2)', stroke: selected ? 'var(--accent)' : 'var(--line)'
    }));
    group.appendChild(svgEl('rect', { x: n.x, y: n.y - 17, width: 4, height: 36, rx: 2, fill: STATUS_FILL[task.status] || '#8b98ad' }));
    var idText = svgEl('text', { x: n.x + 12, y: n.y - 3, 'font-size': '10', fill: 'var(--accent)', 'font-weight': '600' });
    idText.textContent = task.id;
    group.appendChild(idText);
    var titleText = svgEl('text', { x: n.x + 12, y: n.y + 11, 'font-size': '11.5', fill: 'var(--text)' });
    titleText.textContent = task.title.length > 26 ? task.title.slice(0, 25) + '…' : task.title;
    group.appendChild(titleText);
    if (task.blocked_reason) {
      var warn = svgEl('text', { x: n.x + 175, y: n.y + 4, 'font-size': '12', fill: '#f2555a' });
      warn.textContent = '⚠';
      group.appendChild(warn);
    }
    if ((task.children || []).length) {
      var toggle = svgEl('g', { class: 'gnode' });
      toggle.appendChild(svgEl('circle', { cx: n.x + 190, cy: n.y, r: 8, fill: 'var(--panel)', stroke: 'var(--line)' }));
      var sign = svgEl('text', { x: n.x + 190, y: n.y + 4, 'font-size': '11', fill: 'var(--muted)', 'text-anchor': 'middle' });
      sign.textContent = n.collapsed ? '+' : '−';
      toggle.appendChild(sign);
      toggle.addEventListener('click', function (ev) {
        ev.stopPropagation();
        S.open['g:' + task.id] = S.open['g:' + task.id] === false;
        drawGraph();
      });
      group.appendChild(toggle);
    }
    function select() { S.selected = task.id; drawGraph(); renderGraphPanel(task); }
    group.addEventListener('click', select);
    group.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); select(); } });
    root.appendChild(group);
  });
}
function renderGraphPanel(task) {
  var host = $('#graph-panel');
  clear(host);
  if (!task) {
    host.appendChild(el('p', { cls: 'hint', text: 'Selecciona un nodo para ver su información.' }));
    return;
  }
  host.appendChild(el('div', { cls: 'card' }, [
    el('h3', { text: 'Nodo seleccionado' }),
    el('div', { style: 'display:grid;gap:8px' }, [
      el('div', {}, [el('span', { cls: 'tid', text: task.id })]),
      el('strong', { text: task.title }),
      el('div', { style: 'display:flex;gap:6px;flex-wrap:wrap' }, [statusBadge(task.status), priorityBadge(task.priority)]),
      task.blocked_reason ? el('p', { style: 'font-size:12.5px;color:var(--blocked)', text: 'Bloqueo: ' + task.blocked_reason }) : null,
      task.description ? el('p', { style: 'font-size:12.5px;color:var(--muted)', text: task.description }) : null,
      el('div', { style: 'font-size:12px;color:var(--muted)',
        text: plural((task.children || []).length, 'subtarea', 'subtareas') + ' · ' +
              plural((task.prompt_records || []).length, 'prompt', 'prompts') + ' · ' +
              plural((task.dependencies || []).length, 'dependencia', 'dependencias') }),
      segControl(task),
      el('div', { style: 'display:flex;gap:6px;flex-wrap:wrap' }, [
        el('button', { cls: 'btn tiny', type: 'button', text: 'Ir al checklist', on: { click: function () { focusBranch(task.id); } } }),
        el('button', { cls: 'btn tiny', type: 'button', text: 'Prompts · ' + (task.prompt_records || []).length,
          on: { click: function () { openPromptModal(task.id); } } })
      ])
    ])
  ]));
}
function initGraphInteractions() {
  var svg = $('#graph-svg');
  var drag = null;
  svg.addEventListener('pointerdown', function (ev) {
    if (ev.target.closest && ev.target.closest('.gnode')) return;
    drag = { x: ev.clientX, y: ev.clientY, ox: GVIEW.x, oy: GVIEW.y };
    svg.classList.add('dragging'); svg.setPointerCapture(ev.pointerId);
  });
  svg.addEventListener('pointermove', function (ev) {
    if (!drag) return;
    GVIEW.x = drag.ox + (ev.clientX - drag.x); GVIEW.y = drag.oy + (ev.clientY - drag.y);
    var root = svg.querySelector('g:not(defs g)');
    if (root) root.setAttribute('transform', 'translate(' + GVIEW.x + ',' + GVIEW.y + ') scale(' + GVIEW.k + ')');
  });
  ['pointerup', 'pointercancel', 'pointerleave'].forEach(function (name) {
    svg.addEventListener(name, function () { drag = null; svg.classList.remove('dragging'); });
  });
  $('#g-in').addEventListener('click', function () { GVIEW.k = Math.min(2.4, GVIEW.k * 1.2); drawGraph(); });
  $('#g-out').addEventListener('click', function () { GVIEW.k = Math.max(0.35, GVIEW.k / 1.2); drawGraph(); });
  $('#g-reset').addEventListener('click', function () { GVIEW = { x: 0, y: 0, k: 1 }; drawGraph(); });
}

/* ---------- documentos ---------- */
function renderMarkdown(text, host) {
  clear(host);
  if (!text || !text.trim()) {
    host.appendChild(el('div', { cls: 'empty' }, [el('strong', { text: 'Documento vacío.' })]));
    return;
  }
  var lines = text.split('\n'), buffer = [], listItems = [], inCode = false, codeLines = [];
  function flushParagraph() {
    if (!buffer.length) return;
    host.appendChild(el('p', { text: buffer.join(' ') }));
    buffer = [];
  }
  function flushList() {
    if (!listItems.length) return;
    host.appendChild(el('ul', {}, listItems.map(function (i) { return el('li', { text: i }); })));
    listItems = [];
  }
  lines.forEach(function (raw) {
    var line = raw.replace(/\s+$/, '');
    if (line.trim().indexOf('```') === 0) {
      if (inCode) {
        host.appendChild(el('pre', {}, [el('code', { text: codeLines.join('\n') })]));
        codeLines = []; inCode = false;
      } else { flushParagraph(); flushList(); inCode = true; }
      return;
    }
    if (inCode) { codeLines.push(raw); return; }
    var heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flushParagraph(); flushList();
      var level = Math.min(4, Math.max(2, heading[1].length));
      host.appendChild(el('h' + level, { text: heading[2] }));
      return;
    }
    var item = /^\s*[-*+]\s+(.*)$/.exec(line) || /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (item) { flushParagraph(); listItems.push(item[1]); return; }
    if (!line.trim()) { flushParagraph(); flushList(); return; }
    buffer.push(line.trim());
  });
  if (inCode) host.appendChild(el('pre', {}, [el('code', { text: codeLines.join('\n') })]));
  flushParagraph(); flushList();
}

/* ---------- arranque ---------- */
function renderAll() {
  renderSummary();
  renderChecklist();
  renderPrompts();
  renderActivity();
  if (S.tab === 'graph') drawGraph();
  if (S.modalTask && !$('#prompt-backdrop').hidden) renderPromptModal();
  document.querySelectorAll('nav.tabs .count').forEach(function (node) {
    var key = node.dataset.count;
    if (key === 'checklist') node.textContent = String(S.metrics.total_tasks);
    if (key === 'prompts') node.textContent = String(S.metrics.prompts_total);
    if (key === 'activity') node.textContent = String(S.metrics.activity_events);
  });
}
function setMode(mode) {
  S.mode = mode;
  var badge = $('#mode-badge');
  badge.className = 'mode-badge' + (mode === 'edit' ? ' edit' : '');
  clear(badge);
  badge.appendChild(el('span', { cls: 'dot' }));
  badge.appendChild(document.createTextNode(mode === 'edit' ? 'Modo edición' : 'Modo consulta'));
  $('#mode-note').hidden = mode === 'edit';
  $('#btn-refresh').hidden = mode !== 'edit';
}
function boot() {
  document.querySelectorAll('nav.tabs button').forEach(function (b) {
    b.addEventListener('click', function () { setTab(b.dataset.tab); });
  });
  ['f-text', 'f-status', 'f-priority', 'f-special'].forEach(function (id) {
    var node = document.getElementById(id);
    node.addEventListener('input', renderChecklist);
    node.addEventListener('change', renderChecklist);
  });
  ['p-text', 'p-task', 'p-tag', 'p-model', 'p-date', 'p-archived'].forEach(function (id) {
    var node = document.getElementById(id);
    node.addEventListener('input', renderPrompts);
    node.addEventListener('change', renderPrompts);
  });
  $('#a-action').addEventListener('change', renderActivity);
  $('#f-clear').addEventListener('click', function () {
    ['f-text', 'f-status', 'f-priority', 'f-special'].forEach(function (id) { document.getElementById(id).value = ''; });
    renderChecklist();
  });
  $('#f-expand').addEventListener('click', function () {
    allTasks().forEach(function (t) { S.open[t.id] = true; }); renderChecklist();
  });
  $('#f-collapse').addEventListener('click', function () {
    allTasks().forEach(function (t) { S.open[t.id] = false; }); renderChecklist();
  });
  $('#btn-refresh').addEventListener('click', function () {
    refresh().then(function () { toast('Datos actualizados.', 'ok'); });
  });
  $('#prompt-backdrop').addEventListener('click', function (ev) { if (ev.target === ev.currentTarget) closePromptModal(); });
  $('#dialog-backdrop').addEventListener('click', function (ev) { if (ev.target === ev.currentTarget) closeDialog(); });
  document.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Escape') return;
    if (!$('#dialog-backdrop').hidden) closeDialog();
    else if (!$('#prompt-backdrop').hidden) closePromptModal();
  });
  window.addEventListener('beforeunload', function (ev) {
    if (S.dirty) { ev.preventDefault(); ev.returnValue = ''; }
  });
  initGraphInteractions();
  renderMarkdown(S.docs.decisions, $('#doc-decisions'));
  renderMarkdown(S.docs.architecture, $('#doc-architecture'));
  renderMarkdown(S.docs.progress, $('#doc-progress'));
  renderGraphPanel(null);
  setMode('read');
  renderAll();
  setTab('summary');

  if (location.protocol === 'http:' || location.protocol === 'https:') {
    refresh().then(function (r) {
      if (r && r.data && r.data.ok && r.data.mode === 'edit') { setMode('edit'); renderAll(); }
    }).catch(function () { /* sin servidor local: se mantiene el modo consulta */ });
  }
}
document.addEventListener('DOMContentLoaded', boot);
"""

_HTML = r"""<!DOCTYPE html>
<html lang="__LOCALE__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>__TITLE__</title>
<style>__CSS__</style>
</head>
<body>
<div class="shell">
  <header class="top">
    <div class="brand">
      <div class="sigil" aria-hidden="true">IM</div>
      <div>
        <h1>__TITLE__</h1>
        <div class="sub">Ishtar Memory · __PROJECT__</div>
      </div>
    </div>
    <div class="head-right">
      <button class="btn" id="btn-refresh" type="button" hidden>Actualizar datos</button>
      <span class="mode-badge" id="mode-badge"><span class="dot"></span>Modo consulta</span>
    </div>
  </header>

  <div class="mode-note" id="mode-note">
    <strong>Modo consulta.</strong> Para guardar cambios en el proyecto, inicia el modo de edición local:
    <code>python scripts/ishtar_memory.py serve</code> y abre <code>http://127.0.0.1:__PORT__</code>.
  </div>

  <nav class="tabs" role="tablist">
    <button type="button" role="tab" data-tab="summary" aria-selected="true">Resumen</button>
    <button type="button" role="tab" data-tab="checklist" aria-selected="false">Checklist<span class="count" data-count="checklist">0</span></button>
    <button type="button" role="tab" data-tab="graph" aria-selected="false">Grafo</button>
    <button type="button" role="tab" data-tab="prompts" aria-selected="false">Prompts<span class="count" data-count="prompts">0</span></button>
    <button type="button" role="tab" data-tab="activity" aria-selected="false">Actividad<span class="count" data-count="activity">0</span></button>
    <button type="button" role="tab" data-tab="decisions" aria-selected="false">Decisiones</button>
    <button type="button" role="tab" data-tab="architecture" aria-selected="false">Arquitectura</button>
  </nav>

  <section class="tab" data-tab="summary" role="tabpanel">
    <div id="tab-summary"></div>
    <div class="card" style="margin-top:14px">
      <h3>Progreso registrado</h3>
      <div class="md" id="doc-progress"></div>
    </div>
  </section>

  <section class="tab" data-tab="checklist" role="tabpanel" hidden>
    <div class="filters">
      <input type="search" id="f-text" placeholder="Buscar por texto o ID" aria-label="Buscar tareas">
      <select id="f-status" aria-label="Filtrar por estado">
        <option value="">Todos los estados</option>
        <option value="pending">Pendiente</option>
        <option value="in_progress">En progreso</option>
        <option value="blocked">Bloqueada</option>
        <option value="done">Realizada</option>
      </select>
      <select id="f-priority" aria-label="Filtrar por prioridad">
        <option value="">Todas las prioridades</option>
        <option value="low">Baja</option>
        <option value="medium">Media</option>
        <option value="high">Alta</option>
        <option value="critical">Crítica</option>
      </select>
      <select id="f-special" aria-label="Filtros especiales">
        <option value="">Sin filtro adicional</option>
        <option value="with_prompts">Con prompts</option>
        <option value="without_prompts">Sin prompts</option>
        <option value="blocked">Bloqueadas</option>
        <option value="override">Con override de finalización</option>
      </select>
      <button class="btn" id="f-clear" type="button">Limpiar</button>
      <button class="btn" id="f-expand" type="button">Expandir</button>
      <button class="btn" id="f-collapse" type="button">Contraer</button>
      <span class="sub" id="checklist-count" style="color:var(--muted);font-size:12px"></span>
    </div>
    <div class="tree" id="tree"></div>
  </section>

  <section class="tab" data-tab="graph" role="tabpanel" hidden>
    <div class="graph-wrap">
      <div>
        <div class="graph-canvas">
          <div class="graph-tools">
            <button class="btn tiny" id="g-out" type="button" aria-label="Alejar">−</button>
            <button class="btn tiny" id="g-in" type="button" aria-label="Acercar">+</button>
            <button class="btn tiny" id="g-reset" type="button">Centrar</button>
          </div>
          <svg id="graph-svg" role="img" aria-label="Mapa jerárquico de tareas"></svg>
          <div class="empty" id="graph-empty" style="position:absolute;inset:auto 0 0 0;top:40%;border:0;background:none" hidden>
            <strong>Todavía no hay tareas registradas.</strong>
            <span>El árbol se construirá progresivamente a partir de las instrucciones del usuario.</span>
          </div>
        </div>
        <div class="legend">
          <span><i style="background:#8b98ad"></i>Pendiente</span>
          <span><i style="background:#f0b232"></i>En progreso</span>
          <span><i style="background:#f2555a"></i>Bloqueada</span>
          <span><i style="background:#3fb27f"></i>Realizada</span>
          <span><i style="background:#f0b232;border-radius:0;height:2px;width:16px"></i>Dependencia</span>
        </div>
      </div>
      <div id="graph-panel"></div>
    </div>
  </section>

  <section class="tab" data-tab="prompts" role="tabpanel" hidden>
    <div class="filters">
      <input type="search" id="p-text" placeholder="Buscar en prompts" aria-label="Buscar prompts">
      <select id="p-task" aria-label="Filtrar por tarea"><option value="">Todas las tareas</option></select>
      <input type="text" id="p-tag" placeholder="Etiqueta" aria-label="Filtrar por etiqueta" style="max-width:150px">
      <input type="text" id="p-model" placeholder="Modelo" aria-label="Filtrar por modelo" style="max-width:150px">
      <input type="text" id="p-date" placeholder="AAAA-MM-DD" aria-label="Filtrar por fecha" style="max-width:130px">
      <select id="p-archived" aria-label="Filtrar por estado de archivado">
        <option value="active">Solo activos</option>
        <option value="">Activos y archivados</option>
        <option value="archived">Solo archivados</option>
      </select>
      <span id="prompts-count" style="color:var(--muted);font-size:12px"></span>
    </div>
    <div id="prompts-body"></div>
  </section>

  <section class="tab" data-tab="activity" role="tabpanel" hidden>
    <div class="filters">
      <select id="a-action" aria-label="Filtrar por acción">
        <option value="">Todas las acciones</option>
        <option value="task_created">Tarea creada</option>
        <option value="task_updated">Tarea actualizada</option>
        <option value="task_moved">Tarea movida</option>
        <option value="task_status_changed">Cambio de estado</option>
        <option value="task_completion_overridden">Realizada manualmente</option>
        <option value="prompt_created">Prompt añadido</option>
        <option value="prompt_revised">Prompt revisado</option>
        <option value="prompt_archived">Prompt archivado</option>
        <option value="comment_created">Comentario añadido</option>
        <option value="evidence_created">Evidencia añadida</option>
        <option value="dashboard_generated">Dashboard regenerado</option>
      </select>
      <span id="activity-count" style="color:var(--muted);font-size:12px"></span>
    </div>
    <div id="activity-body"></div>
  </section>

  <section class="tab" data-tab="decisions" role="tabpanel" hidden>
    <div class="card md" id="doc-decisions"></div>
  </section>

  <section class="tab" data-tab="architecture" role="tabpanel" hidden>
    <div class="card md" id="doc-architecture"></div>
  </section>
</div>

<div class="backdrop" id="prompt-backdrop" hidden><div id="prompt-host"></div></div>
<div class="backdrop" id="dialog-backdrop" hidden><div id="dialog-host"></div></div>
<div class="toast" id="toast" role="status" aria-live="polite" hidden></div>

<script type="application/json" id="ishtar-data">__PAYLOAD__</script>
<script>__JS__</script>
</body>
</html>
"""


def embed_json(data: Any) -> str:
    """Serializa para un <script type="application/json"> sin poder cerrar la etiqueta."""
    text = json.dumps(data, ensure_ascii=False, sort_keys=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def read_doc(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def build_payload(
    paths: Paths,
    config: dict[str, Any],
    roadmap: dict[str, Any],
    activity: list[dict[str, Any]],
) -> dict[str, Any]:
    project = config.get("project") or {}
    ui = config.get("ui") or {}
    return {
        "state_revision": roadmap.get("state_revision"),
        "config": {
            "project_id": project.get("id"),
            "project_name": project.get("name"),
            "task_prefix": project.get("task_prefix"),
            "locale": ui.get("locale", "es-ES"),
            "default_collapsed_depth": ui.get("default_collapsed_depth", 2),
        },
        "roadmap": roadmap,
        "activity": activity[-ACTIVITY_EMBED_LIMIT:],
        "metrics": compute_metrics(roadmap, activity),
        "branches": branch_progress(roadmap),
        "docs": {
            "decisions": read_doc(paths.decisions),
            "architecture": read_doc(paths.architecture),
            "progress": read_doc(paths.progress),
        },
    }


def render_dashboard(
    paths: Paths,
    config: dict[str, Any],
    roadmap: dict[str, Any],
    activity: list[dict[str, Any]],
    *,
    port: int = DEFAULT_PORT,
) -> str:
    """Genera el HTML autónomo. Determinista para unos mismos datos de entrada."""
    project = config.get("project") or {}
    ui = config.get("ui") or {}
    title = str(ui.get("dashboard_title") or "Development Command Center")
    javascript = "\n".join([_JS_CORE, _JS_CHECKLIST, _JS_MODALS, _JS_VIEWS])
    payload = build_payload(paths, config, roadmap, activity)
    def esc(value: Any) -> str:
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    html = _HTML
    html = html.replace("__LOCALE__", esc(str(ui.get("locale") or "es-ES").split("-")[0]))
    html = html.replace("__TITLE__", esc(title))
    html = html.replace("__PROJECT__", esc(project.get("name") or project.get("id") or "Proyecto"))
    html = html.replace("__PORT__", str(int(port)))
    # CSS y JS se sustituyen antes que el payload: los datos nunca deben poder
    # ocupar el lugar de una plantilla.
    html = html.replace("__CSS__", _CSS)
    html = html.replace("__JS__", javascript)
    html = html.replace("__PAYLOAD__", embed_json(payload))
    return html


def generate_dashboard(paths: Paths, *, port: int = DEFAULT_PORT, record: bool = True) -> str:
    """Valida, registra la generación y escribe el HTML de forma atómica."""
    config = load_config(paths)
    roadmap = load_roadmap(paths)
    activity = read_activity(paths)
    report = validate(config, roadmap, activity)
    if not report.ok:
        raise IshtarError(
            "VALIDATION_ERROR",
            "La validación no pasa: no se sobrescribe el HTML anterior.",
            status=422,
            errors=[issue.message for issue in report.errors],
        )
    if record:
        append_activity(
            paths,
            action="dashboard_generated",
            source="cli",
            metadata={"tasks": len(all_tasks(roadmap))},
            roadmap=None,
        )
        activity = read_activity(paths)
    html = render_dashboard(paths, config, roadmap, activity, port=port)
    atomic_write_text(paths.dashboard, html)
    return html


# --------------------------------------------------------------------------- #
# Servidor local
# --------------------------------------------------------------------------- #


def _api_state(paths: Paths, roadmap: dict[str, Any]) -> dict[str, Any]:
    activity = read_activity(paths)
    return {
        "state_revision": roadmap.get("state_revision"),
        "roadmap": roadmap,
        "activity": activity[-ACTIVITY_EMBED_LIMIT:],
        "metrics": compute_metrics(roadmap, activity),
        "branches": branch_progress(roadmap),
    }


def build_server(paths: Paths, port: int):  # noqa: C901 - enrutado explícito
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    csrf_token = secrets.token_urlsafe(32)
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost"}
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def regenerate(roadmap: dict[str, Any]) -> None:
        config = load_config(paths)
        activity = read_activity(paths)
        html = render_dashboard(paths, config, roadmap, activity, port=port)
        atomic_write_text(paths.dashboard, html)

    class Handler(BaseHTTPRequestHandler):
        server_version = "IshtarMemory/1.0"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("  %s %s\n" % (self.address_string(), fmt % args))

        # -- utilidades de respuesta -------------------------------------- #
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                "img-src data:; connect-src 'self'; form-action 'none'; base-uri 'none'",
            )
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _fail(self, error: IshtarError) -> None:
            payload: dict[str, Any] = {
                "ok": False,
                "error": {"code": error.code, "message": error.message},
            }
            payload["error"].update(error.metadata)
            self._json(error.status, payload)

        def _ok(self, extra: dict[str, Any] | None = None) -> None:
            roadmap = load_roadmap(paths)
            payload: dict[str, Any] = {"ok": True, "mode": "edit"}
            payload.update(_api_state(paths, roadmap))
            if extra:
                payload.update(extra)
            self._json(200, payload)

        # -- seguridad ---------------------------------------------------- #
        def _check_host(self) -> None:
            host = (self.headers.get("Host") or "").strip().lower()
            if host not in allowed_hosts:
                raise IshtarError("FORBIDDEN_HOST", "Host no permitido.", status=403)

        def _check_write(self) -> None:
            origin = (self.headers.get("Origin") or "").strip()
            if origin and origin not in allowed_origins:
                raise IshtarError("FORBIDDEN_ORIGIN", "Origen no permitido.", status=403)
            referer = (self.headers.get("Referer") or "").strip()
            if referer and not any(referer.startswith(o) for o in allowed_origins):
                raise IshtarError("FORBIDDEN_ORIGIN", "Referer no permitido.", status=403)
            token = self.headers.get("X-Ishtar-CSRF") or ""
            if not hmac.compare_digest(token, csrf_token):
                raise IshtarError("INVALID_CSRF", "Token CSRF ausente o incorrecto.", status=403)

        def _body(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise IshtarError("VALIDATION_ERROR", "Content-Length inválido.", status=400) from None
            if length > MAX_REQUEST_BYTES:
                # Se drena una cantidad acotada para poder responder 413 limpiamente
                # en lugar de cortar la conexión mientras el cliente sigue enviando.
                remaining = min(length, MAX_REQUEST_BYTES * 8)
                while remaining > 0:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                self.close_connection = True
                raise IshtarError(
                    "PAYLOAD_TOO_LARGE",
                    f"La petición supera el máximo de {MAX_REQUEST_BYTES} bytes.",
                    status=413,
                )
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise IshtarError("VALIDATION_ERROR", "El cuerpo no es JSON válido.", status=400) from None
            if not isinstance(data, dict):
                raise IshtarError("VALIDATION_ERROR", "El cuerpo debe ser un objeto JSON.", status=400)
            return data

        # -- enrutado ----------------------------------------------------- #
        def _route(self) -> None:
            path = self.path.split("?", 1)[0]
            if not path.startswith("/api/") and self.command in ("GET", "HEAD"):
                self._serve_page(path)
                return
            segments = [segment for segment in path.split("/") if segment]
            if segments[:1] != ["api"]:
                raise IshtarError("NOT_FOUND", "Ruta desconocida.", status=404)
            rest = segments[1:]

            if self.command in ("GET", "HEAD"):
                if rest == ["bootstrap"]:
                    self._ok({"csrf_token": csrf_token, "config": build_payload(
                        paths, load_config(paths), load_roadmap(paths), read_activity(paths))["config"]})
                    return
                if rest == ["activity"]:
                    self._json(200, {"ok": True, "activity": read_activity(paths)})
                    return
                if len(rest) == 2 and rest[0] == "tasks":
                    self._json(200, {"ok": True, "task": find_task(load_roadmap(paths), rest[1])})
                    return
                if len(rest) == 3 and rest[0] == "tasks" and rest[2] == "prompts":
                    task = find_task(load_roadmap(paths), rest[1])
                    self._json(200, {"ok": True, "prompts": task.get("prompt_records") or []})
                    return
                raise IshtarError("NOT_FOUND", "Ruta desconocida.", status=404)

            self._check_write()
            body = self._body()

            if self.command == "PATCH" and len(rest) == 3 and rest[0] == "tasks" and rest[2] == "status":
                self._mutate(rest[1], body, lambda tx, task_id: op_set_status(
                    tx, task_id, str(body.get("status") or ""),
                    override_reason=body.get("override_reason"),
                    blocked_reason=body.get("blocked_reason"),
                ), key="task")
                return
            if self.command == "POST" and len(rest) == 3 and rest[0] == "tasks" and rest[2] == "prompts":
                self._mutate(rest[1], body, lambda tx, task_id: op_add_prompt(tx, task_id, body), key="prompt")
                return
            if self.command == "PATCH" and len(rest) == 4 and rest[0] == "tasks" and rest[2] == "prompts":
                self._mutate(rest[1], body, lambda tx, task_id: op_revise_prompt(tx, task_id, rest[3], body), key="prompt")
                return
            if (self.command == "POST" and len(rest) == 5 and rest[0] == "tasks"
                    and rest[2] == "prompts" and rest[4] == "archive"):
                self._mutate(rest[1], body, lambda tx, task_id: op_archive_prompt(tx, task_id, rest[3]), key="prompt")
                return
            raise IshtarError("NOT_FOUND", "Ruta desconocida.", status=404)

        def _mutate(self, task_id: str, body: dict[str, Any], operation: Any, *, key: str) -> None:
            with Transaction(paths, source="dashboard") as tx:
                check_revision(tx.roadmap, body.get("expected_revision"))
                result = operation(tx, task_id)
                roadmap = tx.commit()
            regenerate(roadmap)
            task = find_task(roadmap, task_id)
            extra = {"task": task}
            if key == "prompt":
                extra["prompt"] = result
            self._ok(extra)

        def _serve_page(self, path: str) -> None:
            if path in ("/", "/index.html", "/dashboard.html"):
                if not paths.dashboard.exists():
                    generate_dashboard(paths, port=port, record=False)
                body = paths.dashboard.read_bytes()
                self._send(200, body, "text/html; charset=utf-8")
                return
            # No se sirve ninguna otra ruta del sistema de archivos.
            raise IshtarError("NOT_FOUND", "Ruta desconocida.", status=404)

        def _dispatch(self) -> None:
            try:
                self._check_host()
                self._route()
            except IshtarError as error:
                self._fail(error)
            except Exception as error:  # pragma: no cover - salvaguarda del servidor
                self._fail(IshtarError("INTERNAL_ERROR", str(error), status=500))

        do_GET = _dispatch
        do_HEAD = _dispatch
        do_POST = _dispatch
        do_PATCH = _dispatch

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return httpd, csrf_token


def serve(paths: Paths, port: int = DEFAULT_PORT) -> None:
    generate_dashboard(paths, port=port, record=False)
    httpd, _token = build_server(paths, port)
    url = f"http://127.0.0.1:{port}"
    print(f"Ishtar Memory · modo edición en {url}")
    print("Escuchando solo en 127.0.0.1. Ctrl+C para detener.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        httpd.server_close()


# --------------------------------------------------------------------------- #
# Migración desde versiones anteriores
# --------------------------------------------------------------------------- #

LEGACY_FILES = [
    "oracle-roadmap.json",
    "oracle-development-dashboard.html",
    "oracle-progress.md",
    "oracle-decisions.md",
    "oracle-architecture.md",
]

LEGACY_STATUS_MAP = {
    "idea": "pending",
    "proposed": "pending",
    "needs_definition": "pending",
    "approved": "pending",
    "ready": "pending",
    "deferred": "pending",
    "rejected": "pending",
    "in_progress": "in_progress",
    "under_review": "in_progress",
    "blocked": "blocked",
    "implemented": "done",
    "validated": "done",
    "deployed": "done",
}
LEGACY_PRIORITY_MAP = {"P0": "critical", "P1": "high", "P2": "medium", "P3": "low"}


def detect_legacy(root: Path) -> list[Path]:
    """Localiza artefactos de versiones anteriores sin modificarlos."""
    found: list[Path] = []
    for directory in (root / "docs" / "development", root / "docs", root):
        for name in LEGACY_FILES:
            candidate = directory / name
            if candidate.exists() and candidate not in found:
                found.append(candidate)
    return found


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    return list(value) if isinstance(value, list) else [value]


def _legacy_to_task(item: dict[str, Any], parent_id: str | None, stamp: str) -> dict[str, Any]:
    raw_status = str(item.get("status") or item.get("state") or "idea")
    status = LEGACY_STATUS_MAP.get(raw_status, "pending")
    blockers = [str(b) for b in _as_list(item.get("blockers")) if str(b).strip()]
    if status == "blocked" and not blockers:
        blockers = ["Bloqueo heredado de la versión anterior sin motivo registrado."]

    task = new_task(
        str(item.get("id")),
        str(item.get("title") or item.get("name") or item.get("id")),
        parent_id=parent_id,
        description=str(item.get("description") or ""),
        objective=str(item.get("business_objective") or item.get("readiness") or ""),
        priority=LEGACY_PRIORITY_MAP.get(str(item.get("priority") or ""), "medium"),
    )
    task["status"] = status
    task["blocked_reason"] = blockers[0] if status == "blocked" else None
    task["dependencies"] = [str(d) for d in _as_list(item.get("dependencies"))]
    task["acceptance_criteria"] = [
        {"text": str(c), "met": status == "done"} for c in _as_list(item.get("acceptance_criteria"))
    ]
    comments = _as_list(item.get("comments"))
    task["comments"] = [
        c if isinstance(c, dict) else {"text": str(c), "author": "migración", "created_at": stamp}
        for c in comments
        if str(c).strip()
    ]
    task["evidence"] = [e for e in _as_list(item.get("implementation_evidence")) if e]
    task["related_files"] = [
        str(f) for f in _as_list(item.get("related_files")) if not UNSAFE_PATH_RE.search(str(f))
    ]
    task["tests"] = [
        {"command": str(t), "result": "passed" if status == "done" else None}
        for t in _as_list(item.get("related_tests"))
    ]
    task["prompt_records"] = []
    created = item.get("created_at")
    updated = item.get("updated_at")
    task["created_at"] = created if _valid_iso(created) else stamp
    task["updated_at"] = updated if _valid_iso(updated) else stamp
    completed = item.get("completed_at")
    task["completed_at"] = (completed if _valid_iso(completed) else stamp) if status == "done" else None
    return task


def migrate(paths: Paths, *, apply: bool) -> dict[str, Any]:
    """Migra un roadmap heredado sin sobrescribir ni borrar los archivos previos."""
    legacy_roadmap = paths.root / "docs" / "development" / "oracle-roadmap.json"
    if not legacy_roadmap.exists():
        raise IshtarError("FILE_NOT_FOUND", "No se encontró docs/development/oracle-roadmap.json.", status=404)

    legacy = read_json(legacy_roadmap)
    stamp = now_iso()
    modules = _as_list(legacy.get("modules"))
    features = _as_list(legacy.get("features"))

    tasks: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    for module in modules:
        task = _legacy_to_task(module, None, stamp)
        tasks.append(task)
        index[task["id"]] = task
    orphans: list[dict[str, Any]] = []
    for feature in features:
        parent_id = str(feature.get("module_id") or "")
        parent = index.get(parent_id)
        task = _legacy_to_task(feature, parent["id"] if parent else None, stamp)
        index[task["id"]] = task
        if parent:
            parent["children"].append(task)
        else:
            orphans.append(task)
    tasks.extend(orphans)

    for edge in _as_list(legacy.get("dependencies")):
        target = index.get(str(edge.get("to") or ""))
        source_id = str(edge.get("from") or "")
        if target and source_id in index and source_id not in target["dependencies"]:
            target["dependencies"].append(source_id)

    for task in index.values():
        task["dependencies"] = [d for d in task["dependencies"] if d in index and d != task["id"]]

    config = load_config(paths)
    roadmap = empty_roadmap(str((config.get("project") or {}).get("id")))
    roadmap["tasks"] = tasks
    roadmap["sequences"]["task"] = len(index)

    report = validate(config, roadmap, [])
    summary = {
        "modules": len(modules),
        "features": len(features),
        "tasks": len(index),
        "orphans": [task["id"] for task in orphans],
        "errors": [issue.message for issue in report.errors],
        "warnings": len(report.warnings),
        "applied": False,
        "backup": None,
    }
    if not report.ok:
        return summary
    if not apply:
        return summary

    backup_dir = paths.memory_dir / "migration-backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for source in detect_legacy(paths.root):
        shutil.copy2(source, backup_dir / source.name)
    if paths.roadmap.exists():
        shutil.copy2(paths.roadmap, backup_dir / "roadmap.before-migration.json")

    with FileLock(paths.lock):
        current = load_roadmap(paths)
        roadmap["state_revision"] = int(current.get("state_revision", 1)) + 1
        for task in index.values():
            append_activity(
                paths,
                action="task_created",
                source="migration",
                task_id=task["id"],
                after={"title": task["title"], "parent_id": task["parent_id"]},
                metadata={"origin": "oracle-roadmap.json"},
                roadmap=roadmap,
            )
        atomic_write_json(paths.roadmap, roadmap)
    generate_dashboard(paths, record=False)
    summary["applied"] = True
    summary["backup"] = str(backup_dir.relative_to(paths.root))
    return summary


# --------------------------------------------------------------------------- #
# Interfaz de línea de comandos
# --------------------------------------------------------------------------- #


def print_report(report: ValidationReport) -> None:
    for issue in report.errors:
        location = f" [{issue.task_id}]" if issue.task_id else ""
        print(f"  ERROR   {issue.code}{location}: {issue.message}")
    for issue in report.warnings:
        location = f" [{issue.task_id}]" if issue.task_id else ""
        print(f"  AVISO   {issue.code}{location}: {issue.message}")


def cmd_init(paths: Paths, args: argparse.Namespace) -> int:
    paths.memory_dir.mkdir(parents=True, exist_ok=True)
    if paths.config.exists() and not args.force:
        print("project-config.json ya existe. Usa --force para regenerarlo.")
    else:
        config = default_config(paths.root)
        if args.project_id:
            config["project"]["id"] = args.project_id
        if args.task_prefix:
            config["project"]["task_prefix"] = args.task_prefix
        atomic_write_json(paths.config, config)
        print(f"Creado {paths.config.relative_to(paths.root)}")
    config = load_config(paths)
    if paths.roadmap.exists() and not args.force:
        print("roadmap.json ya existe: no se toca.")
    else:
        atomic_write_json(paths.roadmap, empty_roadmap(str((config.get("project") or {}).get("id"))))
        print(f"Creado {paths.roadmap.relative_to(paths.root)} con 0 tareas")
    if not paths.activity.exists():
        atomic_write_text(paths.activity, "")
        print(f"Creado {paths.activity.relative_to(paths.root)}")
    return 0


def cmd_validate(paths: Paths, _args: argparse.Namespace) -> int:
    config = load_config(paths)
    roadmap = load_roadmap(paths)
    activity = read_activity(paths)
    report = validate(config, roadmap, activity)
    print_report(report)
    metrics = compute_metrics(roadmap, activity)
    print(
        f"Tareas: {metrics['total_tasks']} · Prompts: {metrics['prompts_total']} · "
        f"Eventos: {metrics['activity_events']} · Revisión: {metrics['state_revision']}"
    )
    if report.ok:
        print(f"Validación correcta ({len(report.warnings)} aviso(s)).")
        return 0
    print(f"Validación fallida: {len(report.errors)} error(es).")
    return 1


def cmd_generate(paths: Paths, args: argparse.Namespace) -> int:
    generate_dashboard(paths, port=args.port, record=True)
    print(f"Dashboard escrito en {paths.dashboard.relative_to(paths.root)}")
    return 0


def cmd_check(paths: Paths, args: argparse.Namespace) -> int:
    config = load_config(paths)
    roadmap = load_roadmap(paths)
    activity = read_activity(paths)
    report = validate(config, roadmap, activity)
    print_report(report)
    if not report.ok:
        print("Validación fallida: no se sobrescribe el HTML anterior.")
        return 1
    expected = render_dashboard(paths, config, roadmap, activity, port=args.port)
    twice = render_dashboard(paths, config, roadmap, activity, port=args.port)
    if expected != twice:
        print("La generación no es determinista.")
        return 1
    if not paths.dashboard.exists():
        print("Falta dashboard.html: ejecuta 'generate'.")
        return 1
    if paths.dashboard.read_text(encoding="utf-8") != expected:
        print("dashboard.html está desincronizado con roadmap.json: ejecuta 'generate'.")
        return 1
    print("Consistencia correcta: roadmap, actividad y dashboard coinciden.")
    return 0


def cmd_serve(paths: Paths, args: argparse.Namespace) -> int:
    serve(paths, port=args.port)
    return 0


def cmd_add_task(paths: Paths, args: argparse.Namespace) -> int:
    with Transaction(paths, source="cli") as tx:
        task = op_add_task(
            tx,
            title=args.title,
            group=args.group,
            parent_id=args.parent,
            description=args.description or "",
            objective=args.objective or "",
            priority=args.priority,
            task_id=args.id,
        )
        tx.commit()
    generate_dashboard(paths, record=False)
    print(task["id"])
    return 0


def cmd_move_task(paths: Paths, args: argparse.Namespace) -> int:
    with Transaction(paths, source="cli") as tx:
        op_move_task(tx, args.task_id, args.parent)
        tx.commit()
    generate_dashboard(paths, record=False)
    print(f"{args.task_id} movida bajo {args.parent or 'la raíz'}")
    return 0


def cmd_set_status(paths: Paths, args: argparse.Namespace) -> int:
    with Transaction(paths, source="cli") as tx:
        op_set_status(
            tx, args.task_id, args.status,
            override_reason=args.override_reason, blocked_reason=args.blocked_reason,
        )
        tx.commit()
    generate_dashboard(paths, record=False)
    print(f"{args.task_id} → {STATUS_LABELS.get(args.status, args.status)}")
    return 0


def cmd_add_prompt(paths: Paths, args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8") if args.file else (args.text or sys.stdin.read())
    with Transaction(paths, source="cli") as tx:
        record = op_add_prompt(
            tx, args.task_id,
            {
                "title": args.title,
                "prompt_text": text,
                "purpose": args.purpose or "",
                "tool_or_model": args.tool or "",
                "tags": args.tags.split(",") if args.tags else [],
            },
        )
        tx.commit()
    generate_dashboard(paths, record=False)
    print(record["id"])
    return 0


def cmd_migrate(paths: Paths, args: argparse.Namespace) -> int:
    summary = migrate(paths, apply=args.apply)
    print(
        f"Origen: {summary['modules']} módulos y {summary['features']} funcionalidades "
        f"→ {summary['tasks']} tareas."
    )
    if summary["orphans"]:
        print(f"Sin módulo padre (quedan como raíz): {', '.join(summary['orphans'])}")
    if summary["errors"]:
        for message in summary["errors"][:10]:
            print(f"  ERROR   {message}")
        print("Migración no aplicada.")
        return 1
    print(f"Avisos tras la conversión: {summary['warnings']}")
    if summary["applied"]:
        print(f"Migración aplicada. Copia de seguridad en {summary['backup']}")
        print("Los archivos anteriores siguen intactos en docs/development/.")
    else:
        print("Simulación correcta. Repite con --apply para escribir el roadmap.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ishtar_memory.py",
        description="Ishtar Memory: planificación viva, prompts por tarea y dashboard local.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Puerto del modo edición.")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Crea la configuración y un roadmap vacío.")
    init.add_argument("--project-id")
    init.add_argument("--task-prefix")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    sub.add_parser("validate", help="Valida configuración, árbol, prompts y actividad.").set_defaults(func=cmd_validate)

    # --port se acepta antes o después del subcomando; SUPPRESS evita que el
    # subparser pise el valor global cuando no se indica aquí.
    for name, help_text, handler in (
        ("generate", "Genera el dashboard HTML.", cmd_generate),
        ("check", "Valida y comprueba la consistencia sin reemplazar.", cmd_check),
        ("serve", "Inicia el modo de edición local.", cmd_serve),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--port", type=int, default=argparse.SUPPRESS)
        command.set_defaults(func=handler)

    add_task = sub.add_parser("add-task", help="Crea una tarea o subtarea.")
    add_task.add_argument("title")
    add_task.add_argument("--group", default="TSK", help="Segmento del ID, por ejemplo ALT.")
    add_task.add_argument("--parent", default=None)
    add_task.add_argument("--description", default="")
    add_task.add_argument("--objective", default="")
    add_task.add_argument("--priority", default="medium", choices=ALLOWED_PRIORITIES)
    add_task.add_argument("--id", default=None, help="ID explícito (por defecto se calcula).")
    add_task.set_defaults(func=cmd_add_task)

    move = sub.add_parser("move-task", help="Mueve una tarea conservando su ID.")
    move.add_argument("task_id")
    move.add_argument("--parent", default=None)
    move.set_defaults(func=cmd_move_task)

    status = sub.add_parser("set-status", help="Cambia el estado de una tarea.")
    status.add_argument("task_id")
    status.add_argument("status", choices=ALLOWED_STATUSES)
    status.add_argument("--blocked-reason", default=None)
    status.add_argument("--override-reason", default=None)
    status.set_defaults(func=cmd_set_status)

    prompt = sub.add_parser("add-prompt", help="Registra un prompt literal en una tarea.")
    prompt.add_argument("task_id")
    prompt.add_argument("--title", required=True)
    prompt.add_argument("--file", default=None, help="Archivo con el texto del prompt.")
    prompt.add_argument("--text", default=None, help="Texto en línea. Sin --file ni --text se lee de stdin.")
    prompt.add_argument("--purpose", default="")
    prompt.add_argument("--tool", default="")
    prompt.add_argument("--tags", default="")
    prompt.set_defaults(func=cmd_add_prompt)

    migrate_cmd = sub.add_parser("migrate", help="Migra un roadmap heredado (oracle-roadmap.json).")
    migrate_cmd.add_argument("--apply", action="store_true", help="Escribe el resultado.")
    migrate_cmd.set_defaults(func=cmd_migrate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = Paths(repository_root())
    try:
        return int(args.func(paths, args))
    except IshtarError as error:
        print(f"{error.code}: {error.message}", file=sys.stderr)
        for message in error.metadata.get("errors", [])[:10]:
            print(f"  - {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
