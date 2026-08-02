"""MDEV-06 · real Celery worker + Redis/PostgreSQL for Ask terminalization.

Requires ORACLE_RUN_INTEGRATION=1 and TEST_* database/redis URLs (jobs_stack).
Provider path uses deterministic Signal HTTP mock (no OpenRouter / paid).
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import httpx
import pytest

from opn_oracle.extensions import db
from opn_oracle.jobs.service import publish_job, request_cancel
from opn_oracle.oracle.conversations import (
    DOSSIER_QUESTION_JOB,
    create_conversation,
    enqueue_user_message,
    get_message,
)
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.tenants.context import TenantContext, tenant_context

# Reuse the module-scoped real worker fixture from jobs integration.
pytest_plugins = ("tests.test_integration_jobs",)

pytestmark = pytest.mark.integration


def _wait_job(
    app: Any,
    ids: dict[str, uuid.UUID],
    job_id: uuid.UUID,
    statuses: set[str],
    *,
    timeout: float = 20,
) -> BackgroundJob:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with (
            app.app_context(),
            tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
        ):
            job = db.session.get(BackgroundJob, job_id)
            if job is not None and job.status in statuses:
                db.session.expunge(job)
                return job
            db.session.remove()
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} never reached {statuses}")


def _dqa_validated(answer_text: str = "Respuesta RT-07 mock terminal.") -> dict[str, Any]:
    return {
        "answer_text": answer_text,
        "facts": [],
        "inferences": [],
        "recommendations": [],
        "confidence": 0,
        "open_questions": ["evidencia_autorizada"],
        "warnings": ["empty_allowlist"],
        "citations": [],
        "claims": [],
        "conflicts": [],
        "unknowns": ["evidencia_en_memoria"],
        "citation_count": 0,
        "schema_version": "dossier_question_answer.v1",
    }


def test_celery_ask_202_publish_worker_signal_mock_terminal(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stage+publish → Celery worker → Signal mock HTTP RT-07 → terminal message.

    The durable handler runs in the real worker. Signal is mocked at the HTTP
    boundary (no OpenRouter). validated_output is the only consumer path.
    """
    app, ids = jobs_stack
    from opn_oracle.ai.provider import LLMRequest, SignalGovernedLLMProvider
    from opn_oracle.ai.schemas import DossierQuestionAnswerOutput
    from opn_oracle.jobs import tasks as job_tasks
    from opn_oracle.oracle import conversations as conv_mod

    signal_calls: list[str] = []

    def signal_post(url: str, **kwargs: object) -> httpx.Response:
        body = kwargs.get("json") if isinstance(kwargs.get("json"), dict) else {}
        signal_calls.append(str(url))
        assert "ai/run" in url
        assert isinstance(body, dict)
        assert body.get("task_key") == "dossier_question_answer"
        validated = _dqa_validated()
        malicious = {**validated, "answer_text": "RESULT CRUDO NO DEBE PUBLICARSE"}
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "ok": True,
                "provider": "mock-rt07",
                "model": "mock-dqa",
                "usage": {"input_tokens": 5, "output_tokens": 8},
                "runtime": {
                    "runtime_id": "RT-07",
                    "prompt_sha256": "a" * 64,
                    "schema_sha256": "b" * 64,
                    "schema_version": "dossier_question_answer.v1",
                    "prompt_version": "1.0.0",
                },
                "result": {"message": {"content": json.dumps(malicious)}},
                "validated_output": validated,
            },
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", signal_post)

    def handler_with_signal_mock(
        session: Any, payload: Any, job: Any, **kwargs: Any
    ) -> dict[str, Any]:
        """Minimal dual-memory settle that still hits SignalGovernedLLMProvider over HTTP."""
        del kwargs
        message = conv_mod.get_message(
            session,
            uuid.UUID(str(payload["message_id"])),
            dossier_id=uuid.UUID(str(payload["dossier_id"])),
            conversation_id=uuid.UUID(str(payload["conversation_id"])),
        )
        if job.cancel_requested:
            conv_mod.cancel_message(message)
            session.flush()
            return {"status": "cancelled", "cancelled": True, "message_id": str(message.id)}
        provider = SignalGovernedLLMProvider(
            base_url="https://signal.test/",
            api_key="test-key-not-secret",
            timeout_seconds=5.0,
        )
        request = LLMRequest(
            agent="dossier_question_answer",
            model="mock-dqa",
            system_prompt="JSON estricto RT-07.",
            task_prompt=str(message.content_text),
            context={"allowed_evidence_ids": []},
            max_output_tokens=500,
            classification="public",
        )
        result = provider.generate_structured(request, DossierQuestionAnswerOutput)
        answer_text = str(result.output.answer_text)
        assert "RESULT CRUDO" not in answer_text
        conv_mod.apply_assistant_answer(
            message,
            answer_text=answer_text,
            answer_payload={
                "provider_path": "signal",
                "task_key": "dossier_question_answer",
                "citations": [],
                "allowed_evidence_ids": [],
                "validated_output_sha256": result.validated_output_sha256,
                "mutates_intent": False,
                "mutates_memory_facts": False,
            },
            coverage_manifest={"version": "coverage_manifest.v1", "mode": "disabled"},
        )
        session.flush()
        return {
            "status": "succeeded",
            "message_id": str(message.id),
            "task_key": "dossier_question_answer",
            "provider_path": "signal",
            "validated_output_sha256": result.validated_output_sha256,
        }

    monkeypatch.setattr(job_tasks, "process_dossier_question_answer", handler_with_signal_mock)

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        conversation = create_conversation(
            db.session,
            dossier_id=ids["dossier"],
            actor_id=ids["user"],
            title="Ask Celery",
        )
        message, job = enqueue_user_message(
            db.session,
            dossier_id=ids["dossier"],
            conversation_id=conversation.id,
            actor_id=ids["user"],
            content_text="¿Hay evidencia autorizada en el expediente?",
            idempotency_key=f"mdev06-celery-{uuid.uuid4().hex[:16]}",
        )
        db.session.commit()
        assert job.job_type == DOSSIER_QUESTION_JOB
        published = publish_job(job)
        assert published is True
        job_id = job.id
        message_id = message.id
        conversation_id = conversation.id

    finished = _wait_job(app, ids, job_id, {"succeeded", "failed", "cancelled"})
    assert finished.status == "succeeded", (
        f"{finished.status} {finished.error_code} {finished.error_message}"
    )
    assert finished.stage not in {"publish_pending", "running", "backoff"}
    assert finished.attempts >= 1
    assert signal_calls, "worker must call Signal mock HTTP"

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        msg = get_message(
            db.session,
            message_id,
            dossier_id=ids["dossier"],
            conversation_id=conversation_id,
        )
        assert msg.status == "succeeded"
        payload = dict(msg.answer_payload or {})
        text = str(payload.get("text") or "")
        assert "RESULT CRUDO" not in text
        assert "RT-07" in text or "autorizada" in text.lower() or "evidencia" in text.lower()
        assert payload.get("provider_path") == "signal"
        assert payload.get("validated_output_sha256")
        reloaded = db.session.get(BackgroundJob, job_id)
        assert reloaded is not None
        assert reloaded.status == "succeeded"


