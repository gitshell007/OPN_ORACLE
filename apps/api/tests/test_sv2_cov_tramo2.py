"""SV2-COV-TRAMO2 · product coverage for the Preguntar HTTP path.

Behavioral tests (not line-painting) for:

- ``oracle/conversation_routes.py`` — create/list/enqueue/get + allowlist-visible
  422 + job message states + tenant permissions (097, MEMSOL-06)
- residual pure helpers from dual allowlist (097 format) exercised via the same
  surface the UI polls after a failed answer job

Unit / Flask unit — no PG. Style aligned with ``test_memory_mdev08_http_lifecycle.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from flask import g

from opn_oracle.auth import permissions
from opn_oracle.integrations.memory_ask_dual import format_allowlist_rejection
from opn_oracle.oracle import conversation_routes
from opn_oracle.oracle.conversations import (
    ConversationConflict,
    ConversationError,
    ConversationNotFound,
    serialize_message,
)
from opn_oracle.platform.models import User

# ---------------------------------------------------------------------------
# Shared HTTP probe (same shape as MDEV-08 lifecycle tests)
# ---------------------------------------------------------------------------


@contextmanager
def _authenticated_http_probe(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
    allowed_permissions: frozenset[str],
    *,
    user: User | None = None,
    tenant_id: uuid.UUID | None = None,
) -> Iterator[tuple[User, uuid.UUID]]:
    actor = user or User(
        id=uuid.uuid4(),
        email="sv2-cov-tramo2@example.com",
        display_name="SV2 COV TRAMO2",
        status="active",
    )
    tid = tenant_id or uuid.uuid4()
    monkeypatch.setattr(permissions, "current_user", actor)
    monkeypatch.setattr(conversation_routes, "current_user", actor)
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda user_id, active_tenant_id: allowed_permissions,
    )
    before_request_funcs = app.before_request_funcs.get(None, [])
    auth_index = next(
        index
        for index, function in enumerate(before_request_funcs)
        if function.__name__ == "protect_csrf_and_install_identity"
    )
    original = before_request_funcs[auth_index]

    def install_test_identity() -> None:
        g.active_tenant_id = tid

    before_request_funcs[auth_index] = install_test_identity
    try:
        yield actor, tid
    finally:
        before_request_funcs[auth_index] = original


def _conversation_body(
    *,
    dossier_id: uuid.UUID,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    conversation_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    cid = conversation_id or uuid.uuid4()
    return {
        "id": str(cid),
        "tenant_id": str(tenant_id),
        "dossier_id": str(dossier_id),
        "status": "open",
        "title": "Preguntas de mercado",
        "created_by_user_id": str(actor_id),
        "intent_revision_id": None,
        "created_at": "2026-08-04T08:00:00+00:00",
        "updated_at": "2026-08-04T08:00:00+00:00",
    }


def _message_ns(
    *,
    dossier_id: uuid.UUID,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    status: str = "queued",
    error_code: str | None = None,
    error_message: str | None = None,
    content_text: str = "¿Qué riesgos hay?",
    answer_payload: dict[str, Any] | None = None,
) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        conversation_id=conversation_id,
        role="user",
        status=status,
        sequence=1,
        content_text=content_text,
        answer_payload=answer_payload or {},
        coverage_manifest={},
        background_job_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
        error_code=error_code,
        error_message=error_message,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Allowlist-visible format (097) — pure contract the UI/job surfaces
# ---------------------------------------------------------------------------


def test_format_allowlist_rejection_includes_ids_and_size() -> None:
    """Bug que cazaría: 422/job que traga los IDs y solo dice «fuera de allowlist (3)»."""

    rejected = [
        "96272488-1112-4058-8217-a34db67b5bd9",
        "dd7940c8-d206-41df-aee9-246c0e51c370",
        "63f7c8ef-3bf5-48ad-9e51-cb313c9f3633",
    ]
    allowed = [str(uuid.uuid4()) for _ in range(12)]
    msg = format_allowlist_rejection(rejected, allowed)
    assert "fuera de allowlist (3)" in msg
    assert rejected[0] in msg
    assert rejected[2] in msg
    assert "allowlist_size=12" in msg
    # Caps sample at 8 with a remainder marker.
    many = [str(uuid.uuid4()) for _ in range(10)]
    long_msg = format_allowlist_rejection(many, allowed)
    assert "(+2 más)" in long_msg
    assert "allowlist_size=12" in long_msg


def test_serialize_message_surfaces_failed_allowlist_cause() -> None:
    """Bug que cazaría: GET message que pierde error_message del fallo allowlist."""

    rejected = ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]
    detail = format_allowlist_rejection(rejected, [str(uuid.uuid4()) for _ in range(5)])
    message = _message_ns(
        dossier_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        status="failed",
        error_code="conversation_error",
        error_message=detail,
    )
    payload = serialize_message(message)  # type: ignore[arg-type]
    assert payload["status"] == "failed"
    assert payload["error_code"] == "conversation_error"
    assert rejected[0] in (payload["error_message"] or "")
    assert "allowlist_size=5" in (payload["error_message"] or "")


# ---------------------------------------------------------------------------
# conversation_routes — create / list
# ---------------------------------------------------------------------------


def test_create_conversation_http_201(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: POST create que no persiste commit o devuelve body incompleto."""

    dossier_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    body = _conversation_body(
        dossier_id=dossier_id,
        tenant_id=tenant_id,
        actor_id=actor_id,
        conversation_id=conversation_id,
    )
    commits: list[str] = []
    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )
    monkeypatch.setattr(
        conversation_routes,
        "create_conversation",
        lambda *a, **k: SimpleNamespace(id=conversation_id),
    )
    monkeypatch.setattr(conversation_routes, "serialize_conversation", lambda c: body)
    monkeypatch.setattr(conversation_routes.db.session, "commit", lambda: commits.append("commit"))
    with _authenticated_http_probe(
        app, monkeypatch, frozenset({"dossier.write"}), tenant_id=tenant_id
    ):
        response = client.post(
            f"/api/v1/dossiers/{dossier_id}/conversations",
            json={"title": "Preguntas de mercado"},
        )
    assert response.status_code == 201, response.get_data(as_text=True)[:500]
    data = response.get_json()
    assert data["id"] == str(conversation_id)
    assert data["status"] == "open"
    assert data["title"] == "Preguntas de mercado"
    assert commits == ["commit"]


