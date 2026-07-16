from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from flask import g

from opn_oracle.extensions import db
from opn_oracle.integrations import entity_intel, entity_intel_routes
from opn_oracle.integrations.entity_intel import (
    EntityIntelCache,
    EntityIntelClient,
    EntityIntelConfigurationError,
    EntityIntelProviderError,
    cached_graph,
    cached_suggest,
    entity_intel_client_from_config,
    person_name_variants,
    resolve_signal_external_tenant_id,
)
from opn_oracle.platform.models import IntegrationConnection


@pytest.mark.unit
def test_entity_intel_suggest_calls_allowlisted_signal_without_tenant_header() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params.multi_items())
        seen["api_key"] = request.headers.get("X-API-Key")
        seen["external_tenant"] = request.headers.get("X-OPN-External-Tenant-ID")
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={
                "kind": "company",
                "suggestions": ["IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA"],
            },
        )

    client = EntityIntelClient(
        base_url="https://signal.example",
        api_key="test-secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(handler),
    )
    try:
        payload = client.suggest(query="IBERDROLA", kind="company", limit=5)
    finally:
        client.close()

    assert seen == {
        "path": "/api/v1/registry/suggest",
        "params": {"q": "IBERDROLA", "kind": "company", "limit": "5"},
        "api_key": "test-secret",
        "external_tenant": None,
    }
    assert payload["suggestions"] == ["IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA"]
    assert payload["cached_seconds"] == 600


@pytest.mark.unit
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Miguel Burgos", ["MIGUEL BURGOS", "BURGOS MIGUEL"]),
        (
            "Miguel Burgos Canto",
            ["MIGUEL BURGOS CANTO", "BURGOS CANTO MIGUEL"],
        ),
        (
            "Juan Carlos Perez Lopez",
            [
                "JUAN CARLOS PEREZ LOPEZ",
                "CARLOS PEREZ LOPEZ JUAN",
                "PEREZ LOPEZ JUAN CARLOS",
            ],
        ),
        (
            "Miguel de la Fuente Garcia",
            [
                "MIGUEL DE LA FUENTE GARCIA",
                "DE LA FUENTE GARCIA MIGUEL",
            ],
        ),
        ("Miguel O' Connor", ["MIGUEL O' CONNOR", "O' CONNOR MIGUEL"]),
        ("Burgos Canto, Miguel", ["BURGOS CANTO MIGUEL"]),
    ],
)
def test_person_name_variants_cover_spanish_name_orders(
    query: str,
    expected: list[str],
) -> None:
    assert person_name_variants(query) == expected


@pytest.mark.unit
def test_entity_intel_person_suggest_stops_when_original_matches() -> None:
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params.multi_items()))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={"kind": "person", "suggestions": ["MIGUEL BURGOS CANTO"]},
        )

    client = EntityIntelClient(
        base_url="https://signal.example",
        api_key="test-secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(handler),
    )
    try:
        payload = client.suggest(query="Miguel Burgos Canto", kind="person", limit=5)
    finally:
        client.close()

    assert [call["q"] for call in calls] == ["MIGUEL BURGOS CANTO"]
    assert payload["suggestions"] == ["MIGUEL BURGOS CANTO"]


@pytest.mark.unit
def test_entity_intel_person_suggest_rotates_merges_and_deduplicates() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["q"]
        calls.append(query)
        suggestions = []
        if query == "BURGOS CANTO MIGUEL":
            suggestions = ["BURGOS CANTO MIGUEL", "Burgos Canto Miguel"]
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={"kind": "person", "suggestions": suggestions},
        )

    client = EntityIntelClient(
        base_url="https://signal.example",
        api_key="test-secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(handler),
    )
    try:
        payload = client.suggest(query="Miguel Burgos Canto", kind="person", limit=5)
    finally:
        client.close()

    assert calls == ["MIGUEL BURGOS CANTO", "BURGOS CANTO MIGUEL"]
    assert payload["suggestions"] == ["BURGOS CANTO MIGUEL"]


