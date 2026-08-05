#!/usr/bin/env python3
"""SV2-EXPEDIENTE-CON-CARNE · alimentar el expediente demo con PLACSP real (coste 0).

Fija licitaciones abiertas y adjudicaciones de competidores del sector software/IA
vía el proxy de contratación de Oracle → Signal (PLACSP estructurado, gratis).

  ORACLE_CREDS_PATH=/path/to/creds.txt python3 scripts/sv2_feed_demo_dossier.py

No usa búsqueda de pago. No toca el gate de fundamentación.
"""

from __future__ import annotations

import json
import os
import sys
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

# Materia prima real elegida a mano (PLACSP signal-dev, 2026-08-03):
# 7 licitaciones abiertas software/plataformas/IT + 5 adjudicaciones a Babel/Capgemini/NTT/Inetum.
PINS: list[tuple[str, str]] = [
    ("tender", "CONTR 2026 11077"),  # red de agentes inteligentes (Baleares) ~5,45 M€
    ("tender", "2601CTRDT001"),  # soporte usuarios MIVAU ~0,91 M€
    ("tender", "26840045700"),  # soporte IT + seguridad AEAT ~4,10 M€
    ("tender", "016/2026/SER/DG"),  # intranet LogiRail ~0,11 M€
    ("tender", "2026044323"),  # plataforma padrón municipal ~0,09 M€
    ("tender", "302026"),  # Business Central / Power Apps ~0,11 M€
    ("tender", "5832/2026"),  # implantación sistema (El Campello) ~0,13 M€
    ("award", "XP1228/2025"),  # Capgemini ZTNA ~0,32 M€
    ("award", "X260033SSODE"),  # NTT DATA EES ~4,87 M€
    ("award", "CG-2026/2815/0061"),  # Capgemini multiagente IA ~0,13 M€
    ("award", "1DGT2AP00041"),  # Inetum/Capgemini analítica ~1,62 M€
    # 102/2026 se omite: el folder colisiona con un lote ajeno al sector software.
]


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
                if not raw:
                    return int(resp.status), None
                return int(resp.status), json.loads(raw)
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", errors="replace")
            try:
                payload: Any = json.loads(raw) if raw else {"detail": str(error)}
            except json.JSONDecodeError:
                payload = {"detail": raw[:800]}
            return int(error.code), payload

    def login(self, email: str, password: str, tenant_id: str) -> None:
        code, payload = self.request("GET", "/api/v1/auth/csrf")
        if code != 200 or not isinstance(payload, dict):
            raise SystemExit(f"CSRF falló {code}: {payload!r}")
        self.csrf = str(payload["csrf_token"])
        code, payload = self.request(
            "POST",
            "/api/v1/auth/login",
            {"email": email, "password": password, "tenant_id": tenant_id},
        )
        if code != 200:
            raise SystemExit(f"Login falló {code}: {payload!r}")
        code, payload = self.request("GET", "/api/v1/auth/csrf")
        self.csrf = str(payload["csrf_token"])


def main() -> int:
    base = env("ORACLE_BASE_URL", DEFAULT_BASE)
    creds_path = Path(env("ORACLE_CREDS_PATH", DEFAULT_CREDS))
    dossier_id = env("DOSSIER_ID", DEFAULT_DOSSIER)
    tenant_id = env("TENANT_ID", DEFAULT_TENANT)
    if not creds_path.is_file():
        raise SystemExit(f"Credenciales no encontradas: {creds_path}")
    email, password = parse_creds(creds_path.read_text(encoding="utf-8"))
    client = Client(base)
    client.login(email, password, tenant_id)

    code, before = client.request("GET", f"/api/v1/dossiers/{dossier_id}/procurement")
    before_n = len((before or {}).get("data") or []) if isinstance(before, dict) else -1
    print(f"BEFORE procurement_items={before_n}", flush=True)

    ok = 0
    for kind, folder_id in PINS:
        code, payload = client.request(
            "POST",
            f"/api/v1/dossiers/{dossier_id}/procurement",
            {"kind": kind, "folder_id": folder_id},
            headers={"Idempotency-Key": f"sv2-feed-{kind}-{folder_id}-{uuid.uuid4().hex[:8]}"},
        )
        title = ""
        if isinstance(payload, dict):
            snap = payload.get("snapshot") or {}
            title = str(snap.get("title") or payload.get("detail") or "")[:90]
        print(f"PIN {code} {kind} {folder_id} {title}", flush=True)
        if code in {200, 201}:
            ok += 1

    code, after = client.request("GET", f"/api/v1/dossiers/{dossier_id}/procurement")
    after_n = len((after or {}).get("data") or []) if isinstance(after, dict) else -1
    print(f"AFTER procurement_items={after_n} pinned_ok={ok}/{len(PINS)}", flush=True)
    if ok < len(PINS):
        return 1
    print("FEED_DEMO_DOSSIER_PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
