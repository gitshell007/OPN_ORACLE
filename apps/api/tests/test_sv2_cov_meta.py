"""SV2-COV-META · residual routes.py (nested / M2M / procurement) to clear 84.5%.

Behavioral tests — each asserts a bug a user could hit (404 leak, write on
archived, bad actor_ids, procurement error mapping). Zero pragmas. No full-suite
measurement in this file's authoring path (suite runs once at turn end).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from flask import g

from opn_oracle.auth import permissions
from opn_oracle.oracle import routes as oracle_routes
from opn_oracle.oracle.models import (
    Briefing,
    Meeting,
    Opportunity,
    Task,
    Watchlist,
)
from opn_oracle.integrations.procurement import (
    ProcurementConfigurationError,
    ProcurementProviderError,
)
from opn_oracle.oracle.procurement_items import ProcurementItemError
from opn_oracle.oracle.service import DomainValidationError, ResourceNotFound
from opn_oracle.platform.models import User
from opn_oracle.reporting.service import ReportWorkflowError


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
        email="sv2-cov-meta@example.com",
        display_name="SV2 COV META",
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


def _dossier_ns(tenant_id: uuid.UUID, **overrides: Any) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "title": "Expediente meta",
        "status": "active",
        "version": 1,
        "current_intent_revision_id": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ===========================================================================
# nested — reports list special-case + create validation residual
# ===========================================================================


def test_nested_reports_list_filters_status_and_paginates(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: listado nested de informes ignora filter[status] o meta.total."""

    dossier_id = uuid.uuid4()
    report = SimpleNamespace(
        id=uuid.uuid4(),
        status="completed",
        template_key="tender",
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(
        oracle_routes, "_dossier_or_404", lambda *a, **k: _dossier_ns(uuid.uuid4(), id=dossier_id)
    )
    monkeypatch.setattr(oracle_routes.db.session, "scalars", lambda *a, **k: [report])
    monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: 1)
    monkeypatch.setattr(
        oracle_routes,
        "serialize_report",
        lambda row, **k: {"id": str(row.id), "status": row.status},
    )

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"report.read"}),
        current_user_modules=(oracle_routes,),
    ):
        ok = client.get(
            f"/api/v1/dossiers/{dossier_id}/reports",
            query_string={"filter[status]": "completed", "page[number]": "1", "page[size]": "10"},
        )
    assert ok.status_code == 200, ok.get_data(as_text=True)[:400]
    body = ok.get_json()
    assert body["meta"] == {"page": 1, "size": 10, "total": 1}
    assert body["data"][0]["status"] == "completed"


def test_nested_create_owner_must_be_active_member(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: owner_user_id ajeno se acepta en task nested create."""

    dossier_id = uuid.uuid4()
    monkeypatch.setattr(
        oracle_routes, "_dossier_or_404", lambda *a, **k: _dossier_ns(uuid.uuid4(), id=dossier_id)
    )
    monkeypatch.setattr(oracle_routes, "active_membership_exists", lambda *a, **k: False)
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"task.write", "task.read"}),
        current_user_modules=(oracle_routes,),
    ):
        bad = client.post(
            f"/api/v1/dossiers/{dossier_id}/tasks",
            json={"title": "Tarea", "owner_user_id": str(uuid.uuid4())},
        )
    assert bad.status_code == 422
    assert "owner_user_id" in bad.get_json()["detail"]


def test_nested_meeting_actor_ids_must_be_list_and_exist(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: actor_ids string o UUIDs fantasma crean reunión inconsistente."""

    dossier_id = uuid.uuid4()
    monkeypatch.setattr(
        oracle_routes, "_dossier_or_404", lambda *a, **k: _dossier_ns(uuid.uuid4(), id=dossier_id)
    )
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)
    monkeypatch.setattr(oracle_routes.db.session, "scalars", lambda *a, **k: [])

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"meeting.write", "meeting.read"}),
        current_user_modules=(oracle_routes,),
    ):
        not_list = client.post(
            f"/api/v1/dossiers/{dossier_id}/meetings",
            json={"title": "Kickoff", "actor_ids": "not-a-list"},
        )
        missing_actors = client.post(
            f"/api/v1/dossiers/{dossier_id}/meetings",
            json={"title": "Kickoff", "actor_ids": [str(uuid.uuid4())]},
        )
    assert not_list.status_code == 422
    assert "lista" in not_list.get_json()["detail"].lower()
    assert missing_actors.status_code == 422
    assert "participantes" in missing_actors.get_json()["detail"].lower()


