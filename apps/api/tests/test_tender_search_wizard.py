from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from flask import g
from pydantic import ValidationError

from opn_oracle.ai import context as ai_context
from opn_oracle.ai import routes as ai_routes
from opn_oracle.ai.context import (
    build_tender_search_replan_context,
    build_tender_search_wizard_context,
)
from opn_oracle.ai.provider import LLMRequest, MockLLMProvider, OllamaLLMProvider
from opn_oracle.ai.registry import PromptRegistry
from opn_oracle.ai.schemas import TenderSearchWizardOutput
from opn_oracle.ai.tender_search_wizard import (
    TenderSearchPlanValidationError,
    postvalidate_tender_search_plan,
)
from opn_oracle.auth import permissions
from opn_oracle.integrations import procurement
from opn_oracle.jobs import tasks as job_tasks
from opn_oracle.oracle import (
    procurement_search_feedback,
    procurement_search_profile_routes,
)
from opn_oracle.oracle.cpv_taxonomy import load_cpv_taxonomy
from opn_oracle.platform.models import User


def _plan(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "intent_summary": "Buscar equipos de protección para servicios de emergencia.",
        "include_terms": ["protección personal"],
        "synonyms": ["equipos"],
        "exclude_terms": ["vestuario escolar"],
        "candidate_cpv": [{"code": "18100000", "label": None}],
        "buyers": ["Consorcios de bomberos"],
        "geographies": ["España"],
        "scope": "active",
        "min_amount": None,
        "max_amount": None,
        "assumptions": [],
        "questions": [],
        "confidence": 70,
        "discarded_count": 0,
        "discarded_reasons": {},
    }
    value.update(overrides)
    return value


def test_registry_exposes_governed_tender_search_wizard() -> None:
    prompt = PromptRegistry().get("tender_search_wizard")

    assert prompt.version == "v2"
    assert prompt.schema is TenderSearchWizardOutput
    assert prompt.requires_evidence_review is False
    assert prompt.evidence_review_failure_policy == "not_required"
    assert prompt.max_output_tokens == 3000
    assert "no aceptes el plan" in prompt.text
    assert "feedback_digest" in prompt.input_contract


def test_tender_search_wizard_rejects_unknown_scope() -> None:
    with pytest.raises(ValidationError):
        TenderSearchWizardOutput.model_validate(_plan(scope="closed"))


def test_postvalidation_labels_cpvs_and_exposes_every_discard_reason() -> None:
    taxonomy = load_cpv_taxonomy()
    result = postvalidate_tender_search_plan(
        _plan(
            include_terms=["Protección personal", "suministro"],
            synonyms=["protección", "EQUIPOS"],
            exclude_terms=["equipos", "riesgo"],
            candidate_cpv=[
                {"code": "18100000-0", "label": "Etiqueta inventada"},
                {"code": "18100000", "label": None},
                {"code": "99999999", "label": None},
                {"code": "no-es-cpv", "label": None},
            ],
        )
    )

    assert result["candidate_cpv"] == [{"code": "18100000", "label": taxonomy.codes["18100000"]}]
    assert result["include_terms"] == ["personal", "proteccion"]
    assert result["synonyms"] == ["equipos"]
    assert result["exclude_terms"] == ["riesgo"]
    assert result["discarded_count"] == 7
    assert result["discarded_reasons"] == {
        "cpv_label_mismatch": 1,
        "duplicate_cpv": 1,
        "duplicate_or_conflicting_term": 2,
        "invalid_cpv_format": 1,
        "term_without_search_tokens": 1,
        "unknown_cpv": 1,
    }


def test_acceptance_mode_rejects_silent_cpv_label_replacement() -> None:
    with pytest.raises(TenderSearchPlanValidationError, match="cpv_label_mismatch=1"):
        postvalidate_tender_search_plan(
            _plan(candidate_cpv=[{"code": "18100000", "label": "Otra etiqueta"}]),
            reject_discards=True,
        )


def test_postvalidation_rejects_inverted_amount_range() -> None:
    with pytest.raises(TenderSearchPlanValidationError, match="importe mínimo"):
        postvalidate_tender_search_plan(_plan(min_amount="200", max_amount="100"))


