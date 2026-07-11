from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from cryptography.exceptions import InvalidTag

from opn_oracle.config import ConfigError, Settings
from opn_oracle.integrations.crypto import (
    EncryptionConfigurationError,
    IntegrationKeyring,
    credential_aad,
)
from opn_oracle.integrations.service import adapter_for_connection
from opn_oracle.integrations.signal_avanza import (
    HttpSignalAvanzaAdapter,
    MockSignalAvanzaAdapter,
    MonitorSpec,
    SignalContractError,
    SignalTemporaryError,
    verify_webhook_signature,
)
from opn_oracle.platform.models import IntegrationConnection


def _keyring() -> IntegrationKeyring:
    encoded = base64.b64encode(b"k" * 32).decode()
    return IntegrationKeyring(f"1:{encoded}", 1)


@pytest.mark.unit
def test_aes_gcm_roundtrip_binds_aad_and_redacts_fingerprint() -> None:
    keyring = _keyring()
    aad = credential_aad(
        tenant_id="tenant", connection_id="connection", kind="api_token", version=1
    )
    encrypted = keyring.encrypt("very-secret-token", aad=aad)
    assert encrypted.ciphertext != b"very-secret-token"
    assert len(encrypted.fingerprint) == 32
    assert encrypted.fingerprint != hashlib.sha256(b"very-secret-token").hexdigest()[:32]
    assert keyring.decrypt(encrypted.ciphertext, encrypted.nonce, 1, aad=aad) == "very-secret-token"
    with pytest.raises(InvalidTag):
        keyring.decrypt(encrypted.ciphertext, encrypted.nonce, 1, aad=b"wrong")


@pytest.mark.unit
def test_keyring_rejects_non_aes256_key() -> None:
    with pytest.raises(EncryptionConfigurationError):
        IntegrationKeyring(f"1:{base64.b64encode(b'short').decode()}", 1)
    with pytest.raises(EncryptionConfigurationError):
        IntegrationKeyring("invalid", 1)
    with pytest.raises(EncryptionConfigurationError):
        IntegrationKeyring(f"2:{base64.b64encode(b'k' * 32).decode()}", 1)
    with pytest.raises(EncryptionConfigurationError):
        _keyring().decrypt(b"value", b"nonce", 99, aad=b"aad")


@pytest.mark.unit
def test_mock_is_deterministic_and_preserves_requested_signal_id() -> None:
    adapter = MockSignalAvanzaAdapter()
    spec = MonitorSpec(client_monitor_id="11111111-1111-1111-1111-111111111111", query="open calls")
    assert adapter.create_monitor(spec, idempotency_key="same") == adapter.create_monitor(
        spec, idempotency_key="same"
    )
    assert adapter.get_signal("external/id").id == "external/id"


@pytest.mark.unit
def test_http_requires_confirmed_contract_https_and_allowlist() -> None:
    with pytest.raises(SignalContractError):
        HttpSignalAvanzaAdapter(
            base_url="https://signal.example",
            api_version="v1",
            token="secret",
            contract_confirmed=False,
            allowed_hosts=frozenset({"signal.example"}),
        )
    with pytest.raises(SignalContractError):
        HttpSignalAvanzaAdapter(
            base_url="https://user:pass@signal.example",
            api_version="v1",
            token="secret",
            contract_confirmed=True,
            allowed_hosts=frozenset({"signal.example"}),
        )


@pytest.mark.unit
def test_http_ssrf_dns_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))]
    )
    with pytest.raises(SignalContractError):
        HttpSignalAvanzaAdapter(
            base_url="https://signal.example",
            api_version="v1",
            token="secret",
            contract_confirmed=True,
            allowed_hosts=frozenset({"signal.example"}),
        )
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *args, **kwargs: (_ for _ in ()).throw(OSError())
    )
    with pytest.raises(SignalContractError):
        HttpSignalAvanzaAdapter(
            base_url="https://signal.example",
            api_version="v1",
            token="secret",
            contract_confirmed=True,
            allowed_hosts=frozenset({"signal.example"}),
        )


@pytest.mark.unit
def test_connection_factory_rejects_unpinned_http_adapter(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    flask_app = app
    connection = IntegrationConnection(
        provider="signal-avanza",
        name="factory",
        status="active",
        adapter_mode="http",
        base_url="https://signal.example",
        api_version="v1",
    )
    monkeypatch.setattr(
        "opn_oracle.integrations.service.active_secrets", lambda *args, **kwargs: ["token"]
    )
    with flask_app.app_context():
        flask_app.config.update(
            SIGNAL_AVANZA_ALLOWED_HOSTS="signal.example",
            SIGNAL_AVANZA_CONTRACT_CONFIRMED=True,
        )
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda *args, **kwargs: [(None, None, None, None, ("8.8.8.8", 443))],
        )
        with pytest.raises(SignalContractError):
            adapter_for_connection(connection)
        monkeypatch.setattr(
            "opn_oracle.integrations.service.active_secrets", lambda *args, **kwargs: []
        )
        with pytest.raises(RuntimeError):
            adapter_for_connection(connection)
    with pytest.raises(SignalContractError):
        HttpSignalAvanzaAdapter(
            base_url="https://evil.example",
            api_version="v1",
            token="secret",
            contract_confirmed=True,
            allowed_hosts=frozenset({"signal.example"}),
        )


@pytest.mark.unit
def test_http_encodes_path_segments_and_maps_404_to_none() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path.decode())
        return httpx.Response(404, headers={"Content-Type": "application/json"}, json={})

    adapter = HttpSignalAvanzaAdapter(
        base_url="https://signal.example",
        api_version="v1",
        token="top-secret",
        contract_confirmed=True,
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(handler),
    )
    try:
        assert adapter.get_signal("one/two?admin=1") is None
        assert "%2F" in seen[0] and "%3F" in seen[0]
        assert "top-secret" not in repr(adapter)
    finally:
        adapter.close()


