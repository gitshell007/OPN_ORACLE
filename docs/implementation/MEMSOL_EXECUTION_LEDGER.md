# MEMSOL Execution Ledger

> Fuente de verdad de ejecución del programa Memoria Sol. Se actualiza en cada fase.
> La conversación del agente no es autoridad.

## Identidad de ejecución

- Inicio Europe/Madrid: 2026-07-31 19:21:27 Europe/Madrid
- Última actualización: 2026-07-31 ~19:27 Europe/Madrid
- Agente/sesión: Grok Build · Memoria Sol master goal
- Oracle repo/rama/SHA inicial: `master@35b2e94` · `oracle-dev@eb61173` · worktree `memsol/execution`
- Signal repo/rama/SHA inicial: `main@60a5782` · `signal-dev@06fbdd6` (sin cambios de código)
- Prompt pack: `SignalV2/memoria_sol`
- Producción autorizada: `no`

## Estado global

| Fase | Estado | Oracle SHA | Signal SHA | Gate | Evidencia/riesgo |
|---|---|---|---|---|---|
| MEMSOL-00 | complete | 50a3b8a | 06fbdd6 | pass | matrix + geo global + tests/mutación |
| MEMSOL-01 | complete | pending_push | 06fbdd6 | pass | ADR-0009 + schemas |
| MEMSOL-02 | complete | n/a | 86c1f74 | pass | CAS/fencing branch memsol/02 |
| MEMSOL-03 | complete | cfe88d1 | 06fbdd6 | pass | IntentRevision API |
| MEMSOL-04 | complete | pending | 86c1f74 | pass | activity read model |
| MEMSOL-05 | pending | | | | |
| MEMSOL-06 | pending | | | | |
| MEMSOL-07 | pending | | | | |
| MEMSOL-08 | pending | | | | |
| MEMSOL-09 | pending | | | | |
| MEMSOL-10 | pending | | | | |
| MEMSOL-11 | pending | | | | solo preparación |

## Fase cerrada · MEMSOL-00

- Objetivo: auditoría, matriz, reconciliación master←oracle-dev, geografía global, prefill no durable.
- Merge-tree: 0 conflictos; merge ort de 26 ficheros.
- Correcciones: `_geography_codes` ISO-2 global; UI presets + ISO libre; sessionStorage efímero documentado.
- Artefactos: ledger, `MEMSOL_CONTRACT_MATRIX_2026-07-31.md`, D-088, STATUS, OPEN_QUESTIONS MEMSOL.
- Tests: `pytest tests/test_geography_global.py --no-cov` → 3 passed; mutación UE-only → 2 failed; vitest selector → 5 passed; ruff clean.
- Signal: sin código; orden de integración documentado; WIP ajeno no tocado.
- WIP Oracle principal (market_competitor_discovery etc.) **no** stageado.

## Cambios realizados

| Bloque | Archivos/migración | Por qué | Check inmediato | Resultado |
|---|---|---|---|---|
| Merge oracle-dev | 26 files market/docs | reconciliación | merge ort | ok |
| Geo global | service.py, UI, CSS, tests | eliminar UE-27 | pytest+vitest+mutación | ok |
| Matriz/ledger | docs/implementation/* | protocolo | revisión | ok |
| D-088 / STATUS / OQ | docs | trazabilidad | — | ok |

## Comandos y pruebas

| Comando | Entorno | Resultado |
|---|---|---|
| `git merge oracle-dev` | worktree memsol | success |
| `uv run pytest tests/test_geography_global.py --no-cov` | apps/api | 3 passed |
| mutación UE-only + pytest | apps/api | 2 failed, 1 passed |
| restauración + pytest | apps/api | 3 passed |
| `vitest eu-country-multiselect` | root | 5 passed |
| `ruff check/format` service+test | apps/api | clean |
| suite integración completa | no | riesgo: no DB/CI en agente; matrix documenta |
| Signal pytest | no | sin cambios Signal |

## Mutaciones

| Comportamiento mutado | Test que cayó | Restaurado | Resultado final |
|---|---|---|---|
| `_geography_codes` vuelve a UE-only | `test_geography_accepts_eu_and_non_eu…`, `test_geography_rejects…` | sí | 3 passed |

## Decisiones

| ID | Decisión | Documento |
|---|---|---|
| M00-D1 | Merge completo oracle-dev (no cherry-pick) | STATUS |
| M00-D2 | Geografía ISO-2 global | D-088 |
| M00-D3 | sessionStorage efímero | matrix + dialog |
| M00-D4 | Signal solo documentado en 00 | matrix |
| M00-D5 | Worktree aislado | ledger |

## Bloqueos

Ninguno global. CI remoto del SHA y suite integración completa quedan como riesgo de entorno, no de diseño.

## Handoff → MEMSOL-01

- Releer: ledger, matrix, plan producto, D-015/D-088, OPEN_QUESTIONS MEMSOL.
- Entregar ADR + schemas de `DossierIntentRevision`, requirements, offerings, coverage_manifest, state machines.
- No activar `opn_memory`; no UI de chat/informes nuevos.
- Congelar inputs: Oracle post-MEMSOL-00 SHA; Signal `06fbdd6` inventario.


## Fase cerrada · MEMSOL-01

- ADR-0009 + D-089, schemas JSON (7), migration matrix, OpenAPI proposal.
- Sin código runtime ni migraciones Alembic.
- Gate: validación JSON + diff --check + coherencia con modelos existentes (BackgroundJob statuses reutilizados).
- Handoff MEMSOL-02: Signal isolation/CAS/flags; no editar OpenAPI Oracle.
- Handoff MEMSOL-03: migraciones IntentRevision contra ADR-0009; worktree Oracle.
