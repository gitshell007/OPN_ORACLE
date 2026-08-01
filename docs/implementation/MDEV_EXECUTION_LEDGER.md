# MDEV execution ledger

## Identidad

- Programa: `MEMORIA_DEV_V2`
- Oracle Dev: `https://oracle-dev.opnconsultoria.com`
- Signal Dev: `https://signal-dev.opnconsultoria.com`
- Producción: `OUT_OF_SCOPE`
- Pack version: `2026-08-01.4`
- Pack `content_set_sha256`: `687505b44447c625aae8c4f5c23d01841ac6bc58bc29eac5d84d4a7d65ada164`
- Integridad revalidada en MDEV-00: sí — 27/27 + content_set MATCH; mutación en copia temporal → `BLOCKED_PACK_INTEGRITY`; canónico revalidado MATCH
- Roadmap idea: `ORC-MEM-001` (status `approved`)
- Informe bilateral: `docs/implementation/MDEV_00_BASELINE_BILATERAL.md`
- Evidencia durable: `docs/implementation/evidence/mdev-00/`
- **Codex decision MDEV-00: PASS MDEV-00** (autoriza MDEV-01)
- SHA master con MDEV-00: `a834034396bc129f08a6997b3af27a87a33ec263`
- PR#7 + CI `30706386596` registrados
- Contrato memory.v1 bundle: `docs/contracts/memory_v1/` content_set `792f267db0ac33277d74e019fafb30844db0337b1ef4e62cf0457bbfa7f6ff91`
- Riesgos abiertos heredados: **NO_ROLLBACK**, beat drift (no resueltos en MDEV-01)
- `APPROVED_EXTERNAL_SPEND` / `APPROVED_CLOUD_DATA_POLICY`: vacíos
- MDEV-01 content Oracle tip pre-merge: `5c18b92`; merge master `407c05f`
- MDEV-01 content Signal: `e6fae27`; merge main `519740e`
- Oracle CI MDEV-01: https://github.com/gitshell007/OPN_ORACLE/actions/runs/30709333094

### Commits e integración (rellenar al cerrar push/PR)

