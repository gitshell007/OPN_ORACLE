"""Provisional, versioned Signal Avanza anti-corruption layer."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
import socket
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from urllib.parse import quote, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class SignalContractError(RuntimeError):
    """Provider response does not satisfy the pinned provisional contract."""


class SignalTemporaryError(RuntimeError):
    """Retryable transport/provider error without secret-bearing detail."""


class MonitorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    oracle_monitor_id: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=4000)
    status: Literal["draft", "active", "paused", "disabled", "error"] = "active"
    keywords: list[str] = Field(default_factory=list, max_length=100)
    entities: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    languages: list[str] = Field(default_factory=list, max_length=20)
    geographies: list[str] = Field(default_factory=list, max_length=100)
    source_types: list[str] = Field(default_factory=lambda: ["news"], max_length=50)
    cadence: str = Field(default="daily", max_length=50)
    retention_days: int = Field(default=365, ge=1, le=3650)


class ProviderMonitor(MonitorSpec):
    model_config = ConfigDict(extra="forbid", strict=False)
    id: str = Field(min_length=1, max_length=200)
    created_at: datetime
    updated_at: datetime
    tenant_id: str
    last_run_at: datetime | None = None
    cursor: str
    config_version: int = Field(ge=1)
    config_hash: str
    subscription_id: str | None = None
    health: dict[str, Any]


class SourceItem(BaseModel):
    model_config = ConfigDict(extra="allow", strict=False)
    name: str
    url: HttpUrl | None = None
    published_at: datetime | None = None
    credibility_score: float | None = Field(default=None, ge=0, le=100)


class ProvenanceItem(BaseModel):
    model_config = ConfigDict(extra="allow", strict=False)
    connector: str
    monitor_config_version: int = Field(ge=1)


class SignalItem(BaseModel):
    model_config = ConfigDict(extra="allow", strict=False)
    id: str = Field(min_length=1, max_length=240)
    monitor_id: str
    type: str
    title: str = Field(min_length=1, max_length=500)
    summary: str | None = None
    source: SourceItem
    language: str | None = None
    tags: list[str] = Field(default_factory=list)
    entities: list[dict[str, Any]] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    content_hash: str
    observed_at: datetime
    created_at: datetime
    provenance: ProvenanceItem

    @field_validator("title", "summary")
    @classmethod
    def reject_active_html(cls, value: str | None) -> str | None:
        if value is not None and re.search(r"<\s*/?\s*[a-zA-Z][^>]*>", value):
            raise ValueError("HTML activo no está permitido en señales.")
        return value


class SignalPage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    items: list[SignalItem]
    next_cursor: str | None = Field(default=None, max_length=500)
    has_more: bool = False


@dataclass(frozen=True, slots=True)
class SignalSyncResult:
    received: int
    created: int
    duplicates: int
    next_cursor: str


class SignalAvanzaAdapter(Protocol):
    def create_monitor(self, spec: MonitorSpec, *, idempotency_key: str) -> ProviderMonitor: ...
    def update_monitor(
        self, monitor_id: str, spec: MonitorSpec, *, idempotency_key: str
    ) -> ProviderMonitor: ...
    def pause_monitor(self, monitor_id: str, *, idempotency_key: str) -> ProviderMonitor: ...
    def resume_monitor(self, monitor_id: str, *, idempotency_key: str) -> ProviderMonitor: ...
    def sync_signals(self, monitor_id: str, *, cursor: str | None) -> SignalPage: ...
    def get_signal(self, signal_id: str) -> SignalItem | None: ...
    def health(self) -> bool: ...

    # Compatibility boundary for the phase-07 durable job; phase-08 ingestion
    # replaces its implementation without coupling Celery to the HTTP client.
    def sync_monitor(self, *, monitor_id: str, cursor: str | None) -> SignalSyncResult: ...


class MockSignalAvanzaAdapter:
    """Deterministic local adapter used unless the external contract is confirmed."""

    def create_monitor(self, spec: MonitorSpec, *, idempotency_key: str) -> ProviderMonitor:
        now = datetime(2020, 1, 1, tzinfo=UTC)
        return ProviderMonitor(
            **spec.model_dump(),
            id=hashlib.sha256(f"{idempotency_key}:{spec.oracle_monitor_id}".encode()).hexdigest()[
                :24
            ],
            created_at=now,
            tenant_id="mock",
            cursor="mock",
            config_version=1,
            config_hash="sha256:mock",
            health={"state": "ok"},
            updated_at=now,
        )

    def update_monitor(
        self, monitor_id: str, spec: MonitorSpec, *, idempotency_key: str
    ) -> ProviderMonitor:
        del idempotency_key
        now = datetime(2020, 1, 1, tzinfo=UTC)
        return ProviderMonitor(
            **spec.model_dump(),
            id=monitor_id,
            tenant_id="mock",
            cursor="mock",
            config_version=1,
            config_hash="sha256:mock",
            health={"state": "ok"},
            created_at=now,
            updated_at=now,
        )

    def pause_monitor(self, monitor_id: str, *, idempotency_key: str) -> ProviderMonitor:
        del idempotency_key
        spec = MonitorSpec(oracle_monitor_id=monitor_id, query="mock", status="paused")
        return self.update_monitor(monitor_id, spec, idempotency_key="mock-pause")

    def resume_monitor(self, monitor_id: str, *, idempotency_key: str) -> ProviderMonitor:
        del idempotency_key
        spec = MonitorSpec(oracle_monitor_id=monitor_id, query="mock", status="active")
        return self.update_monitor(monitor_id, spec, idempotency_key="mock-resume")

    def sync_signals(self, monitor_id: str, *, cursor: str | None) -> SignalPage:
        seed = hashlib.sha256(f"{monitor_id}:{cursor or 'start'}".encode()).hexdigest()
        item = SignalItem(
            id=seed[:24],
            monitor_id=monitor_id,
            type="mock",
            title=f"Señal sintética {seed[:8]}",
            summary="Fixture determinista del adaptador mock.",
            source=SourceItem(name="Signal Avanza Mock", credibility_score=50),
            content_hash=seed,
            observed_at=datetime(2020, 1, 1, tzinfo=UTC),
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
            provenance=ProvenanceItem(connector="mock", monitor_config_version=1),
        )
        second = item.model_copy(
            update={
                "id": seed[24:48],
                "title": f"Señal sintética {seed[8:16]}",
                "content_hash": hashlib.sha256(seed.encode()).hexdigest(),
            }
        )
        return SignalPage(items=[item, second], next_cursor=seed[48:64], has_more=False)

    def sync_monitor(self, *, monitor_id: str, cursor: str | None) -> SignalSyncResult:
        page = self.sync_signals(monitor_id, cursor=cursor)
        duplicates = 1 if cursor else 0
        return SignalSyncResult(
            received=2,
            created=2 - duplicates,
            duplicates=duplicates,
            next_cursor=page.next_cursor or cursor or "",
        )

    def get_signal(self, signal_id: str) -> SignalItem:
        item = self.sync_signals(signal_id, cursor=None).items[0]
        return item.model_copy(update={"id": signal_id})

    def health(self) -> bool:
        return True


class HttpSignalAvanzaAdapter:
    """Real transport; construction is gated by explicit contract confirmation."""

    def __init__(
        self,
        *,
        base_url: str,
        api_version: str,
        token: str,
        contract_confirmed: bool,
        external_tenant_id: str = "test-tenant",
        connect_timeout: float = 2.0,
        read_timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        correlation_id: str | None = None,
        allowed_hosts: frozenset[str] = frozenset(),
    ) -> None:
        if not contract_confirmed:
            raise SignalContractError("Contrato Signal externo todavía no confirmado.")
        if not base_url.startswith("https://"):
            raise SignalContractError("Signal HTTP exige HTTPS.")
        parsed_url = urlparse(base_url)
        if parsed_url.username or parsed_url.password:
            raise SignalContractError("Signal base URL no admite credenciales embebidas.")
        hostname = parsed_url.hostname or ""
        if not allowed_hosts or hostname not in allowed_hosts:
            raise SignalContractError("Host Signal no incluido en la allowlist.")
        if transport is None:
            try:
                addresses = {
                    item[4][0]
                    for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
                }
            except OSError as exc:
                raise SignalContractError("No se pudo resolver el host Signal permitido.") from exc
            if not addresses or any(
                not ipaddress.ip_address(value).is_global for value in addresses
            ):
                raise SignalContractError("Signal base URL resuelve a una red no pública.")
        self._token = token
        self._external_tenant_id = external_tenant_id
        self._api_version = api_version
        self._correlation_id = correlation_id
        self._client = httpx.Client(
            base_url=f"{base_url.rstrip('/')}/",
            timeout=httpx.Timeout(read_timeout, connect=connect_timeout),
            follow_redirects=False,
            transport=transport,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Any:
        headers = {
            "X-API-Key": self._token,
            "X-OPN-External-Tenant-ID": self._external_tenant_id,
            "Accept": "application/json",
        }
        if self._correlation_id:
            headers["X-Correlation-ID"] = self._correlation_id
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if extra_headers:
            headers.update(extra_headers)
        attempts = 2 if method == "GET" or idempotency_key else 1
        response: httpx.Response | None = None
        for attempt in range(attempts):
            try:
                response = self._client.request(
                    method, path, json=body, params=params, headers=headers
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt + 1 == attempts:
                    raise SignalTemporaryError(
                        "Proveedor Signal temporalmente no disponible."
                    ) from exc
                continue
            retryable_status = response.status_code == 429 or response.status_code >= 500
            if not retryable_status or attempt + 1 == attempts:
                break
            retry_after = response.headers.get("Retry-After", "0")
            if retry_after.isdigit():
                time.sleep(min(float(retry_after), 30.0))
        assert response is not None
        if response.status_code == 429 or response.status_code >= 500:
            retry_after = response.headers.get("Retry-After")
            suffix = "" if not retry_after else f" Reintento sugerido en {retry_after}s."
            raise SignalTemporaryError("Proveedor Signal temporalmente no disponible." + suffix)
        if response.status_code == 404 and method == "GET" and path.startswith("signals/"):
            return None
        if response.is_redirect or response.status_code >= 400:
            raise SignalContractError(f"Respuesta Signal no aceptada ({response.status_code}).")
        if "application/json" not in response.headers.get("Content-Type", ""):
            raise SignalContractError("Signal devolvió un Content-Type no permitido.")
        if len(response.content) > 2_000_000:
            raise SignalContractError("Respuesta Signal supera el tamaño permitido.")
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise SignalContractError("Signal devolvió JSON no válido.") from exc

    def create_monitor(self, spec: MonitorSpec, *, idempotency_key: str) -> ProviderMonitor:
        return ProviderMonitor.model_validate(
            self._request(
                "POST",
                "monitors",
                body=spec.model_dump(mode="json"),
                idempotency_key=idempotency_key,
            )
        )

    def update_monitor(
        self, monitor_id: str, spec: MonitorSpec, *, idempotency_key: str
    ) -> ProviderMonitor:
        external_id = quote(monitor_id, safe="")
        current = ProviderMonitor.model_validate(self._request("GET", f"monitors/{external_id}"))
        return ProviderMonitor.model_validate(
            self._request(
                "PATCH",
                f"monitors/{external_id}",
                body={
                    key: value
                    for key, value in spec.model_dump(mode="json").items()
                    if key
                    in {
                        "query",
                        "keywords",
                        "entities",
                        "languages",
                        "geographies",
                        "source_types",
                        "cadence",
                        "retention_days",
                    }
                },
                idempotency_key=idempotency_key,
                extra_headers={"If-Match": str(current.config_version)},
            )
        )

    def _action(self, monitor_id: str, action: str, key: str) -> ProviderMonitor:
        external_id = quote(monitor_id, safe="")
        return ProviderMonitor.model_validate(
            self._request("POST", f"monitors/{external_id}/{action}", body={}, idempotency_key=key)
        )

    def pause_monitor(self, monitor_id: str, *, idempotency_key: str) -> ProviderMonitor:
        return self._action(monitor_id, "pause", idempotency_key)

    def resume_monitor(self, monitor_id: str, *, idempotency_key: str) -> ProviderMonitor:
        return self._action(monitor_id, "resume", idempotency_key)

    def sync_signals(self, monitor_id: str, *, cursor: str | None) -> SignalPage:
        params = {"cursor": cursor} if cursor else None
        params = {**(params or {}), "monitor_id": monitor_id}
        return SignalPage.model_validate(self._request("GET", "signals", params=params))

    def get_signal(self, signal_id: str) -> SignalItem | None:
        payload = self._request("GET", f"signals/{quote(signal_id, safe='')}")
        return None if payload is None else SignalItem.model_validate(payload)

    def sync_monitor(self, *, monitor_id: str, cursor: str | None) -> SignalSyncResult:
        page = self.sync_signals(monitor_id, cursor=cursor)
        return SignalSyncResult(
            received=len(page.items),
            created=len(page.items),
            duplicates=0,
            next_cursor=page.next_cursor or cursor or "",
        )

    def health(self) -> bool:
        data = self._request("GET", "health")
        return (
            isinstance(data, dict)
            and data.get("status") == "ok"
            and data.get("api_version") == self._api_version
        )

    def close(self) -> None:
        self._client.close()

    def __repr__(self) -> str:
        return "HttpSignalAvanzaAdapter(token=<redacted>)"


def verify_webhook_signature(
    *,
    raw_body: bytes,
    timestamp: str,
    signature: str,
    secrets: list[str],
    now: datetime,
    tolerance_seconds: int,
) -> bool:
    try:
        sent_at = datetime.fromtimestamp(int(timestamp), tz=UTC)
    except (TypeError, ValueError, OSError):
        return False
    if abs((now.astimezone(UTC) - sent_at).total_seconds()) > tolerance_seconds:
        return False
    canonical = timestamp.encode() + b"." + raw_body
    supplied = signature.removeprefix("sha256=").removeprefix("v1=")
    return any(
        hmac.compare_digest(
            hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest(), supplied
        )
        for secret in secrets
    )
