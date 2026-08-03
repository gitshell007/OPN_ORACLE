#!/usr/bin/env python3
"""Collect host/application metrics and deliver a daily infrastructure digest.

The monitor is deliberately outside the Flask application.  It connects as a
dedicated SSH account (root during the initial rollout), reads only operational
metadata, keeps the previous capture locally, and sends through Microsoft Graph
without putting credentials in command arguments or logs.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import shlex
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover - Python 3.10 fallback is not supported
    raise SystemExit("Este monitor necesita Python 3.11 o superior.") from exc


REMOTE_COLLECTOR = r'''
import json
import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path


def run(argv, timeout=30):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout or f"exit {result.returncode}").strip()[:240]
    return result.stdout, None


def parse_meminfo():
    values = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, raw = line.split(":", 1)
            fields = raw.strip().split()
            if fields:
                values[key] = int(fields[0]) * (1024 if len(fields) > 1 and fields[1] == "kB" else 1)
    except (OSError, ValueError):
        return {}
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    swap_total = values.get("SwapTotal", 0)
    swap_free = values.get("SwapFree", 0)
    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": max(0, total - available),
        "swap_total_bytes": swap_total,
        "swap_used_bytes": max(0, swap_total - swap_free),
    }


def parse_os_release():
    values = {}
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"')
    except OSError:
        pass
    return values.get("PRETTY_NAME", platform.platform())


def parse_task_rows(raw):
    rows = []
    for line in raw.splitlines():
        fields = line.split("|")
        if len(fields) != 4:
            continue
        source, status, kind, count = fields
        try:
            rows.append({"source": source, "status": status, "kind": kind, "count": int(count)})
        except ValueError:
            continue
    return rows


def parse_db_rows(raw):
    rows = []
    for line in raw.splitlines():
        fields = line.split("|")
        if len(fields) != 2:
            continue
        try:
            rows.append({"name": fields[0], "size_bytes": int(fields[1])})
        except ValueError:
            continue
    return rows


def parse_docker_df(raw):
    rows = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("TYPE") or line.startswith("---"):
            continue
        fields = line.split()
        if len(fields) < 5 or fields[0] not in {"Images", "Containers", "Local", "Build"}:
            continue
        if fields[0] == "Local" and len(fields) >= 6 and fields[1] == "Volumes":
            row_type = "Volumes"
            total, active, size = fields[2:5]
            reclaimable = " ".join(fields[5:])
        elif fields[0] == "Build" and len(fields) >= 6 and fields[1] == "Cache":
            row_type = "Build cache"
            total, active, size = fields[2:5]
            reclaimable = " ".join(fields[5:])
        else:
            row_type = fields[0]
            total, active, size = fields[1:4]
            reclaimable = " ".join(fields[4:])
        rows.append({"type": row_type, "total": total, "active": active, "size": size, "reclaimable": reclaimable})
    return rows


def parse_human_size(raw):
    text = str(raw or "").strip().replace(",", ".")
    if not text:
        return None
    units = {"B": 1, "KB": 1000, "KIB": 1024, "MB": 1000**2, "MIB": 1024**2,
             "GB": 1000**3, "GIB": 1024**3, "TB": 1000**4, "TIB": 1024**4}
    for suffix, multiplier in sorted(units.items(), key=lambda item: len(item[0]), reverse=True):
        if text.upper().endswith(suffix):
            try:
                return int(float(text[:-len(suffix)].strip()) * multiplier)
            except ValueError:
                return None
    try:
        return int(float(text))
    except ValueError:
        return None


def docker_metrics():
    result = {"containers": [], "summary": [], "errors": []}
    raw, error = run(["docker", "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}"], timeout=30)
    if error:
        result["errors"].append(f"docker ps: {error}")
    else:
        for line in raw.splitlines():
            fields = line.split("\t", 2)
            if len(fields) == 3:
                result["containers"].append({"name": fields[0], "image": fields[1], "status": fields[2]})
    raw, error = run(["docker", "system", "df"], timeout=60)
    if error:
        result["errors"].append(f"docker system df: {error}")
    else:
        result["summary"] = parse_docker_df(raw)
    return result


def snapshot_metrics():
    paths = json.loads(os.environ.get("MONITOR_BACKUP_PATHS", "[]"))
    result = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            result.append({"path": str(path), "exists": False, "total_bytes": None, "entries": []})
            continue
        total_raw, error = run(["du", "-sb", str(path)], timeout=120)
        total = None
        if not error and total_raw:
            try:
                total = int(total_raw.split()[0])
            except (ValueError, IndexError):
                pass
        entries = []
        try:
            candidates = sorted(path.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True)[:12]
            for entry in candidates:
                entry_total, _ = run(["du", "-sb", str(entry)], timeout=60)
                size = None
                if entry_total:
                    try:
                        size = int(entry_total.split()[0])
                    except (ValueError, IndexError):
                        pass
                entries.append({"name": entry.name, "size_bytes": size, "mtime": entry.stat().st_mtime})
        except OSError:
            entries = []
        result.append({"path": str(path), "exists": True, "total_bytes": total, "entries": entries})
    return result


def parse_storage_rows(raw):
    rows = []
    for line in raw.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2:
            continue
        try:
            rows.append({"path": fields[1], "size_bytes": int(fields[0])})
        except ValueError:
            continue
    return rows


def storage_usage_metrics():
    result = {"directories": [], "files": [], "errors": []}
    directories, error = run(
        ["sh", "-c", "LC_ALL=C du -x -B1 -d 1 -- / 2>/dev/null | "
         "awk '$2 != \"/\"' | sort -nr -k1,1 | head -n 10"],
        timeout=180,
    )
    if error:
        result["errors"].append(f"top directorios: {error}")
    else:
        result["directories"] = parse_storage_rows(directories or "")
    files, error = run(
        ["sh", "-c", "LC_ALL=C find / -xdev -type f -printf '%s\\t%p\\n' 2>/dev/null | "
         "sort -nr -k1,1 | head -n 10"],
        timeout=180,
    )
    if error:
        result["errors"].append(f"top archivos: {error}")
    else:
        result["files"] = parse_storage_rows(files or "")
    return result


def psql_command(sql):
    mode = os.environ.get("MONITOR_DB_MODE", "none")
    if mode == "native":
        return ["runuser", "-u", "postgres", "--", "psql", "-X", "-A", "-t", "-F", "|", "-v", "ON_ERROR_STOP=1", "-d", os.environ.get("MONITOR_DB_NAME", "postgres"), "-c", sql]
    if mode == "docker":
        return ["docker", "exec", os.environ["MONITOR_DB_CONTAINER"], "psql", "-X", "-A", "-t", "-F", "|", "-v", "ON_ERROR_STOP=1", "-U", os.environ["MONITOR_DB_USER"], "-d", os.environ["MONITOR_DB_NAME"], "-c", sql]
    return None


def db_query(sql, timeout=60):
    command = psql_command(sql)
    if command is None:
        return None, "database mode disabled"
    return run(command, timeout=timeout)


def database_metrics():
    mode = os.environ.get("MONITOR_DB_MODE", "none")
    if mode == "none":
        return {"databases": [], "errors": []}
    databases = "select datname, pg_database_size(datname) from pg_database where datistemplate=false order by datname"
    raw, error = db_query(databases)
    result = {"databases": parse_db_rows(raw or "") if not error else [], "errors": []}
    if error:
        result["errors"].append(f"postgres: {error}")
    return result


def task_sql(mode):
    interval = int(os.environ.get("MONITOR_WINDOW_HOURS", "24"))
    if mode == "oracle":
        return f"select 'background_jobs', status, job_type, count(*) from background_jobs where created_at >= now() - interval '{interval} hours' group by status, job_type order by status, job_type"
    if mode == "signal":
        return f"select 'connector_run_logs', status, connector_kind, count(*) from connector_run_logs where run_started_at >= now() - interval '{interval} hours' group by status, connector_kind order by status, connector_kind"
    if mode == "risk":
        return " union all ".join([
            f"select 'ai_analysis_jobs', status, job_type, count(*) from ai_analysis_jobs where created_at >= now() - interval '{interval} hours' group by status, job_type",
            f"select 'connector_sync_runs', status, sync_type, count(*) from connector_sync_runs where started_at >= now() - interval '{interval} hours' group by status, sync_type",
            f"select 'ingestion_runs', status, source_category, count(*) from ingestion_runs where started_at >= now() - interval '{interval} hours' group by status, source_category",
            f"select 'playbook_runs', status, 'playbook', count(*) from playbook_runs where started_at >= now() - interval '{interval} hours' group by status",
            f"select 'regulatory_export_jobs', status, export_format, count(*) from regulatory_export_jobs where created_at >= now() - interval '{interval} hours' group by status, export_format",
        ])
    if mode == "advisor":
        return " union all ".join([
            f"select 'ai_tasks', status, task_type, count(*) from ai_tasks where created_at >= now() - interval '{interval} hours' group by status, task_type",
            f"select 'connector_sync_runs', status, sync_type, count(*) from connector_sync_runs where started_at >= now() - interval '{interval} hours' group by status, sync_type",
            f"select 'document_processing_jobs', status, job_type, count(*) from document_processing_jobs where started_at >= now() - interval '{interval} hours' group by status, job_type",
            f"select 'backup_jobs', status, 'backup', count(*) from backup_jobs where created_at >= now() - interval '{interval} hours' group by status",
            f"select 'billing_runs', status, run_type, count(*) from billing_runs where started_at >= now() - interval '{interval} hours' group by status, run_type",
        ])
    return None


def task_metrics():
    mode = os.environ.get("MONITOR_TASK_MODE", "none")
    if mode == "none":
        return {"rows": [], "errors": []}
    sql = task_sql(mode)
    if sql is None:
        return {"rows": [], "errors": [f"unknown task mode: {mode}"]}
    raw, error = db_query(sql)
    result = {"rows": parse_task_rows(raw or "") if not error else [], "errors": []}
    if error:
        result["errors"].append(f"tasks: {error}")
    return result


def parse_spend_rows(raw):
    rows = []
    for line in raw.splitlines():
        fields = line.split("|")
        if len(fields) != 10:
            continue
        consumer, model, task, project, status, count, cost, missing_cost, input_tokens, output_tokens = fields
        try:
            rows.append({
                "consumer": consumer or "—",
                "model": model or "—",
                "task": task or "—",
                "project": project or "(sin proyecto)",
                "status": status or "unknown",
                "requests": int(count),
                "cost_usd": float(cost) if cost else 0.0,
                "missing_cost_requests": int(missing_cost),
                "input_tokens": int(input_tokens),
                "output_tokens": int(output_tokens),
            })
        except ValueError:
            continue
    return rows


def openrouter_spend_metrics():
    if os.environ.get("MONITOR_OPENROUTER_SPEND", "0") != "1":
        return None
    interval = int(os.environ.get("MONITOR_WINDOW_HOURS", "24"))
    sql = f"""
        select coalesce(c.name, 'consumer-' || u.consumer_id::text),
               coalesce(u.model, '—'),
               coalesce(u.task_key, '—'),
               coalesce(u.project_name, '(sin proyecto)'),
               u.status,
               count(*),
               coalesce(sum(u.estimated_cost_usd), 0),
               count(*) filter (where u.estimated_cost_usd is null),
               coalesce(sum(u.input_tokens), 0),
               coalesce(sum(u.output_tokens), 0)
          from ai_usage_logs u
          left join consumers c on c.id = u.consumer_id
         where lower(u.provider) = 'openrouter'
           and u.created_at >= now() - interval '{interval} hours'
         group by 1, 2, 3, 4, 5
         order by 7 desc, 6 desc
         limit 100
    """
    raw, error = db_query(sql, timeout=60)
    result = {
        "provider": "openrouter",
        "window_hours": interval,
        "rows": parse_spend_rows(raw or "") if not error else [],
        "total_usd": 0.0,
        "requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "error_requests": 0,
        "missing_cost_requests": 0,
        "errors": [],
    }
    if error:
        result["errors"].append(f"OpenRouter: {error}")
        return result
    for row in result["rows"]:
        result["total_usd"] += row["cost_usd"]
        result["requests"] += row["requests"]
        result["input_tokens"] += row["input_tokens"]
        result["output_tokens"] += row["output_tokens"]
        result["missing_cost_requests"] += row["missing_cost_requests"]
        if row["status"] != "ok":
            result["error_requests"] += row["requests"]
    result["total_usd"] = round(result["total_usd"], 8)
    return result


def service_metrics():
    result = {}
    for unit in filter(None, os.environ.get("MONITOR_SERVICE_UNITS", "").split(",")):
        raw, error = run(["systemctl", "is-active", unit], timeout=10)
        result[unit] = (raw or "unknown").strip() if not error else "unknown"
    return result


def main():
    disk = shutil.disk_usage("/")
    load = os.getloadavg() if hasattr(os, "getloadavg") else (None, None, None)
    data = {
        "hostname": socket.gethostname(),
        "os": parse_os_release(),
        "kernel": platform.release(),
        "cpu_count": os.cpu_count(),
        "load_1m": load[0],
        "memory": parse_meminfo(),
        "disk": {"mount": "/", "total_bytes": disk.total, "used_bytes": disk.used, "free_bytes": disk.free},
        "storage_usage": storage_usage_metrics(),
        "services": service_metrics(),
        "database": database_metrics(),
        "tasks": task_metrics(),
        "openrouter_spend": openrouter_spend_metrics(),
        "snapshots": snapshot_metrics(),
        "docker": None,
        "errors": [],
    }
    if os.environ.get("MONITOR_DOCKER", "0") == "1":
        data["docker"] = docker_metrics()
    data["errors"].extend(data["database"].get("errors", []))
    data["errors"].extend(data["tasks"].get("errors", []))
    data["errors"].extend(data["storage_usage"].get("errors", []))
    if data["openrouter_spend"]:
        data["errors"].extend(data["openrouter_spend"].get("errors", []))
    data["errors"].extend(data["docker"].get("errors", []) if data["docker"] else [])
    print(json.dumps(data, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
'''


def parse_human_size(raw: str | None) -> int | None:
    text = str(raw or "").strip().replace(",", ".")
    if not text:
        return None
    units = {"B": 1, "KB": 1000, "KIB": 1024, "MB": 1000**2, "MIB": 1024**2,
             "GB": 1000**3, "GIB": 1024**3, "TB": 1000**4, "TIB": 1024**4}
    for suffix, multiplier in sorted(units.items(), key=lambda item: len(item[0]), reverse=True):
        if text.upper().endswith(suffix):
            try:
                return int(float(text[:-len(suffix)].strip()) * multiplier)
            except ValueError:
                return None
    try:
        return int(float(text))
    except ValueError:
        return None


def percentage_change(current: int | float | None, previous: int | float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return ((float(current) - float(previous)) / float(previous)) * 100


def format_bytes(value: int | float | None) -> str:
    if value is None:
        return "n/d"
    value = float(value)
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    index = 0
    while abs(value) >= 1000 and index < len(units) - 1:
        value /= 1000
        index += 1
    if index == 0:
        return f"{int(value)} {units[index]}"
    return f"{value:.2f} {units[index]}"


def format_count(value: int | float | None) -> str:
    return "n/d" if value is None else f"{int(value):,}".replace(",", ".")


def format_pct(value: float | None) -> str:
    if value is None:
        return "n/d"
    return f"{value:+.1f}%"


def format_usd(value: int | float | None) -> str:
    if value is None:
        return "n/d"
    amount = float(value)
    if abs(amount) < 0.01:
        return f"{amount:.6f} USD"
    return f"{amount:,.4f} USD"


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def target_env(target: dict[str, Any], window_hours: int) -> dict[str, str]:
    return {
        "MONITOR_SERVICE_UNITS": ",".join(str(item) for item in target.get("services", [])),
        "MONITOR_DB_MODE": str(target.get("db_mode", "none")),
        "MONITOR_DB_CONTAINER": str(target.get("db_container", "")),
        "MONITOR_DB_USER": str(target.get("db_user", "")),
        "MONITOR_DB_NAME": str(target.get("db_name", "postgres")),
        "MONITOR_TASK_MODE": str(target.get("task_mode", "none")),
        "MONITOR_BACKUP_PATHS": json.dumps(target.get("backup_paths", [])),
        "MONITOR_DOCKER": "1" if target.get("docker_metrics", False) else "0",
        "MONITOR_OPENROUTER_SPEND": "1" if target.get("openrouter_spend", False) else "0",
        "MONITOR_WINDOW_HOURS": str(window_hours),
    }


def collect_target(target: dict[str, Any], monitor: dict[str, Any]) -> dict[str, Any]:
    host = str(target["host"])
    key_file = str(monitor.get("ssh_key_file", ""))
    known_hosts = str(monitor.get("ssh_known_hosts_file", "/etc/ssh/ssh_known_hosts"))
    ssh_user = str(monitor.get("ssh_user", "root"))
    timeout = int(monitor.get("ssh_connect_timeout_seconds", 10))
    command_timeout = int(monitor.get("ssh_command_timeout_seconds", 180))
    remote_env = target_env(target, int(monitor.get("window_hours", 24)))
    remote_command = "env " + " ".join(f"{key}={shlex.quote(value)}" for key, value in remote_env.items()) + " python3 -"
    command = [
        "ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}",
        "-o", "ConnectionAttempts=1", "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known_hosts}",
    ]
    if key_file:
        command.extend(["-i", key_file])
    command.extend([f"{ssh_user}@{host}", remote_command])
    try:
        result = subprocess.run(
            command, input=REMOTE_COLLECTOR, text=True, capture_output=True,
            timeout=max(timeout + 30, command_timeout), check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"id": target.get("id", host), "label": target.get("label", host), "host": host,
                "status": "error", "error": str(exc), "data": {}}
    stdout = result.stdout.strip()
    if result.returncode != 0:
        error = (result.stderr or stdout or f"ssh exit {result.returncode}").strip()[:300]
        return {"id": target.get("id", host), "label": target.get("label", host), "host": host,
                "status": "error", "error": error, "data": {}}
    try:
        data = json.loads(stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        return {"id": target.get("id", host), "label": target.get("label", host), "host": host,
                "status": "error", "error": f"respuesta SSH inválida: {exc}", "data": {}}
    return {"id": target.get("id", host), "label": target.get("label", host), "host": host,
            "status": "degraded" if data.get("errors") else "ok", "error": None, "data": data}


def normalized_metrics(capture: dict[str, Any]) -> dict[str, Any]:
    data = capture.get("data", {})
    databases = data.get("database", {}).get("databases", [])
    tasks = data.get("tasks", {}).get("rows", [])
    docker = data.get("docker") or {}
    docker_sizes = {}
    for row in docker.get("summary", []):
        docker_sizes[row.get("type", "unknown")] = {
            "size_bytes": parse_human_size(row.get("size")),
            "reclaimable_bytes": parse_human_size(str(row.get("reclaimable", "")).split(" ", 1)[0]),
            "total": row.get("total"), "active": row.get("active"),
        }
    snapshot_sizes = {item.get("path"): item.get("total_bytes") for item in data.get("snapshots", [])}
    openrouter = data.get("openrouter_spend") or {}
    storage = data.get("storage_usage") or {}
    storage_directories = {
        item.get("path"): item.get("size_bytes")
        for item in storage.get("directories", [])
        if item.get("path")
    }
    storage_files = {
        item.get("path"): item.get("size_bytes")
        for item in storage.get("files", [])
        if item.get("path")
    }
    return {
        "disk_free_bytes": data.get("disk", {}).get("free_bytes"),
        "memory_available_bytes": data.get("memory", {}).get("available_bytes"),
        "database_total_bytes": sum(item.get("size_bytes", 0) or 0 for item in databases),
        "tasks_total": sum(item.get("count", 0) or 0 for item in tasks),
        "openrouter_spend_usd": openrouter.get("total_usd"),
        "storage_directories": storage_directories,
        "storage_files": storage_files,
        "docker_sizes": docker_sizes,
        "snapshot_sizes": snapshot_sizes,
    }


def add_variations(current: dict[str, Any], previous: dict[str, Any] | None) -> None:
    current_metrics = normalized_metrics(current)
    previous_metrics = normalized_metrics(previous or {})
    current["metrics"] = current_metrics
    current["variation"] = {
        key: percentage_change(value, previous_metrics.get(key))
        for key, value in current_metrics.items()
        if key in {
            "disk_free_bytes", "memory_available_bytes", "database_total_bytes", "tasks_total",
            "openrouter_spend_usd",
        }
    }
    current["variation"]["docker_sizes"] = {}
    for kind, values in current_metrics["docker_sizes"].items():
        old = previous_metrics.get("docker_sizes", {}).get(kind, {})
        current["variation"]["docker_sizes"][kind] = {
            "size_bytes": percentage_change(values.get("size_bytes"), old.get("size_bytes")),
            "reclaimable_bytes": percentage_change(values.get("reclaimable_bytes"), old.get("reclaimable_bytes")),
        }
    current["variation"]["snapshot_sizes"] = {
        path: percentage_change(value, previous_metrics.get("snapshot_sizes", {}).get(path))
        for path, value in current_metrics["snapshot_sizes"].items()
    }
    current["variation"]["storage_directories"] = {
        path: percentage_change(value, previous_metrics.get("storage_directories", {}).get(path))
        for path, value in current_metrics["storage_directories"].items()
    }
    current["variation"]["storage_files"] = {
        path: percentage_change(value, previous_metrics.get("storage_files", {}).get(path))
        for path, value in current_metrics["storage_files"].items()
    }


def task_summary(capture: dict[str, Any]) -> str:
    rows = capture.get("data", {}).get("tasks", {}).get("rows", [])
    if not rows:
        return "0"
    by_status: dict[str, int] = {}
    for row in rows:
        by_status[row.get("status", "unknown")] = by_status.get(row.get("status", "unknown"), 0) + int(row.get("count", 0) or 0)
    total = sum(by_status.values())
    details = ", ".join(f"{key}: {format_count(value)}" for key, value in sorted(by_status.items()))
    return f"{format_count(total)} ({details})"


def docker_summary(capture: dict[str, Any]) -> list[str]:
    docker = capture.get("data", {}).get("docker") or {}
    lines = []
    for row in docker.get("summary", []):
        reclaimable = row.get("reclaimable", "n/d")
        lines.append(f"{row.get('type', 'Docker')}: {row.get('size', 'n/d')} · recuperable {reclaimable}")
    return lines


def openrouter_spend(capture: dict[str, Any]) -> dict[str, Any] | None:
    spend = capture.get("data", {}).get("openrouter_spend")
    return spend if isinstance(spend, dict) else None


def openrouter_summary_line(capture: dict[str, Any]) -> str | None:
    spend = openrouter_spend(capture)
    if not spend:
        return None
    variation = capture.get("variation", {}).get("openrouter_spend_usd")
    return (
        f"Gasto OpenRouter: {format_usd(spend.get('total_usd'))} ({format_pct(variation)}) · "
        f"{format_count(spend.get('requests'))} solicitudes · "
        f"tokens: {format_count(spend.get('input_tokens'))} entrada / "
        f"{format_count(spend.get('output_tokens'))} salida"
    )


def openrouter_detail_lines(capture: dict[str, Any]) -> list[str]:
    spend = openrouter_spend(capture)
    if not spend:
        return []
    lines = [
        "  OpenRouter (coste registrado según tokens y catálogo de precios de Signal): "
        f"{format_usd(spend.get('total_usd'))} ({format_pct(capture.get('variation', {}).get('openrouter_spend_usd'))})",
        f"  OpenRouter: {format_count(spend.get('requests'))} solicitudes · "
        f"{format_count(spend.get('input_tokens'))} tokens entrada · "
        f"{format_count(spend.get('output_tokens'))} tokens salida · "
        f"errores {format_count(spend.get('error_requests'))}",
    ]
    for row in spend.get("rows", []):
        lines.append(
            "  OpenRouter detalle: "
            f"{row.get('model', '—')} · tarea {row.get('task', '—')} · "
            f"proyecto {row.get('project', '(sin proyecto)')} · "
            f"{format_count(row.get('requests'))} solicitudes · "
            f"{format_usd(row.get('cost_usd'))} · "
            f"tokens {format_count((row.get('input_tokens') or 0) + (row.get('output_tokens') or 0))} · "
            f"estado {row.get('status', 'unknown')}"
        )
    if spend.get("missing_cost_requests"):
        lines.append(
            f"  OpenRouter aviso: {format_count(spend.get('missing_cost_requests'))} solicitudes sin coste calculable."
        )
    return lines


def storage_usage(capture: dict[str, Any]) -> dict[str, Any]:
    storage = capture.get("data", {}).get("storage_usage")
    return storage if isinstance(storage, dict) else {}


def storage_detail_lines(capture: dict[str, Any]) -> list[str]:
    storage = storage_usage(capture)
    if not storage:
        return []
    variation = capture.get("variation", {})
    lines = ["  Almacenamiento · top 10 directorios por tamaño"]
    for item in storage.get("directories", []):
        path = item.get("path")
        change = variation.get("storage_directories", {}).get(path)
        lines.append(f"    {path}: {format_bytes(item.get('size_bytes'))} ({format_pct(change)})")
    lines.append("  Almacenamiento · top 10 archivos por tamaño")
    for item in storage.get("files", []):
        path = item.get("path")
        change = variation.get("storage_files", {}).get(path)
        lines.append(f"    {path}: {format_bytes(item.get('size_bytes'))} ({format_pct(change)})")
    return lines


def render_text(report: dict[str, Any]) -> str:
    lines = [
        f"Resumen diario de servidores OPN · {report['captured_at_local']}",
        "Ventana de tareas: últimas 24 horas · Variación: frente a la captura diaria anterior",
        "",
        "Servidor | Estado | Disco libre | RAM disponible | BD total | Tareas ejecutadas",
        "---------|--------|-------------|----------------|----------|------------------",
    ]
    spend_captures = [capture for capture in report["targets"] if openrouter_spend(capture)]
    if spend_captures:
        lines.extend(["", "OpenRouter · gasto IA (últimas 24 horas)"])
        for capture in spend_captures:
            lines.append(f"{capture['label']} ({capture['host']}) · {openrouter_summary_line(capture)}")
        lines.append("Coste registrado por Signal a partir de tokens y catálogo de precios de OpenRouter; no es una descarga de factura.")
    for capture in report["targets"]:
        metrics = capture.get("metrics", {})
        variation = capture.get("variation", {})
        state = capture.get("status", "error")
        if state == "error":
            lines.append(f"{capture['label']} ({capture['host']}) | ERROR | {capture.get('error', 'sin detalle')}")
            continue
        lines.append(
            f"{capture['label']} ({capture['host']}) | {state} | "
            f"{format_bytes(metrics.get('disk_free_bytes'))} ({format_pct(variation.get('disk_free_bytes'))}) | "
            f"{format_bytes(metrics.get('memory_available_bytes'))} ({format_pct(variation.get('memory_available_bytes'))}) | "
            f"{format_bytes(metrics.get('database_total_bytes'))} ({format_pct(variation.get('database_total_bytes'))}) | "
            f"{task_summary(capture)} ({format_pct(variation.get('tasks_total'))})"
        )
    lines.extend(["", "Detalles operativos"])
    for capture in report["targets"]:
        if capture.get("status") == "error":
            continue
        data = capture.get("data", {})
        lines.append(f"\n{capture['label']} · {capture['host']}")
        lines.append(f"  OS: {data.get('os', 'n/d')} · CPU: {data.get('cpu_count', 'n/d')} · carga 1m: {data.get('load_1m', 'n/d')}")
        services = data.get("services", {})
        if services:
            lines.append("  Servicios: " + ", ".join(f"{name}={status}" for name, status in services.items()))
        databases = data.get("database", {}).get("databases", [])
        if databases:
            lines.append("  Bases: " + ", ".join(f"{item['name']}={format_bytes(item['size_bytes'])}" for item in databases))
        if data.get("tasks", {}).get("rows"):
            lines.append("  Tareas: " + "; ".join(f"{row['source']}/{row['status']}/{row['kind']}={format_count(row['count'])}" for row in data["tasks"]["rows"]))
        lines.extend(openrouter_detail_lines(capture))
        lines.extend(storage_detail_lines(capture))
        if data.get("docker"):
            lines.append("  Docker: " + "; ".join(docker_summary(capture))
                         if docker_summary(capture) else "  Docker: sin datos")
            lines.append(f"  Contenedores activos: {format_count(len(data['docker'].get('containers', [])))}")
        for snapshot in data.get("snapshots", []):
            variation = capture.get("variation", {}).get("snapshot_sizes", {}).get(snapshot.get("path"))
            lines.append(f"  Snapshot {snapshot.get('path')}: {format_bytes(snapshot.get('total_bytes'))} ({format_pct(variation)})")
        if data.get("errors"):
            lines.append("  Avisos: " + "; ".join(str(item) for item in data["errors"]))
    return "\n".join(lines) + "\n"


def render_html(report: dict[str, Any]) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value))

    def change_class(value: float | None) -> str:
        if value is None:
            return "change muted"
        return "change up" if value > 0 else "change down" if value < 0 else "change flat"

    def metric_card(label: str, value: str, change: float | None) -> str:
        return (
            f"<div class='metric'><div class='metric-label'>{esc(label)}</div>"
            f"<div class='metric-value'>{esc(value)}</div>"
            f"<div class='{change_class(change)}'>{esc(format_pct(change))}</div></div>"
        )

    def chip(value: str, extra_class: str = "") -> str:
        return f"<span class='chip {extra_class}'>{esc(value)}</span>"

    def disk_chart(capture: dict[str, Any]) -> str:
        disk = capture.get("data", {}).get("disk", {})
        try:
            total = max(0, int(disk.get("total_bytes") or 0))
            free = min(total, max(0, int(disk.get("free_bytes") or 0)))
        except (TypeError, ValueError):
            return ""
        if total <= 0:
            return ""
        used = total - free
        free_pct = free / total * 100
        used_pct = used / total * 100
        free_change = capture.get("variation", {}).get("disk_free_bytes")
        label = f"{format_bytes(free)} libres frente a {format_bytes(used)} ocupados"
        return f"""
        <div style='margin-top:16px;padding:14px;border:1px solid #e5ebf2;border-radius:14px;background:#fbfcfe'>
          <div class='detail-label' style='margin-bottom:10px'>Disco raíz · libre frente a ocupado</div>
          <div style='display:flex;align-items:center;gap:14px'>
            <svg role='img' aria-label='{esc(label)}' viewBox='0 0 42 42' width='104' height='104' style='flex:none;display:block'>
              <circle cx='21' cy='21' r='15.9' fill='none' stroke='#e0e7ef' stroke-width='6'/>
              <circle cx='21' cy='21' r='15.9' fill='none' stroke='#32a984' stroke-width='6' stroke-linecap='round' stroke-dasharray='{free_pct:.4f} {used_pct:.4f}' transform='rotate(-90 21 21)'/>
              <text x='21' y='20.2' text-anchor='middle' fill='#152238' font-size='6.2' font-weight='700'>{free_pct:.0f}%</text>
              <text x='21' y='25.1' text-anchor='middle' fill='#7b899a' font-size='3.5'>LIBRE</text>
            </svg>
            <div style='min-width:0;flex:1'>
              <div style='color:#152238;font-size:13px;font-weight:750;line-height:1.3'>{esc(format_bytes(free))} libres</div>
              <div style='margin-top:3px;color:#6c7a8e;font-size:11px'>{esc(format_bytes(used))} ocupados · {esc(format_bytes(total))} total</div>
              <div style='display:flex;flex-wrap:wrap;gap:7px 12px;margin-top:10px;color:#526176;font-size:10px'>
                <span><span style='display:inline-block;width:8px;height:8px;border-radius:50%;background:#32a984;margin-right:4px'></span>Libre {free_pct:.1f}%</span>
                <span><span style='display:inline-block;width:8px;height:8px;border-radius:50%;background:#e0e7ef;margin-right:4px'></span>Ocupado {used_pct:.1f}%</span>
              </div>
              <div class='{change_class(free_change)}' style='margin-top:7px'>Variación de espacio libre: {esc(format_pct(free_change))}</div>
            </div>
          </div>
        </div>"""

    def storage_chart(capture: dict[str, Any]) -> str:
        storage = storage_usage(capture)
        items: list[dict[str, Any]] = []
        for item in storage.get("directories", []):
            path = str(item.get("path") or "")
            try:
                size = max(0, int(item.get("size_bytes") or 0))
            except (TypeError, ValueError):
                continue
            if path and size > 0:
                items.append({"path": path, "size_bytes": size, "kind": "DIR"})
        items = sorted(items, key=lambda item: int(item["size_bytes"]), reverse=True)[:10]
        total = sum(int(item["size_bytes"]) for item in items)
        if not items or total <= 0:
            return ""

        palette = ("#2f6fed", "#32a984", "#c7a667", "#8b6fc4", "#e27d60", "#4e9bb5", "#d26a9a", "#78926a", "#c47c3c", "#65758b")
        segments: list[str] = []
        legend: list[str] = []
        offset = 25.0
        for index, item in enumerate(items):
            percentage = int(item["size_bytes"]) / total * 100
            color = palette[index % len(palette)]
            segments.append(
                f"<circle cx='21' cy='21' r='15.9' fill='none' stroke='{color}' stroke-width='6' stroke-linecap='butt' stroke-dasharray='{percentage:.4f} {100 - percentage:.4f}' stroke-dashoffset='{offset:.4f}' transform='rotate(-90 21 21)'/>"
            )
            offset -= percentage
            variation = capture.get("variation", {}).get("storage_directories", {}).get(item["path"])
            legend.append(
                f"<div style='display:flex;align-items:flex-start;gap:6px;padding:5px 0;border-bottom:1px solid #edf0f4;font-size:10px;line-height:1.3'>"
                f"<span style='flex:none;width:8px;height:8px;margin-top:2px;border-radius:2px;background:{color}'></span>"
                f"<span style='min-width:0;flex:1;color:#526176;overflow-wrap:anywhere'><strong style='color:#7a8798;font-size:9px'>{item['kind']}</strong> {esc(item['path'])}</span>"
                f"<strong style='flex:none;color:#152238'>{esc(format_bytes(item['size_bytes']))} <em class='{change_class(variation)}'>{esc(format_pct(variation))}</em></strong>"
                "</div>"
            )
        return f"""
        <div style='margin-top:10px;padding:14px;border:1px solid #e5ebf2;border-radius:14px;background:#fff'>
          <div class='detail-label' style='margin-bottom:10px'>Qué ocupa más · top 10 directorios</div>
          <div style='display:flex;align-items:center;gap:14px'>
            <svg role='img' aria-label='Top 10 directorios por espacio ocupado' viewBox='0 0 42 42' width='104' height='104' style='flex:none;display:block'>
              <circle cx='21' cy='21' r='15.9' fill='none' stroke='#edf0f4' stroke-width='6'/>
              {''.join(segments)}
              <text x='21' y='19.5' text-anchor='middle' fill='#152238' font-size='5.2' font-weight='700'>TOP 10</text>
              <text x='21' y='24.4' text-anchor='middle' fill='#7b899a' font-size='3.4'>ELEMENTOS</text>
            </svg>
            <div style='min-width:0;flex:1;color:#6c7a8e;font-size:10px;line-height:1.45'>
              <strong style='display:block;color:#152238;font-size:13px'>{esc(format_bytes(total))}</strong>
              <span>peso relativo entre los 10 directorios seleccionados</span>
            </div>
          </div>
          <div style='margin-top:10px'>{''.join(legend)}</div>
        </div>"""

    server_cards: list[str] = []
    spend_captures = [capture for capture in report["targets"] if openrouter_spend(capture)]
    spend_details: list[str] = []
    total_spend = 0.0
    total_requests = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_spend_errors = 0
    for spend_capture in spend_captures:
        spend = openrouter_spend(spend_capture) or {}
        total_spend += float(spend.get("total_usd") or 0)
        total_requests += int(spend.get("requests") or 0)
        total_input_tokens += int(spend.get("input_tokens") or 0)
        total_output_tokens += int(spend.get("output_tokens") or 0)
        total_spend_errors += int(spend.get("error_requests") or 0)
        for row in spend.get("rows", []):
            spend_details.append(
                "<tr>"
                f"<td data-label='Modelo'><strong>{esc(row.get('model', '—'))}</strong><small>{esc(row.get('consumer', '—'))}</small></td>"
                f"<td data-label='Tarea'>{esc(row.get('task', '—'))}</td>"
                f"<td data-label='Proyecto'>{esc(row.get('project', '(sin proyecto)'))}</td>"
                f"<td data-label='Solicitudes'>{esc(format_count(row.get('requests')))}</td>"
                f"<td data-label='Coste'><strong>{esc(format_usd(row.get('cost_usd')))}</strong></td>"
                f"<td data-label='Tokens'>{esc(format_count((row.get('input_tokens') or 0) + (row.get('output_tokens') or 0)))}<small>{esc(format_count(row.get('input_tokens')))} in · {esc(format_count(row.get('output_tokens')))} out</small></td>"
                f"<td data-label='Estado'>{esc(str(row.get('status', 'unknown')))}</td>"
                "</tr>"
            )

    spend_section = ""
    if spend_captures:
        primary_change = spend_captures[0].get("variation", {}).get("openrouter_spend_usd")
        source_host = esc(spend_captures[0].get("host", "signal.opnconsultoria.com"))
        spend_section = f"""
        <section class='section spend-section'>
          <div class='section-kicker'>CONTROL DE COSTE · OPENROUTER</div>
          <div class='spend-header'><div><h2>Gasto de IA</h2><p>Últimas 24 horas · fuente: registros de uso de Signal</p></div><span class='{change_class(primary_change)} badge'>{esc(format_pct(primary_change))} vs. día anterior</span></div>
          <div class='spend-grid'>
            <div class='spend-total'><span>Total registrado</span><strong>{esc(format_usd(total_spend))}</strong><small>{esc(source_host)} · cálculo por tokens y catálogo de precios</small></div>
            <div class='spend-stat'><span>Solicitudes</span><strong>{esc(format_count(total_requests))}</strong><small>{esc(format_count(total_spend_errors))} con error</small></div>
            <div class='spend-stat'><span>Tokens</span><strong>{esc(format_count(total_input_tokens + total_output_tokens))}</strong><small>{esc(format_count(total_input_tokens))} entrada · {esc(format_count(total_output_tokens))} salida</small></div>
          </div>
          <p class='footnote'>El coste es el registrado por Signal a partir del uso y el catálogo de precios de OpenRouter; no es una factura descargada del proveedor.</p>
          <div class='table-wrap'><table class='spend-table'><thead><tr><th>Modelo</th><th>Tarea</th><th>Proyecto</th><th>Solicitudes</th><th>Coste</th><th>Tokens</th><th>Estado</th></tr></thead><tbody>{''.join(spend_details)}</tbody></table></div>
        </section>"""

    for capture in report["targets"]:
        label = esc(capture["label"])
        host = esc(capture["host"])
        status = str(capture.get("status", "error"))
        status_class = "ok" if status == "ok" else "warn" if status == "degraded" else "bad"
        status_label = "OK" if status == "ok" else "DEGRADADO" if status == "degraded" else "ERROR"
        if status == "error":
            server_cards.append(
                f"<article class='server-card error-card'><div class='server-head'><div><div class='server-kicker'>SUPERFICIE</div><h3>{label}</h3><div class='host'>{host}</div></div><span class='status {status_class}'>{status_label}</span></div><p class='warn'>{esc(capture.get('error', 'sin detalle'))}</p></article>"
            )
            continue
        metrics = capture.get("metrics", {})
        variation = capture.get("variation", {})
        data = capture.get("data", {})
        service_chips = "".join(chip(f"{name} · {status}", "service-ok" if status == "active" else "service-warn") for name, status in data.get("services", {}).items())
        database_chips = "".join(chip(f"{item.get('name', '—')} · {format_bytes(item.get('size_bytes'))}") for item in data.get("database", {}).get("databases", []))
        task_rows = "".join(
            f"<div class='task-row'><span>{esc(row.get('source'))} · {esc(row.get('kind'))} · {esc(row.get('status'))}</span><strong>{esc(format_count(row.get('count')))}</strong></div>"
            for row in data.get("tasks", {}).get("rows", [])
        ) or "<div class='empty'>Sin tareas registradas en la ventana.</div>"
        docker_chips = "".join(chip(line, "docker-chip") for line in docker_summary(capture))
        snapshot_rows = "".join(
            f"<div class='detail-row'><span>{esc(snapshot.get('path'))}</span><strong>{esc(format_bytes(snapshot.get('total_bytes')))} <em class='{change_class(variation.get('snapshot_sizes', {}).get(snapshot.get('path')))}'>{esc(format_pct(variation.get('snapshot_sizes', {}).get(snapshot.get('path'))))}</em></strong></div>"
            for snapshot in data.get("snapshots", [])
        )
        storage = storage_usage(capture)
        storage_directory_rows = "".join(
            f"<div class='detail-row'><span>{esc(item.get('path'))}</span><strong>{esc(format_bytes(item.get('size_bytes')))} <em class='{change_class(variation.get('storage_directories', {}).get(item.get('path')))}'>{esc(format_pct(variation.get('storage_directories', {}).get(item.get('path'))))}</em></strong></div>"
            for item in storage.get("directories", [])
        )
        storage_file_rows = "".join(
            f"<div class='detail-row'><span>{esc(item.get('path'))}</span><strong>{esc(format_bytes(item.get('size_bytes')))} <em class='{change_class(variation.get('storage_files', {}).get(item.get('path')))}'>{esc(format_pct(variation.get('storage_files', {}).get(item.get('path'))))}</em></strong></div>"
            for item in storage.get("files", [])
        )
        extras = ""
        if service_chips:
            extras += f"<div class='detail-block'><div class='detail-label'>Servicios</div><div class='chips'>{service_chips}</div></div>"
        if database_chips:
            extras += f"<div class='detail-block'><div class='detail-label'>Bases de datos</div><div class='chips'>{database_chips}</div></div>"
        extras += f"<div class='detail-block'><div class='detail-label'>Tareas ejecutadas · últimas 24 h</div><div class='task-list'>{task_rows}</div></div>"
        if data.get("docker"):
            extras += f"<div class='detail-block'><div class='detail-label'>Docker · espacio explícito · {len(data['docker'].get('containers', []))} contenedores activos</div><div class='chips'>{docker_chips or chip('Sin datos')}</div></div>"
        if snapshot_rows:
            extras += f"<div class='detail-block'><div class='detail-label'>Snapshots / copias</div><div class='detail-list'>{snapshot_rows}</div></div>"
        if storage_directory_rows:
            extras += f"<div class='detail-block'><div class='detail-label'>Top 10 directorios por tamaño</div><div class='detail-list'>{storage_directory_rows}</div></div>"
        if storage_file_rows:
            extras += f"<div class='detail-block'><div class='detail-label'>Top 10 archivos por tamaño</div><div class='detail-list'>{storage_file_rows}</div></div>"
        if data.get("errors"):
            extras += f"<div class='alert'>{'; '.join(esc(item) for item in data['errors'])}</div>"
        charts = disk_chart(capture) + storage_chart(capture)
        server_cards.append(f"""
        <article class='server-card'>
          <div class='server-head'><div><div class='server-kicker'>{esc(str(data.get('os', 'Linux')))} · CPU {esc(data.get('cpu_count', 'n/d'))} · carga {esc(data.get('load_1m', 'n/d'))}</div><h3>{label}</h3><div class='host'>{host}</div></div><span class='status {status_class}'>{status_label}</span></div>
          <div class='metrics'>
            {metric_card('Disco libre', format_bytes(metrics.get('disk_free_bytes')), variation.get('disk_free_bytes'))}
            {metric_card('RAM disponible', format_bytes(metrics.get('memory_available_bytes')), variation.get('memory_available_bytes'))}
            {metric_card('Bases de datos', format_bytes(metrics.get('database_total_bytes')), variation.get('database_total_bytes'))}
            {metric_card('Tareas', task_summary(capture), variation.get('tasks_total'))}
          </div>
          {charts}
          <div class='server-details'>{extras}</div>
        </article>""")

    captured = esc(report["captured_at_local"])
    host_count = len(report["targets"])
    error_count = sum(1 for capture in report["targets"] if capture.get("status") == "error")
    return f"""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><meta name='color-scheme' content='light'><title>OPN · Estado diario</title><style>
