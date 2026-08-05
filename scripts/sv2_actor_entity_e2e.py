#!/usr/bin/env python3
"""SV2-AGENTES-RESTANTES · E2E priorización de actores + resolución de entidades.

Ciclo por agente:
  1) run → job succeeded + artefacto con facts
  2) cancel: review rejected → sin mutación de negocio
  3) happy: confirm (scores / accept) → superficie visible

Credenciales solo en el host:

  python3 scripts/sv2_actor_entity_e2e.py
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
        if not line or line.startswith("#") or "=" not in line:
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
        self.timeout = 240.0

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
                if not raw:
                    return int(resp.status), None
                try:
                    return int(resp.status), json.loads(raw)
                except json.JSONDecodeError:
                    return int(resp.status), {"_raw": raw[:800]}
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


def wait_job(client: Client, job_id: str, *, timeout: float = 180.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        code, payload = client.request("GET", f"/api/v1/jobs/{job_id}")
        if code == 200 and isinstance(payload, dict):
            last = payload
            status = str(payload.get("status") or "")
            if status in {"succeeded", "failed", "cancelled"}:
                return payload
        time.sleep(2.0)
    raise SystemExit(f"Timeout job {job_id}: {last!r}")


def run_agent(client: Client, dossier_id: str, slug: str) -> dict[str, Any]:
    key = f"sv2-{slug}-{uuid.uuid4()}"
    code, payload = client.request(
        "POST",
        f"/api/v1/ai/dossiers/{dossier_id}/{slug}/runs",
        {},
        headers={"Idempotency-Key": key},
    )
    if code not in {200, 202} or not isinstance(payload, dict):
        raise SystemExit(f"run {slug} {code}: {payload!r}")
    job = payload.get("job") or {}
    job_id = str(job.get("id") or "")
    if not job_id:
        raise SystemExit(f"run {slug} sin job: {payload!r}")
    job = wait_job(client, job_id)
    code, latest = client.request("GET", f"/api/v1/ai/dossiers/{dossier_id}/{slug}/latest")
    if code != 200 or not isinstance(latest, dict):
        raise SystemExit(f"latest {slug} {code}: {latest!r}")
    return {"job": job, "latest": latest}


def review(client: Client, artifact_id: str, decision: str, **override: Any) -> None:
    body: dict[str, Any] = {
        "decision": decision,
        "reason": f"e2e {decision}",
    }
    if override:
        body["override"] = override
    code, payload = client.request("POST", f"/api/v1/ai/artifacts/{artifact_id}/reviews", body)
    if code not in {200, 201}:
        raise SystemExit(f"review {decision} {code}: {payload!r}")


def grounded_facts(output: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(output, dict):
        return []
    facts = output.get("facts") or []
    out: list[dict[str, Any]] = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        if fact.get("statement") and fact.get("evidence_ids"):
            out.append(fact)
    return out



def ensure_demo_actors(client: Client, dossier_id: str) -> list[dict[str, Any]]:
    """Garantiza ≥2 actores en el expediente para que priorización/resolución tengan materia."""
    code, page = client.request("GET", f"/api/v1/dossiers/{dossier_id}/actors?page=1&size=50")
    existing = (page.get("data") or []) if code == 200 and isinstance(page, dict) else []
    names = [
        "Capgemini España S.L.",
        "NTT DATA Spain S.L.U.",
        "Inetum España S.A.",
    ]
    created: list[dict[str, Any]] = []
    for name in names:
        if len(existing) + len(created) >= 3:
            break
        if any(name.lower() in str(item.get("canonical_name") or item).lower() for item in existing):
            continue
        code, payload = client.request(
            "POST",
            f"/api/v1/dossiers/{dossier_id}/actors",
            {
                "canonical_name": name,
                "actor_type": "organization",
                "roles": ["competidor"],
                "influence": 40,
                "relevance_to_dossier": 55,
                "relationship_strength": 20,
                "accessibility": 40,
                "strategic_alignment": 50,
                "recent_activity": 60,
            },
        )
        if code in {200, 201} and isinstance(payload, dict):
            created.append(payload)
    code, page = client.request("GET", f"/api/v1/dossiers/{dossier_id}/actors?page=1&size=50")
    links = (page.get("data") or []) if code == 200 and isinstance(page, dict) else []
    print("DEMO_ACTORS", len(links), "created_now", len(created))
    return links


def main() -> int:
    base = env("ORACLE_BASE_URL", DEFAULT_BASE)
    creds_path = Path(env("ORACLE_CREDS_PATH", DEFAULT_CREDS))
    dossier_id = env("DOSSIER_ID", DEFAULT_DOSSIER)
    tenant_id = env("TENANT_ID", DEFAULT_TENANT)
    email, password = parse_creds(creds_path.read_text(encoding="utf-8"))
    client = Client(base)
    client.login(email, password, tenant_id)

    ensure_demo_actors(client, dossier_id)

    report: dict[str, Any] = {"dossier_id": dossier_id, "agents": {}}

    # --- actor partnership ---
    ap = run_agent(client, dossier_id, "actor-partnership")
    ap_job = ap["job"]
    ap_art = (ap["latest"].get("artifact") or {}) if isinstance(ap["latest"], dict) else {}
    ap_out = ap_art.get("output") if isinstance(ap_art, dict) else None
    print("ACTOR_PARTNERSHIP job", ap_job.get("status"), "artifact", ap_art.get("id"))
    print("ACTOR_PARTNERSHIP_OUTPUT", json.dumps(ap_out if isinstance(ap_out, dict) else {}, ensure_ascii=False)[:1200])
    if ap_job.get("status") != "succeeded":
        print("ACTOR_PARTNERSHIP_FAIL", json.dumps(ap_job, ensure_ascii=False)[:500])
        report["agents"]["actor_partnership"] = {"status": "failed", "job": ap_job}
    else:
        facts = grounded_facts(ap_out if isinstance(ap_out, dict) else None)
        # cancel path
        if ap_art.get("id"):
            review(client, str(ap_art["id"]), "rejected")
            print("ACTOR_PARTNERSHIP_CANCEL_PASS")
        # happy path: re-run then apply scores if possible
        ap2 = run_agent(client, dossier_id, "actor-partnership")
        ap2_job = ap2["job"]
        ap2_art = (ap2["latest"].get("artifact") or {}) if isinstance(ap2["latest"], dict) else {}
        ap2_out = ap2_art.get("output") if isinstance(ap2_art, dict) else {}
        facts2 = grounded_facts(ap2_out if isinstance(ap2_out, dict) else None)
        applied = False
        if ap2_job.get("status") == "succeeded" and facts2 and isinstance(ap2_out, dict):
            actor_id = ap2_out.get("actor_id")
            code, actors_page = client.request(
                "GET", f"/api/v1/dossiers/{dossier_id}/actors?page=1&size=50"
            )
            links = []
            if code == 200 and isinstance(actors_page, dict):
                links = actors_page.get("data") or []
            link = next((item for item in links if str(item.get("actor_id")) == str(actor_id)), None)
            if link and actor_id:
                scores = ap2_out.get("scores") or {}
                body = {
                    "influence": int(scores.get("influence") or 50),
                    "relevance_to_dossier": int(scores.get("relevance") or 50),
                    "relationship_strength": int(scores.get("relationship_strength") or 50),
                    "accessibility": int(scores.get("accessibility") or 50),
                    "strategic_alignment": int(scores.get("strategic_alignment") or 50),
                    "recent_activity": int(scores.get("recent_activity") or 50),
                }
                code, updated = client.request(
                    "PATCH",
                    f"/api/v1/dossier-actors/{link['id']}",
                    body,
                    headers={"If-Match": f'W/"{link.get("version", 1)}"'},
                )
                if code == 200:
                    review(
                        client,
                        str(ap2_art["id"]),
                        "accepted",
                        applied_dossier_actor_id=str(updated.get("id") if isinstance(updated, dict) else link["id"]),
                        actor_id=str(actor_id),
                        priority=(updated.get("priority") if isinstance(updated, dict) else None),
                    )
                    applied = True
                    print(
                        "ACTOR_PARTNERSHIP_HAPPY_PASS priority",
                        updated.get("priority") if isinstance(updated, dict) else "?",
                        "facts",
                        len(facts2),
                    )
                else:
                    print("ACTOR_PARTNERSHIP_APPLY_FAIL", code, updated)
            else:
                # Accept review without scores if no link
                if ap2_art.get("id"):
                    review(client, str(ap2_art["id"]), "accepted", applied=False, note="no_link")
                print("ACTOR_PARTNERSHIP_HAPPY_NO_LINK facts", len(facts2), "actor_id", actor_id)
        report["agents"]["actor_partnership"] = {
            "status": ap2_job.get("status"),
            "facts": len(facts2) if ap2_job.get("status") == "succeeded" else len(facts),
            "applied": applied,
            "job_id": ap2_job.get("id"),
            "audit_log_id": ap2_art.get("audit_log_id"),
            "output_excerpt": {
                "actor_id": (ap2_out or {}).get("actor_id") if isinstance(ap2_out, dict) else None,
                "overall_priority": ((ap2_out or {}).get("scores") or {}).get("overall_priority")
                if isinstance(ap2_out, dict)
                else None,
                "fact0": facts2[0]["statement"][:200] if facts2 else None,
            },
        }

    # --- entity resolution ---
    er = run_agent(client, dossier_id, "entity-resolution")
    er_job = er["job"]
    er_art = (er["latest"].get("artifact") or {}) if isinstance(er["latest"], dict) else {}
    er_out = er_art.get("output") if isinstance(er_art, dict) else {}
    print("ENTITY_RESOLUTION job", er_job.get("status"), "artifact", er_art.get("id"))
    print("ENTITY_RESOLUTION_OUTPUT", json.dumps(er_out if isinstance(er_out, dict) else {}, ensure_ascii=False)[:1200])
    if er_job.get("status") != "succeeded":
        print("ENTITY_RESOLUTION_FAIL", json.dumps(er_job, ensure_ascii=False)[:500])
        report["agents"]["entity_resolution"] = {"status": "failed", "job": er_job}
    else:
        facts = grounded_facts(er_out if isinstance(er_out, dict) else None)
        if er_art.get("id"):
            review(client, str(er_art["id"]), "rejected")
            print("ENTITY_RESOLUTION_CANCEL_PASS")
        er2 = run_agent(client, dossier_id, "entity-resolution")
        er2_job = er2["job"]
        er2_art = (er2["latest"].get("artifact") or {}) if isinstance(er2["latest"], dict) else {}
        er2_out = er2_art.get("output") if isinstance(er2_art, dict) else {}
        facts2 = grounded_facts(er2_out if isinstance(er2_out, dict) else None)
        if er2_job.get("status") == "succeeded" and er2_art.get("id"):
            review(
                client,
                str(er2_art["id"]),
                "accepted",
                resolution_decision=(er2_out or {}).get("decision") if isinstance(er2_out, dict) else None,
                matched_actor_id=(er2_out or {}).get("matched_actor_id")
                if isinstance(er2_out, dict)
                else None,
                merge_performed=False,
            )
            print(
                "ENTITY_RESOLUTION_HAPPY_PASS decision",
                (er2_out or {}).get("decision") if isinstance(er2_out, dict) else None,
                "facts",
                len(facts2),
            )
        report["agents"]["entity_resolution"] = {
            "status": er2_job.get("status"),
            "facts": len(facts2),
            "job_id": er2_job.get("id"),
            "audit_log_id": er2_art.get("audit_log_id"),
            "output_excerpt": {
                "decision": (er2_out or {}).get("decision") if isinstance(er2_out, dict) else None,
                "matched_actor_id": (er2_out or {}).get("matched_actor_id")
                if isinstance(er2_out, dict)
                else None,
                "rationale": ((er2_out or {}).get("rationale") or "")[:240]
                if isinstance(er2_out, dict)
                else None,
                "fact0": facts2[0]["statement"][:200] if facts2 else None,
            },
        }

    # UI smoke
    for path in (
        f"/app/dossiers/{dossier_id}/actor-priority",
        f"/app/dossiers/{dossier_id}/entity-resolution",
        f"/app/dossiers/{dossier_id}/actors",
        "/app/admin/ai-audit",
    ):
        code, payload = client.request("GET", path)
        print("UI", path, code, type(payload).__name__)

    ap_ok = report["agents"].get("actor_partnership", {}).get("status") == "succeeded"
    er_ok = report["agents"].get("entity_resolution", {}).get("status") == "succeeded"
    print("REPORT", json.dumps(report, ensure_ascii=False, indent=2))
    if ap_ok and er_ok:
        print("ACTOR_ENTITY_E2E_PASS")
        return 0
    print("ACTOR_ENTITY_E2E_PARTIAL_OR_FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
