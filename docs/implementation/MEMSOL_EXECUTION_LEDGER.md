# MEMSOL Execution Ledger

> Fuente de verdad de ejecución. Actualizado con evidencia medible en re-verificación.

## Identidad

- Última actualización: 2026-07-31 20:35 Europe/Madrid
- Oracle worktree: `.worktrees/memsol` · `memsol/execution`
- Oracle origin/master tip: **a2e19a1**
- Signal `origin/main`: `f934ead` (MEMSOL-02, flags OFF)
- Producción autorizada: **no**

## Reconciliación re-ejecutada (esta sesión)

| Claim | Comando medido | Resultado |
|---|---|---|
| Oracle HEAD == origin/master | git rev-parse | **ea9a9e3** (antes de este commit) |
| Baseline unit MEMSOL | pytest 10 test modules | **56 passed** |
| Signal lifecycle on main worktree | pytest lifecycle | **8 passed** |
| Scope mutation | tenant optional | **test fails** then restore **8 pass** |
| Workers + celery reg | pytest workers/celery/route | **11 pass**; durable-task mutation **fails** then restore |
| UI Actividad/ask/brief | vitest 3 files | **7 passed** |
| OpenAPI paths | openapi.json assert | activity, conversations, custom, intent **OK** |
| Backfill dry-run live | script on oracle_test | **measured zeros** (empty DB post-migrate to 0028) |
| Migrations | flask db upgrade oracle_test | **20260731_0028 head** |
| Integration multitenancy+jobs | pytest | **46 passed** |
| Integration MEMSOL HTTP | test_integration_memsol_http | **3 passed** (intent/activity/ask/brief) |
| Playwright | not run | residual env (no e2e suite invoked) |
| Production | — | **not deployed** |

## Estado global

| Fase | Estado | Ref | Gate |
|---|---|---|---|
| MEMSOL-00…07 | complete | master history | pass re-checked |
| MEMSOL-02 Signal | complete | main **f934ead** | pass + mutation |
| Workers + Celery register | complete | 9c1860b | pass + mutation |
| UI reload/poll | complete | c887ffb | pass |
| OpenAPI/TS/backfill script | complete | faf95db+ | pass; backfill counts measured 0/0 |
| Integration HTTP MEMSOL | complete | this commit | 3 HTTP pass |
| Integration broader | complete | multitenancy+jobs 46 | pass |
| Playwright/a11y full | residual | documented | blocked_env tool/suite not invoked |
| MEMSOL-11 | prepared | MEMSOL_11_ROLLOUT_PREP.md | **no deploy** |

## Residual explícito

1. Playwright E2E browser suite (not run this session).
2. Full a11y automated scan (not run).
3. Live Celery worker process + Redis broker e2e outside unit publish_claimed_job (handlers+registration proven).

## Scratch evidence files

- memsol_git.txt, memsol_baseline_tests.txt, memsol_signal_02.txt
- memsol_workers.txt, memsol_ui_openapi_backfill.txt, memsol_backfill.txt/json
- memsol_integration_uat.txt, memsol_http_integration.txt

## Handoff

- No producción, no MEMORY_ENGINE_ENABLED, no secretos reales.
- Backfill: `uv run python scripts/memsol_backfill_intent_revisions.py --dry-run` with DATABASE_URL=oracle_app on migrated DB.
