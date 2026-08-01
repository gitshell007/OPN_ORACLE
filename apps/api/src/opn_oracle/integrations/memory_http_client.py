"""Signal Memory HTTP client (MDEV-04 provisional).

Tenant-scoped, injectable transport, SSRF/allowlist, strict size/MIME, no secrets in logs.
Publisher debt: surfaces degraded capability; does not claim reindex reliability.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

# Default allowlist hostnames (compose/native-dev + known Signal hosts)
DEFAULT_ALLOWED_HOSTS = frozenset(
    {
        "signal.opnconsultoria.com",
        "localhost",
        "127.0.0.1",
        "host.docker.internal",
    }
)

MAX_RESPONSE_BYTES = 2_000_000  # 2 MiB hard cap before parse
ALLOWED_MIME_PREFIXES = ("application/json", "application/problem+json")


class MemoryHttpError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
        timeout: tuple[float, float],
    ) -> tuple[int, dict[str, str], bytes]:
        """Return (status, headers, body_bytes). Must not follow unsafe redirects."""


@dataclass
class MockTransport:
    """Test double: records calls; scripted responses by path suffix."""

    responses: dict[str, tuple[int, dict[str, str], bytes]] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)
    default: tuple[int, dict[str, str], bytes] = (
        200,
        {"content-type": "application/json"},
        b'{"api_version":"memory.v1","items":[],"coverage_manifest":{"version":"coverage_manifest.v1","requested":[],"consulted":[],"failed":[],"excluded":[],"used":[],"truncated":false,"truncation_notes":[],"cutoff_at":null,"token_budget":0,"token_used_estimate":0}}',
    )

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
        timeout: tuple[float, float],
    ) -> tuple[int, dict[str, str], bytes]:
        # Redact for inspection copies
        safe_headers = {
            k: ("***" if k.lower() in {"x-api-key", "authorization"} else v)
            for k, v in headers.items()
        }
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": safe_headers,
                "json_body": json_body,
                "timeout": timeout,
            }
        )
        path = urlparse(url).path
        for suffix, resp in self.responses.items():
            if path.endswith(suffix) or suffix in path:
                return resp
        return self.default


@dataclass
class MemoryClientConfig:
    base_url: str
    api_token: str
    allowed_hosts: frozenset[str] = DEFAULT_ALLOWED_HOSTS
    connect_timeout: float = 3.0
    read_timeout: float = 15.0
    max_bytes: int = MAX_RESPONSE_BYTES
    require_https: bool = True


def _resolve_host_ips(hostname: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise MemoryHttpError(
            "dns_resolution_failed", "DNS resolution failed", retryable=True
        ) from exc
    ips: list[str] = []
    for info in infos:
        ip = info[4][0]
        if ip not in ips:
            ips.append(ip)
    return ips


def validate_url_ssrf(
    url: str,
    *,
    allowed_hosts: frozenset[str],
    require_https: bool = True,
) -> str:
    parsed = urlparse(url)
    if require_https and parsed.scheme != "https":
        # allow http only for localhost in tests
        host = (parsed.hostname or "").lower()
        if not (parsed.scheme == "http" and host in {"localhost", "127.0.0.1"}):
            raise MemoryHttpError("ssrf_blocked", "URL must use HTTPS", retryable=False)
    host = (parsed.hostname or "").lower()
    if not host:
        raise MemoryHttpError("ssrf_blocked", "URL host missing", retryable=False)
    if host not in allowed_hosts:
        raise MemoryHttpError("ssrf_blocked", "host not in allowlist", retryable=False)
    # DNS rebind protection: resolved IPs must not be unexpected public if host is localhost
    ips = _resolve_host_ips(host)
    for ip_s in ips:
        try:
            ip = ipaddress.ip_address(ip_s)
        except ValueError:
            continue
        if host in {"localhost", "127.0.0.1"} and not (ip.is_loopback or ip.is_private):
            raise MemoryHttpError("ssrf_rebind", "DNS rebind blocked", retryable=False)
        # Block link-local / multicast for non-local allowlisted hosts
        if host not in {"localhost", "127.0.0.1"} and (ip.is_link_local or ip.is_multicast):
            raise MemoryHttpError("ssrf_blocked", "resolved IP not allowed", retryable=False)
    return url.rstrip("/")


def classify_http_error(status: int) -> tuple[str, bool]:
    if status in (401, 403):
        return "auth_or_scope", False
    if status == 404:
        return "not_found", False
    if status in (408, 429) or status >= 500:
        return "upstream_retryable", True
    if status == 422:
        return "schema_validation", False
    if status == 503:
        return "backend_unavailable", True
    return "upstream_error", False


class SignalMemoryHttpClient:
    """Productive Memory.v1 client."""

    def __init__(self, config: MemoryClientConfig, transport: Transport) -> None:
        self.config = config
        self.transport = transport
        self.base = validate_url_ssrf(
            config.base_url,
            allowed_hosts=config.allowed_hosts,
            require_https=config.require_https,
        )

    def retrieve(
        self,
        *,
        external_tenant_id: str,
        dossier_id: str,
        query: str,
        purpose: str = "question",
        limit: int = 20,
        token_budget: int = 4000,
        correlation_id: str | None = None,
        kinds: list[str] | None = None,
        source_types: list[str] | None = None,
        classifications: list[str] | None = None,
        cutoff_at: str | None = None,
    ) -> dict[str, Any]:
        if not str(external_tenant_id or "").strip():
            raise MemoryHttpError("tenant_required", "external tenant required", retryable=False)
        # Fail closed: never trust browser tenant alone — caller must bind connection
        body: dict[str, Any] = {
            "query": query,
            "dossier_id": dossier_id,
            "purpose": purpose,
            "limit": limit,
            "token_budget": token_budget,
        }
        if kinds:
            body["kinds"] = kinds
        if source_types:
            body["source_types"] = source_types
        if classifications:
            body["classifications"] = classifications
        if cutoff_at:
            body["cutoff_at"] = cutoff_at

        corr = correlation_id or f"ora_{uuid.uuid4().hex[:16]}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-API-Key": self.config.api_token,
            "X-OPN-External-Tenant-ID": str(external_tenant_id).strip(),
            "X-OPN-Dossier-ID": str(dossier_id),
            "X-Request-ID": corr,
            "X-Correlation-ID": corr,
        }
        url = f"{self.base}/api/v1/memory/v1/retrieve"
        try:
            status, resp_headers, raw = self.transport.request(
                "POST",
                url,
                headers=headers,
                json_body=body,
                timeout=(self.config.connect_timeout, self.config.read_timeout),
            )
        except MemoryHttpError:
            raise
        except Exception as exc:
            raise MemoryHttpError("transport_error", "transport failure", retryable=True) from exc

        if len(raw) > self.config.max_bytes:
            raise MemoryHttpError("body_too_large", "response exceeds max bytes", retryable=False)

        ctype = (resp_headers.get("content-type") or resp_headers.get("Content-Type") or "").lower()
        if (
            status < 400
            and not any(ctype.startswith(p) for p in ALLOWED_MIME_PREFIXES)
            and ctype
            and "json" not in ctype
        ):
            raise MemoryHttpError("invalid_mime", "unexpected content-type", retryable=False)

        if status >= 400:
            code, retryable = classify_http_error(status)
            # never include raw body (may echo secrets) in message
            raise MemoryHttpError(
                code, f"memory upstream status={status}", http_status=status, retryable=retryable
            )

        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise MemoryHttpError("invalid_json", "response not JSON", retryable=False) from exc
        if not isinstance(data, dict):
            raise MemoryHttpError("invalid_json", "response not object", retryable=False)
        api_v = str(data.get("api_version") or "")
        if api_v and not api_v.startswith("memory"):
            raise MemoryHttpError(
                "unsupported_api_version", "unexpected api_version", retryable=False
            )
        return data

    def health(self, *, external_tenant_id: str) -> dict[str, Any]:
        corr = f"ora_h_{uuid.uuid4().hex[:12]}"
        headers = {
            "Accept": "application/json",
            "X-API-Key": self.config.api_token,
            "X-OPN-External-Tenant-ID": str(external_tenant_id).strip(),
            "X-Request-ID": corr,
        }
        url = f"{self.base}/api/v1/memory/v1/health"
        status, _hdrs, raw = self.transport.request(
            "GET",
            url,
            headers=headers,
            json_body=None,
            timeout=(self.config.connect_timeout, self.config.read_timeout),
        )
        if status >= 400:
            code, retryable = classify_http_error(status)
            raise MemoryHttpError(
                code, f"health status={status}", http_status=status, retryable=retryable
            )
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise MemoryHttpError("invalid_json", "health not JSON", retryable=False) from exc


class HttpxTransport:
    """Real httpx transport (optional dependency). Redirects disabled."""

    def __init__(self) -> None:
        import httpx

        self._client = httpx.Client(follow_redirects=False, timeout=20.0)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
        timeout: tuple[float, float],
    ) -> tuple[int, dict[str, str], bytes]:
        import httpx

        try:
            resp = self._client.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=httpx.Timeout(timeout[1], connect=timeout[0]),
            )
        except httpx.TimeoutException as exc:
            raise MemoryHttpError("timeout", "request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise MemoryHttpError("transport_error", "httpx failure", retryable=True) from exc
        # cap body
        content = resp.content[: MAX_RESPONSE_BYTES + 1]
        return resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, content
