#!/usr/bin/env python3
"""SV2 golden-path regression harness (oracle-dev + signal-dev memory/cost).

One command → PASS or FAIL. Exit code 0 only if every check is OK.

Designed to run from an ops workstation with SSH to both hosts. Credentials are
read from the oracle-dev server file (never from the repo).

  python3 scripts/sv2_golden_path_check.py

Environment (all optional):

  ORACLE_SSH          default root@oracle-dev.opnconsultoria.com
  SIGNAL_SSH          default root@signal-dev.opnconsultoria.com
  ORACLE_BASE_URL     default https://oracle-dev.opnconsultoria.com
  ORACLE_CREDS_PATH   default /root/sv2_demo_owner_credentials.txt
  DOSSIER_ID          default Nexus demo dossier UUID
  TENANT_ID           default sv2-demo tenant UUID
  SIGNAL_TENANT_KEY   default c:64|t:<TENANT_ID>
  COST_WARN_EUR       default 1.0  (FAIL if day cost exceeds this)
  ASK_TIMEOUT_S       default 180
  SSH_CONNECT_TIMEOUT default 15

No ``except: pass``. Failures surface as FALLO lines and non-zero exit.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.cookiejar import CookieJar
from typing import Any


# ---------------------------------------------------------------------------
# Defaults (demo golden path)
# ---------------------------------------------------------------------------

DEFAULT_ORACLE_SSH = "root@oracle-dev.opnconsultoria.com"
DEFAULT_SIGNAL_SSH = "root@signal-dev.opnconsultoria.com"
DEFAULT_BASE_URL = "https://oracle-dev.opnconsultoria.com"
DEFAULT_CREDS = "/root/sv2_demo_owner_credentials.txt"
DEFAULT_DOSSIER = "ab7bba16-3e55-4f35-ad73-0c84e2850688"
DEFAULT_TENANT = "a6edb3c8-0611-4d7a-a6e1-e882c7460539"
DEFAULT_QUESTION = (
    "¿Quién es el administrador único y qué licitación pública tiene en curso "
    "Nexus Ibérica?"
)
REQUIRED_MARKERS = ("LIC-OATDA-2026-017", "2.400.000", "15 de abril")
FORBIDDEN_MARKER = "Ejemplo SL"
ORACLE_SERVICES = (
    "opn-oracle-api",
    "opn-oracle-web",
    "opn-oracle-worker",
    "opn-oracle-beat",
)
COST_WARN_EUR_DEFAULT = 1.0


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


@dataclass
class RunState:
    results: list[CheckResult] = field(default_factory=list)

    def record(self, name: str, ok: bool, detail: str) -> None:
        self.results.append(CheckResult(name=name, ok=ok, detail=detail))
        label = "OK" if ok else "FALLO"
        print(f"[{label}] {name}: {detail}", flush=True)

    @property
    def all_ok(self) -> bool:
        return bool(self.results) and all(r.ok for r in self.results)


def env(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


# ---------------------------------------------------------------------------
# SSH helpers
# ---------------------------------------------------------------------------


def ssh_run(
    host: str,
    remote_script: str,
    *,
    connect_timeout: int,
    timeout: int = 120,
) -> str:
    """Run a remote bash script over SSH. Raises RuntimeError on non-zero exit."""
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        host,
        "bash",
        "-s",
    ]
    try:
        completed = subprocess.run(
            cmd,
            input=remote_script,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"SSH a {host} agotó el timeout ({timeout}s)"
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"No se pudo lanzar SSH a {host}: {exc}") from exc

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        raise RuntimeError(
            f"SSH {host} exit={completed.returncode}: "
            f"stderr={stderr[:800]!r} stdout={stdout[:800]!r}"
        )
    return completed.stdout


def parse_kv_block(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines (one per line)."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


# ---------------------------------------------------------------------------
# HTTP session (stdlib only — no secrets printed)
# ---------------------------------------------------------------------------


class OracleSession:
    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.csrf = ""

    def request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, Any, dict[str, str]]:
        body: bytes | None = None
        req_headers = {
            "Accept": "application/json",
            "Origin": self.base,
            "Referer": f"{self.base}/app",
            **(headers or {}),
        }
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        if self.csrf and "X-CSRF-Token" not in req_headers:
            req_headers["X-CSRF-Token"] = self.csrf
        req = urllib.request.Request(
            self.base + path,
            data=body,
            headers=req_headers,
            method=method,
        )
        try:
            with self.opener.open(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read()
                text = raw.decode("utf-8") if raw else ""
                payload: Any
                if text and "application/json" in (resp.headers.get("Content-Type") or ""):
                    payload = json.loads(text)
                elif text:
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        payload = {"_text": text[:4000]}
                else:
                    payload = None
                resp_headers = {k: v for k, v in resp.headers.items()}
                return int(resp.status), payload, resp_headers
        except urllib.error.HTTPError as error:
            raw = error.read()
            text = raw.decode("utf-8", errors="replace") if raw else ""
            try:
                payload = json.loads(text) if text else {"detail": str(error)}
            except json.JSONDecodeError:
                payload = {"detail": text[:800]}
            return int(error.code), payload, dict(error.headers.items())

    def refresh_csrf(self) -> None:
        code, payload, _ = self.request("GET", "/api/v1/auth/csrf")
        if code != 200 or not isinstance(payload, dict) or not payload.get("csrf_token"):
            raise RuntimeError(f"CSRF falló HTTP {code}: {payload!r}")
        self.csrf = str(payload["csrf_token"])

    def login(self, email: str, password: str, tenant_id: str) -> None:
        self.refresh_csrf()
        code, payload, _ = self.request(
            "POST",
            "/api/v1/auth/login",
            data={"email": email, "password": password, "tenant_id": tenant_id},
        )
        if code != 200:
            # Never include password; body may contain email only.
            raise RuntimeError(f"Login falló HTTP {code}: {payload!r}")
        self.refresh_csrf()


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_services_and_release(
    state: RunState,
    oracle_ssh: str,
    connect_timeout: int,
) -> None:
    remote = r"""
