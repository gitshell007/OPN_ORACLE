"""Extra MDEV-06 behavioral coverage: trust hash, material allowlist, legacy loader."""

from __future__ import annotations

import hashlib
import json
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from opn_oracle.ai.provider import AIUnavailable, LLMRequest, SignalGovernedLLMProvider
from opn_oracle.ai.schemas import DossierQuestionAnswerOutput
from opn_oracle.integrations.memory_ask_dual import (
    build_oracle_authority_block,
    link_snapshot_run_usage,
    load_oracle_authority_from_session,
    validate_citations_allowlist,
    validate_material_evidence_allowlist,
)


def _safe(**overrides: Any) -> dict[str, Any]:
    base = {
        "answer_text": "Respuesta segura.",
        "facts": [],
        "inferences": [],
        "recommendations": [],
        "confidence": 0,
        "open_questions": [],
        "warnings": [],
        "citations": [],
        "claims": [],
        "conflicts": [],
        "unknowns": [],
    }
    base.update(overrides)
    return base


def test_validated_output_hash_is_canonical_and_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted = _safe(answer_text="Hash estable RT-07.")

    def post(url: str, **kwargs: object) -> httpx.Response:
        del kwargs
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "provider": "mock",
                "model": "m",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "runtime": {
                    "runtime_id": "RT-07",
                    "prompt_sha256": "p" * 64,
                    "schema_sha256": "s" * 64,
                },
                "result": {"message": {"content": json.dumps(_safe(answer_text="EVIL"))}},
                "validated_output": {**trusted, "citation_count": 0, "schema_version": "v1"},
            },
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post)
    provider = SignalGovernedLLMProvider(
        base_url="https://signal.test", api_key="k", timeout_seconds=2
    )
    request = LLMRequest(
        agent="dossier_question_answer",
        model="m",
        system_prompt="s",
        task_prompt="t",
        context={"allowed_evidence_ids": []},
        max_output_tokens=50,
        classification="public",
    )
    result = provider.generate_structured(request, DossierQuestionAnswerOutput)
    candidate = {
        k: v
        for k, v in {**trusted, "citation_count": 0, "schema_version": "v1"}.items()
        if k not in {"citation_count", "schema_version", "validated_output_sha256"}
    }
    expected = hashlib.sha256(
        json.dumps(candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    assert result.validated_output_sha256 == expected
    assert result.output.answer_text == "Hash estable RT-07."


def test_incomplete_runtime_meta_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def post(url: str, **kwargs: object) -> httpx.Response:
        del kwargs
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "provider": "mock",
                "model": "m",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "runtime": {"runtime_id": "RT-07"},  # missing hashes
                "result": {"message": {"content": "{}"}},
                "validated_output": _safe(),
            },
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post)
    provider = SignalGovernedLLMProvider(
        base_url="https://signal.test", api_key="k", timeout_seconds=2
    )
    request = LLMRequest(
        agent="dossier_question_answer",
        model="m",
        system_prompt="s",
        task_prompt="t",
        context={"allowed_evidence_ids": []},
        max_output_tokens=50,
        classification="public",
    )
    with pytest.raises(AIUnavailable, match="runtime"):
        provider.generate_structured(request, DossierQuestionAnswerOutput)


def test_material_allowlist_rejects_missing_and_non_object() -> None:
    bad = validate_material_evidence_allowlist(
        ["not-a-dict", {"statement": "x"}, {"statement": "y", "evidence_ids": []}],
        ["ev-1"],
        kind="claims",
    )
    assert "claims:<non-object>" in bad
    assert "claims:missing_evidence" in bad
    ok = validate_material_evidence_allowlist(
        [{"statement": "ok", "evidence_ids": ["ev-1"]}],
        ["ev-1"],
        kind="facts",
    )
    assert ok == []


def test_link_snapshot_preserves_core_and_adds_post_links() -> None:
    snap = {
        "mode": "augment",
        "items": [{"id": "1"}],
        "allowed_evidence_ids": ["e1"],
        "extra": "keep",
    }
    linked = link_snapshot_run_usage(snap, run_id="run-1", usage_log_id="u-1", attempts=2)
    assert linked["mode"] == "augment"
    assert linked["items"] == [{"id": "1"}]
    assert linked["extra"] == "keep"
    assert linked["post_links"]["run_id"] == "run-1"
    assert linked["post_links"]["usage_log_id"] == "u-1"
    assert linked["post_links"]["attempts"] == 2
    assert "linked_at" in linked["post_links"]


def test_build_oracle_authority_marks_loaded_when_intent_present() -> None:
    block = build_oracle_authority_block(
        dossier_id="d",
        tenant_id="t",
        question="q",
        intent={"content_hash": "abc", "status": "accepted"},
        requirements=[{"id": "r1"}],
    )
    assert block["authority_loaded"] is True
    assert block["intent_hash"] == "abc"
    assert block["untrusted_external"] is False


def test_load_oracle_authority_none_dossier_returns_empty_block() -> None:
    session = MagicMock()
    session.scalar.return_value = None
    block = load_oracle_authority_from_session(
        session,
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        question="?",
    )
    assert block["authority_loaded"] is False
    assert block["intent"] == {}


def test_load_oracle_authority_with_intent_id_queries_revision() -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    dossier = SimpleNamespace(
        id=dossier_id, tenant_id=tenant_id, current_intent_revision_id=intent_id
    )
    intent = SimpleNamespace(
        id=intent_id,
        version=2,
        schema_key="custom",
        schema_version="v1",
        request_text="decidir",
        structured_spec={"x": 1},
        content_hash="hash-intent",
        status="accepted",
    )
    session = MagicMock()
    # first scalar: dossier; next: accepted intent; rest empty lists via scalars.
    session.scalar.side_effect = [dossier, intent]
    session.scalars.return_value = []
    block = load_oracle_authority_from_session(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        question="q",
    )
    assert block["intent"]["content_hash"] == "hash-intent"
    assert block["intent_hash"] == "hash-intent"
    assert block["authority_loaded"] is True


def test_citations_reject_non_object_and_missing_id() -> None:
    accepted, rejected = validate_citations_allowlist(
        [None, {"quote": "no-id"}, {"evidence_id": "ok", "quote": "x"}],
        ["ok"],
    )
    assert len(accepted) == 1
    assert "<non-object>" in rejected
    assert "<missing>" in rejected
