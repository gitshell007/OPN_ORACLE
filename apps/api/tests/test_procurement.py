from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
import pytest
from flask import g
from flask_login import login_user

from opn_oracle.auth import permissions
from opn_oracle.integrations import procurement, procurement_routes
from opn_oracle.integrations.procurement import (
    ProcurementClient,
    ProcurementProviderError,
    cached_awards,
    cached_suggest,
)
from opn_oracle.oracle import procurement_items
from opn_oracle.oracle import routes as oracle_routes
from opn_oracle.platform.models import User


@pytest.mark.unit
def test_procurement_awards_calls_global_registry_without_tenant_header() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params.multi_items())
        seen["api_key"] = request.headers.get("X-API-Key")
        seen["external_tenant"] = request.headers.get("X-OPN-External-Tenant-ID")
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={
                "total": 1,
                "items": [{"winner": "Genesis Consulting SLP", "is_ute": True}],
            },
        )

    client = ProcurementClient(
        base_url="https://signal.example",
        api_key="test-secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(handler),
    )
    try:
        payload = client.awards(company="Genesis", buyer=None, limit=5, offset=0)
    finally:
        client.close()

    assert seen == {
        "method": "GET",
        "path": "/api/v1/registry/awards",
        "params": {"company": "Genesis", "limit": "5", "offset": "0"},
        "api_key": "test-secret",
        "external_tenant": None,
    }
    assert payload["total"] == 1
    assert payload["items"][0]["winner"] == "Genesis Consulting SLP"
    assert payload["items"][0]["is_ute"] is True


@pytest.mark.unit
def test_procurement_suggest_calls_global_registry_without_tenant_header() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params.multi_items())
        seen["external_tenant"] = request.headers.get("X-OPN-External-Tenant-ID")
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={
                "kind": "winner",
                "suggestions": ["GENESIS CONSULTING SLP", "GENESIS BIOMED SL"],
            },
        )

    client = ProcurementClient(
        base_url="https://signal.example",
        api_key="test-secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(handler),
    )
    try:
        payload = client.suggest(query="Genesis", kind="winner", limit=8)
    finally:
        client.close()

    assert seen == {
        "method": "GET",
        "path": "/api/v1/registry/suggest",
        "params": {"q": "Genesis", "kind": "winner", "limit": "8"},
        "external_tenant": None,
    }
    assert payload["suggestions"] == ["GENESIS CONSULTING SLP", "GENESIS BIOMED SL"]
    assert payload["cached_seconds"] == procurement.PROCUREMENT_SUGGEST_CACHE_TTL_SECONDS


@pytest.mark.unit
def test_procurement_tender_searches_send_external_tenant_header() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "method": request.method,
                "path": request.url.path,
                "external_tenant": request.headers.get("X-OPN-External-Tenant-ID"),
                "body": request.read().decode(),
            }
        )
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={"ok": True, "items": []},
        )

    client = ProcurementClient(
        base_url="https://signal.example",
        api_key="test-secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(handler),
    )
    try:
        assert client.list_searches(external_tenant_id="tenant-signal")["ok"] is True
        assert (
            client.create_search(
                payload={"name": "Radar energía", "keywords": ["energia"], "filters": {}},
                external_tenant_id="tenant-signal",
            )["ok"]
            is True
        )
        assert (
            client.run_search(
                search_id="search-1",
                limit=10,
                offset=20,
                external_tenant_id="tenant-signal",
            )["ok"]
            is True
        )
    finally:
        client.close()

    assert seen[0] == {
        "method": "GET",
        "path": "/api/v1/oracle/tender-searches",
        "external_tenant": "tenant-signal",
        "body": "",
    }
    assert seen[1]["method"] == "POST"
    assert seen[1]["path"] == "/api/v1/oracle/tender-searches"
    assert seen[1]["external_tenant"] == "tenant-signal"
    assert '"keywords":["energia"]' in seen[1]["body"].replace(" ", "")
    assert seen[2] == {
        "method": "GET",
        "path": "/api/v1/oracle/tender-searches/search-1/run",
        "external_tenant": "tenant-signal",
        "body": "",
    }


