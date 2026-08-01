# MDEV execution ledger

## Identidad

- Programa: `MEMORIA_DEV_V2`
- Oracle Dev: `https://oracle-dev.opnconsultoria.com`
- Signal Dev: `https://signal-dev.opnconsultoria.com`
- Producción: `OUT_OF_SCOPE`
- Pack version: `2026-08-01.4`
- Pack `content_set_sha256`: `687505b44447c625aae8c4f5c23d01841ac6bc58bc29eac5d84d4a7d65ada164`
- Integridad revalidada en cada fase: sí (MDEV-00: 27/27 ficheros + content_set MATCH)
- Roadmap idea: `ORC-MEM-001` (status `approved`)
- Informe bilateral: `docs/implementation/MDEV_00_BASELINE_BILATERAL.md`

## Baselines

| Repo/entorno | Branch/ref | SHA | Migración | Estado Git | Capturado |
|---|---|---|---|---|---|
| Oracle source | `origin/master` | `402fc2955eb73b135c2b2f0bc9567f8d68f84142` | head código `20260731_0028` | limpio en remoto; root local dirty ajeno | 2026-08-01 |
| Oracle Dev | release `20260731T192559Z-native-96250a4` | `96250a40d7944864de1980b70019a0443bfe7fbb` | `20260731_0028` | servicios api/web/worker/beat active | 2026-08-01 |
| Signal source | `origin/main` | `8973a096811f46648e86c2656ace216069e7f80d` | host head `20260801_ai_usage_attempts`; memory head `20260731_mem_lifecycle` en árbol | limpio en remoto; root local dirty ajeno | 2026-08-01 |
| Signal Dev | `origin/signal-dev` desplegado | `db9fd379b44f0057a877d7a098356fd9bdcf6bc1` | host `20260801_ai_usage_attempts`; memory `20260731_mem_areq` | api/worker/beat active; memory flags OFF | 2026-08-01 |

### Divergencia histórica revalidada

| Repo | Solo principal | Solo Dev | Notas |
|---|---:|---:|---|
| Oracle `master` vs `oracle-dev` | 22 | 8 | Dev detrás de master; commits UI/docs mayormente ya portados |
| Signal `main` vs `signal-dev` | 19 | 9 | Dev carece de packaging, MEMSOL-02 lifecycle, loopback PG, catálogo MEMSOL final |

## Fases

| Fase | Grok candidate | Codex decision | SHA Oracle | SHA Signal | Gate Packet |
|---|---|---|---|---|---|
| MDEV-00 | candidate_pass | pending | `mdev/00-baseline-ledger` (docs) | n/a (sin commit Signal) | este ledger + bilateral |
| MDEV-01 | pending | pending | | | |
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

- API memory version: `memory.v1` (Signal router en `main`; **ausente** en SHA Dev `db9fd37`)
- Ingestion schema/hash: pendiente MDEV-01
- Retrieval schema/hash: pendiente MDEV-01 (stub actual devuelve `items=[]` en código `main`)
- Coverage schema/hash: `coverage_manifest.v1` (stub)
- Scope formula: `tenant_key` + `product_code` + `scope_type` + `scope_id` (pilot actual: `c:pilot|t:phase2`)
- Config precedence version: pendiente MDEV-01
- Runtime prompt/schema versions: pack histórico `../runtime_prompts` (no tocado en MDEV-00)

## Configuración Dev efectiva (sin secretos)

