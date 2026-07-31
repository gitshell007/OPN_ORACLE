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
        "services": service_metrics(),
        "database": database_metrics(),
        "tasks": task_metrics(),
        "snapshots": snapshot_metrics(),
        "docker": None,
        "errors": [],
    }
    if os.environ.get("MONITOR_DOCKER", "0") == "1":
        data["docker"] = docker_metrics()
    data["errors"].extend(data["database"].get("errors", []))
    data["errors"].extend(data["tasks"].get("errors", []))
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
        "MONITOR_WINDOW_HOURS": str(window_hours),
    }


def collect_target(target: dict[str, Any], monitor: dict[str, Any]) -> dict[str, Any]:
    host = str(target["host"])
    key_file = str(monitor.get("ssh_key_file", ""))
    known_hosts = str(monitor.get("ssh_known_hosts_file", "/etc/ssh/ssh_known_hosts"))
    ssh_user = str(monitor.get("ssh_user", "root"))
    timeout = int(monitor.get("ssh_connect_timeout_seconds", 10))
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
            timeout=max(timeout + 30, 60), check=False,
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
    return {
        "disk_free_bytes": data.get("disk", {}).get("free_bytes"),
        "memory_available_bytes": data.get("memory", {}).get("available_bytes"),
        "database_total_bytes": sum(item.get("size_bytes", 0) or 0 for item in databases),
        "tasks_total": sum(item.get("count", 0) or 0 for item in tasks),
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
        if key in {"disk_free_bytes", "memory_available_bytes", "database_total_bytes", "tasks_total"}
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


def render_text(report: dict[str, Any]) -> str:
    lines = [
        f"Resumen diario de servidores OPN · {report['captured_at_local']}",
        "Ventana de tareas: últimas 24 horas · Variación: frente a la captura diaria anterior",
        "",
        "Servidor | Estado | Disco libre | RAM disponible | BD total | Tareas ejecutadas",
        "---------|--------|-------------|----------------|----------|------------------",
    ]
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
    rows = []
    details = []
    for capture in report["targets"]:
        label = html.escape(str(capture["label"]))
        host = html.escape(str(capture["host"]))
        if capture.get("status") == "error":
            rows.append(f"<tr><td>{label}<br><small>{host}</small></td><td class='bad'>ERROR</td><td colspan='4'>{html.escape(str(capture.get('error', 'sin detalle')))}</td></tr>")
            continue
        metrics = capture.get("metrics", {})
        variation = capture.get("variation", {})
        def cell(value, change):
            return f"{html.escape(value)}<small>{html.escape(format_pct(change))}</small>"
        rows.append(
            f"<tr><td>{label}<br><small>{host}</small></td><td>{html.escape(str(capture.get('status')))}</td>"
            f"<td>{cell(format_bytes(metrics.get('disk_free_bytes')), variation.get('disk_free_bytes'))}</td>"
            f"<td>{cell(format_bytes(metrics.get('memory_available_bytes')), variation.get('memory_available_bytes'))}</td>"
            f"<td>{cell(format_bytes(metrics.get('database_total_bytes')), variation.get('database_total_bytes'))}</td>"
            f"<td>{cell(task_summary(capture), variation.get('tasks_total'))}</td></tr>"
        )
        data = capture.get("data", {})
        detail_parts = [f"<h3>{label} · {host}</h3>", f"<p>{html.escape(str(data.get('os', 'n/d')))} · CPU {html.escape(str(data.get('cpu_count', 'n/d')))} · carga 1m {html.escape(str(data.get('load_1m', 'n/d')))}</p>"]
        services = data.get("services", {})
        if services:
            detail_parts.append("<p><b>Servicios:</b> " + ", ".join(f"{html.escape(str(name))}={html.escape(str(status))}" for name, status in services.items()) + "</p>")
        databases = data.get("database", {}).get("databases", [])
        if databases:
            detail_parts.append("<p><b>Bases:</b> " + ", ".join(f"{html.escape(str(item['name']))}={format_bytes(item['size_bytes'])}" for item in databases) + "</p>")
        tasks = data.get("tasks", {}).get("rows", [])
        if tasks:
            detail_parts.append("<p><b>Tareas:</b> " + "; ".join(f"{html.escape(str(row['source']))}/{html.escape(str(row['status']))}/{html.escape(str(row['kind']))}={format_count(row['count'])}" for row in tasks) + "</p>")
        if data.get("docker"):
            detail_parts.append("<p><b>Docker:</b> " + "; ".join(html.escape(line) for line in docker_summary(capture)) + f" · {len(data['docker'].get('containers', []))} contenedores activos</p>")
        snapshots = data.get("snapshots", [])
        for snapshot in snapshots:
            change = capture.get("variation", {}).get("snapshot_sizes", {}).get(snapshot.get("path"))
            detail_parts.append(f"<p><b>Snapshot:</b> {html.escape(str(snapshot.get('path')))} · {format_bytes(snapshot.get('total_bytes'))} · {html.escape(format_pct(change))}</p>")
        if data.get("errors"):
            detail_parts.append("<p class='warn'><b>Avisos:</b> " + "; ".join(html.escape(str(item)) for item in data["errors"]) + "</p>")
        details.append("\n".join(detail_parts))
    return """<!doctype html><html lang="es"><head><meta charset="utf-8"><style>
body{font-family:Arial,sans-serif;color:#172033;background:#f6f7f9;padding:24px}main{max-width:1100px;margin:auto;background:#fff;padding:24px;border:1px solid #e2e6ed}h1{font-size:22px}h2{font-size:17px;margin-top:28px}h3{font-size:15px;border-top:1px solid #e2e6ed;padding-top:14px}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:9px 8px;border-bottom:1px solid #e2e6ed;text-align:left;vertical-align:top}th{background:#f0f3f7}small{display:block;color:#687386;margin-top:3px}.bad{color:#a32626;font-weight:bold}.warn{color:#8a5b00}td small{color:#58708c;font-weight:600}
</style></head><body><main><h1>Resumen diario de servidores OPN</h1><p>__CAPTURED__<br>Ventana de tareas: últimas 24 horas · porcentajes frente a la captura diaria anterior.</p><h2>Resumen</h2><table><thead><tr><th>Servidor</th><th>Estado</th><th>Disco libre</th><th>RAM disponible</th><th>BD total</th><th>Tareas ejecutadas</th></tr></thead><tbody>__ROWS__</tbody></table><h2>Detalles operativos</h2>__DETAILS__</main></body></html>""".replace("__CAPTURED__", html.escape(str(report["captured_at_local"]))).replace("__ROWS__", "".join(rows)).replace("__DETAILS__", "".join(details))


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
