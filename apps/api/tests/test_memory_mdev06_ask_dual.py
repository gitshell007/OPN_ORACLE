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
    build_dual_ask_context,
    build_input_manifest,
    build_oracle_authority_block,
    classify_error_code,
    materialize_augment_items,
    validate_citations_allowlist,
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
    # Avoid DB Evidence persistence path noise
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.persist_memory_signal_evidence",
        lambda *a, **k: [],
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
    assert len(result["allowed_evidence_ids"]) == 1
    assert msg.status == "succeeded"
    assert msg.answer_payload.get("citations")
    assert msg.answer_payload["citations"][0]["evidence_id"] in result["allowed_evidence_ids"]


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