@pytest.mark.unit
def test_procurement_summary_uses_post_without_tenant_header() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["external_tenant"] = request.headers.get("X-OPN-External-Tenant-ID")
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={"cached": False, "item": {"folder_id": "P_6_26", "llm_summary": "Resumen"}},
        )

    client = ProcurementClient(
        base_url="https://signal.example",
        api_key="test-secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(handler),
    )
    try:
        payload = client.tender_summary(folder_id="P_6_26")
    finally:
        client.close()

    assert seen == {
        "method": "POST",
        "path": "/api/v1/registry/tenders/P_6_26/summary",
        "external_tenant": None,
    }
    assert payload["cached"] is False
    assert payload["item"]["folder_id"] == "P_6_26"


@pytest.mark.unit
def test_procurement_folder_lookups_call_global_registry_without_tenant_header() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "method": request.method,
                "path": request.url.path,
                "external_tenant": request.headers.get("X-OPN-External-Tenant-ID"),
            }
        )
        if request.url.path.endswith("/awards/P_6_26"):
            payload = {"folder_id": "P_6_26", "total": 1, "items": [{"folder_id": "P_6_26"}]}
        else:
            payload = {"item": {"folder_id": "P_6_26"}}
        return httpx.Response(200, headers={"Content-Type": "application/json"}, json=payload)

    client = ProcurementClient(
        base_url="https://signal.example",
        api_key="test-secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(handler),
    )
    try:
        assert client.tender_by_folder(folder_id="P_6_26")["item"]["folder_id"] == "P_6_26"
        assert client.awards_by_folder(folder_id="P_6_26")["total"] == 1
    finally:
        client.close()

    assert seen == [
        {
            "method": "GET",
            "path": "/api/v1/registry/tenders/P_6_26",
            "external_tenant": None,
        },
        {
            "method": "GET",
            "path": "/api/v1/registry/awards/P_6_26",
            "external_tenant": None,
        },
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "folder_id",
    ["EMERGENCIACR2026/671", "89/2026/27006", "OBR/CNT/2026000031"],
)
def test_procurement_folder_ids_with_slashes_are_encoded_for_signal_path(folder_id: str) -> None:
    seen: list[dict[str, Any]] = []
    encoded = quote(folder_id, safe="")

    def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode().split("?", 1)[0]
        seen.append(
            {
                "method": request.method,
                "path": request.url.path,
                "raw_path": raw_path,
                "external_tenant": request.headers.get("X-OPN-External-Tenant-ID"),
            }
        )
        if raw_path == f"/api/v1/registry/tenders/{encoded}/summary":
            payload = {"cached": False, "item": {"folder_id": folder_id, "llm_summary": "Resumen"}}
        elif raw_path == f"/api/v1/registry/tenders/{encoded}":
            payload = {"item": {"folder_id": folder_id}}
        elif raw_path == f"/api/v1/registry/awards/{encoded}":
            payload = {"folder_id": folder_id, "total": 1, "items": [{"folder_id": folder_id}]}
        else:
            return httpx.Response(
                404,
                headers={"Content-Type": "application/problem+json"},
                json={"code": "not_found", "detail": "No encontrado"},
            )
        return httpx.Response(200, headers={"Content-Type": "application/json"}, json=payload)

    client = ProcurementClient(
        base_url="https://signal.example",
        api_key="test-secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(handler),
    )
    try:
        assert client.tender_summary(folder_id=folder_id)["item"]["folder_id"] == folder_id
        assert client.tender_by_folder(folder_id=folder_id)["item"]["folder_id"] == folder_id
        assert client.awards_by_folder(folder_id=folder_id)["items"][0]["folder_id"] == folder_id
    finally:
        client.close()

    assert seen == [
        {
            "method": "POST",
            "path": f"/api/v1/registry/tenders/{folder_id}/summary",
            "raw_path": f"/api/v1/registry/tenders/{encoded}/summary",
            "external_tenant": None,
        },
        {
            "method": "GET",
            "path": f"/api/v1/registry/tenders/{folder_id}",
            "raw_path": f"/api/v1/registry/tenders/{encoded}",
            "external_tenant": None,
        },
        {
            "method": "GET",
            "path": f"/api/v1/registry/awards/{folder_id}",
            "raw_path": f"/api/v1/registry/awards/{encoded}",
            "external_tenant": None,
        },
    ]


