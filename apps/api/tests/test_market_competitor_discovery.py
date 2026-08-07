from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from flask import g

from opn_oracle.ai import routes as ai_routes
from opn_oracle.ai.context import build_market_competitor_discovery_context
from opn_oracle.ai.provider import LLMRequest, MockLLMProvider
from opn_oracle.ai.registry import PromptRegistry
from opn_oracle.ai.schemas import MarketCompetitorDiscoveryOutput
from opn_oracle.auth import permissions
from opn_oracle.platform.models import User


def _request(context: dict[str, Any]) -> LLMRequest:
    registry = PromptRegistry()
    prompt = registry.get("market_competitor_discovery")
    return LLMRequest(
        agent="market_competitor_discovery",
        model=prompt.model,
        system_prompt=prompt.text,
        task_prompt="Propon competidores candidatos.",
        context=context,
        max_output_tokens=prompt.max_output_tokens,
        classification=prompt.classification,
    )


def test_registry_exposes_governed_market_competitor_discovery() -> None:
    prompt = PromptRegistry().get("market_competitor_discovery")
    assert prompt.version == "v1"
    assert prompt.schema is MarketCompetitorDiscoveryOutput
    assert "dossier_id" not in prompt.input_contract
    assert "known_names" in prompt.input_contract
    assert prompt.requires_evidence_review is False
    assert prompt.evidence_review_failure_policy == "not_required"


def test_mock_discovery_is_deterministic_and_excludes_known_names() -> None:
    provider = MockLLMProvider("seed")
    context = {
        "countries": ["ES", "DE"],
        "known_names": ["Competidor Sintetico 1"],
        "allowed_evidence_ids": [],
    }
    first = provider.generate_structured(_request(context), MarketCompetitorDiscoveryOutput)
    second = provider.generate_structured(_request(context), MarketCompetitorDiscoveryOutput)

    assert first.output.model_dump() == second.output.model_dump()
    names = [item.name for item in first.output.candidates]
    assert "Competidor Sintetico 1" not in names
    assert names, "el mock debe proponer al menos un candidato"
    assert all(item.confidence <= 100 for item in first.output.candidates)
    assert {item.country for item in first.output.candidates} <= {"ES", "DE", ""}


def test_market_discovery_context_is_dossierless_and_normalized(app: Any) -> None:
    from opn_oracle.tenants.context import TenantContext, tenant_context

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=uuid.uuid4(), actor_id=None)),
    ):
        context = build_market_competitor_discovery_context(
            description="  Mercado de   almacenamiento energético  ",
            own_offer="Integración de baterías",
            sectors=["almacenamiento", "almacenamiento"],
            countries=["es", "de", "ES"],
            languages=["ES", "de"],
            known_names=[" Fluence Energy "],
            max_tokens=2_000,
        )

    assert context.manifest["dossier_id"] is None
    assert context.manifest["snapshot_kind"] == "market_competitor_discovery"
    assert context.evidence == ()
    assert context.payload["countries"] == ["ES", "DE"]
    assert context.payload["languages"] == ["es", "de"]
    assert context.payload["sectors"] == ["almacenamiento"]
    assert context.payload["known_names"] == ["Fluence Energy"]
    assert context.payload["description"] == "Mercado de almacenamiento energético"
    assert context.payload["allowed_evidence_ids"] == []


@contextmanager
def _authenticated_ai(app: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[uuid.UUID]:
    user = User(
        id=uuid.uuid4(),
        email="market-discovery@example.com",
        display_name="Market discovery",
        status="active",
    )
    tenant_id = uuid.uuid4()
    principal = type("Principal", (), {"id": user.id, "is_authenticated": True})()
    monkeypatch.setattr(permissions, "current_user", principal)
    monkeypatch.setattr(ai_routes, "current_user", principal)
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda user_id, active_tenant_id: frozenset({"ai.execute"}),
    )
    before = app.before_request_funcs.get(None, [])
    index = next(
        i
        for i, function in enumerate(before)
        if function.__name__ == "protect_csrf_and_install_identity"
    )
    original = before[index]

    def install_identity() -> None:
        g.active_tenant_id = tenant_id

    before[index] = install_identity
    try:
        yield tenant_id
    finally:
        before[index] = original


def test_market_discovery_http_enqueues_dossierless_tenant_job(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_enqueue(task_name: str, **kwargs: Any) -> Any:
        captured["task_name"] = task_name
        captured.update(kwargs)
        return type(
            "Job",
            (),
            {
                "id": uuid.uuid4(),
                "status": "queued",
                "input_payload": kwargs["payload"],
            },
        )()

    monkeypatch.setattr(ai_routes, "enqueue_job", fake_enqueue)
    monkeypatch.setattr(
        ai_routes,
        "serialize_job",
        lambda job: {"id": str(job.id), "status": job.status},
    )
    monkeypatch.setattr(ai_routes, "_latest_market_discovery_artifact", lambda: None)

    with _authenticated_ai(app, monkeypatch) as tenant_id:
        response = client.post(
            "/api/v1/ai/market-competitor-discovery/runs",
            json={
                "description": "  Mercado de   almacenamiento energético en ES y DE ",
                "own_offer": " Integración de baterías ",
                "sectors": ["almacenamiento energético"],
                "countries": ["es", "DE"],
                "languages": ["ES", "de"],
                "known_names": ["Fluence Energy"],
            },
            headers={"Idempotency-Key": "market-discovery-1"},
        )

    assert response.status_code == 202, response.get_json()
    assert captured["task_name"] == "oracle.ai.market_competitor_discovery"
    assert captured["payload"] == {
        "description": "Mercado de almacenamiento energético en ES y DE",
        "own_offer": "Integración de baterías",
        "sectors": ["almacenamiento energético"],
        "countries": ["ES", "DE"],
        "languages": ["es", "de"],
        "known_names": ["Fluence Energy"],
    }
    assert "dossier_id" not in captured
    assert captured["resource_type"] == "market_discovery"
    assert captured["resource_id"] == tenant_id


def test_market_discovery_http_requires_idempotency_key(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _authenticated_ai(app, monkeypatch):
        response = client.post(
            "/api/v1/ai/market-competitor-discovery/runs",
            json={"description": "Mercado de almacenamiento energético"},
        )

    assert response.status_code == 428
    assert response.headers["Content-Type"] == "application/problem+json"
    assert response.get_json()["code"] == "precondition_required"
    assert "Idempotency-Key" in response.get_json()["detail"]