set -euo pipefail
for svc in opn-oracle-api opn-oracle-web opn-oracle-worker opn-oracle-beat; do
  st=$(systemctl is-active "$svc" 2>/dev/null || echo inactive)
  echo "SVC_${svc}=${st}"
done
if [[ -L /opt/opn-oracle/current ]]; then
  echo "CURRENT=$(readlink -f /opt/opn-oracle/current)"
else
  echo "CURRENT=missing"
fi
if [[ -f /opt/opn-oracle/current/RELEASE_GIT_SHA ]]; then
  echo "RELEASE_GIT_SHA=$(cat /opt/opn-oracle/current/RELEASE_GIT_SHA)"
else
  echo "RELEASE_GIT_SHA=missing"
fi
if [[ -f /opt/opn-oracle/current/RELEASE_ID ]]; then
  echo "RELEASE_ID=$(cat /opt/opn-oracle/current/RELEASE_ID)"
else
  echo "RELEASE_ID=missing"
fi
"""
    try:
        out = ssh_run(oracle_ssh, remote, connect_timeout=connect_timeout, timeout=60)
        data = parse_kv_block(out)
    except RuntimeError as exc:
        state.record("servicios_release", False, f"no se pudo leer host: {exc}")
        return

    inactive = [
        svc
        for svc in ORACLE_SERVICES
        if data.get(f"SVC_{svc}", "inactive") != "active"
    ]
    sha = data.get("RELEASE_GIT_SHA", "missing")
    release_id = data.get("RELEASE_ID", "missing")
    current = data.get("CURRENT", "missing")

    if inactive:
        state.record(
            "servicios_release",
            False,
            f"servicios no active={inactive}; sha={sha}; release={release_id}; current={current}",
        )
        return
    if not re.fullmatch(r"[0-9a-f]{7,40}", sha or ""):
        state.record(
            "servicios_release",
            False,
            f"SHA inválido o ausente={sha!r}; release={release_id}; current={current}",
        )
        return
    if release_id in ("", "missing") or current in ("", "missing"):
        state.record(
            "servicios_release",
            False,
            f"release incompleto sha={sha} release_id={release_id} current={current}",
        )
        return

    state.record(
        "servicios_release",
        True,
        f"api/web/worker/beat=active; sha={sha}; release={release_id}; path={current}",
    )


def check_signal_memory(
    state: RunState,
    signal_ssh: str,
    tenant_key: str,
    connect_timeout: int,
) -> None:
    # Escape single quotes for remote SQL literal.
    tk = tenant_key.replace("'", "''")
    forbidden = FORBIDDEN_MARKER.replace("'", "''")
    remote = f"""
