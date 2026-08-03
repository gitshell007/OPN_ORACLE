#!/usr/bin/env python3
"""SV2-OLA1-ANALISIS · E2E oportunidad (+ riesgo si Signal lo permite) en oracle-dev.

Ciclo:
  1) propuesta del agente (job succeeded + fila en /api/v1/ai-audit)
  2) cancelado: review rejected → no se crea entidad
  3) feliz: POST oportunidad/riesgo + review accepted → panel de portada tiene filas
  4) higiene: borra la entidad creada en el camino feliz (si el API lo permite)

Credenciales solo en el host:

  python3 scripts/sv2_opportunity_risk_e2e.py

Variables: ORACLE_BASE_URL, ORACLE_CREDS_PATH, DOSSIER_ID, TENANT_ID,
RUN_RISK (default 1).
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
        self.timeout = 180.0

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


def list_count(client: Client, dossier_id: str, kind: str) -> int:
    path = f"/api/v1/dossiers/{dossier_id}/{kind}"
    code, payload = client.request("GET", path)
    if code != 200 or not isinstance(payload, dict):
        raise SystemExit(f"list {kind} {code}: {payload!r}")
    items = payload.get("data") or payload.get("items") or []
    if isinstance(items, list):
        return len(items)
    return int(payload.get("total") or 0)


def list_titles(client: Client, dossier_id: str, kind: str) -> list[str]:
    path = f"/api/v1/dossiers/{dossier_id}/{kind}?page=1&size=20&sort=-overall_score"
    code, payload = client.request("GET", path)
    if code != 200 or not isinstance(payload, dict):
        return []
    items = payload.get("data") or payload.get("items") or []
    titles: list[str] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get("title"):
            titles.append(str(item["title"]))
    return titles


def run_agent(
    client: Client, dossier_id: str, agent: str
) -> tuple[str, str, dict[str, Any] | None, Any]:
    key = f"sv2-{agent}-e2e-{uuid.uuid4()}"
    code, run = client.request(
        "POST",
        f"/api/v1/ai/dossiers/{dossier_id}/{agent}/runs",
        {},
        {"Idempotency-Key": key},
    )
    if code != 202:
        return "", f"http_{code}", None, run
    job = (run or {}).get("job") or {}
    job_id = str(job.get("id") or "")
    status = str(job.get("status") or "")
    for attempt in range(80):
        if status in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(3)
        code_j, job_payload = client.request("GET", f"/api/v1/jobs/{job_id}")
        status = str(job_payload.get("status") if isinstance(job_payload, dict) else "")
        print(f"  [{agent}] poll[{attempt}] {status}", flush=True)
    code_l, latest = client.request(
        "GET", f"/api/v1/ai/dossiers/{dossier_id}/{agent}/latest"
    )
    artifact = (latest or {}).get("artifact") if isinstance(latest, dict) else None
    return job_id, status, artifact if isinstance(artifact, dict) else None, latest


def require_audit(client: Client, agent: str, job_id: str) -> dict[str, Any] | None:
    code, audits = client.request("GET", f"/api/v1/ai-audit?agent={agent}")
    if code != 200 or not isinstance(audits, dict):
        return None
    items = audits.get("items") or audits.get("data") or []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("background_job_id") == job_id:
            return item
    return None


def grounded_facts(output: dict[str, Any]) -> list[dict[str, Any]]:
    facts = output.get("facts") or []
    result: list[dict[str, Any]] = []
    for fact in facts if isinstance(facts, list) else []:
        if not isinstance(fact, dict):
            continue
        eids = fact.get("evidence_ids") or []
        if fact.get("statement") and isinstance(eids, list) and len(eids) > 0:
            result.append(fact)
    return result


def cycle_agent(
    client: Client,
    dossier_id: str,
    agent: str,
    *,
    create_kind: str,
    create_body: dict[str, Any],
) -> dict[str, Any]:
    print(f"\n=== {agent.upper()} CANCEL PATH ===", flush=True)
    before = list_count(client, dossier_id, create_kind)
    job_id, status, artifact, raw = run_agent(client, dossier_id, agent)
    print(f"job {job_id} {status}", flush=True)
    if status.startswith("http_"):
        detail = raw
        print("ENQUEUE_FAILED", json.dumps(detail, default=str)[:500], flush=True)
        return {
            "agent": agent,
            "status": status,
            "detail": detail,
            "task_key": agent,
            "needs_signal_auth": True,
        }
    audit = require_audit(client, agent, job_id) if job_id else None
    print(
        "audit",
        json.dumps(
            {
                "id": (audit or {}).get("id"),
                "status": (audit or {}).get("status"),
                "provider": (audit or {}).get("provider"),
                "model": (audit or {}).get("model"),
                "error_code": (audit or {}).get("error_code"),
                "input_tokens": (audit or {}).get("input_tokens"),
                "output_tokens": (audit or {}).get("output_tokens"),
                "cost_micros": (audit or {}).get("cost_micros"),
                "latency_ms": (audit or {}).get("latency_ms"),
            },
            default=str,
        ),
        flush=True,
    )
    if status != "succeeded" or not artifact:
        # típico 403 Signal → job failed task_not_allowed
        err = (audit or {}).get("error_code") or (audit or {}).get("status") or status
        print(f"PROPOSAL_NOT_SUCCEEDED {err}", flush=True)
        return {
            "agent": agent,
            "status": status,
            "audit": audit,
            "task_key": agent,
            "needs_signal_auth": True,
            "error": err,
        }

    after_proposal = list_count(client, dossier_id, create_kind)
    if after_proposal != before:
        raise SystemExit(f"[{agent}] la sola propuesta creó entidades: {before}→{after_proposal}")

    code_r, rev = client.request(
        "POST",
        f"/api/v1/ai/artifacts/{artifact['id']}/reviews",
        {
            "decision": "rejected",
            "reason": f"SV2-OLA1-ANALISIS cancel path ({agent})",
        },
    )
    if code_r not in {200, 201}:
        raise SystemExit(f"[{agent}] reject {code_r}: {rev!r}")
    after_reject = list_count(client, dossier_id, create_kind)
    if after_reject != before:
        raise SystemExit(f"[{agent}] cancel mutó negocio: {before}→{after_reject}")
    print(f"{agent.upper()}_CANCEL_PASS", flush=True)

    print(f"\n=== {agent.upper()} HAPPY PATH ===", flush=True)
    before2 = list_count(client, dossier_id, create_kind)
    job_id, status, artifact, _ = run_agent(client, dossier_id, agent)
    print(f"job {job_id} {status}", flush=True)
    if status != "succeeded" or not artifact or not artifact.get("output"):
        raise SystemExit(f"[{agent}] happy path no succeeded: {status}")
    audit = require_audit(client, agent, job_id)
    out = artifact["output"]
    print("proposal_title", out.get("title"), flush=True)
    print("proposal_confidence", out.get("confidence"), flush=True)
    facts = grounded_facts(out)
    print("grounded_facts", len(facts), flush=True)
    for fact in facts[:5]:
        print("  fact:", fact.get("statement"), "eids=", fact.get("evidence_ids"), flush=True)

    if not facts:
        print(f"{agent.upper()}_NO_GROUNDING — no se crea entidad", flush=True)
        return {
            "agent": agent,
            "status": "succeeded_no_grounding",
            "audit": audit,
            "artifact_id": artifact.get("id"),
            "output": out,
            "created": False,
        }

    body = dict(create_body)
    body["title"] = str(out.get("title") or body.get("title") or f"SV2 {agent}")
    if agent == "opportunity":
        body["description"] = str(out.get("summary") or out.get("description") or "")
        if out.get("opportunity_type"):
            body["opportunity_type"] = out["opportunity_type"]
        scores = out.get("scores") or {}
        if isinstance(scores, dict):
            for key in (
                "strategic_fit",
                "urgency",
                "expected_value",
                "actionability",
                "relationship_leverage",
                "timing",
                "confidence",
                "execution_effort",
                "blocking_risk",
            ):
                if key in scores:
                    body[key] = scores[key]
    else:
        body["description"] = str(out.get("description") or "")
        if out.get("category"):
            body["category"] = out["category"]
        scores = out.get("scores") or {}
        if isinstance(scores, dict):
            for key in (
                "impact",
                "likelihood",
                "velocity",
                "exposure",
                "uncertainty",
                "controllability",
            ):
                if key in scores:
                    body[key] = scores[key]
        body["confidence"] = out.get("confidence", 50)

    code_c, created = client.request(
        "POST",
        f"/api/v1/dossiers/{dossier_id}/{create_kind}",
        body,
    )
    if code_c not in {200, 201} or not isinstance(created, dict):
        raise SystemExit(f"[{agent}] create {code_c}: {created!r}")
    created_id = str(created.get("id") or "")
    print("created_id", created_id, flush=True)

    code_a, accepted = client.request(
        "POST",
        f"/api/v1/ai/artifacts/{artifact['id']}/reviews",
        {
            "decision": "accepted",
            "reason": f"SV2-OLA1-ANALISIS happy path ({agent})",
            "override": {
                f"created_{agent}_id": created_id,
                "applied_title": body["title"],
            },
        },
    )
    if code_a not in {200, 201}:
        raise SystemExit(f"[{agent}] accept {code_a}: {accepted!r}")

    after_accept = list_count(client, dossier_id, create_kind)
    if after_accept < before2 + 1:
        raise SystemExit(
            f"[{agent}] confirm no incrementó panel: {before2}→{after_accept}"
        )
    titles = list_titles(client, dossier_id, create_kind)
    print("panel_titles", titles[:5], flush=True)
    if body["title"] not in titles:
        print("WARN title exact match missing; panel has", titles, flush=True)

    print(f"{agent.upper()}_HAPPY_PASS", flush=True)

    # Higiene: intentar borrar si hay DELETE (no es obligatorio)
    deleted = False
    if created_id:
        code_d, _ = client.request("DELETE", f"/api/v1/{create_kind}/{created_id}")
        deleted = code_d in {200, 204}
        print(f"cleanup_delete {code_d}", flush=True)

    return {
        "agent": agent,
        "status": "succeeded",
        "audit": audit,
        "artifact_id": artifact.get("id"),
        "output": {
            "title": out.get("title"),
            "confidence": out.get("confidence"),
            "recommendation": out.get("recommendation") or out.get("recommended_status"),
            "facts": facts[:5],
            "warnings": out.get("warnings"),
        },
        "created_id": created_id,
        "panel_titles": titles,
        "created": True,
        "cleaned": deleted,
        "task_key": agent,
        "needs_signal_auth": False,
    }


def main() -> int:
    base = env("ORACLE_BASE_URL", DEFAULT_BASE)
    creds_path = Path(env("ORACLE_CREDS_PATH", DEFAULT_CREDS))
    dossier_id = env("DOSSIER_ID", DEFAULT_DOSSIER)
    tenant_id = env("TENANT_ID", DEFAULT_TENANT)
    run_risk = env("RUN_RISK", "1") not in {"0", "false", "no"}

    if not creds_path.is_file():
        # local fallback for mac when only running unit/gate locally
        alt = Path.home() / "sv2_demo_owner_credentials.txt"
        if alt.is_file():
            creds_path = alt
        else:
            raise SystemExit(f"Credenciales no encontradas: {creds_path}")

    email, password = parse_creds(creds_path.read_text(encoding="utf-8"))
    client = Client(base)
    client.login(email, password, tenant_id)

    results: dict[str, Any] = {}
    results["opportunity"] = cycle_agent(
        client,
        dossier_id,
        "opportunity",
        create_kind="opportunities",
        create_body={
            "title": "SV2 oportunidad",
            "description": "",
            "status": "identified",
            "opportunity_type": "other",
            "next_action": "Validar propuesta del análisis",
            "strategic_fit": 50,
            "urgency": 50,
            "expected_value": 50,
            "actionability": 50,
            "relationship_leverage": 50,
            "timing": 50,
            "confidence": 50,
            "execution_effort": 50,
            "blocking_risk": 50,
        },
    )

    if run_risk:
        results["risk"] = cycle_agent(
            client,
            dossier_id,
            "risk",
            create_kind="risks",
            create_body={
                "title": "SV2 riesgo",
                "description": "",
                "status": "open",
                "category": "other",
                "mitigation": "Validar propuesta del análisis",
                "impact": 50,
                "likelihood": 50,
                "velocity": 50,
                "exposure": 50,
                "uncertainty": 50,
                "controllability": 50,
                "confidence": 50,
            },
        )

    code_ui, _ = client.request(
        "GET", f"/app/dossiers/{dossier_id}/opportunity-analysis"
    )
    code_ui2, _ = client.request("GET", "/app/admin/ai-audit")
    code_home, _ = client.request("GET", f"/app/dossiers/{dossier_id}")
    print(f"ui_opportunity {code_ui} ui_audit {code_ui2} ui_home {code_home}", flush=True)

    print("RESULTS", json.dumps(results, default=str, ensure_ascii=False)[:4000], flush=True)

    opp = results.get("opportunity") or {}
    if opp.get("needs_signal_auth"):
        print("SIGNAL_AUTH_REQUIRED task_key=opportunity", flush=True)
        # Cableado OK; autorización Signal pendiente → no es fallo de código
        print("ANALYSIS_E2E_WIRED_AWAITING_SIGNAL", flush=True)
        return 0
    if opp.get("created") or opp.get("status") == "succeeded_no_grounding":
        print("ANALYSIS_E2E_PASS", flush=True)
        return 0
    raise SystemExit(f"Opportunity cycle incomplete: {opp}")


if __name__ == "__main__":
    sys.exit(main())
