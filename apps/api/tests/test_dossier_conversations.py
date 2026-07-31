"""Unit tests for durable Preguntar a Oracle (MEMSOL-06)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from opn_oracle.oracle.conversations import (
    ConversationConflict,
    ConversationError,
    apply_assistant_answer,
    can_transition_message,
    create_conversation,
    enqueue_user_message,
    mark_message_failed,
    serialize_message,
    transition_message_status,
)
from opn_oracle.tenants.context import TenantContext, TenantContextMissing, tenant_context


def test_message_state_machine_allows_only_valid_transitions() -> None:
    assert can_transition_message("queued", "running")
    assert can_transition_message("queued", "cancelled")
    assert can_transition_message("running", "succeeded")
    assert can_transition_message("running", "failed")
    assert not can_transition_message("succeeded", "running")
    assert not can_transition_message("failed", "queued")
    assert not can_transition_message("cancelled", "running")
    assert not can_transition_message("queued", "succeeded")

    message = SimpleNamespace(status="queued")
    transition_message_status(message, "running")  # type: ignore[arg-type]
    assert message.status == "running"
    with pytest.raises(ConversationConflict):
        transition_message_status(message, "queued")  # type: ignore[arg-type]


def test_apply_assistant_answer_does_not_flag_intent_or_memory_mutation() -> None:
    message = SimpleNamespace(
        role="user",
        status="queued",
        answer_payload={},
        coverage_manifest={},
    )
    apply_assistant_answer(
        message,  # type: ignore[arg-type]
        answer_text="Resumen provisional sin promoción de hechos.",
        coverage_manifest={"version": "coverage_manifest.v1", "used": []},
    )
    assert message.status == "succeeded"
    assert message.answer_payload["mutates_intent"] is False
    assert message.answer_payload["mutates_memory_facts"] is False
    assert "Resumen provisional" in message.answer_payload["text"]


def test_mark_message_failed_from_queued() -> None:
    message = SimpleNamespace(status="queued", error_code=None, error_message=None)
    mark_message_failed(message, error_code="ai_timeout", error_message="timeout")  # type: ignore[arg-type]
    assert message.status == "failed"
    assert message.error_code == "ai_timeout"


def test_create_conversation_requires_tenant_context() -> None:
    session = MagicMock()
    with pytest.raises(TenantContextMissing):
        create_conversation(
            session,
            dossier_id=uuid.uuid4(),
            actor_id=uuid.uuid4(),
        )


def test_create_conversation_persists_open_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    dossier = SimpleNamespace(
        id=dossier_id,
        tenant_id=tenant_id,
        status="active",
        current_intent_revision_id=intent_id,
    )
    session = MagicMock()
    session.scalar.return_value = dossier
    audits: list[str] = []

    def _audit(*_args: Any, **kwargs: Any) -> None:
        audits.append(str(kwargs.get("action")))

    monkeypatch.setattr("opn_oracle.oracle.conversations.append_audit_event", _audit)

    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=actor_id)):
        conversation = create_conversation(
            session,
            dossier_id=dossier_id,
            actor_id=actor_id,
            title="Preguntas de mercado",
        )

    assert conversation.status == "open"
    assert conversation.dossier_id == dossier_id
    assert conversation.intent_revision_id == intent_id
    assert conversation.title == "Preguntas de mercado"
    session.add.assert_called()
    assert "dossier.conversation.created" in audits


def test_enqueue_user_message_persists_before_job_and_skips_external(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    conversation = SimpleNamespace(
        id=conversation_id,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        status="open",
    )
    job = SimpleNamespace(
        id=uuid.uuid4(),
        status="queued",
        job_type="oracle.dossier_question.answer",
    )
    session = MagicMock()
    # _load_conversation, existing job check, max sequence
    session.scalar.side_effect = [conversation, None, 0]
    added: list[Any] = []

    def _add(obj: Any) -> None:
        added.append(obj)

    session.add.side_effect = _add
    stage_calls: list[dict[str, Any]] = []
    external_calls: list[str] = []

    def _stage(task_name: str, **kwargs: Any) -> Any:
        stage_calls.append({"task_name": task_name, **kwargs})
        return job

    def _forbidden(*_a: Any, **_k: Any) -> Any:
        external_calls.append("external")
        raise AssertionError("No se deben invocar adaptadores externos en el accept path.")

    monkeypatch.setattr("opn_oracle.oracle.conversations.stage_job", _stage)
    monkeypatch.setattr("opn_oracle.oracle.conversations.append_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_context.get_memory_context_adapter",
        _forbidden,
        raising=False,
    )

    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=actor_id)):
        message, returned_job = enqueue_user_message(
            session,
            dossier_id=dossier_id,
            conversation_id=conversation_id,
            actor_id=actor_id,
            content_text="¿Qué riesgos abiertos hay en el expediente?",
            idempotency_key="idem-question-001",
            publish=False,
        )

    assert returned_job is job
    assert message.status == "queued"
    assert message.role == "user"
    assert message.background_job_id == job.id
    assert "riesgos abiertos" in message.content_text
    assert len(stage_calls) == 1
    assert stage_calls[0]["task_name"] == "oracle.dossier_question.answer"
    assert stage_calls[0]["payload"]["message_id"] == str(message.id)
    # Message must be added before stage_job returns (persist before job).
    assert any(getattr(obj, "content_text", None) for obj in added)
    assert external_calls == []


def test_enqueue_rejects_empty_question() -> None:
    tenant_id = uuid.uuid4()
    session = MagicMock()
    with (
        tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())),
        pytest.raises(ConversationError),
    ):
        enqueue_user_message(
            session,
            dossier_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            actor_id=uuid.uuid4(),
            content_text="   ",
            idempotency_key="idem-question-002",
        )


def test_serialize_message_includes_status() -> None:
    message = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        role="user",
        status="queued",
        sequence=1,
        content_text="hola",
        answer_payload={},
        coverage_manifest={},
        background_job_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
        error_code=None,
        error_message=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    payload = serialize_message(message)  # type: ignore[arg-type]
    assert payload["status"] == "queued"
    assert payload["content_text"] == "hola"
    assert payload["background_job_id"] == str(message.background_job_id)
