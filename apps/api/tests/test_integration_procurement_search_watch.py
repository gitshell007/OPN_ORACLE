from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from opn_oracle.ai.models import AIUsageLedger
from opn_oracle.extensions import db
from opn_oracle.integrations.procurement import ProcurementProviderError
from opn_oracle.oracle.jobs import JobSchedule
from opn_oracle.oracle.procurement_search_watch import (
    ProcurementSearchWatch,
    ProcurementSearchWatchItem,
    ProcurementSearchWatchScanError,
    create_watch_for_saved_profile,
    purge_retired_procurement_search_watch_memory,
    retire_procurement_search_watch_for_tender_search,
    scan_procurement_search_watch,
)
from opn_oracle.reporting.models import Notification
from opn_oracle.tenants.context import TenantContext, tenant_context
from tests.test_integration_oracle_domain import (
    _accepted_tender_plan,
    _client,
    _csrf,
    _tender_wizard_artifact,
)
from tests.test_integration_oracle_domain import (
    oracle_stack as _oracle_stack_fixture,  # noqa: F401
)

pytestmark = pytest.mark.integration


def _profile(stack: tuple[Any, dict[str, uuid.UUID], str]) -> tuple[Any, str]:
    app, ids, _ = stack
    client = _client(stack)
    artifact_id = _tender_wizard_artifact(app, ids, _accepted_tender_plan())
    response = client.post(
        "/api/v1/procurement-search-profiles",
        json={
            "original_description": "Buscamos equipos de emergencia.",
            "comparables": ["ITURRI"],
            "accepted_plan": _accepted_tender_plan(),
            "ai_artifact_id": str(artifact_id),
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 201, response.get_json()
    return client, response.get_json()["id"]


def _result(
    *,
    deadline: str = "2026-08-01",
    feed_updated_at: str = "2026-07-23T08:00:00Z",
) -> dict[str, Any]:
    return {
        "results": {
            "total": 1,
            "items": [
                {
                    "folder_id": "EXP-2026-1",
                    "title": "Suministro de equipos de protección",
                    "summary_feed": "Equipamiento para emergencias.",
                    "buyer": "Ayuntamiento de Zaragoza",
                    "amount": "1200000.00",
                    "deadline": deadline,
                    "canonical_status": "open",
                    "cpv": ["18100000"],
                    "feed_updated_at": feed_updated_at,
                }
            ],
        }
    }


def _watch(stack: tuple[Any, dict[str, uuid.UUID], str], profile_id: str) -> uuid.UUID:
    app, ids, _ = stack
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        # The test only needs the profile identity; use SQLAlchemy's mapped class to keep the
        # database relationship and RLS path identical to production.
        from opn_oracle.oracle.procurement_search_profiles import ProcurementSearchProfile

        stored = db.session.get(ProcurementSearchProfile, uuid.UUID(profile_id))
        assert stored is not None
        watch = create_watch_for_saved_profile(
            db.session(),
            stored,
            name="Equipamiento de emergencias",
            tender_search_id=f"signal-watch-{profile_id}",
        )
        watch_id = watch.id
        db.session.commit()
        db.session.remove()
        return watch_id


def test_incremental_watch_detects_new_changed_seen_and_stays_silent_without_changes(
    request: pytest.FixtureRequest,
) -> None:
    stack = request.getfixturevalue("_oracle_stack_fixture")
    app, ids, _ = stack
    client, profile_id = _profile(stack)
    watch_id = _watch(stack, profile_id)

    activated = client.patch(
        f"/api/v1/procurement-search-watches/{watch_id}",
        json={
            "enabled": True,
            "notifications_enabled": True,
            "cadence_seconds": 3600,
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert activated.status_code == 200, activated.get_json()
    assert activated.get_json()["new_count"] == 0
    assert activated.get_json()["cadence_seconds"] == 3600

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
        first = scan_procurement_search_watch(
            db.session(), watch_id, job_id=uuid.uuid4(), runner=lambda **_: _result()
        )
        second = scan_procurement_search_watch(
            db.session(), watch_id, job_id=uuid.uuid4(), runner=lambda **_: _result()
        )
        changed = scan_procurement_search_watch(
            db.session(),
            watch_id,
            job_id=uuid.uuid4(),
            runner=lambda **_: _result(deadline="2026-08-08"),
        )
        ledger_after = int(
            db.session.scalar(
                select(func.count(AIUsageLedger.id)).where(
                    AIUsageLedger.tenant_id == ids["tenant_a"]
                )
            )
            or 0
        )
        notifications = int(
            db.session.scalar(
                select(func.count(Notification.id)).where(
                    Notification.tenant_id == ids["tenant_a"],
                    Notification.notification_type == "procurement.watch",
                )
            )
            or 0
        )
        row = db.session.scalar(
            select(ProcurementSearchWatchItem).where(
                ProcurementSearchWatchItem.watch_id == watch_id
            )
        )
        assert row is not None and row.reviewed_at is None
        assert row.last_change_fields == ["deadline"]
        assert first["new"] == 1 and first["changed"] == 0 and first["notified"] is True
        assert second == {
            "status": "succeeded",
            "new": 0,
            "changed": 0,
            "seen": 1,
            "notified": False,
            "result_count": 1,
        }
        assert changed["new"] == 0 and changed["changed"] == 1
        assert notifications == 2
        assert ledger_after == ledger_before

    listed = client.get(f"/api/v1/procurement-search-watches/{watch_id}/items")
    assert listed.status_code == 200, listed.get_json()
    assert listed.get_json()["items"][0]["state"] == "changed"
    # Feedback is also an explicit human review: it must close the novelty
    # badge without invoking an AI flow or waiting for the next scan.
    feedback = client.post(
        f"/api/v1/procurement-search-profiles/{profile_id}/feedback",
        json={
            "plan_version": 1,
            "folder_id": "EXP-2026-1",
            "verdict": "relevant",
            "reason": None,
            "note": "La persona ya la ha valorado.",
            "tender": {"title": "Suministro de equipos de protección", "cpvs": ["18100000"]},
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert feedback.status_code == 201, feedback.get_json()
    after_feedback = client.get(f"/api/v1/procurement-search-watches/{watch_id}/items")
    assert after_feedback.get_json()["items"][0]["state"] == "reviewed"
    reviewed = client.post(
        f"/api/v1/procurement-search-watches/{watch_id}/items/reviewed",
        json={"folder_ids": ["EXP-2026-1"], "reviewed": True},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert reviewed.status_code == 200, reviewed.get_json()
    assert reviewed.get_json()["items"][0]["state"] == "reviewed"
    undone = client.post(
        f"/api/v1/procurement-search-watches/{watch_id}/items/reviewed",
        json={"folder_ids": ["EXP-2026-1"], "reviewed": False},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert undone.status_code == 200, undone.get_json()
    assert undone.get_json()["items"][0]["state"] == "changed"


def test_watch_provider_failure_preserves_last_success_and_is_retryable(
    request: pytest.FixtureRequest,
) -> None:
    stack = request.getfixturevalue("_oracle_stack_fixture")
    app, ids, _ = stack
    client, profile_id = _profile(stack)
    watch_id = _watch(stack, profile_id)
    activated = client.patch(
        f"/api/v1/procurement-search-watches/{watch_id}",
        json={"enabled": True, "notifications_enabled": False},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert activated.status_code == 200, activated.get_json()
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        stored = db.session.get(ProcurementSearchWatch, watch_id)
        assert stored is not None
        scan_procurement_search_watch(
            db.session(), watch_id, job_id=uuid.uuid4(), runner=lambda **_: _result()
        )
        previous_success = db.session.get(ProcurementSearchWatch, watch_id).last_success_at
        with pytest.raises(ProcurementSearchWatchScanError) as failed:
            scan_procurement_search_watch(
                db.session(),
                watch_id,
                job_id=uuid.uuid4(),
                runner=lambda **_: (_ for _ in ()).throw(
                    ProcurementProviderError(
                        status_code=503,
                        code="procurement_provider_unavailable",
                        detail="Signal no está disponible temporalmente.",
                        retryable=True,
                    )
                ),
            )
        assert failed.value.retryable is True
        refreshed = db.session.get(ProcurementSearchWatch, watch_id)
        assert refreshed is not None
        assert refreshed.last_success_at == previous_success
        assert refreshed.last_error_code == "procurement_provider_unavailable"
        assert (
            retire_procurement_search_watch_for_tender_search(
                db.session(), tender_search_id=f"signal-watch-{profile_id}"
            )
            is True
        )
        retired = db.session.get(ProcurementSearchWatch, watch_id)
        schedule = db.session.scalar(
            select(JobSchedule).where(
                JobSchedule.tenant_id == ids["tenant_a"],
                JobSchedule.schedule_key == f"procurement-watch:{watch_id}",
            )
        )
        assert retired is not None and retired.enabled is False and retired.deleted_at is not None
        assert schedule is not None and schedule.enabled is False
        retired.deleted_at = datetime.now(UTC) - timedelta(days=91)
        db.session.commit()
        assert purge_retired_procurement_search_watch_memory(db.session()) == 1
        assert (
            db.session.scalar(
                select(func.count(ProcurementSearchWatchItem.id)).where(
                    ProcurementSearchWatchItem.watch_id == watch_id
                )
            )
            == 0
        )
