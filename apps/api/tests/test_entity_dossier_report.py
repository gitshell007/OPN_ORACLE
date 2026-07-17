from __future__ import annotations

from opn_oracle.ai.schemas import AGENT_SCHEMAS
from opn_oracle.jobs.service import TASK_QUEUES
from opn_oracle.oracle.entity_dossier_report import (
    ENTITY_DOSSIER_AGENT,
    ENTITY_DOSSIER_REPORT_JOB,
    build_entity_dossier_metrics,
    compact_entity_dossier,
    entity_key,
    source_limits,
)
from opn_oracle.reporting.registry import ReportTemplateRegistry


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
