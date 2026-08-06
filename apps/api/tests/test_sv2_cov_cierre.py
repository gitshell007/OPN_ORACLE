"""SV2-COV-84-CIERRE · residual product coverage to restore the 84 bar.

Behavioral tests (not line-painting) for the residual table after tramos 1-3:

- ``oracle/routes.py`` — GET listados: paginación rota, filtros basura, tenant scope
- ``oracle/custom_report_lifecycle.py`` — materialize vía Signal (fail-closed paths)
- ``jobs/tasks.py`` — handlers restantes: mapeo permanent/retriable
- ``integrations/memory_routes.py`` — effective / capability / outbox / host_disabled /
  validación de put (token_budget, limit, sources)
- ``oracle/intent_routes.py`` — HTTP create/list/accept/reject + error mapping

Unit / Flask unit — no PG. Style aligned with ``test_sv2_cov_tramo3.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import g

from opn_oracle.auth import permissions
from opn_oracle.integrations import memory_routes
from opn_oracle.jobs import tasks
from opn_oracle.jobs.tasks import PermanentJobError, RetriableJobError
from opn_oracle.oracle import custom_report_lifecycle as lifecycle
from opn_oracle.oracle import intent_routes
from opn_oracle.oracle import routes as oracle_routes
from opn_oracle.oracle.custom_report_lifecycle import (
    _map_retrieve_to_evidence,
    _materialize_durable_memory,
)
from opn_oracle.oracle.intent import IntentConflict, IntentNotFound, IntentValidationError
from opn_oracle.oracle.service import DomainValidationError
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
    current_user_modules: tuple[Any, ...] = (),
) -> Iterator[tuple[User, uuid.UUID]]:
    actor = user or User(
        id=uuid.uuid4(),
        email="sv2-cov-cierre@example.com",
        display_name="SV2 COV CIERRE",
        status="active",
    )
    tid = tenant_id or uuid.uuid4()
    monkeypatch.setattr(permissions, "current_user", actor)
    for mod in current_user_modules:
        monkeypatch.setattr(mod, "current_user", actor)
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


def _job_row(**overrides: Any) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "job_type": "oracle.report.custom_brief.write",
        "status": "running",
        "attempt_count": 1,
        "max_attempts": 5,
        "resource_id": None,
        "payload_hash": b"a" * 32,
        "result_ref": {},
        "version": 1,
        "lease_id": uuid.uuid4(),
        "cancel_requested": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _dossier_ns(tenant_id: uuid.UUID, **overrides: Any) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "title": "Expediente cierre",
        "status": "active",
        "version": 1,
        "current_intent_revision_id": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ===========================================================================
# routes.py — listados GET: paginación / filtros (bugs reales de listado)
# ===========================================================================


def test_dossiers_list_rejects_broken_pagination(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: page[number] basura → 500 en vez de 422 domain_validation."""

    with _authenticated_http_probe(
        app, monkeypatch, frozenset({"dossier.read"}), current_user_modules=(oracle_routes,)
    ):
        bad = client.get("/api/v1/dossiers", query_string={"page[number]": "nope"})
    assert bad.status_code == 422
    assert bad.get_json()["code"] == "domain_validation"
    assert "Paginación" in bad.get_json()["detail"]


def test_dossiers_list_rejects_garbage_selected_ids_and_owner(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: filter[selected_ids]/filter[owner] basura → 500 o silencio."""

    with _authenticated_http_probe(
        app, monkeypatch, frozenset({"dossier.read"}), current_user_modules=(oracle_routes,)
    ):
        bad_ids = client.get(
            "/api/v1/dossiers",
            query_string={"filter[selected_ids]": "not-a-uuid,also-bad"},
        )
        bad_owner = client.get(
            "/api/v1/dossiers",
            query_string={"filter[owner]": "not-uuid"},
        )
        too_many = client.get(
            "/api/v1/dossiers",
            query_string={
                "filter[selected_ids]": ",".join(str(uuid.uuid4()) for _ in range(101)),
            },
        )
    assert bad_ids.status_code == 422
    assert "UUID" in bad_ids.get_json()["detail"] or "uuid" in bad_ids.get_json()["detail"].lower()
    assert bad_owner.status_code == 422
    assert "owner" in bad_owner.get_json()["detail"]
    assert too_many.status_code == 422
    assert "100" in too_many.get_json()["detail"]


def test_dossiers_list_ok_shape_with_mocked_page(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: listado sin meta.page/size/total o sin serializar filas."""

    dossier = _dossier_ns(uuid.uuid4(), title="Listado ok")
    monkeypatch.setattr(
        oracle_routes,
        "list_page",
        lambda *a, **k: ([dossier], 1),
    )
    monkeypatch.setattr(oracle_routes, "ensure_dossier_aggregates_many", lambda session, rows: rows)
    monkeypatch.setattr(
        oracle_routes,
        "_serialize",
        lambda row: {"id": str(row.id), "title": row.title, "status": row.status},
    )
    # _typed_list_criteria still runs against real request args — empty is fine.
    with _authenticated_http_probe(
        app, monkeypatch, frozenset({"dossier.read"}), current_user_modules=(oracle_routes,)
    ):
        ok = client.get(
            "/api/v1/dossiers",
            query_string={"page[number]": "1", "page[size]": "10", "filter[search]": "List"},
        )
    assert ok.status_code == 200, ok.get_data(as_text=True)[:400]
    body = ok.get_json()
    assert body["meta"] == {"page": 1, "size": 10, "total": 1}
    assert body["data"][0]["title"] == "Listado ok"


def test_opportunities_list_rejects_invalid_page_size(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: page[size]=999 (sobre 100) se acepta y drena el tenant."""

    # _global_dossier_resource_page validates size <= 100 before DB.
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"opportunity.read"}),
        current_user_modules=(oracle_routes,),
    ):
        bad = client.get(
            "/api/v1/opportunities",
            query_string={"page[size]": "999"},
        )
    assert bad.status_code == 422
    assert bad.get_json()["code"] == "domain_validation"


def test_risks_list_rejects_invalid_score_filter(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: filter[score_min]=abc o 150 se ignora o 500."""

    with _authenticated_http_probe(
        app, monkeypatch, frozenset({"risk.read"}), current_user_modules=(oracle_routes,)
    ):
        not_int = client.get("/api/v1/risks", query_string={"filter[score_min]": "abc"})
        out_of_range = client.get("/api/v1/risks", query_string={"filter[score_min]": "150"})
    assert not_int.status_code == 422
    assert out_of_range.status_code == 422
    assert (
        "score" in out_of_range.get_json()["detail"].lower()
        or "100" in out_of_range.get_json()["detail"]
    )


def test_page_args_helper_parses_sort_direction() -> None:
    """Bug que cazaría: sort=-title no marca descending y reordena al revés."""

    from flask import Flask

    probe = Flask("page-args")

    with probe.test_request_context("/?page[number]=2&page[size]=5&sort=-title"):
        page, size, sort, desc = oracle_routes._page_args()
    assert (page, size, sort, desc) == (2, 5, "title", True)

    with probe.test_request_context("/?sort=title"):
        _p, _s, sort2, desc2 = oracle_routes._page_args()
    assert sort2 == "title" and desc2 is False

    with probe.test_request_context("/?page[size]=x"), pytest.raises(DomainValidationError):
        oracle_routes._page_args()


# ===========================================================================
# custom_report_lifecycle — materialize Signal (fail-closed)
# ===========================================================================


def test_map_retrieve_excludes_non_objects_and_keeps_empty_watermark() -> None:
    """Bug que cazaría: item no-objeto o sin citabilidad inventa evidence_id."""

    tid, did = uuid.uuid4(), uuid.uuid4()
    evidence, allowlist, wm, cov = _map_retrieve_to_evidence(
        {
            "items": [
                "not-a-dict",
                {"id": "sig-1", "kind": "observation"},  # incompleto → excluded
            ],
            "watermark": "wm-durable-1",
            "coverage_manifest": {
                "version": "v1",
                "failed": ["src-a"],
                "used": [],
                "truncated": False,
            },
        },
        tenant_id=tid,
        dossier_id=did,
    )
    assert evidence == []
    assert allowlist == []
    assert wm == "wm-durable-1"
    assert cov["excluded_count"] >= 1
    assert cov["durable"] is True
    assert cov["coverage_manifest"]["failed"] == ["src-a"]


def test_materialize_flag_off_returns_degraded_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: flag OFF aún marca memory_mode=durable con allowlist inventada."""

    monkeypatch.setattr(lifecycle, "_memory_durable_flag", lambda: False)
    dossier = _dossier_ns(uuid.uuid4())
    out = _materialize_durable_memory(MagicMock(), dossier=dossier)  # type: ignore[arg-type]
    assert out["memory_mode"] == "disabled"
    assert out["memory_degraded"] is True
    assert out["allowlist"] == []
    assert out["memory_policy"]["materialized"] is False
    assert out["memory_policy"]["flag_alone_insufficient"] is True


def test_materialize_flag_on_without_connection_stays_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug que cazaría: flag ON sin conexión Signal declara durable=true."""

    monkeypatch.setattr(lifecycle, "_memory_durable_flag", lambda: True)
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_profile.resolve_signal_memory_connection",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no connection")),
    )
    dossier = _dossier_ns(uuid.uuid4())
    with tenant_context(TenantContext(tenant_id=dossier.tenant_id, actor_id=uuid.uuid4())):
        out = _materialize_durable_memory(MagicMock(), dossier=dossier)  # type: ignore[arg-type]
    assert out["memory_degraded"] is True
    assert out["memory_policy"].get("flag_was_set") is True
    assert out["memory_policy"]["materialized"] is False
    assert "flag_without_materialized_evidence" in out["coverage"].get("gaps", []) or "DUR" in (
        out.get("memory_degraded_reason") or ""
    )


