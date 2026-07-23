from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
import pytest
from flask import g
from flask_login import login_user

from opn_oracle.auth import permissions
from opn_oracle.extensions import limiter
from opn_oracle.integrations import procurement, procurement_routes
from opn_oracle.integrations.procurement import (
    ProcurementClient,
    ProcurementProviderError,
    cached_awards,
    cached_comparable_profile,
    cached_suggest,
)
from opn_oracle.oracle import procurement_items
from opn_oracle.oracle import routes as oracle_routes
from opn_oracle.oracle.comparable_procurement import profile_from_history
from opn_oracle.oracle.competitive_procurement import AwardHistory
from opn_oracle.platform.models import User


@contextmanager
def _authenticated_http_probe(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
    allowed_permissions: frozenset[str],
) -> Iterator[None]:
    """Use real HTTP dispatch while replacing only DB-backed session runtime."""

    user = User(
        id=uuid.uuid4(),
        email="procurement-reader@example.com",
        display_name="Procurement Reader",
        status="active",
    )
    tenant_id = uuid.uuid4()
    monkeypatch.setattr(permissions, "current_user", user)
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
    original_auth_runtime = before_request_funcs[auth_index]

    def install_test_identity() -> None:
        g.active_tenant_id = tenant_id

    before_request_funcs[auth_index] = install_test_identity
    try:
        yield
    finally:
        before_request_funcs[auth_index] = original_auth_runtime


def _csrf(client: Any) -> str:
    return str(client.get("/api/v1/auth/csrf").get_json()["csrf_token"])


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
def test_procurement_award_snapshot_classifies_signal_documents_and_ute(
    caplog: pytest.LogCaptureFixture,
) -> None:
    item = {
        "folder_id": "EMERGENCIACR2026/671",
        "lot_id": "1",
        "title": "Emergencia carretera",
        "buyer": "Diputación Provincial",
        "winner": "UTE Carreteras Norte",
        "award_amount": "1234.50",
        "cpv": ["45233141"],
        "status": "Adjudicada",
        "award_date": "2026-07-16",
        "region": "Castilla-La Mancha",
        "source_url": "https://contrataciondelestado.es/award",
        "documents": [
            {
                "uri": "https://contrataciondelestado.es/wps/wcm/connect/doc-1",
                "doc_type": "pliego",
                "file_name": "Pliego administrativo.pdf",
                "unexpected_nested_key": "no se persiste",
            }
        ],
        "is_ute": True,
    }

    caplog.set_level("WARNING", logger=procurement_items.__name__)
    snapshot = procurement_items._snapshot("award", item, "EMERGENCIACR2026/671")

    assert procurement_items._unclassified_snapshot_keys("award", item) == set()
    assert not caplog.records
    assert snapshot["documents"] == [
        {
            "uri": "https://contrataciondelestado.es/wps/wcm/connect/doc-1",
            "doc_type": "pliego",
            "file_name": "Pliego administrativo.pdf",
        }
    ]
    assert snapshot["is_ute"] is True


