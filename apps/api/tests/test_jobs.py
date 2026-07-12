from __future__ import annotations

from datetime import UTC, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from opn_oracle.ai.provider import AIUnavailable
from opn_oracle.celery_app import QUEUES, TASK_ROUTES, celery_init_app
from opn_oracle.integrations.signal_avanza import MockSignalAvanzaAdapter
from opn_oracle.jobs import tasks
from opn_oracle.jobs.service import claim_job_for_publish, payload_digest, validate_payload
from opn_oracle.jobs.tasks import (
    PermanentJobError,
    RetriableJobError,
    execute_durable,
    retry_delay,
)
from opn_oracle.notifications.email import SMTPEmailSender
from opn_oracle.oracle.jobs import BackgroundJob, JobSchedule


@pytest.mark.unit
def test_celery_factory_is_singleton_and_json_utc(app: object) -> None:
    first = celery_init_app(app)  # type: ignore[arg-type]
    second = celery_init_app(app)  # type: ignore[arg-type]
    assert first is second
    assert first.conf.task_serializer == "json"
    assert first.conf.accept_content == ["json"]
    assert first.conf.timezone == "UTC"
    assert {queue.name for queue in first.conf.task_queues} == set(QUEUES)


@pytest.mark.unit
def test_production_worker_consumes_every_declared_queue() -> None:
    compose = Path(__file__).parents[3] / "compose.prod.yml"
    contents = compose.read_text(encoding="utf-8")
    assert f"- {','.join(QUEUES)}" in contents


@pytest.mark.unit
def test_job_payload_is_deterministic_and_rejects_secrets() -> None:
    assert payload_digest({"resource_id": "a", "kind": "x"}) == payload_digest(
        {"kind": "x", "resource_id": "a"}
    )
    forbidden = (
        "token",
        "client_secret",
        "access-token",
        "refresh_token",
        "smtp_password",
        "apikey",
        "api-key",
        "Authorization",
        "credential",
        "private.key",
    )
    for key in forbidden:
        payload = {"nested": {key: "x"}}
        with pytest.raises(ValueError):
            validate_payload(payload)


@pytest.mark.unit
def test_schedule_advance_uses_utc_cadence() -> None:
    now = datetime(2026, 7, 10, tzinfo=UTC)
    schedule = JobSchedule(
        schedule_key="weekly",
        task_name="maintenance.weekly_digest",
        queue="maintenance",
        payload={},
        cadence_seconds=3600,
        next_run_at=now,
    )
    schedule.advance(now)
    assert schedule.last_enqueued_at == now
    assert schedule.next_run_at.timestamp() - now.timestamp() == 3600


@pytest.mark.unit
def test_schedule_catches_up_without_drifting_and_retry_has_bounded_jitter() -> None:
    due = datetime(2026, 7, 10, tzinfo=UTC)
    now = datetime(2026, 7, 10, 3, 30, tzinfo=UTC)
    schedule = JobSchedule(
        schedule_key="hourly",
        task_name="maintenance.weekly_digest",
        queue="maintenance",
        payload={},
        cadence_seconds=3600,
        next_run_at=due,
    )
    schedule.advance(now)
    assert schedule.next_run_at == datetime(2026, 7, 10, 4, tzinfo=UTC)
    assert retry_delay(3, jitter=0.0) == 8.0
    assert retry_delay(20, jitter=3.0) == 300.0


