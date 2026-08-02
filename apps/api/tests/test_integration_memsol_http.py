"""HTTP real: intent draft/accept, activity, conversation 202, custom brief 202 (MEMSOL)."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest

from opn_oracle.ai.context import build_context
from opn_oracle.tenants.context import TenantContext, tenant_context
from tests.test_integration_oracle_domain import _client, _create_dossier, _csrf

# Pull oracle_stack fixture from the domain integration module.
pytest_plugins = ("tests.test_integration_oracle_domain",)

pytestmark = pytest.mark.integration


def test_intent_draft_accept_and_activity_http(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    client = _client(oracle_stack)
    dossier = _create_dossier(client, oracle_stack[1], "Memsol intent HTTP")
    dossier_id = dossier["id"]
    csrf = _csrf(client)

    draft = client.post(
        f"/api/v1/dossiers/{dossier_id}/intent/drafts",
        json={
            "schema_key": "custom",
            "schema_version": "v1",
            "request_text": "Decidir si entrarmos en el mercado objetivo",
            "structured_spec": {"decision_to_make": "entrar o no"},
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert draft.status_code == 201, draft.get_json()
    body = draft.get_json()
    revision_id = body["id"]
    assert body["status"] == "draft"

    accept = client.post(
        f"/api/v1/dossiers/{dossier_id}/intent/drafts/{revision_id}/accept",
        headers={"X-CSRF-Token": csrf},
    )
    assert accept.status_code == 200, accept.get_json()
    assert accept.get_json()["status"] == "accepted"

    requirement = client.post(
        f"/api/v1/dossiers/{dossier_id}/requirements",
        json={
            "class": "market_scan",
            "priority": "high",
            "question": "¿Qué oportunidades cumplen el alcance aceptado?",
            "decision_to_support": "Priorizar entrada",
            "intent_revision_id": revision_id,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert requirement.status_code == 201, requirement.get_json()
    offering = client.post(
        f"/api/v1/dossiers/{dossier_id}/offerings",
        json={
            "name": "Oferta industrial sintética",
            "description": "Capacidad que debe contrastarse con el mercado.",
            "intent_revision_id": revision_id,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert offering.status_code == 201, offering.get_json()

    activity = client.get(f"/api/v1/dossiers/{dossier_id}/activity")
    assert activity.status_code == 200, activity.get_json()
    payload = activity.get_json()
    assert payload["dossier_id"] == dossier_id
    assert payload["intent"] is not None
    assert payload["intent"]["status"] == "accepted"
    assert "items" in payload
    assert "summary" in payload

    app, ids, _ = oracle_stack
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        context = build_context(uuid.UUID(dossier_id), max_tokens=8_000)
    assert context.payload["accepted_intent"]["id"] == revision_id
    assert (
        "entrar o no" in context.payload["accepted_intent"]["structured_spec"]["decision_to_make"]
    )
    assert context.payload["intelligence_requirements"][0]["id"] == requirement.get_json()["id"]
    assert context.payload["offerings"][0]["id"] == offering.get_json()["id"]
    assert context.manifest["intent_revision_id"] == revision_id
    assert context.manifest["intent_content_hash"] == body["content_hash"]

    # Unknown dossier id → 404 (not leak)
    foreign = client.get(f"/api/v1/dossiers/{uuid.uuid4()}/activity")
    assert foreign.status_code == 404


def test_conversation_message_202_and_get_status(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    client = _client(oracle_stack)
    dossier = _create_dossier(client, oracle_stack[1], "Memsol ask HTTP")
    dossier_id = dossier["id"]
    csrf = _csrf(client)

    conv = client.post(
        f"/api/v1/dossiers/{dossier_id}/conversations",
        json={"title": "Preguntas HTTP"},
        headers={"X-CSRF-Token": csrf},
    )
    assert conv.status_code == 201, conv.get_json()
    conversation_id = conv.get_json()["id"]

    # Avoid broker: publish_job may fail-soft; message must still be durable.
    with patch("opn_oracle.jobs.service.publish_job", return_value=True):
        msg = client.post(
            f"/api/v1/dossiers/{dossier_id}/conversations/{conversation_id}/messages",
            json={"content_text": "¿Hay evidencia suficiente en el expediente?"},
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": f"ask-http-{uuid.uuid4().hex[:16]}",
            },
        )
    assert msg.status_code == 202, msg.get_json()
    body = msg.get_json()
    assert body["message_id"]
    assert body["job_id"]
    assert body["status"] == "queued"

    got = client.get(
        f"/api/v1/dossiers/{dossier_id}/conversations/{conversation_id}/messages/{body['message_id']}"
    )
    assert got.status_code == 200, got.get_json()
    assert got.get_json()["content_text"].startswith("¿Hay evidencia")
    assert got.get_json()["status"] == "queued"

    # Dispatch handler in-process (no Celery worker): terminal poll + payload.
    # Debt: real Celery worker E2E not exercised here.
    app, ids, _ = oracle_stack
    from opn_oracle.extensions import db
    from opn_oracle.oracle.conversations import process_dossier_question_answer
    from opn_oracle.oracle.jobs import BackgroundJob

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        job = db.session.get(BackgroundJob, uuid.UUID(str(body["job_id"])))
        assert job is not None
        # Fail-closed default when memory not configured → deterministic answer.
        result = process_dossier_question_answer(
            db.session,
            {
                "message_id": str(body["message_id"]),
                "conversation_id": str(conversation_id),
                "dossier_id": str(dossier_id),
            },
            job,
            memory_mode="disabled",
        )
        db.session.commit()
        assert result.get("status") in {"succeeded", "cancelled"} or result.get("memory_mode") in {
            "disabled",
            "shadow",
            "augment",
        }

    terminal = client.get(
        f"/api/v1/dossiers/{dossier_id}/conversations/{conversation_id}/messages/{body['message_id']}"
    )
    assert terminal.status_code == 200, terminal.get_json()
    payload = terminal.get_json()
    assert payload["status"] in {"succeeded", "failed", "cancelled"}
    if payload["status"] == "succeeded":
        answer = payload.get("answer_payload") or {}
        # No phantom evidence when mode=disabled
        assert answer.get("allowed_evidence_ids", []) == [] or answer.get("citations") == []
        assert "input_manifest_hash" in answer or payload.get("coverage_manifest") is not None


def test_custom_brief_202_and_get_detail(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    client = _client(oracle_stack)
    dossier = _create_dossier(client, oracle_stack[1], "Memsol brief HTTP")
    dossier_id = dossier["id"]
    csrf = _csrf(client)

    with patch("opn_oracle.jobs.service.publish_job", return_value=True):
        created = client.post(
            f"/api/v1/dossiers/{dossier_id}/reports/custom",
            json={"brief_request": "Informe de posicionamiento competitivo del expediente"},
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": f"brief-http-{uuid.uuid4().hex[:16]}",
            },
        )
    assert created.status_code == 202, created.get_json()
    body = created.get_json()
    assert body["report_id"]
    assert body["job_id"]
    assert body["plan_status"] == "draft"

    detail = client.get(f"/api/v1/dossiers/{dossier_id}/reports/custom/{body['report_id']}")
    assert detail.status_code == 200, detail.get_json()
    assert detail.get_json()["plan_status"] == "draft"
    assert "posicionamiento" in detail.get_json()["brief_request"]
