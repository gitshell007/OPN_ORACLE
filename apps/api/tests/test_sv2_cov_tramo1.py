"""SV2-COV-TRAMO1 · product coverage for night-fresh modules.

Behavioral tests (not line-painting) for:

- ``oracle/surveillance.py`` — confirm honesty + lifecycle that 076/082 demonstrated
- ``oracle/activity.py`` — four collection states through the read model (083)
- ``integrations/memory_ask_dual.py`` — allowlist union + identity reuse + id remap (097/098)

Unit only — no PG. Style aligned with ``test_sv2_cov84_focal.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from opn_oracle.integrations.memory_ask_dual import (
    load_existing_memory_signal_mappings,
    merge_ask_citation_allowlist,
    persist_memory_signal_evidence,
    validate_citations_allowlist,
)
from opn_oracle.integrations.memory_contract_v1 import MaterializedCitation
from opn_oracle.oracle.activity import (
    _product_state_from_monitor,
    _product_state_from_procurement,
    _product_state_from_watchlist,
    _provider_snapshot_for_monitor,
    assess_collection_honesty,
    build_dossier_activity,
)
from opn_oracle.oracle.service import ResourceNotFound, VersionConflict
from opn_oracle.oracle.surveillance import (
    SurveillanceValidationError,
    compute_next_run_at,
    compute_retry_after,
    is_due,
)
from opn_oracle.tenants.context import TenantContext, tenant_context

# ---------------------------------------------------------------------------
# Shared fakes (surveillance / activity)
# ---------------------------------------------------------------------------


class _FakeScalars:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = list(rows or [])

    def all(self) -> list[Any]:
        return list(self._rows)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._rows)


class _SurvSession:
    """Minimal session for surveillance lifecycle + confirm edges."""

    def __init__(self) -> None:
        self.actions: list[Any] = []
        self.added: list[Any] = []
        self.commits = 0
        self._dossier: Any = None
        self._actor: Any = None
        self._link: Any = None
        self._connection: Any = None

    def scalar(self, stmt: Any) -> Any:
        text = str(stmt)
        if "strategic_dossiers" in text.lower() or "StrategicDossier" in text:
            return self._dossier
        if "dossier_actors" in text.lower() or "DossierActor" in text:
            return self._link
        if "integration_connections" in text.lower() or "IntegrationConnection" in text:
            return self._connection
        if "actors" in text.lower() or "Actor" in text:
            return self._actor
        if "dossier_surveillance_actions" in text.lower() or "DossierSurveillanceAction" in text:
            return self.actions[0] if self.actions else None
        return None

    def scalars(self, stmt: Any) -> _FakeScalars:
        text = str(stmt)
        if "DossierSurveillanceAction" in text or "dossier_surveillance" in text.lower():
            return _FakeScalars(self.actions)
        if "SignalMonitor" in text or "signal_monitors" in text.lower():
            return _FakeScalars([])
        if "Watchlist" in text or "watchlists" in text.lower():
            return _FakeScalars([])
        if "BackgroundJob" in text:
            return _FakeScalars([])
        return _FakeScalars([])

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if obj.__class__.__name__ == "DossierSurveillanceAction":
            if not getattr(obj, "id", None):
                obj.id = uuid.uuid4()
            self.actions.append(obj)

    def flush(self) -> None:
        for obj in self.added:
            if not getattr(obj, "id", None):
                obj.id = uuid.uuid4()

    def commit(self) -> None:
        self.commits += 1


def _base_action(**overrides: Any) -> SimpleNamespace:
    tenant = uuid.uuid4()
    data = dict(
        id=uuid.uuid4(),
        tenant_id=tenant,
        dossier_id=uuid.uuid4(),
        status="active",
        action_type="news_mentions",
        cadence="daily",
        timezone="Europe/Madrid",
        next_run_at=datetime(2026, 8, 5, 10, 0, tzinfo=UTC),
        retry_count=0,
        retry_after=None,
        last_attempt_at=None,
        last_run_at=None,
        last_error=None,
        row_version=2,
        degraded=False,
        degraded_reason=None,
        signal_monitor_id=None,
        watchlist_id=None,
        title="Vigilancia demo",
        actor_id=None,
        offering_id=None,
        requirement_id=None,
        intent_revision_id=None,
        alignment_state="aligned",
        effective_scope_hash="a" * 64,
        notes="",
    )
    data.update(overrides)
    return SimpleNamespace(**data)


# ---------------------------------------------------------------------------
# surveillance — confirm honesty + lifecycle
# ---------------------------------------------------------------------------


def test_confirm_without_monitor_stays_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    """076: confirm local sin monitor → degraded + SIGNAL-MONITOR-ABSENT (no green active)."""
    from opn_oracle.oracle import surveillance as surv

    tenant = uuid.uuid4()
    dossier_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session = _SurvSession()
    session._dossier = SimpleNamespace(
        id=dossier_id,
        tenant_id=tenant,
        status="active",
        current_intent_revision_id=None,
    )
    monkeypatch.delenv("MEMORY_SURVEILLANCE_SIGNAL_ENABLED", raising=False)
    monkeypatch.setattr(surv, "dossier_accessible", lambda *a, **k: True)
    monkeypatch.setattr(surv, "append_audit_event", lambda *a, **k: None)

    with tenant_context(TenantContext(tenant_id=tenant, actor_id=user_id)):
        action, created = surv.confirm_surveillance_action(
            session,  # type: ignore[arg-type]
            dossier_id=dossier_id,
            actor_user_id=user_id,
            payload={"action_type": "research_digest", "cadence": "weekly"},
        )
    assert created is True
    assert action.status == "active"
    assert action.signal_monitor_id is None
    assert action.degraded is True
    assert "SIGNAL-MONITOR-ABSENT" in (action.degraded_reason or "")


def test_confirm_flags_on_production_ic_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """082: IC pointing at production Signal must not stage a monitor from oracle-dev."""
    from opn_oracle.oracle import surveillance as surv

    tenant = uuid.uuid4()
    dossier_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session = _SurvSession()
    session._dossier = SimpleNamespace(
        id=dossier_id,
        tenant_id=tenant,
        status="active",
        current_intent_revision_id=None,
    )
    session._actor = SimpleNamespace(
        id=actor_id, tenant_id=tenant, canonical_name="Demo SA", actor_type="company"
    )
    session._link = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=tenant, dossier_id=dossier_id, actor_id=actor_id
    )
    session._connection = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant,
        provider="signal-avanza",
        status="active",
        adapter_mode="http",
        base_url="https://signal.opnconsultoria.com/api/v1/oracle",
        created_at=datetime.now(UTC),
    )
    monkeypatch.setenv("MEMORY_SURVEILLANCE_SIGNAL_ENABLED", "1")
    monkeypatch.setattr(surv, "dossier_accessible", lambda *a, **k: True)
    monkeypatch.setattr(surv, "append_audit_event", lambda *a, **k: None)

    with tenant_context(TenantContext(tenant_id=tenant, actor_id=user_id)):
        action, created = surv.confirm_surveillance_action(
            session,  # type: ignore[arg-type]
            dossier_id=dossier_id,
            actor_user_id=user_id,
            payload={
                "action_type": "news_mentions",
                "actor_id": str(actor_id),
                "cadence": "daily",
                "title": "must-not-hit-prod",
            },
        )
    assert created is True
    assert action.signal_monitor_id is None
    assert action.degraded is True
    assert "producción" in (action.degraded_reason or "").lower()


def test_pause_resume_retire_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lifecycle: pause → resume restores active; retire is terminal for pause."""
    from opn_oracle.oracle import surveillance as surv

    action = _base_action(status="active", row_version=1)
    session = _SurvSession()
    session.actions = [action]
    session._dossier = SimpleNamespace(
        id=action.dossier_id,
        tenant_id=action.tenant_id,
        status="active",
        current_intent_revision_id=None,
    )
    user_id = uuid.uuid4()
    monkeypatch.setattr(surv, "dossier_accessible", lambda *a, **k: True)
    monkeypatch.setattr(surv, "append_audit_event", lambda *a, **k: None)

    with tenant_context(TenantContext(tenant_id=action.tenant_id, actor_id=user_id)):
        paused = surv.pause_action(
            session,  # type: ignore[arg-type]
            action_id=action.id,
            actor_user_id=user_id,
            expected_version=1,
        )
        assert paused.status == "paused"
        assert paused.row_version == 2

        # Idempotent pause
        again = surv.pause_action(
            session,  # type: ignore[arg-type]
            action_id=action.id,
            actor_user_id=user_id,
            expected_version=2,
        )
        assert again.status == "paused"
        assert again.row_version == 2

        resumed = surv.resume_action(
            session,  # type: ignore[arg-type]
            action_id=action.id,
            actor_user_id=user_id,
            expected_version=2,
        )
        assert resumed.status == "active"
        assert resumed.row_version == 3
        assert resumed.retry_count == 0

        retired = surv.retire_action(
            session,  # type: ignore[arg-type]
            action_id=action.id,
            actor_user_id=user_id,
            expected_version=3,
        )
        assert retired.status == "retired"
        assert retired.next_run_at is None

        with pytest.raises(SurveillanceValidationError):
            surv.pause_action(
                session,  # type: ignore[arg-type]
                action_id=action.id,
                actor_user_id=user_id,
                expected_version=4,
            )