def test_create_conversation_http_404_and_422(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: 500 en create por ConversationNotFound/Error sin mapear a problem."""

    dossier_id = uuid.uuid4()
    monkeypatch.setattr(conversation_routes, "_dossier_or_404", lambda *a, **k: None)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.write"})):
        missing = client.post(
            f"/api/v1/dossiers/{dossier_id}/conversations",
            json={"title": "x"},
        )
    assert missing.status_code == 404
    assert missing.get_json()["code"] == "not_found"

    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )

    def _boom(*a: Any, **k: Any) -> Any:
        raise ConversationError(
            "Título inválido",
            errors={"title": ["too long"]},
        )

    monkeypatch.setattr(conversation_routes, "create_conversation", _boom)
    monkeypatch.setattr(conversation_routes.db.session, "rollback", lambda: None)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.write"})):
        bad = client.post(
            f"/api/v1/dossiers/{dossier_id}/conversations",
            json={"title": "x"},
        )
    assert bad.status_code == 422
    body = bad.get_json()
    assert body["code"] == "validation_error"
    assert "Título inválido" in body["detail"]


def test_list_conversations_http_and_bad_limit(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: list que ignora el cap o rompe con limit no numérico."""

    dossier_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    body = _conversation_body(dossier_id=dossier_id, tenant_id=tenant_id, actor_id=actor_id)
    seen_limits: list[int] = []

    def _list(*_a: Any, **kwargs: Any) -> list[Any]:
        seen_limits.append(int(kwargs.get("limit") or 0))
        return [SimpleNamespace(id=body["id"])]

    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )
    monkeypatch.setattr(conversation_routes, "list_conversations", _list)
    monkeypatch.setattr(conversation_routes, "serialize_conversation", lambda c: body)
    with _authenticated_http_probe(
        app, monkeypatch, frozenset({"dossier.read"}), tenant_id=tenant_id
    ):
        ok = client.get(f"/api/v1/dossiers/{dossier_id}/conversations?limit=5")
        bad = client.get(f"/api/v1/dossiers/{dossier_id}/conversations?limit=nope")
    assert ok.status_code == 200
    assert ok.get_json()["items"][0]["id"] == body["id"]
    assert bad.status_code == 200
    assert seen_limits == [5, 20]  # invalid → default 20


# ---------------------------------------------------------------------------
# conversation_routes — enqueue (Preguntar) + get/list messages + job states
# ---------------------------------------------------------------------------


