# MEMSOL Execution Ledger

> Fuente de verdad de ejecución. Actualizado con evidencia medible en re-verificación.

## Identidad

- Última actualización: 2026-07-31 21:40 Europe/Madrid
- Oracle worktree: `.worktrees/memsol` · `memsol/execution` (+ canal `oracle-dev` smoke)
- Oracle `origin/oracle-dev` tip activo en Dev: **96250a4**
- Signal `origin/main`: `f934ead` (MEMSOL-02, flags OFF)
- Producción autorizada: **no**

## Gate Oracle Dev · Celery cola `ai` (2026-07-31)

Host: `oracle-dev.opnconsultoria.com` / `v2202607388167489673` · env `/etc/opn-oracle-dev` · **no prod**.

| Paso | Resultado |
|---|---|
| Pre-audit release | `eb61173` · alembic **0026** · MEMSOL tasks **ausentes** |
| Build-release | `20260731T192559Z-native-96250a4` (tras fix `loading` AsyncActionButton) |
| Activate + migrate | **0026→0027→0028 head** · services api/web/worker/beat **active** |
| Tasks registradas | `oracle.dossier_question.answer`, `oracle.report.custom_brief.plan` (cola `ai`) |
| Flags | `AI_ENABLED=false` · `AI_MODE=disabled` · handlers deterministas OK |
| Tenant sintético | slug `memsol-celery-smoke` · dossier `6b3b8d9d-…` |

### E2E pregunta durable

| Campo | Valor |
|---|---|
| HTTP | `POST …/messages` **202** |
| job_id | `e866fc53-80f6-4d9c-b4e0-a0bfd9488113` |
| message_id | `ccd5b6ba-da84-4f7e-87ff-b229ad767f89` |
| queue | `ai` |
| terminal | **succeeded** (~20 ms worker) |
| persistencia GET | message `status=succeeded` + `answer_payload` (policy=disabled) |
| journalctl | `Task oracle.dossier_question.answer[…] received` → `succeeded` |

### E2E custom brief plan

| Campo | Valor |
|---|---|
| HTTP | `POST …/reports/custom` **202** |
| job_id | `9c48b575-7e6e-4e42-b3dd-2dcc98847a50` |
| report_id | `f4948f6d-68c4-4e4e-910a-0f5f70944adf` |
| terminal job | **succeeded** |
| plan_status | **proposed** · `proposed_plan.version=custom_brief_plan.v1` |
| journalctl | `Task oracle.report.custom_brief.plan[…] received` → `succeeded` |

### Fault path controlado

| Campo | Valor |
|---|---|
| job_id | `dfed02aa-63fe-4991-8c05-75b267454a63` (enqueue `publish=False`, status `queued`) |
| cancel | `POST /jobs/{id}/cancel` + `If-Match: W/"1"` → **202** · status **cancelled** |
| retry | `POST …/retry` → **409** «El job no admite reintento.» (comportamiento API medido) |
| race note | cancel sin If-Match → 428; jobs ya en worker (~20 ms) pueden terminar antes del cancel en vivo |

### Evidencia local (scratch / host)

- `memsol_celery_smoke_result.json`, `memsol_celery_smoke.log`
- `memsol_fault_smoke.json`
- `memsol_worker_tasks.log` (journalctl redacted task names)
- `oracle_dev_activate.txt`, `oracle_dev_build2.txt`

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