@pytest.mark.unit
def test_entity_intel_company_suggest_does_not_generate_person_variants() -> None:
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params.multi_items()))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={"kind": "company", "suggestions": ["MIGUEL BURGOS CANTO SL"]},
        )

    client = EntityIntelClient(
        base_url="https://signal.example",
        api_key="test-secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(handler),
    )
    try:
        payload = client.suggest(query="Miguel Burgos Canto", kind="company", limit=5)
    finally:
        client.close()

    assert [call["q"] for call in calls] == ["Miguel Burgos Canto"]
    assert payload["suggestions"] == ["MIGUEL BURGOS CANTO SL"]


@pytest.mark.unit
def test_entity_intel_graph_sends_external_tenant_and_normalizes_payload() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params.multi_items())
        seen["external_tenant"] = request.headers.get("X-OPN-External-Tenant-ID")
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={
                "center": "IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA",
                "nodes": [{"id": "iberdrola", "label": "Iberdrola", "type": "company"}],
                "edges": [{"source": "iberdrola", "target": "grupo", "role": "matriz"}],
                "truncated": False,
            },
        )

    client = EntityIntelClient(
        base_url="https://signal.example",
        api_key="test-secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(handler),
    )
    try:
        payload = client.graph(
            name="IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA",
            kind="company",
            depth=2,
            active_only=True,
            external_tenant_id="tenant-signal",
        )
    finally:
        client.close()

    assert seen == {
        "path": "/api/v1/oracle/entity/graph",
        "params": {
            "name": "IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA",
            "type": "company",
            "depth": "2",
            "active_only": "true",
        },
        "external_tenant": "tenant-signal",
    }
    assert payload["nodes"][0]["id"] == "iberdrola"
    assert payload["edges"][0]["role"] == "matriz"
    assert payload["truncated"] is False


@pytest.mark.unit
def test_entity_intel_requires_https_and_allowlisted_host() -> None:
    with pytest.raises(EntityIntelConfigurationError, match="HTTPS"):
        EntityIntelClient(
            base_url="http://signal.example",
            api_key="secret",
            allowed_hosts=frozenset({"signal.example"}),
            transport=httpx.MockTransport(lambda _: httpx.Response(200)),
        )
    with pytest.raises(EntityIntelConfigurationError, match="allowlist"):
        EntityIntelClient(
            base_url="https://evil.example",
            api_key="secret",
            allowed_hosts=frozenset({"signal.example"}),
            transport=httpx.MockTransport(lambda _: httpx.Response(200)),
        )