def test_context_grounds_only_measured_comparable_aggregates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    captured: dict[str, Any] = {}

    def fake_profile(*, tenant_id: str, company: str) -> dict[str, Any]:
        captured.update(tenant_id=tenant_id, company=company)
        return {
            "schema": "procurement-comparable-profile-v1",
            "company_normalized_by_signal": "COMPARABLE",
            "cache_hit": True,
            "raw_rows": [{"must": "not cross"}],
            "corpus": {"aggregated_contracts": 12},
            "frequent_cpvs": {"items": [{"code": "18100000", "label": "Ropa", "contracts": 8}]},
            "title_terms": {"items": [{"term": "proteccion", "contracts": 7}]},
            "buyers": [{"buyer": "Consorcio", "contracts": 6}],
            "measurement_contract": {"llm_calls": 0},
        }

    monkeypatch.setattr(ai_context, "require_tenant_id", lambda: tenant_id)
    monkeypatch.setattr(procurement, "cached_comparable_profile", fake_profile)

    context = build_tender_search_wizard_context(
        description="  Fabricamos   equipos de protección  ",
        comparable="  Comparable  ",
        max_tokens=1000,
    )

    assert captured == {"tenant_id": str(tenant_id), "company": "Comparable"}
    assert context.manifest["dossier_id"] is None
    assert context.evidence == ()
    assert context.payload["mode"] == "initial"
    assert context.payload["description"] == "Fabricamos equipos de protección"
    assert context.payload["comparable_profile"]["top_cpvs"][0]["code"] == "18100000"
    assert "raw_rows" not in context.payload["comparable_profile"]
    assert "cache_hit" not in context.payload["comparable_profile"]


def test_replan_context_hash_uses_semantics_not_volatile_profile_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    digest = {
        "schema": "procurement-search-feedback-digest-v1",
        "profile_id": str(profile_id),
        "plan_version": 2,
        "digest_hash": "a" * 64,
        "feedback_state_hash": "b" * 64,
        "new_feedback_count": 3,
        "counts": {
            "total": 3,
            "distinct_folders": 3,
            "relevant": 1,
            "not_relevant": 2,
        },
        "reasons": {"wrong_sector": 2},
        "exclusion_candidates": {
            "terms": [{"value": "limpieza", "count": 2, "relevant_count": 0, "delta": 2}],
            "cpvs": [],
        },
        "reinforcement_candidates": {
            "terms": [{"value": "bomberos", "count": 1, "relevant_count": 1, "delta": -1}],
            "cpvs": [],
        },
        "tokenizer_version": "spanish-procurement-stopwords-v1",
        "taxonomy_version": "2008",
    }
    monkeypatch.setattr(ai_context, "require_tenant_id", lambda: tenant_id)

    first = build_tender_search_replan_context(
        description="Fabricamos equipos para bomberos",
        accepted_plan=_plan(),
        feedback_digest=digest,
        profile_id=profile_id,
        profile_version=2,
        accepted_plan_hash="c" * 64,
        digest_hash="a" * 64,
        max_tokens=2_000,
    )
    second = build_tender_search_replan_context(
        description="Fabricamos equipos para bomberos",
        accepted_plan=_plan(),
        feedback_digest={
            **digest,
            "plan_version": 99,
            "new_feedback_count": 0,
            "digest_hash": "d" * 64,
        },
        profile_id=profile_id,
        profile_version=99,
        accepted_plan_hash="e" * 64,
        digest_hash="d" * 64,
        max_tokens=2_000,
    )

    assert first.context_hash == second.context_hash
    assert first.payload["mode"] == "replan"
    assert first.payload["feedback_digest"]["counts"]["not_relevant"] == 2
    assert "profile_id" not in first.payload["feedback_digest"]
    assert first.manifest["profile_version"] == 2
    assert second.manifest["profile_version"] == 99


def test_mock_wizard_is_deterministic_and_schema_valid() -> None:
    schema = TenderSearchWizardOutput
    request = LLMRequest(
        agent="tender_search_wizard",
        model="mock-oracle-v1",
        system_prompt="system",
        task_prompt="task",
        context={
            "description": "Fabricamos equipos de protección",
            "comparable_profile": {
                "top_cpvs": [{"code": "18100000"}],
                "top_terms": [{"term": "proteccion"}],
                "top_buyers": [{"buyer": "Consorcio"}],
            },
        },
        max_output_tokens=3000,
        classification="internal",
    )
    provider = MockLLMProvider("seed")

    first = provider.generate_structured(request, schema)
    second = provider.generate_structured(request, schema)
    first_plan = postvalidate_tender_search_plan(first.output)
    second_plan = postvalidate_tender_search_plan(second.output)

    assert first_plan == second_plan
    assert first_plan["scope"] == "active"
    assert first_plan["candidate_cpv"][0]["code"] == "18100000"