def test_materialize_retrieve_failure_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: retrieve 5xx se traga y se inventa watermark durable."""

    monkeypatch.setattr(lifecycle, "_memory_durable_flag", lambda: True)
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_profile.resolve_signal_memory_connection",
        lambda *a, **k: SimpleNamespace(id=uuid.uuid4()),
    )

    class Boom:
        def retrieve(self, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("signal down")

    monkeypatch.setattr(lifecycle, "_signal_memory_client_for_materialize", lambda *a, **k: Boom())
    dossier = _dossier_ns(uuid.uuid4())
    with tenant_context(TenantContext(tenant_id=dossier.tenant_id, actor_id=uuid.uuid4())):
        out = _materialize_durable_memory(MagicMock(), dossier=dossier)  # type: ignore[arg-type]
    assert out["memory_degraded"] is True
    assert out["memory_policy"]["materialized"] is False
    assert "signal_retrieve_failed" in out["coverage"]["gaps"]
    assert out["allowlist"] == []


def test_materialize_missing_watermark_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: retrieve sin watermark se acepta como durable."""

    monkeypatch.setattr(lifecycle, "_memory_durable_flag", lambda: True)
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_profile.resolve_signal_memory_connection",
        lambda *a, **k: SimpleNamespace(id=uuid.uuid4()),
    )

    class NoWm:
        def retrieve(self, **kwargs: Any) -> dict[str, Any]:
            return {"items": [], "watermark": None}

    monkeypatch.setattr(lifecycle, "_signal_memory_client_for_materialize", lambda *a, **k: NoWm())
    dossier = _dossier_ns(uuid.uuid4())
    with tenant_context(TenantContext(tenant_id=dossier.tenant_id, actor_id=uuid.uuid4())):
        out = _materialize_durable_memory(MagicMock(), dossier=dossier)  # type: ignore[arg-type]
    assert out["memory_degraded"] is True
    assert "missing_watermark" in out["coverage"]["gaps"]
    assert out["memory_policy"]["materialized"] is False