@pytest.mark.unit
def test_procurement_items_resolve_tender_snapshot_with_mock_transport(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"path": request.url.path, "params": dict(request.url.params.multi_items())})
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={
                "item": {
                    "folder_id": "P_6_26",
                    "title": "Plataforma para empresas internacionales en Canarias",
                    "buyer": "PROEXCA",
                    "amount": "83000.00",
                    "deadline": None,
                    "cpv": ["79342000"],
                    "source_url": "https://contrataciondelestado.es/tender",
                },
            },
        )

    with app.app_context():
        app.config.update(
            SIGNAL_AI_BASE_URL="https://signal.example",
            SIGNAL_AI_ALLOWED_HOSTS="signal.example",
            SIGNAL_AI_API_KEY="configured-secret",
        )
        monkeypatch.setattr(
            procurement_items,
            "procurement_client_from_config",
            lambda: ProcurementClient(
                base_url="https://signal.example",
                api_key="configured-secret",
                allowed_hosts=frozenset({"signal.example"}),
                transport=httpx.MockTransport(handler),
            ),
        )
        snapshot = procurement_items.resolve_procurement_snapshot("tender", "P_6_26")

    assert seen[0]["path"] == "/api/v1/registry/tenders/P_6_26"
    assert seen[0]["params"] == {}
    assert snapshot["kind"] == "tender"
    assert snapshot["folder_id"] == "P_6_26"
    assert snapshot["deadline"] is None
    assert snapshot["cpv"] == ["79342000"]


@pytest.mark.unit
def test_procurement_items_resolve_award_snapshot_with_mock_transport(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/registry/awards/P_6_26"
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={
                "folder_id": "P_6_26",
                "total": 2,
                "items": [
                    {
                        "folder_id": "P_6_26",
                        "lot_id": "1",
                        "title": "Campaña promocional",
                        "buyer": "PROEXCA",
                        "winner": "Genesis Consulting SLP",
                        "award_amount": "3600.00",
                        "award_date": "2026-06-25",
                        "cpv": ["79342000"],
                        "source_url": "https://contrataciondelestado.es/award",
                    },
                    {
                        "folder_id": "P_6_26",
                        "lot_id": "2",
                        "title": "Campaña promocional",
                        "buyer": "PROEXCA",
                        "winner": "OPN Consultoría",
                        "award_amount": "1400.00",
                        "award_date": "2026-06-26",
                        "cpv": ["79342000", "79400000"],
                        "source_url": "https://contrataciondelestado.es/award",
                    },
                ],
            },
        )

    with app.app_context():
        monkeypatch.setattr(
            procurement_items,
            "procurement_client_from_config",
            lambda: ProcurementClient(
                base_url="https://signal.example",
                api_key="configured-secret",
                allowed_hosts=frozenset({"signal.example"}),
                transport=httpx.MockTransport(handler),
            ),
        )
        snapshot = procurement_items.resolve_procurement_snapshot("award", "P_6_26")

    assert snapshot["kind"] == "award"
    assert snapshot["total"] == 2
    assert snapshot["cpv"] == ["79342000", "79400000"]
    assert [entry["winner"] for entry in snapshot["entries"]] == [
        "Genesis Consulting SLP",
        "OPN Consultoría",
    ]
    extract = procurement_items.procurement_evidence_extract(snapshot)
    assert "Lotes: 2" in extract
    assert "Importe total adjudicado: 5000.00" in extract


