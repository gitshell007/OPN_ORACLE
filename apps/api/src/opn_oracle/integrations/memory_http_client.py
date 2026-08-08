"""Signal Memory HTTP client (MDEV-04 REWORK).

Tenant-scoped, injectable transport, SSRF/allowlist per request, strict memory.v1,
retry only for retryable statuses, no secrets/query in logs.
"""

from __future__ import annotations

import ipaddress
import json
import random
import socket
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

DEFAULT_ALLOWED_HOSTS = frozenset(
    {
        "signal.opnconsultoria.com",
        "signal-dev.opnconsultoria.com",
        "localhost",
        "127.0.0.1",
        "host.docker.internal",
    }
)

MAX_RESPONSE_BYTES = 2_000_000
ALLOWED_MIME_PREFIXES = ("application/json", "application/problem+json")
ALLOWED_KINDS = frozenset(
    {"fact", "chunk", "summary", "observation", "conflict", "entity", "claim"}
)
ALLOWED_SOURCES = frozenset(
    {"document", "signal", "intent_metadata", "web", "rss", "borme", "patent"}
)
ALLOWED_CLASSIFICATIONS = frozenset({"public", "internal", "confidential", "restricted"})


class MemoryHttpError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
        retryable: bool = False,
        job_error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable
        # Stable durable-job code when this error terminates a background job.
        self.job_error_code = job_error_code or (
            code
            if code
            in {
                "memory_grant_manual_required",
                "memory_grant_rejected",
                "memory_dossier_not_authorized",
                "memory_grant_unknown",
            }
            else None
        )


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
        timeout: tuple[float, float],
    ) -> tuple[int, dict[str, str], bytes]: ...


@dataclass
class MockTransport:
    responses: dict[str, tuple[int, dict[str, str], bytes]] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)
    default: tuple[int, dict[str, str], bytes] = (
        200,
        {"content-type": "application/json"},
        b'{"api_version":"memory.v1","items":[],"coverage_manifest":{"version":"coverage_manifest.v1","requested":[],"consulted":[],"failed":[],"excluded":[],"used":[],"truncated":false,"truncation_notes":[],"cutoff_at":null,"token_budget":0,"token_used_estimate":0},"watermark":null}',
    )
    # optional DNS rebind simulation for tests
    resolve_override: dict[str, list[str]] | None = None

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
        timeout: tuple[float, float],
    ) -> tuple[int, dict[str, str], bytes]:
        safe_headers = {
            k: ("***" if k.lower() in {"x-api-key", "authorization"} else v)
            for k, v in headers.items()
        }
        # never store full query text — hash only
        body_log: dict[str, Any] | None
        if isinstance(json_body, dict) and "query" in json_body:
            import hashlib

            q = str(json_body.get("query") or "")
            qhash = hashlib.sha256(q.encode()).hexdigest()[:16]
            body_log = {**json_body, "query": f"sha256:{qhash}:len={len(q)}"}
        else:
            body_log = dict(json_body) if isinstance(json_body, dict) else None
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": safe_headers,
                "json_body": body_log,
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
    max_retries: int = 2
    deadline_seconds: float = 25.0


def _resolve_host_ips(hostname: str, override: dict[str, list[str]] | None = None) -> list[str]:
    if override and hostname in override:
        return list(override[hostname])
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise MemoryHttpError(
            "dns_resolution_failed", "DNS resolution failed", retryable=True
        ) from exc
    ips: list[str] = []
    for info in infos:
        ip = info[4][0]
        if isinstance(ip, str) and ip not in ips:
            ips.append(ip)
    return ips


def validate_url_ssrf(
    url: str,
    *,
    allowed_hosts: frozenset[str],
    require_https: bool = True,
    dns_override: dict[str, list[str]] | None = None,
) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if (
        require_https
        and parsed.scheme != "https"
        and not (parsed.scheme == "http" and host in {"localhost", "127.0.0.1"})
    ):
        raise MemoryHttpError("ssrf_blocked", "URL must use HTTPS", retryable=False)
    if not host:
        raise MemoryHttpError("ssrf_blocked", "URL host missing", retryable=False)
    if host not in allowed_hosts:
        raise MemoryHttpError("ssrf_blocked", "host not in allowlist", retryable=False)
    ips = _resolve_host_ips(host, dns_override)
    for ip_s in ips:
        try:
            ip = ipaddress.ip_address(ip_s)
        except ValueError:
            continue
        if host in {"localhost", "127.0.0.1"}:
            # loopback only — private/link-local rebind is blocked
            if not ip.is_loopback:
                raise MemoryHttpError("ssrf_rebind", "DNS rebind blocked", retryable=False)
        elif ip.is_link_local or ip.is_multicast or ip.is_loopback or ip.is_private:
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