def test_enqueue_message_http_202_publishes_after_commit(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: 202 sin publish_job (job huérfano en cola nunca) o status ≠ queued."""

    dossier_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    message = _message_ns(
        dossier_id=dossier_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        status="queued",
    )
    job = SimpleNamespace(id=uuid.uuid4(), status="queued")
    published: list[Any] = []
    commits: list[str] = []

    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )
    monkeypatch.setattr(
        conversation_routes,
        "enqueue_user_message",
        lambda *a, **k: (message, job),
    )
    monkeypatch.setattr(
        conversation_routes,
        "serialize_message",
        lambda m: serialize_message(m),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(conversation_routes.db.session, "commit", lambda: commits.append("commit"))
    monkeypatch.setattr(
        "opn_oracle.jobs.service.publish_job",
        lambda j: published.append(j),
    )
    with _authenticated_http_probe(
        app, monkeypatch, frozenset({"ai.execute"}), tenant_id=tenant_id
    ):
        response = client.post(
            f"/api/v1/dossiers/{dossier_id}/conversations/{conversation_id}/messages",
            json={"content_text": "¿Qué riesgos hay en Capgemini?"},
            headers={"Idempotency-Key": "idem-ask-001"},
        )
    assert response.status_code == 202, response.get_data(as_text=True)[:500]
    data = response.get_json()
    assert data["job_id"] == str(job.id)
    assert data["message_id"] == str(message.id)
    assert data["status"] == "queued"
    assert data["message"]["status"] == "queued"
    assert commits == ["commit"]
    assert published == [job]


def test_enqueue_message_http_errors_404_409_422(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: mapear Conflict→500 o tragarse errors del ConversationError."""

    dossier_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )
    monkeypatch.setattr(conversation_routes.db.session, "rollback", lambda: None)

    def _not_found(*a: Any, **k: Any) -> Any:
        raise ConversationNotFound("Conversación no encontrada.")

    monkeypatch.setattr(conversation_routes, "enqueue_user_message", _not_found)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"ai.execute"})):
        r404 = client.post(
            f"/api/v1/dossiers/{dossier_id}/conversations/{conversation_id}/messages",
            json={"content_text": "hola"},
        )
    assert r404.status_code == 404
    assert r404.get_json()["code"] == "not_found"

    def _conflict(*a: Any, **k: Any) -> Any:
        raise ConversationConflict("Ya hay una respuesta en curso.")

    monkeypatch.setattr(conversation_routes, "enqueue_user_message", _conflict)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"ai.execute"})):
        r409 = client.post(
            f"/api/v1/dossiers/{dossier_id}/conversations/{conversation_id}/messages",
            json={"content_text": "hola"},
        )
    assert r409.status_code == 409
    assert r409.get_json()["code"] == "conflict"

    rejected = ["11111111-2222-3333-4444-555555555555"]
    detail = format_allowlist_rejection(rejected, [str(uuid.uuid4()) for _ in range(3)])

    def _allowlist(*a: Any, **k: Any) -> Any:
        # Route maps ConversationError → 422 with detail (accept-path validation
        # or any ConversationError raised before/around enqueue).
        raise ConversationError(detail)

    monkeypatch.setattr(conversation_routes, "enqueue_user_message", _allowlist)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"ai.execute"})):
        r422 = client.post(
            f"/api/v1/dossiers/{dossier_id}/conversations/{conversation_id}/messages",
            json={"content_text": "hola"},
        )
    assert r422.status_code == 422
    body = r422.get_json()
    assert body["code"] == "validation_error"
    assert rejected[0] in body["detail"]
    assert "allowlist_size=3" in body["detail"]


