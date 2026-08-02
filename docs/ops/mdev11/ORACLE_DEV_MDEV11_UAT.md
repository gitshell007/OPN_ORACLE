# MDEV-11 provisional UAT · Oracle Dev

- Window: 2026-08-02T07:22 → ~07:45 Europe/Madrid
- Host: `v2202607388167489673` / `oracle-dev.opnconsultoria.com` / `159.195.216.33`
- Release: **`20260802T040823Z-native-4b454e1`** / SHA **`4b454e1c88fc678b443a18b1c4f0a905b0630fb2`** (no redeploy)
- Services: api/web/worker/beat **active**
- Main checkout `oracle-dev` dirty/WIP: **not modified, not reset, not used as base**

## Connections (superuser / RLS bypass)

| name | status | base_url |
| --- | --- | --- |
| production | **disabled** | https://signal.opnconsultoria.com/api/v1/oracle |
| signal-dev-mdev10-canary | **active** | https://signal-dev.opnconsultoria.com |

- Credential canary fp `8bae98b6558a9d95e71ab6e9aad503e6` / token sha16 `70a69b584cbbef9c` (never printed)
- `SIGNAL_AI_ALLOWED_HOSTS=signal-dev.opnconsultoria.com`
- `SIGNAL_AI_BASE_URL=https://signal-dev.opnconsultoria.com`
- Dossier memory profile canary: **mode=shadow**, etag `W/"dmp-mdev10-v1"`, version 1
- Snapshots canary: **1** (shadow); augment **not** activated

## UI browser

- Login page OK: `https://oracle-dev.opnconsultoria.com/login?next=%2Fapp`
- Network: only `oracle-dev.opnconsultoria.com` origins; `/api/v1/auth/me` → 401 (unauthenticated)
- Console: no errors on login page
- Owner-designated login + Memoria MCC + full expediente workflow: **debt A14** (no invent credentials)

## Modes

| Mode | Result |
| --- | --- |
| disabled | Not fully re-exercised via Ask UI (no auth). IC production disabled; Signal path only via canary. |
| shadow | DMP + snapshot confirm **shadow** retained |
| augment | **Blocked / fail-closed** — retrieve not citable (facts=0, summaries=0, extract jobs=0) |

## Report / faults

- Full informe plan→ready: not executed (auth + pipeline debt)
- Kill switch Signal re-proven via canary credential; Oracle should degrade to own memory when Signal 503 (client behavior already exercised MDEV-10; this turn confirmed Signal 503 path)
- Worker restart fault: not run this turn (time box); marked debt
- Cancel/retry ETag analysis-request: not fully exercised; debt

## Egress

- Config effective + IC: only Signal Dev URL active
- Journals sampled: no openrouter / production signal host hits in last 2h window
- Browser HAR-equivalent network list: zero production domains

## Final

Leave canary **shadow**; production IC **disabled**; no augment.