# ===========================================================================
# procurement residual — 404s, error mapping, report success
# ===========================================================================


def test_procurement_404_when_dossier_missing(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: pin/list/report/delete/refresh/promote en dossier fantasma → 500."""

    dossier_id = uuid.uuid4()
    item_id = uuid.uuid4()
    monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: None)
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"opportunity.write", "opportunity.read", "report.generate"}),
        current_user_modules=(oracle_routes,),
    ):
        pin = client.post(
            f"/api/v1/dossiers/{dossier_id}/procurement",
            json={"kind": "award", "folder_id": "f1"},
        )
        listed = client.get(f"/api/v1/dossiers/{dossier_id}/procurement")
        report = client.post(
            f"/api/v1/dossiers/{dossier_id}/procurement/reports",
            json={},
            headers={"Idempotency-Key": "k1"},
        )
        deleted = client.delete(f"/api/v1/dossiers/{dossier_id}/procurement/{item_id}")
        refreshed = client.post(f"/api/v1/dossiers/{dossier_id}/procurement/{item_id}/refresh")
        promoted = client.post(
            f"/api/v1/dossiers/{dossier_id}/procurement/{item_id}/promote",
            json={},
            headers={"Idempotency-Key": "k2"},
        )
    for resp in (pin, listed, report, deleted, refreshed, promoted):
        assert resp.status_code == 404, resp.get_data(as_text=True)[:200]
        assert resp.get_json()["code"] == "not_found"


def test_procurement_pin_maps_domain_and_config_errors(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: pin con kind inválido o Signal caído → 500 sin mapear."""

    dossier_id = uuid.uuid4()
    active = _dossier_ns(uuid.uuid4(), id=dossier_id)
    monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: active)
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)
    monkeypatch.setattr(oracle_routes.db.session, "commit", lambda: None)

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"opportunity.write"}),
        current_user_modules=(oracle_routes,),
    ):
        monkeypatch.setattr(
            oracle_routes,
            "pin_procurement_item",
            lambda *a, **k: (_ for _ in ()).throw(ProcurementItemError("kind inválido")),
        )
        bad_kind = client.post(
            f"/api/v1/dossiers/{dossier_id}/procurement",
            json={"kind": "???", "folder_id": "f"},
        )
        monkeypatch.setattr(
            oracle_routes,
            "pin_procurement_item",
            lambda *a, **k: (_ for _ in ()).throw(
                ProcurementConfigurationError("Signal no configurado")
            ),
        )
        unconfigured = client.post(
            f"/api/v1/dossiers/{dossier_id}/procurement",
            json={"kind": "award", "folder_id": "f"},
        )
        monkeypatch.setattr(
            oracle_routes,
            "pin_procurement_item",
            lambda *a, **k: (_ for _ in ()).throw(
                ProcurementProviderError(502, "signal_upstream", "upstream")
            ),
        )
        upstream = client.post(
            f"/api/v1/dossiers/{dossier_id}/procurement",
            json={"kind": "award", "folder_id": "f"},
        )
    assert bad_kind.status_code == 422
    assert unconfigured.status_code == 503
    assert unconfigured.get_json()["code"] == "procurement_not_configured"
    assert upstream.status_code == 502
    assert upstream.get_json()["code"] == "signal_upstream"


