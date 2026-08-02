"""MDEV-08 provisional · lifecycle, snapshot freeze, ETag, ready atomicity."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from opn_oracle.oracle.custom_report_lifecycle import (
    CUSTOM_WRITE_JOB,
    IllegalTransition,
    PreconditionRequired,
    accept_plan,
    cancel_report,
    edit_plan,
    get_downloadable_artifact,
    process_custom_brief_write,
    reject_plan,
    serialize_lifecycle,
    validate_citations_against_snapshot,
)
from opn_oracle.oracle.custom_reports import CustomReportConflict
from opn_oracle.tenants.context import TenantContext, tenant_context


def _report(**kwargs: Any) -> SimpleNamespace:
    options = kwargs.pop("options", {})
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": kwargs.get("tenant_id", uuid.uuid4()),
        "dossier_id": kwargs.get("dossier_id", uuid.uuid4()),
        "title": "Informe demo",
        "status": "draft",
        "version": 1,
        "generation_version": 1,
        "options": options,
        "source_snapshot": {},
        "source_snapshot_hash": hashlib.sha256(b"{}").digest(),
        "snapshot_hash_algorithm": "canonical-json-sha256-v1",
        "background_job_id": None,
        "error_code": None,
        "error_message": None,
        "content": {},
        "ready_at": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "template_key": "custom_assistant_brief",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_citations_empty_allowlist_rejects() -> None:
    foreign = validate_citations_against_snapshot(
        {"allowlist": []},
        [{"evidence_id": "ev-1"}],
    )
    assert foreign == ["ev-1"]


def test_accept_plan_requires_if_match(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    report = _report(
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        options={
            "plan_status": "proposed",
            "lifecycle_state": "plan_proposed",
            "brief_request": "Analiza X",
            "proposed_plan": {
                "sections": [{"id": "a", "title": "Resumen", "required": True}],
            },
        },
    )
    session = MagicMock()
    monkeypatch.setattr(
        "opn_oracle.oracle.custom_report_lifecycle.get_custom_brief",
        lambda *a, **k: report,
    )
    with (
        tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())),
        pytest.raises(PreconditionRequired),
    ):
            accept_plan(
                session,
                dossier_id=dossier_id,
                report_id=report.id,
                actor_id=uuid.uuid4(),
                expected_version=None,
                auto_start_generation=False,
            )


def test_accept_plan_freezes_snapshot_and_degrades_without_durable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    report = _report(
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        version=2,
        options={
            "plan_status": "proposed",
            "lifecycle_state": "plan_proposed",
            "brief_request": "Cobertura de alianzas",
            "proposed_plan": {
                "version": "v1",
                "sections": [
                    {"id": "exec", "title": "Ejecutivo", "required": True},
                    {"id": "ev", "title": "Evidencias", "required": True},
                ],
            },
        },
    )
    dossier = SimpleNamespace(
        id=dossier_id,
        tenant_id=tenant_id,
        current_intent_revision_id=uuid.uuid4(),
    )
    session = MagicMock()
    session.scalar.return_value = dossier
    monkeypatch.setattr(
        "opn_oracle.oracle.custom_report_lifecycle.get_custom_brief",
        lambda *a, **k: report,
    )
    monkeypatch.setattr(
        "opn_oracle.oracle.custom_report_lifecycle.append_audit_event",
        lambda *a, **k: None,
    )
    monkeypatch.delenv("MEMORY_DURABLE_STORE_READY", raising=False)

    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=actor_id)):
        out = accept_plan(
            session,
            dossier_id=dossier_id,
            report_id=report.id,
            actor_id=actor_id,
            expected_version=2,
            auto_start_generation=False,
        )

    assert out.options["lifecycle_state"] == "plan_accepted"
    assert out.options["plan_status"] == "accepted"
    snap = out.options["accepted_snapshot"]
    assert snap["memory_mode"] == "disabled"
    assert snap["memory_policy"]["in_process_forbidden"] is True
    assert snap["allowlist"] == []
    assert out.options["memory_degraded"] is True
    assert out.options["accepted_snapshot_hash"]
    assert out.version == 3
    # Changing memory env later must not rewrite frozen hash
    frozen_hash = out.options["accepted_snapshot_hash"]
    monkeypatch.setenv("MEMORY_DURABLE_STORE_READY", "1")
    assert out.options["accepted_snapshot_hash"] == frozen_hash
    assert out.source_snapshot["memory_mode"] == "disabled"


def test_accept_version_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    report = _report(
        tenant_id=tenant_id,
        version=5,
        options={
            "lifecycle_state": "plan_proposed",
            "plan_status": "proposed",
            "proposed_plan": {"sections": [{"title": "A"}]},
        },
    )
    monkeypatch.setattr(
        "opn_oracle.oracle.custom_report_lifecycle.get_custom_brief",
        lambda *a, **k: report,
    )
    with (
        tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())),
        pytest.raises(CustomReportConflict),
    ):
            accept_plan(
                MagicMock(),
                dossier_id=report.dossier_id,
                report_id=report.id,
                actor_id=uuid.uuid4(),
                expected_version=1,
                auto_start_generation=False,
            )


def test_illegal_transition_ready_cannot_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    report = _report(
        tenant_id=tenant_id,
        status="ready",
        version=3,
        options={"lifecycle_state": "ready", "plan_status": "accepted"},
    )
    monkeypatch.setattr(
        "opn_oracle.oracle.custom_report_lifecycle.get_custom_brief",
        lambda *a, **k: report,
    )
    with (
        tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())),
        pytest.raises(IllegalTransition),
    ):
            cancel_report(
                MagicMock(),
                dossier_id=report.dossier_id,
                report_id=report.id,
                actor_id=uuid.uuid4(),
                expected_version=3,
            )


def test_writer_uses_frozen_snapshot_not_live_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    snap = {
        "allowlist": [],
        "memory_mode": "disabled",
        "accepted_plan": {
            "sections": [{"id": "a", "title": "Resumen"}],
        },
        "coverage": {"evidence_count": 0},
    }
    snap_hash = hashlib.sha256(b"snap").hexdigest()
    report = _report(
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        status="generating",
        version=4,
        options={
            "lifecycle_state": "generating",
            "accepted_snapshot": snap,
            "accepted_snapshot_hash": snap_hash,
            "accepted_plan": snap["accepted_plan"],
            "fence_token": "fence-1",
            "brief_request": "x",
        },
    )
    session = MagicMock()
    session.scalar.return_value = report
    monkeypatch.setattr(
        "opn_oracle.oracle.custom_report_lifecycle.append_audit_event",
        lambda *a, **k: None,
    )
    job = SimpleNamespace(cancel_requested=False, correlation_id="c1", id=uuid.uuid4())

    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        result = process_custom_brief_write(
            session,
            {
                "report_id": str(report.id),
                "dossier_id": str(dossier_id),
                "snapshot_hash": snap_hash,
                "fence_token": "fence-1",
            },
            job,
        )

    assert result.get("lifecycle_state") == "ready" or result.get("sha256")
    assert report.status == "ready"
    assert report.options["lifecycle_state"] == "ready"
    art = get_downloadable_artifact(report)
    assert art is not None
    assert art["sha256"] and art["byte_size"] > 0
    # Snapshot hash frozen — still the accepted one
    assert report.options["accepted_snapshot_hash"] == snap_hash
    assert report.options["ready_artifact"]["snapshot_hash"] == snap_hash


def test_late_result_after_fence_mismatch_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    report = _report(
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        status="generating",
        options={
            "lifecycle_state": "generating",
            "accepted_snapshot": {"allowlist": [], "accepted_plan": {"sections": []}},
            "accepted_snapshot_hash": "aaa",
            "fence_token": "current",
        },
    )
    session = MagicMock()
    session.scalar.return_value = report
    job = SimpleNamespace(cancel_requested=False, correlation_id="c", id=uuid.uuid4())
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        result = process_custom_brief_write(
            session,
            {
                "report_id": str(report.id),
                "dossier_id": str(dossier_id),
                "snapshot_hash": "bbb",
                "fence_token": "stale",
            },
            job,
        )
    assert result.get("dropped") is True
    assert report.status != "ready"


def test_ready_not_downloadable_when_partial() -> None:
    report = _report(
        status="generating",
        options={
            "lifecycle_state": "generating",
            "ready_artifact": {"status": "partial", "sha256": "x", "byte_size": 10},
        },
    )
    assert get_downloadable_artifact(report) is None


def test_edit_and_reject_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    report = _report(
        tenant_id=tenant_id,
        version=1,
        options={
            "lifecycle_state": "plan_proposed",
            "plan_status": "proposed",
            "proposed_plan": {"sections": [{"title": "Old"}]},
        },
    )
    monkeypatch.setattr(
        "opn_oracle.oracle.custom_report_lifecycle.get_custom_brief",
        lambda *a, **k: report,
    )
    monkeypatch.setattr(
        "opn_oracle.oracle.custom_report_lifecycle.append_audit_event",
        lambda *a, **k: None,
    )
    actor = uuid.uuid4()
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=actor)):
        edited = edit_plan(
            MagicMock(),
            dossier_id=report.dossier_id,
            report_id=report.id,
            actor_id=actor,
            expected_version=1,
            proposed_plan={"sections": [{"title": "New", "id": "n"}]},
        )
        assert edited.options["proposed_plan"]["sections"][0]["title"] == "New"
        rejected = reject_plan(
            MagicMock(),
            dossier_id=report.dossier_id,
            report_id=report.id,
            actor_id=actor,
            expected_version=edited.version,
            reason="no sirve",
        )
        assert rejected.options["lifecycle_state"] == "brief_draft"
        assert rejected.options["proposed_plan"] is None


def test_serialize_lifecycle_downloadable_flag() -> None:
    report = _report(
        status="ready",
        version=9,
        options={
            "lifecycle_state": "ready",
            "plan_status": "accepted",
            "ready_artifact": {
                "status": "available",
                "sha256": "abc",
                "byte_size": 12,
            },
        },
    )
    body = serialize_lifecycle(report)
    assert body["downloadable"] is True
    assert body["etag"] == 'W/"9"'
    assert CUSTOM_WRITE_JOB.startswith("oracle.report")