def test_get_message_http_job_states(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: poll de mensaje que no expone status failed+causa / succeeded."""

    dossier_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    states = {
        "queued": _message_ns(
            dossier_id=dossier_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            status="queued",
        ),
        "succeeded": _message_ns(
            dossier_id=dossier_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            status="succeeded",
            answer_payload={
                "text": "Resumen provisional.",
                "mutates_intent": False,
                "mutates_memory_facts": False,
            },
        ),
        "failed": _message_ns(
            dossier_id=dossier_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            status="failed",
            error_code="conversation_error",
            error_message=format_allowlist_rejection(
                ["abc-id-rejected"],
                [str(uuid.uuid4()) for _ in range(7)],
            ),
        ),
    }
    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )
    monkeypatch.setattr(
        conversation_routes,
        "serialize_message",
        lambda m: serialize_message(m),  # type: ignore[arg-type]
    )

    def _bind_message(msg: Any) -> Any:
        def _get(*_a: Any, **_k: Any) -> Any:
            return msg

        return _get

    for label, message in states.items():
        monkeypatch.setattr(conversation_routes, "get_message", _bind_message(message))
        with _authenticated_http_probe(
            app, monkeypatch, frozenset({"dossier.read"}), tenant_id=tenant_id
        ):
            response = client.get(
                f"/api/v1/dossiers/{dossier_id}/conversations/"
                f"{conversation_id}/messages/{message.id}"
            )
        assert response.status_code == 200, f"{label}: {response.get_data(as_text=True)[:300]}"
        data = response.get_json()
        assert data["status"] == label
        if label == "failed":
            assert data["error_code"] == "conversation_error"
            assert "abc-id-rejected" in data["error_message"]
            assert "allowlist_size=7" in data["error_message"]
        if label == "succeeded":
            assert data["answer_payload"]["mutates_intent"] is False


def test_get_message_http_404(app: Any, client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: 500 al pedir un message_id de otro hilo/tenant."""

    dossier_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    message_id = uuid.uuid4()
    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )

    def _missing(*a: Any, **k: Any) -> Any:
        raise ConversationNotFound("Mensaje no encontrado.")

    monkeypatch.setattr(conversation_routes, "get_message", _missing)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.read"})):
        response = client.get(
            f"/api/v1/dossiers/{dossier_id}/conversations/{conversation_id}/messages/{message_id}"
        )
    assert response.status_code == 404
    assert response.get_json()["code"] == "not_found"