def test_procurement_refresh_maps_domain_config_provider(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: refresh con error de negocio/config se reintenta como 500."""

    dossier_id = uuid.uuid4()
    item_id = uuid.uuid4()
    monkeypatch.setattr(
        oracle_routes, "_dossier_or_404", lambda *a, **k: _dossier_ns(uuid.uuid4(), id=dossier_id)
    )
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)
    monkeypatch.setattr(oracle_routes.db.session, "commit", lambda: None)

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"opportunity.write"}),
        current_user_modules=(oracle_routes,),
    ):
        monkeypatch.setattr(
            oracle_routes,
            "refresh_procurement_item",
            lambda *a, **k: (_ for _ in ()).throw(ProcurementItemError("snapshot corrupto")),
        )
        domain = client.post(f"/api/v1/dossiers/{dossier_id}/procurement/{item_id}/refresh")
        monkeypatch.setattr(
            oracle_routes,
            "refresh_procurement_item",
            lambda *a, **k: (_ for _ in ()).throw(ProcurementConfigurationError("no cfg")),
        )
        cfg = client.post(f"/api/v1/dossiers/{dossier_id}/procurement/{item_id}/refresh")
        monkeypatch.setattr(
            oracle_routes,
            "refresh_procurement_item",
            lambda *a, **k: (_ for _ in ()).throw(
                ProcurementProviderError(503, "signal_timeout", "timeout")
            ),
        )
        provider = client.post(f"/api/v1/dossiers/{dossier_id}/procurement/{item_id}/refresh")
        item = SimpleNamespace(id=item_id, kind="award", folder_id="f1")
        monkeypatch.setattr(
            oracle_routes,
            "refresh_procurement_item",
            lambda *a, **k: (item, {"evidence_created": False}),
        )
        monkeypatch.setattr(
            oracle_routes,
            "serialize_procurement_item",
            lambda i: {"id": str(i.id), "kind": i.kind},
        )
        ok = client.post(f"/api/v1/dossiers/{dossier_id}/procurement/{item_id}/refresh")
    assert domain.status_code == 422
    assert cfg.status_code == 503
    assert provider.status_code == 503
    assert ok.status_code == 200, ok.get_data(as_text=True)[:300]
    assert ok.get_json()["refresh"]["evidence_created"] is False


def test_procurement_document_report_success_and_workflow_error(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: informe con awards no encola job; ReportWorkflowError → 500."""

    dossier_id = uuid.uuid4()
    award = SimpleNamespace(id=uuid.uuid4(), kind="award", folder_id="a1")
    monkeypatch.setattr(
        oracle_routes, "_dossier_or_404", lambda *a, **k: _dossier_ns(uuid.uuid4(), id=dossier_id)
    )
    monkeypatch.setattr(oracle_routes, "list_procurement_items", lambda *a, **k: [award])
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)

    report = SimpleNamespace(id=uuid.uuid4(), status="pending")
    job = SimpleNamespace(id=uuid.uuid4())
    monkeypatch.setattr(
        oracle_routes,
        "serialize_report",
        lambda r, **k: {"id": str(r.id), "status": r.status},
    )

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"report.generate"}),
        current_user_modules=(oracle_routes,),
    ):
        monkeypatch.setattr(
            oracle_routes,
            "create_report_request",
            lambda *a, **k: (report, job, True),
        )
        ok = client.post(
            f"/api/v1/dossiers/{dossier_id}/procurement/reports",
            json={"options": {"depth": "full"}},
            headers={"Idempotency-Key": "rep-ok"},
        )
        monkeypatch.setattr(
            oracle_routes,
            "create_report_request",
            lambda *a, **k: (_ for _ in ()).throw(ReportWorkflowError("plantilla")),
        )
        bad = client.post(
            f"/api/v1/dossiers/{dossier_id}/procurement/reports",
            json={},
            headers={"Idempotency-Key": "rep-bad"},
        )
    assert ok.status_code == 202, ok.get_data(as_text=True)[:400]
    body = ok.get_json()
    assert body["job_id"] == str(job.id)
    assert body["replayed"] is False
    assert body["report"]["status"] == "pending"
    assert bad.status_code == 422


# ===========================================================================
# monitors / briefings / evidence — fail-closed residual
# ===========================================================================


