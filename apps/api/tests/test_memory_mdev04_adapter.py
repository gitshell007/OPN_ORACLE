"""MDEV-04 provisional: memory HTTP client, modes, SSRF, mutations."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from opn_oracle.integrations.memory_context import (
    DisabledMemoryContextAdapter,
    HttpMemoryContextAdapter,
    MemoryContextDisabled,
    MemoryContextError,
    build_memory_context_adapter,
)
from opn_oracle.integrations.memory_contract_v1 import (
    complete_retrieval_item,
    complete_retrieve_response_stub,
    resolve_effective_mode,
    should_call_signal,
    should_inject_into_llm,
    validate_retrieve_response_frozen,
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

# Integration env that arms conftest advisory lock / real DB session.
# Child mutation pytest must NOT inherit these (mutation-J deadlock pattern).
_CHILD_STRIP_ENV = (
    "ORACLE_RUN_INTEGRATION",
    "TEST_DATABASE_URL",
    "TEST_RUNTIME_DATABASE_URL",
    "TEST_REDIS_URL",
)
_CHILD_TIMEOUT_S = 45


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(API_ROOT / "src")
    for key in _CHILD_STRIP_ENV:
        env.pop(key, None)
    return env


def _run_child_node(node: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--tb=line",
                "--no-cov",
                node,
            ],
            cwd=str(API_ROOT),
            env=_child_env(),
            capture_output=True,
            text=True,
            timeout=_CHILD_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = (exc.stderr or b"").decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        raise AssertionError(
            f"child pytest timed out after {_CHILD_TIMEOUT_S}s for {node}\n"
            f"stdout:\n{out}\nstderr:\n{err}\n"
            "(likely inherited ORACLE_RUN_INTEGRATION / DB URLs → advisory lock deadlock)"
        ) from exc


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
    body = complete_retrieve_response_stub(
        items=[complete_retrieval_item(text="hello", checksum="abc")],
        token_budget=100,
    )
    body["coverage_manifest"]["token_used_estimate"] = 1
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
    body = complete_retrieve_response_stub(
        items=[complete_retrieval_item(text="secret-ish", checksum="c1")],
        request_id="r1",
        token_budget=100,
    )
    body["coverage_manifest"]["consulted"] = ["search"]
    body["coverage_manifest"]["used"] = ["search"]
    body["coverage_manifest"]["token_used_estimate"] = 1
    body["watermark"] = "wm1"
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
    try:
        red = _run_child_node(
            "tests/test_memory_mdev04_adapter.py::test_ssrf_blocks_non_allowlisted_host"
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
    try:
        red = _run_child_node("tests/test_memory_mdev04_adapter.py::test_modes_contract")
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
    try:
        red = _run_child_node(
            "tests/test_memory_mdev04_adapter.py::"
            "test_http_adapter_tenant_mismatch_before_retrieval"
        )
        assert red.returncode != 0, red.stdout + red.stderr
    finally:
        path.write_text(original)


def test_strict_api_version_rejects_prefix_only():
    transport = MockTransport(
        default=(
            200,
            {"content-type": "application/json"},
            b'{"api_version":"memory.retrieve.v1","items":[]}',
        )
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
    assert ei.value.code == "unsupported_api_version"


def test_dns_rebind_blocked_on_request():
    transport = MockTransport(
        resolve_override={"localhost": ["169.254.1.1"]},  # link-local
    )
    # construction may pass with default resolve; force override at request
    client = SignalMemoryHttpClient(
        MemoryClientConfig(
            base_url="http://localhost:9999",
            api_token="k",
            require_https=False,
            allowed_hosts=frozenset({"localhost"}),
        ),
        transport,
    )
    # for localhost, link-local is blocked by rebind check when host is localhost?
    # Our rule: localhost only allows loopback/private. link-local fails.
    with pytest.raises(MemoryHttpError) as ei:
        client.retrieve(
            external_tenant_id="t",
            dossier_id="11111111-1111-4111-8111-111111111111",
            query="q",
        )
    assert ei.value.code in {"ssrf_rebind", "ssrf_blocked"}


def test_retry_on_503_then_success():
    class Flaky(MockTransport):
        def __init__(self):
            super().__init__()
            self.n = 0

        def request(self, method, url, *, headers, json_body, timeout):
            self.n += 1
            if self.n == 1:
                return 503, {"content-type": "application/json"}, b"{}"
            body = complete_retrieve_response_stub()
            return 200, {"content-type": "application/json"}, json.dumps(body).encode()

    transport = Flaky()
    client = SignalMemoryHttpClient(
        MemoryClientConfig(
            base_url="http://localhost:9999",
            api_token="k",
            require_https=False,
            allowed_hosts=frozenset({"localhost"}),
            max_retries=2,
            deadline_seconds=10,
        ),
        transport,
    )
    out = client.retrieve(
        external_tenant_id="t",
        dossier_id="11111111-1111-4111-8111-111111111111",
        query="q",
    )
    assert out["api_version"] == "memory.v1"
    assert transport.n >= 2


def test_frozen_schema_rejects_partial_response():
    partial = {"api_version": "memory.v1", "items": []}
    with pytest.raises(ValueError):
        validate_retrieve_response_frozen(partial)
    full = complete_retrieve_response_stub()
    assert validate_retrieve_response_frozen(full)["api_version"] == "memory.v1"


def test_dns_rebind_midflight_pins_peer_ip():
    """DNS override to link-local must fail before any request body is sent."""
    transport = MockTransport(resolve_override={"localhost": ["169.254.169.254"]})
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
    assert ei.value.code in {"ssrf_rebind", "ssrf_blocked"}
    assert transport.calls == []


def test_persist_snapshot_no_commit_and_modes():
    from opn_oracle.integrations.memory_context import (
        persist_retrieval_snapshot,
        persist_snapshot_from_retrieve_result,
    )

    class _Sess:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.commits = 0

        def add(self, obj: object) -> None:
            self.added.append(obj)

        def commit(self) -> None:  # pragma: no cover - must not be called
            self.commits += 1
            raise AssertionError("adapter must not commit")

    session = _Sess()
    sid = persist_retrieval_snapshot(
        session,
        tenant_id=__import__("uuid").UUID("11111111-1111-4111-8111-111111111111"),
        dossier_id=__import__("uuid").UUID("22222222-2222-4222-8222-222222222222"),
        connection_id=None,
        mode="shadow",
        correlation_id="corr-1",
        snapshot={
            "failed": False,
            "inject_into_llm": False,
            "items": [],
            "items_observed": 2,
            "coverage": {},
            "watermark": "wm",
            "request_id": "r1",
        },
    )
    assert sid is not None
    assert len(session.added) == 1
    assert session.commits == 0
    assert (
        persist_retrieval_snapshot(
            session,
            tenant_id=__import__("uuid").UUID("11111111-1111-4111-8111-111111111111"),
            dossier_id=__import__("uuid").UUID("22222222-2222-4222-8222-222222222222"),
            connection_id=None,
            mode="disabled",
            correlation_id="c",
            snapshot={},
        )
        is None
    )

    session2 = _Sess()
    result = {
        "snapshot_meta": {
            "tenant_id": "11111111-1111-4111-8111-111111111111",
            "dossier_id": "22222222-2222-4222-8222-222222222222",
            "connection_id": None,
            "mode": "augment",
            "correlation_id": "c2",
        },
        "snapshot": {
            "failed": False,
            "inject_into_llm": True,
            "items": [{"id": "1"}],
            "items_observed": 1,
        },
    }
    assert persist_snapshot_from_retrieve_result(session2, result) is not None
    assert session2.commits == 0


def test_frozen_schema_rejects_extra_and_bad_item():
    full = complete_retrieve_response_stub(
        items=[complete_retrieval_item()],
    )
    full["extra_forbidden"] = True
    with pytest.raises(ValueError, match="additional"):
        validate_retrieve_response_frozen(full)
    bad_item = complete_retrieve_response_stub(
        items=[{**complete_retrieval_item(), "kind": "not-a-kind"}]
    )
    with pytest.raises(ValueError):
        validate_retrieve_response_frozen(bad_item)


def test_validated_destination_pins_loopback_ip():
    from opn_oracle.integrations.memory_http_client import validated_destination

    dest = validated_destination(
        "http://localhost:9999/api",
        allowed_hosts=frozenset({"localhost"}),
        require_https=False,
        dns_override={"localhost": ["127.0.0.1"]},
    )
    assert dest["peer_ip"] == "127.0.0.1"
    assert "127.0.0.1:9999" in dest["pinned_url"]
    assert dest["host"] == "localhost"


def test_client_records_pinned_peer_on_mock_transport():
    transport = MockTransport(resolve_override={"localhost": ["127.0.0.1"]})
    client = SignalMemoryHttpClient(
        MemoryClientConfig(
            base_url="http://localhost:9999",
            api_token="k",
            require_https=False,
            allowed_hosts=frozenset({"localhost"}),
        ),
        transport,
    )
    out = client.retrieve(
        external_tenant_id="t",
        dossier_id="11111111-1111-4111-8111-111111111111",
        query="q",
    )
    assert out["api_version"] == "memory.v1"
    assert transport.last_peer_url is not None
    assert "127.0.0.1" in transport.last_peer_url


def test_http_adapter_augment_injects_items():
    body = complete_retrieve_response_stub(
        items=[complete_retrieval_item(text="inject-me", checksum="c2")],
    )
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
        client=client, external_tenant_id="tenant-a", effective_mode="augment"
    )
    out = ad.retrieve(
        {
            "dossier_id": "11111111-1111-4111-8111-111111111111",
            "external_tenant_id": "tenant-a",
            "mode": "augment",
            "tenant_id": "11111111-1111-4111-8111-111111111111",
        },
        "query",
        "question",
        10,
    )
    assert out.get("items_for_prompt")
    assert ad.last_snapshot is not None
    assert ad.last_snapshot["inject_into_llm"] is True


def test_http_adapter_retryable_error_returns_failed_coverage():
    transport = MockTransport(
        default=(503, {"content-type": "application/json"}, b'{"error":"down"}')
    )
    client = SignalMemoryHttpClient(
        MemoryClientConfig(
            base_url="http://localhost:9999",
            api_token="k",
            require_https=False,
            allowed_hosts=frozenset({"localhost"}),
            max_retries=0,
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
        5,
    )
    assert out.get("error", {}).get("retryable") is True
    assert out["coverage_manifest"]["failed"]


def test_capability_payload_and_get_adapter_disabled(app):
    from opn_oracle.integrations.memory_context import (
        capability_payload,
        get_memory_context_adapter,
    )

    cap = capability_payload(host_mode="http", connection_healthy=False)
    assert cap["effective_mode"] == "disabled"
    assert cap["publisher_reliable"] is False
    with app.app_context():
        app.config["MEMORY_CONTEXT_MODE"] = "disabled"
        ad = get_memory_context_adapter()
        with pytest.raises(MemoryContextDisabled):
            ad.retrieve({}, "q", "question", 1)


def test_profile_helpers_and_public_dto():
    from opn_oracle.integrations.memory_profile import (
        build_client_for_connection,
        default_profile_payload,
        profile_to_public,
        resolve_signal_memory_connection,
    )

    cfg = default_profile_payload()
    assert cfg["mode"] == "disabled"
    row = type(
        "R",
        (),
        {
            "id": __import__("uuid").uuid4(),
            "tenant_id": __import__("uuid").uuid4(),
            "dossier_id": __import__("uuid").uuid4(),
            "connection_id": None,
            "mode": "shadow",
            "version": 2,
            "etag": 'W/"x"',
            "profile_config": {**cfg, "mode": "shadow"},
            "last_test_at": None,
            "last_test_status": "ok",
            "last_error": None,
            "last_coverage": {"version": "coverage_manifest.v1"},
            "updated_at": None,
        },
    )()
    pub = profile_to_public(row)
    assert pub["mode"] == "shadow"
    assert pub["publisher_reliable"] is False
    assert "api_token" not in pub

    class _Sess:
        def __init__(self, rows: list[Any]) -> None:
            self._rows = rows

        def scalars(self, _q: Any) -> Any:
            return self

        def all(self) -> list[Any]:
            return list(self._rows)

    tid = __import__("uuid").uuid4()
    with pytest.raises(MemoryHttpError) as ei:
        resolve_signal_memory_connection(_Sess([]), tenant_id=tid)  # type: ignore[arg-type]
    assert ei.value.code == "connection_missing"

    c1 = type(
        "C",
        (),
        {
            "id": __import__("uuid").uuid4(),
            "tenant_id": tid,
            "provider": "signal-avanza",
            "status": "active",
            "base_url": "http://localhost:9",
        },
    )()
    c2 = type(
        "C",
        (),
        {
            "id": __import__("uuid").uuid4(),
            "tenant_id": tid,
            "provider": "signal-avanza",
            "status": "active",
            "base_url": "http://localhost:9",
        },
    )()
    with pytest.raises(MemoryHttpError) as ei2:
        resolve_signal_memory_connection(_Sess([c1, c2]), tenant_id=tid)  # type: ignore[arg-type]
    assert ei2.value.code == "connection_conflict"
    found = resolve_signal_memory_connection(
        _Sess([c1, c2]),
        tenant_id=tid,
        preferred_connection_id=c1.id,  # type: ignore[arg-type]
    )
    assert found is c1
    # preferred missing
    with pytest.raises(MemoryHttpError) as ei3:
        resolve_signal_memory_connection(
            _Sess([c1]),
            tenant_id=tid,
            preferred_connection_id=__import__("uuid").uuid4(),  # type: ignore[arg-type]
        )
    assert ei3.value.code == "connection_missing"
    # empty base_url after preferred resolve
    c_empty = type(
        "C",
        (),
        {
            "id": c1.id,
            "tenant_id": tid,
            "provider": "signal-avanza",
            "status": "active",
            "base_url": "",
        },
    )()
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(
            "opn_oracle.integrations.memory_profile.active_secrets",
            lambda *a, **k: ["tok"],
        )
        with pytest.raises(MemoryHttpError) as ei4:
            build_client_for_connection(
                c_empty,  # type: ignore[arg-type]
                transport=MockTransport(),
                require_https=False,
            )
        assert ei4.value.code == "base_url_missing"
        monkeypatch.setattr(
            "opn_oracle.integrations.memory_profile.active_secrets",
            lambda *a, **k: [],
        )
        with pytest.raises(MemoryHttpError) as ei5:
            build_client_for_connection(
                c1,  # type: ignore[arg-type]
                transport=MockTransport(),
                require_https=False,
            )
        assert ei5.value.code == "credential_missing"
    finally:
        monkeypatch.undo()


def test_client_rejects_invalid_kind_source_and_limit():
    transport = MockTransport()
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
            kinds=["not-allowed-kind"],
        )
    assert ei.value.code == "schema_validation"
    with pytest.raises(MemoryHttpError):
        client.retrieve(
            external_tenant_id="t",
            dossier_id="11111111-1111-4111-8111-111111111111",
            query="q",
            source_types=["not-a-source"],
        )
    with pytest.raises(MemoryHttpError):
        client.retrieve(
            external_tenant_id="t",
            dossier_id="11111111-1111-4111-8111-111111111111",
            query="q",
            limit=0,
        )
    with pytest.raises(MemoryHttpError):
        client.retrieve(
            external_tenant_id="",
            dossier_id="11111111-1111-4111-8111-111111111111",
            query="q",
        )


def test_client_health_and_invalid_mime():
    transport = MockTransport(
        responses={
            "/api/v1/memory/v1/health": (
                200,
                {"content-type": "application/json"},
                b'{"status":"ok","engine_enabled":true}',
            )
        }
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
    health = client.health(external_tenant_id="t")
    assert health["status"] == "ok"

    transport2 = MockTransport(default=(200, {"content-type": "text/html"}, b"<html></html>"))
    client2 = SignalMemoryHttpClient(
        MemoryClientConfig(
            base_url="http://localhost:9999",
            api_token="k",
            require_https=False,
            allowed_hosts=frozenset({"localhost"}),
        ),
        transport2,
    )
    with pytest.raises(MemoryHttpError) as ei:
        client2.retrieve(
            external_tenant_id="t",
            dossier_id="11111111-1111-4111-8111-111111111111",
            query="q",
        )
    assert ei.value.code == "invalid_mime"


def test_httpx_transport_no_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    from opn_oracle.integrations.memory_http_client import HttpxTransport

    class _Resp:
        def __init__(self) -> None:
            self.status_code = 200
            self.content = b'{"ok":true}'
            self.headers = {"content-type": "application/json"}
            self.history: list[Any] = []
            self.url = "http://127.0.0.1:9/x"

    class _Client:
        def request(self, *a: Any, **k: Any) -> _Resp:
            assert k.get("follow_redirects") is False
            return _Resp()

    t = HttpxTransport.__new__(HttpxTransport)
    t._client = _Client()  # type: ignore[attr-defined]
    t.last_peer_url = None
    t.last_effective_url = None
    status, headers, body = t.request(
        "GET",
        "http://127.0.0.1:9/x",
        headers={},
        json_body=None,
        timeout=(1.0, 2.0),
    )
    assert status == 200
    assert headers["content-type"] == "application/json"
    assert body.startswith(b"{")
    assert t.last_peer_url == "http://127.0.0.1:9/x"

    class _RedirectResp(_Resp):
        def __init__(self) -> None:
            super().__init__()
            self.history = [object()]

    class _RedirectClient:
        def request(self, *a: Any, **k: Any) -> _RedirectResp:
            return _RedirectResp()

    t2 = HttpxTransport.__new__(HttpxTransport)
    t2._client = _RedirectClient()  # type: ignore[attr-defined]
    t2.last_peer_url = None
    t2.last_effective_url = None
    with pytest.raises(MemoryHttpError) as ei:
        t2.request(
            "GET",
            "http://127.0.0.1:9/x",
            headers={},
            json_body=None,
            timeout=(1.0, 2.0),
        )
    assert ei.value.code == "ssrf_blocked"


def test_contract_helpers_and_manifest():
    from opn_oracle.integrations.memory_contract_v1 import (
        TenantCredentialBinding,
        build_scope,
        coverage_from_failure,
        degradation_policy,
        is_legitimate_empty_success,
        materialize_signal_item_to_evidence,
        revoke_binding,
        rotate_binding,
        verify_contract_hashes,
    )

    assert verify_contract_hashes()
    scope = build_scope(
        consumer_id=1,
        external_tenant_id="tenant-a",
        dossier_id="11111111-1111-4111-8111-111111111111",
    )
    assert scope["product_code"] == "oracle"
    cov = coverage_from_failure(requested=["r"], code="x", retryable=False)
    assert not is_legitimate_empty_success(cov)
    assert degradation_policy("shadow", "upstream_5xx")["retryable"] is True
    assert degradation_policy("disabled", "x")["call_signal"] is False
    item = complete_retrieval_item(text="La licencia ambiental vence el 2027-03-01.")
    item.update(
        {
            "source_ref": "src:doc:1",
            "checksum": "sha256:abc",
            "locator": "c1",
            "classification": "internal",
            "policy_version": "v1",
            "watermark": "wm",
        }
    )
    cit = materialize_signal_item_to_evidence(
        item,
        tenant_id="11111111-1111-4111-8111-111111111111",
        dossier_id="11111111-1111-4111-8111-111111111111",
    )
    assert cit.signal_item_id == item["id"]
    binding = TenantCredentialBinding(
        tenant_id="t",
        integration_connection_id="c1",
        signal_consumer_slug="oracle",
        bound_external_tenant_id="ext",
        scopes=("memory.read",),
    )
    rotated = rotate_binding(binding, new_connection_id="c2")
    assert rotated.integration_connection_id == "c2"
    revoked = revoke_binding(binding)
    assert revoked.revoked is True
