# MEMSOL Execution Ledger

> Fuente de verdad de ejecución. Solo claims con evidencia en el scratch de la sesión implementer.

## Identidad

- Última actualización: 2026-07-31 21:48 Europe/Madrid
- Re-verificación live run_tag: **`20260731T194745Z`**
- Oracle worktrees: `.worktrees/memsol` · `.worktrees/oracle-dev-memsol-smoke`
- Oracle Dev release activo: **`96250a4`** (`20260731T192559Z-native-96250a4`)
- Signal `origin/main`: `f934ead` (MEMSOL-02, flags OFF)
- Producción autorizada: **no** · **no lista**

## Gate Oracle Dev · Celery cola `ai` (re-medida 20260731T194745Z)

Host: `oracle-dev.opnconsultoria.com` / `v2202607388167489673` · env `/etc/opn-oracle-dev` · **no prod**.

| Paso | Resultado | Evidencia scratch |
|---|---|---|
| RO audit | release `96250a4`; api/web/worker/beat **active**; live+ready 200; Redis/DB ok | `memsol_oracle_dev_audit.txt` |
| Migraciones | head **`20260731_0028`** (0027+0028 aplicadas) | `memsol_migrations_0027_0028.txt` |
| Worker `-Q` | incluye **`ai`**; tasks `oracle.dossier_question.answer` + `oracle.report.custom_brief.plan` | audit + `memsol_worker_tasks.log` |
| Flags | `AI_ENABLED=false` · `AI_MODE=disabled` · `CELERY_TASK_ALWAYS_EAGER=false` | audit |
| Tenant sintético | slug `memsol-celery-smoke` · dossier `37179514-a8cf-4ce8-8ffb-55cc1117335f` | `memsol_e2e_full.json` |

### E2E pregunta durable

| Campo | Valor |
|---|---|
| HTTP | `POST …/messages` **202** |
| job_id | `c6293b76-e6af-4f22-ba28-65f8d08d4ec5` |
| message_id | `dedafe5c-e18a-4b11-b8f8-067b226ad478` |
| queue | **`ai`** |
| terminal | **succeeded** |
| GET message | **200** · `status=succeeded` · `answer_payload.policy_version=disabled` |
| journalctl | `Task oracle.dossier_question.answer[…] received` → `succeeded` · message_id `dedafe5c-…` |
| evidencia | `memsol_q_create.json`, `memsol_q_terminal.json`, `http_enqueue_question.json`, `memsol_q_worker.txt` |

### E2E custom brief plan

| Campo | Valor |
|---|---|
| HTTP | `POST …/reports/custom` **202** |
| job_id | `9c538ca6-c63e-46fe-b76b-8c82e64b44af` |
| report_id | `abb6be7c-8250-45de-9ec6-737b292607d9` |
| queue | **`ai`** |
| terminal job | **succeeded** |
| plan_status | **proposed** · `custom_brief_plan.v1` |
| journalctl | `Task oracle.report.custom_brief.plan[…] received` → `succeeded` · report_id `abb6be7c-…` |
| evidencia | `memsol_brief_create.json`, `memsol_brief_terminal.json`, `http_create_brief.json`, `memsol_brief_worker.txt` |

### Fault path controlado (con transcript HTTP)

| Campo | Valor | HTTP evidence |
|---|---|---|
| Permanent fail | job `ad6d0d67-f8b2-4317-8633-d11fe6d754d5` · publish=True · message_id inexistente → **failed** · `error_code=permanent_failure` · queue `ai` | `http_get_permanent_fail_job.json`, `memsol_fault_permanent.json` |
| Worker fail | `PermanentJobError: permanent_failure` + `job_failed` | `memsol_worker_tasks.log` |
| Cancel sin If-Match | job staged `edbee997-372e-42ef-a80e-4bede252fc06` · **HTTP 428** `precondition_required` | `http_cancel_without_if_match.json` |
| Cancel + If-Match `W/"1"` | **HTTP 202** · status **`cancelled`** · `cancel_requested=true` | `http_cancel_with_if_match.json`, `memsol_fault_smoke.json` |
| Retry cancelado | **HTTP 409** `job_not_retryable` «El job no admite reintento.» | `http_retry_cancelled.json` |
| Paquete | resumen + transcript completo | `memsol_controlled_fail.txt`, `memsol_e2e_full.json`, `memsol_http_transcript.json`, `memsol_fault_smoke.log` |

**Nota de honestidad:** un smoke anterior marcó `fault_ok=true` tras cancel **428** (sin If-Match) y un job en carrera que terminó `succeeded`. Eso **no** cuenta como fault path. Esta re-medida usa cancel 428/202 + permanent_failure con transcript HTTP.

### Evidencia scratch implementer (presente)

