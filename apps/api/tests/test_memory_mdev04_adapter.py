"""MDEV-04 provisional: memory HTTP client, modes, SSRF, mutations."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from opn_oracle.integrations.memory_context import (
    DisabledMemoryContextAdapter,
    HttpMemoryContextAdapter,
    MemoryContextDisabled,
    MemoryContextError,
    build_memory_context_adapter,
)
from opn_oracle.integrations.memory_contract_v1 import (
    resolve_effective_mode,
    should_call_signal,
    should_inject_into_llm,
)
from opn_oracle.integrations.memory_http_client import (
    MemoryClientConfig,
    MemoryHttpError,
    MockTransport,
    SignalMemoryHttpClient,
    validate_url_ssrf,
)

ROOT = Path(__file__).resolve().parents[2]
# apps/api is parents[1] from tests/
API_ROOT = Path(__file__).resolve().parents[1]


def test_ssrf_blocks_non_allowlisted_host():
    with pytest.raises(MemoryHttpError) as ei:
        validate_url_ssrf(
            "https://evil.example.com/api",
            allowed_hosts=frozenset({"signal.opnconsultoria.com"}),
        )
    assert ei.value.code == "ssrf_blocked"


def test_ssrf_allows_localhost_http_for_tests():
    url = validate_url_ssrf(
        "http://localhost:8080",
        allowed_hosts=frozenset({"localhost", "127.0.0.1"}),
        require_https=True,
    )
    assert "localhost" in url


def test_mock_transport_records_headers_redacted():
    body = {
        "api_version": "memory.v1",
        "items": [{"id": "1", "kind": "chunk", "text": "hello", "checksum": "abc"}],
        "coverage_manifest": {
            "version": "coverage_manifest.v1",
            "requested": ["retrieval"],
            "consulted": [],
            "failed": [],
            "excluded": [],
            "used": [],
            "truncated": False,
            "truncation_notes": [],
            "cutoff_at": None,
            "token_budget": 100,
            "token_used_estimate": 1,
        },
    }
    transport = MockTransport(
        default=(
            200,
            {"content-type": "application/json"},
            json.dumps(body).encode(),
        )
    )
    client = SignalMemoryHttpClient(
        MemoryClientConfig(
            base_url="http://localhost:9999",
            api_token="secret-token-xyz",
            require_https=False,
            allowed_hosts=frozenset({"localhost"}),
        ),
        transport,
    )
    out = client.retrieve(
        external_tenant_id="tenant-a",
        dossier_id="11111111-1111-4111-8111-111111111111",
        query="acme",
        purpose="question",
        limit=5,
    )
    assert out["api_version"] == "memory.v1"
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["headers"]["X-OPN-External-Tenant-ID"] == "tenant-a"
    assert call["headers"]["X-API-Key"] == "***"
    assert "secret-token" not in json.dumps(call)


def test_auth_error_not_retryable():
    transport = MockTransport(
        default=(401, {"content-type": "application/json"}, b'{"error":"nope"}')
    )
    client = SignalMemoryHttpClient(
        MemoryClientConfig(
            base_url="http://localhost:9999",
            api_token="k",
            require_https=False,
            allowed_hosts=frozenset({"localhost"}),
        ),
        transport,
    )
    with pytest.raises(MemoryHttpError) as ei:
        client.retrieve(
            external_tenant_id="t",
            dossier_id="11111111-1111-4111-8111-111111111111",
            query="q",
        )
    assert ei.value.retryable is False
    assert ei.value.code == "auth_or_scope"


def test_5xx_is_retryable():
    transport = MockTransport(
        default=(503, {"content-type": "application/json"}, b'{"error":"down"}')
    )
    client = SignalMemoryHttpClient(
        MemoryClientConfig(
            base_url="http://localhost:9999",
            api_token="k",
            require_https=False,
            allowed_hosts=frozenset({"localhost"}),
        ),
        transport,
    )
    with pytest.raises(MemoryHttpError) as ei:
        client.retrieve(
            external_tenant_id="t",
            dossier_id="11111111-1111-4111-8111-111111111111",
            query="q",
        )
    assert ei.value.retryable is True


def test_body_too_large():
    transport = MockTransport(default=(200, {"content-type": "application/json"}, b"x" * 100))
    client = SignalMemoryHttpClient(
        MemoryClientConfig(
            base_url="http://localhost:9999",
            api_token="k",
            require_https=False,
            allowed_hosts=frozenset({"localhost"}),
            max_bytes=10,
        ),
        transport,
    )
    with pytest.raises(MemoryHttpError) as ei:
        client.retrieve(
            external_tenant_id="t",
            dossier_id="11111111-1111-4111-8111-111111111111",
            query="q",
        )
    assert ei.value.code == "body_too_large"


def test_disabled_mode_never_calls():
    ad = DisabledMemoryContextAdapter()
    with pytest.raises(MemoryContextDisabled):
        ad.retrieve({}, "q", "question", 10)


def test_modes_contract():
    assert should_call_signal("disabled") is False
    assert should_call_signal("shadow") is True
    assert should_call_signal("augment") is True
    assert should_inject_into_llm("shadow") is False
    assert should_inject_into_llm("augment") is True
    eff = resolve_effective_mode(
        host_memory_context_mode="disabled",
        connection_healthy=True,
        tenant_mode="augment",
    )
    assert eff.mode == "disabled"


def test_http_adapter_shadow_keeps_items_out_of_prompt():
    body = {
        "api_version": "memory.v1",
        "items": [{"id": "1", "kind": "chunk", "text": "secret-ish", "checksum": "c1"}],
        "coverage_manifest": {
            "version": "coverage_manifest.v1",
            "requested": ["retrieval"],
            "consulted": ["search"],
            "failed": [],
            "excluded": [],
            "used": ["search"],
            "truncated": False,
            "truncation_notes": [],
            "cutoff_at": None,
            "token_budget": 100,
            "token_used_estimate": 1,
        },
        "watermark": "wm1",
        "request_id": "r1",
    }
    transport = MockTransport(
        default=(200, {"content-type": "application/json"}, json.dumps(body).encode())
    )
    client = SignalMemoryHttpClient(
        MemoryClientConfig(
            base_url="http://localhost:9999",
            api_token="k",
            require_https=False,
            allowed_hosts=frozenset({"localhost"}),
        ),
        transport,
    )
    ad = HttpMemoryContextAdapter(
        client=client, external_tenant_id="tenant-a", effective_mode="shadow"
    )
    out = ad.retrieve(
        {
            "dossier_id": "11111111-1111-4111-8111-111111111111",
            "external_tenant_id": "tenant-a",
            "mode": "shadow",
        },
        "query",
        "question",
        10,
    )
    assert out.get("shadow") is True
    assert out.get("items_for_prompt") == []
    assert ad.last_snapshot is not None
    assert ad.last_snapshot["inject_into_llm"] is False


def test_http_adapter_tenant_mismatch_before_retrieval():
    transport = MockTransport()
    client = SignalMemoryHttpClient(
        MemoryClientConfig(
            base_url="http://localhost:9999",
            api_token="key-a",
            require_https=False,
            allowed_hosts=frozenset({"localhost"}),
        ),
        transport,
    )
    ad = HttpMemoryContextAdapter(client=client, external_tenant_id="tenant-a")
    with pytest.raises((MemoryContextError, MemoryHttpError, ValueError, TypeError, RuntimeError)):
        ad.retrieve(
            {
                "dossier_id": "11111111-1111-4111-8111-111111111111",
                "external_tenant_id": "tenant-b",
                "connection_external_tenant_id": "tenant-a",
                "mode": "shadow",
            },
            "q",
            "question",
            5,
        )
    assert transport.calls == []  # never reached transport


def test_build_adapter_unknown_mode_fail_closed():
    with pytest.raises((MemoryContextError, MemoryHttpError, ValueError, TypeError, RuntimeError)):
        build_memory_context_adapter("shadow")  # host mode shadow invalid


def test_mutation_strip_allowlist_red():
    path = API_ROOT / "src/opn_oracle/integrations/memory_http_client.py"
    original = path.read_text()
    old = """    if host not in allowed_hosts:
        raise MemoryHttpError("ssrf_blocked", "host not in allowlist", retryable=False)"""
    new = """    if False and host not in allowed_hosts:
        raise MemoryHttpError("ssrf_blocked", "host not in allowlist", retryable=False)"""
    assert old in original
    path.write_text(original.replace(old, new, 1))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(API_ROOT / "src")
    try:
        red = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--tb=line",
                "tests/test_memory_mdev04_adapter.py::test_ssrf_blocks_non_allowlisted_host",
            ],
            cwd=str(API_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert red.returncode != 0, red.stdout + red.stderr
    finally:
        path.write_text(original)


def test_mutation_strip_mode_gate_red():
    path = API_ROOT / "src/opn_oracle/integrations/memory_contract_v1.py"
    original = path.read_text()
    old = """def should_call_signal(mode: OracleMemoryMode) -> bool:
    return mode in {"shadow", "augment"}"""
    new = """def should_call_signal(mode: OracleMemoryMode) -> bool:
    return True  # MUTATION"""
    assert old in original
    path.write_text(original.replace(old, new, 1))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(API_ROOT / "src")
    try:
        red = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--tb=line",
                "tests/test_memory_mdev04_adapter.py::test_modes_contract",
            ],
            cwd=str(API_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert red.returncode != 0, red.stdout + red.stderr
    finally:
        path.write_text(original)


def test_mutation_strip_tenant_mismatch_red():
    path = API_ROOT / "src/opn_oracle/integrations/memory_context.py"
    original = path.read_text()
    old = """        if bound_tenant and header_tenant and bound_tenant != header_tenant:
            raise MemoryContextError("credential_tenant_mismatch")"""
    new = """        if False and bound_tenant and header_tenant and bound_tenant != header_tenant:
            raise MemoryContextError("credential_tenant_mismatch")"""
    assert old in original
    path.write_text(original.replace(old, new, 1))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(API_ROOT / "src")
    try:
        red = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--tb=line",
                "tests/test_memory_mdev04_adapter.py::test_http_adapter_tenant_mismatch_before_retrieval",
            ],
            cwd=str(API_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert red.returncode != 0, red.stdout + red.stderr
    finally:
        path.write_text(original)