def test_monitor_create_and_list_missing_watchlist(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: monitor sobre watchlist fantasma o archivada → 500."""

    watchlist_id = uuid.uuid4()
    monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: None)
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"signal.review", "signal.read"}),
        current_user_modules=(oracle_routes,),
    ):
        missing = client.post(
            f"/api/v1/watchlists/{watchlist_id}/monitors",
            json={"provider": "signal"},
        )
        listed = client.get(f"/api/v1/watchlists/{watchlist_id}/monitors")

    # watchlist exists but dossier archived
    wl = Watchlist(
        id=watchlist_id,
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        name="WL",
        status="active",
        version=1,
    )
    monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: wl)
    monkeypatch.setattr(
        oracle_routes,
        "_dossier_or_404",
        lambda *a, **k: _dossier_ns(uuid.uuid4(), status="archived"),
    )
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"signal.review", "signal.read"}),
        current_user_modules=(oracle_routes,),
    ):
        archived = client.post(
            f"/api/v1/watchlists/{watchlist_id}/monitors",
            json={"provider": "signal"},
        )
        no_provider = client.post(
            f"/api/v1/watchlists/{watchlist_id}/monitors",
            json={},
        )
    # restore active dossier for provider-required path
    monkeypatch.setattr(
        oracle_routes, "_dossier_or_404", lambda *a, **k: _dossier_ns(uuid.uuid4())
    )
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"signal.review"}),
        current_user_modules=(oracle_routes,),
    ):
        no_provider = client.post(
            f"/api/v1/watchlists/{watchlist_id}/monitors",
            json={},
        )
    assert missing.status_code == 404
    assert listed.status_code == 404
    assert archived.status_code == 422
    assert "archivado" in archived.get_json()["detail"].lower()
    assert no_provider.status_code == 422
    assert "provider" in no_provider.get_json()["detail"].lower()


def test_briefing_create_list_state_missing_meeting(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: briefing sobre reunión inexistente o archivada no es 404/422."""

    meeting_id = uuid.uuid4()
    monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: None)
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"meeting.write", "meeting.read"}),
        current_user_modules=(oracle_routes,),
    ):
        create_miss = client.post(f"/api/v1/meetings/{meeting_id}/briefings", json={})
        list_miss = client.get(f"/api/v1/meetings/{meeting_id}/briefings")
        state_miss = client.get(f"/api/v1/meetings/{meeting_id}/briefing-state")

    meeting = Meeting(
        id=meeting_id,
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        title="Sync",
        status="planned",
        version=1,
    )
    monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: meeting)
    monkeypatch.setattr(
        oracle_routes,
        "_dossier_or_404",
        lambda *a, **k: _dossier_ns(uuid.uuid4(), status="archived"),
    )
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"meeting.write", "meeting.read"}),
        current_user_modules=(oracle_routes,),
    ):
        archived = client.post(f"/api/v1/meetings/{meeting_id}/briefings", json={})
        # list/state with dossier gone
        monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: None)
        list_no_dossier = client.get(f"/api/v1/meetings/{meeting_id}/briefings")
        state_no_dossier = client.get(f"/api/v1/meetings/{meeting_id}/briefing-state")
        # create maps ValueError from enqueue
        monkeypatch.setattr(
            oracle_routes, "_dossier_or_404", lambda *a, **k: _dossier_ns(uuid.uuid4())
        )
        monkeypatch.setattr(
            oracle_routes,
            "enqueue_meeting_briefing",
            lambda *a, **k: (_ for _ in ()).throw(ValueError("sin plantilla")),
        )
        create_err = client.post(f"/api/v1/meetings/{meeting_id}/briefings", json={})

    assert create_miss.status_code == 404
    assert list_miss.status_code == 404
    assert state_miss.status_code == 404
    assert archived.status_code == 422
    assert list_no_dossier.status_code == 404
    assert state_no_dossier.status_code == 404
    assert create_err.status_code == 422