- Signal host gates: `MEMORY_ENGINE_ENABLED=0`, `INGESTION=0`, `EXTRACTION=0`, `CONSOLIDATION=0`, `SUMMARIES=0`, `ANALYST=0`, `REFRESH=0`; `MEMORY_PROBE_ENABLED=1`
- Signal consumer memory settings/version: sin Memory Control Center; consumers pilot sintéticos presentes
- Signal task/model policies: no mutadas en MDEV-00
- Oracle host gate: `AI_ENABLED=true`, `AI_MODE=signal`, `SIGNAL_AI_ALLOWED_HOSTS=signal-dev.opnconsultoria.com`; `MEMORY_CONTEXT_*` **ausente** → default `disabled`
- Oracle tenant/connection mode: structured memory local operativa; Http adapter stub
- Consumer slug/id objetivo futuro: `opn-oracle-dev` (aún no creado; no reutilizar `opn-oracle` id=14)
- Tenants autorizados: pendiente MDEV-01/10
- Credencial/IntegrationConnection por tenant: no creadas en MDEV-00
- `APPROVED_EXTERNAL_SPEND`: (vacío)
- `APPROVED_CLOUD_DATA_POLICY`: (vacío)
- Cuenta/tenant real designados para aceptación: pendiente propietario (MDEV-11)

## Migraciones y recuentos

| Repo | Revision | Pre-count (MDEV-00) | Post-count | Downgrade/rollback |
|---|---|---:|---:|---|
| Oracle Dev host | `20260731_0028` | dossiers=17, documents=7, conversations=9, messages=11, monitors=6 | sin cambio | activate-release + PREVIOUS_RELEASE |
| Signal Dev host | `20260801_ai_usage_attempts` | n/a mutación | sin cambio | `signal-dev-update.sh` + restart |
| Signal Dev memory | `20260731_mem_areq` | sources=11857, chunks=11857, observations=48955, facts=15925, conflicts=418, summaries=241, requests=4 | sin cambio | alembic memory branch; **falta** `20260731_mem_lifecycle` |

## Clasificación commits Dev únicos

### Signal (`origin/main..origin/signal-dev`)

| SHA | Resumen | Decisión |
|---|---|---|
| `db9fd37` | error_code null intentos IA | **descartar** (equivalente `307cc97` en main) |
| `eafa61b` | observabilidad intentos Ollama→Titan | **descartar** (`a84be26`) |
| `1e8e0cc` | tests fallback 5xx/404 | **descartar** (`f396533`) |
| `e0a4a2d` | task keys MEMSOL | **descartar** (`e327dc3`) |
| `06fbdd6` | retención contabilidad | **descartar** (`c6a9606`) |
| `64c3ab3` | ollama_titan OpenAI-compat | **descartar** (`60a5782`) |
| `681ad88` | hotfixes purge/shm | **descartar** (`dc08ad6`) |
| `f32fed6` | auditoría migración OpenRouter + harness F0–F4 | **reimplementar selectivo** si se necesita harness en main (docs/script; no merge ciego) |
| `8d26ccf` | admin: quitar ghost `osint_web_result` | **adoptar** (cherry-pick/reaplicar sobre main en fase posterior si sigue ausente) |

### Oracle (`origin/master..origin/oracle-dev`)

| SHA | Resumen | Decisión |
|---|---|---|
| `81475d0` | docs re-verif Celery | **descartar** (`abff6e7`) |
| `4f0011b` | docs ledger smoke | **descartar** (`04063e7`) |
| `96250a4` | AsyncActionButton loading | **descartar** (`f4d0a59`) |
| `6098d57` | poll ref React Compiler | **descartar** (`ea1ed11`) |
| `6a2b103` | docs governance dashboard | **descartar** (`e896f50`) |
| `1a29387` | docs vitest/Playwright residual | **descartar** (solo ledger MEMSOL histórico; no bloquea base master) |
| `3202221` | docs evidencia Celery | **descartar** (idem) |

**Base candidata limpia:** Oracle `origin/master@402fc29` · Signal `origin/main@8973a09` (incluye lo ya desplegado/corregido en principales; **no** partiendo de ramas Dev antiguas).

## Worktrees / branches definidos (sin merge ciego)