set -euo pipefail
docker exec signal_dev_postgres psql -U opn_signal_dev -d opn_signal_dev_db -v ON_ERROR_STOP=1 -At -F'|' -c "
SELECT 'counts',
  (SELECT count(*) FROM memory.memory_sources WHERE tenant_key='{tk}'),
  (SELECT count(*) FROM memory.memory_chunks WHERE tenant_key='{tk}'),
  (SELECT count(*) FROM memory.memory_facts WHERE tenant_key='{tk}'),
  (SELECT count(*) FROM memory.memory_summaries WHERE tenant_key='{tk}');
SELECT 'ejemplo',
  (SELECT count(*) FROM memory.memory_sources WHERE tenant_key='{tk}'
     AND (title ILIKE '%{forbidden}%' OR coalesce(content,'') ILIKE '%{forbidden}%'))
  + (SELECT count(*) FROM memory.memory_chunks WHERE tenant_key='{tk}'
     AND content ILIKE '%{forbidden}%')
  + (SELECT count(*) FROM memory.memory_facts WHERE tenant_key='{tk}'
     AND value_json::text ILIKE '%{forbidden}%')
  + (SELECT count(*) FROM memory.memory_summaries WHERE tenant_key='{tk}'
     AND (summary_text ILIKE '%{forbidden}%'
          OR coalesce(structured_summary_json::text,'') ILIKE '%{forbidden}%'))
  + (SELECT count(*) FROM memory.memory_observations WHERE tenant_key='{tk}'
     AND (value_json::text ILIKE '%{forbidden}%'
          OR coalesce(normalized_value_json::text,'') ILIKE '%{forbidden}%'));