@pytest.mark.unit
def test_procurement_items_resolve_folder_missing_errors(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/registry/awards/EMPTY":
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json={"folder_id": "EMPTY", "total": 0, "items": []},
            )
        return httpx.Response(
            404,
            headers={"Content-Type": "application/problem+json"},
            json={"code": "not_found", "detail": "No encontrado"},
        )

    with app.app_context():
        monkeypatch.setattr(
            procurement_items,
            "procurement_client_from_config",
            lambda: ProcurementClient(
                base_url="https://signal.example",
                api_key="configured-secret",
                allowed_hosts=frozenset({"signal.example"}),
                transport=httpx.MockTransport(handler),
            ),
        )
        with pytest.raises(procurement_items.ProcurementItemError):
            procurement_items.resolve_procurement_snapshot("tender", "MISSING")
        with pytest.raises(procurement_items.ProcurementItemError):
            procurement_items.resolve_procurement_snapshot("award", "EMPTY")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("response", "expected_status", "expected_code_part"),
    [
        (
            httpx.Response(
                429,
                headers={"Content-Type": "application/problem+json"},
                json={"code": "rate_limited", "detail": "Espera."},
            ),
            503,
            "rate_limited",
        ),
        (
            httpx.Response(
                500,
                headers={"Content-Type": "application/problem+json"},
                json={"type": "https://signal.example/problems/upstream-timeout"},
            ),
            503,
            "upstream_timeout",
        ),
        (
            httpx.Response(302, headers={"Location": "https://elsewhere.example"}),
            502,
            "redirect",
        ),
        (
            httpx.Response(200, headers={"Content-Type": "text/plain"}, text="ok"),
            502,
            "invalid_content_type",
        ),
        (
            httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=b"{" + (b" " * (procurement.PROCUREMENT_MAX_BYTES + 1)) + b"}",
            ),
            502,
            "response_too_large",
        ),
    ],
)
def test_procurement_maps_bad_provider_responses(
    response: httpx.Response,
    expected_status: int,
    expected_code_part: str,
) -> None:
    client = ProcurementClient(
        base_url="https://signal.example",
        api_key="test-secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(lambda _: response),
    )
    with pytest.raises(ProcurementProviderError) as exc_info:
        try:
            client.stats()
        finally:
            client.close()

    assert exc_info.value.status_code == expected_status
    assert expected_code_part in exc_info.value.code
    if response.status_code in {429, 500}:
        assert exc_info.value.retryable is True


