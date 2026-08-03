#!/usr/bin/env python3
"""One-shot: run intake on the SV2 demo dossier and print AI-audit evidence."""

from __future__ import annotations

import json
import re
import time
import uuid
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

BASE = "https://oracle-dev.opnconsultoria.com"
DOSSIER = "ab7bba16-3e55-4f35-ad73-0c84e2850688"
TENANT = "a6edb3c8-0611-4d7a-a6e1-e882c7460539"
CREDS_PATH = Path("/root/sv2_demo_owner_credentials.txt")


def parse_creds(text: str) -> tuple[str, str]:
    email = password = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            key = key.strip().lower()
            value = value.strip().strip("\"'")
            if key in {"email", "username", "user"}:
                email = value
            if key in {"password", "pass", "passwd"}:
                password = value
        elif "@" in line and email is None:
            match = re.search(r"[\w.+-]+@[\w.-]+", line)
            if match:
                email = match.group(0)
    if email is None or password is None:
        raise SystemExit(f"No se pudieron leer credenciales de {CREDS_PATH}")
    return email, password


class Client:
    def __init__(self) -> None:
        self.cj = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.csrf: str | None = None
        self.timeout = 90.0

    def request(self, method: str, path: str, data: dict | None = None, headers: dict | None = None):
        body = None
        req_headers = {
            "Accept": "application/json",
            "Origin": BASE,
            "Referer": f"{BASE}/app",
            **(headers or {}),
        }
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        if self.csrf and method in {"POST", "PATCH", "PUT", "DELETE"}:
            req_headers.setdefault("X-CSRF-Token", self.csrf)
        req = urllib.request.Request(BASE + path, data=body, headers=req_headers, method=method)
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8") if resp.length != 0 else ""
                text = resp.read().decode("utf-8") if False else raw
                payload = json.loads(text) if text else None
                return int(resp.status), payload
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {"detail": str(error)}
            except json.JSONDecodeError:
                payload = {"detail": raw[:800]}
            return int(error.code), payload

    def refresh_csrf(self) -> None:
        code, payload = self.request("GET", "/api/v1/auth/csrf")
        if code != 200 or not isinstance(payload, dict) or not payload.get("csrf_token"):
            raise SystemExit(f"CSRF falló {code}: {payload!r}")
        self.csrf = str(payload["csrf_token"])

    def login(self, email: str, password: str) -> None:
        self.refresh_csrf()
        code, payload = self.request(
            "POST",
            "/api/v1/auth/login",
            {"email": email, "password": password, "tenant_id": TENANT},
        )
        if code != 200:
            raise SystemExit(f"Login falló {code}: {payload!r}")
        self.refresh_csrf()


def main() -> None:
    email, password = parse_creds(CREDS_PATH.read_text())
    client = Client()
    client.login(email, password)

    key = f"sv2-intake-probe-{uuid.uuid4()}"
    code, run = client.request(
        "POST",
        f"/api/v1/ai/dossiers/{DOSSIER}/intake/runs",
        {},
        {"Idempotency-Key": key},
    )
    print("intake_run", code)
    print(json.dumps(run, default=str)[:800])
    if code != 202:
        raise SystemExit(1)

    job = (run or {}).get("job") or {}
    job_id = job.get("id")
    status = job.get("status")
    for attempt in range(45):
        if status in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(2)
        code_j, job_payload = client.request("GET", f"/api/v1/jobs/{job_id}")
        status = job_payload.get("status") if isinstance(job_payload, dict) else None
        print(f"poll[{attempt}] {code_j} {status}")

    code_l, latest = client.request("GET", f"/api/v1/ai/dossiers/{DOSSIER}/intake/latest")
    print("latest", code_l)
    artifact = (latest or {}).get("artifact") if isinstance(latest, dict) else None
    if artifact:
        print(
            "artifact",
            artifact.get("agent"),
            artifact.get("status"),
            "audit_log_id=",
            artifact.get("audit_log_id"),
        )
        output = artifact.get("output") or {}
        print("proposed_title=", output.get("proposed_title"))
        print("facts=", len(output.get("facts") or []))
        print("inferences=", len(output.get("inferences") or []))

    code_a, audits = client.request(
        "GET",
        f"/api/v1/ai-audit?agent=intake&dossier_id={DOSSIER}",
    )
    print("audit_list", code_a)
    items = []
    if isinstance(audits, dict):
        items = audits.get("items") or audits.get("data") or []
    print("audit_count", len(items))
    if items:
        top = items[0]
        print(
            json.dumps(
                {
                    "id": top.get("id"),
                    "agent": top.get("agent"),
                    "status": top.get("status"),
                    "provider": top.get("provider"),
                    "model": top.get("model"),
                    "input_tokens": top.get("input_tokens"),
                    "output_tokens": top.get("output_tokens"),
                    "cost_micros": top.get("cost_micros"),
                    "latency_ms": top.get("latency_ms"),
                    "source_ids": top.get("source_ids"),
                    "dossier_id": top.get("dossier_id"),
                    "human_review_state": top.get("human_review_state"),
                },
                default=str,
            )
        )

    code_ui, _ = client.request("GET", f"/app/dossiers/{DOSSIER}/intake")
    print("ui_intake", code_ui)
    code_ui2, _ = client.request("GET", "/app/admin/ai-audit")
    print("ui_audit", code_ui2)
    if not items:
        raise SystemExit("No hay filas de auditoría para agent=intake")
    if items[0].get("agent") != "intake":
        raise SystemExit("La fila de auditoría no es intake")
    print("PROBE_PASS")


if __name__ == "__main__":
    main()
