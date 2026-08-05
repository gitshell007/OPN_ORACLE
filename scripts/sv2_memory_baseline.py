#!/usr/bin/env python3
"""SV2 memory retrieval baseline runner (oracle-dev · coste 0 · Titan).

Lanza el set versionado de preguntas por el camino real de Preguntar (augment),
evalúa criterios verificables, mide latencias y, para un subconjunto, compara
contra «buscar en la carpeta» (grep sobre el corpus fuente del expediente).

  python3 scripts/sv2_memory_baseline.py
  python3 scripts/sv2_memory_baseline.py --limit 3          # smoke
  python3 scripts/sv2_memory_baseline.py --ids Q01,Q12,Q16  # subset

Environment (all optional):

  ORACLE_SSH          default root@oracle-dev.opnconsultoria.com
  ORACLE_BASE_URL     default https://oracle-dev.opnconsultoria.com
  ORACLE_CREDS_PATH   local path, else fetched via SSH from /root/sv2_demo_owner_credentials.txt
  DOSSIER_ID          default from eval set
  TENANT_ID           default from eval set
  ASK_TIMEOUT_S       default 180
  SSH_CONNECT_TIMEOUT default 15
  EVAL_SET_PATH       override path to eval_set.json
  CORPUS_PATH         override path to dossier_source_corpus.txt
  OUT_DIR             override runs output directory

No prompt/parameter tuning. Measures what is deployed. Exit 0 if the run completes
(metrics are written even when hit-rate is low — a bad number is a valid finding).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
import unicodedata
import uuid
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVAL_SET = (
    REPO_ROOT / "docs" / "evals" / "sv2_memory_baseline" / "v1" / "eval_set.json"
)
DEFAULT_CORPUS = (
    REPO_ROOT
    / "fixtures"
    / "sv2_memory_baseline"
    / "v1"
    / "dossier_source_corpus.txt"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT / "docs" / "evals" / "sv2_memory_baseline" / "v1" / "runs"
)
DEFAULT_ORACLE_SSH = "root@oracle-dev.opnconsultoria.com"
DEFAULT_BASE_URL = "https://oracle-dev.opnconsultoria.com"
DEFAULT_REMOTE_CREDS = "/root/sv2_demo_owner_credentials.txt"
DEFAULT_ASK_TIMEOUT_S = 180


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def env(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def fold(text: str) -> str:
    """Casefold + strip combining accents for tolerant matching."""
    nfkd = unicodedata.normalize("NFKD", text or "")
    no_marks = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return no_marks.casefold()


def normalize_alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", fold(text))


def percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def ssh_cat(host: str, remote_path: str, connect_timeout: int) -> str:
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        host,
        "cat",
        remote_path,
    ]
    completed = subprocess.run(
        cmd, capture_output=True, text=True, timeout=60, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"SSH cat {remote_path} falló: {(completed.stderr or '')[:400]}"
        )
    return completed.stdout


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
        raise RuntimeError("Credenciales incompletas (email/password).")
    return email, password


def load_credentials(
    *,
    local_path: str | None,
    oracle_ssh: str,
    connect_timeout: int,
) -> tuple[str, str]:
    if local_path and Path(local_path).is_file():
        return parse_creds(Path(local_path).read_text(encoding="utf-8"))
    # Prefer explicit env override, else SSH.
    env_path = os.environ.get("ORACLE_CREDS_PATH")
    if env_path and Path(env_path).is_file():
        return parse_creds(Path(env_path).read_text(encoding="utf-8"))
    return parse_creds(ssh_cat(oracle_ssh, DEFAULT_REMOTE_CREDS, connect_timeout))


# ---------------------------------------------------------------------------
# HTTP session
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
    ) -> tuple[int, Any]:
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
            self.base + path, data=body, headers=req_headers, method=method
        )
        try:
            with self.opener.open(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read()
                text = raw.decode("utf-8") if raw else ""
                if text:
                    try:
                        payload: Any = json.loads(text)
                    except json.JSONDecodeError:
                        payload = {"_text": text[:4000]}
                else:
                    payload = None
                return int(resp.status), payload
        except urllib.error.HTTPError as error:
            raw = error.read()
            text = raw.decode("utf-8", errors="replace") if raw else ""
            try:
                payload = json.loads(text) if text else {"detail": str(error)}
            except json.JSONDecodeError:
                payload = {"detail": text[:800]}
            return int(error.code), payload

    def refresh_csrf(self) -> None:
        code, payload = self.request("GET", "/api/v1/auth/csrf")
        if code != 200 or not isinstance(payload, dict) or not payload.get("csrf_token"):
            raise RuntimeError(f"CSRF falló HTTP {code}: {payload!r}")
        self.csrf = str(payload["csrf_token"])

    def login(self, email: str, password: str, tenant_id: str) -> None:
        self.refresh_csrf()
        code, payload = self.request(
            "POST",
            "/api/v1/auth/login",
            data={"email": email, "password": password, "tenant_id": tenant_id},
        )
        if code != 200:
            raise RuntimeError(f"Login falló HTTP {code}: {payload!r}")
        self.refresh_csrf()


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def text_has(haystack: str, needle: str) -> bool:
    if not needle:
        return True
    h = fold(haystack)
    n = fold(needle)
    if n in h:
        return True
    # Also try alnum-only for IDs / CIF variants (B-87994512 vs B87994512).
    hn = normalize_alnum(haystack)
    nn = normalize_alnum(needle)
    return bool(nn) and nn in hn


def group_match(answer: str, group: list[str]) -> bool:
    return all(text_has(answer, token) for token in group)


def score_fact(answer: str, criteria: dict[str, Any]) -> tuple[bool, str]:
    if not answer or not answer.strip():
        return False, "empty_answer"

    for token in criteria.get("must_contain") or []:
        if not text_has(answer, str(token)):
            # name variants
            variants = criteria.get("accept_name_variants") or []
            if variants and any(text_has(answer, str(v)) for v in variants):
                continue
            # normalized CIF-like
            norms = criteria.get("accept_normalized") or []
            if norms and any(text_has(answer, str(v)) for v in norms):
                continue
            return False, f"missing:{token}"

    any_groups = criteria.get("must_any_groups") or []
    if any_groups:
        if not any(group_match(answer, list(g)) for g in any_groups):
            return False, "must_any_groups_failed"

    return True, "ok"


def score_trap(answer: str, criteria: dict[str, Any]) -> tuple[bool, str]:
    if not answer or not answer.strip():
        return False, "empty_answer"
    lower = fold(answer)
    markers = [fold(m) for m in (criteria.get("abstention_markers") or [])]
    abstained = any(m in lower for m in markers if m)
    if abstained:
        return True, "abstained"
    return False, "no_abstention"


def score_answer(
    answer: str, kind: str, criteria: dict[str, Any]
) -> tuple[bool, str]:
    if kind == "trap" or criteria.get("trap"):
        return score_trap(answer, criteria)
    return score_fact(answer, criteria)


def folder_search(corpus: str, question: str, criteria: dict[str, Any]) -> dict[str, Any]:
    """Naive 'search the folder': find snippets containing criterion tokens.

    Not an LLM: returns whether the tokens exist in the source corpus and a
    short excerpt. Latency is pure local I/O + string search.
    """
    t0 = time.perf_counter()
    tokens: list[str] = []
    for t in criteria.get("must_contain") or []:
        tokens.append(str(t))
    for group in criteria.get("must_any_groups") or []:
        tokens.extend(str(x) for x in group)
    for v in criteria.get("accept_name_variants") or []:
        tokens.append(str(v))
    for v in criteria.get("accept_normalized") or []:
        tokens.append(str(v))
    # Dedup preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for t in tokens:
        k = fold(t)
        if k and k not in seen:
            seen.add(k)
            uniq.append(t)

    found: list[str] = []
    excerpts: list[str] = []
    folded_corpus = fold(corpus)
    for token in uniq:
        if text_has(corpus, token):
            found.append(token)
            # Locate a raw excerpt around first casefold hit.
            idx = folded_corpus.find(fold(token))
            if idx >= 0:
                start = max(0, idx - 80)
                end = min(len(corpus), idx + len(token) + 120)
                excerpts.append(corpus[start:end].replace("\n", " ").strip())

    latency_ms = (time.perf_counter() - t0) * 1000.0
    # Folder "answer": join unique excerpts or report missing.
    if found:
        answer = " · ".join(excerpts[:4]) if excerpts else f"tokens={found}"
    else:
        answer = "no_match_in_corpus"
    hit, reason = score_fact(answer if found else "", criteria) if found else (
        False,
        "no_match_in_corpus",
    )
    # Re-score against corpus itself for fairer folder accuracy (not the excerpt).
    hit_full, reason_full = score_fact(corpus, criteria)
    return {
        "method": "grep_corpus",
        "tokens_queried": uniq,
        "tokens_found": found,
        "latency_ms": round(latency_ms, 2),
        "hit": hit_full,
        "reason": reason_full,
        "excerpt": (excerpts[0] if excerpts else "")[:400],
        "answer_preview": answer[:500],
        "partial_excerpt_hit": hit,
        "partial_excerpt_reason": reason,
    }


# ---------------------------------------------------------------------------
# Ask path
# ---------------------------------------------------------------------------


@dataclass
class AskResult:
    question_id: str
    ok_job: bool
    hit: bool
    reason: str
    kind: str
    difficulty: str
    latency_ms: float | None
    citations: int
    memory_mode: str | None
    job_status: str | None
    job_id: str | None
    conversation_id: str | None
    answer_preview: str
    error: str | None = None
    folder: dict[str, Any] | None = None


def ask_one(
    session: OracleSession,
    *,
    dossier_id: str,
    question: dict[str, Any],
    ask_timeout_s: int,
) -> AskResult:
    qid = str(question["id"])
    text = str(question["question"])
    kind = str(question.get("kind") or "fact")
    difficulty = str(question.get("difficulty") or "direct")
    criteria = question.get("criteria") or {}

    t0 = time.perf_counter()
    title = f"baseline-{qid}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    code, conv = session.request(
        "POST",
        f"/api/v1/dossiers/{dossier_id}/conversations",
        data={"title": title},
    )
    if code not in (200, 201) or not isinstance(conv, dict) or not conv.get("id"):
        return AskResult(
            question_id=qid,
            ok_job=False,
            hit=False,
            reason="create_conversation_failed",
            kind=kind,
            difficulty=difficulty,
            latency_ms=None,
            citations=0,
            memory_mode=None,
            job_status=None,
            job_id=None,
            conversation_id=None,
            answer_preview="",
            error=f"HTTP {code}: {str(conv)[:300]}",
        )
    conv_id = str(conv["id"])

    code, msg = session.request(
        "POST",
        f"/api/v1/dossiers/{dossier_id}/conversations/{conv_id}/messages",
        data={"content_text": text},
        headers={"Idempotency-Key": f"sv2-baseline-{qid}-{uuid.uuid4().hex[:12]}"},
    )
    if code not in (200, 201, 202) or not isinstance(msg, dict):
        return AskResult(
            question_id=qid,
            ok_job=False,
            hit=False,
            reason="enqueue_failed",
            kind=kind,
            difficulty=difficulty,
            latency_ms=None,
            citations=0,
            memory_mode=None,
            job_status=None,
            job_id=None,
            conversation_id=conv_id,
            answer_preview="",
            error=f"HTTP {code}: {str(msg)[:300]}",
        )

    job_id = msg.get("job_id") or (msg.get("message") or {}).get("background_job_id")
    msg_id = msg.get("message_id") or (msg.get("message") or {}).get("id")
    if not job_id:
        return AskResult(
            question_id=qid,
            ok_job=False,
            hit=False,
            reason="no_job_id",
            kind=kind,
            difficulty=difficulty,
            latency_ms=None,
            citations=0,
            memory_mode=None,
            job_status=None,
            job_id=None,
            conversation_id=conv_id,
            answer_preview="",
            error=str(list(msg.keys())),
        )

    job_status = "unknown"
    deadline = time.time() + ask_timeout_s
    while time.time() < deadline:
        jcode, jbody = session.request("GET", f"/api/v1/jobs/{job_id}")
        if jcode == 200 and isinstance(jbody, dict):
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
        time.sleep(2.0)
    else:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return AskResult(
            question_id=qid,
            ok_job=False,
            hit=False,
            reason="job_timeout",
            kind=kind,
            difficulty=difficulty,
            latency_ms=round(latency_ms, 1),
            citations=0,
            memory_mode=None,
            job_status=job_status,
            job_id=str(job_id),
            conversation_id=conv_id,
            answer_preview="",
            error=f"timeout>{ask_timeout_s}s",
        )

    latency_ms = (time.perf_counter() - t0) * 1000.0
    ok_job = job_status in {"succeeded", "completed", "success"}

    memory_mode: str | None = None
    citations: list[Any] = []
    answer_text = ""

    if msg_id:
        mcode, mbody = session.request(
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
                memory_mode = (
                    str(payload["memory_mode"])
                    if payload.get("memory_mode") is not None
                    else None
                )
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

    if not answer_text:
        lcode, lbody = session.request(
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
                memory_mode = str(payload.get("memory_mode"))
            if payload.get("citations"):
                citations = payload.get("citations") or citations
            candidate = (
                payload.get("text")
                or payload.get("answer_text")
                or item.get("content_text")
            )
            if candidate and (
                item.get("role") == "assistant" or payload.get("text")
            ):
                answer_text = str(candidate)

    cite_n = len(citations) if isinstance(citations, list) else 0
    if not ok_job:
        hit, reason = False, f"job_status={job_status}"
    else:
        hit, reason = score_answer(answer_text, kind, criteria)

    return AskResult(
        question_id=qid,
        ok_job=ok_job,
        hit=hit,
        reason=reason,
        kind=kind,
        difficulty=difficulty,
        latency_ms=round(latency_ms, 1),
        citations=cite_n,
        memory_mode=memory_mode,
        job_status=job_status,
        job_id=str(job_id),
        conversation_id=conv_id,
        answer_preview=(answer_text or "")[:600].replace("\n", " "),
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class RunReport:
    schema: str = "sv2-memory-baseline-run-v1"
    started_at: str = ""
    finished_at: str = ""
    eval_set_id: str = ""
    eval_set_version: str = ""
    dossier_id: str = ""
    base_url: str = ""
    n_questions: int = 0
    n_jobs_ok: int = 0
    n_fact: int = 0
    n_fact_hit: int = 0
    n_trap: int = 0
    n_trap_abstain: int = 0
    hit_rate_fact: float | None = None
    hit_rate_overall: float | None = None
    trap_abstention_rate: float | None = None
    citations_mean: float | None = None
    citations_per_answer: list[int] = field(default_factory=list)
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    latency_mean_ms: float | None = None
    latencies_ms: list[float] = field(default_factory=list)
    folder_compare: dict[str, Any] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def summarize(results: list[AskResult], *, eval_meta: dict[str, Any], base_url: str) -> RunReport:
    report = RunReport(
        started_at=eval_meta.get("started_at", ""),
        finished_at=datetime.now(timezone.utc).isoformat(),
        eval_set_id=str(eval_meta.get("eval_set_id", "")),
        eval_set_version=str(eval_meta.get("eval_set_version", "")),
        dossier_id=str(eval_meta.get("dossier_id", "")),
        base_url=base_url,
        n_questions=len(results),
    )
    facts = [r for r in results if r.kind != "trap"]
    traps = [r for r in results if r.kind == "trap"]
    report.n_fact = len(facts)
    report.n_trap = len(traps)
    report.n_fact_hit = sum(1 for r in facts if r.hit)
    report.n_trap_abstain = sum(1 for r in traps if r.hit)
    report.n_jobs_ok = sum(1 for r in results if r.ok_job)
    if report.n_fact:
        report.hit_rate_fact = round(report.n_fact_hit / report.n_fact, 4)
    if report.n_questions:
        report.hit_rate_overall = round(
            sum(1 for r in results if r.hit) / report.n_questions, 4
        )
    if report.n_trap:
        report.trap_abstention_rate = round(report.n_trap_abstain / report.n_trap, 4)

    cites = [r.citations for r in results if r.ok_job]
    report.citations_per_answer = cites
    if cites:
        report.citations_mean = round(statistics.mean(cites), 2)

    lats = sorted(r.latency_ms for r in results if r.latency_ms is not None)
    report.latencies_ms = [float(x) for x in lats]
    if lats:
        report.latency_mean_ms = round(statistics.mean(lats), 1)
        report.latency_p50_ms = round(percentile(lats, 50) or 0.0, 1)
        report.latency_p95_ms = round(percentile(lats, 95) or 0.0, 1)

    folder_rows = [r for r in results if r.folder is not None]
    if folder_rows:
        mem_hits = sum(1 for r in folder_rows if r.hit)
        folder_hits = sum(1 for r in folder_rows if (r.folder or {}).get("hit"))
        mem_lats = [r.latency_ms for r in folder_rows if r.latency_ms is not None]
        folder_lats = [
            float((r.folder or {}).get("latency_ms") or 0.0) for r in folder_rows
        ]
        report.folder_compare = {
            "n": len(folder_rows),
            "memory_hits": mem_hits,
            "folder_hits": folder_hits,
            "memory_hit_rate": round(mem_hits / len(folder_rows), 4),
            "folder_hit_rate": round(folder_hits / len(folder_rows), 4),
            "memory_latency_mean_ms": round(statistics.mean(mem_lats), 1)
            if mem_lats
            else None,
            "folder_latency_mean_ms": round(statistics.mean(folder_lats), 1)
            if folder_lats
            else None,
            "memory_citations_mean": round(
                statistics.mean([r.citations for r in folder_rows]), 2
            ),
            "per_question": [
                {
                    "id": r.question_id,
                    "memory_hit": r.hit,
                    "memory_latency_ms": r.latency_ms,
                    "memory_citations": r.citations,
                    "memory_reason": r.reason,
                    "folder_hit": (r.folder or {}).get("hit"),
                    "folder_latency_ms": (r.folder or {}).get("latency_ms"),
                    "folder_reason": (r.folder or {}).get("reason"),
                    "folder_excerpt": (r.folder or {}).get("excerpt"),
                }
                for r in folder_rows
            ],
        }

    report.results = [asdict(r) for r in results]
    return report


def print_summary(report: RunReport) -> None:
    print("\n========== SV2 MEMORY BASELINE ==========", flush=True)
    print(f"eval_set={report.eval_set_id} v={report.eval_set_version}", flush=True)
    print(f"questions={report.n_questions} jobs_ok={report.n_jobs_ok}", flush=True)
    print(
        f"fact_hit={report.n_fact_hit}/{report.n_fact} "
        f"rate={report.hit_rate_fact}",
        flush=True,
    )
    print(
        f"trap_abstain={report.n_trap_abstain}/{report.n_trap} "
        f"rate={report.trap_abstention_rate}",
        flush=True,
    )
    print(
        f"citations_mean={report.citations_mean} "
        f"per_answer={report.citations_per_answer}",
        flush=True,
    )
    print(
        f"latency_ms p50={report.latency_p50_ms} p95={report.latency_p95_ms} "
        f"mean={report.latency_mean_ms}",
        flush=True,
    )
    if report.folder_compare:
        fc = report.folder_compare
        print(
            f"folder_compare n={fc.get('n')} "
            f"memory_hits={fc.get('memory_hits')} "
            f"folder_hits={fc.get('folder_hits')} "
            f"mem_lat_mean={fc.get('memory_latency_mean_ms')} "
            f"folder_lat_mean={fc.get('folder_latency_mean_ms')}",
            flush=True,
        )
    print("=========================================\n", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SV2 memory retrieval baseline")
    parser.add_argument("--eval-set", default=env("EVAL_SET_PATH", str(DEFAULT_EVAL_SET)))
    parser.add_argument("--corpus", default=env("CORPUS_PATH", str(DEFAULT_CORPUS)))
    parser.add_argument("--out-dir", default=env("OUT_DIR", str(DEFAULT_OUT_DIR)))
    parser.add_argument("--limit", type=int, default=0, help="Run only first N questions")
    parser.add_argument(
        "--ids",
        default="",
        help="Comma-separated question ids (e.g. Q01,Q12,Q16)",
    )
    parser.add_argument(
        "--skip-folder",
        action="store_true",
        help="Skip folder (grep corpus) comparison",
    )
    parser.add_argument(
        "--dry-score",
        action="store_true",
        help="Only score canned text / no network (dev)",
    )
    args = parser.parse_args(argv)

    eval_path = Path(args.eval_set)
    if not eval_path.is_file():
        print(f"FATAL: eval set no encontrado: {eval_path}", file=sys.stderr)
        return 2
    eval_set = json.loads(eval_path.read_text(encoding="utf-8"))
    questions: list[dict[str, Any]] = list(eval_set.get("questions") or [])
    if args.ids.strip():
        wanted = {x.strip() for x in args.ids.split(",") if x.strip()}
        questions = [q for q in questions if q.get("id") in wanted]
    if args.limit and args.limit > 0:
        questions = questions[: args.limit]
    if not questions:
        print("FATAL: sin preguntas que ejecutar", file=sys.stderr)
        return 2

    dossier = eval_set.get("dossier") or {}
    dossier_id = env("DOSSIER_ID", str(dossier.get("id") or ""))
    tenant_id = env("TENANT_ID", str(dossier.get("tenant_id") or ""))
    base_url = env("ORACLE_BASE_URL", DEFAULT_BASE_URL)
    oracle_ssh = env("ORACLE_SSH", DEFAULT_ORACLE_SSH)
    connect_timeout = env_int("SSH_CONNECT_TIMEOUT", 15)
    ask_timeout_s = env_int("ASK_TIMEOUT_S", DEFAULT_ASK_TIMEOUT_S)

    corpus_path = Path(args.corpus)
    corpus_text = ""
    if corpus_path.is_file():
        corpus_text = corpus_path.read_text(encoding="utf-8", errors="replace")
    else:
        print(f"WARN: corpus no encontrado ({corpus_path}); folder_compare limited")

    started = datetime.now(timezone.utc).isoformat()
    print(
        f"[baseline] eval={eval_set.get('id')} n={len(questions)} "
        f"dossier={dossier_id} base={base_url}",
        flush=True,
    )

    if args.dry_score:
        print("dry-score mode: no network", flush=True)
        return 0

    email, password = load_credentials(
        local_path=None,
        oracle_ssh=oracle_ssh,
        connect_timeout=connect_timeout,
    )
    session = OracleSession(base_url)
    session.login(email, password, tenant_id)
    print("[baseline] login ok", flush=True)

    results: list[AskResult] = []
    for i, q in enumerate(questions, 1):
        qid = q.get("id")
        print(f"[{i}/{len(questions)}] {qid} {q.get('difficulty')} …", flush=True)
        result = ask_one(
            session,
            dossier_id=dossier_id,
            question=q,
            ask_timeout_s=ask_timeout_s,
        )
        if (
            not args.skip_folder
            and q.get("folder_compare")
            and corpus_text
            and q.get("kind") != "trap"
        ):
            result.folder = folder_search(
                corpus_text, str(q.get("question") or ""), q.get("criteria") or {}
            )
        label = "HIT" if result.hit else "MISS"
        print(
            f"  → {label} job={result.job_status} mode={result.memory_mode} "
            f"cite={result.citations} lat_ms={result.latency_ms} "
            f"reason={result.reason}",
            flush=True,
        )
        if result.folder is not None:
            print(
                f"  → folder hit={result.folder.get('hit')} "
                f"lat_ms={result.folder.get('latency_ms')} "
                f"reason={result.folder.get('reason')}",
                flush=True,
            )
        results.append(result)

    report = summarize(
        results,
        eval_meta={
            "started_at": started,
            "eval_set_id": eval_set.get("id"),
            "eval_set_version": eval_set.get("version"),
            "dossier_id": dossier_id,
        },
        base_url=base_url,
    )
    report.notes.append(
        "Primera medición honesta: no se ajustaron prompts ni parámetros."
    )
    report.notes.append("Coste esperado 0 € (Titan local vía Signal).")
    if any(r.memory_mode and r.memory_mode != "augment" for r in results if r.ok_job):
        report.notes.append(
            "Algunas respuestas no reportaron memory_mode=augment; revisar allowlist."
        )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_json = out_dir / f"run_{stamp}.json"
    out_md = out_dir / f"run_{stamp}.md"
    out_json.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    out_md.write_text(render_markdown(report), encoding="utf-8")
    # Also write latest pointers
    (out_dir / "LATEST.json").write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "LATEST.md").write_text(render_markdown(report), encoding="utf-8")

    print_summary(report)
    print(f"[baseline] wrote {out_json}", flush=True)
    print(f"[baseline] wrote {out_md}", flush=True)
    return 0


def render_markdown(report: RunReport) -> str:
    lines = [
        f"# SV2 Memory Baseline Run · {report.finished_at}",
        "",
        f"- eval_set: `{report.eval_set_id}` v`{report.eval_set_version}`",
        f"- dossier: `{report.dossier_id}`",
        f"- base_url: `{report.base_url}`",
        f"- questions: **{report.n_questions}** · jobs_ok: **{report.n_jobs_ok}**",
        "",
        "## Métricas",
        "",
        f"| Métrica | Valor |",
        f"|---|---|",
        f"| Tasa acierto factual | {report.n_fact_hit}/{report.n_fact} = **{report.hit_rate_fact}** |",
        f"| Abstención correcta (trampas) | {report.n_trap_abstain}/{report.n_trap} = **{report.trap_abstention_rate}** |",
        f"| Tasa global (fact+trap) | **{report.hit_rate_overall}** |",
        f"| Citas media / respuesta | **{report.citations_mean}** |",
        f"| Latencia p50 / p95 (ms) | **{report.latency_p50_ms}** / **{report.latency_p95_ms}** |",
        f"| Latencia media (ms) | {report.latency_mean_ms} |",
        "",
    ]
    if report.folder_compare:
        fc = report.folder_compare
        lines += [
            "## Comparación memoria vs carpeta (grep corpus)",
            "",
            f"| | Memoria (Preguntar) | Carpeta (grep) |",
            f"|---|---|---|",
            f"| Aciertos | {fc.get('memory_hits')}/{fc.get('n')} | {fc.get('folder_hits')}/{fc.get('n')} |",
            f"| Tasa | {fc.get('memory_hit_rate')} | {fc.get('folder_hit_rate')} |",
            f"| Latencia media (ms) | {fc.get('memory_latency_mean_ms')} | {fc.get('folder_latency_mean_ms')} |",
            f"| Citas media | {fc.get('memory_citations_mean')} | n/a (grep no cita) |",
            "",
        ]
        for row in fc.get("per_question") or []:
            lines.append(
                f"- `{row['id']}`: mem={'HIT' if row['memory_hit'] else 'MISS'} "
                f"({row.get('memory_latency_ms')} ms, cite={row.get('memory_citations')}) · "
                f"folder={'HIT' if row['folder_hit'] else 'MISS'} "
                f"({row.get('folder_latency_ms')} ms)"
            )
        lines.append("")

    lines += ["## Detalle por pregunta", ""]
    for r in report.results:
        lines.append(
            f"### {r['question_id']} · {'HIT' if r['hit'] else 'MISS'} · {r['kind']}/{r['difficulty']}"
        )
        lines.append(
            f"- job={r.get('job_status')} mode={r.get('memory_mode')} "
            f"cite={r.get('citations')} lat_ms={r.get('latency_ms')} reason=`{r.get('reason')}`"
        )
        if r.get("answer_preview"):
            lines.append(f"- answer: {r['answer_preview'][:400]}")
        lines.append("")

    for note in report.notes:
        lines.append(f"> {note}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