def validate_memory_v1_response(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise MemoryHttpError("invalid_json", "response not object", retryable=False)
    if data.get("api_version") != "memory.v1":
        raise MemoryHttpError(
            "unsupported_api_version", "api_version must be memory.v1", retryable=False
        )
    items = data.get("items")
    if items is None:
        items = []
    if not isinstance(items, list):
        raise MemoryHttpError("schema_validation", "items must be list", retryable=False)
    for it in items:
        if not isinstance(it, dict):
            raise MemoryHttpError("schema_validation", "item must be object", retryable=False)
        kind = it.get("kind")
        if kind is not None and str(kind) not in ALLOWED_KINDS:
            raise MemoryHttpError("schema_validation", f"invalid kind {kind}", retryable=False)
    cov = data.get("coverage_manifest")
    if cov is not None:
        if not isinstance(cov, dict):
            raise MemoryHttpError(
                "schema_validation", "coverage_manifest must be object", retryable=False
            )
        if cov.get("version") not in (None, "coverage_manifest.v1"):
            raise MemoryHttpError("schema_validation", "bad coverage version", retryable=False)
        # failure vs empty: failed non-empty is not legitimate empty
        failed = cov.get("failed") or []
        if failed and items == []:
            # ok: explicit failure with empty items
            pass
    return data


class SignalMemoryHttpClient:
    def __init__(self, config: MemoryClientConfig, transport: Transport) -> None:
        self.config = config
        self.transport = transport
        # validate base once, re-validate every request for rebind
        self.base = validate_url_ssrf(
            config.base_url,
            allowed_hosts=config.allowed_hosts,
            require_https=config.require_https,
        )

    def _effective_dns_override(self) -> dict[str, list[str]] | None:
        return getattr(self.transport, "resolve_override", None)

    def _request_once(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
    ) -> tuple[int, dict[str, str], bytes]:
        # Per-request SSRF + DNS rebind check (destination must not change to bad IP)
        url = f"{self.base}{path}"
        validate_url_ssrf(
            url,
            allowed_hosts=self.config.allowed_hosts,
            require_https=self.config.require_https,
            dns_override=self._effective_dns_override(),
        )
        try:
            return self.transport.request(
                method,
                url,
                headers=headers,
                json_body=json_body,
                timeout=(self.config.connect_timeout, self.config.read_timeout),
            )
        except MemoryHttpError:
            raise
        except Exception as exc:
            raise MemoryHttpError("transport_error", "transport failure", retryable=True) from exc

    def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
    ) -> tuple[int, dict[str, str], bytes]:
        deadline = time.monotonic() + float(self.config.deadline_seconds)
        attempt = 0
        last_err: MemoryHttpError | None = None
        while attempt <= self.config.max_retries:
            if time.monotonic() > deadline:
                raise MemoryHttpError("deadline_exceeded", "deadline exceeded", retryable=False)
            try:
                status, hdrs, raw = self._request_once(
                    method, path, headers=headers, json_body=json_body
                )
            except MemoryHttpError as exc:
                last_err = exc
                if not exc.retryable or attempt >= self.config.max_retries:
                    raise
                delay = min(2.0, 0.2 * (2**attempt)) + random.uniform(0, 0.1)
                time.sleep(delay)
                attempt += 1
                continue
            if status >= 400:
                code, retryable = classify_http_error(status)
                err = MemoryHttpError(
                    code,
                    f"memory upstream status={status}",
                    http_status=status,
                    retryable=retryable,
                )
                if not retryable or attempt >= self.config.max_retries:
                    raise err
                last_err = err
                delay = min(2.0, 0.2 * (2**attempt)) + random.uniform(0, 0.1)
                time.sleep(delay)
                attempt += 1
                continue
            return status, hdrs, raw
        if last_err:
            raise last_err
        raise MemoryHttpError("upstream_error", "retry exhausted", retryable=False)

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
        if not (1 <= int(limit) <= 100):
            raise MemoryHttpError("schema_validation", "limit out of range", retryable=False)
        if not (0 <= int(token_budget) <= 128000):
            raise MemoryHttpError("schema_validation", "token_budget out of range", retryable=False)
        if kinds:
            for k in kinds:
                if str(k) not in ALLOWED_KINDS:
                    raise MemoryHttpError(
                        "schema_validation", f"kind not allowed: {k}", retryable=False
                    )
        if source_types:
            for s in source_types:
                if str(s) not in ALLOWED_SOURCES:
                    raise MemoryHttpError(
                        "schema_validation", f"source not allowed: {s}", retryable=False
                    )
        if classifications:
            for c in classifications:
                if str(c) not in ALLOWED_CLASSIFICATIONS:
                    raise MemoryHttpError(
                        "schema_validation", f"classification not allowed: {c}", retryable=False
                    )

        body: dict[str, Any] = {
            "query": query,
            "dossier_id": dossier_id,
            "purpose": purpose,
            "limit": int(limit),
            "token_budget": int(token_budget),
        }
        if kinds:
            body["kinds"] = list(kinds)
        if source_types:
            body["source_types"] = list(source_types)
        if classifications:
            body["classifications"] = list(classifications)
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
        status, resp_headers, raw = self._request_with_retry(
            "POST", "/api/v1/memory/v1/retrieve", headers=headers, json_body=body
        )
        if len(raw) > self.config.max_bytes:
            raise MemoryHttpError("body_too_large", "response exceeds max bytes", retryable=False)
        ctype = (resp_headers.get("content-type") or resp_headers.get("Content-Type") or "").lower()
        if (
            status < 400
            and ctype
            and not any(ctype.startswith(p) for p in ALLOWED_MIME_PREFIXES)
            and "json" not in ctype
        ):
            raise MemoryHttpError("invalid_mime", "unexpected content-type", retryable=False)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise MemoryHttpError("invalid_json", "response not JSON", retryable=False) from exc
        return validate_memory_v1_response(data)

    def health(self, *, external_tenant_id: str) -> dict[str, Any]:
        corr = f"ora_h_{uuid.uuid4().hex[:12]}"
        headers = {
            "Accept": "application/json",
            "X-API-Key": self.config.api_token,
            "X-OPN-External-Tenant-ID": str(external_tenant_id).strip(),
            "X-Request-ID": corr,
        }
        _status, _hdrs, raw = self._request_with_retry(
            "GET", "/api/v1/memory/v1/health", headers=headers, json_body=None
        )
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise MemoryHttpError("invalid_json", "health not JSON", retryable=False) from exc
        if not isinstance(data, dict):
            raise MemoryHttpError("invalid_json", "health not object", retryable=False)
        return data

    # Signal error_codes from POST /dossiers/{id}/authorize (SIG-AUTOGRANT, live).
    # Manual path is terminal: never retry aggressively.
    _AUTHORIZE_MANUAL_CODES = frozenset(
        {
            "dossier_authorization_manual_required",
            "memory_grant_manual_required",
        }
    )
    _AUTHORIZE_REJECTED_CODES = frozenset(
        {
            "tenant_not_allowed",
            "insufficient_scope",
            "credential_tenant_mismatch",
        }
    )

    def authorize_dossier(
        self,
        *,
        external_tenant_id: str,
        dossier_id: str,
        correlation_id: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """Request consumer_memory_dossier_grants via the real Signal path.

        Live contract (signal-dev, SIG-AUTOGRANT — NOT scopes/ensure stub):

            POST /api/v1/memory/v1/dossiers/{dossier_id}/authorize
            Headers: X-API-Key, X-OPN-External-Tenant-ID, Accept
            Body: none (dossier_id is path-only)

        Success 200::
            {
              "dossier_id": "<uuid>",
              "authorized": true,
              "reason": "granted" | "already_active" | "reactivated",
              "granted_by": "auto",
              "created": bool,
              "reactivated": bool
            }

        403 MemoryErrorEnvelope::
            {
              "error_code": "dossier_authorization_manual_required" | "tenant_not_allowed",
              "http_status": 403,
              "retryable": false,
              "message": "...",
              "detail": null
            }

        ``/scopes/ensure`` is a non-persisting stub that *requires* an existing
        grant — do not call it for autogrant.
        """
        if not str(external_tenant_id or "").strip():
            raise MemoryHttpError("tenant_required", "external tenant required", retryable=False)
        try:
            dossier = str(__import__("uuid").UUID(str(dossier_id)))
        except (TypeError, ValueError) as exc:
            raise MemoryHttpError(
                "schema_validation", "dossier_id must be a UUID", retryable=False
            ) from exc
        path = f"/api/v1/memory/v1/dossiers/{dossier}/authorize"
        corr = correlation_id or f"ora_authz_{uuid.uuid4().hex[:16]}"
        headers = {
            "Accept": "application/json",
            "X-API-Key": self.config.api_token,
            "X-OPN-External-Tenant-ID": str(external_tenant_id).strip(),
            "X-OPN-Dossier-ID": dossier,
            "X-Request-ID": corr,
            "X-Correlation-ID": corr,
        }
        deadline = time.monotonic() + float(self.config.deadline_seconds)
        attempt = 0
        last_err: MemoryHttpError | None = None
        while attempt <= self.config.max_retries:
            if time.monotonic() > deadline:
                raise MemoryHttpError("deadline_exceeded", "deadline exceeded", retryable=False)
            try:
                # No body: path carries dossier_id (Signal live contract).
                status, _hdrs, raw = self._request_once(
                    "POST", path, headers=headers, json_body=None
                )
            except MemoryHttpError as exc:
                last_err = exc
                if not exc.retryable or attempt >= self.config.max_retries:
                    raise
                time.sleep(min(2.0, 0.2 * (2**attempt)) + random.uniform(0, 0.1))
                attempt += 1
                continue
            if len(raw) > self.config.max_bytes:
                raise MemoryHttpError(
                    "body_too_large", "response exceeds max bytes", retryable=False
                )
            data: dict[str, Any]
            if not raw:
                data = {}
            else:
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except Exception as exc:
                    raise MemoryHttpError(
                        "invalid_json", "response not JSON", retryable=False
                    ) from exc
                data = parsed if isinstance(parsed, dict) else {"value": parsed}
            if status < 400:
                return status, data
            body_code = str(data.get("error_code") or data.get("code") or "").strip()
            code, retryable = classify_http_error(status)
            if body_code:
                code = body_code
            if code in self._AUTHORIZE_MANUAL_CODES or code in self._AUTHORIZE_REJECTED_CODES:
                retryable = False
            job_code: str | None = None
            if code in self._AUTHORIZE_MANUAL_CODES:
                job_code = "memory_grant_manual_required"
            elif code == "tenant_not_allowed":
                job_code = "memory_grant_rejected"
            elif code == "dossier_not_authorized":
                job_code = "memory_dossier_not_authorized"
            err = MemoryHttpError(
                code,
                str(data.get("message") or f"memory authorize status={status}"),
                http_status=status,
                retryable=retryable,
                job_error_code=job_code,
            )
            if not retryable or attempt >= self.config.max_retries:
                raise err
            last_err = err
            time.sleep(min(2.0, 0.2 * (2**attempt)) + random.uniform(0, 0.1))
            attempt += 1
        if last_err:
            raise last_err
        raise MemoryHttpError(
            "upstream_error", "authorize_dossier retry exhausted", retryable=False
        )

    def ensure_scope(
        self,
        *,
        external_tenant_id: str,
        dossier_id: str,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """Deprecated alias: scopes/ensure is a non-persisting stub on Signal.

        Kept only so call sites that still say ensure_scope hit authorize_dossier.
        ``idempotency_key`` is ignored (authorize is path-idempotent server-side).
        """
        del idempotency_key
        return self.authorize_dossier(
            external_tenant_id=external_tenant_id,
            dossier_id=dossier_id,
            correlation_id=correlation_id,
        )

    def post_json(
        self,
        path: str,
        *,
        external_tenant_id: str,
        dossier_id: str | None = None,
        body: dict[str, Any],
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """Generic authenticated JSON POST for memory write paths (bilateral/durable ingest)."""
        if not str(external_tenant_id or "").strip():
            raise MemoryHttpError("tenant_required", "external tenant required", retryable=False)
        if not path.startswith("/"):
            path = f"/{path}"
        corr = correlation_id or f"ora_w_{uuid.uuid4().hex[:16]}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-API-Key": self.config.api_token,
            "X-OPN-External-Tenant-ID": str(external_tenant_id).strip(),
            "X-Request-ID": corr,
            "X-Correlation-ID": corr,
        }
        if dossier_id:
            headers["X-OPN-Dossier-ID"] = str(dossier_id)
        if idempotency_key:
            headers["Idempotency-Key"] = str(idempotency_key)[:200]
        status, _hdrs, raw = self._request_with_retry("POST", path, headers=headers, json_body=body)
        if len(raw) > self.config.max_bytes:
            raise MemoryHttpError("body_too_large", "response exceeds max bytes", retryable=False)
        data: dict[str, Any]
        if not raw:
            data = {}
        else:
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except Exception as exc:
                raise MemoryHttpError("invalid_json", "response not JSON", retryable=False) from exc
            data = parsed if isinstance(parsed, dict) else {"value": parsed}
        if status >= 500:
            raise MemoryHttpError(
                "upstream_error",
                f"memory write status={status}",
                http_status=status,
                retryable=True,
            )
        if status >= 400:
            code = str(data.get("error_code") or data.get("code") or "upstream_error")
            # bilateral flags OFF → 503 disabled: retryable until ops enable flags
            retryable = status in {408, 425, 429, 503} or "disabled" in code
            raise MemoryHttpError(
                code,
                f"memory write status={status}",
                http_status=status,
                retryable=retryable,
            )
        return status, data


class HttpxTransport:
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
        content = resp.content[: MAX_RESPONSE_BYTES + 1]
        return resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, content