def test_evidence_create_requires_signal_dossier_extract(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: evidence sin signal/dossier/extract se crea o 500."""

    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.write"}),
        current_user_modules=(oracle_routes,),
    ):
        no_signal = client.post("/api/v1/evidence", json={"extract": "x"})
        no_dossier = client.post(
            "/api/v1/evidence",
            json={"signal_id": str(uuid.uuid4()), "extract": "x"},
        )
        monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: None)
        missing_dossier = client.post(
            "/api/v1/evidence",
            json={
                "signal_id": str(uuid.uuid4()),
                "dossier_id": str(uuid.uuid4()),
                "extract": "texto",
            },
        )
        monkeypatch.setattr(
            oracle_routes,
            "_dossier_or_404",
            lambda *a, **k: _dossier_ns(uuid.uuid4(), status="archived"),
        )
        archived = client.post(
            "/api/v1/evidence",
            json={
                "signal_id": str(uuid.uuid4()),
                "dossier_id": str(uuid.uuid4()),
                "extract": "texto",
            },
        )
        monkeypatch.setattr(
            oracle_routes, "_dossier_or_404", lambda *a, **k: _dossier_ns(uuid.uuid4())
        )
        monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: None)
        no_link = client.post(
            "/api/v1/evidence",
            json={
                "signal_id": str(uuid.uuid4()),
                "dossier_id": str(uuid.uuid4()),
                "extract": "texto",
            },
        )
        monkeypatch.setattr(
            oracle_routes.db.session,
            "scalar",
            lambda *a, **k: SimpleNamespace(id=uuid.uuid4()),
        )
        empty_extract = client.post(
            "/api/v1/evidence",
            json={
                "signal_id": str(uuid.uuid4()),
                "dossier_id": str(uuid.uuid4()),
                "extract": "",
            },
        )
    for resp, needle in (
        (no_signal, "signal_id"),
        (no_dossier, "dossier_id"),
        (missing_dossier, "no encontrado"),
        (archived, "archivado"),
        (no_link, "no encontrado"),
        (empty_extract, "extract"),
    ):
        assert resp.status_code in {404, 422}, resp.get_data(as_text=True)[:200]
        detail = resp.get_json()["detail"].lower()
        assert needle.lower() in detail or "encontrado" in detail


def test_evidence_list_404_and_domain_error(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: evidence list en dossier ajeno 200; page basura 500."""

    dossier_id = uuid.uuid4()
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"signal.read"}),
        current_user_modules=(oracle_routes,),
    ):
        monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: None)
        missing = client.get(f"/api/v1/dossiers/{dossier_id}/evidence")
        monkeypatch.setattr(
            oracle_routes, "_dossier_or_404", lambda *a, **k: _dossier_ns(uuid.uuid4())
        )
        bad_page = client.get(
            f"/api/v1/dossiers/{dossier_id}/evidence",
            query_string={"page[number]": "x"},
        )
    assert missing.status_code == 404
    assert bad_page.status_code == 422


# ===========================================================================
# detail / delete residual — monitors, briefings, evidence access
# ===========================================================================


def test_detail_resolves_briefing_via_meeting_dossier(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: GET briefing sin dossier accesible filtra mal o 500."""

    meeting = Meeting(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        title="M",
        status="planned",
        version=1,
    )
    briefing = Briefing(
        id=uuid.uuid4(),
        tenant_id=meeting.tenant_id,
        meeting_id=meeting.id,
        version=1,
        content={"summary": "ok"},
    )

    def _get(_model: Any, key: Any) -> Any:
        if key == meeting.id:
            return meeting
        return None

    monkeypatch.setattr(oracle_routes.db.session, "get", _get)
    monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: briefing)
    monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: None)
    monkeypatch.setattr(
        oracle_routes,
        "_serialize",
        lambda row: {"id": str(row.id), "kind": type(row).__name__},
    )

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"meeting.read"}),
        current_user_modules=(oracle_routes,),
    ):
        forbidden = client.get(f"/api/v1/briefings/{briefing.id}")
    assert forbidden.status_code == 404

    monkeypatch.setattr(
        oracle_routes, "_dossier_or_404", lambda *a, **k: _dossier_ns(uuid.uuid4())
    )
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"meeting.read"}),
        current_user_modules=(oracle_routes,),
    ):
        ok = client.get(f"/api/v1/briefings/{briefing.id}")
    assert ok.status_code == 200, ok.get_data(as_text=True)[:300]
    assert ok.get_json()["kind"] == "Briefing"


def test_detail_delete_missing_and_archived(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: DELETE task inexistente 500; DELETE en archivado borra igual."""

    monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: None)
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"task.write", "task.read"}),
        current_user_modules=(oracle_routes,),
    ):
        missing = client.delete(f"/api/v1/tasks/{uuid.uuid4()}")
    assert missing.status_code == 404

    task = Task(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        title="T",
        status="open",
        version=1,
    )
    monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: task)
    monkeypatch.setattr(
        oracle_routes,
        "_dossier_or_404",
        lambda *a, **k: _dossier_ns(uuid.uuid4(), status="archived"),
    )
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"task.write"}),
        current_user_modules=(oracle_routes,),
    ):
        archived = client.delete(f"/api/v1/tasks/{task.id}")
    assert archived.status_code == 422
    assert "archivado" in archived.get_json()["detail"].lower()


