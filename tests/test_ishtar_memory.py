"""Pruebas de Ishtar Memory.

Se ejecutan con pytest o directamente:

    python3 -m pytest tests/test_ishtar_memory.py
    python3 tests/test_ishtar_memory.py

Solo biblioteca estándar. Nunca escriben en el roadmap real del repositorio.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

import ishtar_memory as im  # noqa: E402


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #


def make_repo(root: Path) -> im.Paths:
    """Crea un repositorio de trabajo aislado con un roadmap vacío."""
    paths = im.Paths(root)
    paths.memory_dir.mkdir(parents=True, exist_ok=True)
    config = im.default_config(root)
    config["project"]["id"] = "TEST-PROJECT"
    config["project"]["task_prefix"] = "TST"
    im.atomic_write_json(paths.config, config)
    im.atomic_write_json(paths.roadmap, im.empty_roadmap("TEST-PROJECT"))
    im.atomic_write_text(paths.activity, "")
    im.atomic_write_text(paths.decisions, "# Decisiones\n\n- Sin decisiones.\n")
    im.atomic_write_text(paths.progress, "# Progreso\n\n- Sin progreso.\n")
    im.atomic_write_text(paths.architecture, "# Arquitectura\n\n- Sin contenido.\n")
    return paths


def add_task(paths: im.Paths, title: str, *, parent: str | None = None, group: str = "TSK") -> str:
    with im.Transaction(paths) as tx:
        task = im.op_add_task(tx, title=title, group=group, parent_id=parent)
        tx.commit()
    return task["id"]


def validate_paths(paths: im.Paths) -> im.ValidationReport:
    return im.validate(im.load_config(paths), im.load_roadmap(paths), im.read_activity(paths))


def error_codes(report: im.ValidationReport) -> set[str]:
    return {issue.code for issue in report.errors}


def raises(code: str, fn: Any, *args: Any, **kwargs: Any) -> im.IshtarError:
    try:
        fn(*args, **kwargs)
    except im.IshtarError as error:
        assert error.code == code, f"Se esperaba {code} y llegó {error.code}: {error.message}"
        return error
    raise AssertionError(f"No se lanzó {code}")


# --------------------------------------------------------------------------- #
# Estructura
# --------------------------------------------------------------------------- #


def test_empty_roadmap_is_valid(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    report = validate_paths(paths)
    assert report.ok
    assert im.load_roadmap(paths)["tasks"] == []


def test_single_root_task(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Sistema de alertas", group="ALT")
    assert task_id == "TST-ALT-001"
    roadmap = im.load_roadmap(paths)
    assert roadmap["tasks"][0]["parent_id"] is None
    assert roadmap["state_revision"] == 2
    assert validate_paths(paths).ok


def test_multiple_depths(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    root = add_task(paths, "Raíz", group="ALT")
    child = add_task(paths, "Hijo", parent=root, group="ALT")
    grandchild = add_task(paths, "Nieto", parent=child, group="ALT")
    great = add_task(paths, "Bisnieto", parent=grandchild, group="ALT")

    roadmap = im.load_roadmap(paths)
    depths = {task["id"]: depth for task, _p, depth in im.iter_tasks(roadmap["tasks"])}
    assert depths == {root: 0, child: 1, grandchild: 2, great: 3}
    assert len({root, child, grandchild, great}) == 4, "cada subtarea tiene su propia ID"
    assert validate_paths(paths).ok


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    root = add_task(paths, "Raíz", group="ALT")
    roadmap = im.load_roadmap(paths)
    clone = json.loads(json.dumps(roadmap["tasks"][0]))
    roadmap["tasks"].append(clone)
    im.atomic_write_json(paths.roadmap, roadmap)
    assert "TASK_ID_DUPLICATE" in error_codes(validate_paths(paths))
    assert root  # el ID original sigue presente


def test_incoherent_parent_is_rejected(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    root = add_task(paths, "Raíz", group="ALT")
    add_task(paths, "Hijo", parent=root, group="ALT")
    roadmap = im.load_roadmap(paths)
    roadmap["tasks"][0]["children"][0]["parent_id"] = "TST-ALT-999"
    im.atomic_write_json(paths.roadmap, roadmap)
    codes = error_codes(validate_paths(paths))
    assert "TASK_PARENT_MISMATCH" in codes
    assert "TASK_PARENT_MISSING" in codes


def test_cycle_is_prevented_on_move(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    root = add_task(paths, "Raíz", group="ALT")
    child = add_task(paths, "Hijo", parent=root, group="ALT")
    with im.Transaction(paths) as tx:
        raises("TASK_CYCLE", im.op_move_task, tx, root, child)
        raises("TASK_CYCLE", im.op_move_task, tx, root, root)


def test_move_keeps_id_and_descendants(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    first = add_task(paths, "Primera", group="ALT")
    second = add_task(paths, "Segunda", group="ALT")
    child = add_task(paths, "Hijo", parent=first, group="ALT")
    grandchild = add_task(paths, "Nieto", parent=child, group="ALT")

    with im.Transaction(paths) as tx:
        im.op_move_task(tx, child, second)
        tx.commit()

    roadmap = im.load_roadmap(paths)
    moved = im.find_task(roadmap, child)
    assert moved["id"] == child
    assert moved["parent_id"] == second
    assert im.descendant_ids(moved) == {grandchild}
    assert validate_paths(paths).ok


def test_missing_dependency_is_rejected(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    root = add_task(paths, "Raíz", group="ALT")
    roadmap = im.load_roadmap(paths)
    im.find_task(roadmap, root)["dependencies"] = ["TST-ALT-404"]
    im.atomic_write_json(paths.roadmap, roadmap)
    assert "DEPENDENCY_MISSING" in error_codes(validate_paths(paths))


# --------------------------------------------------------------------------- #
# Estados
# --------------------------------------------------------------------------- #


def test_pending_to_in_progress(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    before = im.find_task(im.load_roadmap(paths), task_id)["updated_at"]
    with im.Transaction(paths) as tx:
        im.op_set_status(tx, task_id, "in_progress")
        tx.commit()
    task = im.find_task(im.load_roadmap(paths), task_id)
    assert task["status"] == "in_progress"
    assert task["completed_at"] is None
    assert task["updated_at"] >= before


def test_done_requires_override_when_pending_items(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    with im.Transaction(paths) as tx:
        error = raises("COMPLETION_REQUIRES_OVERRIDE", im.op_set_status, tx, task_id, "done")
        assert error.metadata["warnings"], "se enumeran los elementos pendientes"


def test_done_without_warnings_needs_no_override(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    roadmap = im.load_roadmap(paths)
    im.find_task(roadmap, task_id)["evidence"] = [{"type": "file", "path": "README.md"}]
    im.atomic_write_json(paths.roadmap, roadmap)

    with im.Transaction(paths) as tx:
        im.op_set_status(tx, task_id, "done")
        tx.commit()
    task = im.find_task(im.load_roadmap(paths), task_id)
    assert task["status"] == "done"
    assert task["completed_at"] is not None
    assert task["completion_override"] is None
    assert validate_paths(paths).ok


def test_completion_override_is_recorded(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    with im.Transaction(paths) as tx:
        im.op_set_status(tx, task_id, "done", override_reason="Cerrada por decisión del usuario")
        tx.commit()

    task = im.find_task(im.load_roadmap(paths), task_id)
    assert task["completion_override"]["reason"] == "Cerrada por decisión del usuario"
    assert task["completion_override"]["actor"] == "user"
    assert task["completed_at"] is not None

    report = validate_paths(paths)
    assert report.ok, "una tarea con override es válida"
    assert "TASK_DONE_WITH_WARNINGS" in {issue.code for issue in report.warnings}

    actions = [event["action"] for event in im.read_activity(paths)]
    assert "task_completion_overridden" in actions


def test_leaving_done_clears_completed_at(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    with im.Transaction(paths) as tx:
        im.op_set_status(tx, task_id, "done", override_reason="Motivo")
        tx.commit()
    with im.Transaction(paths) as tx:
        im.op_set_status(tx, task_id, "pending")
        tx.commit()

    task = im.find_task(im.load_roadmap(paths), task_id)
    assert task["status"] == "pending"
    assert task["completed_at"] is None
    assert task["completion_override"] is None
    changes = [e for e in im.read_activity(paths) if e["action"] == "task_status_changed"]
    assert [(e["before"]["status"], e["after"]["status"]) for e in changes] == [
        ("pending", "done"),
        ("done", "pending"),
    ], "el historial conserva el paso por realizada"


def test_blocked_requires_reason(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    with im.Transaction(paths) as tx:
        raises("BLOCKED_REQUIRES_REASON", im.op_set_status, tx, task_id, "blocked")

    with im.Transaction(paths) as tx:
        im.op_set_status(tx, task_id, "blocked", blocked_reason="Falta una migración")
        tx.commit()
    task = im.find_task(im.load_roadmap(paths), task_id)
    assert task["status"] == "blocked"
    assert task["blocked_reason"] == "Falta una migración"
    assert validate_paths(paths).ok


def test_blocked_without_reason_fails_validation(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    roadmap = im.load_roadmap(paths)
    im.find_task(roadmap, task_id)["status"] = "blocked"
    im.atomic_write_json(paths.roadmap, roadmap)
    assert "BLOCKED_WITHOUT_REASON" in error_codes(validate_paths(paths))


def test_parent_status_is_never_derived(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    root = add_task(paths, "Raíz", group="ALT")
    child = add_task(paths, "Hijo", parent=root, group="ALT")
    with im.Transaction(paths) as tx:
        im.op_set_status(tx, child, "done", override_reason="Motivo")
        tx.commit()

    roadmap = im.load_roadmap(paths)
    assert im.find_task(roadmap, root)["status"] == "pending", "el padre conserva su estado manual"
    branch = im.branch_progress(roadmap)[0]
    assert branch["children_done"] == 1 and branch["children_total"] == 1
    assert branch["percent"] == 50


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #

CODE_PROMPT = """Implementa el módulo.

