"""G06 · agente market_competitor_discovery: source_urls «no verificada», sin red."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from flask import g

from opn_oracle.ai import context as ai_context
from opn_oracle.ai import routes as ai_routes
from opn_oracle.ai.context import build_market_competitor_discovery_context
from opn_oracle.ai.provider import LLMRequest, MockLLMProvider
from opn_oracle.ai.registry import (
    EVIDENCE_REVIEW_REQUIRED,
    INPUT_CONTRACTS,
    PromptRegistry,
)
from opn_oracle.ai.schemas import MarketCompetitorDiscoveryOutput
from opn_oracle.ai.source_url_policy import SOURCE_URL_UNVERIFIED_LABEL
from opn_oracle.auth import permissions
from opn_oracle.jobs import tasks as job_tasks
from opn_oracle.platform.models import User


def test_registry_exposes_market_competitor_discovery() -> None:
    prompt = PromptRegistry().get("market_competitor_discovery")
    assert prompt.schema is MarketCompetitorDiscoveryOutput
    assert prompt.requires_evidence_review is False
    assert prompt.evidence_review_failure_policy == "not_required"
    assert prompt.max_output_tokens == 2500
    assert EVIDENCE_REVIEW_REQUIRED["market_competitor_discovery"] is False
    assert "description" in INPUT_CONTRACTS["market_competitor_discovery"]
    assert "allowed_evidence_ids" in INPUT_CONTRACTS["market_competitor_discovery"]
    assert "no verificada" in prompt.text.casefold() or "source_url" in prompt.text.casefold()


def test_build_market_competitor_discovery_context(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    monkeypatch.setattr(ai_context, "require_tenant_id", lambda: tenant_id)

    context = build_market_competitor_discovery_context(
        description="  Buscamos   competidores de  baterías  industriales  ",
        own_offer="  Oferta propia  ",
        sectors=[" Energía ", "Energía", "  "],
        countries=["es", "ES", "pt"],
        languages=["ES", "en"],
        known_names=["Acme SL", "Acme SL"],
        max_tokens=800,
    )

    assert context.manifest["snapshot_kind"] == "market_competitor_discovery"
    assert context.manifest["dossier_id"] is None
    assert context.manifest["evidence_ids"] == []
    assert context.evidence == ()
    assert context.payload["tenant_id"] == str(tenant_id)
    assert context.payload["description"] == "Buscamos competidores de baterías industriales"
    assert context.payload["own_offer"] == "Oferta propia"
    assert context.payload["sectors"] == ["Energía"]
    assert context.payload["countries"] == ["ES", "PT"]
    assert context.payload["languages"] == ["es", "en"]
    assert context.payload["known_names"] == ["Acme SL"]
    assert context.payload["allowed_evidence_ids"] == []
    assert "no verificada" in context.payload["security_instruction"]


def test_mock_provider_labels_invented_source_urls() -> None:
    provider = MockLLMProvider(seed="g06-market")
    request = LLMRequest(
        agent="market_competitor_discovery",
        model="mock-oracle-v1",
        system_prompt="sys",
        task_prompt="user",
        context={"countries": ["ES", "PT"], "known_names": ["Competidor Sintetico 2"]},
        max_output_tokens=2500,
        classification="internal",
    )
    result = provider.generate_structured(request, MarketCompetitorDiscoveryOutput)
    output = result.output
    assert isinstance(output, MarketCompetitorDiscoveryOutput)
    # known_names filtra el #2; quedan 1 y 3; el #1 lleva URL inventada.
    names = {c.name for c in output.candidates}
    assert "Competidor Sintetico 2" not in names
    with_urls = [c for c in output.candidates if c.source_urls]
    assert with_urls, "mock debe proponer al menos una source_url inventada"
    cand = with_urls[0]
    assert cand.source_urls == ["https://www.empresa-inventada-xyz.es/perfil"]
    assert cand.source_urls_label == SOURCE_URL_UNVERIFIED_LABEL
    assert cand.source_urls_meta[0].verified is False
    assert cand.source_urls_meta[0].label == "no verificada"
    assert any(SOURCE_URL_UNVERIFIED_LABEL in w for w in output.warnings)


def test_market_discovery_input_validation() -> None:
    clean = ai_routes._market_discovery_input(
        {
            "description": "  Fabricamos  baterías  de  litio  ",
            "own_offer": "  pack  ",
            "sectors": ["a", "a", ""],
            "countries": ["es"],
            "languages": ["ES"],
            "known_names": ["X"],
        }
    )
    assert clean["description"] == "Fabricamos baterías de litio"
    assert clean["countries"] == ["ES"]
    assert clean["languages"] == ["es"]

    with pytest.raises(ValueError, match="descripción"):
        ai_routes._market_discovery_input({"description": "corta"})
    with pytest.raises(ValueError, match="lista"):
        ai_routes._market_discovery_input(
            {"description": "Descripción suficientemente larga", "sectors": "no-list"}
        )
    with pytest.raises(ValueError, match="no válido"):
        ai_routes._market_discovery_input("not-a-dict")


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


def test_market_competitor_discovery_http_enqueues_dossierless_job(
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
                "description": "  Buscamos rivales de  storage  grid  ",
                "own_offer": "  EPC  ",
                "sectors": ["energy"],
                "countries": ["es"],
                "languages": ["ES"],
                "known_names": ["Acme"],
            },
            headers={"Idempotency-Key": "market-disc-1"},
        )

    assert response.status_code == 202
    assert captured["task_name"] == "oracle.ai.market_competitor_discovery"
    assert captured["payload"]["description"] == "Buscamos rivales de storage grid"
    assert captured["payload"]["countries"] == ["ES"]
    assert "dossier_id" not in captured
    assert captured["resource_type"] == "market_discovery"
    assert captured["resource_id"] == tenant_id
    body = response.get_json()
    assert body["artifact"] is None
    assert body["job"]["status"] == "queued"


def test_market_competitor_discovery_http_requires_idempotency_key(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _authenticated_ai(app, monkeypatch):
        response = client.post(
            "/api/v1/ai/market-competitor-discovery/runs",
            json={"description": "Descripción suficientemente larga para validar"},
        )

    assert response.status_code == 428
    assert response.headers["Content-Type"] == "application/problem+json"
    assert response.get_json()["code"] == "precondition_required"


def test_market_competitor_discovery_http_validation_error(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _authenticated_ai(app, monkeypatch):
        response = client.post(
            "/api/v1/ai/market-competitor-discovery/runs",
            json={"description": "corta"},
            headers={"Idempotency-Key": "market-disc-bad"},
        )

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_error"


def test_market_competitor_discovery_latest_empty(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ai_routes, "_latest_market_discovery_job", lambda: None)
    monkeypatch.setattr(ai_routes, "_latest_market_discovery_artifact", lambda: None)

    with _authenticated_ai(app, monkeypatch):
        response = client.get("/api/v1/ai/market-competitor-discovery/latest")

    assert response.status_code == 200
    assert response.get_json() == {"job": None, "artifact": None}


def test_execute_ai_market_competitor_discovery_handler(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    captured: dict[str, Any] = {}

    def fake_execute_agent(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        # Ejercita el context_factory real con tenant mock.
        built = kwargs["context_factory"](500)
        captured["built_payload"] = built.payload
        return {"ok": True, "agent": kwargs["agent"]}

    monkeypatch.setattr(job_tasks, "execute_agent", fake_execute_agent)
    monkeypatch.setattr(ai_context, "require_tenant_id", lambda: tenant_id)

    job = type(
        "Job",
        (),
        {"id": uuid.uuid4(), "tenant_id": tenant_id, "dossier_id": None},
    )()
    result = job_tasks._execute_ai(
        "market_competitor_discovery",
        {
            "description": "Descubrimiento de competidores en storage",
            "own_offer": "EPC",
            "sectors": ["energy"],
            "countries": ["ES"],
            "languages": ["es"],
            "known_names": [],
        },
        job,
    )
    assert result["ok"] is True
    assert captured["agent"] == "market_competitor_discovery"
    assert captured["dossier_id"] is None
    assert captured["target_type"] == "market_discovery"
    assert captured["target_id"] == tenant_id
    assert captured["built_payload"]["allowed_evidence_ids"] == []
    assert "no verificada" in captured["built_payload"]["security_instruction"]