def test_detail_patch_archived_and_dossier_actor_error(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: PATCH en archivado muta; DossierActor DomainValidation → 500."""

    task = Task(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        title="T",
        status="open",
        version=1,
    )
    monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: task)
    monkeypatch.setattr(
        oracle_routes,
        "_dossier_or_404",
        lambda *a, **k: _dossier_ns(uuid.uuid4(), status="archived"),
    )
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"task.write", "task.read"}),
        current_user_modules=(oracle_routes,),
    ):
        archived = client.patch(
            f"/api/v1/tasks/{task.id}",
            json={"title": "hack"},
            headers={"If-Match": 'W/"1"'},
        )
    assert archived.status_code == 422

    # Opportunity update error mapping already covered; DossierActor path
    from opn_oracle.oracle.models import DossierActor

    da = DossierActor(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        version=1,
    )
    monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: da)
    monkeypatch.setattr(
        oracle_routes, "_dossier_or_404", lambda *a, **k: _dossier_ns(uuid.uuid4())
    )
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)
    monkeypatch.setattr(
        oracle_routes,
        "update_dossier_actor",
        lambda *a, **k: (_ for _ in ()).throw(DomainValidationError("rol inválido")),
    )
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"actor.write", "actor.read"}),
        current_user_modules=(oracle_routes,),
    ):
        bad = client.patch(
            f"/api/v1/dossier-actors/{da.id}",
            json={"roles": ["x"]},
            headers={"If-Match": 'W/"1"'},
        )
    assert bad.status_code == 422
    assert "rol" in bad.get_json()["detail"].lower()


# ===========================================================================
# M2M residual — parent missing, archived, target missing, delete missing link
# ===========================================================================


def test_m2m_list_and_mutate_fail_closed(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: M2M en parent fantasma, archivado o target missing no es 404/422."""

    opp_id = uuid.uuid4()
    target_id = uuid.uuid4()
    monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: None)
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)
    monkeypatch.setattr(oracle_routes.db.session, "commit", lambda: None)

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"opportunity.read", "opportunity.write"}),
        current_user_modules=(oracle_routes,),
    ):
        list_miss = client.get(f"/api/v1/opportunities/{opp_id}/actors")
        put_miss = client.put(f"/api/v1/opportunities/{opp_id}/actors/{target_id}")

    opp = Opportunity(
        id=opp_id,
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        title="Opp",
        status="identified",
        version=1,
    )
    # parent found, dossier archived on write
    monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: opp)
    monkeypatch.setattr(
        oracle_routes,
        "_dossier_or_404",
        lambda *a, **k: _dossier_ns(uuid.uuid4(), status="archived"),
    )
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"opportunity.write", "opportunity.read"}),
        current_user_modules=(oracle_routes,),
    ):
        put_arch = client.put(f"/api/v1/opportunities/{opp_id}/actors/{target_id}")

    # parent found, active dossier, target missing
    monkeypatch.setattr(
        oracle_routes, "_dossier_or_404", lambda *a, **k: _dossier_ns(uuid.uuid4())
    )

    def _scalar_parent_only(*_a: Any, **_k: Any) -> Any:
        # first call: parent; second: target
        return opp

    calls: list[str] = []

    def _scalar_seq(*_a: Any, **_k: Any) -> Any:
        calls.append("s")
        if len(calls) == 1:
            return opp
        return None  # target missing

    monkeypatch.setattr(oracle_routes.db.session, "scalar", _scalar_seq)
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"opportunity.write"}),
        current_user_modules=(oracle_routes,),
    ):
        put_no_target = client.put(f"/api/v1/opportunities/{opp_id}/actors/{target_id}")

    # delete missing link
    calls.clear()
    actor = SimpleNamespace(id=target_id)

    def _scalar_with_target(*_a: Any, **_k: Any) -> Any:
        calls.append("s")
        if len(calls) == 1:
            return opp
        return actor

    monkeypatch.setattr(oracle_routes.db.session, "scalar", _scalar_with_target)
    monkeypatch.setattr(oracle_routes.db.session, "get", lambda *a, **k: None)
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"opportunity.write"}),
        current_user_modules=(oracle_routes,),
    ):
        del_missing = client.delete(f"/api/v1/opportunities/{opp_id}/actors/{target_id}")

    assert list_miss.status_code == 404
    assert put_miss.status_code == 404
    assert put_arch.status_code == 422
    assert "archivado" in put_arch.get_json()["detail"].lower()
    assert put_no_target.status_code == 404
    assert del_missing.status_code == 404


