"""Prove MEMSOL job types are registered Celery tasks (not only HANDLERS).

publish_job/publish_claimed_job look up celery.tasks[job_type]. Without
_durable_task() registration, apply_async KeyErrors and jobs stay publish_pending.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from opn_oracle.celery_app import TASK_ROUTES, celery_init_app
from opn_oracle.jobs.service import TASK_QUEUES, claim_job_for_publish, publish_claimed_job
from opn_oracle.oracle.conversations import DOSSIER_QUESTION_JOB
from opn_oracle.oracle.custom_reports import CUSTOM_BRIEF_JOB

MEMSOL_JOB_TYPES = (
    DOSSIER_QUESTION_JOB,
    CUSTOM_BRIEF_JOB,
)


@pytest.mark.unit
def test_memsol_job_types_are_registered_celery_tasks(app: object) -> None:
    celery = celery_init_app(app)  # type: ignore[arg-type]
    # Import tasks module so @shared_task registrations attach to the app celery.
    import opn_oracle.jobs.tasks as job_tasks  # noqa: F401

    for job_type in MEMSOL_JOB_TYPES:
        assert job_type in TASK_QUEUES, f"{job_type} missing from TASK_QUEUES"
        assert TASK_QUEUES[job_type] == "ai"
        assert job_type in celery.tasks, (
            f"{job_type} missing from celery.tasks — add _durable_task('{job_type}')"
        )
        task = celery.tasks[job_type]
        assert getattr(task, "name", None) == job_type
        # Shared task must be bound execute_durable entrypoint (callable).
        assert callable(task)


@pytest.mark.unit
def test_memsol_task_routes_cover_queues() -> None:
    # Routes must not leave dossier_question on the default queue by pattern miss.
    assert any(pattern.startswith("oracle.dossier_question") for pattern in TASK_ROUTES), (
        "TASK_ROUTES must include oracle.dossier_question.*"
    )
    assert any(pattern.startswith("oracle.report") for pattern in TASK_ROUTES)


@pytest.mark.unit
def test_publish_claimed_job_looks_up_registered_task(
    app: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """publish_claimed_job must resolve celery.tasks[job_type] for MEMSOL jobs."""

    celery = celery_init_app(app)  # type: ignore[arg-type]
    import opn_oracle.jobs.tasks as job_tasks  # noqa: F401

    captured: list[dict[str, Any]] = []

    for job_type in MEMSOL_JOB_TYPES:
        assert job_type in celery.tasks
        original = celery.tasks[job_type]

        def _make_fake(name: str) -> Any:
            def _fake_apply_async(*_a: Any, **kwargs: Any) -> SimpleNamespace:
                captured.append({"job_type": name, **kwargs})
                return SimpleNamespace(id=kwargs.get("task_id"))

            return _fake_apply_async

        monkeypatch.setattr(original, "apply_async", _make_fake(job_type))

    # Drive publish_claimed_job for each type with a fake DB row lifecycle.
    from flask import current_app

    from opn_oracle.extensions import db

    with app.app_context():  # type: ignore[attr-defined]
        for job_type in MEMSOL_JOB_TYPES:
            job_id = uuid.uuid4()
            tenant_id = uuid.uuid4()
            celery_task_id = str(uuid.uuid4())
            job = SimpleNamespace(
                id=job_id,
                tenant_id=tenant_id,
                job_type=job_type,
                status="queued",
                stage="publishing",
                queue=TASK_QUEUES[job_type],
                input_payload={"purpose": "test"},
                celery_task_id=celery_task_id,
                cancel_requested=False,
                publish_attempts=1,
                last_publish_attempt_at=datetime.now(UTC),
                version=1,
                published_at=None,
                error_code=None,
                error_message=None,
            )

            def _get(_cls: Any, _id: Any, _job: Any = job) -> Any:
                return _job

            monkeypatch.setattr(db.session, "get", _get)
            monkeypatch.setattr(db.session, "expire_all", lambda: None)
            monkeypatch.setattr(db.session, "commit", lambda: None)
            monkeypatch.setattr(db.session, "rollback", lambda: None)

            # Ensure celery extension is the one we registered fakes on.
            assert current_app.extensions["celery"] is celery
            ok = publish_claimed_job(job)  # type: ignore[arg-type]
            assert ok is True, f"publish_claimed_job failed for {job_type}"

    published_types = {item["job_type"] for item in captured}
    assert set(MEMSOL_JOB_TYPES) <= published_types
    for item in captured:
        assert item.get("queue") == "ai"
        assert "kwargs" in item or "job_id" in str(item)


@pytest.mark.unit
def test_claim_job_for_publish_accepts_queued_memsol_job() -> None:
    job = SimpleNamespace(
        status="queued",
        stage="queued",
        cancel_requested=False,
        publish_attempts=0,
        last_publish_attempt_at=None,
        version=1,
    )
    assert claim_job_for_publish(job) is True  # type: ignore[arg-type]
    assert job.stage == "publishing"