def test_list_messages_http_and_not_found(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: list messages sin 404 de conversación o limit basura → 500."""

    dossier_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    msg = _message_ns(
        dossier_id=dossier_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        status="queued",
    )
    seen: list[int] = []

    def _list(*_a: Any, **kwargs: Any) -> list[Any]:
        seen.append(int(kwargs.get("limit") or 0))
        return [msg]

    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )
    monkeypatch.setattr(conversation_routes, "list_messages", _list)
    monkeypatch.setattr(
        conversation_routes,
        "serialize_message",
        lambda m: serialize_message(m),  # type: ignore[arg-type]
    )
    with _authenticated_http_probe(
        app, monkeypatch, frozenset({"dossier.read"}), tenant_id=tenant_id
    ):
        ok = client.get(
            f"/api/v1/dossiers/{dossier_id}/conversations/{conversation_id}/messages?limit=bad"
        )
    assert ok.status_code == 200
    assert ok.get_json()["items"][0]["status"] == "queued"
    assert seen == [50]  # default on bad limit

    def _missing(*_a: Any, **_k: Any) -> list[Any]:
        raise ConversationNotFound("Conversación no encontrada.")

    monkeypatch.setattr(conversation_routes, "list_messages", _missing)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.read"})):
        missing = client.get(
            f"/api/v1/dossiers/{dossier_id}/conversations/{conversation_id}/messages"
        )
    assert missing.status_code == 404


# ---------------------------------------------------------------------------
# Tenant / permission boundaries
# ---------------------------------------------------------------------------


def test_permission_denied_without_ai_execute(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: enqueue Preguntar con solo dossier.read (sin ai.execute)."""

    dossier_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.read"})):
        response = client.post(
            f"/api/v1/dossiers/{dossier_id}/conversations/{conversation_id}/messages",
            json={"content_text": "pregunta sin permiso"},
        )
    assert response.status_code in {401, 403}


def test_permission_denied_without_dossier_write(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: create conversation con solo dossier.read."""

    dossier_id = uuid.uuid4()
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.read"})):
        response = client.post(
            f"/api/v1/dossiers/{dossier_id}/conversations",
            json={"title": "sin write"},
        )
    assert response.status_code in {401, 403}


def test_dossier_inaccessible_is_404_not_leak(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: expediente de otro tenant devuelve 403 filtrable o 500."""

    dossier_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    monkeypatch.setattr(conversation_routes, "_dossier_or_404", lambda *a, **k: None)
    with _authenticated_http_probe(
        app, monkeypatch, frozenset({"dossier.read", "ai.execute", "dossier.write"})
    ):
        listed = client.get(f"/api/v1/dossiers/{dossier_id}/conversations")
        enqueued = client.post(
            f"/api/v1/dossiers/{dossier_id}/conversations/{conversation_id}/messages",
            json={"content_text": "x"},
        )
        got = client.get(
            f"/api/v1/dossiers/{dossier_id}/conversations/{conversation_id}/messages/{uuid.uuid4()}"
        )
    assert listed.status_code == 404
    assert listed.get_json()["code"] == "not_found"
    assert enqueued.status_code == 404
    assert got.status_code == 404


# ---------------------------------------------------------------------------
# Custom brief list residual on the same blueprint (cheap, same module)
# ---------------------------------------------------------------------------


def test_list_custom_briefs_http(app: Any, client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: list custom briefs que no rehidrata items tras tab close."""

    dossier_id = uuid.uuid4()
    brief = {
        "id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "dossier_id": str(dossier_id),
        "title": "Brief",
        "status": "draft",
        "plan_status": "proposed",
    }
    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )
    monkeypatch.setattr(
        conversation_routes,
        "list_custom_briefs",
        lambda *a, **k: [SimpleNamespace(id=brief["id"])],
    )
    monkeypatch.setattr(conversation_routes, "serialize_custom_brief", lambda r: brief)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"report.read"})):
        response = client.get(f"/api/v1/dossiers/{dossier_id}/reports/custom?limit=xx")
    assert response.status_code == 200
    assert response.get_json()["items"][0]["id"] == brief["id"]


def test_create_conversation_not_found_maps_404(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: create_conversation NotFound → 500 en vez de problem 404."""

    dossier_id = uuid.uuid4()
    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )

    def _missing(*a: Any, **k: Any) -> Any:
        raise ConversationNotFound("Expediente no encontrado en servicio.")

    monkeypatch.setattr(conversation_routes, "create_conversation", _missing)
    monkeypatch.setattr(conversation_routes.db.session, "rollback", lambda: None)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.write"})):
        response = client.post(
            f"/api/v1/dossiers/{dossier_id}/conversations",
            json={"title": "x"},
        )
    assert response.status_code == 404
    assert response.get_json()["code"] == "not_found"


def test_create_custom_brief_http_202_and_errors(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: create brief sin publish post-commit o conflict→500."""

    from opn_oracle.oracle.custom_reports import (
        CustomReportConflict,
        CustomReportError,
        CustomReportNotFound,
    )

    dossier_id = uuid.uuid4()
    report_id = uuid.uuid4()
    job = SimpleNamespace(id=uuid.uuid4())
    body = {
        "id": str(report_id),
        "tenant_id": str(uuid.uuid4()),
        "dossier_id": str(dossier_id),
        "title": "Brief libre",
        "status": "draft",
        "plan_status": "queued",
        "report_type": "custom_assistant",
        "template_key": "custom_assistant_brief",
        "template_version": "v1",
        "generation_version": 1,
        "brief_request": "resume el expediente",
        "requested_by_user_id": str(uuid.uuid4()),
    }
    report = SimpleNamespace(id=report_id, status="draft", background_job_id=job.id)
    published: list[Any] = []
    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )
    monkeypatch.setattr(
        conversation_routes,
        "create_custom_report_brief",
        lambda *a, **k: (report, job),
    )
    monkeypatch.setattr(conversation_routes, "serialize_custom_brief", lambda r: body)
    monkeypatch.setattr(conversation_routes.db.session, "commit", lambda: None)
    monkeypatch.setattr(
        "opn_oracle.jobs.service.publish_job",
        lambda j: published.append(j),
    )
    with _authenticated_http_probe(app, monkeypatch, frozenset({"report.generate"})):
        ok = client.post(
            f"/api/v1/dossiers/{dossier_id}/reports/custom",
            json={"brief_request": "resume el expediente"},
            headers={"Idempotency-Key": "brief-idem-1"},
        )
    assert ok.status_code == 202, ok.get_data(as_text=True)[:400]
    data = ok.get_json()
    assert data["job_id"] == str(job.id)
    assert data["report_id"] == str(report_id)
    assert data["plan_status"] == "queued"
    assert published == [job]

    monkeypatch.setattr(conversation_routes.db.session, "rollback", lambda: None)

    def _nf(*a: Any, **k: Any) -> Any:
        raise CustomReportNotFound("no brief")

    monkeypatch.setattr(conversation_routes, "create_custom_report_brief", _nf)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"report.generate"})):
        r404 = client.post(
            f"/api/v1/dossiers/{dossier_id}/reports/custom",
            json={"brief_request": "x"},
        )
    assert r404.status_code == 404

    def _cf(*a: Any, **k: Any) -> Any:
        raise CustomReportConflict("idempotency conflict")

    monkeypatch.setattr(conversation_routes, "create_custom_report_brief", _cf)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"report.generate"})):
        r409 = client.post(
            f"/api/v1/dossiers/{dossier_id}/reports/custom",
            json={"brief_request": "x"},
        )
    assert r409.status_code == 409

    def _ve(*a: Any, **k: Any) -> Any:
        raise CustomReportError("brief vacío", errors={"brief_request": ["required"]})

    monkeypatch.setattr(conversation_routes, "create_custom_report_brief", _ve)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"report.generate"})):
        r422 = client.post(
            f"/api/v1/dossiers/{dossier_id}/reports/custom",
            json={"brief_request": "x"},
        )
    assert r422.status_code == 422


def test_get_custom_brief_http_200_and_404(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: poll de plan_status que 500 cuando el brief no existe."""

    from opn_oracle.oracle.custom_reports import CustomReportNotFound

    dossier_id = uuid.uuid4()
    report_id = uuid.uuid4()
    body = {
        "id": str(report_id),
        "tenant_id": str(uuid.uuid4()),
        "dossier_id": str(dossier_id),
        "title": "Brief",
        "status": "draft",
        "plan_status": "proposed",
        "report_type": "custom_assistant",
        "template_key": "custom_assistant_brief",
        "template_version": "v1",
        "generation_version": 1,
        "brief_request": "x",
        "requested_by_user_id": str(uuid.uuid4()),
    }
    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )
    monkeypatch.setattr(
        conversation_routes,
        "get_custom_brief",
        lambda *a, **k: SimpleNamespace(id=report_id),
    )
    monkeypatch.setattr(conversation_routes, "serialize_custom_brief", lambda r: body)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"report.read"})):
        ok = client.get(f"/api/v1/dossiers/{dossier_id}/reports/custom/{report_id}")
    assert ok.status_code == 200
    assert ok.get_json()["plan_status"] == "proposed"

    def _missing(*a: Any, **k: Any) -> Any:
        raise CustomReportNotFound("brief missing")

    monkeypatch.setattr(conversation_routes, "get_custom_brief", _missing)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"report.read"})):
        bad = client.get(f"/api/v1/dossiers/{dossier_id}/reports/custom/{report_id}")
    assert bad.status_code == 404


