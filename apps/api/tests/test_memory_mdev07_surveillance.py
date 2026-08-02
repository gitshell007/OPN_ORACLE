"""MDEV-07 · cadence, confirm idempotency, needs_review, adapter fail-closed, HTTP gates."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from opn_oracle.integrations.surveillance_signal_adapter import (
    publish_surveillance_scope,
)
from opn_oracle.oracle.surveillance import (
    ACTION_TYPES,
    CADENCES,
    PreconditionRequired,
    build_dedupe_key,
    build_oracle_to_signal_scope,
    compute_next_run_at,
    compute_retry_after,
    effective_scope_hash,
    is_due,
    serialize_action,
)

# ---------------------------------------------------------------------------
# Pure cadence
# ---------------------------------------------------------------------------


def test_cadences_include_product_set() -> None:
    assert frozenset({"manual", "hourly", "daily", "weekly"}) == CADENCES
    assert "news_mentions" in ACTION_TYPES
    assert "no_follow" in ACTION_TYPES
    assert "offering_tenders" in ACTION_TYPES
    assert "research_digest" in ACTION_TYPES


def test_manual_never_schedules_next_run() -> None:
    assert compute_next_run_at(cadence="manual") is None


def test_hourly_daily_weekly_next_run_real() -> None:
    base = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
    hourly = compute_next_run_at(cadence="hourly", from_time=base)
    daily = compute_next_run_at(cadence="daily", from_time=base)
    weekly = compute_next_run_at(cadence="weekly", from_time=base)
    assert hourly is not None and hourly > base
    assert daily is not None and daily >= base + timedelta(hours=23)
    assert weekly is not None and weekly >= base + timedelta(days=6)
    # Beat tick ≠ cadence: deltas are wall intervals, not 15-minute ticks.
    assert (hourly - base) >= timedelta(minutes=59)


def test_retry_does_not_consume_normal_interval() -> None:
    base = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
    r0 = compute_retry_after(retry_count=0, from_time=base)
    r1 = compute_retry_after(retry_count=1, from_time=base)
    r_max = compute_retry_after(retry_count=8, from_time=base)
    assert r0 == base + timedelta(minutes=5)
    assert r1 == base + timedelta(minutes=15)
    assert r_max is None  # terminal — no infinite polling


def test_is_due_respects_status_and_cadence() -> None:
    now = datetime(2026, 8, 2, 15, 0, tzinfo=UTC)
    assert (
        is_due(
            status="active",
            cadence="daily",
            next_run_at=now - timedelta(minutes=1),
            retry_after=None,
            now=now,
        )
        is True
    )
    assert (
        is_due(
            status="paused",
            cadence="daily",
            next_run_at=now - timedelta(minutes=1),
            retry_after=None,
            now=now,
        )
        is False
    )
    assert (
        is_due(
            status="active",
            cadence="manual",
            next_run_at=None,
            retry_after=None,
            now=now,
        )
        is False
    )
    assert (
        is_due(
            status="retrying",
            cadence="daily",
            next_run_at=now + timedelta(days=1),  # normal interval preserved
            retry_after=now - timedelta(seconds=1),
            now=now,
        )
        is True
    )


def test_effective_scope_hash_stable() -> None:
    a = effective_scope_hash({"b": 1, "a": 2})
    b = effective_scope_hash({"a": 2, "b": 1})
    assert a == b
    assert len(a) == 64


def test_dedupe_key() -> None:
    actor = uuid.uuid4()
    assert "news_mentions" in build_dedupe_key(
        action_type="news_mentions", actor_id=actor, offering_id=None
    )


def test_build_oracle_to_signal_scope_requires_links() -> None:
    action = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        action_type="news_mentions",
        actor_id=uuid.uuid4(),
        offering_id=None,
        requirement_id=None,
        intent_revision_id=uuid.uuid4(),
        effective_scope_hash="b" * 64,
        cadence="daily",
        timezone="Europe/Madrid",
        origin="user",
        confirmed_by_user_id=uuid.uuid4(),
        confirmed_at=datetime.now(UTC),
        alignment_state="aligned",
        manual_overrides={},
    )
    env = build_oracle_to_signal_scope(
        action,  # type: ignore[arg-type]
        consumer_id="opn-oracle",
        external_tenant_id="ext-1",
    )
    assert env["consumer_id"] == "opn-oracle"
    assert env["dossier_id"] == str(action.dossier_id)
    assert env["scope"]["effective_scope_hash"] == "b" * 64
    assert env["provenance"]["alignment_state"] == "aligned"


def test_adapter_disabled_and_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    action = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        action_type="actor_tenders",
        actor_id=uuid.uuid4(),
        offering_id=None,
        requirement_id=None,
        intent_revision_id=None,
        effective_scope_hash="c" * 64,
        cadence="weekly",
        timezone="Europe/Madrid",
        origin="user",
        confirmed_by_user_id=uuid.uuid4(),
        confirmed_at=datetime.now(UTC),
        alignment_state="aligned",
        manual_overrides={},
    )
    monkeypatch.delenv("MEMORY_SURVEILLANCE_SIGNAL_ENABLED", raising=False)
    off = publish_surveillance_scope(
        action,  # type: ignore[arg-type]
        consumer_id="opn-oracle",
        external_tenant_id="ext",
    )
    assert off["status"] == "disabled"
    assert off["published"] is False

    monkeypatch.setenv("MEMORY_SURVEILLANCE_SIGNAL_ENABLED", "1")
    monkeypatch.delenv("MEMORY_DURABLE_STORE_READY", raising=False)
    deg = publish_surveillance_scope(
        action,  # type: ignore[arg-type]
        consumer_id="opn-oracle",
        external_tenant_id="ext",
    )
    assert deg["status"] == "degraded"
    assert deg["error_code"] == "DUR-MDEV05-001"
    assert deg["published"] is False


def test_serialize_action_shape() -> None:
    action = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        action_type="no_follow",
        title="Sin seguimiento",
        status="retired",
        alignment_state="aligned",
        cadence="manual",
        timezone="Europe/Madrid",
        actor_id=uuid.uuid4(),
        offering_id=None,
        requirement_id=None,
        intent_revision_id=None,
        effective_scope_hash="d" * 64,
        origin="user",
        confirmed_by_user_id=uuid.uuid4(),
        confirmed_at=datetime.now(UTC),
        manual_overrides={},
        last_run_at=None,
        next_run_at=None,
        last_attempt_at=None,
        last_error=None,
        retry_count=0,
        retry_after=None,
        row_version=1,
        watchlist_id=None,
        signal_monitor_id=None,
        procurement_watch_id=None,
        degraded=False,
        degraded_reason=None,
        notes="",
    )
    body = serialize_action(action)  # type: ignore[arg-type]
    assert body["action_type"] == "no_follow"
    assert body["status"] == "retired"
    assert body["row_version"] == 1


# ---------------------------------------------------------------------------
# Service-level with fake session (no PG required)
# ---------------------------------------------------------------------------


class _FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeResult:
    def __init__(self, row: Any = None, rows: list[Any] | None = None) -> None:
        self._row = row
        self._rows = rows or ([] if row is None else [row])

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeSession:
    def __init__(self) -> None:
        self.actions: list[Any] = []
        self.added: list[Any] = []
        self.commits = 0
        self._dossier: Any = None
        self._actor: Any = None
        self._link: Any = None

    def scalar(self, stmt: Any) -> Any:
        # Heuristic by inspecting compiled-ish string or entity type in with_for_update chains.
        text = str(stmt)
        if "strategic_dossiers" in text.lower() or "StrategicDossier" in text:
            return self._dossier
        if "dossier_actors" in text.lower() or "DossierActor" in text:
            return self._link
        if "actors" in text.lower() or "Actor" in text:
            return self._actor
        if "dossier_surveillance_actions" in text.lower() or "DossierSurveillanceAction" in text:
            if self.actions:
                return self.actions[0]
            return None
        return None

    def scalars(self, stmt: Any) -> _FakeScalars:
        text = str(stmt)
        if "Watchlist" in text or "watchlists" in text.lower():
            return _FakeScalars([])
        if "SignalMonitor" in text or "signal_monitors" in text.lower():
            return _FakeScalars([])
        if "BackgroundJob" in text:
            return _FakeScalars([])
        if "DossierSurveillanceAction" in text or "dossier_surveillance" in text.lower():
            return _FakeScalars(self.actions)
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


def test_confirm_idempotent_and_actor_zero_monitors(monkeypatch: pytest.MonkeyPatch) -> None:
    from opn_oracle.oracle import surveillance as surv
    from opn_oracle.tenants.context import TenantContext, tenant_context

    tenant = uuid.uuid4()
    dossier_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session = _FakeSession()
    session._dossier = SimpleNamespace(
        id=dossier_id,
        tenant_id=tenant,
        status="active",
        current_intent_revision_id=uuid.uuid4(),
    )
    session._actor = SimpleNamespace(id=actor_id, tenant_id=tenant)
    session._link = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=tenant, dossier_id=dossier_id, actor_id=actor_id
    )

    monkeypatch.setattr(surv, "dossier_accessible", lambda *a, **k: True)
    monkeypatch.setattr(surv, "append_audit_event", lambda *a, **k: None)

    with tenant_context(TenantContext(tenant_id=tenant, actor_id=user_id)):
        first, created = surv.confirm_surveillance_action(
            session,  # type: ignore[arg-type]
            dossier_id=dossier_id,
            actor_user_id=user_id,
            payload={
                "action_type": "news_mentions",
                "actor_id": str(actor_id),
                "cadence": "daily",
                "timezone": "Europe/Madrid",
            },
        )
        assert created is True
        assert first.status == "active"
        assert first.next_run_at is not None
        assert first.signal_monitor_id is None
        assert first.watchlist_id is None
        assert first.effective_scope_hash

        second, created2 = surv.confirm_surveillance_action(
            session,  # type: ignore[arg-type]
            dossier_id=dossier_id,
            actor_user_id=user_id,
            payload={
                "action_type": "news_mentions",
                "actor_id": str(actor_id),
                "cadence": "daily",
            },
        )
        assert created2 is False
        assert second.id == first.id
        assert len(session.actions) == 1

        assert (
            surv.count_monitors_for_actor(
                session,  # type: ignore[arg-type]
                dossier_id=dossier_id,
                actor_id=actor_id,
            )
            == 0
        )
        assert (
            surv.count_jobs_for_actor_surveillance(
                session,  # type: ignore[arg-type]
                dossier_id=dossier_id,
                actor_id=actor_id,
            )
            == 0
        )


def test_no_follow_creates_no_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    from opn_oracle.oracle import surveillance as surv
    from opn_oracle.tenants.context import TenantContext, tenant_context

    tenant = uuid.uuid4()
    dossier_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session = _FakeSession()
    session._dossier = SimpleNamespace(
        id=dossier_id,
        tenant_id=tenant,
        status="active",
        current_intent_revision_id=None,
    )
    session._actor = SimpleNamespace(id=actor_id, tenant_id=tenant)
    session._link = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=tenant, dossier_id=dossier_id, actor_id=actor_id
    )
    monkeypatch.setattr(surv, "dossier_accessible", lambda *a, **k: True)
    monkeypatch.setattr(surv, "append_audit_event", lambda *a, **k: None)

    with tenant_context(TenantContext(tenant_id=tenant, actor_id=user_id)):
        action, created = surv.confirm_surveillance_action(
            session,  # type: ignore[arg-type]
            dossier_id=dossier_id,
            actor_user_id=user_id,
            payload={"action_type": "no_follow", "actor_id": str(actor_id)},
        )
        assert created is True
        assert action.status == "retired"
        assert action.next_run_at is None


def test_needs_review_on_intent_supersede(monkeypatch: pytest.MonkeyPatch) -> None:
    from opn_oracle.oracle import surveillance as surv
    from opn_oracle.tenants.context import TenantContext, tenant_context

    tenant = uuid.uuid4()
    dossier_id = uuid.uuid4()
    prev = uuid.uuid4()
    new = uuid.uuid4()
    action = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant,
        dossier_id=dossier_id,
        status="active",
        intent_revision_id=prev,
        alignment_state="aligned",
        row_version=1,
    )
    session = _FakeSession()
    session.actions = [action]

    with tenant_context(TenantContext(tenant_id=tenant, actor_id=uuid.uuid4())):
        # Override scalars for_update path — mark uses scalars with for_update
        session.scalars = lambda stmt: _FakeScalars([action])  # type: ignore[method-assign]
        n = surv.mark_actions_needs_review_for_superseded_intent(
            session,  # type: ignore[arg-type]
            dossier_id=dossier_id,
            previous_revision_id=prev,
            new_revision_id=new,
        )
    assert n == 1
    assert action.alignment_state == "needs_review"
    assert action.row_version == 2
    # Status unchanged (no reconfigure/reactivate)
    assert action.status == "active"


def test_retry_preserves_next_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from opn_oracle.oracle import surveillance as surv
    from opn_oracle.tenants.context import TenantContext, tenant_context

    tenant = uuid.uuid4()
    user_id = uuid.uuid4()
    preserved = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    action = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant,
        dossier_id=uuid.uuid4(),
        status="active",
        action_type="news_mentions",
        cadence="daily",
        timezone="Europe/Madrid",
        next_run_at=preserved,
        retry_count=0,
        retry_after=None,
        last_attempt_at=None,
        last_error=None,
        row_version=2,
    )
    session = _FakeSession()
    session.actions = [action]
    session._dossier = SimpleNamespace(
        id=action.dossier_id, tenant_id=tenant, status="active", current_intent_revision_id=None
    )
    monkeypatch.setattr(surv, "dossier_accessible", lambda *a, **k: True)
    monkeypatch.setattr(surv, "append_audit_event", lambda *a, **k: None)

    with tenant_context(TenantContext(tenant_id=tenant, actor_id=user_id)):
        out = surv.retry_action(
            session,  # type: ignore[arg-type]
            action_id=action.id,
            actor_user_id=user_id,
            expected_version=2,
        )
    assert out.next_run_at == preserved
    assert out.status == "retrying"
    assert out.retry_after is not None
    assert out.row_version == 3


def test_if_match_precondition() -> None:
    from opn_oracle.oracle import surveillance as surv

    action = SimpleNamespace(row_version=3)
    with pytest.raises(PreconditionRequired):
        surv._require_if_match(action, None)  # type: ignore[arg-type]
    with pytest.raises(PreconditionRequired):
        surv._require_if_match(action, 0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# HTTP Flask real (permission gates)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_http_confirm_requires_write_permission(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager

    from flask import g

    from opn_oracle.auth import permissions
    from opn_oracle.oracle import surveillance_routes
    from opn_oracle.platform.models import User

    actor = User(
        id=uuid.uuid4(),
        email="viewer@example.com",
        display_name="Viewer",
        status="active",
    )
    tid = uuid.uuid4()

    @contextmanager
    def _auth(allowed: frozenset[str]) -> Iterator[None]:
        monkeypatch.setattr(permissions, "current_user", actor)
        monkeypatch.setattr(surveillance_routes, "current_user", actor)
        monkeypatch.setattr(
            permissions,
            "current_permissions",
            lambda user_id, active_tenant_id: allowed,
        )
        before = app.before_request_funcs.get(None, [])
        idx = next(
            i for i, f in enumerate(before) if f.__name__ == "protect_csrf_and_install_identity"
        )
        original = before[idx]

        def install() -> None:
            g.active_tenant_id = tid

        before[idx] = install
        try:
            yield
        finally:
            before[idx] = original

    dossier_id = uuid.uuid4()
    with _auth(frozenset({"dossier.read"})):
        resp = client.post(
            f"/api/v1/dossiers/{dossier_id}/surveillance-actions/confirm",
            json={"action_type": "news_mentions", "actor_id": str(uuid.uuid4())},
            headers={"Idempotency-Key": "viewer-denied-key-01"},
        )
    # Viewer cannot confirm (requires dossier.write)
    assert resp.status_code in {403, 401}

    with _auth(frozenset({"dossier.read"})):
        resp2 = client.post(
            f"/api/v1/dossiers/{dossier_id}/surveillance-actions/{uuid.uuid4()}/retry",
            headers={"Idempotency-Key": "viewer-retry-denied", "If-Match": 'W/"1"'},
        )
    assert resp2.status_code in {403, 401}


@pytest.mark.unit
def test_http_pause_requires_if_match(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager

    from flask import g

    from opn_oracle.auth import permissions
    from opn_oracle.oracle import surveillance_routes
    from opn_oracle.platform.models import User

    actor = User(
        id=uuid.uuid4(),
        email="editor@example.com",
        display_name="Editor",
        status="active",
    )
    tid = uuid.uuid4()
    dossier_id = uuid.uuid4()
    action_id = uuid.uuid4()

    @contextmanager
    def _auth(allowed: frozenset[str]) -> Iterator[None]:
        monkeypatch.setattr(permissions, "current_user", actor)
        monkeypatch.setattr(surveillance_routes, "current_user", actor)
        monkeypatch.setattr(
            permissions,
            "current_permissions",
            lambda user_id, active_tenant_id: allowed,
        )
        before = app.before_request_funcs.get(None, [])
        idx = next(
            i for i, f in enumerate(before) if f.__name__ == "protect_csrf_and_install_identity"
        )
        original = before[idx]

        def install() -> None:
            g.active_tenant_id = tid

        before[idx] = install
        try:
            yield
        finally:
            before[idx] = original

    # Service will raise PreconditionRequired when If-Match missing — but first
    # need session wiring. Patch lifecycle handlers.
    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise PreconditionRequired("If-Match es obligatorio.")

    monkeypatch.setattr(surveillance_routes, "pause_action", boom)

    with _auth(frozenset({"signal.review", "dossier.read", "dossier.write"})):
        resp = client.post(
            f"/api/v1/dossiers/{dossier_id}/surveillance-actions/{action_id}/pause",
            headers={"Idempotency-Key": "pause-no-etag-xxxx"},
        )
    assert resp.status_code == 428
    body = resp.get_json()
    assert body is not None
    assert body.get("code") == "precondition_required" or "If-Match" in str(
        body.get("detail") or body
    )


@pytest.mark.unit
def test_http_confirm_happy_path(app: Any, client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager

    from flask import g

    from opn_oracle.auth import permissions
    from opn_oracle.oracle import surveillance_routes
    from opn_oracle.platform.models import User

    actor = User(
        id=uuid.uuid4(),
        email="writer@example.com",
        display_name="Writer",
        status="active",
    )
    tid = uuid.uuid4()
    dossier_id = uuid.uuid4()
    action_id = uuid.uuid4()

    fake_action = SimpleNamespace(
        id=action_id,
        tenant_id=tid,
        dossier_id=dossier_id,
        action_type="research_digest",
        title="Digest",
        status="active",
        alignment_state="aligned",
        cadence="weekly",
        timezone="Europe/Madrid",
        actor_id=None,
        offering_id=None,
        requirement_id=None,
        intent_revision_id=None,
        effective_scope_hash="e" * 64,
        origin="user",
        confirmed_by_user_id=actor.id,
        confirmed_at=datetime.now(UTC),
        manual_overrides={},
        last_run_at=None,
        next_run_at=datetime.now(UTC) + timedelta(days=7),
        last_attempt_at=None,
        last_error=None,
        retry_count=0,
        retry_after=None,
        row_version=1,
        watchlist_id=None,
        signal_monitor_id=None,
        procurement_watch_id=None,
        degraded=False,
        degraded_reason=None,
        notes="",
    )

    monkeypatch.setattr(
        surveillance_routes,
        "confirm_surveillance_action",
        lambda *a, **k: (fake_action, True),
    )

    @contextmanager
    def _auth(allowed: frozenset[str]) -> Iterator[None]:
        monkeypatch.setattr(permissions, "current_user", actor)
        monkeypatch.setattr(surveillance_routes, "current_user", actor)
        monkeypatch.setattr(
            permissions,
            "current_permissions",
            lambda user_id, active_tenant_id: allowed,
        )
        before = app.before_request_funcs.get(None, [])
        idx = next(
            i for i, f in enumerate(before) if f.__name__ == "protect_csrf_and_install_identity"
        )
        original = before[idx]

        def install() -> None:
            g.active_tenant_id = tid

        before[idx] = install
        try:
            yield
        finally:
            before[idx] = original

    with _auth(frozenset({"dossier.write", "dossier.read"})):
        resp = client.post(
            f"/api/v1/dossiers/{dossier_id}/surveillance-actions/confirm",
            json={"action_type": "research_digest", "cadence": "weekly"},
            headers={"Idempotency-Key": "confirm-research-01"},
        )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["action_type"] == "research_digest"
    assert data["duplicate"] is False
    assert resp.headers.get("ETag") == 'W/"1"'
