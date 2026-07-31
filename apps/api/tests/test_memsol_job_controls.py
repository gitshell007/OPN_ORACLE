"""Unit tests: cancel/retry rules for MEMSOL durable jobs (no invented routes)."""

from __future__ import annotations

import uuid

import pytest

from opn_oracle.jobs.service import prepare_retry, request_cancel, serialize_job
from opn_oracle.oracle.jobs import BackgroundJob


def _job(**kwargs: object) -> BackgroundJob:
    base = dict(
        tenant_id=uuid.uuid4(),
        job_type="oracle.dossier_question.answer",
        queue="ai",
        status="queued",
        idempotency_key=f"memsol-{uuid.uuid4().hex[:12]}",
        payload_hash=b"\x00" * 32,
        input_payload={"message_id": str(uuid.uuid4())},
        version=1,
        retryable=True,
        cancel_requested=False,
        attempts=0,
        max_attempts=3,
    )
    base.update(kwargs)
    return BackgroundJob(**base)  # type: ignore[arg-type]


@pytest.mark.unit
def test_request_cancel_queued_memsol_question_is_immediate_cancelled() -> None:
    job = _job(job_type="oracle.dossier_question.answer", status="queued", version=2)
    request_cancel(job, expected_version=2)
    assert job.cancel_requested is True
    assert job.status == "cancelled"
    assert job.stage == "cancelled"
    assert job.version == 3
    assert job.finished_at is not None


@pytest.mark.unit
def test_request_cancel_running_sets_flag_without_forcing_terminal() -> None:
    job = _job(job_type="oracle.report.custom_brief.plan", status="running", version=1)
    request_cancel(job, expected_version=1)
    assert job.cancel_requested is True
    assert job.status == "running"
    assert job.version == 2


@pytest.mark.unit
def test_request_cancel_rejects_wrong_version_and_terminal() -> None:
    job = _job(status="queued", version=4)
    with pytest.raises(ValueError, match="modificado"):
        request_cancel(job, expected_version=3)
    done = _job(status="succeeded", version=1)
    with pytest.raises(ValueError, match="finalizado"):
        request_cancel(done, expected_version=1)


@pytest.mark.unit
def test_prepare_retry_only_failed_retryable() -> None:
    ok = _job(status="failed", retryable=True, version=5)
    prepare_retry(ok, expected_version=5)
    assert ok.status == "queued"
    assert ok.stage == "manual_retry"
    assert ok.cancel_requested is False
    assert ok.version == 6
    assert ok.attempts == 0

    bad = _job(status="failed", retryable=False, version=1)
    with pytest.raises(ValueError, match="no admite"):
        prepare_retry(bad, expected_version=1)

    running = _job(status="running", retryable=True, version=1)
    with pytest.raises(ValueError, match="no admite"):
        prepare_retry(running, expected_version=1)


@pytest.mark.unit
def test_serialize_job_exposes_version_cancel_and_retryable_for_ui() -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    job = _job(
        status="queued",
        version=7,
        cancel_requested=False,
        retryable=True,
        created_at=now,
        updated_at=now,
    )
    payload = serialize_job(job)
    assert payload["version"] == 7
    assert payload["cancel_requested"] is False
    assert payload["retryable"] is True
    assert payload["status"] == "queued"
    assert payload["job_type"] == "oracle.dossier_question.answer"