"
"""
    try:
        out = ssh_run(signal_ssh, remote, connect_timeout=connect_timeout, timeout=90)
    except RuntimeError as exc:
        state.record("memoria_expediente", False, f"no se pudo consultar signal-dev: {exc}")
        return

    sources = fragments = facts = summaries = None
    ejemplo_hits = None
    for line in out.splitlines():
        parts = line.strip().split("|")
        if not parts:
            continue
        if parts[0] == "counts" and len(parts) == 5:
            sources, fragments, facts, summaries = (int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]))
        elif parts[0] == "ejemplo" and len(parts) == 2:
            ejemplo_hits = int(parts[1])

    if None in (sources, fragments, facts, summaries, ejemplo_hits):
        state.record(
            "memoria_expediente",
            False,
            f"respuesta SQL incompleta: {out!r}",
        )
        return

    detail = (
        f"tenant_key={tenant_key} fuentes={sources} fragmentos={fragments} "
        f"hechos={facts} resúmenes={summaries}; '{FORBIDDEN_MARKER}' hits={ejemplo_hits}"
    )
    ok = (
        sources is not None
        and sources > 0
        and fragments is not None
        and fragments > 0
        and facts is not None
        and facts > 0
        and summaries is not None
        and summaries > 0
        and ejemplo_hits == 0
    )
    if not ok and ejemplo_hits and ejemplo_hits > 0:
        detail += " (basura reintroducida)"
    elif not ok:
        detail += " (recuentos insuficientes)"
    state.record("memoria_expediente", ok, detail)


def check_ask(
    state: RunState,
    session: OracleSession,
    dossier_id: str,
    question: str,
    ask_timeout_s: int,
) -> None:
    title = f"sv2-check {time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    code, conv, _ = session.request(
        "POST",
        f"/api/v1/dossiers/{dossier_id}/conversations",
        data={"title": title},
    )
    if code not in (200, 201) or not isinstance(conv, dict) or not conv.get("id"):
        state.record(
            "preguntar",
            False,
            f"crear conversación HTTP {code}: {conv!r}"[:500],
        )
        return
    conv_id = str(conv["id"])

    code, msg, _ = session.request(
        "POST",
        f"/api/v1/dossiers/{dossier_id}/conversations/{conv_id}/messages",
        data={"content_text": question},
        headers={"Idempotency-Key": f"sv2-check-{uuid.uuid4().hex[:16]}"},
    )
    if code not in (200, 201, 202) or not isinstance(msg, dict):
        state.record(
            "preguntar",
            False,
            f"enqueue mensaje HTTP {code}: {msg!r}"[:500],
        )
        return

    job_id = msg.get("job_id") or (msg.get("message") or {}).get("background_job_id")
    msg_id = msg.get("message_id") or (msg.get("message") or {}).get("id")
    if not job_id:
        state.record(
            "preguntar",
            False,
            f"sin job_id en respuesta HTTP {code}: keys={list(msg.keys())}",
        )
        return

    deadline = time.time() + ask_timeout_s
    job_status = "unknown"
    job_body: dict[str, Any] = {}
    while time.time() < deadline:
        jcode, jbody, _ = session.request("GET", f"/api/v1/jobs/{job_id}")
        if jcode == 200 and isinstance(jbody, dict):
            job_body = jbody
            job_status = str(jbody.get("status") or "unknown")
            if job_status in {
                "succeeded",
                "failed",
                "cancelled",
                "permanent_failure",
                "completed",
                "success",
            }:
                break
        time.sleep(2.5)
    else:
        state.record(
            "preguntar",
            False,
            f"job timeout>{ask_timeout_s}s job_id={job_id} last_status={job_status}",
        )
        return

    if job_status not in {"succeeded", "completed", "success"}:
        extra = ""
        if msg_id:
            mcode, mbody, _ = session.request(
                "GET",
                f"/api/v1/dossiers/{dossier_id}/conversations/{conv_id}/messages/{msg_id}",
            )
            if mcode == 200 and isinstance(mbody, dict):
                extra = (
                    f" msg_status={mbody.get('status')!r} "
                    f"msg_err={mbody.get('error_message') or mbody.get('error_code')!r}"
                )
        state.record(
            "preguntar",
            False,
            f"job status={job_status} job_id={job_id} "
            f"err={job_body.get('error_message')!r} code={job_body.get('error_code')!r}{extra}",
        )
        return

    # Fetch message / conversation for answer_payload
    memory_mode = None
    citations: list[Any] = []
    answer_text = ""

    if msg_id:
        mcode, mbody, _ = session.request(
            "GET",
            f"/api/v1/dossiers/{dossier_id}/conversations/{conv_id}/messages/{msg_id}",
        )
        if mcode == 200 and isinstance(mbody, dict):
            payload = mbody.get("answer_payload") or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {"text": payload}
            if isinstance(payload, dict):
                memory_mode = payload.get("memory_mode")
                citations = (
                    payload.get("citations")
                    or payload.get("signal_citations")
                    or []
                )
                answer_text = str(
                    payload.get("text")
                    or payload.get("answer_text")
                    or mbody.get("content_text")
                    or ""
                )

    # List messages as fallback (assistant row)
    if not answer_text or memory_mode is None:
        lcode, lbody, _ = session.request(
            "GET",
            f"/api/v1/dossiers/{dossier_id}/conversations/{conv_id}/messages",
        )
        items: list[Any] = []
        if lcode == 200 and isinstance(lbody, dict):
            items = lbody.get("items") or lbody.get("messages") or []
        elif lcode == 200 and isinstance(lbody, list):
            items = lbody
        for item in items:
            if not isinstance(item, dict):
                continue
            payload = item.get("answer_payload") or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {}
            if not isinstance(payload, dict):
                continue
            if payload.get("memory_mode") is not None:
                memory_mode = payload.get("memory_mode")
            if payload.get("citations"):
                citations = payload.get("citations") or citations
            text = payload.get("text") or payload.get("answer_text") or item.get("content_text")
            if text and (item.get("role") == "assistant" or payload.get("text")):
                answer_text = str(text)

    cite_n = len(citations) if isinstance(citations, list) else 0
    missing = [m for m in REQUIRED_MARKERS if m.lower() not in answer_text.lower()]
    # Accept common numeric variants for the amount
    if "2.400.000" in missing:
        if re.search(r"2[\.\s]?400[\.\s]?000", answer_text):
            missing = [m for m in missing if m != "2.400.000"]
    # Dual-memory materializa tender.deadline como ISO (2026-04-15T14:00:00), no
    # como prosa «15 de abril». Aceptar formas equivalentes del mismo hito demo.
    if "15 de abril" in missing:
        if re.search(
            r"(15\s+de\s+abril|15[/\-.]0?4[/\-.]2026|2026[/\-.]0?4[/\-.]15|"
            r"2026-04-15|15\s+abril\s+de\s+2026)",
            answer_text,
            flags=re.IGNORECASE,
        ):
            missing = [m for m in missing if m != "15 de abril"]

    ok = (
        job_status in {"succeeded", "completed", "success"}
        and memory_mode == "augment"
        and cite_n > 0
        and not missing
    )
    detail = (
        f"job={job_status} job_id={job_id} conv={conv_id} "
        f"memory_mode={memory_mode!r} citations={cite_n} "
        f"markers_missing={missing or '[]'} title={title!r}"
    )
    if not ok and not answer_text:
        detail += " (sin texto de respuesta recuperado)"
    state.record("preguntar", ok, detail)


def check_report(
    state: RunState,
    session: OracleSession,
    dossier_id: str,
    oracle_ssh: str,
    tenant_id: str,
    connect_timeout: int,
) -> None:
    """Find at least one ready report with downloadable artifact (no new report)."""
    # Prefer API list; fall back to SQL on host for known ready IDs.
    ready_ids: list[str] = []
    code, body, _ = session.request(
        "GET",
        f"/api/v1/reports?filter[status]=ready&page[size]=20",
    )
    if code == 200 and isinstance(body, dict):
        items = body.get("items") or body.get("data") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            rid = item.get("id") or item.get("report_id")
            if not rid:
                continue
            item_dossier = str(item.get("dossier_id") or "")
            item_status = str(item.get("status") or "")
            if item_status and item_status != "ready":
                continue
            if item_dossier and item_dossier != dossier_id:
                continue
            ready_ids.append(str(rid))

    if not ready_ids:
        # Host SQL (read-only): ready custom reports for demo dossier
        remote = f"""
