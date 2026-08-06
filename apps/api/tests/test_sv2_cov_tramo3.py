"""SV2-COV-TRAMO3 · product coverage for the three remaining high-miss modules.

Risk-first behavioral tests (not line-painting) for:

- ``oracle/routes.py`` — mutation handlers (create / patch / archive / bulk-delete /
  signal review+promote / actors create+merge / collaborators)
- ``oracle/custom_report_lifecycle.py`` — transitions accept→write→review→ready
  failures + retry/cancel/fence drops
- ``jobs/tasks.py`` — durable delivery fencing, retry exhaustion, permanent failure,
  root-cause messages for AI jobs

Unit / Flask unit — no PG. Style aligned with ``test_sv2_cov_tramo2.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import g

from opn_oracle.auth import permissions
from opn_oracle.jobs import tasks
from opn_oracle.jobs.tasks import (
    PermanentJobError,
    RetriableJobError,
    _exception_cause_text,
    _execute_claimed_delivery,
    _permanent_failure_message,
    _retry_exhausted_message,
    retry_delay,
)
from opn_oracle.oracle import custom_report_lifecycle as lifecycle
from opn_oracle.oracle import routes as oracle_routes
from opn_oracle.oracle.custom_report_lifecycle import (
    IllegalTransition,
    PreconditionRequired,
    cancel_report,
    process_custom_brief_review,
    process_custom_brief_write,
    retry_report,
    start_generation,
)
from opn_oracle.oracle.custom_reports import CustomReportError
from opn_oracle.oracle.service import DomainValidationError, ResourceNotFound, VersionConflict
from opn_oracle.platform.models import User
from opn_oracle.tenants.context import TenantContext, tenant_context

# ---------------------------------------------------------------------------
# Shared HTTP probe
# ---------------------------------------------------------------------------


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
        email="sv2-cov-tramo3@example.com",
        display_name="SV2 COV TRAMO3",
        status="active",
    )
    tid = tenant_id or uuid.uuid4()
    monkeypatch.setattr(permissions, "current_user", actor)
    monkeypatch.setattr(oracle_routes, "current_user", actor)
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


def _dossier_ns(**overrides: Any) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "title": "Expediente demo",
        "status": "active",
        "version": 3,
        "profile_type": "market",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _serialize_stub(row: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in ("id", "tenant_id", "title", "status", "version", "canonical_name", "actor_type"):
        if hasattr(row, key):
            value = getattr(row, key)
            payload[key] = str(value) if isinstance(value, uuid.UUID) else value
    return payload


# ===========================================================================
# routes.py — mutation handlers (risk first)
# ===========================================================================


def test_dossiers_create_http_201_and_validation(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: create sin ETag/201 o DomainValidationError → 500."""

    dossier = _dossier_ns(version=1)
    monkeypatch.setattr(oracle_routes, "create_dossier", lambda *a, **k: dossier)
    monkeypatch.setattr(oracle_routes, "_serialize", _serialize_stub)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.write"})):
        ok = client.post("/api/v1/dossiers", json={"title": "Nuevo expediente"})
    assert ok.status_code == 201, ok.get_data(as_text=True)[:400]
    assert ok.headers.get("ETag") == 'W/"1"'
    assert ok.get_json()["title"] == "Expediente demo"

    def _boom(*a: Any, **k: Any) -> Any:
        raise DomainValidationError("title es obligatorio.")

    monkeypatch.setattr(oracle_routes, "create_dossier", _boom)
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.write"})):
        bad = client.post("/api/v1/dossiers", json={})
    assert bad.status_code == 422
    assert bad.get_json()["code"] == "domain_validation"


