#!/usr/bin/env python3
"""SV2-INTAKE-E2E · camino feliz + cancelado en oracle-dev.

Recorre el ciclo real:
  1) propuesta del agente intake (job succeeded + fila en /api/v1/ai-audit)
  2) cancelado: review rejected → el expediente y las entidades no cambian
  3) feliz: PATCH título/descripción + review accepted → expediente refleja la propuesta

Credenciales solo en el host (nunca en el repo):

  python3 scripts/sv2_intake_e2e.py

Variables opcionales: ORACLE_BASE_URL, ORACLE_CREDS_PATH, DOSSIER_ID, TENANT_ID,
RESTORE_DEMO_TITLE (default 1).
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any


DEFAULT_BASE = "https://oracle-dev.opnconsultoria.com"
DEFAULT_CREDS = "/root/sv2_demo_owner_credentials.txt"
DEFAULT_DOSSIER = "ab7bba16-3e55-4f35-ad73-0c84e2850688"
DEFAULT_TENANT = "a6edb3c8-0611-4d7a-a6e1-e882c7460539"


def env(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def parse_creds(text: str) -> tuple[str, str]:
    email = password = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lower()
        value = value.strip().strip("\"'")
        if key in {"email", "username", "user"}:
            email = value
        if key in {"password", "pass", "passwd"}:
            password = value
    if email is None or password is None:
        raise SystemExit("No se pudieron leer email/password de credenciales.")
    return email, password


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.cj = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.csrf: str | None = None
        self.timeout = 120.0

    def request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        body = None
        req_headers = {
            "Accept": "application/json",
            "Origin": self.base,
            "Referer": f"{self.base}/app",
            **(headers or {}),
        }
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        if self.csrf and method in {"POST", "PATCH", "PUT", "DELETE"}:
            req_headers.setdefault("X-CSRF-Token", self.csrf)
        req = urllib.request.Request(
            self.base + path, data=body, headers=req_headers, method=method
        )
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return int(resp.status), (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", errors="replace")
            try:
                payload: Any = json.loads(raw) if raw else {"detail": str(error)}
            except json.JSONDecodeError:
                payload = {"detail": raw[:800]}
            return int(error.code), payload

    def refresh_csrf(self) -> None:
        code, payload = self.request("GET", "/api/v1/auth/csrf")
        if code != 200 or not isinstance(payload, dict) or not payload.get("csrf_token"):
            raise SystemExit(f"CSRF falló {code}: {payload!r}")
        self.csrf = str(payload["csrf_token"])

    def login(self, email: str, password: str, tenant_id: str) -> None:
        self.refresh_csrf()
        code, payload = self.request(
            "POST",
            "/api/v1/auth/login",
            {"email": email, "password": password, "tenant_id": tenant_id},
        )
        if code != 200:
            raise SystemExit(f"Login falló {code}: {payload!r}")
        self.refresh_csrf()


def snapshot(client: Client, dossier_id: str) -> dict[str, Any]:
    code, dossier = client.request("GET", f"/api/v1/dossiers/{dossier_id}")
    if code != 200 or not isinstance(dossier, dict):
        raise SystemExit(f"No se pudo leer expediente {code}: {dossier!r}")
    counts: dict[str, Any] = {}
    for name, path in [
        ("actors", f"/api/v1/dossiers/{dossier_id}/actors"),
        ("opportunities", f"/api/v1/dossiers/{dossier_id}/opportunities"),
        ("risks", f"/api/v1/dossiers/{dossier_id}/risks"),
        ("signals", f"/api/v1/dossiers/{dossier_id}/signals"),
    ]:
        code_c, payload = client.request("GET", path)
        if code_c == 200 and isinstance(payload, dict):
            items = payload.get("items") or payload.get("data") or payload.get("actors") or []
            counts[name] = len(items) if isinstance(items, list) else payload.get("total")
        else:
            counts[name] = f"http_{code_c}"
    return {
        "title": dossier.get("title"),
        "description": dossier.get("description") or "",
        "version": dossier.get("version"),
        "status": dossier.get("status"),
        "dossier_type": dossier.get("dossier_type"),
        "counts": counts,
    }


def run_intake(client: Client, dossier_id: str) -> tuple[str, str, dict[str, Any] | None]:
    key = f"sv2-intake-e2e-{uuid.uuid4()}"
    code, run = client.request(
        "POST",
        f"/api/v1/ai/dossiers/{dossier_id}/intake/runs",
        {},
        {"Idempotency-Key": key},
    )
    if code != 202:
        raise SystemExit(f"intake/runs {code}: {run!r}")
    job = (run or {}).get("job") or {}
    job_id = str(job.get("id") or "")
    status = str(job.get("status") or "")
    for attempt in range(60):
        if status in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(3)
        code_j, job_payload = client.request("GET", f"/api/v1/jobs/{job_id}")
        status = str(job_payload.get("status") if isinstance(job_payload, dict) else "")
        print(f"  poll[{attempt}] {status}", flush=True)
    code_l, latest = client.request("GET", f"/api/v1/ai/dossiers/{dossier_id}/intake/latest")
    if code_l != 200:
        raise SystemExit(f"intake/latest {code_l}: {latest!r}")
    artifact = (latest or {}).get("artifact") if isinstance(latest, dict) else None
    return job_id, status, artifact if isinstance(artifact, dict) else None


def require_succeeded_audit(client: Client, job_id: str) -> dict[str, Any]:
    code, audits = client.request("GET", "/api/v1/ai-audit?agent=intake")
    if code != 200 or not isinstance(audits, dict):
        raise SystemExit(f"ai-audit {code}: {audits!r}")
    items = audits.get("items") or audits.get("data") or []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("background_job_id") == job_id and item.get("status") == "succeeded":
            return item
    raise SystemExit(f"No hay auditoría succeeded para job={job_id}")


def main() -> int:
    base = env("ORACLE_BASE_URL", DEFAULT_BASE)
    creds_path = Path(env("ORACLE_CREDS_PATH", DEFAULT_CREDS))
    dossier_id = env("DOSSIER_ID", DEFAULT_DOSSIER)
    tenant_id = env("TENANT_ID", DEFAULT_TENANT)
    restore = env("RESTORE_DEMO_TITLE", "1") not in {"0", "false", "no"}

    email, password = parse_creds(creds_path.read_text(encoding="utf-8"))
    client = Client(base)
    client.login(email, password, tenant_id)

    print("=== CANCEL PATH ===", flush=True)
    before = snapshot(client, dossier_id)
    print("before", json.dumps(before, ensure_ascii=False), flush=True)
    job_id, status, artifact = run_intake(client, dossier_id)
    print(f"job {job_id} {status}", flush=True)
    if status != "succeeded" or not artifact:
        raise SystemExit(f"Propuesta cancel-path no succeeded: {status} art={artifact}")
    audit = require_succeeded_audit(client, job_id)
    print(
        "audit",
        json.dumps(
            {
                "id": audit.get("id"),
                "status": audit.get("status"),
                "provider": audit.get("provider"),
                "model": audit.get("model"),
                "input_tokens": audit.get("input_tokens"),
                "output_tokens": audit.get("output_tokens"),
                "cost_micros": audit.get("cost_micros"),
                "latency_ms": audit.get("latency_ms"),
            },
            default=str,
        ),
        flush=True,
    )
    after_proposal = snapshot(client, dossier_id)
    if after_proposal != before:
        raise SystemExit(
            f"La sola propuesta mutó el expediente: {before} → {after_proposal}"
        )

    code_r, rev = client.request(
        "POST",
        f"/api/v1/ai/artifacts/{artifact['id']}/reviews",
        {
            "decision": "rejected",
            "reason": "SV2-INTAKE-E2E cancel path: usuario no confirma",
        },
    )
    if code_r not in {200, 201}:
        raise SystemExit(f"reject {code_r}: {rev!r}")
    after_reject = snapshot(client, dossier_id)
    if after_reject != before:
        raise SystemExit(f"Cancel mutó negocio: {before} → {after_reject}")
    print("CANCEL_PASS", flush=True)

    print("=== HAPPY PATH ===", flush=True)
    before2 = snapshot(client, dossier_id)
    job_id, status, artifact = run_intake(client, dossier_id)
    print(f"job {job_id} {status}", flush=True)
    if status != "succeeded" or not artifact or not artifact.get("output"):
        raise SystemExit(f"Propuesta happy-path no succeeded: {status}")
    audit = require_succeeded_audit(client, job_id)
    print(
        "audit",
        json.dumps(
            {
                "id": audit.get("id"),
                "status": audit.get("status"),
                "provider": audit.get("provider"),
                "model": audit.get("model"),
                "input_tokens": audit.get("input_tokens"),
                "output_tokens": audit.get("output_tokens"),
                "cost_micros": audit.get("cost_micros"),
                "latency_ms": audit.get("latency_ms"),
            },
            default=str,
        ),
        flush=True,
    )
    out = artifact["output"]
    proposed_title = str(out.get("proposed_title") or "SV2 Intake E2E aplicado").strip()
    proposed_desc = str(out.get("proposed_description") or "")[:2000]
    print("proposed_title", proposed_title, flush=True)
    print("proposed_description", proposed_desc[:300], flush=True)

    code_p, updated = client.request(
        "PATCH",
        f"/api/v1/dossiers/{dossier_id}",
        {
            "title": proposed_title,
            "description": proposed_desc,
            "version": before2["version"],
        },
    )
    if code_p != 200 or not isinstance(updated, dict):
        raise SystemExit(f"PATCH expediente {code_p}: {updated!r}")
    code_a, accepted = client.request(
        "POST",
        f"/api/v1/ai/artifacts/{artifact['id']}/reviews",
        {
            "decision": "accepted",
            "reason": "SV2-INTAKE-E2E happy path: confirmación humana",
            "override": {
                "applied_title": proposed_title,
                "applied_description": proposed_desc,
                "proposed_dossier_type": out.get("dossier_type"),
                "type_not_applied": True,
            },
        },
    )
    if code_a not in {200, 201}:
        raise SystemExit(f"accept {code_a}: {accepted!r}")
    after_accept = snapshot(client, dossier_id)
    if after_accept["title"] != proposed_title:
        raise SystemExit(f"Título no aplicado: {after_accept['title']!r}")
    if after_accept["version"] != before2["version"] + 1:
        raise SystemExit(f"Versión inesperada: {after_accept['version']}")
    if after_accept["counts"] != before2["counts"]:
        raise SystemExit(
            f"Confirmación creó/borró entidades: {before2['counts']} → {after_accept['counts']}"
        )
    print("HAPPY_PASS", flush=True)

    if restore:
        code_rest, _ = client.request(
            "PATCH",
            f"/api/v1/dossiers/{dossier_id}",
            {
                "title": before2["title"],
                "description": before2["description"],
                "version": after_accept["version"],
            },
        )
        print(f"restore {code_rest}", flush=True)

    code_ui, _ = client.request("GET", f"/app/dossiers/{dossier_id}/intake")
    code_ui2, _ = client.request("GET", "/app/admin/ai-audit")
    print(f"ui_intake {code_ui} ui_audit {code_ui2}", flush=True)
    if code_ui != 200 or code_ui2 != 200:
        raise SystemExit("UI intake/ai-audit no respondieron 200")

    print("INTAKE_E2E_PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
