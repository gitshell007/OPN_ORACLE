"""Email boundary with capture and SMTP implementations."""

from __future__ import annotations

import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from threading import Lock
from typing import Any, Protocol
from urllib.parse import quote

import httpx


class EmailProviderError(RuntimeError):
    """Provider failure whose message never includes provider response content or secrets."""


class EmailTemporaryError(EmailProviderError):
    """Transport, throttling or provider failure that may recover."""


class EmailPermanentError(EmailProviderError):
    """Configuration or request failure that requires operator action."""


class EmailSender(Protocol):
    supports_idempotency: bool

    def send_invitation(
        self,
        *,
        recipient: str,
        tenant_name: str,
        url: str,
        expires: str,
        idempotency_key: str,
    ) -> None: ...
    def send_password_reset(
        self, *, recipient: str, url: str, expires: str, idempotency_key: str
    ) -> None: ...
    def send_security_alert(self, *, recipient: str, message: str) -> None: ...
    def send_notification(
        self,
        *,
        recipient: str,
        title: str,
        body: str,
        url: str | None,
        idempotency_key: str,
    ) -> None: ...
    def send_digest(
        self,
        *,
        recipient: str,
        cadence: str,
        items: tuple[tuple[str, str, str | None], ...],
        preferences_url: str,
        idempotency_key: str,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class CapturedEmail:
    recipient: str
    subject: str
    body: str
    message_id: str | None = None


class CaptureEmailSender:
    supports_idempotency = True

    def __init__(self) -> None:
        self.messages: list[CapturedEmail] = []
        self._delivery_keys: set[str] = set()

    def _send(
        self, recipient: str, subject: str, body: str, *, idempotency_key: str | None = None
    ) -> None:
        if idempotency_key and idempotency_key in self._delivery_keys:
            return
        if idempotency_key:
            self._delivery_keys.add(idempotency_key)
        self.messages.append(CapturedEmail(recipient, subject, body, idempotency_key))

    def send_invitation(
        self,
        *,
        recipient: str,
        tenant_name: str,
        url: str,
        expires: str,
        idempotency_key: str,
    ) -> None:
        self._send(
            recipient,
            f"Invitación a {tenant_name}",
            f"Acepta la invitación: {url}\nCaduca: {expires}.",
            idempotency_key=idempotency_key,
        )

    def send_password_reset(
        self, *, recipient: str, url: str, expires: str, idempotency_key: str
    ) -> None:
        self._send(
            recipient,
            "Restablece tu contraseña de OPN Oracle",
            f"Restablece tu contraseña: {url}\nCaduca: {expires}.",
            idempotency_key=idempotency_key,
        )

    def send_security_alert(self, *, recipient: str, message: str) -> None:
        self._send(recipient, "Aviso de seguridad de OPN Oracle", message)

    def send_notification(
        self,
        *,
        recipient: str,
        title: str,
        body: str,
        url: str | None,
        idempotency_key: str,
    ) -> None:
        link = f"\nAbrir en OPN Oracle: {url}" if url else ""
        self._send(
            recipient,
            title,
            f"{body}{link}",
            idempotency_key=idempotency_key,
        )

    def send_digest(
        self,
        *,
        recipient: str,
        cadence: str,
        items: tuple[tuple[str, str, str | None], ...],
        preferences_url: str,
        idempotency_key: str,
    ) -> None:
        cadence_label = "diario" if cadence == "daily" else "semanal"
        lines = [f"Resumen {cadence_label} de OPN Oracle", ""]
        for title, body, url in items:
            lines.append(f"• {title}: {body}")
            if url:
                lines.append(f"  {url}")
        lines.extend(("", f"Gestionar preferencias: {preferences_url}"))
        self._send(
            recipient,
            f"Resumen {cadence_label} de OPN Oracle",
            "\n".join(lines),
            idempotency_key=idempotency_key,
        )


class SMTPEmailSender(CaptureEmailSender):
    supports_idempotency = False

    def __init__(
        self, *, host: str, port: int, username: str, password: str, use_tls: bool, sender: str
    ) -> None:
        super().__init__()
        self.host, self.port, self.username, self.password = host, port, username, password
        self.use_tls, self.sender = use_tls, sender

    def _send(
        self, recipient: str, subject: str, body: str, *, idempotency_key: str | None = None
    ) -> None:
        if idempotency_key and idempotency_key in self._delivery_keys:
            return
        if idempotency_key:
            self._delivery_keys.add(idempotency_key)
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = self.sender, recipient, subject
        if idempotency_key:
            message["Message-ID"] = f"<{idempotency_key}@oracle.opnconsultoria.com>"
        message.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)