- `memsol_oracle_dev_audit.txt`
- `memsol_migrations_0027_0028.txt`
- `memsol_e2e_full.json` · `memsol_http_transcript.json` · `memsol_fault_smoke.log`
- `memsol_q_create.json` · `memsol_q_terminal.json` · `memsol_q_worker.txt`
- `memsol_brief_create.json` · `memsol_brief_terminal.json` · `memsol_brief_worker.txt`
- `memsol_fault_permanent.json` · `memsol_fault_smoke.json` · `memsol_controlled_fail.txt`
- `http_enqueue_question.json` · `http_create_brief.json`
- `http_cancel_without_if_match.json` · `http_cancel_with_if_match.json` · `http_retry_cancelled.json` · `http_get_permanent_fail_job.json`
- `memsol_worker_tasks.log`
- `ui_vitest_activity_ask_brief.txt` (**7 passed**: activity 2 + ask 2 + brief 3)
- `tests/e2e/memsol-dossier-tabs.spec.ts` · `memsol_playwright_memsol.txt` · `memsol_playwright_assertions.txt` · `memsol_playwright_a11y.txt` (**3 passed** desktop)

## Gate Playwright MEMSOL tabs (2026-07-31 · E2E local auth stack)

| Check | Resultado |
|---|---|
| Spec | `tests/e2e/memsol-dossier-tabs.spec.ts` |
| Entorno | `scripts/run-auth-e2e-api.sh` + Next :3000 · seed `owner@`/`viewer@oracle-e2e.test` · `APP_ENV=test` → Celery **eager** · AI disabled |
| Actividad | load + empty (GET fulfill) + error UUID + axe AA |
| Preguntar | POST **202** → eager `succeeded` → reload + axe; cancel/retry **no** en UI (residual) |
| Informe libre | POST **202** → plan **proposed** → reload + error POST abort + axe |
| Permiso negativo | viewer sin `ai.execute` → **Acceso restringido** en `/ask` |
| Tenant negativo | UUID ajeno → **Actividad no disponible** sin leak |
| Consola | sin pageerror; console limpia (filtro HMR/abort) |
| Comando medido | `npx playwright test tests/e2e/memsol-dossier-tabs.spec.ts --project=desktop` → **3 passed (27.4s)** |

## Backfill dry-run (Oracle Dev `opn_oracle_dev` · 2026-07-31)

Comando: `scripts/memsol_backfill_intent_revisions.py --dry-run` (migrator URL, no apply).

| Métrica | Valor medido |
|---|---|
| strategic_dossiers | **16** |
| with_nonempty_profile_config | **0** |
| dossier_intent_revisions | **0** |
| would_create | **0** |
| skipped_empty_profile | **16** |
| psql crosscheck | dossiers=16 · revisions=0 · with_profile=0 |

Evidencia: `memsol_backfill_dry_run.json` · ceros son conteos de consulta, no inventados.

## Suite local previa (no re-ejecutada en este tip)

| Claim | Resultado (sesión anterior documentada) |
|---|---|
| Baseline unit MEMSOL | 56 passed (sesión previa) |
| Signal lifecycle | 8 passed (sesión previa) |
| Integration HTTP MEMSOL | 3 passed (sesión previa) |
| Integration multitenancy+jobs | 46 passed (sesión previa) |

## Estado global

| Fase | Estado | Ref | Gate |
|---|---|---|---|
| MEMSOL-00…07 | complete | master history | pass |
| MEMSOL-02 Signal | complete | main **f934ead** | pass |
| Workers + Celery register | complete | 9c1860b | pass |
| UI loading/poll fix | complete | 96250a4 | pass |
| **Oracle Dev Celery `ai` smoke** | **complete** | run **20260731T194745Z** / release **96250a4** | **pass** |
| UI vitest Actividad/Ask/Brief | complete | **7 passed** | pass (component) |
| **Playwright/a11y MEMSOL tabs** | **complete** | `memsol-dossier-tabs.spec.ts` | **3 passed** desktop |
| MEMSOL-11 prod | prepared | MEMSOL_11_ROLLOUT_PREP.md | **no deploy** · **not ready** |

## Gate UI cancel/retry Preguntar + Informe libre (2026-07-31)

| Check | Resultado |
|---|---|
| Wiring | `JobProgress allowActions` en `dossier-ask-section` + `dossier-custom-brief-section` |
| API | `POST /api/v1/jobs/{id}/cancel\|retry` + If-Match (sin rutas nuevas) |
| Unit UI | vitest ask+brief+job-progress **12 passed** (`memsol_cancel_retry_unit.txt`) |
| Unit lifecycle | `tests/test_memsol_job_controls.py` **5 passed** (`memsol_cancel_retry_http.txt`) |
| Playwright | `memsol-dossier-tabs.spec.ts` **4 passed** incl. Cancelar/Reintentar + historial |
| Worker real | smoke Dev previo (run_tag 20260731T194745Z) sigue como evidencia independiente |
| Signal pilot prep | `MEMSOL_SIGNAL_PILOT_PREP.md` + `signal_pilot.env.example` · flags **OFF** · no activado |

## Residual explícito

1. Matriz Playwright **mobile** de tabs MEMSOL omitida a propósito.
2. Cancel en E2E eager usa stub de estado de job para ventana de click; lifecycle real validado en unit `request_cancel`/`prepare_retry` + smoke Dev worker.
3. Producción: **no** autorizada; flags MEMORY/AI OFF; piloto Signal **no** activado; **no declarar lista**.

## Handoff

- No producción, no `MEMORY_ENGINE_ENABLED`, no secretos en evidencia.
- Dev release: `20260731T192559Z-native-96250a4` · SHA `96250a40d7944864de1980b70019a0443bfe7fbb`.
- Rollback Dev: activate previous `20260731T095958Z-native-eb61173`.
