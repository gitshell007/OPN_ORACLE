# MEMSOL Execution Ledger

> Fuente de verdad de ejecución. Actualizado con evidencia medible.

## Identidad

- Última actualización: 2026-07-31 20:16 Europe/Madrid
- Oracle worktree: `.worktrees/memsol` · `memsol/execution`
- Oracle `origin/master`: **9c1860b** durable-task registration (9c1860b6e8af07091519e16536e205a90fb6dc64)
- Signal `origin/main`: `f934ead` (MEMSOL-02 CAS/fencing, flags OFF)
- Producción autorizada: **no**

## Reconciliación (verificada)

| Claim previo | Evidencia re-ejecutada | Resultado |
|---|---|---|
| geography / intent / activity / conversations / brief / memory context | `pytest` 43 baseline + 49 combined | **pass** |
| Signal lifecycle 8 tests | worktree memsol-02 + memsol-02-on-main | **pass** |
| Workers Q&A + brief | handlers reales + tests | **pass** (this residual) |
| Signal en main | cherry-pick 86c1f74 → main f934ead | **pass** |
| Postgres integration suite | role `oracle` missing | **blocked_env** |
| Backfill counts live | same DB | **blocked_env** (script + pure tests) |
| Playwright UAT | not run | **residual documented** |

## Estado global

| Fase | Estado | SHA / ref | Gate |
|---|---|---|---|
| MEMSOL-00…01 | complete | e2ca757 / 50a3b8a | pass (re-checked) |
| MEMSOL-02 | complete | Signal main **f934ead** | pass + mutation scope |
| MEMSOL-03…04 | complete | cfe88d1 / 04bdb8c | pass |
| MEMSOL-05…07 | complete | 89e2e3d + workers 5bee9cc | pass |
| Workers residual | complete | process_* + HANDLERS | pass |
| UI/OpenAPI/client/backfill script | complete | faf95db | UI unit pass; OpenAPI regenerated |
| Integration full / Playwright | blocked_env / residual | evidence scratch | documented |
| MEMSOL-11 | prepared | docs/implementation/memsol/MEMSOL_11_ROLLOUT_PREP.md | **no deploy** |

## Residual explícito restante

1. Ejecutar `memsol_backfill_intent_revisions.py --dry-run/--apply` con `TEST_DATABASE_URL` real y pegar counts al ledger.
2. `ORACLE_RUN_INTEGRATION=1` suite completa + Playwright cuando haya Postgres/Redis/CI.
3. Worker Celery e2e con broker real (handlers unitarios ya existen).
4. UI polish a11y/Playwright.

## Scratch evidence

- `memsol_git.txt`, `memsol_baseline_tests.txt`, `memsol_signal_02.txt`
- `memsol_workers.txt`, `memsol_ui_tests.txt`, `memsol_openapi.txt`
- `memsol_backfill.txt`, `memsol_integration_uat.txt`

## Handoff

- No producción. Kill switches memory OFF.
- Signal main ya contiene MEMSOL-02; no activar MEMORY_ENGINE_ENABLED sin autorización.

## Skeptic fixes (2026-07-31 20:23 Europe/Madrid)

- Ask UI: sessionStorage guarda conversationId+messageId; on mount GET message y reanuda poll.
- Brief UI: customBriefs.get + poll plan_status; GET `/reports/custom/{report_id}`; reload rehidrata.
- Routes: commit + `publish_job(job)` para pregunta y brief (HANDLERS cableados a Celery).
- Tests: ask reload (2), brief create/poll/reload/error (3), route publish structural (1).
- Evidence: `{SCRATCH}/memsol_ui_reload_tests.txt`, `memsol_publish_tests.txt`.

## Celery durable-task registration (skeptic 2026-07-31)

- Bug: HANDLERS + TASK_QUEUES had `oracle.dossier_question.answer` and
  `oracle.report.custom_brief.plan` but no `_durable_task()` → celery.tasks KeyError
  on publish_claimed_job → jobs stuck `publish_pending`.
- Fix: register both via `_durable_task`; TASK_ROUTES `oracle.dossier_question.*` → ai.
- Tests: `test_memsol_celery_registration.py` asserts job_type in celery.tasks and
  publish_claimed_job.apply_async; mutation removing _durable_task lines fails registration test.