class GraphEmailSender(CaptureEmailSender):
    """Microsoft Graph client-credentials sender using a fixed Microsoft endpoint."""

    supports_idempotency = False

    def __init__(
        self,
        *,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        sender_mailbox: str,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__()
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._sender_mailbox = sender_mailbox
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = Lock()
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        """Release pooled connections when the owning application is collected."""

        if not self._client.is_closed:
            self._client.close()

    def _access_token(self, *, force_refresh: bool = False) -> str:
        with self._token_lock:
            now = time.monotonic()
            if not force_refresh and self._token and now < self._token_expires_at:
                return self._token
            try:
                response = self._client.post(
                    (
                        "https://login.microsoftonline.com/"
                        f"{quote(self._tenant_id, safe='')}/oauth2/v2.0/token"
                    ),
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "scope": "https://graph.microsoft.com/.default",
                        "grant_type": "client_credentials",
                    },
                    headers={"Accept": "application/json"},
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise EmailTemporaryError(
                    "Microsoft Graph no esta disponible temporalmente."
                ) from exc
            if response.status_code == 429 or response.status_code >= 500:
                raise EmailTemporaryError("Microsoft Graph no esta disponible temporalmente.")
            if response.status_code != 200:
                raise EmailPermanentError("Microsoft Graph rechazo las credenciales configuradas.")
            try:
                payload: Any = response.json()
                token = payload["access_token"]
                expires_in = int(payload.get("expires_in", 3600))
            except (ValueError, TypeError, KeyError) as exc:
                raise EmailTemporaryError(
                    "Microsoft Graph devolvio una respuesta no valida."
                ) from exc
            if not isinstance(token, str) or not token or len(token) > 64 * 1024:
                raise EmailTemporaryError("Microsoft Graph devolvio una respuesta no valida.")
            self._token = token
            self._token_expires_at = now + max(1, expires_in - 60)
            return token

    def _graph_send(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
        idempotency_key: str | None,
    ) -> None:
        message: dict[str, Any] = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": recipient}}],
        }
        if idempotency_key:
            if "\r" in idempotency_key or "\n" in idempotency_key:
                raise EmailPermanentError("La clave de entrega de correo no es valida.")
            message["internetMessageHeaders"] = [
                {"name": "x-opn-idempotency-key", "value": idempotency_key[:900]}
            ]
        endpoint = (
            "https://graph.microsoft.com/v1.0/users/"
            f"{quote(self._sender_mailbox, safe='')}/sendMail"
        )
        for attempt in range(2):
            token = self._access_token(force_refresh=attempt == 1)
            try:
                response = self._client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json={"message": message, "saveToSentItems": True},
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise EmailTemporaryError(
                    "Microsoft Graph no esta disponible temporalmente."
                ) from exc
            if response.status_code == 202:
                return
            if response.status_code == 401 and attempt == 0:
                continue
            if response.status_code == 429 or response.status_code >= 500:
                raise EmailTemporaryError("Microsoft Graph no esta disponible temporalmente.")
            raise EmailPermanentError("Microsoft Graph rechazo el envio del correo.")
        raise EmailPermanentError("Microsoft Graph rechazo el envio del correo.")

    def _send(
        self, recipient: str, subject: str, body: str, *, idempotency_key: str | None = None
    ) -> None:
        self._graph_send(
            recipient=recipient,
            subject=subject,
            body=body,
            idempotency_key=idempotency_key,
        )
