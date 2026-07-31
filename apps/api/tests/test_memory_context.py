"""Unit tests for MemoryContextAdapter (MEMSOL-05)."""

from __future__ import annotations

import pytest

from opn_oracle.config import ConfigError, Settings
from opn_oracle.integrations.memory_context import (
    COVERAGE_MANIFEST_VERSION,
    DisabledMemoryContextAdapter,
    HttpMemoryContextAdapter,
    MemoryContextDisabled,
    MemoryContextError,
    MockMemoryContextAdapter,
    build_memory_context_adapter,
    empty_coverage_manifest,
    empty_memory_retrieval_response,
)

REQUIRED_MANIFEST_KEYS = frozenset(
    {
        "version",
        "requested",
        "consulted",
        "failed",
        "excluded",
        "used",
        "truncated",
    }
)


def test_empty_coverage_manifest_has_v1_shape() -> None:
    manifest = empty_coverage_manifest(requested=["oracle.docs"], token_budget=1000)
    assert REQUIRED_MANIFEST_KEYS.issubset(manifest.keys())
    assert manifest["version"] == COVERAGE_MANIFEST_VERSION
    assert manifest["requested"] == ["oracle.docs"]
    assert manifest["consulted"] == []
    assert manifest["failed"] == []
    assert manifest["excluded"] == []
    assert manifest["used"] == []
    assert manifest["truncated"] is False
    assert manifest["token_budget"] == 1000
    assert manifest["token_used_estimate"] == 0
    assert manifest["cutoff_at"] is None


def test_mock_adapter_returns_empty_items_and_valid_manifest() -> None:
    adapter = MockMemoryContextAdapter()
    result = adapter.retrieve(
        {"dossier_id": "abc", "tenant_id": "t1"},
        query="¿Quién es el adjudicatario?",
        purpose="question",
        limit=10,
    )
    assert result["items"] == []
    assert result["api_version"]
    assert result["request_id"]
    assert result["policy_version"] == "mock.v1"
    manifest = result["coverage_manifest"]
    assert manifest["version"] == COVERAGE_MANIFEST_VERSION
    assert "mock.memory" in manifest["requested"]
    assert "dossier:abc" in manifest["requested"]
    assert manifest["truncated"] is False
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["purpose"] == "question"
    assert adapter.calls[0]["limit"] == 10


def test_mock_adapter_rejects_invalid_purpose_and_limit() -> None:
    adapter = MockMemoryContextAdapter()
    with pytest.raises(MemoryContextError):
        adapter.retrieve({}, query="q", purpose="chat", limit=5)
    with pytest.raises(MemoryContextError):
        adapter.retrieve({}, query="q", purpose="question", limit=0)
    with pytest.raises(MemoryContextError):
        adapter.retrieve({}, query="q", purpose="question", limit=101)


def test_disabled_adapter_fails_closed() -> None:
    adapter = DisabledMemoryContextAdapter()
    with pytest.raises(MemoryContextDisabled):
        adapter.retrieve({}, query="q", purpose="question", limit=5)


def test_http_adapter_requires_https_and_is_not_live() -> None:
    bad = HttpMemoryContextAdapter(base_url="http://insecure.example")
    with pytest.raises(MemoryContextError):
        bad.retrieve({}, query="q", purpose="question", limit=5)
    ok = HttpMemoryContextAdapter(base_url="https://signal.example/api/v1/memory")
    with pytest.raises(MemoryContextError):
        ok.retrieve({}, query="q", purpose="question", limit=5)


def test_build_adapter_modes() -> None:
    assert isinstance(build_memory_context_adapter("disabled"), DisabledMemoryContextAdapter)
    assert isinstance(build_memory_context_adapter("mock"), MockMemoryContextAdapter)
    assert isinstance(
        build_memory_context_adapter("http", base_url="https://signal.example"),
        HttpMemoryContextAdapter,
    )
    with pytest.raises(MemoryContextError):
        build_memory_context_adapter("weird")


def test_settings_default_memory_context_disabled() -> None:
    settings = Settings.load(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "unit-test-secret-key-32chars-min!!",
            "DATABASE_URL": "postgresql+psycopg://oracle@127.0.0.1:5432/oracle_test",
            "REDIS_URL": "redis://127.0.0.1:6379/15",
            "BACKUP_STORAGE_PATH": "/tmp/oracle-backups-test",
        }
    )
    assert settings.memory_context_mode == "disabled"
    assert settings.memory_context_base_url == ""
    assert settings.memory_context_timeout_seconds == 10.0


def test_settings_rejects_invalid_memory_mode_and_http_without_https() -> None:
    base = {
        "APP_ENV": "test",
        "SECRET_KEY": "unit-test-secret-key-32chars-min!!",
        "DATABASE_URL": "postgresql+psycopg://oracle@127.0.0.1:5432/oracle_test",
        "REDIS_URL": "redis://127.0.0.1:6379/15",
        "BACKUP_STORAGE_PATH": "/tmp/oracle-backups-test",
    }
    with pytest.raises(ConfigError):
        Settings.load({**base, "MEMORY_CONTEXT_MODE": "live"})
    with pytest.raises(ConfigError):
        Settings.load(
            {
                **base,
                "MEMORY_CONTEXT_MODE": "http",
                "MEMORY_CONTEXT_BASE_URL": "http://signal.example",
            }
        )
    settings = Settings.load(
        {
            **base,
            "MEMORY_CONTEXT_MODE": "mock",
        }
    )
    assert settings.memory_context_mode == "mock"


def test_retrieval_response_shape_is_stable() -> None:
    payload = empty_memory_retrieval_response(request_id="req-1", policy_version="p1")
    assert payload["request_id"] == "req-1"
    assert payload["items"] == []
    assert payload["coverage_manifest"]["version"] == COVERAGE_MANIFEST_VERSION
