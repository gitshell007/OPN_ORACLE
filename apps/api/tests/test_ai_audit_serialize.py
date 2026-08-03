"""Unit tests for AI audit list/detail serialization and filters (no invented fields)."""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from opn_oracle.ai.routes import (
    _audit_source_ids,
    list_ai_audit,
    serialize_ai_audit_detail,
    serialize_ai_audit_list_item,
)


def _audit(**overrides: Any) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "dossier_id": uuid.uuid4(),
        "background_job_id": uuid.uuid4(),
        "agent": "opportunity",
        "action": "generate",
        "status": "succeeded",
        "error_code": None,
        "provider": "signal-avanza",
        "model": "mock-model",
        "use_case": "oracle.ai.opportunity",
        "prompt_name": "opportunity",
        "prompt_version": "v1",
        "prompt_hash": bytes.fromhex("ab" * 16),
        "schema_name": "OpportunityOutput",
        "schema_version": "v1",
        "input_tokens": 10,
        "output_tokens": 5,
        "actual_cost_micros": 123456,
        "currency": "EUR",
        "latency_ms": 90,
        "attempt_count": 1,
        "source_ids": ["ev-1", "ev-2"],
        "data_classification": "internal",
        "human_review_state": "not_required",
        "created_at": datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
        "started_at": datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
        "completed_at": datetime(2026, 8, 3, 12, 1, tzinfo=UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.unit
def test_audit_source_ids_tolerates_null_and_non_list() -> None:
    assert _audit_source_ids(None) == []
    assert _audit_source_ids("x") == []
    assert _audit_source_ids([None, " a ", 3]) == [" a ", "3"]


@pytest.mark.unit
def test_serialize_list_item_exposes_metrics_without_invention() -> None:
    row = _audit(latency_ms=None, error_code=None, source_ids=[])
    payload = serialize_ai_audit_list_item(row)  # type: ignore[arg-type]
    assert payload["agent"] == "opportunity"
    assert payload["provider"] == "signal-avanza"
    assert payload["input_tokens"] == 10
    assert payload["output_tokens"] == 5
    assert payload["cost_micros"] == 123456
    assert payload["latency_ms"] is None
    assert payload["error_code"] is None
    assert payload["source_ids"] == []
    assert payload["background_job_id"] is not None
    assert "invented" not in payload


@pytest.mark.unit
def test_serialize_detail_includes_evidence_and_attempts() -> None:
    row = _audit()
    attempt = SimpleNamespace(
        attempt_number=1,
        kind="generate",
        status="succeeded",
        input_tokens=10,
        output_tokens=5,
        cost_micros=123456,
        latency_ms=90,
        error_code=None,
    )
    payload = serialize_ai_audit_detail(row, [attempt])  # type: ignore[arg-type]
    assert payload["source_ids"] == ["ev-1", "ev-2"]
    assert payload["usage"]["cost_micros"] == 123456
    assert payload["attempts"][0]["kind"] == "generate"
    assert payload["prompt"]["hash"] == "ab" * 16


@pytest.mark.unit
def test_list_ai_audit_requires_authentication(app: Any) -> None:
    """Sin sesión la ruta responde 401 (permission gate)."""
    with app.test_request_context("/api/v1/ai-audit"):
        from flask import g

        g.active_tenant_id = uuid.uuid4()
        response = list_ai_audit()
        if isinstance(response, tuple):
            _body, status, *_rest = response
            assert status == 401
        else:
            assert response.status_code == 401


@pytest.mark.unit
def test_list_ai_audit_serializes_visible_rows(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = uuid.uuid4()
    failed = _audit(status="failed", agent="report", dossier_id=uuid.uuid4())
    ok = _audit(status="succeeded", agent="report", dossier_id=failed.dossier_id)

    class _Scalars:
        def __init__(self, rows: list[Any]) -> None:
            self._rows = rows

        def __iter__(self) -> Any:
            return iter(self._rows)

    class _Session:
        def scalars(self, _query: Any) -> _Scalars:
            return _Scalars([failed, ok])

    class _DB:
        session = _Session()

    monkeypatch.setattr("opn_oracle.ai.routes.db", _DB())
    monkeypatch.setattr(
        "opn_oracle.ai.routes._dossier",
        lambda *_a, **_k: SimpleNamespace(id=failed.dossier_id),
    )

    unwrapped = inspect.unwrap(list_ai_audit)

    with app.test_request_context(
        "/api/v1/ai-audit?status=failed&agent=report",
        method="GET",
    ):
        from flask import g

        g.active_tenant_id = tenant
        result = unwrapped()
        assert "items" in result
        assert len(result["items"]) == 2
        assert result["items"][0]["status"] == "failed"
        assert result["items"][0]["cost_micros"] == 123456
        assert result["items"][0]["source_ids"] == ["ev-1", "ev-2"]
        assert result["items"][0]["latency_ms"] == 90