@pytest.mark.unit
@pytest.mark.parametrize("status", [500, 501, 503])
def test_http_retries_retryable_status_once(status: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, headers={"Content-Type": "application/json"}, json={})

    adapter = HttpSignalAvanzaAdapter(
        base_url="https://signal.example",
        api_version="v1",
        token="secret",
        contract_confirmed=True,
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(SignalTemporaryError):
        adapter.health()
    assert calls == 2
    adapter.close()


@pytest.mark.unit
def test_http_contract_success_exercises_all_operations() -> None:
    now = "2026-07-10T12:00:00Z"
    monitor = {
        "client_monitor_id": "11111111-1111-1111-1111-111111111111",
        "query": "calls",
        "status": "active",
        "keywords": [],
        "entities": [],
        "languages": [],
        "geographies": [],
        "source_types": [],
        "cadence": "daily",
        "callback_subscription_id": None,
        "config_version": 1,
        "config_hash": None,
        "id": "external-monitor",
        "created_at": now,
        "updated_at": now,
        "last_run_at": None,
        "cursor": None,
        "health": "healthy",
        "error_code": None,
    }
    signal = {
        "id": "signal-1",
        "monitor_id": "external-monitor",
        "type": "notice",
        "title": "Notice",
        "summary": "Safe",
        "source": {"name": "Source", "published_at": now},
        "language": "en",
        "entities": [],
        "tags": [],
        "categories": [],
        "content_hash": "sha256:value",
        "observed_at": now,
        "created_at": now,
        "provenance": {"connector": "fixture", "monitor_config_version": 1},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/health"):
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json={"status": "healthy", "checked_at": now},
            )
        if path.endswith("/signals"):
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json={"items": [signal], "next_cursor": "next", "has_more": False},
            )
        if "/signals/" in path:
            return httpx.Response(200, headers={"Content-Type": "application/json"}, json=signal)
        return httpx.Response(200, headers={"Content-Type": "application/json"}, json=monitor)

    adapter = HttpSignalAvanzaAdapter(
        base_url="https://signal.example",
        api_version="v1",
        token="secret",
        contract_confirmed=True,
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(handler),
        correlation_id="correlation",
    )
    spec = MonitorSpec(client_monitor_id=monitor["client_monitor_id"], query="calls")
    assert (
        adapter.create_monitor(spec, idempotency_key="create-key-123456").id == "external-monitor"
    )
    assert (
        adapter.update_monitor("external-monitor", spec, idempotency_key="update-key-123456").id
        == "external-monitor"
    )
    assert (
        adapter.pause_monitor("external-monitor", idempotency_key="pause-key-123456").status
        == "active"
    )
    assert (
        adapter.resume_monitor("external-monitor", idempotency_key="resume-key-123456").status
        == "active"
    )
    assert adapter.sync_signals("external-monitor", cursor="before").items[0].id == "signal-1"
    assert adapter.get_signal("signal-1").id == "signal-1"
    assert adapter.health() is True
    adapter.close()


@pytest.mark.unit
def test_http_rejects_invalid_provider_responses_and_html() -> None:
    responses = iter(
        [
            httpx.Response(200, headers={"Content-Type": "text/plain"}, text="no"),
            httpx.Response(
                200, headers={"Content-Type": "application/json"}, content=b"x" * 2_000_001
            ),
            httpx.Response(200, headers={"Content-Type": "application/json"}, content=b"{"),
        ]
    )
    adapter = HttpSignalAvanzaAdapter(
        base_url="https://signal.example",
        api_version="v1",
        token="secret",
        contract_confirmed=True,
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(lambda request: next(responses)),
    )
    for _ in range(3):
        with pytest.raises(SignalContractError):
            adapter.health()
    adapter.close()
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        __import__(
            "opn_oracle.integrations.signal_avanza", fromlist=["SignalItem"]
        ).SignalItem.model_validate(
            {
                "id": "x",
                "monitor_id": "m",
                "type": "x",
                "title": "<script>x</script>",
                "source": {"name": "s"},
                "content_hash": "h",
                "observed_at": "2026-07-10T00:00:00Z",
                "created_at": "2026-07-10T00:00:00Z",
                "provenance": {"connector": "c", "monitor_config_version": 1},
            }
        )


@pytest.mark.unit
def test_webhook_signature_accepts_current_secret_and_rejects_replay() -> None:
    now = datetime.now(UTC)
    timestamp = str(int(now.timestamp()))
    raw = b'{"event":"signal.created"}'
    signature = hmac.new(b"current", timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(
        raw_body=raw,
        timestamp=timestamp,
        signature=f"sha256={signature}",
        secrets=["previous", "current"],
        now=now,
        tolerance_seconds=300,
    )
    assert not verify_webhook_signature(
        raw_body=raw,
        timestamp=timestamp,
        signature=signature,
        secrets=["current"],
        now=now + timedelta(minutes=10),
        tolerance_seconds=300,
    )


@pytest.mark.unit
def test_http_mode_is_disabled_without_confirmation_and_keyring() -> None:
    with pytest.raises(ConfigError):
        Settings.load(
            {
                "APP_ENV": "test",
                "SIGNAL_AVANZA_MODE": "http",
                "SIGNAL_AVANZA_ENABLED": True,
                "SIGNAL_AVANZA_CONTRACT_CONFIRMED": False,
                "SIGNAL_AVANZA_BASE_URL": "https://signal.example",
            }
        )
