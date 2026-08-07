# MDEV-10 · Oracle Dev deploy evidence

**Timezone:** Europe/Madrid  
**Deploy window (observed):** `2026-08-02T06:07` … `2026-08-02T06:13`  
**Verdict for this host:** `deployed_with_debt` (release+migrations OK; durable smoke/augment not completed)

## Target guard

| Check | Evidence |
| --- | --- |
| Hostname | `v2202607388167489673` / `v2202607388167489673.goodsrv.de` |
| FQDN public | `oracle-dev.opnconsultoria.com` |
| IP | `159.195.216.33` (≠ prod `167.233.73.138`) |
| DNS A | oracle-dev → `159.195.216.33`; oracle prod → `167.233.73.138` |
| TLS | LE CN=`oracle-dev.opnconsultoria.com` |
| OS | Debian 13 trixie, kernel 6.12.96 |
| Services pre | api/web/worker/beat/nginx/postgres/redis **active** |
| APP_ENV note | `oracle.env` has `APP_ENV=production` **label** on Dev host — host/IP/FQDN remain Dev; no prod mutation |

## Preflight / backup / restore

| Item | Result |
| --- | --- |
| Pre release | `20260731T192559Z-native-96250a4` |
| Pre SHA | `96250a40d7944864de1980b70019a0443bfe7fbb` |
| Pre alembic | `20260731_0028` |
| Backup | `/var/backups/opn-oracle-dev/pg/opn_oracle_dev_20260802T040755Z.dump` (3.6M) |
| SHA-256 | `a20e3fe75b9f5635aa8f7cddfc4980b431860d8939ee4f5b9b659f2dfd6c4c89` |
| Restore verify | temp DB `opn_oracle_dev_mdev10_restore_test` → version `20260731_0028`, reports=39; **pg_restore_rc=0**; dropped |
| Evidence dir | `/var/backups/opn-oracle-dev/mdev10-20260802T040755Z/` |
| Config bak | `oracle.env.bak` (mode 600; not shipped) + redacted copy |

## Deploy mechanism (MDEV-00)

1. `ORACLE_ALLOW_OFF_BRANCH_SHA=1` (candidate is on `mdev/08-fourth-attempt`, not `oracle-dev`)  
2. `/opt/src/oracle-build/build-release.sh 4b454e1c88fc678b443a18b1c4f0a905b0630fb2`  
3. Release id: **`20260802T040823Z-native-4b454e1`**  
4. `/opt/src/oracle-build/activate-release.sh 20260802T040823Z-native-4b454e1` → symlink + migrate + restart  

Build notes: frontend lint warnings only; unit tests 5 failed / 263 passed on host unit run — materialization continued (`ORACLE_REQUIRE_API_UNIT=0` default). **Not counted as CI green.**

## Post deploy

| Item | Value |
| --- | --- |
| CURRENT_RELEASE | `20260802T040823Z-native-4b454e1` |
| RELEASE_GIT_SHA | **`4b454e1c88fc678b443a18b1c4f0a905b0630fb2`** |
| Alembic | **`20260802_0032`** head (`report_ai_usage_bindings` applied) |
| Migrations applied this turn | `0029` → `0030` → `0031` → **`0032`** |
| health/ready | `{"status":"ok","dependencies":{"database":{"status":"ok"},"redis":{"status":"ok"}}}` |
| Services | api/web/worker/beat **active** |
| Worker queues | `default,signals,ai,documents,notifications,maintenance` |

### Host gate / SSRF allowlist

Observed `oracle.env` (non-secret):

```
SIGNAL_AI_BASE_URL=https://signal-dev.opnconsultoria.com
SIGNAL_AI_ALLOWED_HOSTS=signal-dev.opnconsultoria.com
SIGNAL_AVANZA_ENABLED=false
SIGNAL_AVANZA_MODE=mock
```

Allowlist exclusive **signal-dev**. DNS from host: signal-dev=`159.195.216.184`, signal prod=`178.105.143.191` (prod not targeted by AI allowlist).

### IntegrationConnection canary

| Field | Value |
| --- | --- |
| id | `ffcf1c40-191b-48e5-bc92-46cb3da6b601` |
| tenant | `memsol-celery-smoke` / `3b966c2f-4c54-4269-aea9-3f0f6887f6c3` (existing synthetic smoke tenant) |
| provider/name | `signal` / `signal-dev-mdev10-canary` |
| base_url | `https://signal-dev.opnconsultoria.com` |
| adapter_mode | `http` |
| status | `active` |
| metadata | mode=`shadow`, consumer=`opn-oracle-dev`, external_tenant=`mdev10-canary-tenant` |
| api_token | sealed AES-GCM in `api_credentials` fp `8bae98b6558a9d95e71ab6e9aad503e6` ver=2 active |
| Plain secrets | transferred one-time from Signal → shredded after bind |

**Pre-existing** connection (untouched): `signal-avanza` / name `production` on tenant OPN Consultoría pointing at `signal.opnconsultoria.com` — **not modified**, not used for MDEV-10 canary. Documented as residual risk for future cleanup (out of scope this turn beyond non-use).

### Table presence post-0032

- `report_ai_usage_bindings` exists (owner `oracle_migrator`)  
- `dossier_memory_profiles`, `memory_retrieval_snapshots` present from 0029 chain  

## Smoke gaps (honest)

| Required | Status |
| --- | --- |
| Shadow snapshot/coverage/watermark real | **NOT executed** (Signal engine OFF + E2E-CELERY debt) |
| accept→writer RT-09→review RT-10→ready | **NOT executed** |
| Kill switch usage delta zero | **NOT executed** |
| Canary → augment | **NOT attempted** (required gates not green) |
| Generation/report durable | remains **blocked** under debt |

## Rollback path

1. Disable canary connection / do not call Signal  
2. `ln -sfn /opt/opn-oracle/releases/20260731T192559Z-native-96250a4 /opt/opn-oracle/current`  
3. restart api/web/worker/beat  
4. Keep additive tables (0032) unless explicit restore from `opn_oracle_dev_20260802T040755Z.dump` to a new DB  
5. Restore `oracle.env` from timestamped bak if needed  

## Debt

- All prior `DEFERRED_BLOCKERS` + MDEV-08 finals  
- `MDEV10-SMOKE-ORACLE-INCOMPLETE`  
- `MDEV10-BUILD-UNIT-5FAIL` (host unit subset during build)  
- `MDEV10-PREEXISTING-SIGNAL-AVANZA-PROD-URL` (not mutated)  
- `MDEV10-OFF-BRANCH-SHA` (deployed with `ORACLE_ALLOW_OFF_BRANCH_SHA=1`)  