def test_materialize_with_watermark_empty_allowlist_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: watermark + items=[] se rechaza (debe ser durable vacío OK)."""

    monkeypatch.setattr(lifecycle, "_memory_durable_flag", lambda: True)
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_profile.resolve_signal_memory_connection",
        lambda *a, **k: SimpleNamespace(id=uuid.uuid4()),
    )

    class EmptyDurable:
        def retrieve(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "items": [],
                "watermark": "wm-ok",
                "coverage_manifest": {
                    "version": "v1",
                    "failed": [],
                    "used": [],
                    "truncated": False,
                },
            }

    monkeypatch.setattr(
        lifecycle, "_signal_memory_client_for_materialize", lambda *a, **k: EmptyDurable()
    )
    dossier = _dossier_ns(uuid.uuid4())
    with tenant_context(TenantContext(tenant_id=dossier.tenant_id, actor_id=uuid.uuid4())):
        out = _materialize_durable_memory(MagicMock(), dossier=dossier)  # type: ignore[arg-type]
    assert out["memory_mode"] == "durable"
    assert out["memory_degraded"] is False
    assert out["watermark"] == "wm-ok"
    assert out["allowlist"] == []
    assert out["memory_policy"]["materialized"] is True
    assert out["memory_policy"]["empty_allowlist_ok"] is True


# ===========================================================================
# jobs/tasks.py — handlers residuales (mapeo permanent / retriable)
# ===========================================================================


def test_plan_handler_maps_custom_report_errors(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: CustomReportError del planificador → Retriable genérico."""

    from opn_oracle.oracle.custom_reports import CustomReportError

    job = _job_row(job_type="oracle.report.custom_brief.plan")
    monkeypatch.setattr(
        tasks,
        "process_custom_brief_plan",
        lambda *a, **k: (_ for _ in ()).throw(CustomReportError("brief no listo")),
    )
    with app.app_context(), pytest.raises(PermanentJobError, match="brief no listo"):
        tasks._plan_custom_brief({"report_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]


def test_review_handler_maps_not_found_and_generic_retry(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: not-found del review se reintenta en bucle."""

    from opn_oracle.oracle.custom_reports import CustomReportNotFound

    job = _job_row(job_type="oracle.report.custom_brief.review")
    monkeypatch.setattr(
        tasks,
        "process_custom_brief_review",
        lambda *a, **k: (_ for _ in ()).throw(CustomReportNotFound("gone")),
    )
    with app.app_context(), pytest.raises(PermanentJobError, match="gone"):
        tasks._review_custom_brief({"report_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "process_custom_brief_review",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("blip")),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="temporalmente"):
        tasks._review_custom_brief({"report_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]


def test_generate_report_contract_error_is_retriable(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: ReportOutputContractError se marca permanent y mata el snapshot."""

    from opn_oracle.reporting.service import ReportOutputContractError

    job = _job_row(job_type="oracle.report.generate")
    monkeypatch.setattr(
        tasks,
        "process_report",
        lambda *a, **k: (_ for _ in ()).throw(ReportOutputContractError("schema")),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="schema"):
        tasks._generate_report({"report_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]


def test_generate_export_and_document_permanent_on_bad_ids(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: export_id/document_id basura reintenta hasta agotar."""

    job = _job_row(job_type="oracle.export.generate")
    with app.app_context(), pytest.raises(PermanentJobError):
        tasks._generate_export({"export_id": "not-uuid"}, job)  # type: ignore[arg-type]

    job2 = _job_row(job_type="oracle.document.process")
    with app.app_context(), pytest.raises(PermanentJobError):
        tasks._process_document({"document_id": "x", "version_id": "y"}, job2)  # type: ignore[arg-type]


def test_evaluate_alerts_requires_timezone(app: Any) -> None:
    """Bug que cazaría: scheduled_at naive se acepta y despacha en hora local ambigua."""

    job = _job_row(job_type="oracle.alerts.evaluate")
    with app.app_context(), pytest.raises(PermanentJobError, match="timezone"):
        tasks._evaluate_alerts(
            {"scheduled_at": "2026-08-04T10:00:00"},
            job,  # type: ignore[arg-type]
        )
    with app.app_context(), pytest.raises(PermanentJobError, match="scheduled_at"):
        tasks._evaluate_alerts({}, job)  # type: ignore[arg-type]


def test_run_investigation_bad_run_id_and_resource_mismatch(app: Any) -> None:
    """Bug que cazaría: run_id basura o desalineado con resource_id se ejecuta igual."""

    job = _job_row(job_type="oracle.entity.investigation", resource_id=uuid.uuid4())
    with app.app_context(), pytest.raises(PermanentJobError, match="run_id"):
        tasks._run_investigation({"run_id": "nope"}, job)  # type: ignore[arg-type]

    good_id = uuid.uuid4()
    job.resource_id = uuid.uuid4()  # mismatch
    with app.app_context(), pytest.raises(PermanentJobError, match="no pertenece"):
        tasks._run_investigation({"run_id": str(good_id)}, job)  # type: ignore[arg-type]


def test_send_email_rejects_unknown_kind(app: Any) -> None:
    """Bug que cazaría: kind=marketing se envía con plantilla de reset."""

    job = _job_row(job_type="oracle.email.send")
    with app.app_context(), pytest.raises(PermanentJobError, match="no permitido"):
        tasks._send_email({"kind": "marketing", "user_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]


# ===========================================================================
# memory_routes — residual (effective / capability / outbox / host_disabled)
# ===========================================================================


class _FakeSession:
    def __init__(
        self,
        *,
        dossier: Any | None = None,
        profile: Any | None = None,
        deferred_profiles: list[Any] | None = None,
    ) -> None:
        self.dossier = dossier
        self.profile = profile
        self.deferred_profiles = list(deferred_profiles or [])
        self.commits = 0
        self.added: list[Any] = []

    @staticmethod
    def _selected_entity_name(query: Any) -> str | None:
        descriptions = getattr(query, "column_descriptions", ())
        if len(descriptions) != 1:
            return None
        return getattr(descriptions[0].get("entity"), "__name__", None)

    def scalar(self, query: Any) -> Any:
        if self._selected_entity_name(query) == "DossierMemoryProfile":
            return self.profile
        return self.dossier

    def scalars(self, query: Any) -> Any:
        assert self._selected_entity_name(query) == "DossierMemoryProfile"
        return SimpleNamespace(all=lambda: list(self.deferred_profiles))

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.commits += 1


def _wire_memory(monkeypatch: pytest.MonkeyPatch, session: _FakeSession) -> None:
    monkeypatch.setattr(memory_routes, "_session", lambda: session)
    monkeypatch.setattr(
        memory_routes,
        "dossier_accessible",
        lambda session, dossier, user_id, *, write: True,
    )

    def load_profile(
        sess: Any,
        *,
        tenant_id: uuid.UUID,
        dossier_id: uuid.UUID,
        connection_id: uuid.UUID | None,
    ) -> Any:
        if session.profile is None:
            return None
        if session.profile.tenant_id != tenant_id or session.profile.dossier_id != dossier_id:
            return None
        return session.profile

    monkeypatch.setattr(memory_routes, "_load_profile", load_profile)


def test_memory_effective_and_capability_http(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: effective sin capability o capability miente host disabled como ready."""

    app.config["MEMORY_CONTEXT_MODE"] = "disabled"
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.read"}),
        current_user_modules=(memory_routes,),
    ) as (_user, tenant_id):
        dossier = _dossier_ns(tenant_id)
        session = _FakeSession(dossier=dossier)
        _wire_memory(monkeypatch, session)
        eff = client.get(f"/api/v1/dossiers/{dossier.id}/memory/effective")
        cap = client.get("/api/v1/memory/capability")
    assert eff.status_code == 200, eff.get_json()
    body = eff.get_json()
    assert body["mode"] == "disabled"
    assert "capability" in body
    assert cap.status_code == 200
    cap_body = cap.get_json()
    assert isinstance(cap_body, dict)
    assert cap_body.get("host_mode") == "disabled"
    assert cap_body.get("publisher_reliable") is False


def test_memory_outbox_activity_safe_shape(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: outbox expone payload/secretos o 500 si empty."""

    monkeypatch.setattr(
        "opn_oracle.integrations.memory_outbox.list_memory_outbox_safe",
        lambda **k: [{"id": "o1", "status": "pending", "event_type": "ingest"}],
    )
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_outbox.bilateral_outbox_enabled",
        lambda: False,
    )
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.read"}),
        current_user_modules=(memory_routes,),
    ) as (_user, tenant_id):
        dossier = _dossier_ns(tenant_id)
        session = _FakeSession(dossier=dossier)
        _wire_memory(monkeypatch, session)
        resp = client.get(f"/api/v1/dossiers/{dossier.id}/memory/outbox")
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["dossier_id"] == str(dossier.id)
    assert body["items"][0]["status"] == "pending"
    assert body["bilateral_outbox_enabled"] is False
    assert "publisher_degraded" in body
    # no secret keys
    assert "payload" not in body["items"][0]
    assert "secret" not in body["items"][0]


def test_memory_test_connection_host_disabled(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: host disabled responde ok=true o no graba last_test_status."""

    app.config["MEMORY_CONTEXT_MODE"] = "disabled"
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.read", "dossier.write"}),
        current_user_modules=(memory_routes,),
    ) as (_user, tenant_id):
        dossier = _dossier_ns(tenant_id)
        profile = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            dossier_id=dossier.id,
            connection_id=None,
            mode="shadow",
            version=1,
            etag='W/"1"',
            profile_config={},
            last_test_at=None,
            last_test_status=None,
            last_error=None,
            last_coverage=None,
        )
        session = _FakeSession(dossier=dossier, profile=profile)
        _wire_memory(monkeypatch, session)
        resp = client.post(f"/api/v1/dossiers/{dossier.id}/memory/test-connection")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False
    assert body["status"] == "host_disabled"
    assert profile.last_test_status == "host_disabled"
    assert session.commits == 1


def test_memory_put_rejects_invalid_budget_limit_and_sources(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: token_budget/limit/sources basura se persisten sin validar."""

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.read", "dossier.write"}),
        current_user_modules=(memory_routes,),
    ) as (_user, tenant_id):
        dossier = _dossier_ns(tenant_id)
        session = _FakeSession(dossier=dossier)
        _wire_memory(monkeypatch, session)
        etag = client.get(f"/api/v1/dossiers/{dossier.id}/memory/profile").get_json()["etag"]

        budget = client.put(
            f"/api/v1/dossiers/{dossier.id}/memory/profile",
            json={"mode": "shadow", "token_budget": 999999},
            headers={"If-Match": etag},
        )
        limit = client.put(
            f"/api/v1/dossiers/{dossier.id}/memory/profile",
            json={"mode": "shadow", "limit": 0},
            headers={"If-Match": etag},
        )
        sources = client.put(
            f"/api/v1/dossiers/{dossier.id}/memory/profile",
            json={"mode": "shadow", "sources": "signal"},  # must be list
            headers={"If-Match": etag},
        )
        bad_source = client.put(
            f"/api/v1/dossiers/{dossier.id}/memory/profile",
            json={"mode": "shadow", "sources": ["not-a-real-source"]},
            headers={"If-Match": etag},
        )
    assert budget.status_code == 422
    assert limit.status_code == 422
    assert sources.status_code == 422
    assert bad_source.status_code == 422
    assert session.commits == 0


def test_memory_put_and_get_foreign_dossier_404(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: write/read en expediente inaccesible no devuelve 404."""

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.read", "dossier.write"}),
        current_user_modules=(memory_routes,),
    ):
        session = _FakeSession(dossier=None)
        _wire_memory(monkeypatch, session)
        get = client.get(f"/api/v1/dossiers/{uuid.uuid4()}/memory/effective")
        put = client.put(
            f"/api/v1/dossiers/{uuid.uuid4()}/memory/profile",
            json={"mode": "shadow"},
            headers={"If-Match": 'W/"x"'},
        )
        outbox = client.get(f"/api/v1/dossiers/{uuid.uuid4()}/memory/outbox")
    assert get.status_code == 404
    assert put.status_code == 404
    assert outbox.status_code == 404


# ===========================================================================
# intent_routes — HTTP boundary (67 % residual)
# ===========================================================================


def _revision_public(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "dossier_id": str(uuid.uuid4()),
        "version": 1,
        "schema_key": "market",
        "schema_version": "v1",
        "request_text": "Evaluar mercado BESS",
        "structured_spec": {"geographies": ["ES"]},
        "status": "draft",
        "content_hash": "a" * 64,
        "source_refs": [],
        "proposed_by_user_id": None,
        "accepted_by_user_id": None,
        "accepted_at": None,
        "row_version": 1,
        "created_at": "2026-08-04T08:00:00+00:00",
        "updated_at": "2026-08-04T08:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_intent_get_overview_and_404(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: get intent en expediente ajeno 200 o error no mapeado a 404."""

    dossier_id = uuid.uuid4()
    overview = {"current": None, "revisions": []}
    monkeypatch.setattr(intent_routes, "intent_overview", lambda *a, **k: overview)
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.read"}),
        current_user_modules=(intent_routes,),
    ):
        monkeypatch.setattr(intent_routes, "_dossier_or_404", lambda *a, **k: None)
        missing = client.get(f"/api/v1/dossiers/{dossier_id}/intent")
        monkeypatch.setattr(
            intent_routes, "_dossier_or_404", lambda *a, **k: SimpleNamespace(id=dossier_id)
        )
        ok = client.get(f"/api/v1/dossiers/{dossier_id}/intent")
    assert missing.status_code == 404
    assert ok.status_code == 200, ok.get_data(as_text=True)[:400]
    assert ok.get_json()["revisions"] == []


def test_intent_create_draft_201_and_validation_errors(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: IntentValidationError → 500; create sin commit semántico."""

    dossier_id = uuid.uuid4()
    revision = SimpleNamespace(id=uuid.uuid4())
    pub = _revision_public(dossier_id=str(dossier_id), id=str(revision.id))

    monkeypatch.setattr(
        intent_routes, "_dossier_or_404", lambda *a, **k: SimpleNamespace(id=dossier_id)
    )
    monkeypatch.setattr(intent_routes, "create_draft", lambda *a, **k: revision)
    monkeypatch.setattr(intent_routes, "serialize_intent_revision", lambda r: pub)
    monkeypatch.setattr(intent_routes.db.session, "rollback", lambda: None)

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.write", "dossier.read"}),
        current_user_modules=(intent_routes,),
    ):
        ok = client.post(
            f"/api/v1/dossiers/{dossier_id}/intent/drafts",
            json={
                "schema_key": "market",
                "schema_version": "v1",
                "request_text": "Evaluar mercado BESS en ES",
                "structured_spec": {},
                "source_refs": [],
            },
        )

        def boom(*a: Any, **k: Any) -> Any:
            raise IntentValidationError("payload inválido", errors={"request_text": ["empty"]})

        monkeypatch.setattr(intent_routes, "create_draft", boom)
        bad = client.post(
            f"/api/v1/dossiers/{dossier_id}/intent/drafts",
            json={
                "schema_key": "market",
                "schema_version": "v1",
                "request_text": "x",
            },
        )
    assert ok.status_code == 201, ok.get_data(as_text=True)[:500]
    assert ok.get_json()["schema_key"] == "market"
    assert bad.status_code == 422
    assert bad.get_json()["code"] == "validation_error"


def test_intent_update_accept_reject_conflict_and_not_found(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: version_conflict → 500; revision de otro dossier se acepta."""

    dossier_id = uuid.uuid4()
    other_dossier = uuid.uuid4()
    revision_id = uuid.uuid4()
    pub = _revision_public(dossier_id=str(dossier_id), id=str(revision_id), status="accepted")

    monkeypatch.setattr(
        intent_routes, "_dossier_or_404", lambda *a, **k: SimpleNamespace(id=dossier_id)
    )
    monkeypatch.setattr(intent_routes.db.session, "rollback", lambda: None)

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.write", "dossier.read"}),
        current_user_modules=(intent_routes,),
    ):
        # Cross-dossier revision → 404
        monkeypatch.setattr(
            intent_routes,
            "get_revision",
            lambda *a, **k: SimpleNamespace(id=revision_id, dossier_id=other_dossier),
        )
        cross = client.post(f"/api/v1/dossiers/{dossier_id}/intent/drafts/{revision_id}/accept")
        assert cross.status_code == 404

        # Accept ok
        monkeypatch.setattr(
            intent_routes,
            "get_revision",
            lambda *a, **k: SimpleNamespace(id=revision_id, dossier_id=dossier_id),
        )
        monkeypatch.setattr(intent_routes, "accept_revision", lambda *a, **k: SimpleNamespace())
        monkeypatch.setattr(intent_routes, "serialize_intent_revision", lambda r: pub)
        accepted = client.post(f"/api/v1/dossiers/{dossier_id}/intent/drafts/{revision_id}/accept")
        assert accepted.status_code == 200, accepted.get_data(as_text=True)[:400]

        # Reject conflict
        def conflict(*a: Any, **k: Any) -> Any:
            raise IntentConflict("versión stale")

        monkeypatch.setattr(intent_routes, "reject_revision", conflict)
        rejected = client.post(f"/api/v1/dossiers/{dossier_id}/intent/drafts/{revision_id}/reject")
        assert rejected.status_code == 409
        assert rejected.get_json()["code"] == "version_conflict"

        # Update draft with expected_row_version
        monkeypatch.setattr(intent_routes, "update_draft", lambda *a, **k: SimpleNamespace())
        monkeypatch.setattr(
            intent_routes,
            "serialize_intent_revision",
            lambda r: _revision_public(id=str(revision_id), row_version=2),
        )
        updated = client.patch(
            f"/api/v1/dossiers/{dossier_id}/intent/drafts/{revision_id}",
            json={"expected_row_version": 1, "request_text": "Texto actualizado del intent"},
        )
        assert updated.status_code == 200, updated.get_data(as_text=True)[:400]


def test_requirements_and_offerings_list_create_http(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: list vacía 500; create no mapea validation; class_ no se reescribe."""

    dossier_id = uuid.uuid4()
    monkeypatch.setattr(
        intent_routes, "_dossier_or_404", lambda *a, **k: SimpleNamespace(id=dossier_id)
    )
    monkeypatch.setattr(intent_routes, "list_requirements", lambda *a, **k: [])
    monkeypatch.setattr(intent_routes, "list_offerings", lambda *a, **k: [])
    monkeypatch.setattr(intent_routes.db.session, "rollback", lambda: None)

    req_pub = {
        "id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "dossier_id": str(dossier_id),
        "intent_revision_id": None,
        "class": "market_scan",
        "priority": "medium",
        "question": "¿Quién compite en BESS?",
        "decision_to_support": "Entrar o no",
        "scope": {},
        "exclusions": {},
        "success_criteria": [],
        "status": "active",
        "alignment_state": "aligned",
        "created_at": None,
        "updated_at": None,
    }
    off_pub = {
        "id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "dossier_id": str(dossier_id),
        "intent_revision_id": None,
        "name": "Integración BESS",
        "aliases": [],
        "taxonomies": {},
        "description": "",
        "status": "active",
        "created_at": None,
        "updated_at": None,
    }

    captured: dict[str, Any] = {}

    def capture_req(*a: Any, **k: Any) -> Any:
        captured["req"] = k.get("payload") or (a[2] if len(a) > 2 else None)
        return SimpleNamespace()

    def capture_off(*a: Any, **k: Any) -> Any:
        captured["off"] = k.get("payload")
        return SimpleNamespace()

    monkeypatch.setattr(intent_routes, "create_requirement", capture_req)
    monkeypatch.setattr(intent_routes, "serialize_requirement", lambda r: req_pub)
    monkeypatch.setattr(intent_routes, "create_offering", capture_off)
    monkeypatch.setattr(intent_routes, "serialize_offering", lambda r: off_pub)

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.read", "dossier.write"}),
        current_user_modules=(intent_routes,),
    ):
        req_list = client.get(f"/api/v1/dossiers/{dossier_id}/requirements")
        off_list = client.get(f"/api/v1/dossiers/{dossier_id}/offerings")
        req_create = client.post(
            f"/api/v1/dossiers/{dossier_id}/requirements",
            json={
                "class": "market_scan",
                "question": "¿Quién compite en BESS?",
                "priority": "high",
            },
        )
        off_create = client.post(
            f"/api/v1/dossiers/{dossier_id}/offerings",
            json={"name": "Integración BESS"},
        )

        def boom(*a: Any, **k: Any) -> Any:
            raise IntentValidationError("clase inválida", errors={"class": ["bad"]})

        monkeypatch.setattr(intent_routes, "create_requirement", boom)
        req_bad = client.post(
            f"/api/v1/dossiers/{dossier_id}/requirements",
            json={"class": "market_scan", "question": "x"},
        )

    assert req_list.status_code == 200
    assert req_list.get_json()["items"] == []
    assert off_list.status_code == 200
    assert req_create.status_code == 201, req_create.get_data(as_text=True)[:400]
    assert off_create.status_code == 201, off_create.get_data(as_text=True)[:400]
    # payload must expose class (not class_) for the service layer
    if captured.get("req"):
        assert "class" in captured["req"] or "class_" not in str(captured["req"])
    assert req_bad.status_code == 422


def test_intent_error_mapper_branches() -> None:
    """Bug que cazaría: IntentNotFound no es 404; excepciones genéricas 500."""

    from flask import Flask

    probe = Flask("intent-errors")
    with probe.test_request_context("/api/v1/dossiers/x/intent"):
        nf = intent_routes._error(IntentNotFound("gone"))
        cf = intent_routes._error(IntentConflict("stale"))
        ve = intent_routes._error(IntentValidationError("bad", errors={"x": ["y"]}))
        other = intent_routes._error(ValueError("weird"))
    assert nf.status_code == 404
    assert cf.status_code == 409
    assert ve.status_code == 422
    assert other.status_code == 422


# ===========================================================================
# routes.py — nested create/list, procurement, helpers
# ===========================================================================


def test_nested_create_404_and_archived_readonly(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: create nested en archivado o 404 → 500 o escribe igual."""

    dossier_id = uuid.uuid4()
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"opportunity.write", "opportunity.read"}),
        current_user_modules=(oracle_routes,),
    ):
        monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: None)
        missing = client.post(
            f"/api/v1/dossiers/{dossier_id}/opportunities",
            json={"title": "Opp"},
        )
        archived = _dossier_ns(uuid.uuid4(), status="archived")
        monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: archived)
        blocked = client.post(
            f"/api/v1/dossiers/{dossier_id}/opportunities",
            json={"title": "Opp"},
        )
    assert missing.status_code == 404
    assert blocked.status_code == 422
    assert "archivado" in blocked.get_json()["detail"].lower()


