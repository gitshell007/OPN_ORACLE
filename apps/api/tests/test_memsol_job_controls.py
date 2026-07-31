"""MEMSOL job cancel/retry: unit lifecycle + real Flask HTTP route dispatch."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import g
from flask_login import login_user

from opn_oracle.auth import permissions
from opn_oracle.jobs import routes as jobs_routes
from opn_oracle.jobs.service import prepare_retry, request_cancel, serialize_job
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.platform.models import User


def _job(**kwargs: object) -> BackgroundJob:
    now = datetime.now(UTC)
    base: dict[str, Any] = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        job_type="oracle.dossier_question.answer",
        queue="ai",
        status="queued",
        stage="queued",
        progress=0,
        idempotency_key=f"memsol-{uuid.uuid4().hex[:12]}",
        payload_hash=b"\x00" * 32,
        input_payload={"message_id": str(uuid.uuid4())},
        version=1,
        retryable=True,
        cancel_requested=False,
        attempts=0,
        max_attempts=3,
        created_at=now,
        updated_at=now,
    )
    base.update(kwargs)
    return BackgroundJob(**base)


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


@contextmanager
def _http_auth(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    permission_keys: frozenset[str],
) -> Iterator[User]:
    """Install identity for real route dispatch (same pattern as entity-intel tests)."""

    user = User(
        id=uuid.uuid4(),
        email="memsol-jobs@example.test",
        display_name="MEMSOL Jobs",
        status="active",
    )
    tenant_id = uuid.uuid4()
    monkeypatch.setattr(permissions, "current_user", user)
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda user_id, active_tenant_id: permission_keys,
    )
    # flask_login current_user used by require_permission
    monkeypatch.setattr(permissions, "current_user", user)
    from opn_oracle.jobs import routes as jr
    from opn_oracle.auth import permissions as perm_mod

    # require_permission imports current_user from flask_login at call time
    import opn_oracle.auth.permissions as perm_pkg
    from flask_login import login_user as fl_login

    before = app.before_request_funcs.get(None, [])
    idx = next(
        i for i, fn in enumerate(before) if fn.__name__ == "protect_csrf_and_install_identity"
    )
    original = before[idx]

    def install_identity() -> None:
        g.active_tenant_id = tenant_id
        # mark authenticated for flask_login checks
        g._login_user = user  # type: ignore[attr-defined]

    before[idx] = install_identity
    try:
        yield user
    finally:
        before[idx] = original


def _patch_login(monkeypatch: pytest.MonkeyPatch, user: User) -> None:
    """Make flask_login current_user appear authenticated in require_permission."""

    class _Proxy:
        is_authenticated = True
        id = user.id

        def __getattr__(self, name: str) -> Any:
            return getattr(user, name)

    monkeypatch.setattr("flask_login.utils._get_user", lambda: _Proxy())
    monkeypatch.setattr(permissions, "current_user", _Proxy())


@pytest.mark.unit
def test_http_cancel_requires_if_match_428(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job(job_type="oracle.dossier_question.answer", status="queued", version=1)
    monkeypatch.setattr(jobs_routes, "_job_or_404", lambda job_id, write=False: job)
    monkeypatch.setattr(jobs_routes, "append_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(jobs_routes.db.session, "commit", lambda: None)

    user = User(
        id=uuid.uuid4(), email="m@example.test", display_name="M", status="active"
    )
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda *a, **k: frozenset({"dossier.read", "ai.execute"}),
    )
    _patch_login(monkeypatch, user)
    before = app.before_request_funcs.get(None, [])
    idx = next(
        i for i, fn in enumerate(before) if fn.__name__ == "protect_csrf_and_install_identity"
    )
    original = before[idx]
    before[idx] = lambda: setattr(g, "active_tenant_id", job.tenant_id)
    try:
        response = client.post(f"/api/v1/jobs/{job.id}/cancel")
    finally:
        before[idx] = original
    assert response.status_code == 428
    assert response.get_json()["code"] == "precondition_required"


@pytest.mark.unit
def test_http_cancel_wrong_version_409(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job(job_type="oracle.dossier_question.answer", status="queued", version=2)
    monkeypatch.setattr(jobs_routes, "_job_or_404", lambda job_id, write=False: job)
    monkeypatch.setattr(jobs_routes, "append_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(jobs_routes.db.session, "commit", lambda: None)
    user = User(id=uuid.uuid4(), email="m@example.test", display_name="M", status="active")
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda *a, **k: frozenset({"dossier.read", "ai.execute"}),
    )
    _patch_login(monkeypatch, user)
    before = app.before_request_funcs.get(None, [])
    idx = next(
        i for i, fn in enumerate(before) if fn.__name__ == "protect_csrf_and_install_identity"
    )
    original = before[idx]
    before[idx] = lambda: setattr(g, "active_tenant_id", job.tenant_id)
    try:
        response = client.post(
            f"/api/v1/jobs/{job.id}/cancel",
            headers={"If-Match": 'W/"9"'},
        )
    finally:
        before[idx] = original
    assert response.status_code == 409
    assert response.get_json()["code"] == "job_not_cancellable"


@pytest.mark.unit
def test_http_cancel_queued_memsol_202(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job(job_type="oracle.dossier_question.answer", status="queued", version=1)
    monkeypatch.setattr(jobs_routes, "_job_or_404", lambda job_id, write=False: job)
    monkeypatch.setattr(jobs_routes, "append_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(jobs_routes.db.session, "commit", lambda: None)
    user = User(id=uuid.uuid4(), email="m@example.test", display_name="M", status="active")
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda *a, **k: frozenset({"dossier.read", "ai.execute"}),
    )
    _patch_login(monkeypatch, user)
    before = app.before_request_funcs.get(None, [])
    idx = next(
        i for i, fn in enumerate(before) if fn.__name__ == "protect_csrf_and_install_identity"
    )
    original = before[idx]
    before[idx] = lambda: setattr(g, "active_tenant_id", job.tenant_id)
    try:
        response = client.post(
            f"/api/v1/jobs/{job.id}/cancel",
            headers={"If-Match": 'W/"1"'},
        )
    finally:
        before[idx] = original
    assert response.status_code == 202
    body = response.get_json()
    assert body["status"] == "cancelled"
    assert body["cancel_requested"] is True
    assert body["version"] == 2
    assert job.status == "cancelled"


@pytest.mark.unit
def test_http_retry_failed_memsol_brief_202(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job(
        job_type="oracle.report.custom_brief.plan",
        status="failed",
        retryable=True,
        version=1,
        stage="failed",
    )
    monkeypatch.setattr(jobs_routes, "_job_or_404", lambda job_id, write=False: job)
    monkeypatch.setattr(jobs_routes, "append_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(jobs_routes.db.session, "commit", lambda: None)
    monkeypatch.setattr(jobs_routes, "publish_job", lambda j: True)
    user = User(id=uuid.uuid4(), email="m@example.test", display_name="M", status="active")
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda *a, **k: frozenset({"dossier.read", "report.generate"}),
    )
    _patch_login(monkeypatch, user)
    before = app.before_request_funcs.get(None, [])
    idx = next(
        i for i, fn in enumerate(before) if fn.__name__ == "protect_csrf_and_install_identity"
    )
    original = before[idx]
    before[idx] = lambda: setattr(g, "active_tenant_id", job.tenant_id)
    try:
        response = client.post(
            f"/api/v1/jobs/{job.id}/retry",
            headers={"If-Match": 'W/"1"'},
        )
    finally:
        before[idx] = original
    assert response.status_code == 202
    body = response.get_json()
    assert body["status"] == "queued"
    assert body["stage"] == "manual_retry"
    assert job.status == "queued"


@pytest.mark.unit
def test_http_cancel_missing_job_404(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """write=True + missing control permission / missing job → 404 (no leak)."""

    monkeypatch.setattr(jobs_routes, "_job_or_404", lambda job_id, write=False: None)
    user = User(id=uuid.uuid4(), email="m@example.test", display_name="M", status="active")
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda *a, **k: frozenset({"dossier.read"}),  # no ai.execute
    )
    _patch_login(monkeypatch, user)
    before = app.before_request_funcs.get(None, [])
    idx = next(
        i for i, fn in enumerate(before) if fn.__name__ == "protect_csrf_and_install_identity"
    )
    original = before[idx]
    before[idx] = lambda: setattr(g, "active_tenant_id", uuid.uuid4())
    try:
        response = client.post(
            f"/api/v1/jobs/{uuid.uuid4()}/cancel",
            headers={"If-Match": 'W/"1"'},
        )
    finally:
        before[idx] = original
    assert response.status_code == 404
    assert response.get_json()["code"] == "not_found"


@pytest.mark.unit
def test_http_cancel_permission_denied_403(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """require_permission(dossier.read) fails when permissions empty → 403."""

    user = User(id=uuid.uuid4(), email="m@example.test", display_name="M", status="active")
    monkeypatch.setattr(permissions, "current_permissions", lambda *a, **k: frozenset())
    _patch_login(monkeypatch, user)
    before = app.before_request_funcs.get(None, [])
    idx = next(
        i for i, fn in enumerate(before) if fn.__name__ == "protect_csrf_and_install_identity"
    )
    original = before[idx]
    before[idx] = lambda: setattr(g, "active_tenant_id", uuid.uuid4())
    try:
        response = client.post(
            f"/api/v1/jobs/{uuid.uuid4()}/cancel",
            headers={"If-Match": 'W/"1"'},
        )
    finally:
        before[idx] = original
    assert response.status_code == 403
    assert response.get_json()["code"] == "permission_denied"
