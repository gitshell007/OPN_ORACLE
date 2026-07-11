from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from opn_oracle import create_app
from opn_oracle.auth.tokens import stable_invitation_token
from opn_oracle.config import ConfigError, Settings
from opn_oracle.notifications.email import (
    EmailPermanentError,
    EmailTemporaryError,
    GraphEmailSender,
)

TENANT_ID = "11111111-1111-4111-8111-111111111111"
CLIENT_ID = "22222222-2222-4222-8222-222222222222"


@pytest.mark.unit
def test_graph_sender_gets_token_and_sends_plain_text_without_secret_leak() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            form = parse_qs(request.content.decode())
            assert form == {
                "client_id": [CLIENT_ID],
                "client_secret": ["client-secret-canary"],
                "scope": ["https://graph.microsoft.com/.default"],
                "grant_type": ["client_credentials"],
            }
            return httpx.Response(200, json={"access_token": "access-token", "expires_in": 3600})
        assert request.url == (
            "https://graph.microsoft.com/v1.0/users/oracle%40example.test/sendMail"
        )
        assert request.headers["Authorization"] == "Bearer access-token"
        payload = json.loads(request.content)
        graph_requests = [item for item in requests if item.url.host == "graph.microsoft.com"]
        if len(graph_requests) == 1:
            assert payload == {
                "message": {
                    "subject": "Aviso",
                    "body": {"contentType": "Text", "content": "Cuerpo"},
                    "toRecipients": [{"emailAddress": {"address": "user@example.test"}}],
                    "internetMessageHeaders": [
                        {"name": "x-opn-idempotency-key", "value": "delivery-123"}
                    ],
                },
                "saveToSentItems": True,
            }
        return httpx.Response(202)

    sender = GraphEmailSender(
        tenant_id=TENANT_ID,
        client_id=CLIENT_ID,
        client_secret="client-secret-canary",
        sender_mailbox="oracle@example.test",
        transport=httpx.MockTransport(handler),
    )
    sender.send_notification(
        recipient="user@example.test",
        title="Aviso",
        body="Cuerpo",
        url=None,
        idempotency_key="delivery-123",
    )
    sender.send_security_alert(recipient="user@example.test", message="Segundo")

    assert sender.supports_idempotency is False
    assert (
        len([request for request in requests if request.url.host == "login.microsoftonline.com"])
        == 1
    )
    assert len([request for request in requests if request.url.host == "graph.microsoft.com"]) == 2


@pytest.mark.unit
def test_graph_sender_refreshes_token_once_after_unauthorized() -> None:
    token_calls = 0
    send_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, send_calls
        if request.url.host == "login.microsoftonline.com":
            token_calls += 1
            return httpx.Response(200, json={"access_token": f"token-{token_calls}"})
        send_calls += 1
        if send_calls == 1:
            return httpx.Response(401, json={"error": {"message": "secret provider detail"}})
        assert request.headers["Authorization"] == "Bearer token-2"
        return httpx.Response(202)

    sender = GraphEmailSender(
        tenant_id=TENANT_ID,
        client_id=CLIENT_ID,
        client_secret="opaque",
        sender_mailbox="33333333-3333-4333-8333-333333333333",
        transport=httpx.MockTransport(handler),
    )
    sender.send_security_alert(recipient="user@example.test", message="Aviso")

    assert token_calls == 2
    assert send_calls == 2


@pytest.mark.unit
@pytest.mark.parametrize("status", [429, 500])
def test_graph_sender_classifies_retryable_provider_failures_without_body(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(status, json={"error": {"message": "provider-secret-canary"}})

    sender = GraphEmailSender(
        tenant_id=TENANT_ID,
        client_id=CLIENT_ID,
        client_secret="opaque",
        sender_mailbox="oracle@example.test",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(EmailTemporaryError) as caught:
        sender.send_security_alert(recipient="user@example.test", message="Aviso")
    assert "provider-secret-canary" not in str(caught.value)


@pytest.mark.unit
def test_graph_sender_classifies_permanent_provider_failure_without_body() -> None:
    transport = httpx.MockTransport(
        lambda request: (
            httpx.Response(200, json={"access_token": "token"})
            if request.url.host == "login.microsoftonline.com"
            else httpx.Response(403, json={"error": {"message": "provider-secret-canary"}})
        )
    )
    sender = GraphEmailSender(
        tenant_id=TENANT_ID,
        client_id=CLIENT_ID,
        client_secret="opaque",
        sender_mailbox="oracle@example.test",
        transport=transport,
    )
    with pytest.raises(EmailPermanentError) as caught:
        sender.send_security_alert(recipient="user@example.test", message="Aviso")
    assert "provider-secret-canary" not in str(caught.value)


@pytest.mark.unit
def test_graph_secret_can_be_loaded_from_file(tmp_path: Path) -> None:
    secret = tmp_path / "graph-client-secret"
    secret.write_text("opaque-graph-secret\n", encoding="utf-8")

    settings = Settings.load(
        {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "MAIL_BACKEND": "graph",
            "GRAPH_TENANT_ID": TENANT_ID,
            "GRAPH_CLIENT_ID": CLIENT_ID,
            "GRAPH_CLIENT_SECRET_FILE": str(secret),
            "GRAPH_SENDER_MAILBOX": "oracle@example.test",
        }
    )
    assert settings.graph_client_secret == "opaque-graph-secret"


@pytest.mark.unit
def test_graph_production_configuration_is_fail_closed() -> None:
    base = {
        "APP_ENV": "production",
        "SECRET_KEY": "x" * 40,
        "DATABASE_URL": "postgresql://user:password@db/oracle",
        "REDIS_URL": "rediss://redis.example/0",
        "FRONTEND_ORIGIN": "https://oracle.example",
        "MAIL_BACKEND": "graph",
    }
    with pytest.raises(ConfigError, match="GRAPH_TENANT_ID"):
        Settings.load(base)

    app = create_app(
        {
            **base,
            "GRAPH_TENANT_ID": TENANT_ID,
            "GRAPH_CLIENT_ID": CLIENT_ID,
            "GRAPH_CLIENT_SECRET": "opaque",
            "GRAPH_SENDER_MAILBOX": "oracle@example.test",
        }
    )
    assert isinstance(app.extensions["email_sender"], GraphEmailSender)


@pytest.mark.unit
def test_invitation_token_is_stable_scoped_and_not_the_identifier() -> None:
    import uuid

    invitation_id = uuid.UUID("33333333-3333-4333-8333-333333333333")
    first = stable_invitation_token(invitation_id=invitation_id, secret_key="secret-a")
    assert first == stable_invitation_token(invitation_id=invitation_id, secret_key="secret-a")
    assert first != stable_invitation_token(invitation_id=invitation_id, secret_key="secret-b")
    assert first != str(invitation_id)
    assert len(first) == 43


@pytest.mark.unit
def test_graph_sender_close_is_idempotent() -> None:
    sender = GraphEmailSender(
        tenant_id=TENANT_ID,
        client_id=CLIENT_ID,
        client_secret="opaque",
        sender_mailbox="oracle@example.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(202)),
    )
    sender.close()
    sender.close()