@pytest.mark.unit
def test_entity_intel_maps_signal_problem_without_leaking_transport_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            500,
            headers={"Content-Type": "application/problem+json"},
            json={
                "type": "https://signal.example/problems/upstream-timeout",
                "title": "Timeout",
                "detail": "No se pudo resolver el grafo a tiempo.",
            },
        )

    client = EntityIntelClient(
        base_url="https://signal.example",
        api_key="test-secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(EntityIntelProviderError) as exc_info:
        try:
            client.suggest(query="IBERDROLA", kind="company", limit=5)
        finally:
            client.close()

    error = exc_info.value
    assert error.status_code == 503
    assert error.code == "upstream_timeout"
    assert error.detail == "No se pudo resolver el grafo a tiempo."
    assert error.retryable is True


@pytest.mark.unit
def test_entity_intel_route_problem_response_preserves_provider_detail(app: Any) -> None:
    with app.test_request_context("/api/v1/entity-intel/graph"):
        response = entity_intel_routes._provider_error_response(
            EntityIntelProviderError(
                status_code=403,
                code="insufficient_scope",
                detail="La credencial no tiene el scope 'entity:read'.",
            )
        )

    assert response.status_code == 403
    assert response.content_type == "application/problem+json"
    assert response.get_json()["code"] == "insufficient_scope"
    assert response.get_json()["detail"] == "La credencial no tiene el scope 'entity:read'."


@pytest.mark.unit
def test_entity_intel_cache_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    moments = iter([10.0, 10.0, 10.5, 12.1])
    monkeypatch.setattr(entity_intel.time, "monotonic", lambda: next(moments))
    cache = EntityIntelCache(ttl_seconds=2)

    assert cache.get(("missing",)) is None
    cache.set(("key",), {"value": "fresh"})
    assert cache.get(("key",)) == {"value": "fresh"}
    assert cache.get(("key",)) is None


@pytest.mark.unit
def test_entity_intel_rejects_unsafe_base_urls_and_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200))
    with pytest.raises(EntityIntelConfigurationError, match="clave"):
        EntityIntelClient(
            base_url="https://signal.example",
            api_key="",
            allowed_hosts=frozenset({"signal.example"}),
            transport=transport,
        )
    with pytest.raises(EntityIntelConfigurationError, match="credenciales"):
        EntityIntelClient(
            base_url="https://user:pass@signal.example",
            api_key="secret",
            allowed_hosts=frozenset({"signal.example"}),
            transport=transport,
        )
    with pytest.raises(EntityIntelConfigurationError, match="query"):
        EntityIntelClient(
            base_url="https://signal.example?debug=true",
            api_key="secret",
            allowed_hosts=frozenset({"signal.example"}),
            transport=transport,
        )
    monkeypatch.setattr(
        entity_intel.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    with pytest.raises(EntityIntelConfigurationError, match="red no pública"):
        EntityIntelClient(
            base_url="https://signal.example",
            api_key="secret",
            allowed_hosts=frozenset({"signal.example"}),
        )
    monkeypatch.setattr(
        entity_intel.socket,
        "getaddrinfo",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError()),
    )
    with pytest.raises(EntityIntelConfigurationError, match="resolver"):
        EntityIntelClient(
            base_url="https://signal.example",
            api_key="secret",
            allowed_hosts=frozenset({"signal.example"}),
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(302, headers={"Location": "https://elsewhere.example"}), "redirect"),
        (
            httpx.Response(200, headers={"Content-Type": "text/plain"}, text="ok"),
            "invalid_content_type",
        ),
        (
            httpx.Response(200, headers={"Content-Type": "application/json"}, content=b"{"),
            "invalid_json",
        ),
        (
            httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json=["not", "object"],
            ),
            "invalid_payload",
        ),
    ],
)
def test_entity_intel_rejects_bad_provider_responses(
    response: httpx.Response,
    code: str,
) -> None:
    client = EntityIntelClient(
        base_url="https://signal.example",
        api_key="test-secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(lambda _: response),
    )
    with pytest.raises(EntityIntelProviderError) as exc_info:
        try:
            client.suggest(query="IBERDROLA", kind="company", limit=5)
        finally:
            client.close()
    assert code in exc_info.value.code


@pytest.mark.unit
def test_entity_intel_rejects_invalid_suggestions_and_graph() -> None:
    responses = iter(
        [
            httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json={"suggestions": "IBERDROLA"},
            ),
            httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json={"nodes": {}, "edges": []},
            ),
        ]
    )
    client = EntityIntelClient(
        base_url="https://signal.example",
        api_key="test-secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(lambda _: next(responses)),
    )
    try:
        with pytest.raises(EntityIntelProviderError) as suggestions_error:
            client.suggest(query="IBERDROLA", kind="company", limit=5)
        assert suggestions_error.value.code == "entity_intel_invalid_suggestions"
        with pytest.raises(EntityIntelProviderError) as graph_error:
            client.graph(
                name="IBERDROLA",
                kind="company",
                depth=2,
                active_only=True,
                external_tenant_id="tenant",
            )
        assert graph_error.value.code == "entity_intel_invalid_graph"
    finally:
        client.close()