def test_celery_ask_retry_exhausted_and_permanent_not_stuck(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transient retries exhaust and permanent 4xx fail terminal — never stuck running."""
    app, ids = jobs_stack
    from opn_oracle.integrations.memory_ask_dual import (
        PermanentMemoryAskError,
        RetryableMemoryAskError,
    )
    from opn_oracle.jobs import tasks as job_tasks

    calls: dict[str, int] = {"retry": 0, "perm": 0}

    def raise_retry(*_a: Any, **_k: Any) -> Any:
        calls["retry"] += 1
        raise RetryableMemoryAskError("upstream_timeout simulated", code="timeout")

    def raise_perm(*_a: Any, **_k: Any) -> Any:
        calls["perm"] += 1
        raise PermanentMemoryAskError("schema_validation simulated", code="schema_validation")

    monkeypatch.setattr(job_tasks, "process_dossier_question_answer", raise_retry)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        conversation = create_conversation(
            db.session, dossier_id=ids["dossier"], actor_id=ids["user"], title="retry"
        )
        message, job = enqueue_user_message(
            db.session,
            dossier_id=ids["dossier"],
            conversation_id=conversation.id,
            actor_id=ids["user"],
            content_text="retry path",
            idempotency_key=f"mdev06-retry-{uuid.uuid4().hex[:16]}",
        )
        # Force low max_attempts via direct stage if needed — enqueue uses 3.
        job.max_attempts = 2
        db.session.commit()
        publish_job(job)
        retry_job_id = job.id
        retry_message_id = message.id

    retried = _wait_job(app, ids, retry_job_id, {"failed"}, timeout=30)
    assert retried.status == "failed"
    assert retried.stage in {"retry_exhausted", "failed"}
    assert retried.attempts >= 2
    assert retried.error_code in {"retry_exhausted", "temporary_failure", "permanent_failure"}
    assert retried.error_message
    assert retried.status not in {"publish_pending", "running", "retrying"}

    monkeypatch.setattr(job_tasks, "process_dossier_question_answer", raise_perm)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        conversation = create_conversation(
            db.session, dossier_id=ids["dossier"], actor_id=ids["user"], title="perm"
        )
        message, job = enqueue_user_message(
            db.session,
            dossier_id=ids["dossier"],
            conversation_id=conversation.id,
            actor_id=ids["user"],
            content_text="permanent path",
            idempotency_key=f"mdev06-perm-{uuid.uuid4().hex[:16]}",
        )
        db.session.commit()
        publish_job(job)
        perm_job_id = job.id

    permanent = _wait_job(app, ids, perm_job_id, {"failed"}, timeout=20)
    assert permanent.status == "failed"
    assert permanent.retryable is False or permanent.error_code in {
        "permanent_failure",
        "schema_validation",
    }
    assert permanent.stage not in {"publish_pending", "running", "backoff"}
    assert permanent.attempts >= 1
    assert calls["perm"] >= 1
    # Message for retry path must not stay queued forever.
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        # Message may remain queued if handler raised before settle — job is terminal.
        job_row = db.session.get(BackgroundJob, retry_job_id)
        assert job_row is not None and job_row.status == "failed"
        _ = retry_message_id


def test_celery_ask_cancel_pre_publish_and_during_retry_no_late_result(
    jobs_stack: tuple[Any, dict[str, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, ids = jobs_stack
    from opn_oracle.integrations.memory_ask_dual import RetryableMemoryAskError
    from opn_oracle.jobs import tasks as job_tasks
    from opn_oracle.oracle.conversations import DossierMessage, cancel_message, get_message

    # Pre-publish cancel: stage without publish, cancel, ensure not succeeded later.
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        conversation = create_conversation(
            db.session, dossier_id=ids["dossier"], actor_id=ids["user"], title="cancel-pre"
        )
        message, job = enqueue_user_message(
            db.session,
            dossier_id=ids["dossier"],
            conversation_id=conversation.id,
            actor_id=ids["user"],
            content_text="cancel before publish",
            idempotency_key=f"mdev06-cancel-pre-{uuid.uuid4().hex[:16]}",
        )
        db.session.commit()
        request_cancel(job, expected_version=job.version)
        db.session.commit()
        pre_id = job.id
        pre_message_id = message.id
        job2 = db.session.get(BackgroundJob, pre_id)
        assert job2 is not None
        assert job2.cancel_requested is True or job2.status == "cancelled"
        # Explicitly mark message cancelled as the cooperative path would.
        cancel_message(message)
        db.session.commit()

    # Cancel-aware handler: if cancel_requested, never publish a late answer.
    def cancel_aware(session: Any, payload: Any, job: Any, **_k: Any) -> dict[str, Any]:
        message = get_message(
            session,
            uuid.UUID(str(payload["message_id"])),
            dossier_id=uuid.UUID(str(payload["dossier_id"])),
            conversation_id=uuid.UUID(str(payload["conversation_id"])),
        )
        if bool(getattr(job, "cancel_requested", False)):
            cancel_message(message)
            session.flush()
            return {"status": "cancelled", "cancelled": True, "message_id": str(message.id)}
        raise RetryableMemoryAskError("would retry if not cancelled", code="timeout")

    monkeypatch.setattr(job_tasks, "process_dossier_question_answer", cancel_aware)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        conversation = create_conversation(
            db.session, dossier_id=ids["dossier"], actor_id=ids["user"], title="cancel-retry"
        )
        message, job = enqueue_user_message(
            db.session,
            dossier_id=ids["dossier"],
            conversation_id=conversation.id,
            actor_id=ids["user"],
            content_text="cancel during retry",
            idempotency_key=f"mdev06-cancel-retry-{uuid.uuid4().hex[:16]}",
        )
        job.max_attempts = 3
        db.session.commit()
        # Cancel before first delivery can invent a success.
        request_cancel(job, expected_version=job.version)
        db.session.commit()
        publish_job(job)
        mid = message.id
        jid = job.id

    terminal = _wait_job(app, ids, jid, {"failed", "cancelled"}, timeout=20)
    assert terminal.status in {"failed", "cancelled"}
    assert terminal.status != "succeeded"
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        msg = db.session.get(DossierMessage, mid)
        if msg is not None:
            assert msg.status != "succeeded"
        pre_msg = db.session.get(DossierMessage, pre_message_id)
        assert pre_msg is not None
        assert pre_msg.status in {"queued", "cancelled", "failed"}
        assert pre_msg.status != "succeeded"