| Propósito | Repo | Branch | Base | Path local |
|---|---|---|---|---|
| MDEV-00 docs/ledger | Oracle | `mdev/00-baseline-ledger` | `origin/master` | `.worktrees/mdev00-oracle-audit` |
| Auditoría Signal RO | Signal | detached `origin/main` | `origin/main` | `.worktrees/mdev00-signal-audit` |
| Implementación posterior | Oracle | `mdev/dual-memory` (crear en MDEV-01+) | `origin/master` | TBD clean worktree |
| Implementación posterior | Signal | `mdev/dual-memory` (crear en MDEV-01+) | `origin/main` | TBD clean worktree |

Roots compartidos **no tocados** (WIP ajeno intacto).

## Deploy / rollback Dev (descubierto, no ejecutado)

### Oracle Dev

- Canal: `infra/native-dev/build-release.sh <git-sha>` (default branch fetch `oracle-dev`) → release inmutable `/opt/opn-oracle/releases/<TS>-native-<short>`
- Activación: `infra/native-dev/activate-release.sh <release-id>` (symlink `current`, migrate, restart `opn-oracle-{api,web,worker,beat}`)
- Punteros: `/opt/opn-oracle/CURRENT_RELEASE`, `PREVIOUS_RELEASE`
- Activo: `20260731T192559Z-native-96250a4` / SHA `96250a4`
- Rollback: activar `PREVIOUS_RELEASE` (p. ej. `20260731T095958Z-native-eb61173`) sin force-push

### Signal Dev

- Update: `/usr/local/sbin/signal-dev-update.sh <branch>` (default histórico `develop`; árbol actual en `signal-dev`)
- Install dir guard: `/opt/apps/opn_signal_dev` only; refuse prod IP pattern
- Servicios: `opn-signal-dev-{api,worker,beat}` (beat unit disabled-by-policy pero proceso active observado)
- Backup: `/usr/local/sbin/signal-dev-backup-pg.sh` → `/var/backups/opn_signal_dev`
- Prod path distinto: `scripts/update_server_from_github.sh --branch main` en `/opt/apps/opn_signal` (**no usar en Dev**)
- Nota: script Dev actual **no** instala `packages/opn_memory` ni corre rama alembic memory (gap para MDEV-10)

## Riesgos/bloqueos abiertos

| ID | Severidad | Descripción | Owner | Evidencia | Resuelto por |
|---|---|---|---|---|---|
| R-00-1 | medium | SSH directo workstation→signal-dev: connection refused (posible fail2ban); acceso vía jump oracle-dev+agent | ops | MDEV-00 audit | MDEV-10 runbook |
| R-00-2 | high | Signal Dev SHA sin router `/memory/v1` → 404; retrieve stub solo existe en `main` | dual | HTTP 404 + `NO_MEMORY_API` | MDEV-02/10 deploy main-based |
| R-00-3 | high | Memory schema en `20260731_mem_areq`; falta lifecycle CAS en Dev | signal | `memory.alembic_version_memory` | MDEV-02/10 |
| R-00-4 | medium | Corpus 100% `c:pilot|t:phase2` / product `signal` — no tenant/dossier | dual | SQL group by | MDEV-05 scope real |
| R-00-5 | medium | `signal-dev-update.sh` incompleto vs packaging main (`opn_memory` install) | signal | script host | MDEV-10 |
| R-00-6 | low | Roots locales con WIP ajeno; no stashear | both | git status | disciplina worktrees |

## UAT final

- run_id: (pendiente MDEV-11)
- dossier_id:
- document_id/job_id:
- monitor_id/external_id:
- memory source/chunk/fact/summary counts:
- question/job/message/context snapshot:
- report/job/artifact:
- usage_log/attempt IDs:
- disabled/shadow/augment:
- cross-tenant negative:
- cuenta real Oracle/Signal, roles y recovery:
- egress browser/backend a producción/cloud:
- restart/cancel/retry/kill switch:
- cleanup:

## Estado final

```text
IN_PROGRESS
```

## MDEV-00 timestamps (Europe/Madrid)

- Inicio medición: `2026-08-01 17:02:19 Europe/Madrid` (sesión) / revalidación pack `17:02:49`
- Entrega artefactos: ver Gate Packet / commit de esta fase