@pytest.mark.unit
def test_entity_intel_client_from_config_uses_signal_ai_settings(app: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "configured-secret"
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={"kind": "company", "suggestions": ["Iberdrola"]},
        )

    with app.app_context():
        app.config.update(
            SIGNAL_AI_BASE_URL="https://signal.example",
            SIGNAL_AI_ALLOWED_HOSTS="signal.example",
            SIGNAL_AI_API_KEY="configured-secret",
            SIGNAL_CONNECT_TIMEOUT_SECONDS=1,
            SIGNAL_AI_TIMEOUT_SECONDS=2,
        )
        client = entity_intel_client_from_config(transport=httpx.MockTransport(handler))
        try:
            assert client.suggest(query="IBERDROLA", kind="company", limit=1)["suggestions"] == [
                "Iberdrola"
            ]
        finally:
            client.close()


class _FakeEntityIntelClient:
    def __init__(self) -> None:
        self.suggest_calls = 0
        self.graph_calls = 0
        self.closed = 0

    def suggest(self, *, query: str, kind: str, limit: int) -> dict[str, Any]:
        self.suggest_calls += 1
        return {"kind": kind, "suggestions": [query], "cached_seconds": 600, "limit": limit}

    def graph(
        self,
        *,
        name: str,
        kind: str,
        depth: int,
        active_only: bool,
        external_tenant_id: str,
    ) -> dict[str, Any]:
        self.graph_calls += 1
        return {
            "center": name,
            "nodes": [{"id": name, "type": kind}],
            "edges": [],
            "truncated": not active_only,
            "cached_seconds": 600,
            "depth": depth,
            "external_tenant_id": external_tenant_id,
        }

    def close(self) -> None:
        self.closed += 1


@pytest.mark.unit
def test_cached_suggest_and_graph_reuse_server_side_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = EntityIntelCache(ttl_seconds=60)
    fake = _FakeEntityIntelClient()
    monkeypatch.setattr(entity_intel, "_CACHE", cache)
    monkeypatch.setattr(entity_intel, "entity_intel_client_from_config", lambda: fake)

    first = cached_suggest(tenant_id="tenant", query="IBERDROLA", kind="company", limit=5)
    second = cached_suggest(tenant_id="tenant", query="iberdrola", kind="company", limit=5)
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert fake.suggest_calls == 1

    graph_first = cached_graph(
        tenant_id="tenant",
        name="IBERDROLA",
        kind="company",
        depth=2,
        active_only=True,
        external_tenant_id="external",
    )
    graph_second = cached_graph(
        tenant_id="tenant",
        name="iberdrola",
        kind="company",
        depth=2,
        active_only=True,
        external_tenant_id="external",
    )
    assert graph_first["cache_hit"] is False
    assert graph_second["cache_hit"] is True
    assert fake.graph_calls == 1
    assert fake.closed == 2


@pytest.mark.unit
def test_resolve_signal_external_tenant_id_uses_connection_metadata(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    connection = IntegrationConnection(
        tenant_id=tenant_id,
        provider="signal-avanza",
        name="Signal",
        status="active",
        connection_metadata={"external_tenant_id": "signal-tenant"},
    )
    monkeypatch.setattr(db.session, "scalar", lambda statement: connection)
    with app.test_request_context("/"):
        g.active_tenant_id = tenant_id
        assert resolve_signal_external_tenant_id() == "signal-tenant"
    connection.connection_metadata = {}
    with app.test_request_context("/"):
        g.active_tenant_id = tenant_id
        assert resolve_signal_external_tenant_id() == str(tenant_id)


@pytest.mark.unit
def test_resolve_signal_external_tenant_id_requires_active_connection(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db.session, "scalar", lambda statement: None)
    with app.test_request_context("/"):
        g.active_tenant_id = uuid.uuid4()
        with pytest.raises(EntityIntelProviderError) as exc_info:
            resolve_signal_external_tenant_id()
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "signal_connection_missing"