def test_mock_wizard_replans_from_deterministic_feedback_digest() -> None:
    accepted = _plan(
        include_terms=["proteccion", "limpieza"],
        exclude_terms=[],
    )
    request = LLMRequest(
        agent="tender_search_wizard",
        model="mock-oracle-v1",
        system_prompt="system",
        task_prompt="task",
        context={
            "mode": "replan",
            "description": "Fabricamos equipos para bomberos",
            "accepted_plan": accepted,
            "feedback_digest": {
                "exclusion_candidates": {
                    "terms": [{"value": "limpieza", "count": 3}],
                    "cpvs": [],
                },
                "reinforcement_candidates": {
                    "terms": [{"value": "bomberos", "count": 2}],
                    "cpvs": [],
                },
            },
        },
        max_output_tokens=3_000,
        classification="internal",
    )

    result = MockLLMProvider("seed").generate_structured(
        request,
        TenderSearchWizardOutput,
    )
    replanned = postvalidate_tender_search_plan(result.output)

    assert replanned["include_terms"] == ["proteccion", "bomberos"]
    assert replanned["exclude_terms"] == ["limpieza"]
    assert any("digest determinista" in item for item in replanned["assumptions"])


def test_ollama_disables_thinking_only_for_tender_wizard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = TenderSearchWizardOutput
    request = LLMRequest(
        agent="tender_search_wizard",
        model="qwen3.5:9b",
        system_prompt="system",
        task_prompt="task",
        context={"description": "Fabricamos equipos de protección"},
        max_output_tokens=3000,
        classification="internal",
    )
    output = MockLLMProvider("fixture").generate_structured(request, schema).output

    def post(url: str, **kwargs: Any) -> httpx.Response:
        body = kwargs["json"]
        assert isinstance(body, dict)
        assert body["format"] == "json"
        assert body["think"] is False
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"message": {"content": output.model_dump_json()}},
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post)
    provider = OllamaLLMProvider(
        base_url="http://ollama.test",
        model="qwen3.5:9b",
        timeout_seconds=3,
    )

    result = provider.generate_structured(request, schema)

    assert result.output == output


