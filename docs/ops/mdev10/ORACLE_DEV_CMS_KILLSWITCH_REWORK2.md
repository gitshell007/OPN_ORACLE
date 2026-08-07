# MDEV-10 rework 2/3 · Oracle Dev · kill switch client + shadow only

- Window: 2026-08-02T06:50 → ~07:15 Europe/Madrid
- Host: `v2202607388167489673` / `oracle-dev.opnconsultoria.com` / `159.195.216.33`
- Release: **`20260802T040823Z-native-4b454e1`** (unchanged)
- SHA: **`4b454e1c88fc678b443a18b1c4f0a905b0630fb2`**
- Services: api/web/worker/beat **active**

## Connections

| name | status | base_url |
| --- | --- | --- |
| production | **disabled** | https://signal.opnconsultoria.com/api/v1/oracle |
| signal-dev-mdev10-canary | **active** | https://signal-dev.opnconsultoria.com |

## Kill switch exercise (keyring, no secret print)

- Connection id `ffcf1c40-191b-48e5-bc92-46cb3da6b601`
- Active credential fingerprint `8bae98b6558a9d95e71ab6e9aad503e6` (token sha16 `70a69b584cbbef9c`)
- Against Signal Dev SHA `c8bcd1e…`: sano 200; CMS kill/disabled 503; restore 200
- Snapshot rows for dossier canary: **1** (shadow retained)
- **Augment not enabled**

## Host unit tests

Dual-env cleanup (load `*_FILE` into base, unset FILE dual pairs): five memory files → **38 passed, 4 skipped**; FAIL only coverage gate 26.74% < 84% (not lowered). No candidate code patch this turn.