def test_edit_plan_http_with_bad_if_match_and_illegal(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: If-Match basura no parseada o IllegalTransition→500."""

    from opn_oracle.oracle.custom_report_lifecycle import IllegalTransition

    dossier_id = uuid.uuid4()
    report_id = uuid.uuid4()
    body = {
        "id": str(report_id),
        "tenant_id": str(uuid.uuid4()),
        "dossier_id": str(dossier_id),
        "title": "Brief",
        "status": "draft",
        "plan_status": "proposed",
        "report_type": "custom_assistant",
        "template_key": "custom_assistant_brief",
        "template_version": "v1",
        "generation_version": 1,
        "version": 2,
        "brief_request": "x",
        "proposed_plan": {"sections": []},
        "requested_by_user_id": str(uuid.uuid4()),
    }
    seen_version: list[Any] = []

    def _edit(*_a: Any, **kwargs: Any) -> Any:
        seen_version.append(kwargs.get("expected_version"))
        return SimpleNamespace(id=report_id, version=2)

    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )
    monkeypatch.setattr(conversation_routes, "edit_plan", _edit)
    monkeypatch.setattr(conversation_routes, "serialize_custom_brief", lambda r: body)
    monkeypatch.setattr(conversation_routes.db.session, "commit", lambda: None)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"report.generate"})):
        ok = client.post(
            f"/api/v1/dossiers/{dossier_id}/reports/custom/{report_id}/plan/edit",
            json={"proposed_plan": {"sections": ["a"]}},
            headers={"If-Match": "not-an-int"},
        )
    assert ok.status_code == 200
    assert seen_version == [None]  # bad If-Match → expected_version=None

    def _illegal(*a: Any, **k: Any) -> Any:
        raise IllegalTransition("plan no editable en este estado")

    monkeypatch.setattr(conversation_routes, "edit_plan", _illegal)
    monkeypatch.setattr(conversation_routes.db.session, "rollback", lambda: None)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"report.generate"})):
        bad = client.post(
            f"/api/v1/dossiers/{dossier_id}/reports/custom/{report_id}/plan/edit",
            json={"proposed_plan": {"sections": ["a"]}},
            headers={"If-Match": 'W/"2"'},
        )
    assert bad.status_code == 409
    assert bad.get_json()["code"] == "illegal_transition"


def test_reject_cancel_download_success_paths(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: cancel/reject/download listos que no devuelven body/headers."""

    dossier_id = uuid.uuid4()
    report_id = uuid.uuid4()
    body = {
        "id": str(report_id),
        "tenant_id": str(uuid.uuid4()),
        "dossier_id": str(dossier_id),
        "title": "Brief",
        "status": "cancelled",
        "plan_status": "rejected",
        "report_type": "custom_assistant",
        "template_key": "custom_assistant_brief",
        "template_version": "v1",
        "generation_version": 1,
        "version": 5,
        "brief_request": "x",
        "requested_by_user_id": str(uuid.uuid4()),
    }
    report = SimpleNamespace(id=report_id, version=5, options={"lifecycle_state": "rejected"})
    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )
    monkeypatch.setattr(conversation_routes, "reject_plan", lambda *a, **k: report)
    monkeypatch.setattr(conversation_routes, "cancel_report", lambda *a, **k: report)
    monkeypatch.setattr(conversation_routes, "serialize_custom_brief", lambda r: body)
    monkeypatch.setattr(conversation_routes.db.session, "commit", lambda: None)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"report.generate"})):
        rej = client.post(
            f"/api/v1/dossiers/{dossier_id}/reports/custom/{report_id}/plan/reject",
            json={"reason": "no aplica"},
            headers={"If-Match": 'W/"4"'},
        )
        cancel = client.post(
            f"/api/v1/dossiers/{dossier_id}/reports/custom/{report_id}/cancel",
            headers={"If-Match": 'W/"5"'},
        )
    assert rej.status_code == 200
    assert cancel.status_code == 200

    monkeypatch.setattr(
        conversation_routes,
        "get_custom_brief",
        lambda *a, **k: report,
    )
    monkeypatch.setattr(
        conversation_routes,
        "get_downloadable_artifact",
        lambda r: {
            "content": {"title": "ok"},
            "sha256": "deadbeef",
            "byte_size": 12,
        },
    )
    with _authenticated_http_probe(app, monkeypatch, frozenset({"report.read"})):
        dl = client.get(f"/api/v1/dossiers/{dossier_id}/reports/custom/{report_id}/download")
    assert dl.status_code == 200
    assert dl.headers.get("X-Content-SHA256") == "deadbeef"
    assert "report-" in (dl.headers.get("Content-Disposition") or "")