def test_sync_marks_pending_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Manual sync never invents durable remote success — stays degraded."""
    from opn_oracle.oracle import surveillance as surv

    action = _base_action(status="active", row_version=5, degraded=False, degraded_reason=None)
    session = _SurvSession()
    session.actions = [action]
    session._dossier = SimpleNamespace(
        id=action.dossier_id,
        tenant_id=action.tenant_id,
        status="active",
        current_intent_revision_id=None,
    )
    user_id = uuid.uuid4()
    monkeypatch.setattr(surv, "dossier_accessible", lambda *a, **k: True)
    monkeypatch.setattr(surv, "append_audit_event", lambda *a, **k: None)

    with tenant_context(TenantContext(tenant_id=action.tenant_id, actor_id=user_id)):
        out = surv.sync_action(
            session,  # type: ignore[arg-type]
            action_id=action.id,
            actor_user_id=user_id,
            expected_version=5,
        )
    assert out.status == "pending"
    assert out.degraded is True
    assert out.degraded_reason is not None
    assert out.last_attempt_at is not None


def test_record_run_failure_preserves_cadence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure schedules retry without consuming normal next_run_at interval."""
    from opn_oracle.oracle import surveillance as surv

    preserved = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)
    action = _base_action(
        status="active",
        next_run_at=preserved,
        retry_count=0,
        row_version=1,
    )
    session = _SurvSession()
    session.actions = [action]
    user_id = uuid.uuid4()
    monkeypatch.setattr(surv, "dossier_accessible", lambda *a, **k: True)

    with tenant_context(TenantContext(tenant_id=action.tenant_id, actor_id=user_id)):
        out = surv.record_run_failure(
            session,  # type: ignore[arg-type]
            action_id=action.id,
            error_message="upstream timeout",
        )
    assert out.next_run_at == preserved
    assert out.status == "retrying"
    assert out.retry_after is not None
    assert "timeout" in (out.last_error or "")