def test_m2m_put_links_when_missing(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: PUT M2M no crea vínculo o no audit trail (commit sin linked)."""

    opp_id = uuid.uuid4()
    target_id = uuid.uuid4()
    opp = Opportunity(
        id=opp_id,
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        title="Opp",
        status="identified",
        version=1,
    )
    actor = SimpleNamespace(id=target_id)
    calls: list[str] = []

    def _scalar(*_a: Any, **_k: Any) -> Any:
        calls.append("s")
        return opp if len(calls) == 1 else actor

    added: list[Any] = []
    monkeypatch.setattr(oracle_routes.db.session, "scalar", _scalar)
    monkeypatch.setattr(oracle_routes.db.session, "get", lambda *a, **k: None)
    monkeypatch.setattr(oracle_routes.db.session, "add", lambda obj: added.append(obj))
    monkeypatch.setattr(oracle_routes.db.session, "commit", lambda: None)
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)
    monkeypatch.setattr(
        oracle_routes, "_dossier_or_404", lambda *a, **k: _dossier_ns(uuid.uuid4())
    )
    monkeypatch.setattr(oracle_routes, "append_audit_event", lambda *a, **k: None)

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"opportunity.write"}),
        current_user_modules=(oracle_routes,),
    ):
        linked = client.put(f"/api/v1/opportunities/{opp_id}/actors/{target_id}")
    assert linked.status_code == 200, linked.get_data(as_text=True)[:300]
    assert linked.get_json()["linked"] is True
    assert len(added) == 1


# ===========================================================================
# collaborators / summaries residual 404s
# ===========================================================================


def test_collaborators_list_put_delete_404(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: collaborators en dossier no gestionable no es 404."""

    dossier_id = uuid.uuid4()
    user_id = uuid.uuid4()
    monkeypatch.setattr(oracle_routes, "_dossier_manage_or_404", lambda *a, **k: None)

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.read", "dossier.write"}),
        current_user_modules=(oracle_routes,),
    ):
        listed = client.get(f"/api/v1/dossiers/{dossier_id}/collaborators")
        put = client.put(
            f"/api/v1/dossiers/{dossier_id}/collaborators/{user_id}",
            json={"role": "viewer"},
        )
        deleted = client.delete(f"/api/v1/dossiers/{dossier_id}/collaborators/{user_id}")
    assert listed.status_code == 404
    assert put.status_code == 404
    assert deleted.status_code == 404

    # delete when collaborator row missing
    monkeypatch.setattr(
        oracle_routes, "_dossier_manage_or_404", lambda *a, **k: _dossier_ns(uuid.uuid4())
    )
    monkeypatch.setattr(oracle_routes.db.session, "get", lambda *a, **k: None)
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"dossier.write"}),
        current_user_modules=(oracle_routes,),
    ):
        del_row = client.delete(f"/api/v1/dossiers/{dossier_id}/collaborators/{user_id}")
    assert del_row.status_code == 404


