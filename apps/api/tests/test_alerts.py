from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from opn_oracle.jobs import tasks
from opn_oracle.jobs.service import TASK_QUEUES
from opn_oracle.reporting.alerts import (
    ALERT_TYPES,
    DEFAULT_ENABLED_TYPES,
    DEFAULT_SEVERITY_MAP,
    AlertPolicyError,
    validate_policy_maps,
)
from opn_oracle.reporting.models import AlertPolicy
from opn_oracle.reporting.routes import _apply_alert_policy

pytestmark = pytest.mark.unit


def test_alert_policy_maps_are_strict_allowlists() -> None:
    enabled, severities = validate_policy_maps(
        DEFAULT_ENABLED_TYPES,
        {"high_risk": "critical", "report_ready": "success"},
    )
    assert set(enabled) == set(ALERT_TYPES)
    assert severities == {"high_risk": "critical", "report_ready": "success"}
    for invalid_enabled, invalid_severity in (
        ({"high_risk": True}, {}),
        ({**DEFAULT_ENABLED_TYPES, "unknown": True}, {}),
        ({**DEFAULT_ENABLED_TYPES, "high_risk": "yes"}, {}),
        (DEFAULT_ENABLED_TYPES, {"unknown": "warning"}),
        (DEFAULT_ENABLED_TYPES, {"high_risk": "urgent"}),
    ):
        with pytest.raises(AlertPolicyError):
            validate_policy_maps(invalid_enabled, invalid_severity)


def test_alert_policy_patch_merges_allowed_subsets_without_deleting_other_values() -> None:
    policy = AlertPolicy(
        scope="tenant",
        signal_score_threshold=75,
        risk_score_threshold=75,
        opportunity_deadline_days=14,
        meeting_upcoming_hours=24,
        cooldown_minutes=60,
        enabled_types=dict(DEFAULT_ENABLED_TYPES),
        severity_map=dict(DEFAULT_SEVERITY_MAP),
        timezone="UTC",
        version=1,
    )
    _apply_alert_policy(
        policy,
        {
            "enabled_types": {"report_ready": False},
            "severity_map": {"high_signal": "critical"},
        },
    )
    assert policy.enabled_types == {**DEFAULT_ENABLED_TYPES, "report_ready": False}
    assert policy.severity_map == {**DEFAULT_SEVERITY_MAP, "high_signal": "critical"}
    with pytest.raises(AlertPolicyError):
        _apply_alert_policy(policy, {"enabled_types": {"unknown": True}})


def test_alert_job_uses_scheduled_instant_and_rejects_malformed_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[datetime] = []
    monkeypatch.setattr(
        tasks,
        "evaluate_alerts",
        lambda *, now: seen.append(now) or {"emitted": 0},
    )
    payload = {"scheduled_at": "2026-07-11T06:55:00+02:00"}
    assert tasks.HANDLERS["notifications.evaluate_alerts"](payload, SimpleNamespace()) == {
        "emitted": 0
    }
    assert seen == [datetime(2026, 7, 11, 4, 55, tzinfo=UTC)]
    for malformed in ({}, {"scheduled_at": "not-a-date"}, {"scheduled_at": "2026-07-11T05:00:00"}):
        with pytest.raises(tasks.PermanentJobError):
            tasks.HANDLERS["notifications.evaluate_alerts"](malformed, SimpleNamespace())


def test_alert_jobs_are_registered_on_durable_notification_queue(app: Any) -> None:
    assert TASK_QUEUES["notifications.evaluate_alerts"] == "notifications"
    assert "notifications.evaluate_alerts" in tasks.HANDLERS
    schedule = app.extensions["celery"].conf.beat_schedule["schedule-alert-evaluations"]
    assert schedule["task"] == "maintenance.schedule_alert_evaluations"
    assert schedule["options"] == {"queue": "maintenance"}
    nightly = app.extensions["celery"].conf.beat_schedule[
        "schedule-nightly-dossier-summaries"
    ]
    assert nightly["task"] == "maintenance.schedule_nightly_dossier_summaries"
    assert nightly["options"] == {"queue": "maintenance"}


def test_tenant_alert_policy_openapi_contract(client: Any) -> None:
    spec = client.get("/api/v1/openapi.json").get_json()
    assert set(spec["paths"]["/api/v1/alert-policy"]) >= {"get", "patch"}
    schema = spec["components"]["schemas"]["AlertPolicyResponse"]
    assert {"scope", "inherited", "risk_score_threshold"}.issubset(schema["required"])