@contextmanager
def _authenticated_ai(app: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[uuid.UUID]:
    user = User(
        id=uuid.uuid4(),
        email="tender-wizard@example.com",
        display_name="Tender wizard",
        status="active",
    )
    tenant_id = uuid.uuid4()
    principal = type("Principal", (), {"id": user.id, "is_authenticated": True})()
    monkeypatch.setattr(permissions, "current_user", principal)
    monkeypatch.setattr(ai_routes, "current_user", principal)
    monkeypatch.setattr(procurement_search_profile_routes, "current_user", principal)
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


def test_tender_search_wizard_http_enqueues_dossierless_tenant_job(
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
    monkeypatch.setattr(ai_routes, "_latest_tender_search_artifact", lambda: None)

    with _authenticated_ai(app, monkeypatch) as tenant_id:
        response = client.post(
            "/api/v1/ai/tender-search-wizard/runs",
            json={
                "description": "  Fabricamos   equipos de protección  ",
                "comparable": " Comparable ",
            },
            headers={"Idempotency-Key": "tender-wizard-1"},
        )

    assert response.status_code == 202
    assert captured["task_name"] == "oracle.ai.tender_search_wizard"
    assert captured["payload"] == {
        "mode": "initial",
        "description": "Fabricamos equipos de protección",
        "comparable": "Comparable",
    }
    assert "dossier_id" not in captured
    assert captured["resource_type"] == "tenant_search_profile"
    assert captured["resource_id"] == tenant_id


def test_tender_search_wizard_http_requires_idempotency_key(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _authenticated_ai(app, monkeypatch):
        response = client.post(
            "/api/v1/ai/tender-search-wizard/runs",
            json={"description": "Fabricamos equipos de protección"},
        )

    assert response.status_code == 428
    assert response.headers["Content-Type"] == "application/problem+json"
    assert response.get_json()["code"] == "precondition_required"
    assert "Idempotency-Key" in response.get_json()["detail"]


def test_tender_search_replan_http_enqueues_profile_scoped_snapshot(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_id = uuid.uuid4()
    captured: dict[str, Any] = {}
    profile = type(
        "Profile",
        (),
        {
            "id": profile_id,
            "version": 3,
            "accepted_plan_hash": bytes.fromhex("ab" * 32),
        },
    )()

    monkeypatch.setattr(
        procurement_search_profile_routes,
        "get_procurement_search_profile",
        lambda session, requested_id: profile,
    )
    monkeypatch.setattr(
        procurement_search_feedback,
        "build_procurement_search_feedback_digest",
        lambda session, requested_id: {"digest_hash": "cd" * 32},
    )

    def fake_enqueue(task_name: str, **kwargs: Any) -> Any:
        captured["task_name"] = task_name
        captured.update(kwargs)
        return type("Job", (), {"id": uuid.uuid4(), "status": "queued"})()

    monkeypatch.setattr(procurement_search_profile_routes, "enqueue_job", fake_enqueue)
    monkeypatch.setattr(
        procurement_search_profile_routes,
        "serialize_job",
        lambda job: {"id": str(job.id), "status": job.status},
    )
    monkeypatch.setattr(
        procurement_search_profile_routes,
        "_latest_replan_artifact",
        lambda requested_id: None,
    )

    with _authenticated_ai(app, monkeypatch):
        response = client.post(
            f"/api/v1/procurement-search-profiles/{profile_id}/replans",
            json={"expected_version": 3, "digest_hash": "cd" * 32},
            headers={"Idempotency-Key": "profile-replan-1"},
        )

    assert response.status_code == 202
    assert response.get_json()["artifact"] is None
    assert captured["task_name"] == "oracle.ai.tender_search_wizard"
    assert captured["payload"] == {
        "mode": "replan",
        "profile_id": str(profile_id),
        "expected_profile_version": 3,
        "expected_plan_hash": "ab" * 32,
        "expected_digest_hash": "cd" * 32,
    }
    assert captured["resource_type"] == "procurement_search_profile"
    assert captured["resource_id"] == profile_id


def test_tender_search_replan_job_rechecks_snapshot_before_ai(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    accepted = _plan()
    digest = {
        "schema": "procurement-search-feedback-digest-v1",
        "digest_hash": "cd" * 32,
        "counts": {
            "total": 1,
            "distinct_folders": 1,
            "relevant": 0,
            "not_relevant": 1,
        },
        "reasons": {"wrong_sector": 1},
        "exclusion_candidates": {
            "terms": [{"value": "limpieza", "count": 1}],
            "cpvs": [],
        },
        "reinforcement_candidates": {"terms": [], "cpvs": []},
        "tokenizer_version": "spanish-procurement-stopwords-v1",
        "taxonomy_version": "2008",
    }
    profile = SimpleNamespace(
        id=profile_id,
        version=3,
        accepted_plan_hash=bytes.fromhex("ab" * 32),
        accepted_plan=accepted,
        original_description="Fabricamos equipos para bomberos",
    )
    captured: dict[str, Any] = {}
    monkeypatch.setattr(job_tasks, "get_procurement_search_profile", lambda session, value: profile)
    monkeypatch.setattr(
        procurement_search_feedback,
        "build_procurement_search_feedback_digest",
        lambda session, value: digest,
    )
    monkeypatch.setattr(ai_context, "require_tenant_id", lambda: tenant_id)

    def fake_execute_agent(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        captured["context"] = kwargs["context_factory"](2_000)
        return {"artifact_id": str(uuid.uuid4()), "status": "candidate"}

    monkeypatch.setattr(job_tasks, "execute_agent", fake_execute_agent)
    payload = {
        "mode": "replan",
        "profile_id": str(profile_id),
        "expected_profile_version": 3,
        "expected_plan_hash": "ab" * 32,
        "expected_digest_hash": "cd" * 32,
    }

    with app.app_context():
        result = job_tasks._execute_ai(
            "tender_search_wizard",
            payload,
            SimpleNamespace(tenant_id=tenant_id),
        )

    assert result["status"] == "candidate"
    assert captured["target_type"] == "procurement_search_profile"
    assert captured["target_id"] == profile_id
    assert captured["context"].payload["mode"] == "replan"
    assert captured["context"].payload["feedback_digest"]["counts"]["total"] == 1


def test_tender_search_replan_job_refuses_changed_feedback_before_ai(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_id = uuid.uuid4()
    profile = SimpleNamespace(
        id=profile_id,
        version=3,
        accepted_plan_hash=bytes.fromhex("ab" * 32),
    )
    monkeypatch.setattr(job_tasks, "get_procurement_search_profile", lambda session, value: profile)
    monkeypatch.setattr(
        procurement_search_feedback,
        "build_procurement_search_feedback_digest",
        lambda session, value: {"digest_hash": "ef" * 32},
    )
    monkeypatch.setattr(
        job_tasks,
        "execute_agent",
        lambda **kwargs: pytest.fail("No debe llamar IA con feedback cambiado."),
    )

    with (
        app.app_context(),
        pytest.raises(
            job_tasks.PermanentJobError,
            match="feedback cambió",
        ),
    ):
        job_tasks._execute_ai(
            "tender_search_wizard",
            {
                "mode": "replan",
                "profile_id": str(profile_id),
                "expected_profile_version": 3,
                "expected_plan_hash": "ab" * 32,
                "expected_digest_hash": "cd" * 32,
            },
            SimpleNamespace(tenant_id=uuid.uuid4()),
        )