def test_living_and_oracle_summary_404_paths(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: summaries en dossier inexistente devuelven 200 vacío."""

    dossier_id = uuid.uuid4()
    version_id = uuid.uuid4()
    monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: None)
    monkeypatch.setattr(oracle_routes.db.session, "rollback", lambda: None)

    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset(
            {
                "dossier.read",
                "dossier.write",
                "ai.execute",
                "audit.read",
            }
        ),
        current_user_modules=(oracle_routes,),
    ):
        living = client.get(f"/api/v1/dossiers/{dossier_id}/living-summary")
        oracle = client.get(f"/api/v1/dossiers/{dossier_id}/oracle-summary")
        refresh = client.post(
            f"/api/v1/dossiers/{dossier_id}/oracle-summary/refresh",
            json={},
            headers={"Idempotency-Key": "refresh-01"},
        )
        versions = client.get(f"/api/v1/dossiers/{dossier_id}/oracle-summary/versions")
        version = client.get(
            f"/api/v1/dossiers/{dossier_id}/oracle-summary/versions/{version_id}"
        )
        feedback = client.post(
            f"/api/v1/dossiers/{dossier_id}/oracle-summary/{version_id}/feedback",
            json={"rating": 1},
        )
        put_living = client.put(
            f"/api/v1/dossiers/{dossier_id}/living-summary",
            json={"summary": {"text": "x"}},
        )
        del_living = client.delete(f"/api/v1/dossiers/{dossier_id}/living-summary")
        audit = client.get(f"/api/v1/dossiers/{dossier_id}/audit")
        history = client.get(f"/api/v1/dossiers/{dossier_id}/status-history")
        feedback_list = client.get(f"/api/v1/dossiers/{dossier_id}/feedback")
    for resp in (
        living,
        oracle,
        refresh,
        versions,
        version,
        feedback,
        put_living,
        del_living,
        audit,
        history,
        feedback_list,
    ):
        assert resp.status_code == 404, resp.get_data(as_text=True)[:200]


def test_signal_get_missing_and_inaccessible(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug que cazaría: signal de otro tenant se filtra por id global."""

    signal_id = uuid.uuid4()
    monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: None)
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"signal.read"}),
        current_user_modules=(oracle_routes,),
    ):
        missing = client.get(f"/api/v1/signals/{signal_id}")
    assert missing.status_code == 404

    row = SimpleNamespace(id=signal_id, title="S")
    monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: row)
    monkeypatch.setattr(oracle_routes, "_accessible_signal_dossier", lambda *a, **k: None)
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"signal.read"}),
        current_user_modules=(oracle_routes,),
    ):
        inaccessible = client.get(f"/api/v1/signals/{signal_id}")
    assert inaccessible.status_code == 404


def test_parse_datetime_naive_and_date_helpers() -> None:
    """Bug que cazaría: datetime naive o date object no se normaliza a UTC."""

    from datetime import date

    naive = oracle_routes._parse_datetime_value("2026-08-04T10:00:00")
    assert naive is not None and naive.tzinfo is not None
    assert oracle_routes._parse_datetime_value("") is None
    assert oracle_routes._parse_date_value(date(2026, 8, 4)) == date(2026, 8, 4)
    assert oracle_routes._parse_date_value(datetime(2026, 8, 4, 12, 0, tzinfo=UTC)) == date(
        2026, 8, 4
    )


def test_m2m_parent_helper_direct(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug que cazaría: _m2m_parent no eleva ResourceNotFound / archived en write."""

    monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: None)
    with app.app_context(), pytest.raises(ResourceNotFound):
        oracle_routes._m2m_parent("opportunities", uuid.uuid4(), write=False)

    opp = Opportunity(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        title="O",
        status="identified",
        version=1,
    )
    monkeypatch.setattr(oracle_routes.db.session, "scalar", lambda *a, **k: opp)
    monkeypatch.setattr(oracle_routes, "_dossier_or_404", lambda *a, **k: None)
    with app.app_context(), pytest.raises(ResourceNotFound):
        oracle_routes._m2m_parent("opportunities", opp.id, write=True)

    monkeypatch.setattr(
        oracle_routes,
        "_dossier_or_404",
        lambda *a, **k: _dossier_ns(uuid.uuid4(), status="archived"),
    )
    with app.app_context(), pytest.raises(DomainValidationError, match="archivado"):
        oracle_routes._m2m_parent("opportunities", opp.id, write=True)
