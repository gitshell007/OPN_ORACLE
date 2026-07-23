from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select

from opn_oracle.ai.models import AIArtifact, AIUsageLedger
from opn_oracle.extensions import db
from opn_oracle.jobs.tasks import execute_durable
from opn_oracle.oracle.jobs import AIAuditLog, BackgroundJob
from opn_oracle.oracle.procurement_search_feedback import (
    ProcurementSearchFeedback,
    build_procurement_search_feedback_digest,
)
from opn_oracle.oracle.procurement_search_profiles import (
    ProcurementSearchProfileNotFound,
)
from opn_oracle.tenants.context import TenantContext, tenant_context
from tests.test_integration_oracle_domain import (
    _accepted_tender_plan,
    _client,
    _csrf,
    _enable_mock_ai,
    _tender_wizard_artifact,
)
from tests.test_integration_oracle_domain import (
    oracle_stack as _oracle_stack_fixture,  # noqa: F401
)

pytestmark = pytest.mark.integration


def _profile(stack: tuple[Any, dict[str, uuid.UUID], str]) -> tuple[Any, str]:
    app, ids, _ = stack
    client = _client(stack)
    plan = _accepted_tender_plan()
    artifact_id = _tender_wizard_artifact(app, ids, plan)
    response = client.post(
        "/api/v1/procurement-search-profiles",
        json={
            "original_description": "Buscamos equipos de emergencia.",
            "comparables": ["ITURRI"],
            "accepted_plan": plan,
            "ai_artifact_id": str(artifact_id),
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 201, response.get_json()
    return client, response.get_json()["id"]


def test_feedback_repeat_digest_and_undo_need_no_ai_usage(
    request: pytest.FixtureRequest,
) -> None:
    stack = request.getfixturevalue("_oracle_stack_fixture")
    app, ids, _ = stack
    client, profile_id = _profile(stack)
    endpoint = f"/api/v1/procurement-search-profiles/{profile_id}/feedback"
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        ledger_before = int(
            db.session.scalar(
                select(func.count(AIUsageLedger.id)).where(
                    AIUsageLedger.tenant_id == ids["tenant_a"]
                )
            )
            or 0
        )

    invalid = client.post(
        endpoint,
        json={
            "plan_version": 1,
            "folder_id": "EXP/2026/1",
            "verdict": "relevant",
            "reason": "wrong_sector",
            "tender": {"title": "Vehículos de emergencia", "cpvs": ["35110000"]},
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert invalid.status_code == 422
    assert invalid.get_json()["errors"] == {
        "reason": ["Una licitación relevante no lleva motivo de descarte."]
    }

    first_payload = {
        "plan_version": 1,
        "folder_id": "EXP/2026/1",
        "verdict": "relevant",
        "reason": None,
        "note": "",
        "tender": {
            "title": "Vehículos de emergencia",
            "cpvs": ["35110000"],
        },
    }
    first = client.post(
        endpoint,
        json=first_payload,
        headers={"X-CSRF-Token": _csrf(client)},
    )
    repeated = client.post(
        endpoint,
        json=first_payload,
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert first.status_code == 201, first.get_json()
    assert repeated.status_code == 201, repeated.get_json()
    assert repeated.get_json()["id"] == first.get_json()["id"]

    replacement = client.post(
        endpoint,
        json={
            **first_payload,
            "verdict": "not_relevant",
            "reason": "wrong_sector",
            "note": "Es mantenimiento, no equipamiento.",
            "tender": {
                "title": "Mantenimiento y limpieza técnica",
                "cpvs": ["18100000"],
            },
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert replacement.status_code == 201, replacement.get_json()
    assert replacement.get_json()["id"] != first.get_json()["id"]

    current = client.get(endpoint)
    history = client.get(f"{endpoint}?include_history=true")
    assert current.status_code == 200
    assert current.get_json()["total"] == 1
    assert current.get_json()["items"][0]["state"] == "current"
    assert history.status_code == 200
    assert history.get_json()["total"] == 2
    assert {item["state"] for item in history.get_json()["items"]} == {
        "current",
        "superseded",
    }

    digest_response = client.get(
        f"/api/v1/procurement-search-profiles/{profile_id}/feedback-digest"
    )
    assert digest_response.status_code == 200, digest_response.get_json()
    digest = digest_response.get_json()
    assert digest["counts"]["not_relevant"] == 1
    assert digest["reasons"]["wrong_sector"] == 1
    assert digest["new_feedback_count"] == 1
    assert "mantenimiento" in {item["value"] for item in digest["exclusion_candidates"]["terms"]}

    feedback_id = replacement.get_json()["id"]
    withdrawn = client.delete(
        f"{endpoint}/{feedback_id}",
        headers={"X-CSRF-Token": _csrf(client)},
    )
    repeated_withdrawal = client.delete(
        f"{endpoint}/{feedback_id}",
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert withdrawn.status_code == 204
    assert repeated_withdrawal.status_code == 204
    empty_digest = client.get(
        f"/api/v1/procurement-search-profiles/{profile_id}/feedback-digest"
    ).get_json()
    assert empty_digest["counts"]["total"] == 0
    assert empty_digest["digest_hash"] != digest["digest_hash"]

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        ledger_after = int(
            db.session.scalar(
                select(func.count(AIUsageLedger.id)).where(
                    AIUsageLedger.tenant_id == ids["tenant_a"]
                )
            )
            or 0
        )
        stored = db.session.scalar(
            select(func.count(ProcurementSearchFeedback.id)).where(
                ProcurementSearchFeedback.profile_id == uuid.UUID(profile_id)
            )
        )
        assert stored == 2
        assert ledger_after == ledger_before


def test_feedback_and_digest_are_tenant_scoped(
    request: pytest.FixtureRequest,
) -> None:
    stack = request.getfixturevalue("_oracle_stack_fixture")
    app, ids, _ = stack
    client, profile_id = _profile(stack)
    created = client.post(
        f"/api/v1/procurement-search-profiles/{profile_id}/feedback",
        json={
            "plan_version": 1,
            "folder_id": "EXP-TENANT-A",
            "verdict": "not_relevant",
            "reason": "region",
            "tender": {"title": "Servicio fuera de región", "cpvs": []},
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert created.status_code == 201, created.get_json()
    feedback_id = uuid.UUID(created.get_json()["id"])

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_b"], actor_id=ids["user"])),
    ):
        assert (
            db.session.scalar(
                select(ProcurementSearchFeedback).where(ProcurementSearchFeedback.id == feedback_id)
            )
            is None
        )
        with pytest.raises(ProcurementSearchProfileNotFound):
            build_procurement_search_feedback_digest(
                db.session(),
                uuid.UUID(profile_id),
            )


def test_feedback_replan_uses_exactly_one_ai_call_and_reuses_artifact_by_digest(
    request: pytest.FixtureRequest,
) -> None:
    stack = request.getfixturevalue("_oracle_stack_fixture")
    app, ids, _ = stack
    _enable_mock_ai(app, ids)
    client, profile_id = _profile(stack)
    feedback_endpoint = f"/api/v1/procurement-search-profiles/{profile_id}/feedback"
    registered = client.post(
        feedback_endpoint,
        json={
            "plan_version": 1,
            "folder_id": "EXP-REPLAN-1",
            "verdict": "not_relevant",
            "reason": "wrong_sector",
            "note": "Limpieza operativa, fuera del foco de emergencia.",
            "tender": {
                "title": "Servicio de limpieza de dependencias municipales",
                "cpvs": ["90910000"],
            },
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert registered.status_code == 201, registered.get_json()
    digest_response = client.get(
        f"/api/v1/procurement-search-profiles/{profile_id}/feedback-digest"
    )
    assert digest_response.status_code == 200, digest_response.get_json()
    digest = digest_response.get_json()

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        ledger_before = int(
            db.session.scalar(
                select(func.count(AIUsageLedger.id))
                .join(AIAuditLog, AIAuditLog.id == AIUsageLedger.audit_log_id)
                .where(
                    AIUsageLedger.tenant_id == ids["tenant_a"],
                    AIAuditLog.agent == "tender_search_wizard",
                )
            )
            or 0
        )

    first = client.post(
        f"/api/v1/procurement-search-profiles/{profile_id}/replans",
        json={"expected_version": 1, "digest_hash": digest["digest_hash"]},
        headers={
            "X-CSRF-Token": _csrf(client),
            "Idempotency-Key": f"replan-first-{uuid.uuid4()}",
        },
    )
    assert first.status_code == 202, first.get_json()

    class TaskProbe:
        request = type("Request", (), {"id": ""})()

    def run_job(job_id: str) -> dict[str, Any]:
        with (
            app.app_context(),
            tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
        ):
            job = db.session.get(BackgroundJob, uuid.UUID(job_id))
            assert job is not None
            assert job.status != "failed", job.error_message
            if job.status == "succeeded":
                result = dict(job.result_ref)
                db.session.remove()
                return result
            payload = dict(job.input_payload)
            db.session.remove()
        with app.app_context():
            return execute_durable(  # type: ignore[arg-type]
                TaskProbe(),
                job_id=job_id,
                tenant_id=str(ids["tenant_a"]),
                payload=payload,
            )

    first_result = run_job(first.get_json()["job"]["id"])
    assert "artifact_id" in first_result

    second = client.post(
        f"/api/v1/procurement-search-profiles/{profile_id}/replans",
        json={"expected_version": 1, "digest_hash": digest["digest_hash"]},
        headers={
            "X-CSRF-Token": _csrf(client),
            "Idempotency-Key": f"replan-second-{uuid.uuid4()}",
        },
    )
    assert second.status_code == 202, second.get_json()
    second_result = run_job(second.get_json()["job"]["id"])
    if first.get_json()["artifact"] is not None:
        assert first.get_json()["artifact"]["id"] == first_result["artifact_id"]
    assert second_result["artifact_id"] == first_result["artifact_id"]

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        ledger_after = int(
            db.session.scalar(
                select(func.count(AIUsageLedger.id))
                .join(AIAuditLog, AIAuditLog.id == AIUsageLedger.audit_log_id)
                .where(
                    AIUsageLedger.tenant_id == ids["tenant_a"],
                    AIAuditLog.agent == "tender_search_wizard",
                )
            )
            or 0
        )
        artifact = db.session.get(AIArtifact, uuid.UUID(first_result["artifact_id"]))
        assert artifact is not None
        assert "limpieza" in artifact.output["exclude_terms"]
    assert ledger_after == ledger_before + 1
