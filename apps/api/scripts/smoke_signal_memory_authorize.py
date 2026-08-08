#!/usr/bin/env python3
"""Live smoke: POST /memory/v1/dossiers/{id}/authorize against signal-dev.

Requires env (never commit secrets):
  SIGNAL_MEMORY_LIVE_BASE_URL   default https://signal-dev.opnconsultoria.com
  SIGNAL_MEMORY_LIVE_API_KEY    consumer credential with memory:write
  SIGNAL_MEMORY_LIVE_TENANT_ID  X-OPN-External-Tenant-ID (allowed on consumer)
  SIGNAL_MEMORY_LIVE_DOSSIER_ID UUID of a dossier to authorize

Exit codes:
  0 authorized or manual_required (both are expected honest outcomes)
  2 missing env
  3 unexpected HTTP / transport failure
"""

from __future__ import annotations

import json
import os
import sys
import uuid

# Allow running as `python scripts/...` from apps/api
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))

from opn_oracle.integrations.memory_grant import (  # noqa: E402
    CODE_MANUAL_REQUIRED,
    _interpret_authorize_error,
    _interpret_authorize_success,
)
from opn_oracle.integrations.memory_http_client import (  # noqa: E402
    HttpxTransport,
    MemoryClientConfig,
    MemoryHttpError,
    SignalMemoryHttpClient,
)


def main() -> int:
    base = os.environ.get(
        "SIGNAL_MEMORY_LIVE_BASE_URL", "https://signal-dev.opnconsultoria.com"
    ).rstrip("/")
    api_key = os.environ.get("SIGNAL_MEMORY_LIVE_API_KEY", "").strip()
    tenant = os.environ.get("SIGNAL_MEMORY_LIVE_TENANT_ID", "").strip()
    dossier = os.environ.get("SIGNAL_MEMORY_LIVE_DOSSIER_ID", "").strip()
    if not api_key or not tenant or not dossier:
        print(
            "SKIP live authorize: set SIGNAL_MEMORY_LIVE_API_KEY, "
            "SIGNAL_MEMORY_LIVE_TENANT_ID, SIGNAL_MEMORY_LIVE_DOSSIER_ID",
            file=sys.stderr,
        )
        return 2
    try:
        uuid.UUID(dossier)
    except ValueError:
        print("SIGNAL_MEMORY_LIVE_DOSSIER_ID must be a UUID", file=sys.stderr)
        return 2

    client = SignalMemoryHttpClient(
        MemoryClientConfig(base_url=base, api_token=api_key, require_https=True),
        HttpxTransport(),
    )
    print(f"POST {base}/api/v1/memory/v1/dossiers/{dossier}/authorize")
    print(f"tenant={tenant} (api key not logged)")
    try:
        status, data = client.authorize_dossier(
            external_tenant_id=tenant,
            dossier_id=dossier,
        )
    except MemoryHttpError as exc:
        mapped = _interpret_authorize_error(exc)
        print(
            json.dumps(
                {
                    "http_error_code": exc.code,
                    "job_error_code": exc.job_error_code,
                    "mapped_status": mapped.status,
                    "mapped_code": mapped.code,
                    "message": exc.message,
                    "http_status": exc.http_status,
                },
                indent=2,
            )
        )
        if mapped.code == CODE_MANUAL_REQUIRED:
            print("OK: manual_required path (autogrant off on consumer)")
            return 0
        if mapped.status == "rejected":
            print("OK: rejected path (tenant not allowed or similar)")
            return 0
        print("FAIL: unexpected MemoryHttpError", file=sys.stderr)
        return 3

    mapped_ok = _interpret_authorize_success(data)
    print(json.dumps({"http_status": status, "body": data, "mapped": mapped_ok.status}, indent=2))
    if mapped_ok.status != "authorized":
        print("FAIL: 200 without authorized mapping", file=sys.stderr)
        return 3
    print("OK: authorized (grant created or already active on Signal)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
