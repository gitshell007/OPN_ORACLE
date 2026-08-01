# MDEV-00 · Baseline bilateral Oracle Dev ↔ Signal Dev

**Fecha captura:** 2026-08-01 (Europe/Madrid)  
**Pack:** `memoria_dev_v2` version `2026-08-01.4`  
**content_set_sha256:** `687505b44447c625aae8c4f5c23d01841ac6bc58bc29eac5d84d4a7d65ada164` (MATCH)  
**Producción:** fuera de alcance (no mutada, no consultada más allá de refs git públicas)

## 1. Integridad del paquete

- 27/27 ficheros del manifiesto con SHA-256 coincidente.
- `content_set_sha256` recalculado (líneas `sha256␠␠path\\n` orden bytewise) = manifiesto.
- Sin ficheros extra/missing respecto al inventario.

## 2. Roots compartidos (intactos)

| Root | Branch local | HEAD | WIP |
|---|---|---|---|
| `/Users/gitshellmini/PycharmProjects/OPN_ORACLE` | `oracle-dev` (behind 36) | `6a2b103` | dirty + untracked ajenos — **no tocado** |
| `/Users/gitshellmini/PycharmProjects/opn_signal` | `fix/signal-release-packaging` | `d185757` | dirty + untracked ajenos — **no tocado** |

## 3. Tabla ref → SHA → entorno → migración

| Ref | SHA | Entorno | Migración |
|---|---|---|---|
| `origin/master` (Oracle) | `402fc29` | source of truth | código incluye hasta `20260731_0028` |
| `origin/oracle-dev` | `81475d0` | rama Dev git (divergente) | docs/UI residuales |
| Oracle Dev release activo | `96250a4` (`20260731T192559Z-native-96250a4`) | `oracle-dev.opnconsultoria.com` / `159.195.216.33` | DB `20260731_0028` |
| `origin/main` (Signal) | `8973a09` | source of truth | host `20260801_ai_usage_attempts`; memory código `20260731_mem_lifecycle` |
| `origin/signal-dev` | `db9fd37` | desplegado en Dev | host `20260801_ai_usage_attempts`; memory DB `20260731_mem_areq` |
| Signal Dev tree | `db9fd37` | `/opt/apps/opn_signal_dev` | sin `app/api/v1/memory.py` |

## 4. Oracle Dev (RO)

- **Host:** `v2202607388167489673` · IP `159.195.216.33`
- **Servicios:** `opn-oracle-{api,web,worker,beat}` = active
- **Listeners:** gunicorn `127.0.0.1:8010`, next `127.0.0.1:3010`, nginx 80/443, postgres/redis loopback
- **Health:** `GET /health/ready` → `{"status":"ok","dependencies":{"database":"ok","redis":"ok"}}`; meta release `20260731T192559Z-native-96250a4`
- **AI:** `AI_ENABLED=true`, `AI_MODE=signal`, `SIGNAL_AI_ALLOWED_HOSTS=signal-dev.opnconsultoria.com`
- **Documentos:** local backend habilitado (`DOCUMENT_STORAGE_BACKEND=local`)
- **MEMORY_CONTEXT_***:** ausente en `oracle.env` → default efectivo `disabled`
- **HttpMemoryContextAdapter (código desplegado + runtime):**
  - `DisabledMemoryContextAdapter.retrieve` → `MemoryContextDisabled`
  - `HttpMemoryContextAdapter.retrieve` → `MemoryContextError: El adaptador HTTP de memoria aún no está habilitado en este despliegue.`
- **Worker queues:** `default,signals,ai,documents,notifications,maintenance`
- **Backups:** `/var/backups/opn-oracle-dev` (+ dumps memsol pilot)
- **Counts (migrator):** tenants=4, users=6, strategic_dossiers=17, documents=7, document_chunks=162, dossier_conversations=9, dossier_messages=11, signal_monitors=6, signals=32, reports=39, evidence=156

### Deploy Oracle Dev (único mecanismo)

1. `build-release.sh <sha>` → artefacto en `/opt/opn-oracle/releases/`
2. `activate-release.sh <release-id>` → symlink, migrate, restart
3. Rollback vía `PREVIOUS_RELEASE`

## 5. Signal Dev (RO)