def test_dossier_patch_maps_version_conflict_to_409(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: CAS roto → 500 en vez de 409 version_conflict."""

    dossier_id = uuid.uuid4()

    def _conflict(*a: Any, **k: Any) -> Any:
        raise VersionConflict("La versión del expediente ya no es la esperada.")

    monkeypatch.setattr(oracle_routes, "update_dossier", _conflict)
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.write"})):
        response = client.patch(
            f"/api/v1/dossiers/{dossier_id}",
            json={"title": "Renombrado", "version": 2},
            headers={"If-Match": 'W/"2"'},
        )
    assert response.status_code == 409
    assert response.get_json()["code"] == "version_conflict"


def test_dossier_archive_and_bulk_delete_validation(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: archive sin CAS o bulk-delete con lista basura/duplicados → 500."""

    dossier = _dossier_ns(status="archived", version=4)
    monkeypatch.setattr(oracle_routes, "archive_dossier", lambda *a, **k: dossier)
    monkeypatch.setattr(oracle_routes, "_serialize", _serialize_stub)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.archive"})):
        archived = client.post(
            f"/api/v1/dossiers/{dossier.id}/archive",
            json={"version": 3},
            headers={"If-Match": 'W/"3"'},
        )
    assert archived.status_code == 200
    assert archived.get_json()["status"] == "archived"
    assert archived.headers.get("ETag") == 'W/"4"'

    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.delete"})):
        not_list = client.post("/api/v1/dossiers/bulk-delete", json={"dossier_ids": "x"})
        dup_id = str(uuid.uuid4())
        dups = client.post(
            "/api/v1/dossiers/bulk-delete",
            json={"dossier_ids": [dup_id, dup_id]},
        )
    assert not_list.status_code == 422
    assert "lista" in not_list.get_json()["detail"].lower()
    assert dups.status_code == 422
    assert "repetidos" in dups.get_json()["detail"].lower()

    deleted = [uuid.uuid4(), uuid.uuid4()]
    monkeypatch.setattr(oracle_routes, "delete_dossiers", lambda *a, **k: deleted)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.delete"})):
        ok = client.post(
            "/api/v1/dossiers/bulk-delete",
            json={"dossier_ids": [str(x) for x in deleted]},
        )
    assert ok.status_code == 200
    body = ok.get_json()
    assert body["deleted_count"] == 2
    assert set(body["deleted_ids"]) == {str(x) for x in deleted}


def test_signal_review_and_promote_contracts(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: review NotFound→500; promote sin Idempotency-Key aceptado."""

    link_id = uuid.uuid4()
    link = SimpleNamespace(id=link_id, status="reviewed", version=2, overall_score=80)
    monkeypatch.setattr(oracle_routes, "review_signal_link", lambda *a, **k: link)
    monkeypatch.setattr(oracle_routes, "_serialize", _serialize_stub)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"signal.review"})):
        ok = client.post(
            f"/api/v1/signals/{link_id}/review",
            json={"status": "relevant", "version": 1},
        )
    assert ok.status_code == 200
    assert ok.get_json()["status"] == "reviewed"

    def _missing(*a: Any, **k: Any) -> Any:
        raise ResourceNotFound("Enlace de señal no encontrado.")

    monkeypatch.setattr(oracle_routes, "review_signal_link", _missing)
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"signal.review"})):
        missing = client.post(
            f"/api/v1/signals/{link_id}/review",
            json={"status": "relevant", "version": 1},
        )
    assert missing.status_code == 404
    assert missing.get_json()["code"] == "not_found"

    with _authenticated_http_probe(app, monkeypatch, frozenset({"signal.promote"})):
        no_key = client.post(
            f"/api/v1/signals/{link_id}/promote",
            json={"kind": "opportunity"},
        )
    assert no_key.status_code == 422
    assert no_key.get_json()["code"] == "idempotency_key_required"

    opportunity = SimpleNamespace(
        id=uuid.uuid4(),
        title="Oportunidad",
        status="open",
        version=1,
    )
    monkeypatch.setattr(oracle_routes, "promote_signal_link", lambda *a, **k: opportunity)
    monkeypatch.setattr(oracle_routes, "Opportunity", type(opportunity))
    # isinstance check uses Opportunity from routes; force kind via non-Opportunity type
    # by returning a plain SimpleNamespace → kind == "risk" path; still valid 200.
    with _authenticated_http_probe(app, monkeypatch, frozenset({"signal.promote"})):
        promoted = client.post(
            f"/api/v1/signals/{link_id}/promote",
            json={"kind": "risk"},
            headers={"Idempotency-Key": "promo-1"},
        )
    assert promoted.status_code == 200, promoted.get_data(as_text=True)[:400]
    data = promoted.get_json()
    assert data["kind"] in {"opportunity", "risk"}
    assert "resource" in data


def test_actors_create_merge_and_collaborators_guard(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: merge sin source_actor_id → 500; collaborator en archived sin 422."""

    # create validation
    with _authenticated_http_probe(app, monkeypatch, frozenset({"actor.write"})):
        bad = client.post("/api/v1/actors", json={"canonical_name": "", "actor_type": "x"})
    assert bad.status_code == 422

    # create new actor
    commits: list[str] = []
    monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: None)
    monkeypatch.setattr(oracle_routes.db.session, "add", lambda *a, **k: None)
    monkeypatch.setattr(oracle_routes.db.session, "commit", lambda: commits.append("c"))
    monkeypatch.setattr(oracle_routes, "_serialize", _serialize_stub)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"actor.write"})):
        created = client.post(
            "/api/v1/actors",
            json={"canonical_name": "Iberdrola SA", "actor_type": "organization"},
        )
    assert created.status_code == 201, created.get_data(as_text=True)[:400]
    assert commits == ["c"]

    # merge missing source → 422 (KeyError mapped via _domain_error)
    target_id = uuid.uuid4()
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"actor.write"})):
        merge_bad = client.post(
            f"/api/v1/actors/{target_id}/merge",
            json={"reason": "duplicado"},
        )
    assert merge_bad.status_code == 422

    merged = SimpleNamespace(
        id=target_id,
        canonical_name="Iberdrola",
        actor_type="organization",
        version=2,
    )
    monkeypatch.setattr(oracle_routes, "merge_actors", lambda *a, **k: merged)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"actor.write"})):
        merge_ok = client.post(
            f"/api/v1/actors/{target_id}/merge",
            json={
                "source_actor_id": str(uuid.uuid4()),
                "reason": "duplicado",
                "confirm": True,
                "expected_target_version": 1,
                "expected_source_version": 1,
            },
        )
    assert merge_ok.status_code == 200
    assert merge_ok.get_json()["canonical_name"] == "Iberdrola"

    # collaborators: missing manage rights → 404; archived → 422
    dossier_id = uuid.uuid4()
    user_id = uuid.uuid4()
    monkeypatch.setattr(oracle_routes, "_dossier_manage_or_404", lambda *a, **k: None)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.write"})):
        missing = client.put(
            f"/api/v1/dossiers/{dossier_id}/collaborators/{user_id}",
            json={"role": "editor"},
        )
    assert missing.status_code == 404

    archived = _dossier_ns(id=dossier_id, status="archived")
    monkeypatch.setattr(oracle_routes, "_dossier_manage_or_404", lambda *a, **k: archived)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.write"})):
        blocked = client.put(
            f"/api/v1/dossiers/{dossier_id}/collaborators/{user_id}",
            json={"role": "editor"},
        )
        blocked_del = client.delete(
            f"/api/v1/dossiers/{dossier_id}/collaborators/{user_id}",
        )
    assert blocked.status_code == 422
    assert blocked_del.status_code == 422