@pytest.mark.unit
def test_procurement_award_snapshot_warns_about_unclassified_provider_keys() -> None:
    """Avisa cuando Signal manda claves PLACSP que Oracle no sabe clasificar.

    Se captura con un handler propio en vez de con `caplog`: `configure_logging`
    hace `root.handlers.clear()` al construir la app Flask, así que en cuanto un test
    de integración crea una app, el handler que pytest instala en el logger raíz
    desaparece y `caplog` deja de ver nada. Con la integración desactivada el test
    pasaba; al activarla, fallaba por orden de ejecución y no por el código.
    """

    capturados: list[logging.LogRecord] = []

    class _Coleccionador(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            capturados.append(record)

    handler = _Coleccionador(level=logging.WARNING)
    modulo_logger = logging.getLogger(procurement_items.__name__)
    nivel_previo = modulo_logger.level
    desactivado_previo = modulo_logger.disabled
    modulo_logger.addHandler(handler)
    modulo_logger.setLevel(logging.WARNING)
    # Celery, al arrancar el worker real de los tests de integración, reconfigura el
    # logging con `disable_existing_loggers`, que deja este logger en disabled=True.
    # Sin reactivarlo, el warning no se emite y el test falla por orden de ejecución.
    modulo_logger.disabled = False
    try:
        unknown_keys = procurement_items._unclassified_snapshot_keys(
            "award",
            {"folder_id": "P_6_26", "signal_new_field": "value"},
        )
        snapshot = procurement_items._snapshot(
            "award",
            {"folder_id": "P_6_26", "signal_new_field": "value"},
            "P_6_26",
        )
    finally:
        modulo_logger.removeHandler(handler)
        modulo_logger.setLevel(nivel_previo)
        modulo_logger.disabled = desactivado_previo

    assert unknown_keys == {"signal_new_field"}
    assert snapshot["folder_id"] == "P_6_26"
    assert len(capturados) == 1
    assert capturados[0].unclassified_keys == ["signal_new_field"]


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
                        "lot_id": "A41050113",
                        "title": "Campaña promocional",
                        "buyer": "PROEXCA",
                        "winner": "Genesis Consulting SLP",
                        "award_amount": "3600.00",
                        "award_date": "2026-06-25",
                        "cpv": ["79342000"],
                        "source_url": "https://contrataciondelestado.es/award",
                        "documents": [
                            {
                                "uri": "https://contrataciondelestado.es/documents/pliego.pdf",
                                "doc_type": "pliego",
                                "file_name": "Pliego.pdf",
                            },
                            {
                                "uri": "https://contrataciondelestado.es/documents/pliego.pdf",
                                "doc_type": "pliego",
                                "file_name": "Duplicado.pdf",
                            },
                        ],
                        "is_ute": True,
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
                        "documents": [
                            {
                                "uri": "https://contrataciondelestado.es/documents/pliego.pdf",
                                "doc_type": "pliego",
                                "file_name": "Pliego.pdf",
                            },
                            {
                                "uri": "https://contrataciondelestado.es/documents/anexos.pdf",
                                "doc_type": "anexo",
                                "file_name": "Anexos.pdf",
                            },
                        ],
                        "is_ute": False,
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
    assert snapshot["award_amount"] == 5000
    assert snapshot["award_date"] == "2026-06-25/2026-06-26"
    assert snapshot["cpv"] == ["79342000", "79400000"]
    assert snapshot["is_ute"] is True
    assert [entry["award_amount"] for entry in snapshot["entries"]] == [3600, 1400]
    assert "lot_id" not in snapshot["entries"][0]
    assert snapshot["entries"][1]["lot_id"] == "2"
    assert [entry["winner"] for entry in snapshot["entries"]] == [
        "Genesis Consulting SLP",
        "OPN Consultoría",
    ]
    assert snapshot["entries"][0]["is_ute"] is True
    assert snapshot["entries"][1]["is_ute"] is False
    assert snapshot["entries"][0]["documents"] == [
        {
            "uri": "https://contrataciondelestado.es/documents/pliego.pdf",
            "doc_type": "pliego",
            "file_name": "Pliego.pdf",
        }
    ]
    assert snapshot["entries"][1]["documents"] == [
        {
            "uri": "https://contrataciondelestado.es/documents/anexos.pdf",
            "doc_type": "anexo",
            "file_name": "Anexos.pdf",
        }
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
def test_cached_comparable_profile_reuses_six_hour_aggregate_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = procurement.EntityIntelCache(
        ttl_seconds=procurement.PROCUREMENT_COMPARABLE_PROFILE_CACHE_TTL_SECONDS
    )
    fake = _FakeProcurementClient()
    monkeypatch.setattr(procurement, "_COMPARABLE_PROFILE_CACHE", cache)
    monkeypatch.setattr(procurement, "procurement_client_from_config", lambda: fake)

    first = cached_comparable_profile(tenant_id="tenant", company="Genesis Consulting")
    second = cached_comparable_profile(tenant_id="tenant", company="  genesis   consulting ")
    other_tenant = cached_comparable_profile(
        tenant_id="other-tenant",
        company="Genesis Consulting",
    )

    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert other_tenant["cache_hit"] is False
    assert first["cached_seconds"] == 21_600
    assert first["measured_at"] == second["measured_at"]
    assert fake.awards_calls == 2
    assert fake.closed == 2


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
    ("query_string", "expected_scope", "expected_active"),
    [
        ({}, "active", None),
        ({"scope": "active"}, "active", "true"),
        ({"scope": "all"}, "all", "false"),
        ({"active": "true"}, "active", "true"),
        ({"active": "false"}, "all", "false"),
    ],
)
def test_procurement_tender_scope_maps_to_signal_over_http(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
    query_string: dict[str, str],
    expected_scope: str,
    expected_active: str | None,
) -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params.multi_items()))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={
                "total": 2,
                "limit": 20,
                "offset": 0,
                "items": [
                    {"folder_id": "award", "status": "Adjudicada"},
                    {"folder_id": "unknown"},
                ],
            },
        )

    monkeypatch.setattr(
        procurement,
        "_TENDERS_CACHE",
        procurement.EntityIntelCache(ttl_seconds=90),
    )
    monkeypatch.setattr(
        procurement,
        "procurement_client_from_config",
        lambda: ProcurementClient(
            base_url="https://signal.example",
            api_key="configured-secret",
            allowed_hosts=frozenset({"signal.example"}),
            transport=httpx.MockTransport(handler),
        ),
    )

    with _authenticated_http_probe(app, monkeypatch, frozenset({"opportunity.read"})):
        response = client.get("/api/v1/procurement/tenders", query_string=query_string)

    assert response.status_code == 200
    assert seen[0].get("active") == expected_active
    assert response.get_json()["semantics"]["oracle_scope"] == expected_scope
    assert [item["canonical_status"] for item in response.get_json()["items"]] == [
        "awarded",
        "unknown",
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("query_string", "field"),
    [
        ({"scope": "future"}, "scope"),
        ({"scope": "historical"}, "scope"),
        ({"scope": "active", "active": "true"}, "scope"),
        ({"published_from": "2025-01-01"}, "published_from"),
        ({"deadline_from": "2025-01-01"}, "deadline_from"),
    ],
)
def test_procurement_rejects_unavailable_or_ambiguous_temporal_filters(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
    query_string: dict[str, str],
    field: str,
) -> None:
    with _authenticated_http_probe(app, monkeypatch, frozenset({"opportunity.read"})):
        response = client.get("/api/v1/procurement/tenders", query_string=query_string)

    assert response.status_code == 422
    assert field in str(response.get_json()["errors"])