| Rol | Valor |
|---|---|
| Rama de trabajo rework | `mdev/00-baseline-rework` |
| Commit de contenido (docs/ledger/evidence) | `0f06376150da7692746cc596f1dd03bbf067605b` |
| Tip de la rama tras push | `0f06376150da7692746cc596f1dd03bbf067605b` |
| SHA final integrado en `origin/master` | `a834034396bc129f08a6997b3af27a87a33ec263` |
| PR | [#6](https://github.com/gitshell007/OPN_ORACLE/pull/6) |
| CI run MDEV-00 | [30705985882](https://github.com/gitshell007/OPN_ORACLE/actions/runs/30705985882) (all SUCCESS) |
| Rama histórica (no reescribir) | `mdev/00-baseline-ledger` @ `020a784` |

**Regla:** no hay autorreferencia circular al SHA del propio ledger dentro del mismo commit de contenido. El tip y el SHA de master se registran **después** del push/merge. MDEV-01 debe partir de `origin/master` **cuando ya contenga** este ledger (post-merge). Codex decision permanece `pending` hasta revisión humana.


## REWORK MDEV-01 (Codex) → REWORK-2

- Veredicto Codex: **REWORK MDEV-01** (segunda corrección / REWORK-2; no auto-PASS).
- Bases integradas REWORK-2: Oracle `5c2177d`, Signal `ac3c753` + higiene main `03adaf8`.
- Bundle REWORK-2 content_set: `e4431048e83bc678661aeb31c610db715b22635e4caf226f2cea13660ce5faa4`
  (`schema_bundle_version` `2026-08-01.mdev01.rework2`).
- Bloqueantes REWORK-2:
  - key legacy multitenant en memory.v1 → **cerrado** (`tenant_bound_credential_required`)
  - analysis en diccionario de proceso → **cerrado** (`get_analysis_request` / `request_cancel` durables)
  - matriz HTTP sin 429 real / envelope incompleto → **cerrado** (parametrizada + mutación I)
  - host mode desconocido puede elevar a augment → **cerrado** (fail-closed + mutación J)
  - rotación documentada con overlap vs índice → **cerrado** (política **A** atómica; doc alineada)
  - `key_hash` no globalmente único → **cerrado** (`uq_ctc_key_hash_global`)
  - OpenAPI anuncia ops no operativas sin `x-status` → **cerrado**
  - suite Signal 8 fallos preexistentes → **cerrado** (PR higiene #8 / `03adaf8`)
  - mutaciones A–J RED→restore GREEN → **cerrado**
- Migración expand `20260801_mem_cred`: upgrade/downgrade en PG de prueba solo; **no** Dev/Prod.

NO_ROLLBACK y beat drift permanecen abiertos (fuera de alcance MDEV-01).
APPROVED_EXTERNAL_SPEND / CLOUD_DATA_POLICY vacíos.


## Baselines

| Repo/entorno | Branch/ref | SHA | Migración | Estado Git | Capturado |
|---|---|---|---|---|---|
| Oracle source | `origin/master` | `e5468b296c68085dd72c0dd210f0e25368d9c098` | head código incluye `20260731_0028` | remoto limpio; root local dirty ajeno | 2026-08-01 rework |
| Oracle Dev | release `20260731T192559Z-native-96250a4` | `96250a40d7944864de1980b70019a0443bfe7fbb` | DB `20260731_0028` | api/web/worker/beat active | 2026-08-01 |
| Signal source | `origin/main` | `8973a096811f46648e86c2656ace216069e7f80d` | host head `20260801_ai_usage_attempts`; memory código `20260731_mem_lifecycle` | remoto limpio; root local dirty ajeno | 2026-08-01 |
| Signal Dev | `origin/signal-dev` desplegado | `db9fd379b44f0057a877d7a098356fd9bdcf6bc1` | host `20260801_ai_usage_attempts`; memory `20260731_mem_areq` | api/worker active; beat **active** con unit **disabled** (drift) | 2026-08-01 |

### Divergencia revalidada

| Repo | Solo principal | Solo Dev (todos) | Solo Dev (no-merges) |
|---|---:|---:|---:|
| Oracle `master`…`oracle-dev` | 22 | **8** | 7 |
| Signal `main`…`signal-dev` | 19 | **9** | 9 |

## Fases

| Fase | Grok candidate | Codex decision | SHA Oracle (master final) | SHA Signal | Gate Packet / evidencia |
|---|---|---|---|---|---|
| MDEV-00 | candidate_pass | **PASS MDEV-00** | `a834034396bc129f08a6997b3af27a87a33ec263` | n/a | PR#6/#7 + CI 30705985882/30706386596 |
| MDEV-01 | candidate_pass (REWORK-2) | **pending** | (pending push) | (pending push) | REWORK-2 security/durability/green |
| MDEV-02 | pending | pending | | | |
| MDEV-03 | pending | pending | | | |
| MDEV-04 | pending | pending | | | |
| MDEV-05 | pending | pending | | | |
| MDEV-06 | pending | pending | | | |
| MDEV-07 | pending | pending | | | |
| MDEV-08 | pending | pending | | | |
| MDEV-09 | pending | pending | | | |
| MDEV-10 | pending | pending | | | |
| MDEV-11 | pending | pending | | | |

## Contratos congelados

- Bundle MDEV-01 REWORK-2: `docs/contracts/memory_v1/` (schemas+fixtures+error_catalog)
- `content_set_sha256` bilateral: `e4431048e83bc678661aeb31c610db715b22635e4caf226f2cea13660ce5faa4`
- Scope productivo: `c:<consumer>|t:<tenant>` + product oracle + scope_type dossier + scope_id UUID
- Modes Oracle: disabled|shadow|augment; host switch prevalece; host mode inválido → disabled
- Credencial tenant-bound obligatoria en memory.v1; scopes vacíos deniegan; política rotación A
- Citabilidad: materializar Evidence Oracle antes del LLM

- API memory version: `memory.v1` en código `main`; **ausente** en SHA Dev `db9fd37` (HTTP 404)
- Ingestion / retrieval / coverage: congelados en docs/contracts/memory_v1 (REWORK)
- Retrieve stub (`main`): `items=[]` con nota pack builder pendiente
- Scope formula: `tenant_key` + `product_code` + `scope_type` + `scope_id`
- Pilot actual: `tenant_key=c:pilot|t:phase2`, `scope_type=pilot`, `scope_id=phase2`, `product_code=signal`
- Config precedence: docs/contracts/memory_v1/CONFIG_PRECEDENCE.md

## Configuración Dev efectiva (sin secretos)

### Signal host gates

`MEMORY_ENGINE_ENABLED=0`, `INGESTION=0`, `EXTRACTION=0`, `CONSOLIDATION=0`, `SUMMARIES=0`, `ANALYST=0`, `REFRESH=0`; `MEMORY_PROBE_ENABLED=1`; `WEB_SEARCH_PROVIDER=disabled`; paid allowlist vacía.

### Signal consumers / policies (redactado)

- ids/slugs: 1 nexus … 14 `opn-oracle`, 47 structured-dev, 55/59 pilot sintéticos, 61 `opn-oracle-memsol-pilot`
- **No** existe `opn-oracle-dev`
- Task policies (sin keys): ver `evidence/mdev-00/05b_consumers_policies.txt`
  - 14: 16 tasks (IA gobernada ollama/openrouter)
  - 61: `dossier_question_answer`, `report_custom_brief_plan` (ollama + titan fallback)
  - 59: `memory_extraction`
- Tenant allowlist memoria productiva: **no aplica** (corpus solo pilot; engine OFF)

### Oracle host

- `AI_ENABLED=true`, `AI_MODE=signal`, `SIGNAL_AI_ALLOWED_HOSTS=signal-dev.opnconsultoria.com`
- `MEMORY_CONTEXT_*` **ausente** → default `disabled`
- Documentos local backend ON
- Celery queues: `default,signals,ai,documents,notifications,maintenance`
- 51 tasks registradas; 12 beat entries — `evidence/mdev-00/04b_celery_tasks.txt`

## Migraciones y recuentos (RO)

| Repo | Revision | Counts | Rollback path |
|---|---|---|---|
| Oracle Dev | `20260731_0028` | dossiers=17 docs=7 chunks=162 conv=9 msg=11 monitors=6 signals=32 reports=39 tenants=4 users=6 | `activate-release.sh` + `PREVIOUS_RELEASE` |
| Signal host | `20260801_ai_usage_attempts` | n/a | **NO_ROLLBACK** formal (ver deploy) |
| Signal memory | `20260731_mem_areq` | sources/chunks=11857 obs=48955 facts=15925 conflicts=418 summaries=241 requests=4 jobs=3 | sin procedimiento host documentado de reverso memory; falta `20260731_mem_lifecycle` |

## Clasificación commits Dev únicos

### Oracle — 8 commits `origin/master..origin/oracle-dev`

| SHA | Tipo | Resumen | Decisión | Justificación |
|---|---|---|---|---|
| `81475d0` | docs | re-verif Celery transcripts | **descartar** | equivalente/contenido ya en master (`abff6e7` lineage) |
| `1a29387` | docs | vitest/Playwright residual | **descartar** | solo ledger MEMSOL histórico; no aporta base limpia |
| `3202221` | docs | evidencia Celery | **descartar** | idem docs Dev |
| `4f0011b` | docs | ledger smoke | **descartar** | portado (`04063e7`) |
| `96250a4` | fix UI | AsyncActionButton loading | **descartar** | en master (`f4d0a59`); es el SHA del **release Dev** pero el contenido UI ya está en master |
| `6098d57` | fix UI | poll ref React Compiler | **descartar** | en master (`ea1ed11`) |
| `d3804ba` | **merge** | `merge(master): integrar Memoria Sol en canal oracle-dev` parents `6a2b103`+`e896f50` | **descartar** | merge de integración hacia **oracle-dev**, no un delta único que falte en master; master ya contiene (y supera) el lado MEMSOL del merge. No cherry-pick de merges. Base = master |
| `6a2b103` | docs | living roadmap dashboard | **descartar** | en master (`e896f50`) |

**Conteo:** 8/8 clasificados.

### Signal — 9 commits `origin/main..origin/signal-dev`

| SHA | Resumen | Decisión |
|---|---|---|
| `db9fd37` | error_code null intentos | **descartar** (`307cc97` main) |
| `eafa61b` | observabilidad intentos | **descartar** (`a84be26`) |
| `1e8e0cc` | tests fallback | **descartar** (`f396533`) |
| `e0a4a2d` | task keys MEMSOL | **descartar** (`e327dc3`) |
| `06fbdd6` | retención contabilidad | **descartar** (`c6a9606`) |
| `64c3ab3` | ollama_titan OpenAI-compat | **descartar** (`60a5782`) |
| `681ad88` | hotfixes purge/shm | **descartar** (`dc08ad6`) |
| `f32fed6` | auditoría OpenRouter + harness F0–F4 | **reimplementar selectivo** si hace falta harness (no merge ciego) |
| `8d26ccf` | admin quitar ghost `osint_web_result` | **adoptar** (cherry-pick posterior si sigue ausente en main) |

**Conteo:** 9/9 clasificados.

**Bases candidatas:** Oracle `origin/master` · Signal `origin/main` (worktrees limpios; roots ajenos intactos).

## Worktrees

| Propósito | Branch | Base | Path |
|---|---|---|---|
| MDEV-00 rework (esta entrega) | `mdev/00-baseline-rework` | `origin/master@402fc29` | `.worktrees/mdev00-rework` |
| Histórico no reescrito | `mdev/00-baseline-ledger` | (frozen) | no tocar |
| Auditoría Signal RO | detached main | `origin/main` | `.worktrees/mdev00-signal-audit` |

## Deploy / rollback Dev

### Oracle Dev — procedimiento real

1. `infra/native-dev/build-release.sh <git-sha>` → `/opt/opn-oracle/releases/<TS>-native-<short>`
2. `infra/native-dev/activate-release.sh <release-id>` → symlink `current`, migrate, restart 4 units
3. Punteros `CURRENT_RELEASE` / `PREVIOUS_RELEASE`
4. Rollback: activar release previo (p. ej. `20260731T095958Z-native-eb61173`)

### Signal Dev — procedimiento real y límites

- Update: `/usr/local/sbin/signal-dev-update.sh <branch>`
  - hace fetch/checkout/pull, `pip install -r requirements.txt`, `alembic upgrade head`
  - **reinicia solo** `opn-signal-dev-api` y `opn-signal-dev-worker`
  - **no reinicia beat** (comentario explícito: beat stays stopped unless explicitly started)
- **Drift observado:** unit beat `UnitFileState=disabled` pero proceso `ActiveState=active` / running
- **No** hay `CURRENT`/`PREVIOUS` release pointers en `/opt/apps/opn_signal_dev`
- Script **no** implementa rollback de código ni de schema
- Backup existe: `signal-dev-backup-pg.sh` → dumps en `/var/backups/opn_signal_dev` (recuperación manual, no automatizada en update)

#### Blocker MDEV-10

| ID | Severidad | Descripción |
|---|---|---|
| **NO_ROLLBACK** | **high** | No se demostró read-only un procedimiento real, reproducible y verificable de rollback de código/migración en Signal Dev comparable a Oracle `PREVIOUS_RELEASE`. Solo backup PG + checkout manual ad hoc. **No inventar rollback.** MDEV-10 debe resolver o documentar runbook nuevo antes de deploy coordinado. |

## Suites de tests

| Suite | En MDEV-00 | Resultado / nota |
|---|---|---|
| Oracle `test_memory_context.py --no-cov` | **ejecutada** | 9 passed |
| Signal focused memory/ai (5 archivos) | **ejecutada** | 31 passed |
| Oracle suite completa + cov≥84% | **NO ejecutada** | histórico conocido: PR #1 release memsol CI green ~84% |
| Signal `pytest -q` completo | **NO ejecutada** | histórico: PRs packaging/memsol #2–#5 merged |
| Dashboard `--check` | **ejecutada** | OK tras crear paths referenciados |

## Riesgos / bloqueos

| ID | Sev | Descripción | Resuelve |
|---|---|---|---|
| NO_ROLLBACK | high | Signal Dev sin rollback reproducible | MDEV-10 |
| R-00-2 | high | Dev sin `/memory/v1` (404) | MDEV-02/10 deploy main |
| R-00-3 | high | memory rev sin lifecycle | MDEV-02/10 |
| R-00-4 | medium | corpus solo pilot | MDEV-05 |
| R-00-5 | medium | update.sh sin install opn_memory ni memory alembic | MDEV-10 |
| R-00-beat | medium | beat disabled+active drift | MDEV-10 ops |
| R-00-ssh | low | SSH directo workstation refused; jump oracle-dev OK | ops |

## UAT final

(pendiente MDEV-11)

## Estado final del programa

```text
IN_PROGRESS
```
