# MEMSOL Execution Ledger

> Fuente de verdad de ejecución. Actualizado con evidencia medible en re-verificación.

## Identidad

- Última actualización: 2026-07-31 21:40 Europe/Madrid (re-verificación live 21:36)
- Oracle worktree: `.worktrees/oracle-dev-memsol-smoke` · rama `memsol/oracle-dev-smoke`
- Oracle Dev release activo: **96250a4** (`20260731T192559Z-native-96250a4`)
- Signal `origin/main`: `f934ead` (MEMSOL-02, flags OFF)
- Producción autorizada: **no**

## Gate Oracle Dev · Celery cola `ai` (2026-07-31)

Host: `oracle-dev.opnconsultoria.com` / `159.195.216.33` · env `/etc/opn-oracle-dev` · **no prod** (sin contenedores `opn-oracle-prod-*`).

| Paso | Resultado |
|---|---|
| RO audit | services api/web/worker/beat **active**; Redis PING OK; `/health/ready` database+redis ok |
| Release | `20260731T192559Z-native-96250a4` · SHA **96250a4** |
| Migraciones | head **`20260731_0028`** (0027+0028 ya aplicadas; no re-migrate) |
| Worker `-Q` | `default,signals,**ai**,documents,notifications,maintenance` · inspect ping **pong** |
| Tasks registradas | `oracle.dossier_question.answer`, `oracle.report.custom_brief.plan` → cola **`ai`** |
| Flags | `AI_ENABLED=false` · `AI_MODE=disabled` · `CELERY_TASK_ALWAYS_EAGER=false` · handlers sin LLM de pago |
| Tenant sintético | slug `memsol-celery-smoke` · run_tag **`20260731T193646Z`** · dossier `d72c2384-eefc-4cfc-9a59-d5d83d65a4fe` |

### E2E pregunta durable (re-medida)

| Campo | Valor |
|---|---|
| HTTP | `POST …/messages` **202** (~58 ms accept) |
| job_id | `24696b29-905d-4016-895a-cbc6779203a3` |
| message_id | `abbb9f77-e659-4ff0-8b75-d324017f9d86` |
| queue | **`ai`** |
| terminal | **succeeded** (worker ~15 ms; reload idéntico) |
| persistencia GET | message `status=succeeded` |
| journalctl | `Task oracle.dossier_question.answer[…] received` → `job_succeeded` · `policy_version=disabled` |

### E2E custom brief plan (re-medida)

| Campo | Valor |
|---|---|
| HTTP | `POST …/reports/custom` **202** (~32 ms accept) |
| job_id | `0b6ddf17-135a-48da-a9d4-cba17f859c4d` |
| report_id | `4cf98009-b649-4c85-a0c1-2540b706b37a` |
| terminal job | **succeeded** · queue **`ai`** |
| plan_status | **proposed** (GET detail 200) |
| journalctl | `Task oracle.report.custom_brief.plan[…] received` → `job_succeeded` · `section_count=4` |

### Fault path controlado (re-medida)

| Campo | Valor |
|---|---|
| Permanent fail | job `17591fdb-6094-432b-afe0-c5c17c8f41ee` · bad `message_id` → worker **`PermanentJobError`** · status **`failed`** · queue `ai` |
| Cancel + If-Match | staged job `a9fd2d90-448d-4a4f-828e-5bec11d52304` · `POST /api/v1/jobs/{id}/cancel` + `If-Match: W/"1"` → **202** · status **`cancelled`** |
| Cancel sin If-Match | **428** precondition_required (medido en intento previo) |
| Tenant intacto | dossier sintético sin corrupción; AI flags sin cambiar |

### Evidencia scratch (implementer)

- `memsol_oracle_dev_audit.txt` (RO audit consolidado)
- `memsol_migrations_0027_0028.txt` (head 0028, no-op migrate)
- `memsol_q_create.json` / `memsol_q_terminal.json` / `memsol_q_worker.txt`
- `memsol_brief_create.json` / `memsol_brief_terminal.json` / `memsol_brief_worker.txt`
- `memsol_controlled_fail.txt` · `memsol_e2e_full.json`

## Reconciliación previa (suite local)

| Claim | Resultado |
|---|---|
| Baseline unit MEMSOL | **56 passed** |
| Signal lifecycle | **8 passed** (+ mutación scope) |
| Workers/Celery reg | **11 pass** (+ mutación durable-task) |
| UI vitest Ask/Brief | **5 passed** (post-fix loading) / 7 previos |
| Integration multitenancy+jobs | **46 passed** |
| Integration HTTP MEMSOL | **3 passed** |
| Migrations oracle_test | **20260731_0028 head** |
| Playwright browser | residual (suite no invocada en Dev UI aún) |
| Production | **not deployed** |

## Estado global

| Fase | Estado | Ref | Gate |
|---|---|---|---|
| MEMSOL-00…07 | complete | master history | pass re-checked |
| MEMSOL-02 Signal | complete | main **f934ead** | pass + mutation |
| Workers + Celery register | complete | 9c1860b | pass + mutation |
| UI reload/poll + loading prop | complete | 96250a4 | pass |
| OpenAPI/TS/backfill script | complete | faf95db+ | pass |
| Integration HTTP MEMSOL | complete | a2e19a1 | 3 HTTP pass |
| **Oracle Dev Celery `ai` smoke** | **complete** | release **96250a4** | **pass** (question+brief+cancel) |
| Playwright/a11y full | residual | — | not run |
| MEMSOL-11 prod | prepared | MEMSOL_11_ROLLOUT_PREP.md | **no deploy** |

## Residual explícito

1. Playwright E2E browser (Actividad / Preguntar / Informe libre) — siguiente si entorno UI listo.
2. Full a11y automated scan.
3. Producción: **no** autorizada; flags MEMORY/AI OFF.

## Handoff

- No producción, no `MEMORY_ENGINE_ENABLED`, no secretos reales en evidencia.
- Dev release: `20260731T192559Z-native-96250a4` · SHA `96250a40d7944864de1980b70019a0443bfe7fbb`.
- Previous Dev: `20260731T095958Z-native-eb61173` (rollback vía activate-release).
- Backfill: `uv run python scripts/memsol_backfill_intent_revisions.py --dry-run` con migrator en DB migrada.
