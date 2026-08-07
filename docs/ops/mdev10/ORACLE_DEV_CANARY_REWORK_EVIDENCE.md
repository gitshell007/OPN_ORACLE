# MDEV-10 rework · Oracle Dev canary evidence

- Timezone: Europe/Madrid
- Host: `v2202607388167489673` / `oracle-dev.opnconsultoria.com` / `159.195.216.33`
- Release (unchanged): `20260802T040823Z-native-4b454e1`
- SHA: `4b454e1c88fc678b443a18b1c4f0a905b0630fb2`
- Alembic: `20260802_0032`
- Services: api/web/worker/beat **active**

## 1. Pre-existing production URL connection

Snapshot dir: `/var/backups/opn-oracle-dev/mdev10-rework-20260802T042800Z/`

| Field | Value |
| --- | --- |
| id | `9452d354-3b82-4f3c-ba24-5c678b926669` |
| name | `production` |
| provider | `signal-avanza` |
| base_url | `https://signal.opnconsultoria.com/api/v1/oracle` |
| prior status | `active` |
| **new status** | **`disabled`** (version 2) |
| deps (not deleted) | signal_monitors=6, signals=30, api_credentials=3 |

- Host production **not contacted** and **not mutated**.
- Canary selection under tenant `3b966c2f-…` only sees `signal-dev-mdev10-canary` active with base_url Signal Dev.
- active_prod_url count = **0**.

## 2. Canary IntegrationConnection

| Field | Value |
| --- | --- |
| id | `ffcf1c40-191b-48e5-bc92-46cb3da6b601` |
| name | `signal-dev-mdev10-canary` |
| provider | `signal-avanza` (normalized from `signal` so resolver contract applies) |
| base_url | `https://signal-dev.opnconsultoria.com` |
| status | active |
| metadata.mode | shadow |
| credential | AES-256-GCM active sealed; token_sha16=`70a69b584cbbef9c`; never printed |

## 3. Shadow smoke

Synthetic strategic dossier + DMP mode=shadow for dossier `726bfb3d-090e-470b-b343-596cf5604ed6`.

HttpMemoryContextAdapter effective_mode=shadow:

- effective host **only** `signal-dev.opnconsultoria.com`
- watermark `wm_8dea1a66587dcdee`
- `items_for_prompt` length **0**
- coverage_manifest persisted
- `memory_retrieval_snapshots` count for dossier = **1**
- secret remains sealed post-call

## 4. Augment

**NOT activated.** Reason: extraction/facts empty (no local model), CMS kill-switch not wired to API, residual MDEV-08 durable debts. Left **shadow**.

## 5. Host unit 5 failures classification

Reproduced subset against release tree with host env loaded:

```text
pytest tests/test_app.py::test_file_backed_secrets_are_loaded_without_changing_plain_settings
       tests/test_app.py::test_file_backed_secret_rejects_conflicting_inline_value
       tests/test_app.py::test_create_app_tolerates_local_storage_chmod_failure
       tests/test_app.py::test_create_app_tolerates_uncreatable_local_storage_root
       tests/test_documents.py::test_additional_fail_closed_parser_scanner_and_storage_branches
→ 3 failed, 2 passed
```

Failures:

1. `test_file_backed_secrets_are_loaded_without_changing_plain_settings` — `ConfigError: REDIS_URL y REDIS_URL_FILE no pueden configurarse a la vez` (**host env dual-source pollution**)
2. `test_create_app_tolerates_local_storage_chmod_failure` — `SECRET_KEY y SECRET_KEY_FILE no pueden configurarse a la vez` (**env harness**)
3. `test_create_app_tolerates_uncreatable_local_storage_root` — same SECRET_KEY dual (**env harness**)

Passed: conflicting inline reject; documents additional fail-closed.

**Classification: environment/harness**, not candidate defect. CI run `30731011696`: 999 passed, FAIL only coverage 81.89% < 84%. No coverage gate lowered; no candidate code change.

## 6. OpenRouter / cloud

- SIGNAL_AI allowlist exclusive `signal-dev.opnconsultoria.com`
- No OpenRouter/paid smoke from Oracle this turn
- Canary Signal side: zero openrouter usage attempts observed

## 7. Rollback

- Re-enable production URL connection only if explicitly authorized (currently disabled, not deleted)
- Canary: set DMP mode=disabled; IC status=disabled
- Release pin remains `20260802T040823Z-native-4b454e1`