- **Host:** `v2202607388167489649` · IP `159.195.216.184`
- **Servicios:** `opn-signal-dev-{api,worker,beat}` = active (beat unit disabled policy, proceso running)
- **Tree:** `/opt/apps/opn_signal_dev` @ `db9fd37`
- **Health público:** `https://signal-dev.opnconsultoria.com/healthz` → 200 `{"status":"ok","service":"opn_signal","version":"0.1.0"}`
- **Memory HTTP en Dev:** `GET/POST /api/v1/memory/v1/*` → **404** (router no existe en este SHA)
- **Flags memoria (settings.env):** todos los switches funcionales en `0` (ENGINE/INGESTION/EXTRACTION/CONSOLIDATION/SUMMARIES/ANALYST/REFRESH); probe `1`
- **Postgres/Redis:** docker `signal_dev_postgres` `:5433`, `signal_dev_redis` `:6380`
- **Worker:** `-Q celery,memory --concurrency=1`
- **Consumers (ids):** 1 nexus, 2 risk, 3 core, 4 sentinel, 5 evaluator, 11 totalenergies, **14 opn-oracle**, 47 structured-dev, 55/59 pilot sintéticos, **61 opn-oracle-memsol-pilot** — **no** existe aún `opn-oracle-dev`
- **Memory schema (`memory.*`):**

| Tabla | Count | Scope |
|---|---:|---|
| memory_sources | 11857 | 100% `c:pilot\|t:phase2` / scope pilot/phase2 |
| memory_chunks | 11857 | idem |
| memory_observations | 48955 | idem |
| memory_facts | 15925 | idem |
| memory_conflicts | 418 | idem |
| memory_summaries | 241 | idem |
| memory_analysis_requests | 4 | idem |
| memory_jobs | 3 | idem |
| alembic_version_memory | rev `20260731_mem_areq` | falta lifecycle |

- **product_code** en sources/facts: `signal` (no dossier-scoped)
- **Conclusión corpus:** piloto de fase2; **no** es memoria productiva por tenant/expediente Oracle

### Deploy Signal Dev (único mecanismo host)

- `/usr/local/sbin/signal-dev-update.sh <branch>` sobre `/opt/apps/opn_signal_dev`
- Backup `/usr/local/sbin/signal-dev-backup-pg.sh`
- **No desplegado** en esta fase

### Stub retrieve en código `main` (no desplegado en Dev)

En `app/api/v1/memory.py` (`origin/main`): con engine ON autentica consumer, construye scope y **devuelve siempre** `items=[]` con nota `retrieve stub: engine on, pack builder pending MEMSOL-05`. Con engine OFF → 503.

## 6. Stubs demostrados

| Componente | Prueba | Resultado |
|---|---|---|
| Signal Dev HTTP memory | curl health/retrieve local y público | 404 (SHA sin router) |
| Signal `main` retrieve code | lectura `memory_retrieve` | `items=[]` stub |
| Oracle Disabled adapter | runtime en release | `MemoryContextDisabled` |
| Oracle Http adapter | runtime en release | `MemoryContextError` “aún no está habilitado” |
| Oracle unit tests | `pytest apps/api/tests/test_memory_context.py --no-cov` | 9 passed |

## 7. Baselines de tests

| Suite | Comando | Resultado |
|---|---|---|
| Oracle memory_context | `pytest apps/api/tests/test_memory_context.py --no-cov` en worktrees master/release | 9 passed |
| Signal focused | `pytest tests/test_memory_request_lifecycle.py tests/test_opn_memory_packaging.py tests/test_memsol_fallback_gate.py tests/test_memsol_ai_pilot_tasks.py tests/test_ai_usage_attempts.py` sobre `origin/main` | 31 passed |
| Oracle full suite | no re-ejecutada completa en MDEV-00; estado conocido release memsol: ≥84% cov en PR #1 (histórico) | preexistente |

No se atribuyen fallos nuevos a este cambio documental.

## 8. Diff selectivo y base limpia

- **No merge ciego** de `oracle-dev` ni `signal-dev` hacia principales.
- Casi todos los commits “solo Dev” ya están en principales por cherry/PR.
- Señal de adopción residual Signal: `8d26ccf` (ghost osint_web_result).
- Harness OpenRouter `f32fed6`: reimplementar solo si se necesita, no merge masivo.
- Bases: **Oracle master@402fc29**, **Signal main@8973a09**.

## 9. Roadmap

- No existía feature equivalente “memoria dual”.
- Creada **`ORC-MEM-001`** status **`approved`** (no implemented).
- Dashboard regenerado con generador `--check` OK.

## 10. Mutaciones

Ninguna en hosts Dev ni flags. Solo documentación en worktree Oracle limpio.