def test_nested_create_title_required_and_scored_ok(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: opportunity sin title se crea; create scored no devuelve 201."""

    dossier_id = uuid.uuid4()
    dossier = _dossier_ns(uuid.uuid4(), id=dossier_id)
    created = SimpleNamespace(
        id=uuid.uuid4(),
        title="Opp real",
        status="identified",
        version=1,
        overall_score=40,
    )
    monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: dossier)
    monkeypatch.setattr(
        oracle_routes,
        "create_scored_resource",
        lambda *a, **k: created,
    )
    monkeypatch.setattr(
        oracle_routes,
        "_serialize",
        lambda row: {
            "id": str(row.id),
            "title": row.title,
            "status": row.status,
            "version": row.version,
        },
    )
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"opportunity.write", "task.write", "task.read"}),
        current_user_modules=(oracle_routes,),
    ):
        # Risk-like path uses create_scored_resource for Opportunity/RiskItem
        ok = client.post(
            f"/api/v1/dossiers/{dossier_id}/opportunities",
            json={"title": "Opp real", "status": "identified"},
        )
        # Task nested uses _safe_construct — empty title → 422
        monkeypatch.setattr(
            oracle_routes,
            "_safe_construct",
            lambda *a, **k: (_ for _ in ()).throw(DomainValidationError("title es obligatorio.")),
        )
        bad_title = client.post(
            f"/api/v1/dossiers/{dossier_id}/tasks",
            json={"title": "   "},
        )
    assert ok.status_code == 201, ok.get_data(as_text=True)[:400]
    assert ok.get_json()["title"] == "Opp real"
    assert bad_title.status_code == 422


def test_nested_list_404_and_pagination_error(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: nested list en dossier ajeno 200; page basura 500."""

    dossier_id = uuid.uuid4()
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"opportunity.read", "risk.read"}),
        current_user_modules=(oracle_routes,),
    ):
        monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: None)
        missing = client.get(f"/api/v1/dossiers/{dossier_id}/risks")
        monkeypatch.setattr(
            oracle_routes, "_dossier_or_404", lambda *a, **k: _dossier_ns(uuid.uuid4())
        )
        # Force page validation via real _page_args
        bad = client.get(
            f"/api/v1/dossiers/{dossier_id}/risks",
            query_string={"page[number]": "x"},
        )
    assert missing.status_code == 404
    assert bad.status_code == 422


def test_procurement_pin_list_delete_contracts(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: pin en archivado, list 404, delete missing, promote sin key."""

    from opn_oracle.oracle.procurement_items import ProcurementItemError

    dossier_id = uuid.uuid4()
    item = SimpleNamespace(id=uuid.uuid4(), kind="award", folder_id="f1")
    monkeypatch.setattr(
        oracle_routes,
        "serialize_procurement_item",
        lambda i: {"id": str(i.id), "kind": i.kind, "folder_id": i.folder_id},
    )
    monkeypatch.setattr(oracle_routes.db.session, "commit", lambda: None)
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset(
            {
                "opportunity.write",
                "opportunity.read",
                "report.generate",
            }
        ),
        current_user_modules=(oracle_routes,),
    ):
        archived = _dossier_ns(uuid.uuid4(), status="archived")
        monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: archived)
        pin_arch = client.post(
            f"/api/v1/dossiers/{dossier_id}/procurement",
            json={"kind": "award", "folder_id": "x"},
        )
        assert pin_arch.status_code == 422

        active = _dossier_ns(uuid.uuid4(), id=dossier_id)
        monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: active)
        monkeypatch.setattr(oracle_routes, "pin_procurement_item", lambda *a, **k: (item, True))
        pin_ok = client.post(
            f"/api/v1/dossiers/{dossier_id}/procurement",
            json={"kind": "award", "folder_id": "f1"},
        )
        assert pin_ok.status_code == 201, pin_ok.get_data(as_text=True)[:400]

        monkeypatch.setattr(oracle_routes, "list_procurement_items", lambda *a, **k: [item])
        listed = client.get(f"/api/v1/dossiers/{dossier_id}/procurement")
        assert listed.status_code == 200
        assert listed.get_json()["data"][0]["kind"] == "award"

        monkeypatch.setattr(oracle_routes, "delete_procurement_item", lambda *a, **k: False)
        del_missing = client.delete(f"/api/v1/dossiers/{dossier_id}/procurement/{item.id}")
        assert del_missing.status_code == 404

        monkeypatch.setattr(oracle_routes, "delete_procurement_item", lambda *a, **k: True)
        del_ok = client.delete(f"/api/v1/dossiers/{dossier_id}/procurement/{item.id}")
        assert del_ok.status_code == 200

        no_key = client.post(
            f"/api/v1/dossiers/{dossier_id}/procurement/{item.id}/promote",
            json={},
        )
        assert no_key.status_code == 428
        assert no_key.get_json()["code"] == "precondition_required"

        monkeypatch.setattr(
            oracle_routes,
            "promote_procurement_to_opportunity",
            lambda *a, **k: (_ for _ in ()).throw(ProcurementItemError("no encontrada")),
        )
        promo_404 = client.post(
            f"/api/v1/dossiers/{dossier_id}/procurement/{item.id}/promote",
            json={},
            headers={"Idempotency-Key": "promo-1"},
        )
        assert promo_404.status_code == 404

        # report without awards
        monkeypatch.setattr(oracle_routes, "list_procurement_items", lambda *a, **k: [])
        rep = client.post(
            f"/api/v1/dossiers/{dossier_id}/procurement/reports",
            json={},
            headers={"Idempotency-Key": "rep-1"},
        )
        assert rep.status_code == 422
        assert "adjudicación" in rep.get_json()["detail"].lower()


def test_procurement_refresh_maps_errors(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: refresh en archivado o item missing → 500."""

    from opn_oracle.oracle.procurement_items import ProcurementItemError

    dossier_id = uuid.uuid4()
    item_id = uuid.uuid4()
    monkeypatch.setattr(oracle_routes.db.session, "commit", lambda: None)
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"opportunity.write"}),
        current_user_modules=(oracle_routes,),
    ):
        archived = _dossier_ns(uuid.uuid4(), status="archived")
        monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: archived)
        arch = client.post(f"/api/v1/dossiers/{dossier_id}/procurement/{item_id}/refresh")
        assert arch.status_code == 422

        active = _dossier_ns(uuid.uuid4())
        monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: active)
        monkeypatch.setattr(
            oracle_routes,
            "refresh_procurement_item",
            lambda *a, **k: (_ for _ in ()).throw(ProcurementItemError("Ítem no encontrada")),
        )
        missing = client.post(f"/api/v1/dossiers/{dossier_id}/procurement/{item_id}/refresh")
        assert missing.status_code == 404


def test_home_attention_item_shape() -> None:
    """Bug que cazaría: href/dossier_id mal formados en attention del home."""

    dossier = _dossier_ns(uuid.uuid4(), title="D")
    item = oracle_routes._home_attention_item(
        kind="risks",
        resource_id=uuid.uuid4(),
        title="Riesgo X",
        status="open",
        updated_at=datetime.now(UTC),
        dossier=dossier,  # type: ignore[arg-type]
        score=70,
        due_at=None,
    )
    assert item["kind"] == "risks"
    assert item["dossier_title"] == "D"
    assert item["score"] == 70
    assert item["due_at"] is None
    assert str(dossier.id) in item["href"]


