"""SV2-COV-84 · focal product coverage (memory client, profile DTO, adapter publish).

Pure/unit tests — no PG. Target real product gaps measured at 80.79% total
(run 30886412860), not ops/evals (omitted from the coverage denominator).
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from opn_oracle.integrations.memory_http_client import (
    MemoryClientConfig,
    MemoryHttpError,
    MockTransport,
    SignalMemoryHttpClient,
    classify_http_error,
    validate_memory_v1_response,
    validate_url_ssrf,
)
from opn_oracle.integrations.memory_profile import (
    MODE_ES,
    default_profile_payload,
    profile_to_public,
)
from opn_oracle.integrations.surveillance_signal_adapter import (
    SurveillanceSignalAdapterError,
    durable_memory_store_available,
    publish_surveillance_scope,
    surveillance_signal_enabled,
)

_V1_OK = {
    "api_version": "memory.v1",
    "items": [{"id": "1", "kind": "fact", "text": "ok", "checksum": "c1"}],
    "coverage_manifest": {
        "version": "coverage_manifest.v1",
        "requested": [],
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


def _client(
    transport: MockTransport,
    *,
    max_bytes: int = 2_000_000,
    max_retries: int = 0,
) -> SignalMemoryHttpClient:
    return SignalMemoryHttpClient(
        MemoryClientConfig(
            base_url="http://localhost:9999",
            api_token="tok-secret",
            require_https=False,
            allowed_hosts=frozenset({"localhost"}),
            max_bytes=max_bytes,
            max_retries=max_retries,
        ),
        transport,
    )


# ---------------------------------------------------------------------------
# memory_http_client — validation + write/health paths under-covered in CI
# ---------------------------------------------------------------------------


def test_classify_http_error_matrix() -> None:
    assert classify_http_error(401) == ("auth_or_scope", False)
    assert classify_http_error(403) == ("auth_or_scope", False)
    assert classify_http_error(404) == ("not_found", False)
    assert classify_http_error(422) == ("schema_validation", False)
    assert classify_http_error(408) == ("upstream_retryable", True)
    assert classify_http_error(429) == ("upstream_retryable", True)
    assert classify_http_error(500) == ("upstream_retryable", True)
    assert classify_http_error(418) == ("upstream_error", False)


def test_validate_memory_v1_rejects_bad_shapes() -> None:
    with pytest.raises(MemoryHttpError) as ei:
        validate_memory_v1_response([])
    assert ei.value.code == "invalid_json"

    with pytest.raises(MemoryHttpError) as ei:
        validate_memory_v1_response({"api_version": "memory.v0", "items": []})
    assert ei.value.code == "unsupported_api_version"

    with pytest.raises(MemoryHttpError) as ei:
        validate_memory_v1_response({"api_version": "memory.v1", "items": "x"})
    assert ei.value.code == "schema_validation"

    with pytest.raises(MemoryHttpError) as ei:
        validate_memory_v1_response({"api_version": "memory.v1", "items": ["not-dict"]})
    assert ei.value.code == "schema_validation"

    with pytest.raises(MemoryHttpError) as ei:
        validate_memory_v1_response({"api_version": "memory.v1", "items": [{"kind": "bogus_kind"}]})
    assert ei.value.code == "schema_validation"

    with pytest.raises(MemoryHttpError) as ei:
        validate_memory_v1_response(
            {
                "api_version": "memory.v1",
                "items": [],
                "coverage_manifest": "nope",
            }
        )
    assert ei.value.code == "schema_validation"

    with pytest.raises(MemoryHttpError) as ei:
        validate_memory_v1_response(
            {
                "api_version": "memory.v1",
                "items": [],
                "coverage_manifest": {"version": "coverage_manifest.v9"},
            }
        )
    assert ei.value.code == "schema_validation"

    # failed + empty items is legitimate empty
    out = validate_memory_v1_response(
        {
            "api_version": "memory.v1",
            "items": [],
            "coverage_manifest": {
                "version": "coverage_manifest.v1",
                "failed": ["timeout"],
            },
        }
    )
    assert out["items"] == []


def test_retrieve_validates_filters_and_range() -> None:
    transport = MockTransport(
        default=(200, {"content-type": "application/json"}, json.dumps(_V1_OK).encode())
    )
    client = _client(transport)

    with pytest.raises(MemoryHttpError) as ei:
        client.retrieve(external_tenant_id="", dossier_id="d", query="q")
    assert ei.value.code == "tenant_required"

    with pytest.raises(MemoryHttpError) as ei:
        client.retrieve(external_tenant_id="t", dossier_id="d", query="q", limit=0)
    assert ei.value.code == "schema_validation"

    with pytest.raises(MemoryHttpError) as ei:
        client.retrieve(external_tenant_id="t", dossier_id="d", query="q", token_budget=-1)
    assert ei.value.code == "schema_validation"

    with pytest.raises(MemoryHttpError) as ei:
        client.retrieve(
            external_tenant_id="t",
            dossier_id="d",
            query="q",
            kinds=["not_a_kind"],
        )
    assert ei.value.code == "schema_validation"

    with pytest.raises(MemoryHttpError) as ei:
        client.retrieve(
            external_tenant_id="t",
            dossier_id="d",
            query="q",
            source_types=["nope"],
        )
    assert ei.value.code == "schema_validation"

    with pytest.raises(MemoryHttpError) as ei:
        client.retrieve(
            external_tenant_id="t",
            dossier_id="d",
            query="q",
            classifications=["top_secret"],
        )
    assert ei.value.code == "schema_validation"

    out = client.retrieve(
        external_tenant_id="tenant-x",
        dossier_id="11111111-1111-4111-8111-111111111111",
        query="acme",
        kinds=["fact", "chunk"],
        source_types=["document", "signal"],
        classifications=["public"],
        cutoff_at="2026-01-01T00:00:00Z",
        limit=10,
        token_budget=500,
    )
    assert out["api_version"] == "memory.v1"
    body = transport.calls[-1]["json_body"]
    assert body is not None
    assert body["kinds"] == ["fact", "chunk"]
    assert body["source_types"] == ["document", "signal"]
    assert body["classifications"] == ["public"]
    assert body["cutoff_at"] == "2026-01-01T00:00:00Z"
    # query is redacted in the mock call log
    assert str(body.get("query", "")).startswith("sha256:")


def test_retrieve_rejects_invalid_json_and_mime() -> None:
    transport = MockTransport(default=(200, {"content-type": "text/html"}, b"<html>nope</html>"))
    client = _client(transport)
    with pytest.raises(MemoryHttpError) as ei:
        client.retrieve(
            external_tenant_id="t",
            dossier_id="11111111-1111-4111-8111-111111111111",
            query="q",
        )
    assert ei.value.code == "invalid_mime"

    transport = MockTransport(default=(200, {"content-type": "application/json"}, b"not-json{"))
    client = _client(transport)
    with pytest.raises(MemoryHttpError) as ei:
        client.retrieve(
            external_tenant_id="t",
            dossier_id="11111111-1111-4111-8111-111111111111",
            query="q",
        )
    assert ei.value.code == "invalid_json"


def test_health_and_post_json_paths() -> None:
    health_body = {"status": "ok", "api_version": "memory.v1"}
    transport = MockTransport(
        responses={
            "/api/v1/memory/v1/health": (
                200,
                {"content-type": "application/json"},
                json.dumps(health_body).encode(),
            ),
            "/api/v1/memory/v1/ingest": (
                202,
                {"content-type": "application/json"},
                json.dumps({"accepted": True}).encode(),
            ),
        }
    )
    client = _client(transport)
    assert client.health(external_tenant_id="ext-1")["status"] == "ok"

    status, data = client.post_json(
        "api/v1/memory/v1/ingest",  # missing leading slash → normalized
        external_tenant_id="ext-1",
        dossier_id="11111111-1111-4111-8111-111111111111",
        body={"kind": "chunk"},
        idempotency_key="idem-1",
    )
    assert status == 202
    assert data["accepted"] is True
    call = transport.calls[-1]
    assert call["headers"]["Idempotency-Key"] == "idem-1"
    assert call["headers"]["X-OPN-Dossier-ID"] == "11111111-1111-4111-8111-111111111111"
    assert call["headers"]["X-API-Key"] == "***"


def test_post_json_error_and_empty_body() -> None:
    # 5xx/4xx surface via _request_with_retry classify_http_error (before post_json body parse).
    transport = MockTransport(
        responses={
            "/api/v1/memory/v1/write": (
                503,
                {"content-type": "application/json"},
                json.dumps({"error_code": "feature_disabled"}).encode(),
            ),
        }
    )
    client = _client(transport, max_retries=0)
    with pytest.raises(MemoryHttpError) as ei:
        client.post_json(
            "/api/v1/memory/v1/write",
            external_tenant_id="ext",
            body={"x": 1},
        )
    assert ei.value.http_status == 503
    assert ei.value.retryable is True
    assert ei.value.code == "upstream_retryable"

    transport = MockTransport(
        responses={
            "/api/v1/memory/v1/write": (
                400,
                {"content-type": "application/json"},
                json.dumps({"code": "bad_request"}).encode(),
            ),
        }
    )
    client = _client(transport, max_retries=0)
    with pytest.raises(MemoryHttpError) as ei:
        client.post_json(
            "/api/v1/memory/v1/write",
            external_tenant_id="ext",
            body={"x": 1},
        )
    assert ei.value.retryable is False
    assert ei.value.code == "upstream_error"

    transport = MockTransport(
        responses={
            "/api/v1/memory/v1/write": (201, {"content-type": "application/json"}, b""),
        }
    )
    client = _client(transport)
    status, data = client.post_json(
        "/api/v1/memory/v1/write",
        external_tenant_id="ext",
        body={"x": 1},
    )
    assert status == 201
    assert data == {}

    # Non-object JSON becomes {"value": ...}
    transport = MockTransport(
        responses={
            "/api/v1/memory/v1/write": (
                200,
                {"content-type": "application/json"},
                b'["list"]',
            ),
        }
    )
    client = _client(transport)
    status, data = client.post_json(
        "/api/v1/memory/v1/write",
        external_tenant_id="ext",
        body={"x": 1},
    )
    assert status == 200
    assert data == {"value": ["list"]}

    transport = MockTransport(
        responses={
            "/api/v1/memory/v1/write": (
                200,
                {"content-type": "application/json"},
                b"not-json",
            ),
        }
    )
    client = _client(transport)
    with pytest.raises(MemoryHttpError) as ei:
        client.post_json(
            "/api/v1/memory/v1/write",
            external_tenant_id="ext",
            body={"x": 1},
        )
    assert ei.value.code == "invalid_json"

    with pytest.raises(MemoryHttpError) as ei:
        client.post_json("/x", external_tenant_id="  ", body={})
    assert ei.value.code == "tenant_required"


def test_transport_error_wrapped_as_retryable() -> None:
    class BoomTransport:
        def request(self, *args: object, **kwargs: object) -> tuple[int, dict[str, str], bytes]:
            raise RuntimeError("socket closed")

    client = SignalMemoryHttpClient(
        MemoryClientConfig(
            base_url="http://localhost:9999",
            api_token="k",
            require_https=False,
            allowed_hosts=frozenset({"localhost"}),
            max_retries=0,
        ),
        BoomTransport(),  # type: ignore[arg-type]
    )
    with pytest.raises(MemoryHttpError) as ei:
        client.retrieve(
            external_tenant_id="t",
            dossier_id="11111111-1111-4111-8111-111111111111",
            query="q",
        )
    assert ei.value.code == "transport_error"
    assert ei.value.retryable is True


def test_ssrf_blocks_private_rebind(monkeypatch: pytest.MonkeyPatch) -> None:
    from opn_oracle.integrations import memory_http_client as mhc

    def fake_resolve(hostname: str, override: dict[str, list[str]] | None = None) -> list[str]:
        if override and hostname in override:
            return list(override[hostname])
        return ["10.0.0.5"]

    monkeypatch.setattr(mhc, "_resolve_host_ips", fake_resolve)
    with pytest.raises(MemoryHttpError) as ei:
        validate_url_ssrf(
            "https://signal-dev.opnconsultoria.com/api",
            allowed_hosts=frozenset({"signal-dev.opnconsultoria.com"}),
        )
    assert ei.value.code == "ssrf_blocked"


# ---------------------------------------------------------------------------
# memory_profile — pure DTO helpers
# ---------------------------------------------------------------------------


def test_default_profile_and_public_dto() -> None:
    payload = default_profile_payload()
    assert payload["mode"] == "disabled"
    assert "document" in payload["sources"]
    assert MODE_ES["augment"] == "Usar para responder"

    now = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
    row = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        mode="shadow",
        version=3,
        etag='W/"x"',
        profile_config={
            "mode": "shadow",
            "sources": ["signal"],
            "kinds": ["fact"],
            "classifications_allowed": ["public"],
            "token_budget": 1200,
            "limit": 7,
            "status": "active",
            "provenance": "tenant_default",
        },
        last_test_at=now,
        last_test_status="ok",
        last_error=None,
        last_coverage={"used": 1},
        updated_at=now,
    )
    pub = profile_to_public(row)
    assert pub["mode"] == "shadow"
    assert pub["mode_label_es"] == MODE_ES["shadow"]
    assert pub["token_budget"] == 1200
    assert pub["limit"] == 7
    # Profile DTO is configuration-only; host health lives on /memory/effective.
    assert "publisher_reliable" not in pub
    assert "actions_reliable" not in pub
    assert "deferred_blockers" not in pub
    assert not re.search(r"(RACE|DB|SEC|MIG)-MDEV", json.dumps(pub))
    assert "api_token" not in json.dumps(pub)
    assert pub["last_test_at"] == now.isoformat()

    # connection_id optional + empty config defaults
    row2 = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        connection_id=None,
        mode=None,
        version=1,
        etag="e",
        profile_config={},
        last_test_at=None,
        last_test_status=None,
        last_error=None,
        last_coverage=None,
        updated_at=None,
    )
    pub2 = profile_to_public(row2)
    assert pub2["connection_id"] is None
    assert pub2["mode"] == "disabled"
    assert pub2["sources"] == []
    assert pub2["last_test_at"] is None
    assert pub2["updated_at"] is None


# ---------------------------------------------------------------------------
# surveillance_signal_adapter — remaining fail-closed branches
# ---------------------------------------------------------------------------


def _action() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        action_type="actor_tenders",
        actor_id=uuid.uuid4(),
        offering_id=None,
        requirement_id=None,
        intent_revision_id=None,
        effective_scope_hash="a" * 64,
        cadence="weekly",
        timezone="Europe/Madrid",
        origin="user",
        confirmed_by_user_id=uuid.uuid4(),
        confirmed_at=datetime.now(UTC),
        alignment_state="aligned",
        manual_overrides={},
    )


def test_adapter_flags_and_missing_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMORY_SURVEILLANCE_SIGNAL_ENABLED", raising=False)
    assert surveillance_signal_enabled() is False
    monkeypatch.setenv("MEMORY_SURVEILLANCE_SIGNAL_ENABLED", "yes")
    assert surveillance_signal_enabled() is True

    monkeypatch.delenv("MEMORY_DURABLE_STORE_READY", raising=False)
    assert durable_memory_store_available() is False
    monkeypatch.setenv("MEMORY_DURABLE_STORE_READY", "1")
    assert durable_memory_store_available() is True

    with pytest.raises(Exception) as ei:
        publish_surveillance_scope(
            _action(),  # type: ignore[arg-type]
            consumer_id="",
            external_tenant_id="",
        )
    # SurveillanceValidationError from surveillance module
    assert "obligator" in str(ei.value).lower() or "consumer" in str(ei.value).lower()


def test_adapter_publish_success_and_transport_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMORY_SURVEILLANCE_SIGNAL_ENABLED", "1")
    monkeypatch.setenv("MEMORY_DURABLE_STORE_READY", "1")

    with pytest.raises(SurveillanceSignalAdapterError) as ei:
        publish_surveillance_scope(
            _action(),  # type: ignore[arg-type]
            consumer_id="opn-oracle",
            external_tenant_id="ext-t",
            transport=None,
        )
    assert ei.value.code == "transport_missing"

    class OkTransport:
        def publish_surveillance_scope(self, envelope: dict) -> dict:
            return {"monitor_id": "m-1", "envelope_keys": sorted(envelope.keys())}

    out = publish_surveillance_scope(
        _action(),  # type: ignore[arg-type]
        consumer_id="opn-oracle",
        external_tenant_id="ext-t",
        transport=OkTransport(),
    )
    assert out["status"] == "accepted"
    assert out["published"] is True
    assert out["result"]["monitor_id"] == "m-1"
    assert out["degraded"] is False