def test_competitive_intelligence_readiness_checks(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: readiness que miente 'ready' sin AI o Signal."""

    policy = SimpleNamespace(enabled=True, kill_switch=False)
    connection = SimpleNamespace(status="active")
    calls = {"n": 0}

    def _scalar(*_a: Any, **_k: Any) -> Any:
        calls["n"] += 1
        return policy if calls["n"] == 1 else connection

    monkeypatch.setattr(oracle_routes.db.session, "scalar", _scalar)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.write"})):
        ready = client.get("/api/v1/dossiers/competitive-intelligence/readiness")
    assert ready.status_code == 200
    body = ready.get_json()
    assert body["ready"] is True
    assert {c["key"] for c in body["checks"]} == {"ai", "signal"}

    calls["n"] = 0
    policy.enabled = False
    connection = None  # type: ignore[assignment]

    def _scalar_off(*_a: Any, **_k: Any) -> Any:
        calls["n"] += 1
        return policy if calls["n"] == 1 else None

    monkeypatch.setattr(oracle_routes.db.session, "scalar", _scalar_off)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.write"})):
        not_ready = client.get("/api/v1/dossiers/competitive-intelligence/readiness")
    assert not_ready.get_json()["ready"] is False


def test_expected_version_rejects_garbage_if_match(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: If-Match basura aceptado o 500 en patch."""

    dossier_id = uuid.uuid4()
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.write"})):
        response = client.patch(
            f"/api/v1/dossiers/{dossier_id}",
            json={"title": "x"},
            headers={"If-Match": "not-a-version"},
        )
    assert response.status_code == 422
    assert (
        "If-Match" in response.get_json()["detail"]
        or "version" in response.get_json()["detail"].lower()
    )


# ===========================================================================
# custom_report_lifecycle — transitions + fence/retry failures
# ===========================================================================


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
        "source_snapshot_hash": b"\x00" * 32,
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


def _durable_snap(**overrides: Any) -> dict[str, Any]:
    base = {
        "allowlist": ["ev-1"],
        "evidence_items": [
            {"evidence_id": "ev-1", "exact_excerpt": "Capgemini gana X", "source_ref": "s1"}
        ],
        "memory_mode": "durable",
        "memory_policy": {
            "materialized": True,
            "in_process_forbidden": True,
            "empty_allowlist_ok": False,
        },
        "watermark": "wm-tramo3",
        "accepted_plan": {"sections": [{"id": "a", "title": "Resumen"}]},
        "coverage": {"evidence_count": 1, "durable": True},
        "runtime_sha256": {
            "plan": "p" * 64,
            "writer": "w" * 64,
            "review": "r" * 64,
        },
        "brief_request": "Analiza X",
    }
    base.update(overrides)
    return base


def test_retry_report_from_failed_with_snapshot_restarts_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug que cazaría: retry desde failed que no reusa snapshot o no encola writer."""

    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    snap = _durable_snap()
    report = _report(
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        status="failed",
        version=5,
        options={
            "lifecycle_state": "failed",
            "plan_status": "accepted",
            "accepted_snapshot": snap,
            "accepted_snapshot_hash": "a" * 64,
            "accepted_plan": snap["accepted_plan"],
            "fence_token": "fence-old",
        },
    )
    session = MagicMock()
    started: list[dict[str, Any]] = []

    monkeypatch.setattr(lifecycle, "get_custom_brief", lambda *a, **k: report)
    monkeypatch.setattr(
        lifecycle,
        "_productive_generation_allowed",
        lambda snap: (True, None, None),
    )
    monkeypatch.setattr(
        lifecycle,
        "stage_job",
        lambda *a, **k: SimpleNamespace(
            id=uuid.uuid4(),
            input_payload={"generation_fence": "fence-new"},
        ),
    )
    monkeypatch.setattr(lifecycle, "append_audit_event", lambda *a, **k: None)

    original_start = start_generation

    def _track_start(*a: Any, **k: Any) -> Any:
        started.append(dict(k))
        return original_start(*a, **k)

    monkeypatch.setattr(lifecycle, "start_generation", _track_start)
    # re-import path uses local name — patch module attribute used by retry_report
    monkeypatch.setattr(
        "opn_oracle.oracle.custom_report_lifecycle.start_generation",
        _track_start,
    )

    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=actor_id)):
        result = retry_report(
            session,
            dossier_id=dossier_id,
            report_id=report.id,
            actor_id=actor_id,
            expected_version=5,
        )
    assert started, "retry con snapshot debe invocar start_generation"
    assert result.status == "generating"
    assert result.options["lifecycle_state"] == "generating"
    assert result.background_job_id is not None


def test_retry_report_without_snapshot_returns_to_brief_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug que cazaría: retry sin snapshot que reencola writer o se queda en failed."""

    tenant_id = uuid.uuid4()
    report = _report(
        tenant_id=tenant_id,
        status="failed",
        version=2,
        options={"lifecycle_state": "failed", "plan_status": "draft"},
    )
    session = MagicMock()
    monkeypatch.setattr(lifecycle, "get_custom_brief", lambda *a, **k: report)
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        result = retry_report(
            session,
            dossier_id=report.dossier_id,
            report_id=report.id,
            actor_id=uuid.uuid4(),
            expected_version=2,
        )
    assert result.options["lifecycle_state"] == "brief_draft"
    assert result.status == "draft"
    assert result.error_code is None


def test_retry_report_rejects_non_failed_and_missing_if_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug que cazaría: retry en plan_accepted o sin If-Match aceptado."""

    tenant_id = uuid.uuid4()
    report = _report(
        tenant_id=tenant_id,
        options={"lifecycle_state": "plan_accepted", "plan_status": "accepted"},
    )
    session = MagicMock()
    monkeypatch.setattr(lifecycle, "get_custom_brief", lambda *a, **k: report)
    with (
        tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())),
        pytest.raises(IllegalTransition),
    ):
        retry_report(
            session,
            dossier_id=report.dossier_id,
            report_id=report.id,
            actor_id=uuid.uuid4(),
            expected_version=1,
        )
    with (
        tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())),
        pytest.raises(PreconditionRequired),
    ):
        retry_report(
            session,
            dossier_id=report.dossier_id,
            report_id=report.id,
            actor_id=uuid.uuid4(),
            expected_version=None,
        )


def test_cancel_report_flags_background_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug que cazaría: cancel que no marca cancel_requested en el job en vuelo."""

    tenant_id = uuid.uuid4()
    job = SimpleNamespace(id=uuid.uuid4(), cancel_requested=False)
    report = _report(
        tenant_id=tenant_id,
        status="generating",
        version=4,
        background_job_id=job.id,
        options={"lifecycle_state": "generating", "plan_status": "accepted"},
    )
    session = MagicMock()
    session.get.return_value = job
    monkeypatch.setattr(lifecycle, "get_custom_brief", lambda *a, **k: report)
    monkeypatch.setattr(lifecycle, "append_audit_event", lambda *a, **k: None)
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        result = cancel_report(
            session,
            dossier_id=report.dossier_id,
            report_id=report.id,
            actor_id=uuid.uuid4(),
            expected_version=4,
        )
    assert result.options["lifecycle_state"] == "cancelled"
    assert result.error_code == "cancelled"
    assert job.cancel_requested is True


def test_start_generation_idempotent_when_already_generating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug que cazaría: re-start que duplica writer jobs en estado generating."""

    tenant_id = uuid.uuid4()
    report = _report(
        tenant_id=tenant_id,
        status="generating",
        options={
            "lifecycle_state": "generating",
            "plan_status": "accepted",
            "accepted_snapshot": _durable_snap(),
            "accepted_snapshot_hash": "b" * 64,
        },
    )
    session = MagicMock()
    staged: list[Any] = []
    monkeypatch.setattr(lifecycle, "get_custom_brief", lambda *a, **k: report)
    monkeypatch.setattr(lifecycle, "stage_job", lambda *a, **k: staged.append(1) or MagicMock())
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        result = start_generation(
            session,
            dossier_id=report.dossier_id,
            report_id=report.id,
            actor_id=uuid.uuid4(),
            expected_version=1,
        )
    assert result is report
    assert staged == []


def test_writer_drops_cancelled_and_fails_when_gate_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug que cazaría: writer que escribe tras cancel o con memoria no durable."""

    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    snap = _durable_snap(memory_mode="disabled")
    report = _report(
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        status="generating",
        version=2,
        options={
            "lifecycle_state": "generating",
            "accepted_snapshot": snap,
            "accepted_snapshot_hash": "c" * 64,
            "fence_token": "fence-1",
            "accepted_plan": snap["accepted_plan"],
        },
    )
    session = MagicMock()
    session.scalar.return_value = report
    job = SimpleNamespace(
        id=uuid.uuid4(),
        cancel_requested=True,
        correlation_id=None,
        requested_by_user_id=uuid.uuid4(),
        request_id=None,
    )
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        dropped = process_custom_brief_write(
            session,
            {
                "report_id": str(report.id),
                "dossier_id": str(dossier_id),
                "snapshot_hash": "c" * 64,
                "generation_fence": "fence-1",
            },
            job,  # type: ignore[arg-type]
        )
    assert dropped["dropped"] is True
    assert dropped["reason"] == "cancelled"

    job.cancel_requested = False
    monkeypatch.setattr(
        lifecycle,
        "_productive_generation_allowed",
        lambda snap: (False, "memory_not_durable", "no durable"),
    )
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        failed = process_custom_brief_write(
            session,
            {
                "report_id": str(report.id),
                "dossier_id": str(dossier_id),
                "snapshot_hash": "c" * 64,
                "generation_fence": "fence-1",
            },
            job,  # type: ignore[arg-type]
        )
    assert failed.get("failed") is True
    assert failed.get("reason") == "memory_not_durable"
    assert report.status == "failed"
    assert report.options["lifecycle_state"] == "failed"


def test_review_fails_without_writer_output_and_on_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug que cazaría: review sin writer_output → ready, o rejected → ready."""

    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    snap = _durable_snap()
    report = _report(
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        status="generating",
        version=3,
        options={
            "lifecycle_state": "reviewing",
            "accepted_snapshot": snap,
            "accepted_snapshot_hash": "d" * 64,
            "fence_token": "fence-r",
            # no writer_output
        },
    )
    session = MagicMock()
    session.scalar.return_value = report
    job = SimpleNamespace(
        id=uuid.uuid4(),
        cancel_requested=False,
        correlation_id=None,
        requested_by_user_id=None,
        request_id=None,
    )
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        missing = process_custom_brief_review(
            session,
            {
                "report_id": str(report.id),
                "dossier_id": str(dossier_id),
                "snapshot_hash": "d" * 64,
                "generation_fence": "fence-r",
            },
            job,  # type: ignore[arg-type]
        )
    assert missing["failed"] is True
    assert missing["reason"] == "writer_output_missing"
    assert report.status == "failed"

    report.status = "generating"
    report.version = 4
    report.options = {
        "lifecycle_state": "reviewing",
        "accepted_snapshot": snap,
        "accepted_snapshot_hash": "d" * 64,
        "fence_token": "fence-r",
        "writer_output": {
            "sections": [{"id": "a", "title": "Resumen", "body": "x", "citations": []}],
            "citations": [],
        },
        "accepted_plan": snap["accepted_plan"],
        "ai_usage_bindings": [],
    }
    monkeypatch.setattr(lifecycle, "_testing_mode", lambda: False)
    monkeypatch.setattr(
        lifecycle,
        "_invoke_rt10_review_via_signal",
        lambda **k: {
            "validated_output": {
                "approved": False,
                "citations_ok": False,
                "issues": ["hallucinated entity"],
            },
            "validated_output_sha256": "sha",
            "provider": "signal",
            "model": "m",
            "run_id": "run-1",
            "usage": {},
            "attempts": 1,
        },
    )
    monkeypatch.setattr(
        lifecycle,
        "_bind_ai_usage_once",
        lambda *a, **k: {
            "id": str(uuid.uuid4()),
            "phase": "review",
            "run_id": "run-1",
            "task_key": "report_custom_review",
            "runtime_id": "RT-10",
        },
    )
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        rejected = process_custom_brief_review(
            session,
            {
                "report_id": str(report.id),
                "dossier_id": str(dossier_id),
                "snapshot_hash": "d" * 64,
                "generation_fence": "fence-r",
            },
            job,  # type: ignore[arg-type]
        )
    assert rejected["failed"] is True
    assert rejected["reason"] == "review_rejected"
    assert report.error_code == "review_rejected"
    assert report.options["lifecycle_state"] == "failed"


def test_review_fence_token_mismatch_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: review tardío con fence viejo que pisa un ready/nuevo generation."""

    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    report = _report(
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        options={
            "lifecycle_state": "reviewing",
            "accepted_snapshot": _durable_snap(),
            "accepted_snapshot_hash": "e" * 64,
            "fence_token": "fence-current",
            "writer_output": {"sections": [{"id": "a", "title": "A"}]},
        },
    )
    session = MagicMock()
    session.scalar.return_value = report
    job = SimpleNamespace(id=uuid.uuid4(), cancel_requested=False)
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        dropped = process_custom_brief_review(
            session,
            {
                "report_id": str(report.id),
                "dossier_id": str(dossier_id),
                "snapshot_hash": "e" * 64,
                "generation_fence": "fence-stale",
            },
            job,  # type: ignore[arg-type]
        )
    assert dropped["dropped"] is True
    assert dropped["reason"] == "fence_token_mismatch"


# ===========================================================================
# jobs/tasks.py — retry / fencing / root-cause messages
# ===========================================================================


def test_retry_delay_bounds_and_jitter() -> None:
    """Bug que cazaría: backoff sin techo o jitter negativo."""

    assert retry_delay(1, jitter=0.0) == 2.0
    assert retry_delay(0, jitter=0.0) == 2.0
    assert retry_delay(10, jitter=3.0) == 300.0
    assert 2.0 <= retry_delay(1, jitter=1.5) <= 5.0


def test_exception_cause_text_walks_chain() -> None:
    """Bug que cazaría: error_message que solo guarda el wrapper Celery genérico."""

    root = ValueError("allowlist violation on ev-9")
    mid = RuntimeError("signal schema")
    mid.__cause__ = root
    outer = RetriableJobError("temporary")
    outer.__cause__ = mid
    text = _exception_cause_text(outer)
    assert "ValueError" in text
    assert "allowlist violation" in text


def test_retry_exhausted_message_surfaces_ai_cause_only() -> None:
    """Bug que cazaría: agotamiento que filtra payload o esconde causa de IA."""

    ai_job = SimpleNamespace(job_type="oracle.dossier_question.answer")
    msg = _retry_exhausted_message(ai_job, "Invalid JSON: EOF")  # type: ignore[arg-type]
    assert "Última causa: Invalid JSON: EOF" in msg

    mail_job = SimpleNamespace(job_type="notifications.send_email")
    assert _retry_exhausted_message(mail_job, "smtp timeout") == (  # type: ignore[arg-type]
        "Se agotaron los reintentos permitidos."
    )


def test_permanent_failure_message_for_ai_and_generic() -> None:
    root = TypeError("sections missing")
    wrapped = RuntimeError("handler boom")
    wrapped.__cause__ = root
    ai = SimpleNamespace(job_type="oracle.ai.summary")
    msg = _permanent_failure_message(ai, wrapped)  # type: ignore[arg-type]
    assert "TypeError" in msg
    assert "sections missing" in msg
    generic = SimpleNamespace(job_type="oracle.signal.triage")
    assert _permanent_failure_message(generic, wrapped) == "El job no pudo completarse."  # type: ignore[arg-type]


def _job_row(**overrides: Any) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "job_type": "oracle.signal.triage",
        "status": "queued",
        "stage": "queued",
        "payload_hash": b"h" * 32,
        "celery_task_id": "task-1",
        "execution_lease_id": None,
        "lease_expires_at": None,
        "cancel_requested": False,
        "attempts": 0,
        "max_attempts": 3,
        "started_at": None,
        "heartbeat_at": None,
        "finished_at": None,
        "progress": 0,
        "result_ref": None,
        "error_code": None,
        "error_message": None,
        "retryable": True,
        "not_before": None,
        "version": 1,
        "dossier_id": None,
        "correlation_id": None,
        "input_payload": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _FakeTask:
    class request:
        id = "task-1"

    def retry(self, *, exc: Exception, countdown: float, max_retries: int) -> None:
        raise exc


def test_execute_claimed_delivery_fencing_paths(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: delivery obsoleta/terminal/activa re-ejecuta el handler."""

    payload = {"resource_id": "x"}
    expected_hash = b"h" * 32
    task = _FakeTask()

    # obsolete celery delivery
    job = _job_row(celery_task_id="other-task", status="queued")
    monkeypatch.setattr(tasks.db.session, "scalar", lambda *a, **k: job)
    monkeypatch.setattr(tasks, "_log_job", lambda *a, **k: None)
    with app.app_context():
        ignored = _execute_claimed_delivery(
            task,  # type: ignore[arg-type]
            job_uuid=job.id,
            expected_payload_hash=expected_hash,
            payload=payload,
        )
    assert ignored == {"ignored": True, "reason": "obsolete_delivery"}

    # already succeeded → result_ref
    job = _job_row(status="succeeded", result_ref={"ok": True})
    monkeypatch.setattr(tasks.db.session, "scalar", lambda *a, **k: job)
    with app.app_context():
        done = _execute_claimed_delivery(
            task,  # type: ignore[arg-type]
            job_uuid=job.id,
            expected_payload_hash=expected_hash,
            payload=payload,
        )
    assert done == {"ok": True}

    # terminal failed
    job = _job_row(status="failed")
    monkeypatch.setattr(tasks.db.session, "scalar", lambda *a, **k: job)
    with app.app_context():
        terminal = _execute_claimed_delivery(
            task,  # type: ignore[arg-type]
            job_uuid=job.id,
            expected_payload_hash=expected_hash,
            payload=payload,
        )
    assert terminal == {"ignored": True, "reason": "terminal_state"}

    # active lease still held
    job = _job_row(
        status="running",
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        execution_lease_id=uuid.uuid4(),
    )
    monkeypatch.setattr(tasks.db.session, "scalar", lambda *a, **k: job)
    with app.app_context():
        active = _execute_claimed_delivery(
            task,  # type: ignore[arg-type]
            job_uuid=job.id,
            expected_payload_hash=expected_hash,
            payload=payload,
        )
    assert active == {"ignored": True, "reason": "active_delivery"}


def test_execute_claimed_delivery_cancel_before_start(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: cancel_requested que sigue corriendo el handler y marca succeeded."""

    job = _job_row(status="queued", cancel_requested=True, job_type="notifications.send_email")
    commits: list[str] = []
    monkeypatch.setattr(tasks.db.session, "scalar", lambda *a, **k: job)
    monkeypatch.setattr(tasks.db.session, "commit", lambda: commits.append("c"))
    monkeypatch.setattr(tasks, "_revoke_email_delivery", lambda j: None)
    monkeypatch.setattr(tasks, "append_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(tasks, "_log_job", lambda *a, **k: None)
    with app.app_context():
        result = _execute_claimed_delivery(
            _FakeTask(),  # type: ignore[arg-type]
            job_uuid=job.id,
            expected_payload_hash=job.payload_hash,
            payload={},
        )
    assert result == {"cancelled": True}
    assert job.status == "cancelled"
    assert commits == ["c"]


def test_execute_claimed_delivery_retriable_backoff_and_exhaustion(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: retriable que no programa backoff o no marca retry_exhausted."""

    # path 1: still has attempts → retrying + task.retry
    job = _job_row(status="queued", attempts=0, max_attempts=3, job_type="oracle.signal.triage")
    owned = job
    calls = {"n": 0}

    def _scalar(*_a: Any, **_k: Any) -> Any:
        calls["n"] += 1
        # first claim select, then _owned_lease before handler, then after error
        return owned

    monkeypatch.setattr(tasks.db.session, "scalar", _scalar)
    monkeypatch.setattr(tasks.db.session, "commit", lambda: None)
    monkeypatch.setattr(tasks.db.session, "rollback", lambda: None)
    monkeypatch.setattr(tasks, "_log_job", lambda *a, **k: None)
    monkeypatch.setattr(tasks, "append_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(
        tasks,
        "HANDLERS",
        {
            "oracle.signal.triage": lambda p, j: (_ for _ in ()).throw(
                RetriableJobError("Signal caído")
            )
        },
    )
    monkeypatch.setattr(tasks, "retry_delay", lambda attempt, jitter=None: 4.0)

    with app.app_context():
        app.config["CELERY_TASK_TIME_LIMIT"] = 300
        with pytest.raises(RetriableJobError, match="temporary_failure"):
            _execute_claimed_delivery(
                _FakeTask(),  # type: ignore[arg-type]
                job_uuid=job.id,
                expected_payload_hash=job.payload_hash,
                payload={"resource_id": "1"},
            )
    assert job.status == "retrying"
    assert job.stage == "backoff"
    assert job.error_code == "temporary_failure"
    assert job.not_before is not None

    # path 2: exhausted
    job2 = _job_row(
        status="queued",
        attempts=2,
        max_attempts=3,
        job_type="oracle.signal.triage",
    )
    monkeypatch.setattr(tasks.db.session, "scalar", lambda *a, **k: job2)
    monkeypatch.setattr(tasks, "_revoke_email_delivery", lambda j: None)
    monkeypatch.setattr(tasks, "_audit_job_failure", lambda j: None)
    with app.app_context():
        app.config["CELERY_TASK_TIME_LIMIT"] = 300
        with pytest.raises(RetriableJobError, match="temporary_failure"):
            _execute_claimed_delivery(
                _FakeTask(),  # type: ignore[arg-type]
                job_uuid=job2.id,
                expected_payload_hash=job2.payload_hash,
                payload={"resource_id": "1"},
            )
    assert job2.status == "failed"
    assert job2.stage == "retry_exhausted"
    assert job2.error_code == "retry_exhausted"
    assert job2.retryable is True


def test_execute_claimed_delivery_permanent_failure_sanitized(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: fallo permanente de job no-IA que filtra el detalle del payload."""

    job = _job_row(status="queued", attempts=0, max_attempts=3, job_type="oracle.signal.triage")
    monkeypatch.setattr(tasks.db.session, "scalar", lambda *a, **k: job)
    monkeypatch.setattr(tasks.db.session, "commit", lambda: None)
    monkeypatch.setattr(tasks.db.session, "rollback", lambda: None)
    monkeypatch.setattr(tasks, "_log_job", lambda *a, **k: None)
    monkeypatch.setattr(tasks, "append_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(tasks, "_revoke_email_delivery", lambda j: None)
    monkeypatch.setattr(tasks, "_audit_job_failure", lambda j: None)
    monkeypatch.setattr(
        tasks,
        "HANDLERS",
        {
            "oracle.signal.triage": lambda p, j: (_ for _ in ()).throw(
                RuntimeError("secret=must-not-leak in stack")
            )
        },
    )
    with app.app_context():
        app.config["CELERY_TASK_TIME_LIMIT"] = 300
        with pytest.raises(PermanentJobError, match="permanent_failure"):
            _execute_claimed_delivery(
                _FakeTask(),  # type: ignore[arg-type]
                job_uuid=job.id,
                expected_payload_hash=job.payload_hash,
                payload={"token": "secret"},
            )
    assert job.status == "failed"
    assert job.error_code == "permanent_failure"
    assert job.error_message == "El job no pudo completarse."
    assert "secret" not in (job.error_message or "")


def test_execute_claimed_payload_hash_mismatch_is_permanent(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: delivery con hash distinto al durable re-ejecuta el job."""

    job = _job_row(payload_hash=b"a" * 32)
    monkeypatch.setattr(tasks.db.session, "scalar", lambda *a, **k: job)
    with app.app_context(), pytest.raises(PermanentJobError, match="permanent_failure"):
        _execute_claimed_delivery(
            _FakeTask(),  # type: ignore[arg-type]
            job_uuid=job.id,
            expected_payload_hash=b"b" * 32,
            payload={},
        )


def test_write_handler_maps_custom_report_errors(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: CustomReportError del writer no se mapea a PermanentJobError."""

    job = _job_row(job_type="oracle.report.custom_brief.write")
    monkeypatch.setattr(
        tasks,
        "process_custom_brief_write",
        lambda *a, **k: (_ for _ in ()).throw(
            CustomReportError("Snapshot no congelado.", errors={"snapshot": ["missing"]})
        ),
    )
    with app.app_context(), pytest.raises(PermanentJobError, match="Snapshot no congelado"):
        tasks._write_custom_brief({"report_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]
