# Matriz contractual Oracle ↔ Signal · MEMSOL-00

**Fecha de congelación:** 2026-07-31 Europe/Madrid  
**Oracle refs:** `master` pre-merge `35b2e94` · `oracle-dev` `eb61173` · merge-base `71c7552`  
**Signal refs:** `main` `60a5782` · `signal-dev` `06fbdd6` · merge-base `3b378c9`  
**Autoridad:** esta matriz es inventario de **estado real medido**; no autoriza activar flags ni proveedores de pago.

## 1. Divergencia de ramas

| Repo | Solo en dev | Solo en main/master | Merge-tree conflictos |
|---|---|---|---|
| Oracle | 6 commits (Mercado `market.v1`, docs/documents dev, UI checkbox, activate-release) | 11 commits (monitor infra, OpenRouter spend, rankings storage, plan Memoria Sol docs) | 0 en merge-tree |
| Signal | 5 commits (retención usage logs, auditoría OpenRouter F0–F4, hotfixes patch-equiv) | 4 commits (release 06b4b1e, login admin, Titan hotfix, purge/shm) | no fusionado en MEMSOL-00 |

**Orden de integración Signal (documentado, no ejecutado):**

1. Asegurar hotfixes patch-equivalentes ya en ambas líneas.
2. Integrar `usage_logs_retention` + harness F0–F4 a `main` solo tras gate de tests y aprobación de coste.
3. No mezclar WIP local de admin UI / web_search_chain / PROMPT_*.
4. `opn_memory` ya en `main` vía release `06b4b1e` con **flags OFF**.

## 2. Endpoints Signal namespace Oracle

Base: `/api/v1/oracle/*` · consumer `opn-oracle` · scopes `monitor:write|signal:read|webhook:manage|entity:read`.

| Método | Ruta | Scope | Notas |
|---|---|---|---|
| POST | `/monitors` | monitor:write | INSERT-only; idempotency key |
| GET/PATCH | `/monitors/{id}` | read/write | config_version optimistic |
| POST | `/monitors/{id}/pause\|resume\|sync` | monitor:write | sync → 202 |
| CRUD | `/tender-searches` | monitor:write / signal:read | active searches |
| GET | `/tender-searches/{id}/run` | signal:read | run snapshot |
| GET | `/signals`, `/signals/{id}` | signal:read | cursor opaco |
| POST/GET/… | `/subscriptions` | webhook:manage | HMAC por consumer |
| GET | `/entity/graph\|patents\|disclosures\|news\|dossier` | entity:read | dossier puede añadir `memory_analysis` si flags ON |
| GET | `/health` | auth | liveness contrato |

Gobierno IA genérico: `POST /api/v1/ai/run` (no namespace oracle).

## 3. Task keys Oracle en Signal (`ai_governance` catalog)

| task_key | Catálogo default (código) | Notas prod/dev |
|---|---|---|
| `report_writer` | ollama gobernado · max_out 6500 · timeout 300s | no cambiar por inferencia MEMSOL |
| `evidence_reviewer` | ollama gobernado | |
| `dossier_situation_summary` | ollama gobernado | |
| `dossier_completion_wizard` | ollama gobernado | |
| `competitive_procurement_intelligence` | ollama / OpenRouter según BD | |
| `entity_dossier_intelligence` | ollama / OpenRouter según BD | |
| `tender_search_wizard` | ollama gobernado | |
| `tender_summary` | max_out 900 · 90s | |
| `memory_extraction` | ollama→ollama_titan · 45s · 2000 | flags memoria OFF |
| `memory_entity_resolution` | ollama→titan · 30s | OFF |
| `memory_consolidation` | ollama→titan · 45s | OFF |
| `memory_conflict_detection` | ollama→titan · 45s | OFF |
| `memory_summary_update` | ollama→titan · 60s | OFF |
| `memory_analysis` | ollama→titan | OFF |
| *(aún no existen)* | `dossier_question_answer`, `report_brief_planner`, `custom_report_writer` | MEMSOL-06/07 |

**Regla D-015:** Oracle solo envía `task_key`; Signal resuelve proveedor/modelo/fallback/presupuesto.  
`ConsumerAISettings.per_task_settings` (BD) manda sobre el catálogo.  
`signal-dev@f32fed6+` experimenta Gemini 3.1 Flash Lite en subset OpenRouter; **main no lo tiene**.

## 4. Flags `opn_memory` (Signal `Settings`)