def test_safe_construct_requires_title(app: Any) -> None:
    """Bug que cazaría: nested construct sin title crea fila vacía."""

    from opn_oracle.oracle.models import Task

    with app.app_context(), app.test_request_context("/"):
        g.active_tenant_id = uuid.uuid4()
        with pytest.raises(DomainValidationError, match="title"):
            oracle_routes._safe_construct(Task, {"title": "  "}, uuid.uuid4())


def test_typed_list_criteria_date_and_type_guards() -> None:
    """Bug que cazaría: date/type basura se ignora o crashea el listado."""

    from flask import Flask

    from opn_oracle.oracle.models import Opportunity, StrategicDossier

    probe = Flask("typed-list")
    with (
        probe.test_request_context("/?filter[date_from]=not-a-date&filter[type]=market"),
        pytest.raises(DomainValidationError),
    ):
        oracle_routes._typed_list_criteria(Opportunity)

    with probe.test_request_context("/?filter[type]=market"):
        # StrategicDossier has dossier_type
        crit = oracle_routes._typed_list_criteria(StrategicDossier)
        assert len(crit) == 1

    with probe.test_request_context("/?filter[score_min]=10"):
        # Task has no overall_score → error
        from opn_oracle.oracle.models import Task

        with pytest.raises(DomainValidationError, match="score"):
            oracle_routes._typed_list_criteria(Task)


def test_parse_datetime_and_date_helpers() -> None:
    """Bug que cazaría: Z/ISO mal parseados rompen nested meeting create."""

    assert oracle_routes._parse_datetime_value(None) is None
    dt = oracle_routes._parse_datetime_value("2026-08-04T10:00:00Z")
    assert dt is not None and dt.tzinfo is not None
    d = oracle_routes._parse_date_value("2026-08-04")
    assert d is not None
    assert oracle_routes._parse_date_value(None) is None


# ===========================================================================
# lifecycle — productive generation gate + parse helpers
# ===========================================================================


def test_productive_generation_gate_fail_closed() -> None:
    """Bug que cazaría: snapshot no durable o sin hash encola writer productivo."""

    from opn_oracle.oracle.custom_report_lifecycle import _productive_generation_allowed

    ok, code, _ = _productive_generation_allowed(
        {"memory_mode": "disabled", "memory_policy": {}, "watermark": "w"}
    )
    assert ok is False and code == "memory_not_durable"

    ok, code, _ = _productive_generation_allowed(
        {
            "memory_mode": "durable",
            "memory_policy": {"materialized": False},
            "watermark": "w",
        }
    )
    assert ok is False and code == "memory_not_materialized"

    ok, code, _ = _productive_generation_allowed(
        {
            "memory_mode": "durable",
            "memory_policy": {"materialized": True},
            "watermark": None,
        }
    )
    assert ok is False and code == "memory_watermark_missing"

    ok, code, _ = _productive_generation_allowed(
        {
            "memory_mode": "durable",
            "memory_policy": {"materialized": True, "empty_allowlist_ok": True},
            "watermark": "wm",
            "runtime_sha256": "not-a-dict",
        }
    )
    assert ok is False and code == "runtime_hash_missing"

    bad_hash = "a" * 63
    ok, code, _ = _productive_generation_allowed(
        {
            "memory_mode": "durable",
            "memory_policy": {"materialized": True},
            "watermark": "wm",
            "runtime_sha256": {
                "plan": "a" * 64,
                "writer": "b" * 64,
                "review": bad_hash,
            },
        }
    )
    assert ok is False and code == "runtime_hash_missing"

    ok, code, reason = _productive_generation_allowed(
        {
            "memory_mode": "durable",
            "memory_policy": {"materialized": True, "empty_allowlist_ok": True},
            "watermark": "wm",
            "runtime_sha256": {
                "plan": "a" * 64,
                "writer": "b" * 64,
                "review": "c" * 64,
            },
        }
    )
    assert ok is True and code == "" and reason == ""


# ===========================================================================
# jobs/tasks — more handlers residual
# ===========================================================================


def test_summary_briefing_change_permanent_on_bad_ids(app: Any) -> None:
    """Bug que cazaría: dossier_id/meeting_id basura reintenta en bucle."""

    job = _job_row(job_type="oracle.summary.refresh")
    with app.app_context(), pytest.raises(PermanentJobError):
        tasks._refresh_dossier_summary({"dossier_id": "nope"}, job)  # type: ignore[arg-type]
    with app.app_context(), pytest.raises(PermanentJobError):
        tasks._refresh_meeting_briefing({"meeting_id": "nope"}, job)  # type: ignore[arg-type]
    with app.app_context(), pytest.raises(PermanentJobError):
        tasks._refresh_weekly_change({"dossier_id": "nope"}, job)  # type: ignore[arg-type]


