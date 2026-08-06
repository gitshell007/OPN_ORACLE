#!/usr/bin/env python3
"""Higiene segura de un tenant de demo/UAT mediante la API.

Archiva expedientes de prueba, marca notificaciones como leídas y opcionalmente
lanza informes «dorados» con PDF (el backend añade pdf si WeasyPrint está activo).

Uso:

  export ORACLE_BASE_URL=https://oracle-dev.example.test
  export ORACLE_EMAIL='user@example.com'
  export ORACLE_PASSWORD='…'   # no lo pegues en tickets ni en el repo
  python3 scripts/demo_tenant_hygiene.py --expected-tenant 'SV2 Demo Tenant'
  python3 scripts/demo_tenant_hygiene.py --expected-tenant 'SV2 Demo Tenant' --apply

No imprime la contraseña. Es dry-run por defecto, no tiene URL de producción
predeterminada y exige confirmar por nombre el tenant activo. No borra filas:
archiva expedientes y desactiva vigilancias QA de forma reversible.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from typing import Any


TITLE_ARCHIVE_MARKERS = (
    "alta-honesta",
    "audit-test",
    "playwright",
    "prueba real",
    "scope-403",
    "smoke tip",
    "uat p",
)

WATCH_DISABLE_MARKERS = (
    "alta-honesta",
    "playwright",
    "scope-403",
    "smoke",
    "uat",
)

# Expedientes demo a conservar (subcadena del título, casefold).
KEEP_MARKERS = (
    "coches de bomberos",
    "gigafactoría",
    "catl",
    "concurso bomberos",
)


class Session:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
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
        timeout: float = 60,
    ) -> tuple[int, Any]:
        body = None
        req_headers = {"Accept": "application/json", **(headers or {})}
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            self.base + path,
            data=body,
            headers=req_headers,
            method=method,
        )
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                payload: Any = json.loads(raw) if raw else None
                return resp.status, payload
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8")
            try:
                payload = json.loads(raw) if raw else {"detail": str(error)}
            except json.JSONDecodeError:
                payload = {"detail": raw[:500]}
            return error.code, payload

    def refresh_csrf(self) -> None:
        code, payload = self.request("GET", "/api/v1/auth/csrf")
        if (
            code != 200
            or not isinstance(payload, dict)
            or not payload.get("csrf_token")
        ):
            raise RuntimeError(f"No se pudo obtener CSRF ({code}): {payload}")
        self.csrf = str(payload["csrf_token"])

    def login(self, email: str, password: str) -> None:
        self.refresh_csrf()
        code, payload = self.request(
            "POST",
            "/api/v1/auth/login",
            data={"email": email, "password": password},
            headers={"X-CSRF-Token": self.csrf},
        )
        if code != 200:
            raise RuntimeError(f"Login fallido ({code}): {payload}")
        self.refresh_csrf()


def should_archive(title: str, status: str) -> bool:
    if status == "archived":
        return False
    low = title.casefold()
    if any(marker in low for marker in KEEP_MARKERS) and not any(
        marker in low for marker in TITLE_ARCHIVE_MARKERS
    ):
        return False
    return any(marker in low for marker in TITLE_ARCHIVE_MARKERS)


def archive_junk(session: Session, *, apply: bool) -> list[str]:
    code, payload = session.request("GET", "/api/v1/dossiers?page=1&page_size=100")
    if code != 200 or not isinstance(payload, dict):
        raise RuntimeError(f"Listado de expedientes falló ({code}): {payload}")
    archived: list[str] = []
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        status = str(item.get("status") or "")
        dossier_id = str(item.get("id") or "")
        if not dossier_id or not should_archive(title, status):
            continue
        if not apply:
            print(f"  [dry-run] archivaría: {title}")
            archived.append(title)
            continue
        session.refresh_csrf()
        code, detail = session.request("GET", f"/api/v1/dossiers/{dossier_id}")
        if code != 200 or not isinstance(detail, dict):
            print(f"  omitido (detalle {code}): {title}", file=sys.stderr)
            continue
        version = detail.get("version")
        code, body = session.request(
            "POST",
            f"/api/v1/dossiers/{dossier_id}/archive",
            headers={
                "X-CSRF-Token": session.csrf,
                "If-Match": f'W/"{version}"',
            },
        )
        if code == 200:
            print(f"  archivado: {title}")
            archived.append(title)
        else:
            print(f"  error archive {code}: {title} → {body}", file=sys.stderr)
    return archived


def should_disable_watch(name: str, enabled: bool, notifications_enabled: bool) -> bool:
    low = str(name or "").casefold()
    return (enabled or notifications_enabled) and any(
        marker in low for marker in WATCH_DISABLE_MARKERS
    )


def disable_junk_watches(session: Session, *, apply: bool) -> list[str]:
    code, payload = session.request("GET", "/api/v1/procurement-search-watches")
    if code != 200 or not isinstance(payload, dict):
        raise RuntimeError(f"Listado de vigilancias falló ({code}): {payload}")
    disabled: list[str] = []
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        watch_id = str(item.get("id") or "")
        if not watch_id or not should_disable_watch(
            name,
            bool(item.get("enabled")),
            bool(item.get("notifications_enabled")),
        ):
            continue
        if not apply:
            print(f"  [dry-run] desactivaría vigilancia: {name}")
            disabled.append(name)
            continue
        session.refresh_csrf()
        code, body = session.request(
            "PATCH",
            f"/api/v1/procurement-search-watches/{watch_id}",
            data={
                "enabled": False,
                "notifications_enabled": False,
                "cadence_seconds": item.get("cadence_seconds"),
            },
            headers={"X-CSRF-Token": session.csrf},
        )
        if code == 200:
            print(f"  vigilancia desactivada: {name}")
            disabled.append(name)
        else:
            print(f"  error vigilancia {code}: {name} → {body}", file=sys.stderr)
    return disabled


def read_all_notifications(session: Session) -> int:
    session.refresh_csrf()
    code, payload = session.request(
        "POST",
        "/api/v1/notifications/read-all",
        headers={"X-CSRF-Token": session.csrf},
    )
    if code != 200 or not isinstance(payload, dict):
        raise RuntimeError(f"read-all falló ({code}): {payload}")
    return int(payload.get("updated") or 0)


def create_report(
    session: Session,
    *,
    dossier_id: str,
    template_key: str,
    options: dict[str, Any],
    label: str,
) -> tuple[str, str] | None:
    session.refresh_csrf()
    key = f"hygiene-{template_key}-{int(time.time())}"
    code, payload = session.request(
        "POST",
        f"/api/v1/dossiers/{dossier_id}/reports",
        data={"template_key": template_key, "options": options},
        headers={"X-CSRF-Token": session.csrf, "Idempotency-Key": key},
    )
    if code not in (200, 202) or not isinstance(payload, dict):
        print(f"  informe {label} falló ({code}): {payload}", file=sys.stderr)
        return None
    report = payload.get("report") or {}
    job_id = str(payload.get("job_id") or report.get("job_id") or "")
    report_id = str(report.get("id") or "")
    if not job_id or not report_id:
        print(f"  informe {label}: respuesta incompleta {payload}", file=sys.stderr)
        return None
    print(f"  encolado {label}: report={report_id} job={job_id}")
    return job_id, report_id


def wait_jobs(
    session: Session, jobs: list[tuple[str, str, str]], *, timeout_s: int = 600
) -> None:
    deadline = time.time() + timeout_s
    pending = {job_id: (label, report_id) for label, job_id, report_id in jobs}
    while pending and time.time() < deadline:
        for job_id in list(pending):
            label, report_id = pending[job_id]
            code, job = session.request("GET", f"/api/v1/jobs/{job_id}")
            if code != 200 or not isinstance(job, dict):
                continue
            status = job.get("status")
            if status in {"succeeded", "failed", "cancelled"}:
                code_r, report = session.request("GET", f"/api/v1/reports/{report_id}")
                arts = []
                if code_r == 200 and isinstance(report, dict):
                    arts = [
                        a.get("format")
                        for a in (report.get("artifacts") or [])
                        if isinstance(a, dict)
                    ]
                print(
                    f"  {label}: job={status} report={report.get('status') if isinstance(report, dict) else '?'} "
                    f"artifacts={arts}"
                )
                del pending[job_id]
        if pending:
            time.sleep(10)
    if pending:
        print(f"  timeout esperando: {list(pending)}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-golden-reports",
        action="store_true",
        help="Encola informes CATL ejecutivo y actores de Concurso bomberos",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("ORACLE_BASE_URL", ""),
    )
    parser.add_argument(
        "--expected-tenant",
        default=os.environ.get("ORACLE_EXPECTED_TENANT", ""),
        help="Nombre exacto del tenant activo; obligatorio como guardia anti-producción.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplica archivado/desactivación. Sin esta opción solo muestra el plan.",
    )
    args = parser.parse_args()
    if not args.base_url.strip():
        print(
            "Define ORACLE_BASE_URL o usa --base-url explícitamente.", file=sys.stderr
        )
        return 2
    expected_tenant = str(args.expected_tenant or "").strip()
    if not expected_tenant:
        print("--expected-tenant es obligatorio.", file=sys.stderr)
        return 2
    if args.with_golden_reports and not args.apply:
        print("--with-golden-reports requiere --apply.", file=sys.stderr)
        return 2
    email = os.environ.get("ORACLE_EMAIL", "").strip()
    password = os.environ.get("ORACLE_PASSWORD", "")
    if not email or not password:
        print("Define ORACLE_EMAIL y ORACLE_PASSWORD en el entorno.", file=sys.stderr)
        return 2

    session = Session(args.base_url)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"Modo {mode} · login en {args.base_url} como {email}")
    session.login(email, password)
    me_code, me = session.request("GET", "/api/v1/auth/me")
    if me_code != 200 or not isinstance(me, dict):
        raise RuntimeError(f"No se pudo verificar el tenant activo ({me_code}): {me}")
    active_tenant_id = str(me.get("active_tenant_id") or "")
    tenant = next(
        (
            item
            for item in (me.get("memberships") or [])
            if isinstance(item, dict)
            and str(item.get("tenant_id") or "") == active_tenant_id
        ),
        None,
    )
    active_name = str((tenant or {}).get("tenant_name") or "")
    if active_name.casefold() != expected_tenant.casefold():
        raise RuntimeError(
            f"Guardia de tenant: activo={active_name!r}, esperado={expected_tenant!r}. "
            "No se realizará ninguna mutación."
        )
    print(f"Tenant verificado: {active_name} · rol {me.get('roles')}")

    print("Archivando expedientes de prueba…")
    archived = archive_junk(session, apply=args.apply)
    print(f"{'Archivados' if args.apply else 'Candidatos a archivar'}: {len(archived)}")

    print("Revisando vigilancias QA…")
    disabled = disable_junk_watches(session, apply=args.apply)
    print(
        f"{'Desactivadas' if args.apply else 'Candidatas a desactivar'}: {len(disabled)}"
    )

    if args.apply:
        print("Marcando notificaciones leídas…")
        updated = read_all_notifications(session)
        print(f"Notificaciones actualizadas: {updated}")

    if args.with_golden_reports:
        print("Encolando informes dorados (PDF lo añade el backend si aplica)…")
        jobs: list[tuple[str, str, str]] = []
        # IDs conocidos del tenant demo OPN; se re-resuelven por título si faltan.
        code, dossiers = session.request("GET", "/api/v1/dossiers?page=1&page_size=50")
        by_title: dict[str, str] = {}
        if code == 200 and isinstance(dossiers, dict):
            for item in dossiers.get("data") or []:
                if isinstance(item, dict) and item.get("status") != "archived":
                    by_title[str(item.get("title") or "").casefold()] = str(
                        item.get("id")
                    )
        catl_id = next(
            (v for k, v in by_title.items() if "catl" in k or "gigafactor" in k), ""
        )
        concurso_id = next(
            (v for k, v in by_title.items() if "concurso bomberos" in k), ""
        )
        base_opts = {
            "formats": ["html", "json"],
            "classification": "internal",
            "confidentiality_label": "Uso interno",
        }
        if catl_id:
            created = create_report(
                session,
                dossier_id=catl_id,
                template_key="executive_dossier",
                options=dict(base_opts),
                label="CATL executive",
            )
            if created:
                jobs.append(("CATL executive", created[0], created[1]))
        if concurso_id:
            created = create_report(
                session,
                dossier_id=concurso_id,
                template_key="actors",
                options=dict(base_opts),
                label="Concurso actors",
            )
            if created:
                jobs.append(("Concurso actors", created[0], created[1]))
        if jobs:
            wait_jobs(session, jobs)
        read_all_notifications(session)

    code, notif = session.request("GET", "/api/v1/notifications?page=1&page_size=1")
    if code == 200 and isinstance(notif, dict):
        print("Notificaciones:", notif.get("meta"))
    code, dossiers = session.request("GET", "/api/v1/dossiers?page=1&page_size=50")
    if code == 200 and isinstance(dossiers, dict):
        print("Expedientes no archivados:")
        for item in dossiers.get("data") or []:
            if isinstance(item, dict) and item.get("status") != "archived":
                print(f"  - [{item.get('status')}] {item.get('title')}")
    print("Higiene terminada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