def test_dossier_or_404_real_lookup_and_access(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: _dossier_or_404 que ignora tenant o write=True sin acceso."""

    dossier_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    actor = User(
        id=uuid.uuid4(),
        email="access@example.com",
        display_name="Access",
        status="active",
    )
    dossier = SimpleNamespace(id=dossier_id, tenant_id=tenant_id)
    monkeypatch.setattr(conversation_routes, "current_user", actor)

    class _Sess:
        """Minimal scoped-session stand-in (scalar + call + teardown hooks)."""

        def __init__(self, value: Any) -> None:
            self._value = value

        def scalar(self, *_a: Any, **_k: Any) -> Any:
            return self._value

        def __call__(self) -> Any:
            return self

        def remove(self) -> None:
            return None

    monkeypatch.setattr(conversation_routes.db, "session", _Sess(dossier))
    monkeypatch.setattr(
        conversation_routes,
        "dossier_accessible",
        lambda *_a, **kwargs: bool(kwargs.get("write") is False),
    )
    with app.test_request_context("/"):
        g.active_tenant_id = tenant_id
        # read allowed
        assert conversation_routes._dossier_or_404(dossier_id, write=False) is dossier
        # write denied by policy → None
        assert conversation_routes._dossier_or_404(dossier_id, write=True) is None

    # missing dossier
    monkeypatch.setattr(conversation_routes.db, "session", _Sess(None))
    with app.test_request_context("/"):
        g.active_tenant_id = tenant_id
        assert conversation_routes._dossier_or_404(dossier_id, write=False) is None