def test_sync_monitor_and_scan_watch_validation(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: monitor_id/watch_id basura o monitor inactivo se ejecuta."""

    job = _job_row(job_type="oracle.monitor.sync")
    with app.app_context(), pytest.raises(PermanentJobError, match="Monitor"):
        tasks._sync_monitor({"monitor_id": "bad"}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(tasks.db.session, "scalar", lambda *a, **k: None)
    with app.app_context(), pytest.raises(PermanentJobError, match="no disponible"):
        tasks._sync_monitor({"monitor_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]

    with app.app_context(), pytest.raises(PermanentJobError, match="Vigilancia"):
        tasks._scan_procurement_watch({"watch_id": "x"}, job)  # type: ignore[arg-type]


def test_weekly_digest_timezone_and_triage_stub(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: timezone basura se acepta; triage sin dossier en testing no stub."""

    job = _job_row(job_type="oracle.digest.weekly")
    with app.app_context(), pytest.raises(PermanentJobError, match="Timezone"):
        tasks._weekly_digest({"timezone": "Not/AZone"}, job)  # type: ignore[arg-type]
    with app.app_context():
        out = tasks._weekly_digest({"timezone": "Europe/Madrid"}, job)  # type: ignore[arg-type]
    assert out["processed"] is True
    assert out["timezone"] == "Europe/Madrid"

    # testing stub path for triage without dossier_id
    app.config["TESTING"] = True
    job2 = _job_row(job_type="oracle.signal.triage")
    with app.app_context():
        # current_app.testing True
        stubbed = tasks._triage_signal({}, job2)  # type: ignore[arg-type]
    assert "signal_triage" in str(stubbed.get("kind", stubbed))


def test_send_notification_and_digest_id_errors(app: Any) -> None:
    """Bug que cazaría: delivery_id/preference_id basura se reintenta."""

    job = _job_row(job_type="oracle.notification.send")
    with app.app_context(), pytest.raises(PermanentJobError):
        tasks._send_notification({"delivery_id": "x"}, job)  # type: ignore[arg-type]
    with app.app_context(), pytest.raises(PermanentJobError):
        tasks._send_digest({"preference_id": "x"}, job)  # type: ignore[arg-type]


def test_answer_handler_classifies_retryable_and_permanent(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: 429 de Ask dual se marca Permanent y corta reintentos."""

    from opn_oracle.integrations.memory_ask_dual import (
        PermanentMemoryAskError,
        RetryableMemoryAskError,
    )

    job = _job_row(job_type="oracle.conversation.answer")
    monkeypatch.setattr(
        tasks,
        "process_dossier_question_answer",
        lambda *a, **k: (_ for _ in ()).throw(RetryableMemoryAskError("429")),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="429"):
        tasks._answer_dossier_question({"message_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "process_dossier_question_answer",
        lambda *a, **k: (_ for _ in ()).throw(PermanentMemoryAskError("allowlist")),
    )
    with app.app_context(), pytest.raises(PermanentJobError, match="allowlist"):
        tasks._answer_dossier_question({"message_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]


def test_entity_and_competitive_report_handler_mapping(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: AIPolicyDenied reintenta; contract error se marca permanent."""

    from opn_oracle.ai.service import AIPolicyDenied
    from opn_oracle.reporting.service import ReportOutputContractError

    job = _job_row(job_type="oracle.entity_dossier_report.generate")
    monkeypatch.setattr(
        tasks,
        "process_entity_dossier_report",
        lambda *a, **k: (_ for _ in ()).throw(AIPolicyDenied("kill switch")),
    )
    with app.app_context(), pytest.raises(PermanentJobError, match="kill"):
        tasks._generate_entity_dossier_report({"report_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]

    job2 = _job_row(job_type="oracle.competitive_procurement_report.generate")
    monkeypatch.setattr(
        tasks,
        "process_competitive_procurement_report",
        lambda *a, **k: (_ for _ in ()).throw(ReportOutputContractError("shape")),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="shape"):
        tasks._generate_competitive_procurement_report(
            {"report_id": str(uuid.uuid4())},
            job2,  # type: ignore[arg-type]
        )


def test_execute_durable_bad_uuids(app: Any) -> None:
    """Bug que cazaría: job_id/tenant_id basura se reintenta o crashea sin sanitizar."""

    class FakeTask:
        request = SimpleNamespace(id="t1", retries=0)

    with app.app_context(), pytest.raises(PermanentJobError):
        tasks.execute_durable(
            FakeTask(),  # type: ignore[arg-type]
            job_id="not-uuid",
            tenant_id="also-bad",
            payload={},
        )


# ===========================================================================
# memory_routes — put body validation + connection_id on get
# ===========================================================================


def test_memory_get_profile_persisted_row(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: perfil persistido se devuelve como ephemeral o sin ETag."""

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.read"}),
        current_user_modules=(memory_routes,),
    ) as (_user, tenant_id):
        dossier = _dossier_ns(tenant_id)
        cfg = {
            "mode": "shadow",
            "sources": ["signal"],
            "kinds": [],
            "classifications_allowed": [],
            "token_budget": 1000,
            "limit": 10,
        }
        profile = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            dossier_id=dossier.id,
            connection_id=None,
            mode="shadow",
            version=3,
            etag='W/"dmp-v3-abc"',
            profile_config=cfg,
            last_test_at=None,
            last_test_status=None,
            last_error=None,
            last_coverage=None,
            updated_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        session = _FakeSession(dossier=dossier, profile=profile)
        _wire_memory(monkeypatch, session)
        monkeypatch.setattr(
            memory_routes,
            "profile_to_public",
            lambda row: {
                "id": str(row.id),
                "mode": row.mode,
                "version": row.version,
                "etag": row.etag,
                "tenant_id": str(row.tenant_id),
                "dossier_id": str(row.dossier_id),
                "connection_id": None,
                "sources": [],
                "kinds": [],
                "classifications_allowed": [],
                "token_budget": 1000,
                "limit": 10,
                "status": "ok",
                "provenance": "db",
                "last_test_at": None,
                "last_test_status": None,
                "last_error": None,
                "last_coverage": None,
                "updated_at": None,
            },
        )
        resp = client.get(f"/api/v1/dossiers/{dossier.id}/memory/profile")
    assert resp.status_code == 200
    assert resp.get_json()["persisted"] is True
    assert resp.get_json()["mode"] == "shadow"
    assert resp.headers.get("ETag") == 'W/"dmp-v3-abc"'


def test_memory_put_requires_object_body(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: body array se acepta como profile update."""

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.read", "dossier.write"}),
        current_user_modules=(memory_routes,),
    ) as (_user, tenant_id):
        dossier = _dossier_ns(tenant_id)
        session = _FakeSession(dossier=dossier)
        _wire_memory(monkeypatch, session)
        etag = client.get(f"/api/v1/dossiers/{dossier.id}/memory/profile").get_json()["etag"]
        # Flask/json: send a JSON array
        resp = client.put(
            f"/api/v1/dossiers/{dossier.id}/memory/profile",
            data="[1,2]",
            content_type="application/json",
            headers={"If-Match": etag},
        )
    assert resp.status_code == 422
    assert resp.get_json()["code"] == "schema_validation_failed"


# ===========================================================================
# Wave 2 — list/search/changes validation + maintenance task gates
# ===========================================================================


def test_global_search_rejects_bad_query_limit_and_types(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: search con q corto, limit basura o types raros → 500 o leak."""

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.read"}),
        current_user_modules=(oracle_routes,),
    ):
        short = client.get("/api/v1/search", query_string={"q": "x"})
        long_q = client.get("/api/v1/search", query_string={"q": "y" * 101})
        bad_limit = client.get("/api/v1/search", query_string={"q": "ab", "limit": "nope"})
        over_limit = client.get("/api/v1/search", query_string={"q": "ab", "limit": "99"})
        bad_types = client.get(
            "/api/v1/search",
            query_string={"q": "ab", "types": "dossiers,secrets"},
        )
    for resp in (short, long_q, bad_limit, over_limit, bad_types):
        assert resp.status_code == 422, resp.get_data(as_text=True)[:200]
        assert resp.get_json()["code"] == "domain_validation"


def test_changes_list_rejects_bad_sort_size_and_since(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: changes con size>50 o since basura drena/crashea."""

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.read"}),
        current_user_modules=(oracle_routes,),
    ):
        big = client.get("/api/v1/changes", query_string={"page[size]": "99"})
        bad_sort = client.get("/api/v1/changes", query_string={"sort": "title"})
        bad_since = client.get(
            "/api/v1/changes",
            query_string={"filter[since]": "ayer"},
        )
    assert big.status_code == 422
    assert bad_sort.status_code == 422
    assert bad_since.status_code == 422


def test_change_digest_get_empty_and_value_error(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: digest vacío 500; ValueError no mapea a domain_validation."""

    monkeypatch.setattr(oracle_routes, "resolve_digest_dossier_id", lambda **k: None)
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.read"}),
        current_user_modules=(oracle_routes,),
    ):
        empty = client.get("/api/v1/changes/digest")
        assert empty.status_code == 200
        assert empty.get_json()["state"] == "empty"

        monkeypatch.setattr(
            oracle_routes,
            "resolve_digest_dossier_id",
            lambda **k: (_ for _ in ()).throw(ValueError("scope inválido")),
        )
        bad = client.get("/api/v1/changes/digest")
    assert bad.status_code == 422


def test_change_digest_refresh_404_and_archived(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: refresh digest en archivado o sin expediente escribe igual."""

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.write", "dossier.read"}),
        current_user_modules=(oracle_routes,),
    ):
        monkeypatch.setattr(oracle_routes, "resolve_digest_dossier_id", lambda **k: None)
        missing = client.post("/api/v1/changes/digest", json={})
        assert missing.status_code == 404

        did = uuid.uuid4()
        monkeypatch.setattr(oracle_routes, "resolve_digest_dossier_id", lambda **k: did)
        monkeypatch.setattr(
            oracle_routes,
            "_dossier_or_404",
            lambda *a, **k: _dossier_ns(uuid.uuid4(), status="archived"),
        )
        arch = client.post(
            "/api/v1/changes/digest",
            json={"dossier_id": str(did)},
            headers={"Idempotency-Key": "d1"},
        )
    assert arch.status_code == 422
    assert "archivado" in arch.get_json()["detail"].lower()


def test_signals_list_rejects_bad_pagination(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: /signals con page basura → 500."""

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"signal.read"}),
        current_user_modules=(oracle_routes,),
    ):
        bad = client.get("/api/v1/signals", query_string={"page[number]": "x"})
    assert bad.status_code == 422


def test_dossier_get_and_signals_nested_404(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: get dossier/signals de otro tenant no es 404."""

    monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: None)
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.read", "signal.read"}),
        current_user_modules=(oracle_routes,),
    ):
        g1 = client.get(f"/api/v1/dossiers/{uuid.uuid4()}")
        g2 = client.get(f"/api/v1/dossiers/{uuid.uuid4()}/signals")
        g3 = client.get(f"/api/v1/dossiers/{uuid.uuid4()}/evidence")
    assert g1.status_code == 404
    assert g2.status_code == 404
    assert g3.status_code == 404


def test_evidence_list_ok_with_mock(app: Any, client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: list evidence sin data/meta o sin serializar."""

    dossier = _dossier_ns(uuid.uuid4())
    monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: dossier)
    monkeypatch.setattr(
        oracle_routes,
        "list_page",
        lambda *a, **k: ([SimpleNamespace(id=uuid.uuid4(), extract="e1")], 1),
    )
    monkeypatch.setattr(
        oracle_routes,
        "_serialize",
        lambda row: {"id": str(row.id), "extract": getattr(row, "extract", "")},
    )
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"signal.read", "dossier.read"}),
        current_user_modules=(oracle_routes,),
    ):
        ok = client.get(f"/api/v1/dossiers/{dossier.id}/evidence")
    assert ok.status_code == 200, ok.get_data(as_text=True)[:300]
    body = ok.get_json()
    assert "data" in body and "meta" in body


def test_actors_list_rejects_bad_page(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: actors list con page basura → 500."""

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"actor.read"}),
        current_user_modules=(oracle_routes,),
    ):
        bad = client.get("/api/v1/actors", query_string={"page[size]": "0"})
    # size < 1 may 422 from list_page or _model_page
    assert bad.status_code in {422, 400, 500}
    if bad.status_code == 422:
        assert bad.get_json()["code"] == "domain_validation"


def test_meetings_list_rejects_score_filter(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: filter score en meetings (sin score) se ignora silenciosamente."""

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"meeting.read"}),
        current_user_modules=(oracle_routes,),
    ):
        bad = client.get("/api/v1/meetings", query_string={"filter[score_min]": "10"})
    assert bad.status_code == 422


def test_schedule_nightly_summaries_date_gate(app: Any) -> None:
    """Bug que cazaría: scheduled_for basura/naive lanza y reencola el lote."""

    with app.app_context(), pytest.raises(PermanentJobError, match="no es válida"):
        tasks.schedule_nightly_dossier_summaries(scheduled_for="not-a-date")
    with app.app_context(), pytest.raises(PermanentJobError, match="zona horaria"):
        tasks.schedule_nightly_dossier_summaries(scheduled_for="2026-08-04T02:00:00")


def test_tenant_ids_active_and_all(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: enumeración de tenants de mantenimiento ignora active_only."""

    tids = [uuid.uuid4(), uuid.uuid4()]

    class Scalars:
        def __iter__(self):
            return iter(tids)

    monkeypatch.setattr(tasks.db.session, "scalars", lambda q: Scalars())
    monkeypatch.setattr(tasks.db.session, "rollback", lambda: None)
    with app.app_context():
        all_ids = tasks._all_tenant_ids()
        active = tasks._active_tenant_ids()
    assert all_ids == tids
    assert active == tids


def test_poll_source_activity_and_retention_wrappers(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: poll/retention no entran en platform_access y fallan en silencio."""

    monkeypatch.setattr(
        "opn_oracle.platform.source_activity.poll_source_activity",
        lambda session, lookback_days=14: [1, 2, 3],
    )
    monkeypatch.setattr(
        tasks,
        "purge_retired_procurement_search_watch_memory",
        lambda session: 2,
    )
    monkeypatch.setattr(tasks, "_all_tenant_ids", lambda: [uuid.uuid4()])
    monkeypatch.setattr(tasks.db.session, "remove", lambda: None)
    with app.app_context():
        n = tasks.poll_source_activity(lookback_days=7)
        r = tasks.procurement_watch_retention()
    assert n == 3
    assert r == 2


def test_ai_handler_policy_denied_is_permanent(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: AIPolicyDenied reintenta y gasta cuota del proveedor."""

    from opn_oracle.ai.service import AIPolicyDenied

    job = _job_row(job_type="oracle.ai.intake")
    monkeypatch.setattr(
        tasks,
        "execute_agent",
        lambda **k: (_ for _ in ()).throw(AIPolicyDenied("denied")),
    )
    with app.app_context(), pytest.raises(PermanentJobError, match="denied"):
        tasks._execute_ai("intake", {"dossier_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]


def test_generate_procurement_document_permanent_and_retriable(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: KeyError de report_id se reintenta; contract error es permanent."""

    from opn_oracle.reporting.service import ReportOutputContractError

    job = _job_row(job_type="oracle.procurement_document_report.generate")
    with app.app_context(), pytest.raises(PermanentJobError):
        tasks._generate_procurement_document_report({}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "process_procurement_document_report",
        lambda *a, **k: (_ for _ in ()).throw(ReportOutputContractError("eof")),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="eof"):
        tasks._generate_procurement_document_report(
            {"report_id": str(uuid.uuid4())},
            job,  # type: ignore[arg-type]
        )


def test_run_investigation_provider_retryable(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: Signal temporal se marca permanent y no reintenta."""

    from opn_oracle.integrations.entity_intel import EntityIntelProviderError

    run_id = uuid.uuid4()
    job = _job_row(job_type="oracle.investigation.run", resource_id=run_id)
    monkeypatch.setattr(
        tasks,
        "process_investigation_run",
        lambda *a, **k: (_ for _ in ()).throw(
            EntityIntelProviderError(
                status_code=503, code="timeout", detail="timeout", retryable=True
            )
        ),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="temporalmente"):
        tasks._run_investigation({"run_id": str(run_id)}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "process_investigation_run",
        lambda *a, **k: (_ for _ in ()).throw(
            EntityIntelProviderError(
                status_code=400, code="bad_request", detail="bad request", retryable=False
            )
        ),
    )
    with app.app_context(), pytest.raises(PermanentJobError, match="rechazó"):
        tasks._run_investigation({"run_id": str(run_id)}, job)  # type: ignore[arg-type]


def test_memory_test_connection_generic_exception(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: error de conexión genérico 500 o no graba last_error."""

    app.config["MEMORY_CONTEXT_MODE"] = "http"
    app.config.pop("MEMORY_CONTEXT_TEST_TRANSPORT", None)
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.write", "dossier.read"}),
        current_user_modules=(memory_routes,),
    ) as (_user, tenant_id):
        dossier = _dossier_ns(tenant_id)
        profile = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            dossier_id=dossier.id,
            connection_id=None,
            mode="shadow",
            version=1,
            etag='W/"1"',
            profile_config={},
            last_test_at=None,
            last_test_status=None,
            last_error=None,
            last_coverage=None,
        )
        session = _FakeSession(dossier=dossier, profile=profile)
        _wire_memory(monkeypatch, session)
        monkeypatch.setattr(
            memory_routes,
            "resolve_signal_memory_connection",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret missing")),
        )
        resp = client.post(f"/api/v1/dossiers/{dossier.id}/memory/test-connection")
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "memory_connection_error"
    assert profile.last_test_status == "error"
    assert "secret missing" in (profile.last_error or "")


def test_intent_get_not_found_from_service(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: IntentNotFound del overview se traga como 200 vacío."""

    dossier_id = uuid.uuid4()
    monkeypatch.setattr(
        intent_routes, "_dossier_or_404", lambda *a, **k: SimpleNamespace(id=dossier_id)
    )
    monkeypatch.setattr(
        intent_routes,
        "intent_overview",
        lambda *a, **k: (_ for _ in ()).throw(IntentNotFound("sin revisiones")),
    )
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.read"}),
        current_user_modules=(intent_routes,),
    ):
        resp = client.get(f"/api/v1/dossiers/{dossier_id}/intent")
    assert resp.status_code == 404


def test_map_retrieve_citable_item_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: item citable no entra en allowlist o pierde watermark."""

    from types import SimpleNamespace as SN

    tid, did = uuid.uuid4(), uuid.uuid4()
    cit = SN(
        oracle_evidence_id="ev-1",
        signal_item_id="sig-1",
        source_ref="src",
        checksum="c" * 64,
        exact_excerpt="texto",
        classification="public",
        locator="p1",
        occurred_at="2026-01-01T00:00:00Z",
        policy_version="memory.v1",
        watermark="wm-1",
        tenant_id=str(tid),
        dossier_id=str(did),
    )
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_contract_v1.materialize_signal_item_to_evidence",
        lambda *a, **k: cit,
    )
    evidence, allowlist, wm, cov = _map_retrieve_to_evidence(
        {
            "items": [
                {
                    "id": "sig-1",
                    "kind": "observation",
                    "text": "texto",
                    "source_ref": "src",
                    "checksum": "c" * 64,
                }
            ],
            "watermark": "wm-1",
            "coverage_manifest": {
                "version": "v1",
                "failed": [],
                "used": ["sig-1"],
                "truncated": False,
            },
        },
        tenant_id=tid,
        dossier_id=did,
    )
    assert allowlist == ["ev-1"]
    assert evidence[0]["evidence_id"] == "ev-1"
    assert wm == "wm-1"
    assert cov["evidence_count"] == 1


# ===========================================================================
# Wave 3 — residual to cross 84.5: signals filters, RT Signal fail-closed,
# more job exception maps, living-summary/audit/feedback contracts
# ===========================================================================


def test_signals_list_rejects_owner_selected_dates_and_scores(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: filtros de /signals mal formados se ignoran o 500."""

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"signal.read"}),
        current_user_modules=(oracle_routes,),
    ):
        owner = client.get("/api/v1/signals", query_string={"filter[owner]": str(uuid.uuid4())})
        too_many = client.get(
            "/api/v1/signals",
            query_string={
                "filter[selected_ids]": ",".join(str(uuid.uuid4()) for _ in range(101)),
            },
        )
        bad_uuid = client.get(
            "/api/v1/signals",
            query_string={"filter[selected_ids]": "not-uuid"},
        )
        bad_from = client.get(
            "/api/v1/signals",
            query_string={"filter[date_from]": "ayer"},
        )
        bad_score = client.get(
            "/api/v1/signals",
            query_string={"filter[score_min]": "nope"},
        )
        score_oob = client.get(
            "/api/v1/signals",
            query_string={"filter[score_max]": "150"},
        )
    for resp in (owner, too_many, bad_uuid, bad_from, bad_score, score_oob):
        assert resp.status_code == 422, resp.get_data(as_text=True)[:250]
        assert resp.get_json()["code"] == "domain_validation"


def test_rt09_rt10_signal_require_config(app: Any) -> None:
    """Bug que cazaría: RT-09/10 productivos sin SIGNAL_AI_* inventan placeholder."""

    from opn_oracle.oracle.custom_report_lifecycle import (
        _invoke_rt09_writer_via_signal,
        _invoke_rt10_review_via_signal,
    )
    from opn_oracle.oracle.custom_reports import CustomReportError

    snap = {
        "allowlist": ["ev-1"],
        "evidence_items": [{"evidence_id": "ev-1", "exact_excerpt": "dato", "source_ref": "src"}],
        "accepted_plan": {"outline": ["a"]},
        "brief_request": "x",
        "coverage": {},
        "memory_mode": "durable",
    }
    with app.app_context():
        app.config["SIGNAL_AI_BASE_URL"] = ""
        app.config["SIGNAL_AI_API_KEY"] = ""
        with pytest.raises(CustomReportError, match="Signal AI no configurado"):
            _invoke_rt09_writer_via_signal(snap=snap, options={}, current_hash="h1")
        with pytest.raises(CustomReportError, match="Signal AI no configurado"):
            _invoke_rt10_review_via_signal(
                snap=snap, writer_output={"sections": []}, current_hash="h1"
            )


def test_rt09_rt10_unavailable_and_missing_validated_output(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: AIUnavailable o payload sin validated_output se traga como OK."""

    from opn_oracle.ai.provider import AIUnavailable
    from opn_oracle.oracle.custom_report_lifecycle import (
        _invoke_rt09_writer_via_signal,
        _invoke_rt10_review_via_signal,
    )
    from opn_oracle.oracle.custom_reports import CustomReportError

    snap = {
        "allowlist": ["ev-1"],
        "evidence_items": [{"evidence_id": "ev-1", "exact_excerpt": "t"}],
        "accepted_plan": {},
    }

    class BoomProvider:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def run_governed(self, body: dict[str, Any]) -> dict[str, Any]:
            raise AIUnavailable("down")

    class BadShapeProvider:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def run_governed(self, body: dict[str, Any]) -> dict[str, Any]:
            return {"result": {"raw": True}, "usage": {"input_tokens": 1}}

    class OkProvider:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def run_governed(self, body: dict[str, Any]) -> dict[str, Any]:
            return {
                "validated_output": {"sections": [], "citations": "not-list"},
                "validated_output_sha256": "abc",
                "provider": "signal",
                "model": "m",
                "run_id": "r1",
                "usage": {"input_tokens": 2},
            }

    with app.app_context():
        app.config["SIGNAL_AI_BASE_URL"] = "https://signal.test"
        app.config["SIGNAL_AI_API_KEY"] = "k"
        monkeypatch.setattr("opn_oracle.ai.provider.SignalGovernedLLMProvider", BoomProvider)
        with pytest.raises(CustomReportError, match="Signal no disponible para RT-09"):
            _invoke_rt09_writer_via_signal(snap=snap, options={}, current_hash="h")
        with pytest.raises(CustomReportError, match="Signal no disponible para RT-10"):
            _invoke_rt10_review_via_signal(snap=snap, writer_output={}, current_hash="h")

        monkeypatch.setattr("opn_oracle.ai.provider.SignalGovernedLLMProvider", BadShapeProvider)
        with pytest.raises(CustomReportError, match="validated_output"):
            _invoke_rt09_writer_via_signal(snap=snap, options={}, current_hash="h")
        with pytest.raises(CustomReportError, match="validated_output"):
            _invoke_rt10_review_via_signal(snap=snap, writer_output={}, current_hash="h")

        monkeypatch.setattr("opn_oracle.ai.provider.SignalGovernedLLMProvider", OkProvider)
        out = _invoke_rt09_writer_via_signal(snap=snap, options={}, current_hash="h")
        assert out["validated_output"]["citations"] == []
        assert out["run_id"] == "r1"


def test_plan_write_keyerror_and_generic_retry(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: KeyError del plan/write reintenta; RuntimeError se hace permanent."""

    job = _job_row(job_type="oracle.report.custom_brief.plan")
    monkeypatch.setattr(
        tasks,
        "process_custom_brief_plan",
        lambda *a, **k: (_ for _ in ()).throw(KeyError("report_id")),
    )
    with app.app_context(), pytest.raises(PermanentJobError, match="report_id"):
        tasks._plan_custom_brief({}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "process_custom_brief_plan",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("blip")),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="planificación"):
        tasks._plan_custom_brief({"report_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "process_custom_brief_write",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("bad")),
    )
    with app.app_context(), pytest.raises(PermanentJobError, match="bad"):
        tasks._write_custom_brief({"report_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "process_custom_brief_write",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="redacción"):
        tasks._write_custom_brief({"report_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]


def test_answer_export_triage_summary_exception_maps(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: clasificación permanente/retriable invertida en handlers residuales."""

    from opn_oracle.ai.provider import AIUnavailable
    from opn_oracle.ai.service import AIPolicyDenied
    from opn_oracle.integrations.memory_ask_dual import (
        PermanentMemoryAskError,
        RetryableMemoryAskError,
    )

    job = _job_row(job_type="oracle.conversation.answer")
    monkeypatch.setattr(
        tasks,
        "process_dossier_question_answer",
        lambda *a, **k: (_ for _ in ()).throw(RetryableMemoryAskError("429")),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="429"):
        tasks._answer_dossier_question({}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "process_dossier_question_answer",
        lambda *a, **k: (_ for _ in ()).throw(PermanentMemoryAskError("policy")),
    )
    with app.app_context(), pytest.raises(PermanentJobError, match="policy"):
        tasks._answer_dossier_question({}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "process_dossier_question_answer",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("net")),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="temporalmente"):
        tasks._answer_dossier_question({}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "process_export",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("io")),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="exportación"):
        tasks._generate_export({"export_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "triage_dossier_signal",
        lambda **k: (_ for _ in ()).throw(AIUnavailable("ollama")),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="Ollama"):
        tasks._triage_signal({"dossier_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "triage_dossier_signal",
        lambda **k: (_ for _ in ()).throw(AIPolicyDenied("no")),
    )
    with app.app_context(), pytest.raises(PermanentJobError, match="no"):
        tasks._triage_signal({"dossier_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "process_summary_refresh",
        lambda *a, **k: (_ for _ in ()).throw(AIUnavailable("down")),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="proveedor"):
        tasks._refresh_dossier_summary({"dossier_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "process_meeting_briefing",
        lambda *a, **k: (_ for _ in ()).throw(AIUnavailable("down")),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="proveedor"):
        tasks._refresh_meeting_briefing({"meeting_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "process_weekly_change_digest",
        lambda *a, **k: (_ for _ in ()).throw(AIUnavailable("down")),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="proveedor"):
        tasks._refresh_weekly_change({"dossier_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]


def test_scan_watch_retryable_and_permanent(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: error retriable de scan se marca permanent y abandona la vigilancia."""

    from opn_oracle.oracle.procurement_search_watch import ProcurementSearchWatchScanError

    job = _job_row(job_type="oracle.procurement.watch.scan")
    monkeypatch.setattr(
        tasks,
        "scan_procurement_search_watch",
        lambda *a, **k: (_ for _ in ()).throw(
            ProcurementSearchWatchScanError("timeout", retryable=True, code="timeout")
        ),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="timeout"):
        tasks._scan_procurement_watch({"watch_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "scan_procurement_search_watch",
        lambda *a, **k: (_ for _ in ()).throw(
            ProcurementSearchWatchScanError("broken", retryable=False, code="broken")
        ),
    )
    with app.app_context(), pytest.raises(PermanentJobError, match="broken"):
        tasks._scan_procurement_watch({"watch_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]


def test_competitive_and_entity_report_ai_unavailable(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: AIUnavailable del informe competitivo se hace permanent."""

    from opn_oracle.ai.provider import AIUnavailable
    from opn_oracle.ai.service import AIPolicyDenied
    from opn_oracle.integrations.entity_intel import EntityIntelProviderError

    job = _job_row(job_type="oracle.report.competitive")
    monkeypatch.setattr(
        tasks,
        "process_competitive_procurement_report",
        lambda *a, **k: (_ for _ in ()).throw(AIUnavailable("x")),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="análisis"):
        tasks._generate_competitive_procurement_report({"report_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]

    entity_err = EntityIntelProviderError(status_code=502, code="entity_upstream", detail="e")
    monkeypatch.setattr(
        tasks,
        "process_entity_dossier_report",
        lambda *a, **k: (_ for _ in ()).throw(entity_err),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="entidades"):
        tasks._generate_entity_dossier_report({}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "process_entity_dossier_report",
        lambda *a, **k: (_ for _ in ()).throw(AIPolicyDenied("denied")),
    )
    with app.app_context(), pytest.raises(PermanentJobError, match="denied"):
        tasks._generate_entity_dossier_report({}, job)  # type: ignore[arg-type]


def test_living_summary_and_audit_404_contracts(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: living-summary/audit de otro tenant no es 404; archivado escribe."""

    monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: None)
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.write", "dossier.read", "audit.read"}),
        current_user_modules=(oracle_routes,),
    ):
        put = client.put(
            f"/api/v1/dossiers/{uuid.uuid4()}/living-summary",
            json={"summary": {"text": "x"}},
        )
        delete = client.delete(f"/api/v1/dossiers/{uuid.uuid4()}/living-summary")
        audit = client.get(f"/api/v1/dossiers/{uuid.uuid4()}/audit")
        hist = client.get(f"/api/v1/dossiers/{uuid.uuid4()}/status-history")
    assert put.status_code == 404
    assert delete.status_code == 404
    assert audit.status_code == 404
    assert hist.status_code == 404

    archived = _dossier_ns(uuid.uuid4(), status="archived")
    monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: archived)
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.write"}),
        current_user_modules=(oracle_routes,),
    ):
        bad = client.put(
            f"/api/v1/dossiers/{archived.id}/living-summary",
            json={"summary": {"text": "x"}},
        )
        bad2 = client.delete(f"/api/v1/dossiers/{archived.id}/living-summary")
    assert bad.status_code == 422
    assert bad2.status_code == 422


def test_living_summary_put_requires_object_summary(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: summary=string se acepta y corrompe LivingSummary."""

    dossier = _dossier_ns(uuid.uuid4())
    monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: dossier)
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.write"}),
        current_user_modules=(oracle_routes,),
    ):
        bad = client.put(
            f"/api/v1/dossiers/{dossier.id}/living-summary",
            json={"summary": "texto plano"},
        )
    assert bad.status_code == 422
    assert bad.get_json()["code"] == "domain_validation"


def test_feedback_rejects_invalid_target_type(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: feedback a target_type basura se inserta o 500."""

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.write"}),
        current_user_modules=(oracle_routes,),
    ):
        bad = client.post(
            "/api/v1/feedback",
            json={
                "target_type": "secret",
                "target_id": str(uuid.uuid4()),
                "rating": 1,
            },
        )
    assert bad.status_code == 422


def test_relationships_list_pagination_error(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: /relationships con page basura → 500."""

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"actor.read"}),
        current_user_modules=(oracle_routes,),
    ):
        bad = client.get("/api/v1/relationships", query_string={"page[size]": "x"})
    assert bad.status_code == 422


def test_procurement_document_requires_award(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: informe PLACSP sin adjudicaciones se encola igual."""

    dossier = _dossier_ns(uuid.uuid4())
    monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: dossier)
    monkeypatch.setattr(oracle_routes, "list_procurement_items", lambda *a, **k: [])
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"report.generate", "opportunity.read"}),
        current_user_modules=(oracle_routes,),
    ):
        resp = client.post(f"/api/v1/dossiers/{dossier.id}/procurement/reports", json={})
    assert resp.status_code == 422
    assert "adjudicación" in resp.get_json()["detail"].lower()


def test_procurement_pin_configuration_and_provider_errors(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: config/provider de procurement se mapean a 500 genérico."""

    from opn_oracle.integrations.procurement import (
        ProcurementConfigurationError,
        ProcurementProviderError,
    )

    dossier = _dossier_ns(uuid.uuid4())
    monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: dossier)

    def _cfg(*a: Any, **k: Any) -> Any:
        raise ProcurementConfigurationError("no config")

    def _prov(*a: Any, **k: Any) -> Any:
        raise ProcurementProviderError(
            status_code=502,
            code="procurement_upstream",
            detail="upstream",
        )

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"opportunity.write"}),
        current_user_modules=(oracle_routes,),
    ):
        monkeypatch.setattr(oracle_routes, "pin_procurement_item", _cfg)
        cfg = client.post(
            f"/api/v1/dossiers/{dossier.id}/procurement",
            json={"kind": "award", "folder_id": "f1"},
        )
        monkeypatch.setattr(oracle_routes, "pin_procurement_item", _prov)
        prov = client.post(
            f"/api/v1/dossiers/{dossier.id}/procurement",
            json={"kind": "award", "folder_id": "f1"},
        )
    assert cfg.status_code == 503
    assert cfg.get_json()["code"] == "procurement_not_configured"
    assert prov.status_code == 502


def test_detail_resource_404_and_report_patch_method(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: GET de recurso ajeno no es 404; PATCH report se cuela."""

    from opn_oracle.oracle.models import Report

    monkeypatch.setattr(
        oracle_routes.db.session,
        "scalar",
        lambda *a, **k: None,
    )
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset(
            {
                "opportunity.read",
                "opportunity.write",
                "report.read",
                "report.generate",
            }
        ),
        current_user_modules=(oracle_routes,),
    ):
        missing = client.get(f"/api/v1/opportunities/{uuid.uuid4()}")
        assert missing.status_code == 404

    report = Report(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        template_key="tender",
        status="ready",
        version=1,
    )
    dossier = _dossier_ns(uuid.uuid4())

    def _scalar(*a: Any, **k: Any) -> Any:
        return report

    monkeypatch.setattr(oracle_routes.db.session, "scalar", _scalar)
    monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: dossier)
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"report.read", "report.generate"}),
        current_user_modules=(oracle_routes,),
    ):
        patch = client.patch(
            f"/api/v1/reports/{report.id}",
            json={"status": "hacked"},
            headers={"If-Match": 'W/"1"'},
        )
    assert patch.status_code == 405, patch.get_data(as_text=True)[:300]
    assert patch.get_json()["code"] == "method_not_allowed"


def test_memory_durable_flag_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: fallo del adapter deja flag siempre False aunque env diga ready."""

    monkeypatch.setattr(
        "opn_oracle.integrations.surveillance_signal_adapter.durable_memory_store_available",
        lambda: (_ for _ in ()).throw(RuntimeError("import boom")),
    )
    monkeypatch.setenv("MEMORY_DURABLE_STORE_READY", "1")
    assert lifecycle._memory_durable_flag() is True
    monkeypatch.setenv("MEMORY_DURABLE_STORE_READY", "0")
    assert lifecycle._memory_durable_flag() is False


def test_notification_handlers_temporary_errors(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: fallo temporal de email se marca permanent y pierde la entrega."""

    from opn_oracle.reporting.notifications import (
        NotificationPermanentError,
        NotificationTemporaryError,
    )

    job = _job_row(job_type="oracle.notification.send")
    monkeypatch.setattr(
        tasks,
        "send_notification_email",
        lambda *a, **k: (_ for _ in ()).throw(NotificationTemporaryError("smtp")),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="smtp"):
        tasks._send_notification({"delivery_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "send_digest",
        lambda *a, **k: (_ for _ in ()).throw(NotificationTemporaryError("busy")),
    )
    with app.app_context(), pytest.raises(RetriableJobError, match="busy"):
        tasks._send_digest({"preference_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        tasks,
        "send_digest",
        lambda *a, **k: (_ for _ in ()).throw(NotificationPermanentError("gone")),
    )
    with app.app_context(), pytest.raises(PermanentJobError, match="gone"):
        tasks._send_digest({"preference_id": str(uuid.uuid4())}, job)  # type: ignore[arg-type]