| Flag | Default | Efecto |
|---|---|---|
| `MEMORY_ENGINE_ENABLED` | false | master switch |
| `MEMORY_INGESTION_ENABLED` | false | |
| `MEMORY_EXTRACTION_ENABLED` | false | |
| `MEMORY_CONSOLIDATION_ENABLED` | false | |
| `MEMORY_SUMMARIES_ENABLED` | false | |
| `MEMORY_ANALYST_ENABLED` | false | |
| `MEMORY_ADAPTER_*` | false | procurement/borme/placsp/ip/raw |
| `MEMORY_REFRESH_ENABLED` | true *solo si engine* | 6h |
| `MEMORY_PROBE_ENABLED` | true *solo si engine* | 45min |
| `MEMORY_REFRESH_ALLOW_LLM` | false | |
| `memory_target_entities` | ITURRI,IBERDROLA | **piloto** — endurecer en MEMSOL-02 |

Schema Postgres: `memory.*` (paquete `packages/opn_memory`).  
Tablas: sources, chunks, observations, facts, fact_evidence, conflicts, summaries, analysis_runs/cache/requests, entities/aliases/merges, jobs.

## 5. Oracle dominio relevante (pre MEMSOL-03)

| Capacidad | Estado |
|---|---|
| `StrategicDossier.profile_config` | competitive-intelligence.v1 (master) + market.v1 (tras merge) |
| `DossierIntentRevision` | **no existe** |
| `IntelligenceRequirement` / `DossierOffering` | **no existen** |
| `Watchlist` / `SignalMonitor` | sí; materialización starter no crea monitores remotos |
| Procurement search profiles/watches | sí (prompts 78–97) |
| `BackgroundJob` stages/cancel/retry/lease | sí |
| `LivingSummary` / oráculo nocturno | resumen versionado, no chat Q&A |
| Reports + snapshot evidencia | sí; plantillas genéricas |
| Documents → memory read contract | `docs/integrations/memory/DOCUMENTS_READ_CONTRACT.md` |
| `/api/v1/dossiers/{id}/activity` | **no existe** (MEMSOL-04) |
| Preguntar a Oracle persistente | **no existe** (MEMSOL-06) |
| Custom report assistant | **no existe** (MEMSOL-07) |

## 6. Estados y cadencias observados

| Superficie | Estados / cadencias |
|---|---|
| Dossier | draft→active→paused→archived |
| Watchlist | `manual\|hourly\|daily\|weekly` (starter: daily + requires_review) |
| Signal monitor (Oracle adapter) | desired/observed, cursor, health |
| BackgroundJob | pending/running/succeeded/failed/cancelled + lease/heartbeat |
| Memory analysis request (Signal) | pending/running/…/failed/cancelled/stale (CAS en MEMSOL-02) |
| Report | draft/generating/ready/failed (artefacto no listo parcial) |

## 7. Timeouts y alineación (deuda MEMSOL-08)

| Capa | Valor típico observado |
|---|---|
| Task report_writer | 300 s |
| Meeting briefing | 180 s |
| Oracle HTTP client ejemplo | ~210 s documentado históricamente |
| Celery soft/hard | ver `docs/operations/CELERY.md` |
| Lease BackgroundJob | existing recovery |

Cadena objetivo (MEMSOL-08): `primary+fallback+red < HTTP Oracle < soft < hard < lease`.

## 8. Fuentes / conectores Signal (ejecutables por kind)

Incluye (no exhaustivo productivo): `web_search`, `rss`, `telegram`, redes, `borme`, `tender_eu`, `tender_es`, `gazette`, `grants_es`, `sanctions`, `eurlex`, `patents`, `cnmv`, scrapers.  
DuckDuckGo bloqueado en prod IP; búsqueda de pago allowlisted.  
MEMSOL-09 debe mapear salud/cobertura honesta («Menciones web» ≠ prensa verificada).

## 9. Contratos HTTP internos pendientes (MEMSOL-01/05)

| Contrato | Decisión provisional |
|---|---|
| Oracle → opn_memory retrieval | HTTP versionado interno o gateway Signal; **no** SQL cruzado |
| Context snapshot | hash + coverage_manifest + versions |
| MemoryScope | consumer + external_tenant + product_code + scope_type/id desde identidad |

## 10. Contradicciones documentales registradas

| ID | Tema | Resolución provisional |
|---|---|---|
| C-D015 | D-015 “sin cloud” vs tasks OpenRouter operativas | Signal decide; Oracle no elige modelo; supersede parcial en MEMSOL-01 |
| C-UE27 | market.v1 UE-only vs producto global | **corregido en MEMSOL-00** a ISO-2 global |
| C-session | sessionStorage prefill | efímero; no reanudación multi-dispositivo |
| C-pilot | memory_target_entities hardcode piloto | apagar defaults productivos en MEMSOL-02 |
| C-homonym | task keys `oracle_*` Nexus vs producto OPN Oracle | ya documentado en AGENTS Signal |

## 11. WIP no incluido

Ningún fichero del working tree sucio de `oracle-dev` ni `signal-dev` se stagea en MEMSOL-00.  
Trabajo MEMSOL vive en worktree Oracle `.worktrees/memsol` → merge a `master`.
