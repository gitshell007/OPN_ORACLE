from __future__ import annotations

from typing import Any

import httpx
import pytest

from opn_oracle.integrations.entity_intel import (
    EntityIntelClient,
    EntityIntelConfigurationError,
    EntityIntelProviderError,
)


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
        "path": "/entity-intel/suggest",
        "params": {"q": "IBERDROLA", "kind": "company", "limit": "5"},
        "api_key": "test-secret",
        "external_tenant": None,
    }
    assert payload["suggestions"] == ["IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA"]
    assert payload["cached_seconds"] == 600


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
        "path": "/entity-intel/graph",
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
