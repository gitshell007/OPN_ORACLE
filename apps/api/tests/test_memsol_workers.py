"""Workers reales: Preguntar a Oracle y plan de brief (residual MEMSOL)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from opn_oracle.integrations.memory_context import (
    MockMemoryContextAdapter,
    empty_coverage_manifest,
)
from opn_oracle.jobs.tasks import (
    HANDLERS,
    PermanentJobError,
    _answer_dossier_question,
    _plan_custom_brief,
)
from opn_oracle.oracle.conversations import (
    DOSSIER_QUESTION_JOB,
    apply_assistant_answer,
    process_dossier_question_answer,
)
from opn_oracle.oracle.custom_reports import (
    CUSTOM_BRIEF_JOB,
    CUSTOM_BRIEF_TEMPLATE_KEY,
    process_custom_brief_plan,
)
from opn_oracle.tenants.context import TenantContext, tenant_context


def _job(**kwargs: Any) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "cancel_requested": False,
        "correlation_id": "corr-test",
        "job_type": DOSSIER_QUESTION_JOB,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_handlers_register_memsol_job_types() -> None:
    assert DOSSIER_QUESTION_JOB in HANDLERS
    assert CUSTOM_BRIEF_JOB in HANDLERS


def test_process_question_answer_settles_with_mock_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    message_id = uuid.uuid4()
    message = SimpleNamespace(
        id=message_id,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        conversation_id=conversation_id,
        role="user",
        status="queued",
        content_text="¿Cuál es el CIF del adjudicatario?",
        answer_payload={},
        coverage_manifest={},
        error_code=None,
        error_message=None,
    )
    session = MagicMock()
    session.scalar.return_value = message
    audits: list[str] = []
    monkeypatch.setattr(
        "opn_oracle.oracle.conversations.append_audit_event",
        lambda *_a, **kwargs: audits.append(str(kwargs.get("action"))),
    )

    adapter = MockMemoryContextAdapter()
    job = _job()
    payload = {
        "message_id": str(message_id),
        "conversation_id": str(conversation_id),
        "dossier_id": str(dossier_id),
        "purpose": "question",
    }
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        result = process_dossier_question_answer(
            session,
            payload,
            job,  # type: ignore[arg-type]
            memory_adapter=adapter,
        )

    assert result["status"] == "succeeded"
    assert result["mutates_intent"] is False
    assert result["mutates_memory_facts"] is False
    assert message.status == "succeeded"
    assert message.answer_payload["mutates_intent"] is False
    assert message.answer_payload["mutates_memory_facts"] is False
    assert (
        "evidencia" in message.answer_payload["text"].lower()
        or "memoria" in message.answer_payload["text"].lower()
    )
    assert message.coverage_manifest.get("version") == "coverage_manifest.v1"
    assert adapter.calls and adapter.calls[0]["query"].startswith("¿Cuál")
    assert "dossier.conversation.message.answered" in audits


def test_process_question_answer_respects_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    message_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    message = SimpleNamespace(
        id=message_id,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        conversation_id=conversation_id,
        role="user",
        status="queued",
        content_text="pregunta",
        answer_payload={},
        coverage_manifest={},
        error_code=None,
        error_message=None,
    )
    session = MagicMock()
    session.scalar.return_value = message
    monkeypatch.setattr("opn_oracle.oracle.conversations.append_audit_event", lambda *a, **k: None)
    job = _job(cancel_requested=True)
    payload = {
        "message_id": str(message_id),
        "conversation_id": str(conversation_id),
        "dossier_id": str(dossier_id),
    }
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        result = process_dossier_question_answer(
            session,
            payload,
            job,  # type: ignore[arg-type]
            memory_adapter=MockMemoryContextAdapter(),
        )
    assert result["cancelled"] is True
    assert message.status == "cancelled"


def test_process_custom_brief_plan_proposes_without_report_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    report_id = uuid.uuid4()
    report = SimpleNamespace(
        id=report_id,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        template_key=CUSTOM_BRIEF_TEMPLATE_KEY,
        status="draft",
        options={
            "brief_request": "Necesito un informe de posicionamiento competitivo",
            "plan_status": "draft",
        },
        error_code=None,
        error_message=None,
    )
    session = MagicMock()
    session.scalar.return_value = report
    audits: list[str] = []
    monkeypatch.setattr(
        "opn_oracle.oracle.custom_reports.append_audit_event",
        lambda *_a, **kwargs: audits.append(str(kwargs.get("action"))),
    )
    # Guard: report_writer path must not run
    monkeypatch.setattr(
        "opn_oracle.reporting.service.process_report",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("report_writer invocado")),
        raising=False,
    )

    job = _job(job_type=CUSTOM_BRIEF_JOB)
    payload = {"report_id": str(report_id), "dossier_id": str(dossier_id)}
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        result = process_custom_brief_plan(session, payload, job)  # type: ignore[arg-type]

    assert result["plan_status"] == "proposed"
    assert result["mutates_intent"] is False
    assert report.options["plan_status"] == "proposed"
    assert report.options["proposed_plan"]["version"] == "custom_brief_plan.v1"
    assert len(report.options["proposed_plan"]["sections"]) >= 3
    assert report.status == "draft"
    assert "report.custom_brief.plan_proposed" in audits


def test_task_wrappers_map_permanent_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "opn_oracle.jobs.tasks.process_dossier_question_answer",
        lambda *a, **k: (_ for _ in ()).throw(
            __import__(
                "opn_oracle.oracle.conversations", fromlist=["ConversationNotFound"]
            ).ConversationNotFound("x")
        ),
    )
    monkeypatch.setattr("opn_oracle.jobs.tasks.db", SimpleNamespace(session=MagicMock()))
    with pytest.raises(PermanentJobError):
        _answer_dossier_question(
            {
                "message_id": str(uuid.uuid4()),
                "conversation_id": str(uuid.uuid4()),
                "dossier_id": str(uuid.uuid4()),
            },
            _job(),  # type: ignore[arg-type]
        )

    monkeypatch.setattr(
        "opn_oracle.jobs.tasks.process_custom_brief_plan",
        lambda *a, **k: (_ for _ in ()).throw(
            __import__(
                "opn_oracle.oracle.custom_reports", fromlist=["CustomReportNotFound"]
            ).CustomReportNotFound("y")
        ),
    )
    with pytest.raises(PermanentJobError):
        _plan_custom_brief(
            {"report_id": str(uuid.uuid4()), "dossier_id": str(uuid.uuid4())},
            _job(job_type=CUSTOM_BRIEF_JOB),  # type: ignore[arg-type]
        )


def test_apply_answer_still_forbids_intent_mutation_flag() -> None:
    message = SimpleNamespace(
        role="user",
        status="queued",
        answer_payload={},
        coverage_manifest={},
    )
    apply_assistant_answer(
        message,  # type: ignore[arg-type]
        answer_text="ok",
        coverage_manifest=empty_coverage_manifest(requested=["x"]),
    )
    assert message.answer_payload["mutates_intent"] is False
    assert message.answer_payload["mutates_memory_facts"] is False
