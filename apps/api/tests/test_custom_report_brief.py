"""Unit tests for custom report brief intake (MEMSOL-07)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from opn_oracle.oracle.custom_reports import (
    CUSTOM_BRIEF_JOB,
    CUSTOM_BRIEF_TEMPLATE_KEY,
    CustomReportConflict,
    CustomReportError,
    create_custom_report_brief,
    serialize_custom_brief,
)
from opn_oracle.tenants.context import TenantContext, TenantContextMissing, tenant_context


def test_create_custom_brief_requires_tenant() -> None:
    with pytest.raises(TenantContextMissing):
        create_custom_report_brief(
            MagicMock(),
            dossier_id=uuid.uuid4(),
            actor_id=uuid.uuid4(),
            brief_request="Analiza el posicionamiento de la competencia",
            idempotency_key="idem-brief-0001",
        )


def test_create_custom_brief_stages_pending_job_without_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    dossier = SimpleNamespace(
        id=dossier_id,
        tenant_id=tenant_id,
        status="active",
        title="Expediente demo",
        current_intent_revision_id=None,
    )
    job = SimpleNamespace(id=uuid.uuid4(), status="queued", job_type=CUSTOM_BRIEF_JOB)
    session = MagicMock()
    # _load_dossier, existing report, generation_version
    session.scalar.side_effect = [dossier, None, 0]
    session.get.return_value = None
    added: list[Any] = []
    session.add.side_effect = lambda obj: added.append(obj)

    stage_calls: list[dict[str, Any]] = []
    signal_calls: list[str] = []

    def _stage(task_name: str, **kwargs: Any) -> Any:
        stage_calls.append({"task_name": task_name, **kwargs})
        return job

    def _signal_forbidden(*_a: Any, **_k: Any) -> Any:
        signal_calls.append("signal")
        raise AssertionError("Custom brief no debe invocar Signal.")

    monkeypatch.setattr("opn_oracle.oracle.custom_reports.stage_job", _stage)
    monkeypatch.setattr("opn_oracle.oracle.custom_reports.append_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(
        "opn_oracle.integrations.signal_avanza.MockSignalAvanzaAdapter.create_monitor",
        _signal_forbidden,
        raising=False,
    )
    monkeypatch.setattr(
        "opn_oracle.jobs.tasks._generate_report",
        _signal_forbidden,
        raising=False,
    )

    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=actor_id)):
        report, returned_job = create_custom_report_brief(
            session,
            dossier_id=dossier_id,
            actor_id=actor_id,
            brief_request="Prepara un plan de informe sobre alianzas en defensa.",
            idempotency_key="idem-brief-0001",
            publish=False,
        )

    assert returned_job is job
    assert report.status == "draft"
    assert report.template_key == CUSTOM_BRIEF_TEMPLATE_KEY
    assert report.options["plan_status"] == "draft"
    assert "alianzas" in report.options["brief_request"]
    assert report.options["mutates_intent"] is False
    assert report.options["mutates_memory_facts"] is False
    assert report.background_job_id == job.id
    assert len(stage_calls) == 1
    assert stage_calls[0]["task_name"] == CUSTOM_BRIEF_JOB
    assert stage_calls[0]["payload"]["report_id"] == str(report.id)
    assert signal_calls == []
    # Report row staged before job association
    assert any(getattr(obj, "template_key", None) == CUSTOM_BRIEF_TEMPLATE_KEY for obj in added)


def test_create_custom_brief_rejects_empty_and_short_idempotency() -> None:
    tenant_id = uuid.uuid4()
    session = MagicMock()
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        with pytest.raises(CustomReportError):
            create_custom_report_brief(
                session,
                dossier_id=uuid.uuid4(),
                actor_id=uuid.uuid4(),
                brief_request="   ",
                idempotency_key="idem-brief-0002",
            )
        with pytest.raises(CustomReportError):
            create_custom_report_brief(
                session,
                dossier_id=uuid.uuid4(),
                actor_id=uuid.uuid4(),
                brief_request="texto válido de brief",
                idempotency_key="short",
            )


def test_idempotent_replay_returns_existing_when_payload_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    job_id = uuid.uuid4()
    brief = "Informe de riesgos regulatorios en ES"
    existing = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        template_key=CUSTOM_BRIEF_TEMPLATE_KEY,
        options={"brief_request": brief, "plan_status": "draft"},
        background_job_id=job_id,
        status="draft",
        report_type="custom_assistant",
        template_version="v1",
        generation_version=1,
        title="x",
        requested_by_user_id=actor_id,
        created_at=None,
        updated_at=None,
    )
    job = SimpleNamespace(id=job_id, status="queued")
    dossier = SimpleNamespace(
        id=dossier_id,
        tenant_id=tenant_id,
        status="active",
        title="D",
        current_intent_revision_id=None,
    )
    session = MagicMock()
    session.scalar.side_effect = [dossier, existing]
    session.get.return_value = job
    stage_calls: list[Any] = []
    monkeypatch.setattr(
        "opn_oracle.oracle.custom_reports.stage_job",
        lambda *a, **k: stage_calls.append(1) or job,
    )

    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=actor_id)):
        report, returned = create_custom_report_brief(
            session,
            dossier_id=dossier_id,
            actor_id=actor_id,
            brief_request=brief,
            idempotency_key="idem-brief-replay1",
            publish=False,
        )

    assert report is existing
    assert returned is job
    assert stage_calls == []


def test_idempotent_conflict_on_different_brief(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    existing = SimpleNamespace(
        template_key=CUSTOM_BRIEF_TEMPLATE_KEY,
        options={"brief_request": "otro brief", "plan_status": "draft"},
        background_job_id=uuid.uuid4(),
    )
    dossier = SimpleNamespace(
        id=dossier_id,
        tenant_id=tenant_id,
        status="active",
        title="D",
        current_intent_revision_id=None,
    )
    session = MagicMock()
    session.scalar.side_effect = [dossier, existing]

    with (
        tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())),
        pytest.raises(CustomReportConflict),
    ):
        create_custom_report_brief(
            session,
            dossier_id=dossier_id,
            actor_id=uuid.uuid4(),
            brief_request="brief distinto",
            idempotency_key="idem-brief-conflict",
            publish=False,
        )


def test_serialize_custom_brief_exposes_plan_status() -> None:
    report = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        title="t",
        status="draft",
        report_type="custom_assistant",
        template_key=CUSTOM_BRIEF_TEMPLATE_KEY,
        template_version="v1",
        generation_version=1,
        options={"brief_request": "hola", "plan_status": "draft"},
        background_job_id=uuid.uuid4(),
        requested_by_user_id=uuid.uuid4(),
        created_at=None,
        updated_at=None,
    )
    payload = serialize_custom_brief(report)  # type: ignore[arg-type]
    assert payload["plan_status"] == "draft"
    assert payload["brief_request"] == "hola"
    assert payload["status"] == "draft"