@pytest.mark.unit
def test_procurement_timeout_is_retryable_503() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ReadTimeout("slow")

    client = ProcurementClient(
        base_url="https://signal.example",
        api_key="test-secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProcurementProviderError) as exc_info:
        try:
            client.stats()
        finally:
            client.close()

    assert exc_info.value.status_code == 503
    assert exc_info.value.retryable is True


class _FakeProcurementClient:
    def __init__(self) -> None:
        self.awards_calls = 0
        self.suggest_calls = 0
        self.closed = 0

    def awards(
        self,
        *,
        company: str | None,
        buyer: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        self.awards_calls += 1
        return {
            "company_norm": (company or "").upper(),
            "buyer_norm": (buyer or "").upper(),
            "total": 1,
            "items": [{"winner": company, "limit": limit, "offset": offset}],
        }

    def suggest(self, *, query: str, kind: str, limit: int) -> dict[str, Any]:
        self.suggest_calls += 1
        return {
            "kind": kind,
            "suggestions": [f"{query} Consulting SLP"],
            "cached_seconds": procurement.PROCUREMENT_SUGGEST_CACHE_TTL_SECONDS,
            "limit": limit,
        }

    def close(self) -> None:
        self.closed += 1


@pytest.mark.unit
def test_cached_awards_reuses_server_side_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = procurement.EntityIntelCache(ttl_seconds=600)
    fake = _FakeProcurementClient()
    monkeypatch.setattr(procurement, "_AWARDS_CACHE", cache)
    monkeypatch.setattr(procurement, "procurement_client_from_config", lambda: fake)

    first = cached_awards(tenant_id="tenant", company="Genesis", buyer=None, limit=5, offset=0)
    second = cached_awards(tenant_id="tenant", company="genesis", buyer=None, limit=5, offset=0)

    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert fake.awards_calls == 1
    assert fake.closed == 1


@pytest.mark.unit
def test_cached_suggest_reuses_short_server_side_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = procurement.EntityIntelCache(ttl_seconds=300)
    fake = _FakeProcurementClient()
    monkeypatch.setattr(procurement, "_SUGGEST_CACHE", cache)
    monkeypatch.setattr(procurement, "procurement_client_from_config", lambda: fake)

    first = cached_suggest(tenant_id="tenant", query="Genesis", kind="winner", limit=8)
    second = cached_suggest(tenant_id="tenant", query="genesis", kind="winner", limit=8)

    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert fake.suggest_calls == 1
    assert fake.closed == 1


@pytest.mark.unit
def test_procurement_route_denies_user_without_opportunity_read(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        id=uuid.uuid4(),
        email="reader@example.com",
        display_name="Reader",
        status="active",
    )
    monkeypatch.setattr(permissions, "current_permissions", lambda user_id, tenant_id: frozenset())

    with app.test_request_context("/api/v1/procurement/tenders?keywords=energia"):
        login_user(user)
        g.active_tenant_id = uuid.uuid4()
        response = procurement_routes.tenders()

    assert response[1] == 403
    assert response[2]["Content-Type"] == "application/problem+json"


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/procurement/tenders",
        "/api/v1/procurement/awards?company=x",
        "/api/v1/procurement/suggest?q=it&kind=winner",
    ],
)
def test_procurement_routes_require_auth_before_schema_validation(app: Any, path: str) -> None:
    response = app.test_client().get(path)

    assert response.status_code == 401
    assert response.headers["Content-Type"] == "application/problem+json"
    assert response.headers.get("Location") is None
    assert response.get_json()["code"] == "authentication_required"


@pytest.mark.unit
def test_procurement_suggest_route_serializes_provider_payload(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        id=uuid.uuid4(),
        email="reader@example.com",
        display_name="Reader",
        status="active",
    )
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda user_id, tenant_id: frozenset({"actor.read"}),
    )
    monkeypatch.setattr(
        procurement_routes,
        "cached_suggest",
        lambda tenant_id, query, kind, limit: {
            "kind": kind,
            "suggestions": [f"{query} CONSULTING SLP"],
            "cached_seconds": 300,
            "cache_hit": False,
            "limit": limit,
        },
    )

    with app.test_request_context("/api/v1/procurement/suggest?q=Genesis&kind=winner"):
        login_user(user)
        g.active_tenant_id = uuid.uuid4()
        response = procurement_routes.suggest()

    payload = response[0] if isinstance(response, tuple) else response
    assert payload.get_json() == {
        "kind": "winner",
        "suggestions": ["Genesis CONSULTING SLP"],
        "cached_seconds": 300,
        "cache_hit": False,
    }


@pytest.mark.unit
def test_procurement_saved_search_route_serializes_signal_payload(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        id=uuid.uuid4(),
        email="writer@example.com",
        display_name="Writer",
        status="active",
    )
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda user_id, tenant_id: frozenset({"opportunity.write"}),
    )
    monkeypatch.setattr(
        procurement_routes,
        "create_tender_search",
        lambda payload: {
            "id": "search-1",
            "tenant_id": "tenant-signal",
            "name": payload["name"],
            "keywords": payload["keywords"],
            "filters": payload["filters"],
        },
    )

    with app.test_request_context(
        "/api/v1/procurement/tender-searches",
        method="POST",
        json={"name": "Radar energía", "keywords": ["energia"], "filters": {}},
    ):
        login_user(user)
        g.active_tenant_id = uuid.uuid4()
        response, status = procurement_routes.tender_searches_create()

    assert status == 201
    assert response.get_json() == {
        "id": "search-1",
        "name": "Radar energía",
        "keywords": ["energia"],
        "filters": {},
    }


