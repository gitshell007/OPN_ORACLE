#!/usr/bin/env python3
"""Bounded HTTP load probe for an isolated OPN Oracle environment.

Credentials are read only from environment variables and never printed. This is not a production
benchmark; see docs/quality/PERFORMANCE_BUDGET.md.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import http.cookiejar
import json
import os
import random
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never allow a measured origin to redirect traffic to another host."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: object,
        code: int,
        message: str,
        headers: object,
        new_url: str,
    ) -> None:
        del request, file_pointer, code, message, headers, new_url
        return None


@dataclass(frozen=True, slots=True)
class Sample:
    scenario: str
    status: int
    elapsed_ms: float
    expected: bool


class OracleClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            NoRedirectHandler(), urllib.request.HTTPCookieProcessor(jar)
        )
        self.csrf = ""

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any], float]:
        payload = json.dumps(body).encode() if body is not None else None
        request_headers = {"Accept": "application/json", **(headers or {})}
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
        if method not in {"GET", "HEAD"}:
            request_headers["X-CSRF-Token"] = self.csrf
        started = time.perf_counter()
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=payload,
            headers=request_headers,
            method=method,
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            raw = error.read()
            status = error.code
        elapsed_ms = (time.perf_counter() - started) * 1000
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {}
        return status, parsed if isinstance(parsed, dict) else {}, elapsed_ms

    def authenticate(self, email: str, password: str, tenant_id: str) -> list[Sample]:
        status, payload, elapsed = self.request("GET", "/api/v1/auth/csrf")
        if status != 200 or not isinstance(payload.get("csrf_token"), str):
            raise RuntimeError(f"No se pudo obtener CSRF (HTTP {status}).")
        self.csrf = str(payload["csrf_token"])
        body: dict[str, Any] = {"email": email, "password": password}
        if tenant_id:
            body["tenant_id"] = tenant_id
        status, payload, login_elapsed = self.request(
            "POST", "/api/v1/auth/login", body=body
        )
        if status != 200:
            raise RuntimeError(
                f"Login sintético falló (HTTP {status}, code={payload.get('code')})."
            )
        # Login rotates both session ID and CSRF token.
        status, payload, csrf_elapsed = self.request("GET", "/api/v1/auth/csrf")
        if status != 200:
            raise RuntimeError(f"No se pudo renovar CSRF (HTTP {status}).")
        self.csrf = str(payload["csrf_token"])
        return [
            Sample("csrf_bootstrap", 200, elapsed, True),
            Sample("login", 200, login_elapsed, True),
            Sample("csrf_after_login", 200, csrf_elapsed, True),
        ]


def percentile(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * value)))
    return ordered[index]


def scenario(
    client: OracleClient, name: str, dossier_id: str, mutations: bool
) -> Sample:
    query = urllib.parse.urlencode({"page[number]": 1, "page[size]": 25})
    cases = {
        "me": ("GET", "/api/v1/auth/me", None, {}),
        "dossiers": ("GET", f"/api/v1/dossiers?{query}", None, {}),
        "signals": (
            "GET",
            f"/api/v1/signals?{query}&filter%5Bscore_min%5D=40&sort=-overall_score",
            None,
            {},
        ),
        "search": (
            "GET",
            "/api/v1/search?q=alianza&page%5Bnumber%5D=1&page%5Bsize%5D=10",
            None,
            {},
        ),
        "jobs": ("GET", f"/api/v1/jobs?{query}", None, {}),
    }
    if name in cases:
        method, path, body, headers = cases[name]
    elif name == "create_update" and mutations:
        marker = uuid.uuid4().hex[:10]
        method, path = "POST", "/api/v1/dossiers"
        status, payload, elapsed = client.request(
            method,
            path,
            body={"title": f"Perf sintético {marker}", "type": "custom"},
            headers={"Idempotency-Key": f"perf-dossier-{marker}"},
        )
        if status != 201:
            return Sample(name, status, elapsed, False)
        resource_id = str(payload.get("id", ""))
        version = int(payload.get("version", 1))
        status, _, update_elapsed = client.request(
            "PATCH",
            f"/api/v1/dossiers/{resource_id}",
            body={"description": "Medición sintética acotada", "version": version},
            headers={"If-Match": f'W/"{version}"'},
        )
        return Sample(name, status, elapsed + update_elapsed, status == 200)
    elif name == "report_enqueue" and mutations and dossier_id:
        marker = uuid.uuid4().hex
        method, path = "POST", f"/api/v1/dossiers/{dossier_id}/reports"
        body = {"template_key": "executive_dossier", "options": {}}
        headers = {"Idempotency-Key": f"perf-report-{marker}"}
    else:
        return Sample(name, 0, 0.0, False)
    status, _, elapsed = client.request(method, path, body=body, headers=headers)
    return Sample(name, status, elapsed, 200 <= status < 300)


def worker(
    worker_id: int,
    deadline: float,
    args: argparse.Namespace,
    email: str,
    password: str,
    tenant_id: str,
    dossier_id: str,
    mutations: bool,
) -> list[Sample]:
    client = OracleClient(args.base_url, args.timeout)
    samples = client.authenticate(email, password, tenant_id)
    names = ["me", "dossiers", "signals", "search", "jobs"]
    if mutations:
        names.append("create_update")
        if dossier_id:
            names.append("report_enqueue")
    rng = random.Random(f"opn-oracle-perf-{worker_id}")
    while time.monotonic() < deadline:
        samples.append(scenario(client, rng.choice(names), dossier_id, mutations))
        time.sleep(args.think_time)
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--think-time", type=float, default=0.25)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-staging",
        action="store_true",
        help="permit an explicitly authorized non-loopback staging origin",
    )
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 100 or not 5 <= args.duration <= 3600:
        parser.error("concurrency debe ser 1..100 y duration 5..3600")
    parsed = urllib.parse.urlparse(args.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        parser.error("base-url debe ser un origen HTTP(S) absoluto")
    if parsed.username or parsed.password:
        parser.error("base-url no admite credenciales embebidas")
    if (
        parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        and not args.allow_staging
    ):
        parser.error(
            "el target no es loopback; usa --allow-staging solo con autorización"
        )
    email = os.environ.get("ORACLE_PERF_EMAIL", "")
    password = os.environ.get("ORACLE_PERF_PASSWORD", "")
    tenant_id = os.environ.get("ORACLE_PERF_TENANT_ID", "")
    dossier_id = os.environ.get("ORACLE_PERF_DOSSIER_ID", "")
    mutations = os.environ.get("ORACLE_PERF_MUTATIONS") == "1"
    if not email or not password:
        parser.error("ORACLE_PERF_EMAIL y ORACLE_PERF_PASSWORD son obligatorias")
    deadline = time.monotonic() + args.duration
    all_samples: list[Sample] = []
    errors: list[str] = []
    lock = threading.Lock()
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.concurrency
    ) as executor:
        futures = [
            executor.submit(
                worker,
                index,
                deadline,
                args,
                email,
                password,
                tenant_id,
                dossier_id,
                mutations,
            )
            for index in range(args.concurrency)
        ]
        for future in concurrent.futures.as_completed(futures):
            try:
                with lock:
                    all_samples.extend(future.result())
            except Exception as error:
                errors.append(type(error).__name__)
    result: dict[str, Any] = {
        "duration_seconds": args.duration,
        "concurrency": args.concurrency,
        "mutations": mutations,
        "worker_errors": errors,
        "scenarios": {},
    }
    for name in sorted({sample.scenario for sample in all_samples}):
        values = [
            sample.elapsed_ms for sample in all_samples if sample.scenario == name
        ]
        failures = [
            sample
            for sample in all_samples
            if sample.scenario == name and not sample.expected
        ]
        result["scenarios"][name] = {
            "requests": len(values),
            "p50_ms": round(statistics.median(values), 2) if values else 0,
            "p95_ms": round(percentile(values, 0.95), 2),
            "p99_ms": round(percentile(values, 0.99), 2),
            "unexpected_errors": len(failures),
            "unexpected_error_rate": round(len(failures) / len(values), 4)
            if values
            else 1,
        }
    output = json.dumps(result, indent=2, sort_keys=True)
    print(output)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    return 1 if errors or any(not sample.expected for sample in all_samples) else 0


if __name__ == "__main__":
    raise SystemExit(main())