def test_record_run_success_clears_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    from opn_oracle.oracle import surveillance as surv

    action = _base_action(
        status="retrying",
        retry_count=3,
        retry_after=datetime.now(UTC) + timedelta(minutes=5),
        last_error="was broken",
        row_version=4,
        cadence="hourly",
    )
    session = _SurvSession()
    session.actions = [action]
    user_id = uuid.uuid4()
    monkeypatch.setattr(surv, "dossier_accessible", lambda *a, **k: True)

    with tenant_context(TenantContext(tenant_id=action.tenant_id, actor_id=user_id)):
        out = surv.record_run_success(session, action_id=action.id)  # type: ignore[arg-type]
    assert out.status == "active"
    assert out.retry_count == 0
    assert out.retry_after is None
    assert out.last_error is None
    assert out.last_run_at is not None
    assert out.next_run_at is not None


def test_adopt_and_keep_alignment(monkeypatch: pytest.MonkeyPatch) -> None:
    from opn_oracle.oracle import surveillance as surv

    intent_new = uuid.uuid4()
    action = _base_action(
        status="active",
        alignment_state="needs_review",
        intent_revision_id=uuid.uuid4(),
        row_version=2,
    )
    session = _SurvSession()
    session.actions = [action]
    session._dossier = SimpleNamespace(
        id=action.dossier_id,
        tenant_id=action.tenant_id,
        status="active",
        current_intent_revision_id=intent_new,
    )
    user_id = uuid.uuid4()
    monkeypatch.setattr(surv, "dossier_accessible", lambda *a, **k: True)
    monkeypatch.setattr(surv, "append_audit_event", lambda *a, **k: None)

    with tenant_context(TenantContext(tenant_id=action.tenant_id, actor_id=user_id)):
        adopted = surv.adopt_alignment(
            session,  # type: ignore[arg-type]
            action_id=action.id,
            actor_user_id=user_id,
            expected_version=2,
        )
        assert adopted.alignment_state == "aligned"
        assert adopted.intent_revision_id == intent_new
        assert adopted.effective_scope_hash
        assert adopted.row_version == 3

        kept = surv.keep_alignment(
            session,  # type: ignore[arg-type]
            action_id=action.id,
            actor_user_id=user_id,
            expected_version=3,
        )
        assert kept.alignment_state == "overridden"
        assert kept.row_version == 4


