"""HTTP real: intent draft/accept, activity, conversation 202, custom brief 202 (MEMSOL)."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest

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

    activity = client.get(f"/api/v1/dossiers/{dossier_id}/activity")
    assert activity.status_code == 200, activity.get_json()
    payload = activity.get_json()
    assert payload["dossier_id"] == dossier_id
    assert payload["intent"] is not None
    assert payload["intent"]["status"] == "accepted"
    assert "items" in payload
    assert "summary" in payload

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