@pytest.mark.unit
def test_procurement_rejects_unavailable_award_date_ranges(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _authenticated_http_probe(app, monkeypatch, frozenset({"actor.read"})):
        response = client.get(
            "/api/v1/procurement/awards",
            query_string={"company": "ITURRI", "awarded_from": "2025-01-01"},
        )

    assert response.status_code == 422
    assert "awarded_from" in str(response.get_json()["errors"])


@pytest.mark.unit
def test_procurement_search_plan_preview_dispatches_bounded_independent_probes(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter.reset()
    calls: list[dict[str, Any]] = []

    def fake_tenders(**query: Any) -> dict[str, Any]:
        calls.append(query)
        return {
            "total": 3,
            "limit": query["limit"],
            "offset": query["offset"],
            "items": [{"title": query.get("keywords") or query.get("cpv")}],
            "cached_seconds": 90,
            "cache_hit": False,
        }

    monkeypatch.setattr(procurement_routes, "cached_tenders", fake_tenders)
    plan = {
        "intent_summary": "Equipos de protección y vehículos de emergencia.",
        "include_terms": ["protección", "bomberos"],
        "synonyms": [],
        "exclude_terms": [],
        "candidate_cpv": [{"code": "18100000", "label": None}],
        "buyers": [],
        "geographies": [],
        "scope": "active",
        "min_amount": None,
        "max_amount": None,
        "assumptions": [],
        "questions": [],
        "confidence": 80,
        "discarded_count": 0,
        "discarded_reasons": {},
    }

    with _authenticated_http_probe(app, monkeypatch, frozenset({"opportunity.read"})):
        response = client.post(
            "/api/v1/procurement/search-plans/preview",
            json={"plan": plan},
        )

    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["plan"]["include_terms"] == ["proteccion", "bomberos"]
    assert payload["plan"]["candidate_cpv"] == [
        {"code": "18100000", "label": "Ropa de trabajo, ropa de trabajo especial y accesorios"}
    ]
    assert payload["preview"]["provider_requests"] == 3
    assert payload["preview"]["semantics"]["merged_results"] is False
    assert [call["keywords"] for call in calls] == ["proteccion", "bomberos", None]
    assert [call["cpv"] for call in calls] == [None, None, "18100000"]


@pytest.mark.unit
def test_procurement_search_plan_preview_rejects_historical_before_signal(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def unexpected_tenders(**query: Any) -> dict[str, Any]:
        del query
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(procurement_routes, "cached_tenders", unexpected_tenders)
    plan = {
        "intent_summary": "Vehículos de emergencia.",
        "include_terms": ["vehiculos"],
        "synonyms": [],
        "exclude_terms": [],
        "candidate_cpv": [],
        "buyers": [],
        "geographies": [],
        "scope": "historical",
        "min_amount": None,
        "max_amount": None,
        "assumptions": [],
        "questions": [],
        "confidence": 80,
        "discarded_count": 0,
        "discarded_reasons": {},
    }

    with _authenticated_http_probe(app, monkeypatch, frozenset({"opportunity.read"})):
        response = client.post(
            "/api/v1/procurement/search-plans/preview",
            json={"plan": plan},
        )

    assert response.status_code == 422
    assert "históricas" in response.get_json()["detail"]
    assert response.get_json()["errors"] == {
        "plan.scope": response.get_json()["detail"],
    }
    assert called is False


@pytest.mark.unit
@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"confidence": 101}, "plan.confidence"),
        ({"min_amount": 200, "max_amount": 100}, "plan.min_amount"),
    ],
)
def test_procurement_search_plan_preview_returns_field_keyed_validation_errors(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, Any],
    field: str,
) -> None:
    plan = {
        "intent_summary": "Vehículos de emergencia.",
        "include_terms": ["vehiculos"],
        "synonyms": [],
        "exclude_terms": [],
        "candidate_cpv": [],
        "buyers": [],
        "geographies": [],
        "scope": "active",
        "min_amount": None,
        "max_amount": None,
        "assumptions": [],
        "questions": [],
        "confidence": 80,
        "discarded_count": 0,
        "discarded_reasons": {},
        **changes,
    }

    with _authenticated_http_probe(app, monkeypatch, frozenset({"opportunity.read"})):
        response = client.post(
            "/api/v1/procurement/search-plans/preview",
            json={"plan": plan},
        )

    assert response.status_code == 422
    assert response.headers["Content-Type"] == "application/problem+json"
    assert field in response.get_json()["errors"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        (
            "POST",
            "/api/v1/procurement/tender-searches",
            {
                "name": "Archivo completo",
                "keywords": ["incendios"],
                "filters": {"scope": "all"},
            },
        ),
        (
            "PATCH",
            "/api/v1/procurement/tender-searches/search-1",
            {"filters": {"active": False}},
        ),
    ],
)
def test_procurement_rejects_saved_search_scopes_signal_cannot_preserve(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    payload: dict[str, Any],
) -> None:
    provider_called = False

    def unexpected_provider_call(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        nonlocal provider_called
        provider_called = True

    monkeypatch.setattr(
        procurement_routes,
        "create_tender_search",
        unexpected_provider_call,
    )
    monkeypatch.setattr(
        procurement_routes,
        "patch_tender_search",
        unexpected_provider_call,
    )

    with _authenticated_http_probe(app, monkeypatch, frozenset({"opportunity.write"})):
        response = client.open(path, method=method, json=payload)

    assert response.status_code == 422
    assert "filters" in str(response.get_json()["errors"])
    assert provider_called is False


PROCUREMENT_AUTH_ORDER_CASES: tuple[dict[str, Any], ...] = (
    {
        "method": "GET",
        "invalid_path": "/api/v1/procurement/comparable-profile?company=x",
        "valid_path": "/api/v1/procurement/comparable-profile?company=Acme",
        "invalid_json": None,
        "valid_json": None,
        "field": "company",
    },
    {
        "method": "POST",
        "invalid_path": f"/api/v1/procurement/tenders/{'x' * 201}/summary",
        "valid_path": "/api/v1/procurement/tenders/P_6_26/summary",
        "invalid_json": None,
        "valid_json": None,
        "field": "folder_id",
    },
    {
        "method": "POST",
        "invalid_path": "/api/v1/procurement/tender-searches",
        "valid_path": "/api/v1/procurement/tender-searches",
        # `name` debe ser válido: marshmallow omite los validadores de esquema
        # (skip_on_field_errors) si algún campo ya falló, y `keywords` se valida ahí.
        "invalid_json": {"name": "Radar energía", "keywords": []},
        "valid_json": {"name": "Radar energía", "keywords": ["energia"], "filters": {}},
        "field": "keywords",
    },
    {
        "method": "GET",
        "invalid_path": f"/api/v1/procurement/tender-searches/{'x' * 121}",
        "valid_path": "/api/v1/procurement/tender-searches/search-1",
        "invalid_json": None,
        "valid_json": None,
        "field": "search_id",
    },
    {
        "method": "PATCH",
        "invalid_path": "/api/v1/procurement/tender-searches/search-1",
        "valid_path": "/api/v1/procurement/tender-searches/search-1",
        "invalid_json": {},
        "valid_json": {"name": "Radar energía"},
        "field": "Indica",
    },
    {
        "method": "DELETE",
        "invalid_path": f"/api/v1/procurement/tender-searches/{'x' * 121}",
        "valid_path": "/api/v1/procurement/tender-searches/search-1",
        "invalid_json": None,
        "valid_json": None,
        "field": "search_id",
    },
    {
        "method": "GET",
        "invalid_path": "/api/v1/procurement/tender-searches/search-1/run?limit=0",
        "valid_path": "/api/v1/procurement/tender-searches/search-1/run?limit=1&offset=0",
        "invalid_json": None,
        "valid_json": None,
        "field": "limit",
    },
)


def _open_procurement_case(
    client: Any,
    case: dict[str, Any],
    *,
    valid: bool,
) -> Any:
    json_data = case["valid_json"] if valid else case["invalid_json"]
    request_kwargs: dict[str, Any] = {}
    if json_data is not None:
        request_kwargs["json"] = json_data
    if case["method"] in {"POST", "PATCH", "DELETE"}:
        request_kwargs["headers"] = {"X-CSRF-Token": _csrf(client)}
    return client.open(
        case["valid_path"] if valid else case["invalid_path"],
        method=case["method"],
        **request_kwargs,
    )


@pytest.mark.unit
@pytest.mark.parametrize("case", PROCUREMENT_AUTH_ORDER_CASES)
def test_procurement_anonymous_invalid_requests_do_not_leak_schema(
    client: Any,
    case: dict[str, Any],
) -> None:
    response = _open_procurement_case(client, case, valid=False)
    payload = response.get_json()

    assert response.status_code == 401
    assert payload["code"] == "authentication_required"
    assert "errors" not in payload


@pytest.mark.unit
@pytest.mark.parametrize("case", PROCUREMENT_AUTH_ORDER_CASES)
def test_procurement_anonymous_valid_requests_still_require_auth(
    client: Any,
    case: dict[str, Any],
) -> None:
    response = _open_procurement_case(client, case, valid=True)
    payload = response.get_json()

    assert response.status_code == 401
    assert payload["code"] == "authentication_required"


@pytest.mark.unit
@pytest.mark.parametrize("case", PROCUREMENT_AUTH_ORDER_CASES)
def test_procurement_authenticated_invalid_requests_still_validate(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
    case: dict[str, Any],
) -> None:
    with _authenticated_http_probe(
        app,
        monkeypatch,
        frozenset({"actor.read", "opportunity.read", "opportunity.write"}),
    ):
        response = _open_procurement_case(client, case, valid=False)
    payload = response.get_json()

    assert response.status_code == 422
    assert "errors" in payload
    assert case["field"] in str(payload["errors"])


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/procurement/tenders",
        "/api/v1/procurement/awards?company=x",
        "/api/v1/procurement/comparable-profile?company=x",
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
def test_comparable_profile_route_dispatches_with_actor_permission(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter.reset()
    measured = profile_from_history(
        AwardHistory(
            rows=(
                {
                    "folder_id": "A",
                    "award_amount": "125000",
                    "award_date": "2026-01-10",
                    "buyer": "Consorcio de Seguridad",
                    "cpv": "34144210",
                    "is_ute": False,
                    "source_url": "https://example.test/A",
                    "title": "Suministro de vehículo de extinción",
                    "winner": "ACME SA",
                },
            ),
            provider_total=1,
            truncated=False,
            provider_company_norm="ACME",
        ),
        company_name="Acme",
    )
    seen: dict[str, str] = {}

    def fake_profile(*, tenant_id: str, company: str) -> dict[str, Any]:
        seen.update(tenant_id=tenant_id, company=company)
        return {**measured, "cached_seconds": 21_600, "cache_hit": False}

    monkeypatch.setattr(procurement_routes, "cached_comparable_profile", fake_profile)
    with _authenticated_http_probe(app, monkeypatch, frozenset({"actor.read"})):
        response = client.get(
            "/api/v1/procurement/comparable-profile",
            query_string={"company": "  Acme  "},
        )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert seen["company"] == "Acme"
    assert response.get_json()["measured_at"] == measured["measured_at"]
    assert response.get_json()["frequent_cpvs"]["items"][0]["code"] == "34144210"
    assert response.get_json()["measurement_contract"]["llm_calls"] == 0


@pytest.mark.unit
def test_cpv_suggest_route_is_bounded_cacheable_and_never_calls_signal(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter.reset()
    with _authenticated_http_probe(app, monkeypatch, frozenset({"opportunity.read"})):
        by_code = client.get(
            "/api/v1/procurement/cpv/suggest",
            query_string={"q": "341442", "limit": 8},
        )
        by_label = client.get(
            "/api/v1/procurement/cpv/suggest",
            query_string={"q": "extincion", "limit": 20},
        )
        too_short = client.get(
            "/api/v1/procurement/cpv/suggest",
            query_string={"q": "x"},
        )

    assert by_code.status_code == 200
    assert by_code.headers["Cache-Control"] == "private, max-age=3600"
    assert by_code.get_json()["items"][0] == {
        "code": "34144200",
        "label": "Vehículos para servicios de emergencia",
    }
    assert len(by_label.get_json()["items"]) <= 20
    assert any(
        item["code"] == "34144210" and "extinción" in item["label"]
        for item in by_label.get_json()["items"]
    )
    assert too_short.status_code == 422
    assert "q" in str(too_short.get_json()["errors"])


@pytest.mark.unit
def test_cpv_suggest_route_enforces_declared_rate_limit(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter.reset()
    try:
        with _authenticated_http_probe(app, monkeypatch, frozenset({"opportunity.read"})):
            responses = [
                client.get(
                    "/api/v1/procurement/cpv/suggest",
                    query_string={"q": "341442", "limit": 1},
                )
                for _request in range(61)
            ]
        assert all(response.status_code == 200 for response in responses[:60])
        assert responses[60].status_code == 429
    finally:
        limiter.reset()


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
        self.linked_opportunity_id = None
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
    monkeypatch.setattr(
        oracle_routes,
        "list_procurement_items",
        lambda session, **kwargs: [pinned],
    )
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