@pytest.mark.unit
def test_wall_clock_schedules_respect_europe_madrid_dst_contract() -> None:
    spring = JobSchedule(
        schedule_key="daily-dst",
        task_name="maintenance.weekly_digest",
        queue="maintenance",
        payload={},
        cadence_seconds=86400,
        next_run_at=datetime(2026, 3, 28, 1, 30, tzinfo=UTC),
        schedule_kind="daily",
        local_time=time(2, 30),
        timezone="Europe/Madrid",
    )
    spring.advance(datetime(2026, 3, 28, 12, tzinfo=UTC))
    spring_local = spring.next_run_at.astimezone(ZoneInfo("Europe/Madrid"))
    assert (spring_local.month, spring_local.day, spring_local.hour, spring_local.minute) == (
        3,
        29,
        3,
        30,
    )

    weekly = JobSchedule(
        schedule_key="weekly-dst",
        task_name="maintenance.weekly_digest",
        queue="maintenance",
        payload={},
        cadence_seconds=604800,
        next_run_at=datetime(2026, 10, 18, 7, tzinfo=UTC),
        schedule_kind="weekly",
        local_time=time(9),
        weekday=6,
        timezone="Europe/Madrid",
    )
    weekly.advance(datetime(2026, 10, 23, 12, tzinfo=UTC))
    assert weekly.next_run_at == datetime(2026, 10, 25, 8, tzinfo=UTC)


@pytest.mark.unit
def test_routes_and_publish_claim_are_explicit_and_idempotent() -> None:
    assert TASK_ROUTES["oracle.signal.*"] == {"queue": "signals"}
    assert TASK_ROUTES["oracle.dossier_summary.*"] == {"queue": "ai"}
    assert TASK_ROUTES["oracle.ai.*"] == {"queue": "ai"}
    assert TASK_ROUTES["notifications.*"] == {"queue": "notifications"}
    job = BackgroundJob(
        tenant_id=__import__("uuid").uuid4(),
        job_type="oracle.signal.triage",
        queue="signals",
        status="queued",
        idempotency_key="unit-claim",
        payload_hash=b"0" * 32,
        input_payload={},
        stage="queued",
        publish_attempts=0,
        cancel_requested=False,
        version=1,
    )
    assert claim_job_for_publish(job) is True
    assert job.stage == "publishing" and job.publish_attempts == 1
    assert claim_job_for_publish(job) is False
    job.cancel_requested = True
    assert claim_job_for_publish(job) is False


@pytest.mark.unit
def test_untrusted_delivery_errors_are_sanitized_before_app_or_database_access() -> None:
    with pytest.raises(PermanentJobError, match=r"^permanent_failure$"):
        execute_durable(  # type: ignore[arg-type]
            None,
            job_id="credential=must-not-leak",
            tenant_id="not-a-uuid",
            payload={"token": "must-not-leak"},
        )


@pytest.mark.unit
def test_mock_signal_adapter_is_deterministic_and_cursor_aware() -> None:
    adapter = MockSignalAvanzaAdapter()
    first = adapter.sync_monitor(monitor_id="monitor-1", cursor=None)
    repeated = adapter.sync_monitor(monitor_id="monitor-1", cursor=None)
    incremental = adapter.sync_monitor(monitor_id="monitor-1", cursor=first.next_cursor)
    assert first == repeated
    assert (first.received, first.created, first.duplicates) == (2, 2, 0)
    assert (incremental.received, incremental.created, incremental.duplicates) == (2, 1, 1)


@pytest.mark.unit
def test_summary_provider_outage_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tasks,
        "process_summary_refresh",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AIUnavailable("temporal")),
    )
    with pytest.raises(RetriableJobError):
        tasks._refresh_dossier_summary(
            {"dossier_id": str(__import__("uuid").uuid4())},
            BackgroundJob(),
        )


@pytest.mark.unit
def test_smtp_sender_is_at_most_once_per_delivery_key(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

    class FakeSMTP:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def __enter__(self) -> FakeSMTP:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def send_message(self, message: object) -> None:
            sent.append(str(message))

    monkeypatch.setattr("opn_oracle.notifications.email.smtplib.SMTP", FakeSMTP)
    sender = SMTPEmailSender(
        host="smtp.test",
        port=25,
        username="",
        password="",
        use_tls=False,
        sender="oracle@example.test",
    )
    for _ in range(2):
        sender.send_password_reset(
            recipient="user@example.test",
            url="https://oracle.example/reset",
            expires="2026-07-10T12:00:00Z",
            idempotency_key="password-reset-stable",
        )
    assert sender.supports_idempotency is False
    assert len(sent) == 1
    assert "password-reset-stable@oracle.opnconsultoria.com" in sent[0]