*{{box-sizing:border-box}}html,body{{margin:0;padding:0;background:#edf1f6;color:#152238;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;-webkit-text-size-adjust:100%}}body{{padding:20px}}.shell{{max-width:780px;margin:0 auto;background:#fff;border:1px solid #e1e7ef;border-radius:24px;overflow:hidden;box-shadow:0 18px 55px rgba(20,39,67,.12)}}.hero{{padding:28px 28px 24px;background:#0c1b2e;color:#fff;border-bottom:3px solid #c7a667}}.eyebrow,.section-kicker,.server-kicker,.detail-label{{font-size:10px;letter-spacing:1.3px;text-transform:uppercase;font-weight:750}}.eyebrow,.section-kicker{{color:#c7a667}}.hero h1{{margin:10px 0 7px;font-size:28px;line-height:1.1;letter-spacing:-.6px}}.hero p{{margin:0;color:#b7c5d6;font-size:13px;line-height:1.5}}.hero-meta{{display:flex;gap:8px;flex-wrap:wrap;margin-top:19px}}.hero-meta span{{padding:7px 10px;border:1px solid rgba(255,255,255,.18);border-radius:999px;color:#dce5ef;font-size:11px}}.section{{padding:24px 28px}}.section h2{{margin:4px 0 4px;font-size:19px;letter-spacing:-.2px}}.section-subtitle,.spend-header p{{margin:0;color:#6c7a8e;font-size:12px}}.summary-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:16px}}.summary-card,.spend-stat,.spend-total{{padding:16px;border:1px solid #e2e8f0;border-radius:16px;background:#fbfcfe}}.summary-card span,.spend-stat span,.spend-total span{{display:block;color:#6c7a8e;font-size:11px;font-weight:650;text-transform:uppercase;letter-spacing:.5px}}.summary-card strong,.spend-stat strong{{display:block;margin-top:6px;color:#152238;font-size:20px;letter-spacing:-.4px}}.summary-card small,.spend-stat small,.spend-total small{{display:block;margin-top:6px;color:#8290a1;font-size:11px;line-height:1.4}}.summary-card.accent{{background:#f8f5ee;border-color:#dfcfad}}.spend-section{{padding-top:25px;background:#fbfaf7;border-top:1px solid #eee8db;border-bottom:1px solid #eee8db}}.spend-header{{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}}.spend-header h2{{color:#172238}}.badge{{white-space:nowrap;margin-top:3px;padding:6px 8px;border-radius:999px;font-size:10px;font-weight:750}}.spend-grid{{display:grid;grid-template-columns:1.5fr 1fr 1fr;gap:10px;margin-top:16px}}.spend-total{{background:#fff;border-color:#dfcfad}}.spend-total strong{{display:block;margin-top:5px;color:#0c1b2e;font-size:28px;letter-spacing:-.8px}}.spend-total small{{color:#7c6b4d}}.spend-stat{{background:rgba(255,255,255,.65)}}.footnote{{margin:14px 0 0;color:#7c6b4d;font-size:11px;line-height:1.45}}.table-wrap{{overflow-x:auto;margin-top:16px;border:1px solid #e6e0d5;border-radius:13px;background:#fff}}table{{width:100%;border-collapse:collapse;font-size:11px}}th,td{{padding:10px 9px;text-align:left;vertical-align:top;border-bottom:1px solid #edf0f4}}th{{color:#6c7a8e;background:#f7f8fa;font-size:10px;text-transform:uppercase;letter-spacing:.4px;white-space:nowrap}}td{{color:#25344a}}td small{{display:block;margin-top:3px;color:#8a97a8;font-size:10px}}tr:last-child td{{border-bottom:0}}.change{{font-size:11px;font-weight:750;margin-top:5px}}.change.up{{color:#b75d52}}.change.down{{color:#27866e}}.change.flat,.change.muted{{color:#7e8b9c}}.server-section{{padding-top:20px}}.server-section h2{{margin-bottom:14px}}.server-card{{margin-top:14px;padding:20px;border:1px solid #e0e7ef;border-radius:18px;background:#fff;box-shadow:0 6px 18px rgba(33,53,79,.05)}}.server-card:first-child{{margin-top:0}}.server-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}}.server-kicker{{color:#8794a5;letter-spacing:.8px;font-size:9px}}.server-head h3{{margin:6px 0 3px;color:#152238;font-size:17px;letter-spacing:-.2px}}.host{{color:#728095;font-size:11px;overflow-wrap:anywhere}}.status{{flex:none;padding:6px 9px;border-radius:999px;font-size:10px;font-weight:800;letter-spacing:.4px}}.status.ok{{color:#16735e;background:#e6f5ef}}.status.warn{{color:#946b18;background:#fbf2d8}}.status.bad{{color:#a54545;background:#fae8e8}}.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:18px}}.metric{{min-width:0;padding:11px 10px;border-radius:12px;background:#f5f7fa}}.metric-label{{color:#718096;font-size:10px;font-weight:650;line-height:1.25}}.metric-value{{margin-top:6px;color:#152238;font-size:14px;font-weight:750;overflow-wrap:anywhere;line-height:1.2}}.server-details{{margin-top:18px;border-top:1px solid #edf0f4;padding-top:16px}}.detail-block+.detail-block{{margin-top:14px}}.detail-label{{color:#8794a5;font-size:9px;letter-spacing:.8px;margin-bottom:8px}}.chips{{display:flex;flex-wrap:wrap;gap:6px}}.chip{{display:inline-block;padding:6px 8px;border:1px solid #e1e7ef;border-radius:8px;background:#f8fafc;color:#485870;font-size:10px;line-height:1.25;overflow-wrap:anywhere}}.service-ok{{color:#22745f;background:#edf8f4;border-color:#d2eee3}}.service-warn{{color:#946b18;background:#fff8e5;border-color:#f1e2b4}}.docker-chip{{color:#315b88;background:#eff6ff;border-color:#d9e8f8}}.task-list,.detail-list{{border:1px solid #edf0f4;border-radius:10px;overflow:hidden}}.task-row,.detail-row{{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:8px 10px;border-bottom:1px solid #edf0f4;color:#526176;font-size:10px;line-height:1.3}}.task-row:last-child,.detail-row:last-child{{border-bottom:0}}.task-row strong,.detail-row strong{{flex:none;color:#152238;font-size:11px}}.detail-row span{{overflow-wrap:anywhere}}em{{font-style:normal;font-size:10px;font-weight:750;margin-left:5px}}.empty{{padding:10px;color:#8794a5;font-size:10px}}.alert{{margin-top:14px;padding:10px 12px;border-radius:10px;color:#946b18;background:#fff8e5;border:1px solid #f1e2b4;font-size:10px;line-height:1.4}}.error-card{{border-color:#efcaca;background:#fffafa}}.footer{{padding:20px 28px 25px;color:#8995a5;font-size:10px;line-height:1.5;border-top:1px solid #edf0f4}}@media(max-width:620px){{body{{padding:0;background:#fff}}.shell{{border:0;border-radius:0;box-shadow:none;max-width:none}}.hero,.section,.footer{{padding-left:18px;padding-right:18px}}.hero{{padding-top:24px;padding-bottom:21px}}.hero h1{{font-size:25px}}.summary-grid{{grid-template-columns:1fr 1fr;gap:8px}}.summary-card{{padding:13px}}.summary-card strong{{font-size:17px}}.spend-header{{display:block}}.badge{{display:inline-block;margin-top:10px}}.spend-grid{{grid-template-columns:1fr 1fr}}.spend-total{{grid-column:1/-1}}.spend-total strong{{font-size:26px}}.server-card{{padding:16px;border-radius:15px}}.metrics{{grid-template-columns:1fr 1fr;gap:7px}}.metric{{min-height:78px;padding:10px}}.metric-value{{font-size:13px}}.server-head h3{{font-size:16px}}.spend-table{{min-width:650px}}}}
</style></head><body><main class='shell'><header class='hero'><div class='eyebrow'>OPN · CONTROL CENTER</div><h1>Estado diario de infraestructura</h1><p>Salud operativa, capacidad y gasto de IA en una vista ejecutiva.</p><div class='hero-meta'><span>{captured}</span><span>{host_count} superficies monitorizadas</span><span>Ventana 24 h</span></div></header><section class='section'><div class='section-kicker'>RESUMEN EJECUTIVO</div><h2>La operación, en una pantalla</h2><p class='section-subtitle'>Variaciones frente a la captura diaria anterior.</p><div class='summary-grid'><div class='summary-card accent'><span>Servidores OK</span><strong>{host_count - error_count} / {host_count}</strong><small>{'Sin incidencias de conexión' if error_count == 0 else f'{error_count} con incidencia'}</small></div><div class='summary-card'><span>Ventana de actividad</span><strong>24 horas</strong><small>Servicios, tareas y consumo registrados</small></div></div></section>{spend_section}<section class='section server-section'><div class='section-kicker'>SALUD POR SUPERFICIE</div><h2>Servidores y servicios</h2><p class='section-subtitle'>Capacidad disponible, bases de datos y ejecución reciente.</p>{''.join(server_cards)}</section><footer class='footer'>Informe generado automáticamente por el monitor externo de OPN. El gasto OpenRouter se toma de los registros de uso de Signal y se muestra con su variación frente al informe anterior.</footer></main></body></html>"""


def send_graph_email(monitor: dict[str, Any], subject: str, text_body: str, html_body: str) -> None:
    tenant = str(monitor.get("graph_tenant_id", "")).strip()
    client_id = str(monitor.get("graph_client_id", "")).strip()
    sender = str(monitor.get("graph_sender_mailbox", "")).strip()
    recipients = [str(item).strip() for item in monitor.get("recipients", []) if str(item).strip()]
    secret_file = Path(str(monitor.get("graph_client_secret_file", "")))
    if not all((tenant, client_id, sender, recipients)) or not secret_file.is_file():
        raise RuntimeError("faltan parámetros de Microsoft Graph o el fichero de secreto")
    secret = secret_file.read_text(encoding="utf-8").strip()
    token_url = f"https://login.microsoftonline.com/{urllib.parse.quote(tenant)}/oauth2/v2.0/token"
    token_payload = urllib.parse.urlencode({
        "client_id": client_id, "client_secret": secret, "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    }).encode()
    token_request = urllib.request.Request(token_url, data=token_payload, method="POST")
    try:
        with urllib.request.urlopen(token_request, timeout=30) as response:
            token = json.loads(response.read().decode("utf-8"))["access_token"]
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError("no se pudo obtener token de Microsoft Graph") from exc
    message = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html_body},
            "toRecipients": [{"emailAddress": {"address": item}} for item in recipients],
        },
        "saveToSentItems": False,
    }
    send_url = f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(sender)}/sendMail"
    send_request = urllib.request.Request(
        send_url, data=json.dumps(message, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(send_request, timeout=30) as response:
            if response.status not in (200, 202):
                raise RuntimeError(f"Graph respondió HTTP {response.status}")
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise RuntimeError("Microsoft Graph rechazó el envío") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--ssh-key", type=Path, help="override the SSH key from TOML")
    parser.add_argument("--known-hosts", type=Path, help="override the known_hosts file from TOML")
    parser.add_argument("--no-send", action="store_true", help="recoge y muestra el informe sin enviar correo")
    parser.add_argument("--dry-run", action="store_true", help="no guarda histórico ni envía correo")
    parser.add_argument("--print-json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_toml(args.config)
    monitor = dict(config.get("monitor", {}))
    if args.ssh_key:
        monitor["ssh_key_file"] = str(args.ssh_key)
    if args.known_hosts:
        monitor["ssh_known_hosts_file"] = str(args.known_hosts)
    targets = config.get("targets", [])
    if not targets:
        raise SystemExit("El fichero de configuración no contiene targets.")
    zone = ZoneInfo(str(monitor.get("timezone", "Europe/Madrid")))
    now = datetime.now(UTC)
    state_path = args.state or (Path(str(monitor["state_file"])) if monitor.get("state_file") else None)
    previous_state = read_json(state_path) if state_path else {}
    previous_targets = previous_state.get("targets", {})
    captures = [None] * len(targets)
    with ThreadPoolExecutor(max_workers=min(8, len(targets))) as executor:
        futures = {executor.submit(collect_target, target, monitor): index for index, target in enumerate(targets)}
        for future in as_completed(futures):
            captures[futures[future]] = future.result()
    for capture in captures:
        previous = previous_targets.get(capture["id"])
        add_variations(capture, previous)
    report = {
        "captured_at": now.isoformat(),
        "captured_at_local": now.astimezone(zone).strftime("%Y-%m-%d %H:%M %Z"),
        "targets": captures,
    }
    text_body = render_text(report)
    html_body = render_html(report)
    if args.print_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(text_body, end="")
    if not args.dry_run and state_path:
        baselines = dict(previous_targets)
        for capture in captures:
            if capture.get("status") != "error":
                baselines[capture["id"]] = capture
        write_json_atomic(state_path, {"version": 1, "captured_at": report["captured_at"], "targets": baselines})
    if not args.no_send and not args.dry_run:
        date_label = now.astimezone(zone).strftime("%Y-%m-%d")
        send_graph_email(monitor, f"OPN · Estado diario de servidores · {date_label}", text_body, html_body)
        print(f"Correo enviado a {', '.join(monitor.get('recipients', []))}.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