class _FakeDossier:
    def __init__(self, dossier_id: uuid.UUID) -> None:
        self.id = dossier_id
        self.status = "active"


class _FakePinnedItem:
    def __init__(self, *, item_id: uuid.UUID, tenant_id: uuid.UUID, dossier_id: uuid.UUID) -> None:
        now = datetime(2026, 7, 14, tzinfo=UTC)
        self.id = item_id
        self.tenant_id = tenant_id
        self.dossier_id = dossier_id
        self.kind = "tender"
        self.folder_id = "P_6_26"
        self.snapshot = {"kind": "tender", "folder_id": "P_6_26", "deadline": None}
        self.source_url = "https://contrataciondelestado.es/tender"
        self.evidence_id = uuid.uuid4()
        self.pinned_by_user_id = uuid.uuid4()
        self.created_at = now
        self.updated_at = now


@pytest.mark.unit
def test_dossier_procurement_routes_pin_list_delete_and_replay(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    item_id = uuid.uuid4()
    user = User(
        id=uuid.uuid4(),
        email="writer@example.com",
        display_name="Writer",
        status="active",
    )
    calls: list[dict[str, Any]] = []
    pinned = _FakePinnedItem(item_id=item_id, tenant_id=tenant_id, dossier_id=dossier_id)
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda user_id, active_tenant_id: frozenset({"opportunity.write", "opportunity.read"}),
    )
    monkeypatch.setattr(
        oracle_routes,
        "_dossier_or_404",
        lambda value, write=False: _FakeDossier(value),
    )

    def fake_pin(session: Any, **kwargs: Any) -> tuple[_FakePinnedItem, bool]:
        del session
        calls.append(kwargs)
        return pinned, len(calls) == 1

    monkeypatch.setattr(oracle_routes, "pin_procurement_item", fake_pin)
    monkeypatch.setattr(oracle_routes, "list_procurement_items", lambda session, **kwargs: [pinned])
    monkeypatch.setattr(oracle_routes, "delete_procurement_item", lambda session, **kwargs: True)

    with app.test_request_context(
        f"/api/v1/dossiers/{dossier_id}/procurement",
        method="POST",
        json={"kind": "tender", "folder_id": "P_6_26"},
    ):
        login_user(user)
        g.active_tenant_id = tenant_id
        response, status = oracle_routes.dossier_procurement_pin(dossier_id)
    assert status == 201
    assert response["folder_id"] == "P_6_26"
    assert calls[0]["tenant_id"] == tenant_id
    assert calls[0]["dossier_id"] == dossier_id

    with app.test_request_context(
        f"/api/v1/dossiers/{dossier_id}/procurement",
        method="POST",
        json={"kind": "tender", "folder_id": "P_6_26"},
    ):
        login_user(user)
        g.active_tenant_id = tenant_id
        _, replay_status = oracle_routes.dossier_procurement_pin(dossier_id)
    assert replay_status == 200

    with app.test_request_context(f"/api/v1/dossiers/{dossier_id}/procurement"):
        login_user(user)
        g.active_tenant_id = tenant_id
        listed = oracle_routes.dossier_procurement_list(dossier_id)
    assert listed["data"][0]["id"] == str(item_id)

    with app.test_request_context(
        f"/api/v1/dossiers/{dossier_id}/procurement/{item_id}", method="DELETE"
    ):
        login_user(user)
        g.active_tenant_id = tenant_id
        deleted = oracle_routes.dossier_procurement_delete(dossier_id, item_id)
    assert deleted == {"deleted": True, "id": str(item_id)}
