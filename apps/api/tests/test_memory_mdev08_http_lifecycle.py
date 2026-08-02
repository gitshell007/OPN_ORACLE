"""MDEV-08 HTTP gates (Flask unit): accept degraded, start blocked, ETag 428/409."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from flask import g

from opn_oracle.auth import permissions
from opn_oracle.oracle import conversation_routes
from opn_oracle.oracle.custom_report_lifecycle import PreconditionRequired
from opn_oracle.oracle.custom_reports import CustomReportConflict, CustomReportError
from opn_oracle.platform.models import User


@contextmanager
def _authenticated_http_probe(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
    allowed_permissions: frozenset[str],
    *,
    user: User | None = None,
    tenant_id: uuid.UUID | None = None,
) -> Iterator[tuple[User, uuid.UUID]]:
    actor = user or User(
        id=uuid.uuid4(),
        email="mdev08-http@example.com",
        display_name="MDEV08 HTTP",
        status="active",
    )
    tid = tenant_id or uuid.uuid4()
    monkeypatch.setattr(permissions, "current_user", actor)
    monkeypatch.setattr(conversation_routes, "current_user", actor)
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda user_id, active_tenant_id: allowed_permissions,
    )
    before_request_funcs = app.before_request_funcs.get(None, [])
    auth_index = next(
        index
        for index, function in enumerate(before_request_funcs)
        if function.__name__ == "protect_csrf_and_install_identity"
    )
    original = before_request_funcs[auth_index]

    def install_test_identity() -> None:
        g.active_tenant_id = tid

    before_request_funcs[auth_index] = install_test_identity
    try:
        yield actor, tid
    finally:
        before_request_funcs[auth_index] = original


def _report_body(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "dossier_id": str(uuid.uuid4()),
        "title": "Brief",
        "status": "draft",
        "report_type": "custom_assistant",
        "template_key": "custom_assistant_brief",
        "template_version": "v1",
        "generation_version": 1,
        "version": 3,
        "etag": 'W/"3"',
        "brief_request": "x",
        "plan_status": "accepted",
        "lifecycle_state": "accepted_degraded",
        "accepted_degraded": True,
        "generation_blocked": True,
        "generation_blocked_code": "memory_not_durable",
        "generation_blocked_reason": "memory_mode != durable",
        "memory_degraded": True,
        "background_job_id": None,
        "requested_by_user_id": str(uuid.uuid4()),
    }
    base.update(overrides)
    return base


def test_accept_plan_http_428_without_if_match(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    dossier_id = uuid.uuid4()
    report_id = uuid.uuid4()
    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise PreconditionRequired("If-Match es obligatorio.")

    monkeypatch.setattr(conversation_routes, "accept_plan", _boom)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"report.generate"})):
        response = client.post(
            f"/api/v1/dossiers/{dossier_id}/reports/custom/{report_id}/plan/accept",
            json={"start_generation": True},
        )
    assert response.status_code == 428
    body = response.get_json()
    assert body["code"] == "precondition_required"


def test_accept_plan_http_409_version_conflict(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    dossier_id = uuid.uuid4()
    report_id = uuid.uuid4()
    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise CustomReportConflict("Conflicto de versión")

    monkeypatch.setattr(conversation_routes, "accept_plan", _boom)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"report.generate"})):
        response = client.post(
            f"/api/v1/dossiers/{dossier_id}/reports/custom/{report_id}/plan/accept",
            json={"start_generation": True},
            headers={"If-Match": 'W/"1"'},
        )
    assert response.status_code == 409
    assert response.get_json()["code"] == "conflict"


def test_accept_plan_http_degraded_no_job(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Accept with auto_start returns accepted_degraded and does not publish a job."""

    dossier_id = uuid.uuid4()
    report_id = uuid.uuid4()
    body = _report_body(id=str(report_id), dossier_id=str(dossier_id), version=4)
    report = SimpleNamespace(
        id=report_id,
        background_job_id=None,
        options={
            "lifecycle_state": "accepted_degraded",
            "generation_blocked": True,
            "generation_blocked_code": "memory_not_durable",
        },
        version=4,
    )
    published: list[Any] = []
    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )
    monkeypatch.setattr(conversation_routes, "accept_plan", lambda *a, **k: report)
    monkeypatch.setattr(conversation_routes, "serialize_custom_brief", lambda r: body)
    monkeypatch.setattr(conversation_routes.db.session, "commit", lambda: None)
    monkeypatch.setattr(
        "opn_oracle.jobs.service.publish_job",
        lambda job: published.append(job),
    )
    with _authenticated_http_probe(app, monkeypatch, frozenset({"report.generate"})):
        response = client.post(
            f"/api/v1/dossiers/{dossier_id}/reports/custom/{report_id}/plan/accept",
            json={"start_generation": True},
            headers={"If-Match": 'W/"3"'},
        )
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    data = response.get_json()
    assert data["lifecycle_state"] == "accepted_degraded"
    assert data["generation_blocked"] is True
    assert data["generation_blocked_code"] == "memory_not_durable"
    assert published == []


def test_start_via_retry_blocked_http(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    dossier_id = uuid.uuid4()
    report_id = uuid.uuid4()
    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )

    def _blocked(*args: Any, **kwargs: Any) -> Any:
        raise CustomReportError(
            "memory_mode != durable",
            errors={"generation": ["memory_not_durable"], "code": ["memory_not_durable"]},
        )

    monkeypatch.setattr(conversation_routes, "retry_report", _blocked)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"report.generate"})):
        response = client.post(
            f"/api/v1/dossiers/{dossier_id}/reports/custom/{report_id}/retry",
            headers={"If-Match": 'W/"5"'},
        )
    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_error"


def test_download_not_ready_409(app: Any, client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    dossier_id = uuid.uuid4()
    report_id = uuid.uuid4()
    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )
    monkeypatch.setattr(
        conversation_routes,
        "get_custom_brief",
        lambda *a, **k: SimpleNamespace(id=report_id, options={}),
    )
    monkeypatch.setattr(conversation_routes, "get_downloadable_artifact", lambda r: None)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"report.read"})):
        response = client.get(f"/api/v1/dossiers/{dossier_id}/reports/custom/{report_id}/download")
    assert response.status_code == 409
    assert response.get_json()["code"] == "artifact_not_ready"


def test_permission_denied_without_report_generate(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    dossier_id = uuid.uuid4()
    report_id = uuid.uuid4()
    monkeypatch.setattr(
        conversation_routes,
        "_dossier_or_404",
        lambda *a, **k: SimpleNamespace(id=dossier_id),
    )
    with _authenticated_http_probe(app, monkeypatch, frozenset({"report.read"})):
        response = client.post(
            f"/api/v1/dossiers/{dossier_id}/reports/custom/{report_id}/plan/accept",
            json={},
            headers={"If-Match": 'W/"1"'},
        )
    assert response.status_code in {403, 401}
