#!/usr/bin/env python3
"""Small non-destructive DAST baseline for an owned local/staging Oracle API."""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep every probe on the explicitly authorized origin."""

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


OPENER = urllib.request.build_opener(NoRedirectHandler())


@dataclass(frozen=True, slots=True)
class Finding:
    check: str
    passed: bool
    detail: str


def fetch(
    base_url: str, path: str, *, method: str = "GET"
) -> tuple[int, dict[str, str], str]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        method=method,
        headers={"Accept": "application/json", "Origin": "https://attacker.invalid"},
    )
    try:
        with OPENER.open(request, timeout=5) as response:
            return (
                response.status,
                dict(response.headers.items()),
                response.read().decode(errors="replace"),
            )
    except urllib.error.HTTPError as error:
        return (
            error.code,
            dict(error.headers.items()),
            error.read().decode(errors="replace"),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5001")
    parser.add_argument(
        "--allow-staging",
        action="store_true",
        help="permit a non-loopback owned staging target; never implies production authorization",
    )
    args = parser.parse_args()
    parsed = urllib.parse.urlparse(args.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        parser.error("El target debe ser un origen HTTP(S) absoluto.")
    if parsed.username or parsed.password:
        parser.error("El target no admite credenciales embebidas en la URL.")
    if (
        parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        and not args.allow_staging
    ):
        parser.error(
            "El target no es loopback; usa --allow-staging solo con autorización explícita."
        )

    findings: list[Finding] = []
    status, headers, body = fetch(args.base_url, "/health/live")
    findings.append(Finding("liveness", status == 200, f"HTTP {status}"))
    for header, expected in {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
    }.items():
        findings.append(
            Finding(
                f"header:{header}",
                headers.get(header) == expected,
                headers.get(header, "missing"),
            )
        )
    server = headers.get("Server", "")
    findings.append(
        Finding(
            "server-version",
            re.search(r"\d+\.\d+", server) is None,
            server or "not disclosed",
        )
    )
    findings.append(
        Finding(
            "cors-deny-untrusted",
            headers.get("Access-Control-Allow-Origin")
            not in {"*", "https://attacker.invalid"},
            headers.get("Access-Control-Allow-Origin", "not reflected"),
        )
    )

    status, headers, body = fetch(args.base_url, "/api/v1/auth/me")
    findings.append(Finding("auth-required", status == 401, f"HTTP {status}"))
    findings.append(
        Finding(
            "sensitive-no-store",
            "no-store" in headers.get("Cache-Control", ""),
            headers.get("Cache-Control", "missing"),
        )
    )
    findings.append(
        Finding(
            "problem-no-trace",
            "traceback" not in body.lower(),
            "traceback absent"
            if "traceback" not in body.lower()
            else "traceback exposed",
        )
    )

    status, _, _ = fetch(args.base_url, "/internal/metrics")
    findings.append(Finding("metrics-hidden", status == 404, f"HTTP {status}"))

    for path in (
        "/api/v1/%2e%2e/%2e%2e/etc/passwd",
        "/api/v1/not-found%3Cscript%3Ewindow.__xss=1%3C/script%3E",
        "/api/v1/search?q=%27%20OR%201%3D1--",
    ):
        status, _, body = fetch(args.base_url, path)
        passed = status in {400, 401, 404, 422} and "traceback" not in body.lower()
        findings.append(Finding(f"safe-input:{path[:36]}", passed, f"HTTP {status}"))

    port = parsed.port or ("443" if parsed.scheme == "https" else "80")
    result = {
        "target": f"{parsed.scheme}://{parsed.hostname}:{port}",
        "checks": [asdict(finding) for finding in findings],
        "passed": sum(finding.passed for finding in findings),
        "failed": sum(not finding.passed for finding in findings),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