def test_if_match_version_conflict_and_missing_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opn_oracle.oracle import surveillance as surv

    action = _base_action(row_version=7)
    session = _SurvSession()
    session.actions = [action]
    session._dossier = SimpleNamespace(
        id=action.dossier_id,
        tenant_id=action.tenant_id,
        status="active",
        current_intent_revision_id=None,
    )
    user_id = uuid.uuid4()
    monkeypatch.setattr(surv, "dossier_accessible", lambda *a, **k: True)
    monkeypatch.setattr(surv, "append_audit_event", lambda *a, **k: None)

    with (
        tenant_context(TenantContext(tenant_id=action.tenant_id, actor_id=user_id)),
        pytest.raises(VersionConflict),
    ):
        surv.pause_action(
            session,  # type: ignore[arg-type]
            action_id=action.id,
            actor_user_id=user_id,
            expected_version=1,  # stale
        )

    empty = _SurvSession()
    with (
        tenant_context(TenantContext(tenant_id=uuid.uuid4(), actor_id=user_id)),
        pytest.raises(ResourceNotFound),
    ):
        surv.pause_action(
            empty,  # type: ignore[arg-type]
            action_id=uuid.uuid4(),
            actor_user_id=user_id,
            expected_version=1,
        )


def test_pure_cadence_edges() -> None:
    """Edges that break schedule honesty if regressing."""
    base = datetime(2026, 8, 4, 12, 0)
    # naive → treated as UTC
    nxt = compute_next_run_at(cadence="daily", from_time=base)
    assert nxt is not None and nxt.tzinfo is not None

    with pytest.raises(SurveillanceValidationError):
        compute_next_run_at(cadence="fortnightly")
    with pytest.raises(SurveillanceValidationError):
        compute_retry_after(retry_count=-1)

    assert compute_retry_after(retry_count=8) is None  # terminal
    assert is_due(
        status="retrying",
        cadence="daily",
        next_run_at=None,
        retry_after=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert not is_due(
        status="active",
        cadence="manual",
        next_run_at=datetime.now(UTC) - timedelta(hours=1),
        retry_after=None,
    )


# ---------------------------------------------------------------------------
# activity — four collection states through read model
# ---------------------------------------------------------------------------


class _ActivitySession:
    """Session that returns pre-seeded surveillance actions + optional monitors."""

    def __init__(
        self,
        *,
        dossier: Any,
        actions: list[Any],
        monitors: list[Any] | None = None,
    ) -> None:
        self._dossier = dossier
        self._actions = actions
        self._monitors = {m.id: m for m in (monitors or [])}
        self._monitor_list = list(monitors or [])

    def scalar(self, stmt: Any) -> Any:
        text = str(stmt)
        if "StrategicDossier" in text or "strategic_dossiers" in text.lower():
            return self._dossier
        if "IntegrationConnection" in text or "integration_connections" in text.lower():
            return None
        return None

    def scalars(self, stmt: Any) -> _FakeScalars:
        text = str(stmt)
        if "DossierSurveillanceAction" in text or "dossier_surveillance" in text.lower():
            return _FakeScalars(self._actions)
        if "SignalMonitor" in text or "signal_monitors" in text.lower():
            # Prefetch by id.in_(...) for surveillance, or watchlist join.
            return _FakeScalars(self._monitor_list)
        if "Watchlist" in text or "watchlists" in text.lower():
            return _FakeScalars([])
        if "ProcurementSearchProfile" in text or "procurement_search" in text.lower():
            return _FakeScalars([])
        if "BackgroundJob" in text or "background_jobs" in text.lower():
            return _FakeScalars([])
        return _FakeScalars([])


def _surv_action(
    *,
    status: str = "active",
    signal_monitor_id: uuid.UUID | None = None,
    degraded: bool = False,
    degraded_reason: str | None = None,
    title: str = "Vigilancia",
    action_type: str = "news_mentions",
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        status=status,
        action_type=action_type,
        title=title,
        cadence="daily",
        next_run_at=None,
        last_run_at=None,
        last_attempt_at=None,
        last_error=None,
        intent_revision_id=None,
        requirement_id=None,
        actor_id=None,
        offering_id=None,
        alignment_state="aligned",
        signal_monitor_id=signal_monitor_id,
        degraded=degraded,
        degraded_reason=degraded_reason,
        retry_count=0,
        retry_after=None,
        row_version=1,
        updated_at=datetime.now(UTC),
    )


def test_build_activity_four_collection_states(monkeypatch: pytest.MonkeyPatch) -> None:
    """083: read model exposes absent / not_collecting / collecting / unknown + demotes active."""
    from opn_oracle.oracle import activity as act

    tenant = uuid.uuid4()
    dossier_id = uuid.uuid4()
    user_id = uuid.uuid4()
    mon_nc = uuid.uuid4()
    mon_ok = uuid.uuid4()
    mon_unk = uuid.uuid4()

    actions = [
        _surv_action(
            tenant_id=tenant,
            dossier_id=dossier_id,
            title="A-absent",
            signal_monitor_id=None,
            degraded=True,
            degraded_reason="SIGNAL-MONITOR-ABSENT: local only",
        ),
        _surv_action(
            tenant_id=tenant,
            dossier_id=dossier_id,
            title="B-not-collecting",
            signal_monitor_id=mon_nc,
        ),
        _surv_action(
            tenant_id=tenant,
            dossier_id=dossier_id,
            title="C-collecting",
            signal_monitor_id=mon_ok,
        ),
        _surv_action(
            tenant_id=tenant,
            dossier_id=dossier_id,
            title="D-unknown",
            signal_monitor_id=mon_unk,
        ),
    ]
    monitors = [
        SimpleNamespace(
            id=mon_nc,
            tenant_id=tenant,
            external_id="ext-nc",
            connection_id=uuid.uuid4(),
            watchlist_id=uuid.uuid4(),
            desired_status="active",
            observed_status="active",
            status="active",
            last_error=None,
            next_sync_at=None,
            last_synced_at=None,
            last_sync_attempt_at=None,
            provider="signal-avanza",
        ),
        SimpleNamespace(
            id=mon_ok,
            tenant_id=tenant,
            external_id="ext-ok",
            connection_id=uuid.uuid4(),
            watchlist_id=uuid.uuid4(),
            desired_status="active",
            observed_status="active",
            status="active",
            last_error=None,
            next_sync_at=None,
            last_synced_at=None,
            last_sync_attempt_at=None,
            provider="signal-avanza",
        ),
        SimpleNamespace(
            id=mon_unk,
            tenant_id=tenant,
            external_id="ext-unk",
            connection_id=uuid.uuid4(),
            watchlist_id=uuid.uuid4(),
            desired_status="active",
            observed_status="active",
            status="active",
            last_error=None,
            next_sync_at=None,
            last_synced_at=None,
            last_sync_attempt_at=None,
            provider="signal-avanza",
        ),
    ]
    dossier = SimpleNamespace(id=dossier_id, tenant_id=tenant, status="active")
    session = _ActivitySession(dossier=dossier, actions=actions, monitors=monitors)

    def fake_snapshot(sess: Any, monitor: Any) -> tuple[dict[str, Any] | None, bool]:
        if monitor is None or not monitor.external_id:
            return None, False
        if monitor.external_id == "ext-nc":
            return (
                {
                    "status": "active",
                    "last_run_at": None,
                    "health": {"state": "ok", "last_error_code": None},
                },
                True,
            )
        if monitor.external_id == "ext-ok":
            return (
                {
                    "status": "active",
                    "last_run_at": "2026-08-03T12:00:00+00:00",
                    "health": {"state": "ok", "last_error_code": None},
                },
                True,
            )
        # ext-unk: Signal unreachable
        return None, False

    monkeypatch.setattr(act, "dossier_accessible", lambda *a, **k: True)
    monkeypatch.setattr(act, "get_current_intent", lambda *a, **k: None)
    monkeypatch.setattr(act, "list_requirements", lambda *a, **k: [])
    monkeypatch.setattr(act, "list_offerings", lambda *a, **k: [])
    monkeypatch.setattr(act, "_provider_snapshot_for_monitor", fake_snapshot)

    with tenant_context(TenantContext(tenant_id=tenant, actor_id=user_id)):
        payload = build_dossier_activity(
            session,  # type: ignore[arg-type]
            dossier_id,
            user_id,
        )

    by_title = {
        item["title"]: item for item in payload["items"] if item["kind"] == "surveillance_action"
    }
    assert set(by_title) == {"A-absent", "B-not-collecting", "C-collecting", "D-unknown"}

    a = by_title["A-absent"]
    assert a["target"]["collection_state"] == "absent"
    assert a["product_state"] == "needs_attention"  # never clean active without monitor
    assert a["target"]["degraded"] is True

    b = by_title["B-not-collecting"]
    assert b["target"]["collection_state"] == "not_collecting"
    assert b["product_state"] == "needs_attention"
    assert "SIGNAL-COLLECTION-NEVER" in (b["target"]["degraded_reason"] or "")

    c = by_title["C-collecting"]
    assert c["target"]["collection_state"] == "collecting"
    assert c["product_state"] == "active"
    assert c["target"]["degraded"] is False

    d = by_title["D-unknown"]
    assert d["target"]["collection_state"] == "unknown"
    assert d["product_state"] == "needs_attention"
    assert d["target"]["degraded"] is True

    # summary: collecting is the only clean active among the four
    assert payload["summary"]["by_state"].get("active", 0) == 1
    assert payload["summary"]["by_state"].get("needs_attention", 0) == 3


def test_collection_unknown_health_and_error_code() -> None:
    """Unrecognized health.state → unknown; error code appended on unhealthy."""
    h = assess_collection_honesty(
        has_monitor=True,
        snapshot_available=True,
        snapshot={
            "status": "active",
            "last_run_at": "2026-08-03T12:00:00+00:00",
            "health": {"state": "weird-future-state"},
        },
    )
    assert h.collection_state == "unknown"
    assert h.degraded is True

    bad = assess_collection_honesty(
        has_monitor=True,
        snapshot_available=True,
        snapshot={
            "status": "active",
            "last_run_at": "2026-08-03T12:00:00+00:00",
            "health": {"state": "error", "last_error_code": "quota_exhausted"},
        },
    )
    assert bad.collection_state == "not_collecting"
    assert "quota_exhausted" in (bad.degraded_reason or "")


def test_product_state_helpers_remaining_branches() -> None:
    assert (
        _product_state_from_monitor(
            SimpleNamespace(
                observed_status="pending",
                status="pending",
                desired_status="active",
                last_error=None,
            )
        )
        == "pending"
    )
    assert (
        _product_state_from_monitor(
            SimpleNamespace(
                observed_status="active",
                status="active",
                desired_status="disabled",
                last_error=None,
            )
        )
        == "finished"
    )
    assert (
        _product_state_from_monitor(
            SimpleNamespace(
                observed_status="active",
                status="active",
                desired_status="active",
                last_error=None,
            )
        )
        == "active"
    )
    assert _product_state_from_watchlist(SimpleNamespace(status="paused", query_config={})) == (
        "paused"
    )
    assert (
        _product_state_from_watchlist(SimpleNamespace(status="archived", query_config={}))
        == "finished"
    )
    assert (
        _product_state_from_procurement(
            SimpleNamespace(deleted_at=datetime.now(UTC), last_error_code=None, enabled=True)
        )
        == "finished"
    )
    assert (
        _product_state_from_procurement(
            SimpleNamespace(deleted_at=None, last_error_code=None, enabled=True)
        )
        == "active"
    )


def test_provider_snapshot_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing connection / adapter boom → (None, False) so UI stays unknown."""
    mon = SimpleNamespace(
        external_id="ext-1",
        connection_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
    )
    # no connection_id
    assert _provider_snapshot_for_monitor(
        SimpleNamespace(scalar=lambda *_: None),  # type: ignore[arg-type]
        SimpleNamespace(external_id="x", connection_id=None, tenant_id=uuid.uuid4()),
    ) == (None, False)

    session = SimpleNamespace(
        scalar=lambda *_: SimpleNamespace(id=uuid.uuid4(), status="active"),
    )

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("signal down")

    monkeypatch.setattr(
        "opn_oracle.integrations.service.adapter_for_connection",
        boom,
    )
    snap, ok = _provider_snapshot_for_monitor(session, mon)  # type: ignore[arg-type]
    assert snap is None and ok is False


# ---------------------------------------------------------------------------
# memory_ask_dual — allowlist union, identity reuse, citation remap
# ---------------------------------------------------------------------------


class _EvidenceSession:
    """In-memory Evidence store for persist + load_existing mappings."""

    def __init__(self) -> None:
        self.rows: list[Any] = []
        self.links: list[Any] = []
        self.added: list[Any] = []

    def scalar(self, stmt: Any) -> Any:
        text = str(stmt)
        # Evidence by id, or EvidenceDossier link, or identity search.
        if "EvidenceDossier" in text or "evidence_dossiers" in text.lower():
            # link lookup — return matching link if any
            for link in self.links:
                return link  # first is fine for our controlled cases
            return None
        if "Evidence" in text or "evidence" in text.lower():
            # Prefer id match among stored rows
            for row in self.rows:
                return row
            return None
        return None

    def scalars(self, stmt: Any) -> _FakeScalars:
        return _FakeScalars(self.rows)

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        name = obj.__class__.__name__
        if name == "Evidence":
            self.rows.append(obj)
        elif name == "EvidenceDossier":
            self.links.append(obj)

    def flush(self) -> None:
        return None


def _citation(
    *,
    evidence_id: str | None = None,
    source_ref: str = "fact:39502",
    checksum: str = "ab" * 32,
    excerpt: str = "Capgemini adjudicataria CPV 72000000",
    tenant_id: str,
    dossier_id: str,
) -> MaterializedCitation:
    return MaterializedCitation(
        oracle_evidence_id=evidence_id or str(uuid.uuid4()),
        signal_item_id="sig-1",
        source_ref=source_ref,
        checksum=checksum,
        exact_excerpt=excerpt,
        classification="internal",
        locator='{"page":1}',
        occurred_at=None,
        policy_version="memory.v1",
        watermark="wm",
        tenant_id=tenant_id,
        dossier_id=dossier_id,
    )


def test_merge_allowlist_dual_union_citable_rejects_memory_signal_from_authority() -> None:
    """097: effective allowlist = dual U dossier citable; authority memory_signal ignored."""
    dual = ["dual-1", "dual-2"]
    authority = {
        "oracle_evidence": [
            {"id": "proc-1", "source_kind": "procurement"},
            {"id": "doc-1", "source_kind": "document"},
            {"id": "mem-skip", "source_kind": "memory_signal"},  # must not bulk-import
            {"id": "  ", "source_kind": "procurement"},  # empty
            "not-a-mapping",
        ]
    }
    merged = merge_ask_citation_allowlist(
        dual,
        oracle_authority=authority,
        extra_dossier_evidence_ids=["proc-1", "extra-1"],
    )
    assert "dual-1" in merged and "dual-2" in merged
    assert "proc-1" in merged and "doc-1" in merged and "extra-1" in merged
    assert "mem-skip" not in merged
    # order: dual first, then extras, then authority
    assert merged.index("dual-1") < merged.index("proc-1")

    accepted, rejected = validate_citations_allowlist(
        [{"evidence_id": "proc-1"}, {"evidence_id": "mem-skip"}, "bad"],
        merged,
    )
    assert [c["evidence_id"] for c in accepted] == ["proc-1"]
    assert "mem-skip" in rejected
    assert "<non-object>" in rejected


def test_persist_remaps_fresh_uuid_to_durable_identity() -> None:
    """098: same source_ref+checksum → durable id; caller remaps citations to it."""
    from opn_oracle.oracle.models import Evidence

    tenant = uuid.uuid4()
    dossier = uuid.uuid4()
    durable = uuid.uuid4()
    checksum_hex = "cd" * 32
    checksum = bytes.fromhex(checksum_hex)
    existing = Evidence(
        id=durable,
        tenant_id=tenant,
        source_kind="memory_signal",
        source_url=None,
        extract="Capgemini adjudicataria CPV 72000000",
        locator={"raw": "{}", "source_ref": "fact:39502"},
        checksum=checksum,
        classification="internal",
        provenance={
            "source_ref": "fact:39502",
            "checksum": checksum_hex,
        },
        version=1,
    )
    # created_at used by load_existing ordering
    existing.created_at = datetime(2026, 8, 2, tzinfo=UTC)  # type: ignore[attr-defined]

    session = _EvidenceSession()
    session.rows = [existing]

    # Fresh uuid4 for the same identity (as materialize would mint without mappings).
    fresh = str(uuid.uuid4())
    cit = _citation(
        evidence_id=fresh,
        source_ref="fact:39502",
        checksum=checksum_hex,
        tenant_id=str(tenant),
        dossier_id=str(dossier),
    )

    # Force identity path: scalar returns None for id lookup, then existing via identity.
    calls = {"n": 0}

    def selective_scalar(stmt: Any) -> Any:
        text = str(stmt)
        calls["n"] += 1
        if "EvidenceDossier" in text or "evidence_dossiers" in text.lower():
            for link in session.links:
                return link
            return None
        # First Evidence query is by id (requested fresh) → miss
        # Identity search uses or_ on provenance/locator → hit existing
        if "as_string" in text or "source_ref" in text.lower() or "or_" in text.lower():
            return existing
        # id equality lookup: no row with that id
        if str(fresh) in text or "Evidence.id" in text:
            return None
        # fallback: if checksum filter present treat as identity
        return existing

    session.scalar = selective_scalar  # type: ignore[method-assign]

    id_map = persist_memory_signal_evidence(
        session,
        tenant_id=tenant,
        dossier_id=dossier,
        citations=[cit],
        job_id="job-1",
    )
    assert isinstance(id_map, dict)
    assert id_map[fresh] == str(durable)
    # Link to dossier created
    assert any(getattr(x, "evidence_id", None) == durable for x in session.links) or any(
        getattr(x, "evidence_id", None) == durable for x in session.added
    )

    # Remap citation like conversations.process_dossier_question_answer
    durable_id = id_map[fresh]
    assert durable_id != fresh
    remapped = MaterializedCitation(
        **{**cit.__dict__, "oracle_evidence_id": durable_id},
    )
    assert remapped.oracle_evidence_id == str(durable)

    # Effective allowlist after remap must use durable id only
    allowed = [durable_id]
    accepted, rejected = validate_citations_allowlist(
        [{"evidence_id": fresh}, {"evidence_id": durable_id}],
        allowed,
    )
    assert rejected == [fresh]
    assert [c["evidence_id"] for c in accepted] == [durable_id]


def test_load_existing_mappings_dedupes_by_identity() -> None:
    """Oldest mapping wins per source_ref+checksum; incomplete rows skipped."""
    tenant = uuid.uuid4()
    dossier = uuid.uuid4()
    old_id = uuid.uuid4()
    new_id = uuid.uuid4()
    checksum = "ee" * 32

    old = SimpleNamespace(
        id=old_id,
        provenance={"source_ref": "fact:1", "checksum": checksum},
        locator={"raw": {"page": 1}},
        checksum=bytes.fromhex(checksum),
        extract="first",
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    newer = SimpleNamespace(
        id=new_id,
        provenance={"source_ref": "fact:1", "checksum": checksum},
        locator={"raw": {"page": 2}},
        checksum=bytes.fromhex(checksum),
        extract="second-dup",
        created_at=datetime(2026, 8, 3, tzinfo=UTC),
    )
    incomplete = SimpleNamespace(
        id=uuid.uuid4(),
        provenance={},
        locator={},
        checksum=None,
        extract="skip",
        created_at=datetime(2026, 8, 4, tzinfo=UTC),
    )
    session = _EvidenceSession()
    session.rows = [old, newer, incomplete]

    mappings = load_existing_memory_signal_mappings(
        session,
        tenant_id=tenant,
        dossier_id=dossier,
    )
    assert len(mappings) == 1
    assert mappings[0]["oracle_evidence_id"] == str(old_id)
    assert mappings[0]["source_ref"] == "fact:1"
    assert mappings[0]["checksum"] == checksum


def test_persist_creates_new_row_when_no_identity_hit() -> None:
    """First sighting of a fact inserts Evidence + dossier link."""
    tenant = uuid.uuid4()
    dossier = uuid.uuid4()
    session = _EvidenceSession()
    # Always miss on lookup
    session.scalar = lambda stmt: None  # type: ignore[method-assign]
    cit = _citation(
        tenant_id=str(tenant),
        dossier_id=str(dossier),
        checksum="ff" * 32,
        source_ref="fact:new",
    )
    id_map = persist_memory_signal_evidence(
        session,
        tenant_id=tenant,
        dossier_id=dossier,
        citations=[cit],
    )
    assert id_map[cit.oracle_evidence_id] == cit.oracle_evidence_id
    assert any(x.__class__.__name__ == "Evidence" for x in session.added)
    assert any(x.__class__.__name__ == "EvidenceDossier" for x in session.added)


def test_persist_skips_checksum_mismatch_existing() -> None:
    """Immutable extract/checksum: mismatch does not rewrite and drops from map."""
    from opn_oracle.oracle.models import Evidence

    tenant = uuid.uuid4()
    dossier = uuid.uuid4()
    eid = uuid.uuid4()
    existing = Evidence(
        id=eid,
        tenant_id=tenant,
        source_kind="memory_signal",
        extract="old",
        locator={"source_ref": "fact:x"},
        checksum=bytes.fromhex("11" * 32),
        classification="internal",
        provenance={"source_ref": "fact:x", "checksum": "11" * 32},
        version=1,
    )
    session = _EvidenceSession()
    session.rows = [existing]
    session.scalar = lambda stmt: existing  # type: ignore[method-assign]

    cit = _citation(
        evidence_id=str(eid),
        source_ref="fact:x",
        checksum="22" * 32,  # different content
        excerpt="new text",
        tenant_id=str(tenant),
        dossier_id=str(dossier),
    )
    id_map = persist_memory_signal_evidence(
        session,
        tenant_id=tenant,
        dossier_id=dossier,
        citations=[cit],
    )
    assert id_map == {}
    assert existing.extract == "old"  # never rewritten
