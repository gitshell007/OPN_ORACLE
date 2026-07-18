from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from flask import g

from opn_oracle.ai.registry import PromptRegistry
from opn_oracle.ai.schemas import AGENT_SCHEMAS
from opn_oracle.auth import permissions
from opn_oracle.integrations import entity_intel_routes
from opn_oracle.jobs.service import TASK_QUEUES
from opn_oracle.oracle.entity_dossier_report import (
    ENTITY_DOSSIER_AGENT,
    ENTITY_DOSSIER_REPORT_JOB,
    build_entity_dossier_metrics,
    build_pending_entity_evidence_sources,
    compact_entity_dossier,
    entity_key,
    source_limits,
)
from opn_oracle.platform.models import User
from opn_oracle.reporting.registry import ReportTemplateRegistry


@contextmanager
def _authenticated(app: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Real HTTP dispatch with a test identity, replacing only the auth runtime."""

    user = User(
        id=uuid.uuid4(),
        email="entity-report@example.com",
        display_name="Entity Report",
        status="active",
    )
    tenant_id = uuid.uuid4()
    monkeypatch.setattr(permissions, "current_user", user)
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda user_id, active_tenant_id: frozenset({"report.generate"}),
    )
    before = app.before_request_funcs.get(None, [])
    idx = next(
        i for i, fn in enumerate(before) if fn.__name__ == "protect_csrf_and_install_identity"
    )
    original = before[idx]

    def install_identity() -> None:
        g.active_tenant_id = tenant_id

    before[idx] = install_identity
    try:
        yield
    finally:
        before[idx] = original


def test_create_entity_report_route_dispatches_body_via_http(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regresión: la ruta debía romperse con json_data vs payload en dispatch real.

    El bug solo aparecía por HTTP (APIFlask inyecta el cuerpo como `json_data`);
    invocar la vista directa no lo reproduce. Este test dispara la ruta de verdad.
    """

    captured: dict[str, Any] = {}

    def fake_enqueue(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return type("Job", (), {"id": uuid.uuid4()})()

    monkeypatch.setattr(entity_intel_routes, "enqueue_entity_dossier_report", fake_enqueue)
    monkeypatch.setattr(entity_intel_routes, "serialize_job", lambda job: {"id": str(job.id)})
    monkeypatch.setattr(
        entity_intel_routes,
        "current_user",
        type("U", (), {"id": uuid.uuid4()})(),
    )

    with _authenticated(app, monkeypatch):
        response = client.post(
            "/api/v1/entity-intel/reports",
            json={"name": "ITURRI SA", "type": "company"},
            headers={"Idempotency-Key": "entity-report-key-1"},
        )

    assert response.status_code == 202
    assert captured["name"] == "ITURRI SA"
    assert captured["kind"] == "company"


def test_incorporate_entity_report_route_dispatches_body_via_http(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Segunda ruta con el mismo riesgo json_data vs payload; dispatch real."""

    captured: dict[str, Any] = {}
    dossier_id = uuid.uuid4()

    def fake_incorporate(**kwargs: Any) -> Any:
        captured.update(kwargs)
        report = type("R", (), {"id": uuid.uuid4()})()
        job = type("J", (), {"id": uuid.uuid4()})()
        return report, job

    monkeypatch.setattr(entity_intel_routes, "incorporate_entity_dossier_report", fake_incorporate)
    monkeypatch.setattr(
        entity_intel_routes,
        "serialize_report",
        lambda report, **_kw: {"id": str(report.id)},
    )
    monkeypatch.setattr(entity_intel_routes, "serialize_job", lambda job: {"id": str(job.id)})
    monkeypatch.setattr(entity_intel_routes, "current_user", type("U", (), {"id": uuid.uuid4()})())

    with _authenticated(app, monkeypatch):
        response = client.post(
            f"/api/v1/entity-intel/reports/{uuid.uuid4()}/incorporate",
            json={"dossier_id": str(dossier_id)},
        )

    assert response.status_code in (200, 201)
    assert captured["dossier_id"] == dossier_id


def test_entity_intel_json_routes_use_apiflask_body_argument() -> None:
    """Contrato: toda vista con @bp.input(location='json') debe recibir `json_data`.

    APIFlask inyecta el cuerpo con ese nombre; una firma con otro nombre revienta
    con TypeError solo en dispatch HTTP real. Se barre el fuente del blueprint para
    que un tercer endpoint no repita el fallo sin que nadie se entere. Es una
    comprobación textual a propósito: no depende de internals de APIFlask.
    """
    import re
    from pathlib import Path

    source = Path(entity_intel_routes.__file__).read_text(encoding="utf-8")
    # Cada @bp.input(..., location="json") seguido (saltando otros decoradores)
    # de la firma def ...(...): debe llevar un parámetro json_data.
    pattern = re.compile(
        r'location="json"\).*?\ndef \w+\((?P<sig>[^)]*)\)',
        re.DOTALL,
    )
    offenders = [
        m.group("sig") for m in pattern.finditer(source) if "json_data" not in m.group("sig")
    ]
    assert offenders == [], f"vistas con cuerpo json sin arg 'json_data': {offenders}"


def test_entity_dossier_prompt_output_budget_matches_signal_policy() -> None:
    """El informe cita evidencia BORME/noticias, así que su salida es larga.

    Con 5000 y con 8000 se truncaba a media palabra y ReportOutput fallaba con
    "Invalid JSON: EOF". Este valor queda sincronizado con la config gobernada de
    la task en Signal (16000); si allí cambia, aquí debe cambiar también.
    """
    prompt = PromptRegistry().get(ENTITY_DOSSIER_AGENT, "v1")
    assert prompt.max_output_tokens == 16000


def test_entity_dossier_report_runtime_is_registered() -> None:
    assert AGENT_SCHEMAS[ENTITY_DOSSIER_AGENT].__name__ == "ReportOutput"
    assert TASK_QUEUES[ENTITY_DOSSIER_REPORT_JOB] == "ai"
    assert ReportTemplateRegistry().get("entity_intelligence").formats == ("html", "json")


def test_entity_dossier_metrics_are_python_calculated() -> None:
    payload = {
        "entity": {"name": "ITURRI SA", "type": "company"},
        "sections": {
            "registry": {
                "ok": True,
                "data": {
                    "total": 2,
                    "profile": {
                        "status": "activa",
                        "first_act_date": "2020-01-01",
                        "last_act_date": "2026-07-17",
                    },
                    "items": [
                        {
                            "action": "nombramiento",
                            "province": "SEVILLA",
                            "date": "2026-07-17",
                        },
                        {"action": "cese", "province": "MADRID", "date": "2025-01-01"},
                    ],
                },
            },
            "graph": {
                "ok": True,
                "data": {
                    "nodes": [{"id": "company"}, {"id": "person"}],
                    "edges": [
                        {"source": "company", "target": "person", "date": "2026-07-17"},
                        {"source": "company", "target": "other"},
                    ],
                    "truncated": False,
                },
            },
            "news": {"ok": True, "data": {"items": [{"title": "Mención"}]}},
        },
    }

    metrics = build_entity_dossier_metrics(payload)

    assert metrics["registry"]["acts"] == 2
    assert metrics["registry"]["actions"] == {"nombramiento": 1, "cese": 1}
    assert metrics["registry"]["provinces"] == ["MADRID", "SEVILLA"]
    assert metrics["graph"] == {
        "nodes": 2,
        "edges": 2,
        "dated_edges": 1,
        "undated_edges": 1,
        "truncated": False,
    }
    assert metrics["news"]["items"] == 1


def test_entity_dossier_waiting_payload_discloses_limits_and_caps_lists() -> None:
    payload = {
        "entity": {"name": "Entidad", "type": "company"},
        "sections": {
            "registry": {
                "ok": True,
                "data": {"items": [{"action": "nombramiento"} for _ in range(205)]},
            },
            "news": {"ok": True, "data": {"items": [{"title": "Mención"} for _ in range(31)]}},
        },
    }

    compact = compact_entity_dossier(payload)

    assert len(compact["registry"]["items"]) == 200
    assert compact["registry"]["truncated_by_oracle"] is True
    assert len(compact["news"]["items"]) == 30
    assert compact["news"]["truncated_by_oracle"] is True
    assert any("BORME" in item and "publicación" in item for item in source_limits())
    assert entity_key(name="ITURRI, S.A.", kind="company").startswith("company:iturri-s-a")


def test_registry_limit_caps_sources_and_discloses_the_cut() -> None:
    """El tope de actos acota la salida y debe declararse, no ocultarse.

    Cada acto se vuelve una fuente citable que el modelo enumera en su índice, así
    que el número de actos fija el suelo de longitud de la salida: con 65 actas el
    informe agotaba 16000 tokens y moría con "Invalid JSON: EOF". Recortar sin
    declararlo sería peor que el fallo: presentaría un análisis de 5 actos como si
    hubiera visto los 65.
    """

    payload = {
        "entity": {"name": "Entidad", "type": "company"},
        "sections": {
            "registry": {
                "ok": True,
                "data": {
                    "total": 65,
                    "items": [
                        {
                            "action": "nombramiento",
                            "date": f"2026-07-{index:02d}",
                            "source_url": f"https://www.boe.es/borme/dias/2026/07/{index:02d}/",
                        }
                        for index in range(1, 28)
                    ],
                },
            }
        },
    }

    compact = compact_entity_dossier(payload, registry_limit=5)

    assert len(compact["registry"]["items"]) == 5
    assert compact["registry"]["analyzed_acts"] == 5
    assert compact["registry"]["truncated_by_oracle"] is True

    # El recorte reduce las fuentes citables, que es lo que acota la salida del modelo.
    sources = build_pending_entity_evidence_sources(
        entity_dossier=compact,
        corpus_hash="b" * 64,
    )
    assert len(sources) == 5

    disclosure = source_limits(compact)
    assert any("5" in line and "65" in line for line in disclosure), disclosure
    # Sin recorte no se inventa una advertencia que no aplica.
    assert source_limits(compact_entity_dossier(payload, registry_limit=200)) == source_limits()


def test_entity_dossier_builds_pending_citable_sources_from_urls() -> None:
    compact = {
        "registry": {
            "items": [
                {
                    "company": "ITURRI SA",
                    "person": "APELLIDOS NOMBRE",
                    "role": "Administrador",
                    "action": "nombramiento",
                    "date": "2026-07-01",
                    "province": "SEVILLA",
                    "source_url": "https://www.boe.es/borme/dias/2026/07/01/",
                },
                {"action": "cese", "date": "2026-07-02"},
            ]
        },
        "news": {
            "items": [
                {
                    "title": "ITURRI obtiene una adjudicación",
                    "published_at": "2026-07-03",
                    "source_name": "Medio",
                    "url": "https://example.test/noticia",
                }
            ]
        },
    }

    first = build_pending_entity_evidence_sources(
        entity_dossier=compact,
        corpus_hash="a" * 64,
    )
    second = build_pending_entity_evidence_sources(
        entity_dossier=compact,
        corpus_hash="a" * 64,
    )

    assert first == second
    assert [item["source_kind"] for item in first] == ["registry_act", "news"]
    assert all(uuid.UUID(item["id"]) for item in first)
    assert "BORME" in first[0]["label"]
    assert first[0]["source_url"].startswith("https://www.boe.es/borme/")
