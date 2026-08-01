"""Behavioral unit coverage for MEMSOL conversations and custom brief services."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from opn_oracle.integrations.memory_context import (
    MemoryContextDisabled,
    MockMemoryContextAdapter,
    empty_coverage_manifest,
)
from opn_oracle.jobs.service import prepare_retry, request_cancel
from opn_oracle.oracle import conversations as conv
from opn_oracle.oracle import custom_reports as briefs
from opn_oracle.tenants.context import TenantContext, tenant_context


def _tenant() -> uuid.UUID:
    return uuid.uuid4()


def _dossier(tenant_id: uuid.UUID, **kw: Any) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "title": "Expediente MEMSOL",
        "status": "active",
        "current_intent_revision_id": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _conversation(tenant_id: uuid.UUID, dossier_id: uuid.UUID, **kw: Any) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "dossier_id": dossier_id,
        "status": "open",
        "title": "Ask",
        "created_by_user_id": uuid.uuid4(),
        "intent_revision_id": None,
        "created_at": datetime(2026, 7, 31, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 31, tzinfo=UTC),
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _message(
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    conversation_id: uuid.UUID,
    **kw: Any,
) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "dossier_id": dossier_id,
        "conversation_id": conversation_id,
        "role": "user",
        "status": "queued",
        "sequence": 1,
        "content_text": "¿Estado del control de calidad?",
        "answer_payload": {},
        "coverage_manifest": {},
        "background_job_id": None,
        "created_by_user_id": uuid.uuid4(),
        "error_code": None,
        "error_message": None,
        "created_at": datetime(2026, 7, 31, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 31, tzinfo=UTC),
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _job(**kw: Any) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "cancel_requested": False,
        "correlation_id": "corr-memsol",
        "job_type": conv.DOSSIER_QUESTION_JOB,
        "version": 1,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _ctx(tenant_id: uuid.UUID | None = None) -> TenantContext:
    return TenantContext(tenant_id=tenant_id or _tenant(), actor_id=uuid.uuid4())


def test_message_transition_matrix_and_illegal() -> None:
    assert conv.can_transition_message("queued", "running") is True
    assert conv.can_transition_message("queued", "cancelled") is True
    assert conv.can_transition_message("running", "succeeded") is True
    assert conv.can_transition_message("succeeded", "running") is False
    assert conv.can_transition_message("nope", "queued") is False
    message = _message(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), status="succeeded")
    with pytest.raises(conv.ConversationConflict):
        conv.transition_message_status(message, "running")


def test_serialize_conversation_and_message_null_optionals() -> None:
    tenant_id = _tenant()
    dossier_id = uuid.uuid4()
    conversation = _conversation(
        tenant_id, dossier_id, intent_revision_id=None, created_at=None, updated_at=None
    )
    payload = conv.serialize_conversation(conversation)
    assert payload["id"] == str(conversation.id)
    assert payload["intent_revision_id"] is None
    assert payload["created_at"] is None

    message = _message(
        tenant_id,
        dossier_id,
        conversation.id,
        background_job_id=None,
        created_by_user_id=None,
        created_at=None,
        updated_at=None,
    )
    m = conv.serialize_message(message)
    assert m["background_job_id"] is None
    assert m["created_by_user_id"] is None
    assert m["status"] == "queued"


def test_apply_answer_cancel_fail_paths() -> None:
    tenant_id = _tenant()
    dossier_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    message = _message(tenant_id, dossier_id, conversation_id, role="assistant")
    with pytest.raises(conv.ConversationError):
        conv.apply_assistant_answer(message, answer_text="x")

    user = _message(tenant_id, dossier_id, conversation_id, status="queued")
    conv.apply_assistant_answer(
        user,
        answer_text="ok",
        answer_payload={"provider_path": "deterministic"},
        coverage_manifest=empty_coverage_manifest(),
    )
    assert user.status == "succeeded"
    assert user.answer_payload["mutates_intent"] is False
    assert user.coverage_manifest.get("version") == "coverage_manifest.v1"

    terminal = _message(tenant_id, dossier_id, conversation_id, status="succeeded")
    with pytest.raises(conv.ConversationConflict):
        conv.mark_message_failed(terminal, error_code="x", error_message="y")

    failable = _message(tenant_id, dossier_id, conversation_id, status="queued")
    conv.mark_message_failed(failable, error_code="memory_context_error", error_message="boom")
    assert failable.status == "failed"
    assert failable.error_code == "memory_context_error"

    cancellable = _message(tenant_id, dossier_id, conversation_id, status="running")
    conv.cancel_message(cancellable)
    assert cancellable.status == "cancelled"
    already = _message(tenant_id, dossier_id, conversation_id, status="cancelled")
    assert conv.cancel_message(already) is already


def test_payload_digest_is_stable() -> None:
    a = conv.payload_digest_preview({"b": 1, "a": 2})
    b = conv.payload_digest_preview({"a": 2, "b": 1})
    assert a == b
    assert len(a) == 64


def test_create_conversation_requires_dossier_and_audits(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = _tenant()
    actor = uuid.uuid4()
    dossier = _dossier(tenant_id)
    session = MagicMock()
    session.scalar.return_value = dossier
    audits: list[str] = []
    monkeypatch.setattr(
        conv,
        "append_audit_event",
        lambda *_a, **kw: audits.append(str(kw.get("action"))),
    )
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=actor)):
        conversation = conv.create_conversation(
            session,
            dossier_id=dossier.id,
            actor_id=actor,
            title="  Hilo  ",
        )
    assert conversation.status == "open"
    assert conversation.title == "Hilo"
    assert conversation.dossier_id == dossier.id
    assert "dossier.conversation.created" in audits
    session.add.assert_called()
    session.flush.assert_called()


def test_create_conversation_not_found() -> None:
    tenant_id = _tenant()
    session = MagicMock()
    session.scalar.return_value = None
    with (
        tenant_context(_ctx(tenant_id)),
        pytest.raises(conv.ConversationNotFound),
    ):
        conv.create_conversation(session, dossier_id=uuid.uuid4(), actor_id=uuid.uuid4())


def test_enqueue_validates_idempotency_and_question() -> None:
    tenant_id = _tenant()
    session = MagicMock()
    with tenant_context(_ctx(tenant_id)):
        with pytest.raises(conv.ConversationError) as short_key:
            conv.enqueue_user_message(
                session,
                dossier_id=uuid.uuid4(),
                conversation_id=uuid.uuid4(),
                actor_id=uuid.uuid4(),
                content_text="hola",
                idempotency_key="short",
            )
        assert "idempotency_key" in short_key.value.errors
        with pytest.raises(conv.ConversationError) as empty_q:
            conv.enqueue_user_message(
                session,
                dossier_id=uuid.uuid4(),
                conversation_id=uuid.uuid4(),
                actor_id=uuid.uuid4(),
                content_text="  ",
                idempotency_key="idempotency-key-ok",
            )
        assert "content_text" in empty_q.value.errors


def test_enqueue_rejects_closed_conversation(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = _tenant()
    dossier_id = uuid.uuid4()
    conversation = _conversation(tenant_id, dossier_id, status="archived")
    session = MagicMock()
    monkeypatch.setattr(conv, "_load_conversation", lambda *_a, **_k: conversation)
    with (
        tenant_context(_ctx(tenant_id)),
        pytest.raises(conv.ConversationConflict),
    ):
        conv.enqueue_user_message(
            session,
            dossier_id=dossier_id,
            conversation_id=conversation.id,
            actor_id=uuid.uuid4(),
            content_text="pregunta válida",
            idempotency_key="idempotency-key-01",
        )


def test_enqueue_idempotent_return_and_new_message(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = _tenant()
    actor = uuid.uuid4()
    dossier_id = uuid.uuid4()
    conversation = _conversation(tenant_id, dossier_id, status="open")
    existing_message = _message(tenant_id, dossier_id, conversation.id)
    existing_job = SimpleNamespace(
        id=uuid.uuid4(),
        resource_type="dossier_message",
        resource_id=existing_message.id,
    )
    session = MagicMock()
    session.scalar.side_effect = [existing_job, existing_message]
    monkeypatch.setattr(conv, "_load_conversation", lambda *_a, **_k: conversation)
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=actor)):
        message, job = conv.enqueue_user_message(
            session,
            dossier_id=dossier_id,
            conversation_id=conversation.id,
            actor_id=actor,
            content_text="misma pregunta",
            idempotency_key="idempotency-key-02",
        )
    assert message is existing_message
    assert job is existing_job

    staged = SimpleNamespace(id=uuid.uuid4())
    audits: list[str] = []
    session3 = MagicMock()
    session3.scalar.side_effect = [None, 4]
    monkeypatch.setattr(conv, "_load_conversation", lambda *_a, **_k: conversation)
    monkeypatch.setattr(conv, "stage_job", lambda *a, **k: staged)
    monkeypatch.setattr(
        conv,
        "append_audit_event",
        lambda *_a, **kw: audits.append(str(kw.get("action"))),
    )
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=actor)):
        message2, job2 = conv.enqueue_user_message(
            session3,
            dossier_id=dossier_id,
            conversation_id=conversation.id,
            actor_id=actor,
            content_text="nueva pregunta",
            idempotency_key="idempotency-key-03",
        )
    assert job2 is staged
    assert message2.background_job_id == staged.id
    assert message2.sequence == 5
    assert message2.content_text == "nueva pregunta"
    assert "dossier.conversation.message.enqueued" in audits
    session3.add.assert_called()


def test_process_invalid_payload_and_tenant_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = _tenant()
    session = MagicMock()
    job = _job()
    with (
        tenant_context(_ctx(tenant_id)),
        pytest.raises(conv.ConversationError),
    ):
        conv.process_dossier_question_answer(session, {}, job)

    other_tenant = uuid.uuid4()
    message = _message(other_tenant, uuid.uuid4(), uuid.uuid4())
    monkeypatch.setattr(conv, "get_message", lambda *a, **k: message)
    with (
        tenant_context(_ctx(tenant_id)),
        pytest.raises(conv.ConversationNotFound),
    ):
        conv.process_dossier_question_answer(
            session,
            {
                "message_id": str(message.id),
                "conversation_id": str(message.conversation_id),
                "dossier_id": str(message.dossier_id),
            },
            job,
        )


def test_process_idempotent_terminal_and_wrong_status(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = _tenant()
    message = _message(tenant_id, uuid.uuid4(), uuid.uuid4(), status="succeeded")
    session = MagicMock()
    job = _job()
    monkeypatch.setattr(conv, "get_message", lambda *a, **k: message)
    with tenant_context(_ctx(tenant_id)):
        out = conv.process_dossier_question_answer(
            session,
            {
                "message_id": str(message.id),
                "conversation_id": str(message.conversation_id),
                "dossier_id": str(message.dossier_id),
            },
            job,
        )
    assert out["idempotent"] is True

    running = _message(tenant_id, uuid.uuid4(), uuid.uuid4(), status="running")
    monkeypatch.setattr(conv, "get_message", lambda *a, **k: running)
    with (
        tenant_context(_ctx(tenant_id)),
        pytest.raises(conv.ConversationConflict),
    ):
        conv.process_dossier_question_answer(
            session,
            {
                "message_id": str(running.id),
                "conversation_id": str(running.conversation_id),
                "dossier_id": str(running.dossier_id),
            },
            job,
        )


def test_process_memory_disabled_and_items_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = _tenant()
    dossier_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    message = _message(tenant_id, dossier_id, conversation_id, status="queued")
    session = MagicMock()
    job = _job()
    audits: list[str] = []
    monkeypatch.setattr(conv, "get_message", lambda *a, **k: message)
    monkeypatch.setattr(conv, "_signal_ai_enabled", lambda: False)
    monkeypatch.setattr(
        conv,
        "append_audit_event",
        lambda *_a, **kw: audits.append(str(kw.get("action"))),
    )

    class Disabled:
        def retrieve(self, *a: Any, **k: Any) -> dict[str, Any]:
            raise MemoryContextDisabled("off")

    with tenant_context(_ctx(tenant_id)):
        out = conv.process_dossier_question_answer(
            session,
            {
                "message_id": str(message.id),
                "conversation_id": str(conversation_id),
                "dossier_id": str(dossier_id),
            },
            job,
            memory_adapter=Disabled(),
        )
    assert out["status"] == "succeeded"
    assert message.answer_payload["provider_path"] == "deterministic"

    message2 = _message(tenant_id, dossier_id, conversation_id, status="queued")
    monkeypatch.setattr(conv, "get_message", lambda *a, **k: message2)

    class WithItems:
        def retrieve(self, *a: Any, **k: Any) -> dict[str, Any]:
            return {
                "items": [{"text": "Hito de calidad aprobado el 2026-07-15"}],
                "coverage_manifest": empty_coverage_manifest(requested=["memory.mock"]),
                "policy_version": "mock.v1",
            }

    with tenant_context(_ctx(tenant_id)):
        out2 = conv.process_dossier_question_answer(
            session,
            {
                "message_id": str(message2.id),
                "conversation_id": str(conversation_id),
                "dossier_id": str(dossier_id),
            },
            job,
            memory_adapter=WithItems(),
        )
    assert out2["item_count"] == 1
    assert "Hito de calidad" in message2.answer_payload["text"]
    assert "dossier.conversation.message.answered" in audits


def test_process_memory_error_marks_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = _tenant()
    message = _message(tenant_id, uuid.uuid4(), uuid.uuid4(), status="queued")
    session = MagicMock()
    job = _job()
    monkeypatch.setattr(conv, "get_message", lambda *a, **k: message)

    class Boom:
        def retrieve(self, *a: Any, **k: Any) -> dict[str, Any]:
            raise RuntimeError("adapter down")

    with (
        tenant_context(_ctx(tenant_id)),
        pytest.raises(conv.ConversationError),
    ):
        conv.process_dossier_question_answer(
            session,
            {
                "message_id": str(message.id),
                "conversation_id": str(message.conversation_id),
                "dossier_id": str(message.dossier_id),
            },
            job,
            memory_adapter=Boom(),
        )
    assert message.status == "failed"
    assert message.error_code == "memory_context_error"


def test_process_cancel_after_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = _tenant()
    message = _message(tenant_id, uuid.uuid4(), uuid.uuid4(), status="queued")
    session = MagicMock()
    job = _job(cancel_requested=False)
    monkeypatch.setattr(conv, "get_message", lambda *a, **k: message)

    class FlipCancel:
        def retrieve(self, *a: Any, **k: Any) -> dict[str, Any]:
            job.cancel_requested = True
            return {
                "items": [],
                "coverage_manifest": empty_coverage_manifest(),
                "policy_version": "mock",
            }

    with tenant_context(_ctx(tenant_id)):
        out = conv.process_dossier_question_answer(
            session,
            {
                "message_id": str(message.id),
                "conversation_id": str(message.conversation_id),
                "dossier_id": str(message.dossier_id),
            },
            job,
            memory_adapter=FlipCancel(),
        )
    assert out["cancelled"] is True
    assert message.status == "cancelled"


def test_process_signal_path_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = _tenant()
    message = _message(tenant_id, uuid.uuid4(), uuid.uuid4(), status="queued")
    session = MagicMock()
    job = _job()
    monkeypatch.setattr(conv, "get_message", lambda *a, **k: message)
    monkeypatch.setattr(conv, "_signal_ai_enabled", lambda: True)
    monkeypatch.setattr(conv, "append_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(
        conv,
        "_answer_via_signal",
        lambda *a, **k: {
            "answer_text": "Respuesta Signal",
            "answer_payload": {
                "provider_path": "signal",
                "task_key": "dossier_question_answer",
                "facts": [],
                "inferences": [],
                "recommendations": [],
            },
            "meta": {"artifact_id": str(uuid.uuid4())},
        },
    )
    with tenant_context(_ctx(tenant_id)):
        out = conv.process_dossier_question_answer(
            session,
            {
                "message_id": str(message.id),
                "conversation_id": str(message.conversation_id),
                "dossier_id": str(message.dossier_id),
            },
            job,
            memory_adapter=MockMemoryContextAdapter(),
        )
    assert out["status"] == "succeeded"
    assert message.answer_payload["provider_path"] == "signal"

    message2 = _message(tenant_id, uuid.uuid4(), uuid.uuid4(), status="queued")
    monkeypatch.setattr(conv, "get_message", lambda *a, **k: message2)

    def _boom(*a: Any, **k: Any) -> dict[str, Any]:
        raise RuntimeError("signal down")

    monkeypatch.setattr(conv, "_answer_via_signal", _boom)
    with (
        tenant_context(_ctx(tenant_id)),
        pytest.raises(conv.ConversationError),
    ):
        conv.process_dossier_question_answer(
            session,
            {
                "message_id": str(message2.id),
                "conversation_id": str(message2.conversation_id),
                "dossier_id": str(message2.dossier_id),
            },
            job,
            memory_adapter=MockMemoryContextAdapter(),
        )
    assert message2.error_code == "signal_ai_error"


def test_custom_brief_validation_and_not_found() -> None:
    tenant_id = _tenant()
    session = MagicMock()
    with tenant_context(_ctx(tenant_id)):
        with pytest.raises(briefs.CustomReportError):
            briefs.create_custom_report_brief(
                session,
                dossier_id=uuid.uuid4(),
                actor_id=uuid.uuid4(),
                brief_request="x",
                idempotency_key="short",
            )
        with pytest.raises(briefs.CustomReportError):
            briefs.create_custom_report_brief(
                session,
                dossier_id=uuid.uuid4(),
                actor_id=uuid.uuid4(),
                brief_request="  ",
                idempotency_key="idempotency-key-ok",
            )
        session.scalar.return_value = None
        with pytest.raises(briefs.CustomReportNotFound):
            briefs.get_custom_brief(
                session,
                dossier_id=uuid.uuid4(),
                report_id=uuid.uuid4(),
            )


def test_create_custom_brief_idempotent_and_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = _tenant()
    actor = uuid.uuid4()
    dossier = _dossier(tenant_id)
    monkeypatch.setattr(briefs, "_load_dossier", lambda *a, **k: dossier)

    existing_job = SimpleNamespace(id=uuid.uuid4())
    existing = SimpleNamespace(
        template_key=briefs.CUSTOM_BRIEF_TEMPLATE_KEY,
        options={"brief_request": "mismo brief"},
        background_job_id=existing_job.id,
    )
    session2 = MagicMock()
    session2.execute = MagicMock()
    session2.scalar.return_value = existing
    session2.get.return_value = existing_job
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=actor)):
        report2, job2 = briefs.create_custom_report_brief(
            session2,
            dossier_id=dossier.id,
            actor_id=actor,
            brief_request="mismo brief",
            idempotency_key="idempotency-brief-02",
        )
    assert report2 is existing
    assert job2 is existing_job

    existing.options = {"brief_request": "otro"}
    session3 = MagicMock()
    session3.execute = MagicMock()
    session3.scalar.return_value = existing
    with (
        tenant_context(TenantContext(tenant_id=tenant_id, actor_id=actor)),
        pytest.raises(briefs.CustomReportConflict),
    ):
        briefs.create_custom_report_brief(
            session3,
            dossier_id=dossier.id,
            actor_id=actor,
            brief_request="nuevo brief distinto",
            idempotency_key="idempotency-brief-03",
        )


def test_process_custom_brief_plan_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = _tenant()
    dossier_id = uuid.uuid4()
    report_id = uuid.uuid4()
    job = _job(job_type=briefs.CUSTOM_BRIEF_JOB)
    session = MagicMock()
    with (
        tenant_context(_ctx(tenant_id)),
        pytest.raises(briefs.CustomReportError),
    ):
        briefs.process_custom_brief_plan(session, {}, job)

    session.scalar.return_value = None
    with (
        tenant_context(_ctx(tenant_id)),
        pytest.raises(briefs.CustomReportNotFound),
    ):
        briefs.process_custom_brief_plan(
            session,
            {"report_id": str(report_id), "dossier_id": str(dossier_id)},
            job,
        )

    report = SimpleNamespace(
        id=report_id,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        template_key="other",
        options={},
        status="draft",
        error_code=None,
        error_message=None,
    )
    session.scalar.return_value = report
    with (
        tenant_context(_ctx(tenant_id)),
        pytest.raises(briefs.CustomReportError),
    ):
        briefs.process_custom_brief_plan(
            session,
            {"report_id": str(report_id), "dossier_id": str(dossier_id)},
            job,
        )

    report.template_key = briefs.CUSTOM_BRIEF_TEMPLATE_KEY
    report.options = {"plan_status": "proposed", "proposed_plan": {"sections": []}}
    with tenant_context(_ctx(tenant_id)):
        out = briefs.process_custom_brief_plan(
            session,
            {"report_id": str(report_id), "dossier_id": str(dossier_id)},
            job,
        )
    assert out["idempotent"] is True

    report.options = {"plan_status": "draft", "brief_request": "x" * 20}
    job.cancel_requested = True
    with tenant_context(_ctx(tenant_id)):
        out = briefs.process_custom_brief_plan(
            session,
            {"report_id": str(report_id), "dossier_id": str(dossier_id)},
            job,
        )
    assert out["cancelled"] is True
    assert report.error_code == "cancelled"

    job.cancel_requested = False
    report.options = {"plan_status": "draft", "brief_request": "Plan de control de calidad"}
    report.error_code = None
    report.error_message = None
    monkeypatch.setattr(briefs, "_signal_ai_enabled", lambda: False)
    monkeypatch.setattr(briefs, "append_audit_event", lambda *a, **k: None)
    with tenant_context(_ctx(tenant_id)):
        out = briefs.process_custom_brief_plan(
            session,
            {"report_id": str(report_id), "dossier_id": str(dossier_id)},
            job,
        )
    assert out["plan_status"] == "proposed"
    assert report.options["proposed_plan"]["provider_path"] == "deterministic"
    assert report.options["mutates_intent"] is False

    report.options = {"plan_status": "draft", "brief_request": "otro plan"}
    monkeypatch.setattr(briefs, "_signal_ai_enabled", lambda: True)

    def _boom(*a: Any, **k: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        raise RuntimeError("titan unavailable")

    monkeypatch.setattr(briefs, "_plan_via_signal", _boom)
    with (
        tenant_context(_ctx(tenant_id)),
        pytest.raises(briefs.CustomReportError),
    ):
        briefs.process_custom_brief_plan(
            session,
            {"report_id": str(report_id), "dossier_id": str(dossier_id)},
            job,
        )
    assert report.error_code == "signal_ai_error"


def test_serialize_custom_brief_and_signal_flag() -> None:
    report = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        status="draft",
        title="Brief",
        report_type=briefs.CUSTOM_BRIEF_REPORT_TYPE,
        template_key=briefs.CUSTOM_BRIEF_TEMPLATE_KEY,
        template_version="v1",
        options={"plan_status": "proposed", "proposed_plan": {"sections": [{"id": "a"}]}},
        background_job_id=uuid.uuid4(),
        error_code=None,
        error_message=None,
        created_at=datetime(2026, 7, 31, tzinfo=UTC),
        updated_at=datetime(2026, 7, 31, tzinfo=UTC),
        generation_version=1,
        classification="internal",
        confidentiality_label="Uso interno",
        requested_by_user_id=uuid.uuid4(),
    )
    data = briefs.serialize_custom_brief(report)
    assert data["plan_status"] == "proposed"
    assert data["id"] == str(report.id)
    assert briefs._signal_ai_enabled() is False


def test_job_request_cancel_and_prepare_retry_version_gate() -> None:
    job = SimpleNamespace(
        id=uuid.uuid4(),
        version=3,
        status="running",
        cancel_requested=False,
        cancel_requested_at=None,
        attempts=1,
        max_attempts=3,
        retryable=True,
        error_code=None,
        error_message=None,
        stage="running",
        not_before=None,
        finished_at=None,
        started_at=None,
        result_ref={},
        celery_task_id=None,
        execution_lease_id=None,
        lease_expires_at=None,
    )
    with pytest.raises(ValueError, match="modificado"):
        request_cancel(job, expected_version=2)
    request_cancel(job, expected_version=3)
    assert job.cancel_requested is True
    assert job.version == 4

    job2 = SimpleNamespace(
        id=uuid.uuid4(),
        version=1,
        status="failed",
        cancel_requested=False,
        cancel_requested_at=None,
        attempts=1,
        max_attempts=3,
        retryable=True,
        error_code="x",
        error_message="y",
        stage="failed",
        not_before=None,
        finished_at=datetime.now(UTC),
        started_at=None,
        result_ref={},
        celery_task_id=None,
        execution_lease_id=None,
        lease_expires_at=None,
    )
    with pytest.raises(ValueError, match="modificado"):
        prepare_retry(job2, expected_version=9)
    prepare_retry(job2, expected_version=1)
    assert job2.status == "queued"
    assert job2.stage == "manual_retry"
    assert job2.version == 2
    assert job2.error_code is None