set -euo pipefail
DBURL=$(python3 -c '
from pathlib import Path
u=Path("/etc/opn-oracle-dev/secrets/oracle_database_url").read_text().strip()
print(u.replace("postgresql+psycopg://","postgresql://").replace("postgresql+psycopg2://","postgresql://"))
')
psql "$DBURL" -v ON_ERROR_STOP=1 -At -c "
SELECT set_config('app.tenant_id','{tenant_id}',false);
SELECT id::text FROM reports
WHERE dossier_id='{dossier_id}' AND status='ready'
ORDER BY ready_at DESC NULLS LAST
LIMIT 5;
"
"""
        try:
            out = ssh_run(oracle_ssh, remote, connect_timeout=connect_timeout, timeout=60)
            ready_ids = [line.strip() for line in out.splitlines() if line.strip()]
        except RuntimeError as exc:
            state.record("informe", False, f"no ready vía API ni SQL: {exc}")
            return

    if not ready_ids:
        state.record(
            "informe",
            False,
            f"ningún informe status=ready en expediente {dossier_id}",
        )
        return

    # Probe download for first few ready reports
    download_ok = False
    last_detail = ""
    chosen = ""
    for report_id in ready_ids[:5]:
        gcode, gbody, _ = session.request(
            "GET",
            f"/api/v1/dossiers/{dossier_id}/reports/custom/{report_id}",
        )
        downloadable = None
        status = None
        if gcode == 200 and isinstance(gbody, dict):
            downloadable = gbody.get("downloadable")
            status = gbody.get("status")
            if gbody.get("ready_artifact"):
                downloadable = downloadable or True
        dcode, dbody, dheaders = session.request(
            "GET",
            f"/api/v1/dossiers/{dossier_id}/reports/custom/{report_id}/download",
        )
        size = 0
        if dcode == 200:
            if isinstance(dbody, dict):
                size = len(json.dumps(dbody))
            elif isinstance(dbody, dict) is False and dbody is not None:
                size = len(str(dbody))
            else:
                size = int(dheaders.get("X-Content-Size") or 0) or size
            if size > 0 or dheaders.get("X-Content-SHA256"):
                download_ok = True
                chosen = report_id
                last_detail = (
                    f"report_id={report_id} status={status} downloadable={downloadable} "
                    f"download_http={dcode} bytes≈{size} sha={dheaders.get('X-Content-SHA256', '')[:16]}"
                )
                break
        last_detail = (
            f"report_id={report_id} status={status} downloadable={downloadable} "
            f"download_http={dcode} body={str(dbody)[:200]!r}"
        )

    if download_ok:
        state.record(
            "informe",
            True,
            f"ready≥1 (n={len(ready_ids)}); artefacto descargable: {last_detail}",
        )
    else:
        # content-in-DB fallback: status ready with non-empty content counts as artifact
        remote = f"""
set -euo pipefail
DBURL=$(python3 -c '
from pathlib import Path
u=Path("/etc/opn-oracle-dev/secrets/oracle_database_url").read_text().strip()
print(u.replace("postgresql+psycopg://","postgresql://").replace("postgresql+psycopg2://","postgresql://"))
')
psql "$DBURL" -v ON_ERROR_STOP=1 -At -F'|' -c "
SELECT set_config('app.tenant_id','{tenant_id}',false);
SELECT id::text, length(content::text),
  coalesce((options->'ready_artifact'->>'status'),''),
  coalesce((options->'ready_artifact'->>'byte_size'),'0')
FROM reports
WHERE dossier_id='{dossier_id}' AND status='ready'
ORDER BY ready_at DESC NULLS LAST
LIMIT 3;
"
"""
        try:
            out = ssh_run(oracle_ssh, remote, connect_timeout=connect_timeout, timeout=60)
            for line in out.splitlines():
                parts = line.strip().split("|")
                if len(parts) >= 4:
                    rid, clen, art_st, art_bytes = parts[0], int(parts[1] or 0), parts[2], int(parts[3] or 0)
                    if clen > 100 or (art_st == "available" and art_bytes > 0):
                        state.record(
                            "informe",
                            True,
                            f"ready report_id={rid} content_len={clen} "
                            f"ready_artifact.status={art_st} byte_size={art_bytes} "
                            f"(download API: {last_detail})",
                        )
                        return
        except RuntimeError as exc:
            state.record(
                "informe",
                False,
                f"ready ids={ready_ids[:3]} pero sin artefacto descargable; SQL err={exc}; last={last_detail}",
            )
            return
        state.record(
            "informe",
            False,
            f"ready ids={ready_ids[:3]} pero sin artefacto descargable; last={last_detail}",
        )


def check_cost(
    state: RunState,
    signal_ssh: str,
    cost_warn_eur: float,
    connect_timeout: int,
) -> None:
    remote = r"""
set -euo pipefail
docker exec signal_dev_postgres psql -U opn_signal_dev -d opn_signal_dev_db -v ON_ERROR_STOP=1 -At -F'|' -c "
SELECT 'today',
  (now() AT TIME ZONE 'Europe/Madrid')::date::text,
  coalesce(sum(estimated_cost_usd),0)::text
FROM ai_usage_logs
WHERE (created_at AT TIME ZONE 'Europe/Madrid')::date
    = (now() AT TIME ZONE 'Europe/Madrid')::date;
SELECT 'last24h', coalesce(sum(estimated_cost_usd),0)::text
FROM ai_usage_logs
WHERE created_at >= now() - interval '24 hours';
"
"""
    try:
        out = ssh_run(signal_ssh, remote, connect_timeout=connect_timeout, timeout=60)
    except RuntimeError as exc:
        state.record("coste", False, f"no se pudo consultar ai_usage_logs: {exc}")
        return

    day = "?"
    cost_today = None
    cost_24h = None
    for line in out.splitlines():
        parts = line.strip().split("|")
        if parts and parts[0] == "today" and len(parts) >= 3:
            day = parts[1]
            cost_today = float(parts[2])
        elif parts and parts[0] == "last24h" and len(parts) >= 2:
            cost_24h = float(parts[1])

    if cost_today is None:
        state.record("coste", False, f"parse fallido: {out!r}")
        return

    # Primary gate: calendar day Europe/Madrid. Also surface 24h for ops context.
    over = cost_today > cost_warn_eur
    detail = (
        f"día_madrid={day} estimated_cost_usd_hoy={cost_today:.6f} "
        f"last_24h={cost_24h if cost_24h is not None else 'n/a'} "
        f"umbral={cost_warn_eur:.2f}€"
    )
    if over:
        detail += " (supera umbral — posible proveedor de pago)"
    state.record("coste", not over, detail)


def check_health_jobs(
    state: RunState,
    oracle_ssh: str,
    signal_ssh: str,
    tenant_id: str,
    connect_timeout: int,
) -> None:
    oracle_remote = f"""
set -euo pipefail
DBURL=$(python3 -c '
from pathlib import Path
u=Path("/etc/opn-oracle-dev/secrets/oracle_database_url").read_text().strip()
print(u.replace("postgresql+psycopg://","postgresql://").replace("postgresql+psycopg2://","postgresql://"))
')
psql "$DBURL" -v ON_ERROR_STOP=1 -At -c "
SELECT set_config('app.tenant_id','{tenant_id}',false);
SELECT count(*) FROM background_jobs
WHERE status IN ('running','queued','pending','claimed','retry','started','received')
  AND coalesce(started_at, created_at) < now() - interval '15 minutes';
"
"""
    signal_remote = r"""
set -euo pipefail
docker exec signal_dev_postgres psql -U opn_signal_dev -d opn_signal_dev_db -v ON_ERROR_STOP=1 -At -c "
SELECT count(*) FROM memory.memory_jobs
WHERE status NOT IN ('completed','failed','cancelled','succeeded')
  AND coalesce(started_at, created_at) < now() - interval '15 minutes';
"
"""
    try:
        o_out = ssh_run(oracle_ssh, oracle_remote, connect_timeout=connect_timeout, timeout=60)
        oracle_stuck = int(o_out.strip().splitlines()[-1])
    except (RuntimeError, ValueError) as exc:
        state.record("salud_jobs", False, f"oracle stuck query falló: {exc}")
        return
    try:
        s_out = ssh_run(signal_ssh, signal_remote, connect_timeout=connect_timeout, timeout=60)
        signal_stuck = int(s_out.strip().splitlines()[-1])
    except (RuntimeError, ValueError) as exc:
        state.record("salud_jobs", False, f"signal stuck query falló: {exc}")
        return

    total = oracle_stuck + signal_stuck
    ok = total == 0
    state.record(
        "salud_jobs",
        ok,
        f"oracle_stuck>15m={oracle_stuck} signal_memory_stuck>15m={signal_stuck} total={total}",
    )


def load_creds_from_oracle(oracle_ssh: str, creds_path: str, connect_timeout: int) -> dict[str, str]:
    remote = f"""
set -euo pipefail
if [[ ! -f {shlex.quote(creds_path)} ]]; then
  echo "MISSING_CREDS" >&2
  exit 3
fi
# Print only key=value lines; never echo to syslog beyond this SSH channel.
cat {shlex.quote(creds_path)}
"""
    out = ssh_run(oracle_ssh, remote, connect_timeout=connect_timeout, timeout=30)
    creds = parse_kv_block(out)
    if not creds.get("password") and not any("pass" in k.lower() for k in creds):
        raise RuntimeError(f"Credenciales sin password en {creds_path}")
    if not creds.get("password"):
        for key, value in creds.items():
            if "pass" in key.lower():
                creds["password"] = value
                break
    return creds


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    oracle_ssh = env("ORACLE_SSH", DEFAULT_ORACLE_SSH)
    signal_ssh = env("SIGNAL_SSH", DEFAULT_SIGNAL_SSH)
    base_url = env("ORACLE_BASE_URL", DEFAULT_BASE_URL)
    creds_path = env("ORACLE_CREDS_PATH", DEFAULT_CREDS)
    dossier_id = env("DOSSIER_ID", DEFAULT_DOSSIER)
    tenant_id = env("TENANT_ID", DEFAULT_TENANT)
    tenant_key = env("SIGNAL_TENANT_KEY", f"c:64|t:{tenant_id}")
    cost_warn = env_float("COST_WARN_EUR", COST_WARN_EUR_DEFAULT)
    ask_timeout = env_int("ASK_TIMEOUT_S", 180)
    connect_timeout = env_int("SSH_CONNECT_TIMEOUT", 15)
    question = env("ASK_QUESTION", DEFAULT_QUESTION)

    # Safety: refuse obvious production hosts unless explicitly forced.
    if "oracle.opnconsultoria.com" in base_url and "oracle-dev" not in base_url:
        if os.environ.get("SV2_ALLOW_PRODUCTION") != "1":
            print(
                "REFUSE: ORACLE_BASE_URL parece producción. "
                "Use oracle-dev o SV2_ALLOW_PRODUCTION=1.",
                file=sys.stderr,
            )
            return 2

    print("=== SV2 golden path check ===", flush=True)
    print(f"oracle_ssh={oracle_ssh}", flush=True)
    print(f"signal_ssh={signal_ssh}", flush=True)
    print(f"base_url={base_url}", flush=True)
    print(f"dossier_id={dossier_id}", flush=True)
    print(f"tenant_key={tenant_key}", flush=True)
    print(f"started_at={time.strftime('%Y-%m-%dT%H:%M:%S%z')}", flush=True)
    print("---", flush=True)

    state = RunState()

    # 1) Services + release
    check_services_and_release(state, oracle_ssh, connect_timeout)

    # 2) Memory on signal-dev
    check_signal_memory(state, signal_ssh, tenant_key, connect_timeout)

    # Auth for API checks (3, 4)
    try:
        creds = load_creds_from_oracle(oracle_ssh, creds_path, connect_timeout)
        email = creds.get("email") or "owner.sv2.demo@oracle.invalid"
        password = creds["password"]
        tenant = creds.get("tenant_id") or tenant_id
        session = OracleSession(base_url, timeout=90.0)
        session.login(email, password, tenant)
        print("[OK] auth: sesión owner demo (password no impresa)", flush=True)
    except Exception as exc:
        state.record("auth", False, f"login/credenciales: {exc}")
        session = None  # type: ignore[assignment]

    # 3) Ask
    if session is not None:
        check_ask(state, session, dossier_id, question, ask_timeout)
    else:
        state.record("preguntar", False, "omitido: sin sesión")

    # 4) Report (existing ready — no new generation)
    if session is not None:
        check_report(
            state, session, dossier_id, oracle_ssh, tenant_id, connect_timeout
        )
    else:
        state.record("informe", False, "omitido: sin sesión")

    # 5) Cost
    check_cost(state, signal_ssh, cost_warn, connect_timeout)

    # 6) Hung jobs
    check_health_jobs(state, oracle_ssh, signal_ssh, tenant_id, connect_timeout)

    print("---", flush=True)
    ok_n = sum(1 for r in state.results if r.ok)
    fail_n = sum(1 for r in state.results if not r.ok)
    if state.all_ok:
        print(f"VEREDICTO=PASS checks_ok={ok_n} checks_fail={fail_n}", flush=True)
        return 0
    print(f"VEREDICTO=FAIL checks_ok={ok_n} checks_fail={fail_n}", flush=True)
    for r in state.results:
        if not r.ok:
            print(f"  - FAIL {r.name}: {r.detail}", flush=True)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("INTERRUPTED", file=sys.stderr)
        raise SystemExit(130)
