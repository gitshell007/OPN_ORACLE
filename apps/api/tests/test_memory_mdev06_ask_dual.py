"""MDEV-06 · dual-memory ask vertical: modes, allowlist, checksum, retryable, tenant."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from opn_oracle.integrations.memory_ask_dual import (
    PERMANENT_ERROR_CODES,
    RETRYABLE_ERROR_CODES,
    _normalize_retrieval_item,
    build_dual_ask_context,
    build_input_manifest,
    build_oracle_authority_block,
    build_signal_factual_block,
    classify_error_code,
    format_allowlist_rejection,
    load_oracle_authority_from_session,
    materialize_augment_items,
    merge_ask_citation_allowlist,
    validate_citations_allowlist,
    validate_material_evidence_allowlist,
)
from opn_oracle.integrations.memory_http_client import classify_http_error
from opn_oracle.jobs.tasks import PermanentJobError, RetriableJobError, _answer_dossier_question
from opn_oracle.oracle import conversations as conv
from opn_oracle.tenants.context import TenantContext, tenant_context


def _item(
    *,
    item_id: str = "sig-1",
    text: str = "El adjudicatario X concentra CPV 35400000.",
    checksum: str = "a" * 64,
    tenant_id: str | None = None,
    dossier_id: str | None = None,
    source_ref: str = "signal://doc/1#chunk-0",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": item_id,
        "text": text,
        "source_ref": source_ref,
        "checksum": checksum,
        "locator": '{"page":1,"chunk":0}',
        "classification": "internal",
        "policy_version": "memory.v1",
        "watermark": "wm-1",
        "kind": "chunk",
        "source_version": "v1",
    }
    if tenant_id:
        row["tenant_id"] = tenant_id
    if dossier_id:
        row["dossier_id"] = dossier_id
    return row


def test_modes_disabled_shadow_augment_distinct() -> None:
    tenant = str(uuid.uuid4())
    dossier = str(uuid.uuid4())
    items = [_item(tenant_id=tenant, dossier_id=dossier)]

    disabled = build_dual_ask_context(
        mode="disabled",
        tenant_id=tenant,
        dossier_id=dossier,
        question="¿Quién concentra el CPV?",
        retrieval_items=items,
        coverage_manifest={"requested": ["q"], "used": [], "failed": [], "excluded": []},
        memory_policy="disabled",
    )
    shadow = build_dual_ask_context(
        mode="shadow",
        tenant_id=tenant,
        dossier_id=dossier,
        question="¿Quién concentra el CPV?",
        retrieval_items=items,
        coverage_manifest={"requested": ["q"], "used": [], "failed": [], "excluded": []},
        memory_policy="memory.v1",
    )
    augment = build_dual_ask_context(
        mode="augment",
        tenant_id=tenant,
        dossier_id=dossier,
        question="¿Quién concentra el CPV?",
        retrieval_items=items,
        coverage_manifest={"requested": ["q"], "used": [], "failed": [], "excluded": []},
        memory_policy="memory.v1",
    )

    assert disabled.signal_factual["items"] == []
    assert disabled.allowed_evidence_ids == ()
    assert shadow.signal_factual["observed_count"] == 1
    assert shadow.signal_factual["items"] == []
    assert shadow.allowed_evidence_ids == ()
    assert shadow.input_manifest["signal_item_count"] == 0
    assert len(augment.signal_factual["items"]) == 1
    assert len(augment.allowed_evidence_ids) == 1
    assert augment.input_manifest["signal_item_count"] == 1
    # Distinct measurable effects
    assert (
        len(disabled.allowed_evidence_ids),
        len(shadow.allowed_evidence_ids),
        len(augment.allowed_evidence_ids),
    ) == (0, 0, 1)


def test_allowlist_precision_100_rejects_foreign() -> None:
    allowed = ["ev-1", "ev-2"]
    accepted, rejected = validate_citations_allowlist(
        [
            {"evidence_id": "ev-1", "quote": "ok"},
            {"evidence_id": "foreign", "quote": "bad"},
            {"evidence_id": "ev-2", "quote": "ok2"},
        ],
        allowed,
    )
    assert [c["evidence_id"] for c in accepted] == ["ev-1", "ev-2"]
    assert rejected == ["foreign"]


def test_merge_ask_allowlist_unions_dual_and_dossier_procurement() -> None:
    """SV2-ASK-FLAKE: dual-only validation rejected legitimate procurement IDs."""
    dual = ["dual-mem-1", "dual-mem-2"]
    procurement = "96272488-1112-4058-8217-a34db67b5bd9"
    authority = {
        "oracle_evidence": [
            {"id": procurement, "source_kind": "procurement"},
            {"id": "bulk-mem-signal", "source_kind": "memory_signal"},
        ]
    }
    merged = merge_ask_citation_allowlist(
        dual,
        oracle_authority=authority,
        extra_dossier_evidence_ids=["doc-ev-1"],
    )
    assert "dual-mem-1" in merged and "dual-mem-2" in merged
    assert procurement in merged
    assert "doc-ev-1" in merged
    # memory_signal from authority is NOT bulk-imported (dual owns those IDs)
    assert "bulk-mem-signal" not in merged
    # Model citing Capgemini PLACSP awards must pass when merged is used
    accepted, rejected = validate_citations_allowlist(
        [
            {"evidence_id": "dual-mem-1", "quote": "Laura"},
            {"evidence_id": procurement, "quote": "Capgemini PLACSP"},
        ],
        merged,
    )
    assert rejected == []
    assert len(accepted) == 2
    msg = format_allowlist_rejection(["foreign-id"], merged)
    assert "foreign-id" in msg and "allowlist_size=" in msg


def test_signal_factual_items_omit_signal_item_id() -> None:
    """Never teach non-citable memory fact/chunk IDs to the model."""
    from opn_oracle.integrations.memory_contract_v1 import MaterializedCitation

    citation = MaterializedCitation(
        oracle_evidence_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        signal_item_id="fact:39502",
        source_ref="fact:39502",
        checksum="a" * 64,
        exact_excerpt="company.legal_name: Capgemini",
        classification="internal",
        locator='{"k":1}',
        occurred_at=None,
        policy_version="memory.v1",
        watermark="wm-1",
        tenant_id=str(uuid.uuid4()),
        dossier_id=str(uuid.uuid4()),
    )
    block = build_signal_factual_block(
        mode="augment", citations=[citation], observed_count=1
    )
    assert len(block["items"]) == 1
    assert "signal_item_id" not in block["items"][0]
    assert block["items"][0]["evidence_id"] == citation.oracle_evidence_id


def test_empty_allowlist_rejects_any_citation_and_material_facts() -> None:
    """Oracle local defense must fail closed even when remote RT-07 is bypassed."""
    accepted, rejected = validate_citations_allowlist(
        [{"evidence_id": "anything", "quote": "x"}],
        [],
    )
    assert accepted == []
    assert rejected == ["anything"]
    # Safe answer: zero citations → no rejects
    accepted2, rejected2 = validate_citations_allowlist([], [])
    assert accepted2 == [] and rejected2 == []
    assert validate_material_evidence_allowlist(
        [{"statement": "Hecho", "evidence_ids": ["ev-1"]}],
        [],
        kind="facts",
    )
    assert not validate_material_evidence_allowlist([], [], kind="facts")
    assert validate_material_evidence_allowlist(
        [{"statement": "Claim", "evidence_ids": ["foreign"]}],
        ["ev-ok"],
        kind="claims",
    ) == ["foreign"]


def test_load_oracle_authority_tolerates_legacy_dossier_without_intent_attr() -> None:
    """Fixtures/SimpleNamespace without current_intent_revision_id must not crash."""
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    legacy = SimpleNamespace(id=dossier_id, tenant_id=tenant_id)  # no intent attr
    session = MagicMock()
    session.scalar.return_value = legacy
    block = load_oracle_authority_from_session(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        question="¿legacy?",
    )
    assert block["block"] == "oracle_authority"
    assert block["dossier_id"] == str(dossier_id)
    assert block["intent"] == {}
    assert block["authority_loaded"] is False


def test_answer_via_signal_empty_allowlist_rejects_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opn_oracle.oracle.conversations import ConversationError, _answer_via_signal

    artifact_id = uuid.uuid4()
    artifact = SimpleNamespace(
        id=artifact_id,
        provider="mock",
        model="m",
        output={
            "answer_text": "Cita ilegal con allowlist vacía.",
            "citations": [{"evidence_id": "foreign", "quote": "x"}],
            "facts": [],
            "claims": [],
            "conflicts": [],
            "inferences": [],
            "recommendations": [],
            "confidence": 10,
            "open_questions": [],
            "warnings": [],
        },
    )
    session = MagicMock()
    session.get.return_value = artifact
    monkeypatch.setattr(
        "opn_oracle.ai.service.execute_agent",
        lambda **_k: {"artifact_id": str(artifact_id), "audit_log_id": "a"},
    )
    job = SimpleNamespace(id=uuid.uuid4(), cancel_requested=False)
    with pytest.raises(ConversationError, match="allowlist"):
        _answer_via_signal(
            session,
            job=job,  # type: ignore[arg-type]
            dossier_id=uuid.uuid4(),
            message=SimpleNamespace(id=uuid.uuid4(), content_text="q"),  # type: ignore[arg-type]
            memory_items=[],
            coverage={},
            memory_policy="disabled",
            allowed_evidence_ids=[],
        )


def test_answer_via_signal_empty_allowlist_rejects_material_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opn_oracle.oracle.conversations import ConversationError, _answer_via_signal

    artifact_id = uuid.uuid4()
    artifact = SimpleNamespace(
        id=artifact_id,
        provider="mock",
        model="m",
        output={
            "answer_text": "Afirmación material sin Evidence permitida.",
            "citations": [],
            "facts": [{"statement": "Hecho no permitido", "evidence_ids": ["ev-x"]}],
            "claims": [],
            "conflicts": [],
            "inferences": [],
            "recommendations": [],
            "confidence": 10,
            "open_questions": [],
            "warnings": [],
        },
    )
    session = MagicMock()
    session.get.return_value = artifact
    monkeypatch.setattr(
        "opn_oracle.ai.service.execute_agent",
        lambda **_k: {"artifact_id": str(artifact_id), "audit_log_id": "a"},
    )
    job = SimpleNamespace(id=uuid.uuid4(), cancel_requested=False)
    with pytest.raises(ConversationError, match="facts/claims"):
        _answer_via_signal(
            session,
            job=job,  # type: ignore[arg-type]
            dossier_id=uuid.uuid4(),
            message=SimpleNamespace(id=uuid.uuid4(), content_text="q"),  # type: ignore[arg-type]
            memory_items=[],
            coverage={},
            memory_policy="disabled",
            allowed_evidence_ids=[],
        )


def test_answer_via_signal_safe_answer_empty_allowlist_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opn_oracle.oracle.conversations import _answer_via_signal

    artifact_id = uuid.uuid4()
    artifact = SimpleNamespace(
        id=artifact_id,
        provider="mock",
        model="m",
        output={
            "answer_text": "Sin evidencia autorizada; no se afirman hechos materiales.",
            "citations": [],
            "facts": [],
            "claims": [],
            "conflicts": [],
            "inferences": [],
            "recommendations": [],
            "confidence": 0,
            "open_questions": ["evidencia"],
            "warnings": ["empty_allowlist"],
            "validated_output_sha256": "b" * 64,
        },
    )
    session = MagicMock()
    session.get.return_value = artifact
    monkeypatch.setattr(
        "opn_oracle.ai.service.execute_agent",
        lambda **_k: {"artifact_id": str(artifact_id), "audit_log_id": "a"},
    )
    job = SimpleNamespace(id=uuid.uuid4(), cancel_requested=False)
    result = _answer_via_signal(
        session,
        job=job,  # type: ignore[arg-type]
        dossier_id=uuid.uuid4(),
        message=SimpleNamespace(id=uuid.uuid4(), content_text="q"),  # type: ignore[arg-type]
        memory_items=[],
        coverage={},
        memory_policy="disabled",
        allowed_evidence_ids=[],
    )
    assert (
        "evidencia autorizada" in result["answer_text"].lower()
        or "sin evidencia" in result["answer_text"].lower()
    )
    assert result["answer_payload"]["citations"] == []
    assert result["answer_payload"]["validated_output_sha256"] == "b" * 64


def test_checksum_change_rematerializes_new_evidence_id() -> None:
    tenant = str(uuid.uuid4())
    dossier = str(uuid.uuid4())
    first = _item(checksum="b" * 64, tenant_id=tenant, dossier_id=dossier)
    c1, _m1, ex1 = materialize_augment_items([first], tenant_id=tenant, dossier_id=dossier)
    assert len(c1) == 1 and not ex1
    eid1 = c1[0].oracle_evidence_id

    # Same source_ref/locator but new checksum → new evidence id (no stale reuse).
    second = _item(checksum="c" * 64, tenant_id=tenant, dossier_id=dossier)
    existing = [
        {
            "source_ref": first["source_ref"],
            "checksum": first["checksum"],
            "locator": first["locator"],
            "oracle_evidence_id": eid1,
            "tenant_id": tenant,
            "dossier_id": dossier,
            "exact_excerpt": first["text"],
        }
    ]
    c2, m2, ex2 = materialize_augment_items(
        [second],
        tenant_id=tenant,
        dossier_id=dossier,
        existing_mappings=existing,
    )
    assert len(c2) == 1 and not ex2
    assert c2[0].oracle_evidence_id != eid1
    assert m2[0].checksum == "c" * 64


def test_tenant_mismatch_excludes_item() -> None:
    tenant = str(uuid.uuid4())
    dossier = str(uuid.uuid4())
    other = str(uuid.uuid4())
    items = [_item(tenant_id=other, dossier_id=dossier)]
    c, m, ex = materialize_augment_items(items, tenant_id=tenant, dossier_id=dossier)
    assert c == [] and m == []
    assert ex and ex[0]["reason"] == "tenant_or_dossier_mismatch"


def test_shadow_manifest_zero_items_even_if_retrieval_nonempty() -> None:
    tenant = str(uuid.uuid4())
    dossier = str(uuid.uuid4())
    ctx = build_dual_ask_context(
        mode="shadow",
        tenant_id=tenant,
        dossier_id=dossier,
        question="q",
        retrieval_items=[_item(tenant_id=tenant, dossier_id=dossier)],
        coverage_manifest={},
        memory_policy="memory.v1",
    )
    assert ctx.input_manifest["signal_item_count"] == 0
    assert ctx.input_manifest["allowed_evidence_ids"] == []
    assert ctx.input_manifest["evidence_hashes"] == []
    # Deterministic hash for empty injection
    m2, h2 = build_input_manifest(
        mode="shadow",
        oracle_authority=ctx.oracle_authority,
        signal_factual=ctx.signal_factual,
        allowed_evidence_ids=[],
        coverage=ctx.coverage,
        memory_policy="memory.v1",
    )
    assert m2["signal_item_count"] == 0
    assert isinstance(h2, str) and len(h2) == 64


def test_retryable_classification_http_and_codes() -> None:
    assert classify_http_error(408)[1] is True
    assert classify_http_error(429)[1] is True
    assert classify_http_error(503)[1] is True
    assert classify_http_error(500)[1] is True
    assert classify_http_error(401)[1] is False
    assert classify_http_error(403)[1] is False
    assert classify_http_error(422)[1] is False
    for code in RETRYABLE_ERROR_CODES:
        assert classify_error_code(code) is True
    for code in PERMANENT_ERROR_CODES:
        assert classify_error_code(code) is False


def test_oracle_authority_block_separated() -> None:
    block = build_oracle_authority_block(
        dossier_id=str(uuid.uuid4()),
        tenant_id=str(uuid.uuid4()),
        question="q",
        intent={"accepted": True},
        requirements=["r1"],
    )
    assert block["block"] == "oracle_authority"
    assert block["untrusted_external"] is False
    assert block["intent"]["accepted"] is True


def test_handler_retryable_vs_permanent_classification(monkeypatch: pytest.MonkeyPatch) -> None:
    import opn_oracle.jobs.tasks as tasks_mod
    from opn_oracle.integrations.memory_ask_dual import (
        PermanentMemoryAskError,
        RetryableMemoryAskError,
    )

    job = SimpleNamespace(id=uuid.uuid4(), cancel_requested=False)
    # Arguments evaluate before the call; stub session so no Flask app context is required.
    monkeypatch.setattr(tasks_mod.db, "session", lambda: MagicMock())

    def raise_retry(*_a: Any, **_k: Any) -> Any:
        raise RetryableMemoryAskError("timeout", code="timeout")

    def raise_perm(*_a: Any, **_k: Any) -> Any:
        raise PermanentMemoryAskError("auth", code="auth_or_scope")

    monkeypatch.setattr(tasks_mod, "process_dossier_question_answer", raise_retry)
    with pytest.raises(RetriableJobError):
        _answer_dossier_question({"message_id": "x"}, job)  # type: ignore[arg-type]

    monkeypatch.setattr(tasks_mod, "process_dossier_question_answer", raise_perm)
    with pytest.raises(PermanentJobError):
        _answer_dossier_question({"message_id": "x"}, job)  # type: ignore[arg-type]


def test_process_answer_augment_injects_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant = uuid.uuid4()
    dossier = uuid.uuid4()
    conversation = uuid.uuid4()
    message_id = uuid.uuid4()
    item = _item(tenant_id=str(tenant), dossier_id=str(dossier))

    class AugmentAdapter:
        effective_mode = "augment"

        def retrieve(self, scope: Any, query: str, purpose: str, limit: int) -> dict[str, Any]:
            return {
                "items": [item],
                "items_for_prompt": [item],
                "coverage_manifest": {
                    "requested": ["q"],
                    "used": [],
                    "failed": [],
                    "excluded": [],
                },
                "policy_version": "memory.v1",
            }

    msg = SimpleNamespace(
        id=message_id,
        tenant_id=tenant,
        dossier_id=dossier,
        conversation_id=conversation,
        role="user",
        status="queued",
        content_text="¿Quién concentra el CPV?",
        answer_payload={},
        coverage_manifest={},
        error_code=None,
        error_message=None,
        background_job_id=None,
    )
    job = SimpleNamespace(
        id=uuid.uuid4(),
        cancel_requested=False,
        correlation_id="corr-1",
        attempt_count=1,
    )
    session = MagicMock()
    session.refresh = MagicMock()
    session.get = MagicMock(return_value=None)
    session.scalar = MagicMock(return_value=None)
    session.flush = MagicMock()
    session.add = MagicMock()

    monkeypatch.setattr(conv, "get_message", lambda *a, **k: msg)
    monkeypatch.setattr(conv, "append_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(conv, "_signal_ai_enabled", lambda: False)
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.load_oracle_authority_from_session",
        lambda *a, **k: build_oracle_authority_block(
            dossier_id=str(dossier),
            tenant_id=str(tenant),
            question="¿Quién concentra el CPV?",
            intent={"content_hash": "a" * 64, "status": "accepted"},
            requirements=[{"id": "req-1", "question": "quién?"}],
            objectives=[{"id": "obj-1", "title": "ganar"}],
            decisions=[{"id": "dec-1", "title": "seguir"}],
            oracle_evidence=[{"id": "ev-oracle-1", "source_kind": "document"}],
        ),
    )

    def _persist(_session: Any, **kwargs: Any) -> list[str]:
        citations = kwargs.get("citations") or []
        return [c.oracle_evidence_id for c in citations]

    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.persist_memory_signal_evidence",
        _persist,
    )

    with tenant_context(TenantContext(tenant_id=tenant, actor_id=uuid.uuid4())):
        result = conv.process_dossier_question_answer(
            session,
            {
                "message_id": str(message_id),
                "conversation_id": str(conversation),
                "dossier_id": str(dossier),
                "memory_mode": "augment",
            },
            job,  # type: ignore[arg-type]
            memory_adapter=AugmentAdapter(),
            memory_mode="augment",
        )

    assert result["memory_mode"] == "augment"
    assert result["item_count"] == 1
    # SV2-ASK-FLAKE: effective allowlist = dual materialization ∪ dossier-citable
    # evidence taught via oracle_authority (here: document ev-oracle-1).
    assert len(result["allowed_evidence_ids"]) == 2
    assert "ev-oracle-1" in result["allowed_evidence_ids"]
    assert msg.status == "succeeded"
    assert msg.answer_payload.get("citations")
    assert msg.answer_payload["citations"][0]["evidence_id"] in result["allowed_evidence_ids"]
    # Authority from loader must reach answer path (via dual / audit)
    assert msg.answer_payload.get("input_manifest_hash")


def test_process_answer_shadow_zero_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant = uuid.uuid4()
    dossier = uuid.uuid4()
    conversation = uuid.uuid4()
    message_id = uuid.uuid4()
    item = _item(tenant_id=str(tenant), dossier_id=str(dossier))

    class ShadowAdapter:
        effective_mode = "shadow"

        def retrieve(self, scope: Any, query: str, purpose: str, limit: int) -> dict[str, Any]:
            return {
                "items": [item],
                "items_for_prompt": [],
                "items_observed": [item],
                "coverage_manifest": {
                    "requested": ["q"],
                    "used": [],
                    "failed": [],
                    "excluded": [],
                },
                "policy_version": "memory.v1",
                "shadow": True,
            }

    msg = SimpleNamespace(
        id=message_id,
        tenant_id=tenant,
        dossier_id=dossier,
        conversation_id=conversation,
        role="user",
        status="queued",
        content_text="pregunta shadow",
        answer_payload={},
        coverage_manifest={},
        error_code=None,
        error_message=None,
        background_job_id=None,
    )
    job = SimpleNamespace(
        id=uuid.uuid4(),
        cancel_requested=False,
        correlation_id="corr-2",
        attempt_count=1,
    )
    session = MagicMock()
    session.refresh = MagicMock()
    session.flush = MagicMock()

    monkeypatch.setattr(conv, "get_message", lambda *a, **k: msg)
    monkeypatch.setattr(conv, "append_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(conv, "_signal_ai_enabled", lambda: False)
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.load_oracle_authority_from_session",
        lambda *a, **k: build_oracle_authority_block(
            dossier_id=str(dossier), tenant_id=str(tenant), question="pregunta shadow"
        ),
    )

    with tenant_context(TenantContext(tenant_id=tenant, actor_id=uuid.uuid4())):
        result = conv.process_dossier_question_answer(
            session,
            {
                "message_id": str(message_id),
                "conversation_id": str(conversation),
                "dossier_id": str(dossier),
            },
            job,  # type: ignore[arg-type]
            memory_adapter=ShadowAdapter(),
            memory_mode="shadow",
        )

    assert result["memory_mode"] == "shadow"
    assert result["item_count"] == 0
    assert result["items_observed"] == 1
    assert result["allowed_evidence_ids"] == []
    assert msg.answer_payload.get("citations") == []


def test_cancel_after_retrieval_no_late_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant = uuid.uuid4()
    dossier = uuid.uuid4()
    conversation = uuid.uuid4()
    message_id = uuid.uuid4()

    class Adapter:
        effective_mode = "disabled"

        def retrieve(self, *a: Any, **k: Any) -> dict[str, Any]:
            return {"items": [], "coverage_manifest": {}, "policy_version": "disabled"}

    msg = SimpleNamespace(
        id=message_id,
        tenant_id=tenant,
        dossier_id=dossier,
        conversation_id=conversation,
        role="user",
        status="queued",
        content_text="q",
        answer_payload={},
        coverage_manifest={},
        error_code=None,
        error_message=None,
        background_job_id=None,
    )
    job = SimpleNamespace(
        id=uuid.uuid4(),
        cancel_requested=False,
        correlation_id="c",
        attempt_count=1,
    )

    def refresh(_obj: Any, attribute_names: Any = None) -> None:
        job.cancel_requested = True

    session = MagicMock()
    session.refresh = refresh
    session.flush = MagicMock()

    monkeypatch.setattr(conv, "get_message", lambda *a, **k: msg)
    monkeypatch.setattr(conv, "_signal_ai_enabled", lambda: False)
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.load_oracle_authority_from_session",
        lambda *a, **k: build_oracle_authority_block(
            dossier_id=str(dossier), tenant_id=str(tenant), question="q"
        ),
    )

    with tenant_context(TenantContext(tenant_id=tenant, actor_id=uuid.uuid4())):
        result = conv.process_dossier_question_answer(
            session,
            {
                "message_id": str(message_id),
                "conversation_id": str(conversation),
                "dossier_id": str(dossier),
            },
            job,  # type: ignore[arg-type]
            memory_adapter=Adapter(),
            memory_mode="disabled",
        )

    assert result.get("cancelled") is True
    assert msg.status == "cancelled"


def test_normalize_excludes_synthetic_and_incomplete() -> None:
    assert _normalize_retrieval_item({"text": "x"}) is None
    assert (
        _normalize_retrieval_item(
            {
                "id": "1",
                "text": "hello",
                "source_ref": "synthetic://mock/1",
                "checksum": "a" * 64,
                "locator": "{}",
                "policy_version": "memory.v1",
                "watermark": "wm",
            }
        )
        is None
    )
    assert (
        _normalize_retrieval_item(
            {
                "id": "1",
                "text": "hello",
                "source_ref": "signal://doc/1",
                # no checksum/version
                "locator": "{}",
                "policy_version": "memory.v1",
                "watermark": "wm",
            }
        )
        is None
    )
    ok = _normalize_retrieval_item(_item())
    assert ok is not None
    assert ok["source_ref"].startswith("signal://")


def test_default_mode_fail_closed_not_augment(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant = uuid.uuid4()
    dossier = uuid.uuid4()
    conversation = uuid.uuid4()
    message_id = uuid.uuid4()
    item = _item(tenant_id=str(tenant), dossier_id=str(dossier))

    class NoModeAdapter:
        # no effective_mode attribute
        def retrieve(self, *a: Any, **k: Any) -> dict[str, Any]:
            return {
                "items": [item],
                "coverage_manifest": {"requested": ["q"], "used": [], "failed": [], "excluded": []},
                "policy_version": "memory.v1",
            }

    msg = SimpleNamespace(
        id=message_id,
        tenant_id=tenant,
        dossier_id=dossier,
        conversation_id=conversation,
        role="user",
        status="queued",
        content_text="q",
        answer_payload={},
        coverage_manifest={},
        error_code=None,
        error_message=None,
        background_job_id=None,
    )
    job = SimpleNamespace(
        id=uuid.uuid4(), cancel_requested=False, correlation_id="c", attempt_count=1
    )
    session = MagicMock()
    session.refresh = MagicMock()
    session.flush = MagicMock()
    session.get = MagicMock(return_value=None)

    monkeypatch.setattr(conv, "get_message", lambda *a, **k: msg)
    monkeypatch.setattr(conv, "append_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(conv, "_signal_ai_enabled", lambda: False)
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.load_oracle_authority_from_session",
        lambda *a, **k: build_oracle_authority_block(
            dossier_id=str(dossier), tenant_id=str(tenant), question="q"
        ),
    )
    monkeypatch.delenv("TESTING", raising=False)

    with tenant_context(TenantContext(tenant_id=tenant, actor_id=uuid.uuid4())):
        result = conv.process_dossier_question_answer(
            session,
            {
                "message_id": str(message_id),
                "conversation_id": str(conversation),
                "dossier_id": str(dossier),
            },
            job,  # type: ignore[arg-type]
            memory_adapter=NoModeAdapter(),
            memory_mode=None,
        )

    assert result["memory_mode"] == "disabled"
    assert result["allowed_evidence_ids"] == []
    assert result["item_count"] == 0


def test_persist_failure_excludes_from_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant = uuid.uuid4()
    dossier = uuid.uuid4()
    conversation = uuid.uuid4()
    message_id = uuid.uuid4()
    item = _item(tenant_id=str(tenant), dossier_id=str(dossier))

    class AugmentAdapter:
        effective_mode = "augment"

        def retrieve(self, *a: Any, **k: Any) -> dict[str, Any]:
            return {
                "items": [item],
                "items_for_prompt": [item],
                "coverage_manifest": {"requested": ["q"], "used": [], "failed": [], "excluded": []},
                "policy_version": "memory.v1",
            }

    msg = SimpleNamespace(
        id=message_id,
        tenant_id=tenant,
        dossier_id=dossier,
        conversation_id=conversation,
        role="user",
        status="queued",
        content_text="q",
        answer_payload={},
        coverage_manifest={},
        error_code=None,
        error_message=None,
        background_job_id=None,
    )
    job = SimpleNamespace(
        id=uuid.uuid4(), cancel_requested=False, correlation_id="c", attempt_count=1
    )
    session = MagicMock()
    session.refresh = MagicMock()
    session.flush = MagicMock()
    session.get = MagicMock(return_value=None)

    monkeypatch.setattr(conv, "get_message", lambda *a, **k: msg)
    monkeypatch.setattr(conv, "append_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(conv, "_signal_ai_enabled", lambda: False)
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.load_oracle_authority_from_session",
        lambda *a, **k: build_oracle_authority_block(
            dossier_id=str(dossier), tenant_id=str(tenant), question="q"
        ),
    )

    def _boom(*a: Any, **k: Any) -> list[str]:
        raise RuntimeError("constraint missing")

    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.persist_memory_signal_evidence",
        _boom,
    )

    with tenant_context(TenantContext(tenant_id=tenant, actor_id=uuid.uuid4())):
        result = conv.process_dossier_question_answer(
            session,
            {
                "message_id": str(message_id),
                "conversation_id": str(conversation),
                "dossier_id": str(dossier),
            },
            job,  # type: ignore[arg-type]
            memory_adapter=AugmentAdapter(),
            memory_mode="augment",
        )

    assert result["allowed_evidence_ids"] == []
    assert result["item_count"] == 0
    assert result.get("degraded") is True
    assert msg.answer_payload.get("citations") == []


def test_snapshot_fail_rebuilds_effective_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    """On snapshot persist failure, coverage/manifest are rebuilt to effective state."""

    tenant = uuid.uuid4()
    dossier = uuid.uuid4()
    conversation = uuid.uuid4()
    message_id = uuid.uuid4()
    item = _item(tenant_id=str(tenant), dossier_id=str(dossier))

    class AugmentAdapter:
        effective_mode = "augment"

        def retrieve(self, *a: Any, **k: Any) -> dict[str, Any]:
            return {
                "items": [item],
                "items_for_prompt": [item],
                "coverage_manifest": {
                    "requested": ["q"],
                    "used": [],
                    "failed": [],
                    "excluded": [],
                },
                "policy_version": "memory.v1",
                "snapshot_meta": {"purpose": "ask", "limit": 8},
            }

    msg = SimpleNamespace(
        id=message_id,
        tenant_id=tenant,
        dossier_id=dossier,
        conversation_id=conversation,
        role="user",
        status="queued",
        content_text="q",
        answer_payload={},
        coverage_manifest={},
        error_code=None,
        error_message=None,
        background_job_id=None,
    )
    job = SimpleNamespace(
        id=uuid.uuid4(), cancel_requested=False, correlation_id="c", attempt_count=1
    )
    session = MagicMock()
    session.refresh = MagicMock()
    session.flush = MagicMock()
    session.get = MagicMock(return_value=None)

    monkeypatch.setattr(conv, "get_message", lambda *a, **k: msg)
    monkeypatch.setattr(conv, "append_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(conv, "_signal_ai_enabled", lambda: False)
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.load_oracle_authority_from_session",
        lambda *a, **k: build_oracle_authority_block(
            dossier_id=str(dossier), tenant_id=str(tenant), question="q"
        ),
    )

    def _persist(_session: Any, **kwargs: Any) -> list[str]:
        citations = kwargs.get("citations") or []
        return [c.oracle_evidence_id for c in citations]

    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.persist_memory_signal_evidence",
        _persist,
    )

    def _boom_snapshot(*a: Any, **k: Any) -> None:
        raise RuntimeError("snapshot write failed")

    # process_dossier_question_answer imports from memory_context at call time.
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_context.persist_snapshot_from_retrieve_result",
        _boom_snapshot,
    )

    with tenant_context(TenantContext(tenant_id=tenant, actor_id=uuid.uuid4())):
        result = conv.process_dossier_question_answer(
            session,
            {
                "message_id": str(message_id),
                "conversation_id": str(conversation),
                "dossier_id": str(dossier),
            },
            job,  # type: ignore[arg-type]
            memory_adapter=AugmentAdapter(),
            memory_mode="augment",
        )

    assert result.get("degraded") is True
    failed = (msg.coverage_manifest or {}).get("failed") or []
    assert any(
        isinstance(row, dict) and row.get("reason") == "snapshot_persist_failed" for row in failed
    )
    # Effective manifest hash must be present and match answer payload (rebuilt after fail).
    assert result.get("input_manifest_hash")
    assert msg.answer_payload.get("input_manifest_hash") == result["input_manifest_hash"]
    # No half-linked snapshot id on success path
    assert result.get("snapshot_id") in (None, "")
    # Allowlist only contains effectively persisted evidence ids
    assert len(result["allowed_evidence_ids"]) == 1


def test_humanize_structured_deadline_and_amount_for_llm_prompt() -> None:
    from opn_oracle.integrations.memory_ask_dual import (
        _humanize_structured_memory_text,
        build_signal_factual_block,
    )
    from opn_oracle.integrations.memory_contract_v1 import MaterializedCitation

    raw_deadline = "tender.deadline: {'datetime': '2026-04-15T14:00:00'}"
    humanized = _humanize_structured_memory_text(raw_deadline)
    assert "15 de abril de 2026" in humanized
    assert "14:00" in humanized
    assert "ISO 2026-04-15T14:00:00" in humanized
    # Idempotent: already humanized text is left intact.
    assert _humanize_structured_memory_text(humanized) == humanized

    raw_amount = "tender.amount: {'amount': 2400000, 'currency': 'EUR'}"
    amount = _humanize_structured_memory_text(raw_amount)
    assert "2.400.000 EUR" in amount
    assert "amount=2400000" in amount

    def _cit(
        *,
        evidence_id: str,
        signal_item_id: str,
        excerpt: str,
        checksum: str,
    ) -> MaterializedCitation:
        return MaterializedCitation(
            oracle_evidence_id=evidence_id,
            signal_item_id=signal_item_id,
            source_ref=f"signal://{signal_item_id}",
            checksum=checksum,
            exact_excerpt=excerpt,
            classification="internal",
            locator="{}",
            occurred_at=None,
            policy_version="memory.v1",
            watermark="wm-1",
            tenant_id="t1",
            dossier_id="d1",
        )

    # Presentation order: tender key facts before company boilerplate.
    citations = (
        _cit(
            evidence_id="e-company",
            signal_item_id="s1",
            excerpt="[company:name:x] company.legal_name: {'name': 'X'}",
            checksum="c1",
        ),
        _cit(
            evidence_id="e-deadline",
            signal_item_id="s2",
            excerpt="tender.deadline: {'datetime': '2026-04-15T14:00:00'}",
            checksum="c2",
        ),
        _cit(
            evidence_id="e-ext",
            signal_item_id="s3",
            excerpt="tender.external_id: {'id': 'LIC-OATDA-2026-017'}",
            checksum="c3",
        ),
        _cit(
            evidence_id="e-amount",
            signal_item_id="s4",
            excerpt="tender.amount: {'amount': 2400000, 'currency': 'EUR'}",
            checksum="c4",
        ),
    )
    block = build_signal_factual_block(
        mode="augment", citations=citations, observed_count=4
    )
    texts = [str(item["text"]) for item in block["items"]]
    ids = [str(item["evidence_id"]) for item in block["items"]]
    assert ids[0] == "e-ext"
    assert ids[1] == "e-deadline"
    assert ids[2] == "e-amount"
    assert ids[3] == "e-company"
    assert "15 de abril de 2026" in texts[1]
    assert "2.400.000 EUR" in texts[2]


def test_complete_answer_with_grounded_tender_facts_copies_deadline() -> None:
    from opn_oracle.integrations.memory_ask_dual import (
        complete_answer_with_grounded_tender_facts,
    )

    items = [
        {
            "evidence_id": "e-ext",
            "text": "[tender:proc:LIC-OATDA-2026-017] tender.external_id: {'id': 'LIC-OATDA-2026-017'}",
        },
        {
            "evidence_id": "e-amount",
            "text": "[tender:proc:LIC-OATDA-2026-017] tender.amount: {'amount': 2400000, 'currency': 'EUR'}",
        },
        {
            "evidence_id": "e-deadline",
            "text": "[tender:proc:LIC-OATDA-2026-017] tender.deadline: {'datetime': '2026-04-15T14:00:00'}",
        },
    ]
    answer = (
        "Nexus participa en LIC-OATDA-2026-017 con un importe de 2.400.000 EUR."
    )
    completed, cites = complete_answer_with_grounded_tender_facts(
        answer, signal_items=items, citations=[{"evidence_id": "e-amount", "quote": "importe"}]
    )
    assert "15 de abril de 2026" in completed
    assert "LIC-OATDA-2026-017" in completed
    # Does not re-introduce amount already present via digit form.
    assert completed.count("2.400.000") == 1
    assert any(c.get("evidence_id") == "e-deadline" for c in cites)

    # Unknown tender not mentioned → no invention.
    untouched, cites2 = complete_answer_with_grounded_tender_facts(
        "Solo datos de la empresa sin licitación.",
        signal_items=items,
        citations=[],
    )
    assert "15 de abril" not in untouched
    assert cites2 == []