```python
def alerta(nivel: str) -> str:
    return f"nivel: {nivel}"
```

    Bloque indentado con  espacios.
Fin — con acentos, ñ, «comillas» y emojis 🚀.
"""


def test_prompt_creation_and_sequential_ids(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    with im.Transaction(paths) as tx:
        first = im.op_add_prompt(tx, task_id, {"title": "Primero", "prompt_text": "Texto uno"})
        second = im.op_add_prompt(tx, task_id, {"title": "Segundo", "prompt_text": "Texto dos"})
        tx.commit()
    assert first["id"] == f"{task_id}-P001"
    assert second["id"] == f"{task_id}-P002"
    assert validate_paths(paths).ok
    actions = [e["action"] for e in im.read_activity(paths)]
    assert actions.count("prompt_created") == 2


def test_prompt_preserves_literal_text(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    with im.Transaction(paths) as tx:
        im.op_add_prompt(tx, task_id, {"title": "Con código", "prompt_text": CODE_PROMPT})
        tx.commit()
    stored = im.find_task(im.load_roadmap(paths), task_id)["prompt_records"][0]["prompt_text"]
    assert stored == CODE_PROMPT
    assert "```python" in stored
    assert stored.count("\n") == CODE_PROMPT.count("\n")
    assert "🚀" in stored and "ñ" in stored


def test_prompt_long_text(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    long_text = ("línea de prompt muy larga con contenido real\n" * 4000).strip()
    with im.Transaction(paths) as tx:
        im.op_add_prompt(tx, task_id, {"title": "Largo", "prompt_text": long_text})
        tx.commit()
    stored = im.find_task(im.load_roadmap(paths), task_id)["prompt_records"][0]
    assert stored["prompt_text"] == long_text
    assert len(stored["prompt_text"]) > 150_000


def test_prompt_requires_title_and_text(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    with im.Transaction(paths) as tx:
        raises("VALIDATION_ERROR", im.op_add_prompt, tx, task_id, {"title": "  ", "prompt_text": "x"})
        raises("VALIDATION_ERROR", im.op_add_prompt, tx, task_id, {"title": "t", "prompt_text": "   "})


def test_prompt_revision_keeps_previous_version(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    with im.Transaction(paths) as tx:
        record = im.op_add_prompt(tx, task_id, {"title": "Original", "prompt_text": "Versión uno"})
        tx.commit()
    with im.Transaction(paths) as tx:
        im.op_revise_prompt(
            tx, task_id, record["id"],
            {"prompt_text": "Versión dos", "change_reason": "Ajuste de alcance"},
        )
        tx.commit()

    stored = im.find_task(im.load_roadmap(paths), task_id)["prompt_records"][0]
    assert stored["prompt_text"] == "Versión dos"
    assert len(stored["revision_history"]) == 1
    assert stored["revision_history"][0]["prompt_text"] == "Versión uno"
    assert stored["revision_history"][0]["revision"] == 1
    assert stored["revision_history"][0]["change_reason"] == "Ajuste de alcance"
    assert validate_paths(paths).ok


def test_archive_keeps_prompt_and_never_reuses_id(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    with im.Transaction(paths) as tx:
        first = im.op_add_prompt(tx, task_id, {"title": "Uno", "prompt_text": "Texto"})
        tx.commit()
    with im.Transaction(paths) as tx:
        im.op_archive_prompt(tx, task_id, first["id"])
        tx.commit()
    with im.Transaction(paths) as tx:
        second = im.op_add_prompt(tx, task_id, {"title": "Dos", "prompt_text": "Texto"})
        tx.commit()

    records = im.find_task(im.load_roadmap(paths), task_id)["prompt_records"]
    assert len(records) == 2, "archivar no elimina"
    assert records[0]["archived_at"] is not None
    assert second["id"] == f"{task_id}-P002", "no se reutiliza el ID archivado"
    assert "prompt_archived" in [e["action"] for e in im.read_activity(paths)]


def test_activity_does_not_duplicate_prompt_text(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    secreto = "TEXTO-LITERAL-QUE-NO-DEBE-DUPLICARSE"
    with im.Transaction(paths) as tx:
        im.op_add_prompt(tx, task_id, {"title": "Uno", "prompt_text": secreto})
        tx.commit()
    assert secreto not in paths.activity.read_text(encoding="utf-8")
    events = [e for e in im.read_activity(paths) if e["action"] == "prompt_created"]
    assert events[0]["after"]["prompt_id"] == f"{task_id}-P001"


def test_prompt_not_found(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    with im.Transaction(paths) as tx:
        raises("PROMPT_NOT_FOUND", im.op_archive_prompt, tx, task_id, f"{task_id}-P999")
        raises("TASK_NOT_FOUND", im.op_add_prompt, tx, "TST-ALT-404", {"title": "t", "prompt_text": "x"})


# --------------------------------------------------------------------------- #
# API local
# --------------------------------------------------------------------------- #

XSS_TEXT = '</script><img src=x onerror="alert(1)"><b>&amp;</b>'


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Server:
    """Servidor local efímero para las pruebas de la API."""

    def __init__(self, paths: im.Paths) -> None:
        self.paths = paths
        self.port = free_port()
        self.httpd, self.csrf = im.build_server(paths, self.port)
        self.origin = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "Server":
        self.thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        csrf: str | None = "auto",
        origin: str | None = "auto",
        host: str | None = None,
        raw: bytes | None = None,
    ) -> tuple[int, dict[str, Any]]:
        data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
        request = urllib.request.Request(self.origin + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if csrf == "auto":
            request.add_header("X-Ishtar-CSRF", self.csrf)
        elif csrf:
            request.add_header("X-Ishtar-CSRF", csrf)
        if origin == "auto":
            request.add_header("Origin", self.origin)
        elif origin:
            request.add_header("Origin", origin)
        if host:
            request.add_header("Host", host)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))


def test_api_bootstrap(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    add_task(paths, "Tarea", group="ALT")
    im.generate_dashboard(paths, record=False)
    with Server(paths) as server:
        status, data = server.request("GET", "/api/bootstrap")
        assert status == 200 and data["ok"] is True
        assert data["mode"] == "edit"
        assert data["csrf_token"] == server.csrf
        assert data["state_revision"] == im.load_roadmap(paths)["state_revision"]
        assert data["metrics"]["total_tasks"] == 1


def test_api_write_requires_csrf_and_valid_origin(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    im.generate_dashboard(paths, record=False)
    revision = im.load_roadmap(paths)["state_revision"]
    url = f"/api/tasks/{task_id}/status"

    with Server(paths) as server:
        status, data = server.request(
            "PATCH", url, {"status": "in_progress", "expected_revision": revision}, csrf=None
        )
        assert status == 403 and data["error"]["code"] == "INVALID_CSRF"

        status, data = server.request(
            "PATCH", url, {"status": "in_progress", "expected_revision": revision}, csrf="token-falso"
        )
        assert status == 403 and data["error"]["code"] == "INVALID_CSRF"

        status, data = server.request(
            "PATCH", url, {"status": "in_progress", "expected_revision": revision},
            origin="http://evil.example",
        )
        assert status == 403 and data["error"]["code"] == "FORBIDDEN_ORIGIN"

        status, data = server.request(
            "PATCH", url, {"status": "in_progress", "expected_revision": revision},
            host="evil.example",
        )
        assert status == 403 and data["error"]["code"] == "FORBIDDEN_HOST"

    assert im.find_task(im.load_roadmap(paths), task_id)["status"] == "pending"


def test_api_status_change_and_revision_conflict(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    im.generate_dashboard(paths, record=False)
    revision = im.load_roadmap(paths)["state_revision"]

    with Server(paths) as server:
        status, data = server.request(
            "PATCH", f"/api/tasks/{task_id}/status",
            {"status": "in_progress", "expected_revision": revision},
        )
        assert status == 200 and data["ok"] is True
        assert data["state_revision"] == revision + 1
        assert data["task"]["status"] == "in_progress"

        status, data = server.request(
            "PATCH", f"/api/tasks/{task_id}/status",
            {"status": "pending", "expected_revision": revision},
        )
        assert status == 409
        assert data["error"]["code"] == "REVISION_CONFLICT"

    task = im.find_task(im.load_roadmap(paths), task_id)
    assert task["status"] == "in_progress", "el cambio en conflicto no se aplicó"
    assert paths.dashboard.read_text(encoding="utf-8").count("in_progress") > 0


def test_api_completion_override_flow(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    im.generate_dashboard(paths, record=False)

    with Server(paths) as server:
        revision = im.load_roadmap(paths)["state_revision"]
        status, data = server.request(
            "PATCH", f"/api/tasks/{task_id}/status", {"status": "done", "expected_revision": revision}
        )
        assert status == 409
        assert data["error"]["code"] == "COMPLETION_REQUIRES_OVERRIDE"
        assert data["error"]["warnings"]

        status, data = server.request(
            "PATCH", f"/api/tasks/{task_id}/status",
            {"status": "done", "expected_revision": revision, "override_reason": "Decisión del usuario"},
        )
        assert status == 200
        assert data["task"]["completion_override"]["reason"] == "Decisión del usuario"


def test_api_prompt_lifecycle(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    im.generate_dashboard(paths, record=False)

    with Server(paths) as server:
        revision = im.load_roadmap(paths)["state_revision"]
        status, data = server.request(
            "POST", f"/api/tasks/{task_id}/prompts",
            {"title": "Alta", "prompt_text": CODE_PROMPT, "tags": ["backend"], "expected_revision": revision},
        )
        assert status == 200
        prompt_id = data["prompt"]["id"]
        assert prompt_id == f"{task_id}-P001"

        status, data = server.request(
            "PATCH", f"/api/tasks/{task_id}/prompts/{prompt_id}",
            {"prompt_text": "Nuevo texto", "change_reason": "Corrección",
             "expected_revision": data["state_revision"]},
        )
        assert status == 200
        assert data["prompt"]["revision_history"][0]["prompt_text"] == CODE_PROMPT

        status, data = server.request(
            "POST", f"/api/tasks/{task_id}/prompts/{prompt_id}/archive",
            {"expected_revision": data["state_revision"]},
        )
        assert status == 200 and data["prompt"]["archived_at"]

        status, data = server.request("GET", f"/api/tasks/{task_id}/prompts")
        assert status == 200 and len(data["prompts"]) == 1

        status, data = server.request("GET", "/api/activity")
        assert status == 200
        actions = [event["action"] for event in data["activity"]]
        assert {"prompt_created", "prompt_revised", "prompt_archived"} <= set(actions)


def test_api_errors(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    im.generate_dashboard(paths, record=False)

    with Server(paths) as server:
        revision = im.load_roadmap(paths)["state_revision"]

        status, data = server.request("GET", "/api/tasks/TST-ALT-404")
        assert status == 404 and data["error"]["code"] == "TASK_NOT_FOUND"

        status, data = server.request(
            "PATCH", f"/api/tasks/{task_id}/prompts/{task_id}-P404",
            {"prompt_text": "x", "expected_revision": revision},
        )
        assert status == 404 and data["error"]["code"] == "PROMPT_NOT_FOUND"

        status, data = server.request(
            "PATCH", f"/api/tasks/{task_id}/status", {"status": "volando", "expected_revision": revision}
        )
        assert status == 422 and data["error"]["code"] == "INVALID_STATUS"

        oversized = json.dumps({"title": "x", "prompt_text": "a" * (im.MAX_REQUEST_BYTES + 100)}).encode()
        status, data = server.request("POST", f"/api/tasks/{task_id}/prompts", raw=oversized)
        assert status == 413 and data["error"]["code"] == "PAYLOAD_TOO_LARGE"

        status, data = server.request("GET", "/api/desconocido")
        assert status == 404 and data["error"]["code"] == "NOT_FOUND"


def test_api_serves_only_the_dashboard(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    im.generate_dashboard(paths, record=False)
    with Server(paths) as server:
        request = urllib.request.Request(server.origin + "/", method="GET")
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/html")

        for path in ("/../../../etc/passwd", "/docs/ishtar_memory/roadmap.json", "/project-config.json"):
            status, data = server.request("GET", path)
            assert status == 404, f"{path} no debe servirse"
            assert data["error"]["code"] == "NOT_FOUND"


# --------------------------------------------------------------------------- #
# Generación
# --------------------------------------------------------------------------- #


def test_generate_empty_dashboard(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    html = im.generate_dashboard(paths, record=True)
    assert "Todavía no hay tareas registradas" in html
    assert "Esta tarea todavía no tiene prompts registrados" in html
    assert "Todavía no se han registrado cambios" in html
    assert "Modo consulta" in html
    assert '"tasks": []' in paths.roadmap.read_text(encoding="utf-8")
    assert "dashboard_generated" in paths.activity.read_text(encoding="utf-8")


def test_generated_html_contains_every_view(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    root = add_task(paths, "Raíz", group="ALT")
    child = add_task(paths, "Hijo", parent=root, group="ALT")
    add_task(paths, "Nieto", parent=child, group="ALT")
    html = im.generate_dashboard(paths, record=False)

    for marker in ('data-tab="summary"', 'data-tab="checklist"', 'data-tab="graph"',
                   'data-tab="prompts"', 'data-tab="activity"', 'data-tab="decisions"',
                   'data-tab="architecture"'):
        assert marker in html, f"falta la pestaña {marker}"
    assert 'id="graph-svg"' in html
    assert 'id="prompt-backdrop"' in html
    assert "openPromptModal" in html
    assert "http://www.w3.org/2000/svg" in html
    assert "://" not in html.replace("http://www.w3.org/2000/svg", "").replace(
        "http://127.0.0.1", ""), "el dashboard no carga recursos externos"


def test_generation_is_deterministic(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    add_task(paths, "Raíz", group="ALT")
    config = im.load_config(paths)
    roadmap = im.load_roadmap(paths)
    activity = im.read_activity(paths)
    first = im.render_dashboard(paths, config, roadmap, activity)
    second = im.render_dashboard(paths, config, roadmap, activity)
    assert first == second


def test_prompt_content_is_escaped_in_html(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    with im.Transaction(paths) as tx:
        im.op_add_prompt(tx, task_id, {"title": XSS_TEXT, "prompt_text": XSS_TEXT})
        tx.commit()
    html = im.generate_dashboard(paths, record=False)

    payload = html.split('<script type="application/json" id="ishtar-data">')[1].split("</script>")[0]
    assert "</script>" not in payload and "<img" not in payload
    assert "\\u003c" in payload, "los signos < se escapan dentro del JSON incrustado"
    data = json.loads(payload)
    stored = data["roadmap"]["tasks"][0]["prompt_records"][0]
    assert stored["prompt_text"] == XSS_TEXT, "el texto literal se conserva intacto"
    # El texto sigue conteniendo la cadena literal que escribió el usuario, pero
    # ningún signo < o > sin escapar: no puede formarse una etiqueta ejecutable.
    assert "onerror" in stored["prompt_text"]
    assert "<img" not in html and "<b>" not in html


def test_invalid_roadmap_protects_last_html(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    add_task(paths, "Raíz", group="ALT")
    good = im.generate_dashboard(paths, record=False)

    roadmap = im.load_roadmap(paths)
    roadmap["tasks"][0]["status"] = "inventado"
    im.atomic_write_json(paths.roadmap, roadmap)

    raises("VALIDATION_ERROR", im.generate_dashboard, paths, record=False)
    assert paths.dashboard.read_text(encoding="utf-8") == good, "no se sobrescribe el HTML válido"


def test_transaction_rolls_back_on_invalid_state(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    before = paths.roadmap.read_text(encoding="utf-8")
    try:
        with im.Transaction(paths) as tx:
            im.find_task(tx.roadmap, task_id)["priority"] = "urgentísima"
            tx.commit()
    except im.IshtarError as error:
        assert error.code == "VALIDATION_ERROR"
    else:
        raise AssertionError("la transacción inválida debía fallar")
    assert paths.roadmap.read_text(encoding="utf-8") == before


def test_check_detects_desynchronised_dashboard(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    add_task(paths, "Raíz", group="ALT")
    im.generate_dashboard(paths, record=False)

    class Args:
        port = im.DEFAULT_PORT

    assert im.cmd_check(paths, Args()) == 0
    add_task(paths, "Otra", group="ALT")
    assert im.cmd_check(paths, Args()) == 1


def test_activity_malformed_is_detected(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    im.atomic_write_text(paths.activity, '{"event_id": "EVT-000001"}\n')
    report = validate_paths(paths)
    assert "ACTIVITY_MALFORMED" in error_codes(report)
    im.atomic_write_text(paths.activity, "esto no es json\n")
    raises("INVALID_ACTIVITY", im.read_activity, paths)


def test_unsafe_file_reference_is_detected(tmp_path: Path) -> None:
    paths = make_repo(tmp_path)
    task_id = add_task(paths, "Tarea", group="ALT")
    roadmap = im.load_roadmap(paths)
    im.find_task(roadmap, task_id)["related_files"] = ["../../etc/passwd"]
    im.atomic_write_json(paths.roadmap, roadmap)
    assert "UNSAFE_FILE_REFERENCE" in error_codes(validate_paths(paths))


# --------------------------------------------------------------------------- #
# Ejecución sin pytest
# --------------------------------------------------------------------------- #


def _run_standalone() -> int:
    import tempfile
    import traceback

    tests = sorted(
        (name, obj)
        for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    )
    failures = 0
    for name, function in tests:
        with tempfile.TemporaryDirectory() as directory:
            try:
                function(Path(directory))
            except Exception:
                failures += 1
                print(f"FALLO  {name}")
                traceback.print_exc()
            else:
                print(f"OK     {name}")
    print(f"\n{len(tests) - failures}/{len(tests)} pruebas correctas.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
