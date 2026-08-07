# ADR-0009 — Intención versionada, memoria y automatización del expediente

- **Estado:** accepted
- **Fecha:** 2026-07-31
- **Prompt:** MEMSOL-01
- **Entrada:** MEMSOL-00 @ Oracle `50a3b8a`, Signal inventario `main@60a5782` / `signal-dev@06fbdd6`
- **Supersede parcial:** aclara D-015 (política de proveedor) sin abrirlo a cloud global

## Contexto

Oracle tiene intake parcial (`profile_config`, `market.v1`, `competitive-intelligence.v1`),
jobs durables, informes y monitores, pero carece de una **intención aceptada versionada** que
enlace requisitos, oferta, vigilancias, preguntas e informes. Signal hospeda `opn_memory` con
flags OFF y gobierno de modelos. Memoria Sol exige contratos cerrados antes de migraciones.

## Decisiones

### 1. Nombre y lifecycle de la intención

**Nombre final:** `DossierIntentRevision` (tabla `dossier_intent_revisions`).

| Estado | Significado | Transiciones |
|---|---|---|
| `draft` | propuesta o edición humana no aceptada | → `accepted`, `rejected` |
| `accepted` | vigente para el expediente | → `superseded` (solo al aceptar otra) |
| `superseded` | sustituida por revisión posterior | terminal |
| `rejected` | descartada | terminal |

Reglas:

- `version` monotónica por `(tenant_id, dossier_id)` empezando en 1.
- Como máximo **una** revisión `accepted` por expediente (`current_intent_revision_id` en
  `strategic_dossiers` + constraint de unicidad parcial).
- Aceptar una draft: draft→accepted; la accepted anterior →superseded en la misma transacción.
- `request_text` inmutable tras `accepted`.
- `content_hash` = SHA-256 canónico de `(schema_key, schema_version, request_text, structured_spec)`.
- Optimistic concurrency: columna `row_version` / ETag en PATCH de drafts.

### 2. IntelligenceRequirement

Tabla `intelligence_requirements`, tenant + dossier scoped.

| Campo | Tipo lógico |
|---|---|
| id, tenant_id, dossier_id | UUID |
| intent_revision_id | FK a revisión (puede ser la vigente o la que lo originó) |
| class | enum: `market_scan`, `competitive_watch`, `procurement_fit`, `actor_monitor`, `research_question`, `risk_watch`, `custom` |
| priority | `low\|medium\|high\|critical` |
| question | texto ≤2000 |
| decision_to_support | texto ≤2000 |
| scope | JSON acotado: geographies[], sectors[], languages[], entities[], keywords[] |
| exclusions | JSON acotado |
| success_criteria | lista ≤20 strings |
| status | `active\|paused\|needs_review\|retired` |
| alignment_state | `aligned\|needs_review\|overridden` |

### 3. DossierOffering

**Decisión:** **dossier-scoped v1** (no catálogo tenant global todavía).

Tabla `dossier_offerings`: nombre, aliases[], taxonomies (CPV/keywords), description,
`intent_revision_id`, status `active|retired`. Justificación: la oferta estratégica cambia por
expediente; un catálogo tenant se evaluará cuando ≥2 expedientes compartan ofertas sin fricción.

### 4. Schemas de intake (`schema_key` + `schema_version`)

| Key | Version inicial | Notas |
|---|---|---|
| `market` | `v1` | ya en código post-MEMSOL-00; geografía global ISO-2 |
| `procurement` | `v1` | subtipo `tender\|grant\|framework`; CPV, compradores, elegibilidad |
| `research` | `v1` | pregunta/tesis; `InvestigationRun` = ejecución, no el tipo de expediente |
| `competitive-intelligence` | `v2` | v1 actual en `profile_config` se proyecta; v2 alinea con IntentRevision |
| `custom` | `v1` | genérico |

`profile_config` permanece como **proyección expand/contract** hasta backfill contado; no crece
como bolsa sin historial. Escrituras nuevas preferirán IntentRevision.

### 5. Provenance de acciones

Todo `Watchlist`, `SignalMonitor`, `ProcurementSearchWatch`, pregunta, informe y automation
guardará:

```text
intent_revision_id?
requirement_id?
offering_id?
effective_scope_hash
origin: user | intake | assistant | signal | system
confirmed_by_user_id?
manual_overrides: object acotado
alignment_state: aligned | needs_review | overridden
```

### 6. Semántica `needs_review`

Al aceptar una **nueva** IntentRevision:

1. No se mutan monitores/búsquedas/jobs en silencio.
2. Recursos con `intent_revision_id` de la revisión supersedida → `alignment_state=needs_review`.
3. UI/API de Actividad exponen el desalineamiento.
4. El usuario adopta (rebind + scope nuevo), conserva override, o retira el recurso.

### 7. Propiedad de capas de memoria

| Capa | Autoridad | Persistencia |
|---|---|---|
| Intención, requisitos, oferta, decisiones, tareas, conversaciones, jobs, informes | Oracle | PostgreSQL Oracle |
| Corpus externo, chunks, observaciones, facts Signal, monitores, conectores | Signal | PostgreSQL Signal schema `memory` + dominio |
| Evidencia promovida / citas / snapshots de artefacto | Oracle | evidence + context snapshots |
| Proveedor/modelo/fallback/tokens/coste | Signal | AIUsageLog / governance |

### 8. Contrato Oracle ↔ opn_memory

**Decisión:** **HTTP interno versionado** expuesto por Signal bajo namespace dedicado
(propuesta `/api/v1/memory/*` o extensión documentada de `/api/v1/oracle/*` solo lectura de
contexto). Oracle **no** abre SQL a Signal ni importa `app.*`.

Paquete `packages/opn_memory` sigue siendo librería de **host Signal** (y tests). Un adapter
Flask en Oracle (`MemoryContextAdapter`) hablará HTTP con API key de consumer, tenant externo y
`MemoryScope` construido solo desde identidad autenticada.

Payload de retrieval (respuesta):

- `items[]` con `kind`, `id`, `text`, `score`, `source_ref`, `classification`, `occurred_at`
- `coverage_manifest`
- `policy_version`, `request_id`

### 9. coverage_manifest y DossierContextSnapshot

`coverage_manifest` (objeto versionado `coverage_manifest.v1`):

```json
{
  "version": "coverage_manifest.v1",
  "requested": [],
  "consulted": [],
  "failed": [{"source": "", "error_code": ""}],
  "excluded": [{"source": "", "reason": "acl|classification|budget|stale"}],
  "used": [],
  "truncated": false,
  "truncation_notes": [],
  "cutoff_at": null,
  "token_budget": 0,
  "token_used_estimate": 0
}
```

`DossierContextSnapshot` (Oracle, inmutable por ejecución):

- `id`, `tenant_id`, `dossier_id`, `purpose` (`question|report|summary|wizard`)
- `intent_revision_id`, `context_hash`, `payload` (JSON acotado), `coverage_manifest`
- `prompt_name/version`, `schema_name/version`, `created_at`, `job_id?`

### 10. State machines

#### Intent — ver §1

#### Automation / vigilancia (producto)

`prepared → active → paused → needs_attention → retired`
Observado: `idle|running|retrying|error|synced`.
Comandos: prepare, activate, pause, resume, retry, retire. Idempotency-Key en mutaciones.

#### Conversation message (Preguntar a Oracle)

Conversation: `open|archived`.
Message: `queued → running → succeeded|failed|cancelled`.
Pregunta se persiste **antes** de encolar; API devuelve **202** + `job_id` + `message_id`.

#### Report (custom assistant)

`brief_draft → plan_proposed → plan_accepted → generating → reviewing → ready|failed|cancelled`.
Informes genéricos actuales se mantienen. Tasks Signal nuevas:
`report_brief_planner`, `custom_report_writer` (no reutilizar `report_writer` sin benchmark).

#### BackgroundJob (existente, se reutiliza)

`queued|running|retrying|succeeded|failed|cancelled` + lease/heartbeat/cancel cooperativo.

#### Memory analysis request (Signal, MEMSOL-02)

`pending → running → succeeded|failed|cancelled|stale` con CAS, fencing, heartbeat.

### 11. Política IA (actualiza D-015)

- Oracle envía solo `task_key` (+ payload/schema). **Nunca** `provider`/`model` de negocio.
- Signal resuelve primario/fallback/presupuesto/`enabled`.
- Tasks cloud ya operativas para un subset de Oracle **no** autorizan cloud global ni OpenRouter
  por defecto en tasks nuevas de memoria.
- Fallback cloud **prohibido** ante `policy_denied`, budget, classification o inyección.
- Tasks nuevas Memoria Sol: Ollama-first salvo benchmark documentado.

### 12. Retención, tombstones, feedback, embeddings

- Retención por tipo de fuente (Signal) + clasificación; borrado deja tombstone/hash/audit.
- Conversaciones: retención tenant configurable; default alineado a evidencias (p. ej. 365d).
- Feedback humano → propuesta `pending`; **nunca** promueve hecho sin aceptación.
- Embeddings/`pgvector`: **no** en v1; baseline FTS + `pg_trgm`; eval en MEMSOL-05/10.
- Compactación no destructiva: no borra fuentes/versiones para mejorar métricas.

## Agregados (diagrama)

```text
StrategicDossier
  ├─ current_intent_revision_id → DossierIntentRevision*
  ├─ IntelligenceRequirement*
  ├─ DossierOffering*
  ├─ Watchlist / SignalMonitor / ProcurementSearchWatch  (provenance → intent/req)
  ├─ DossierConversation → DossierMessage* → BackgroundJob
  ├─ Report (+ Brief) → BackgroundJob → DossierContextSnapshot
  └─ Evidence / AIContextEvidence

Signal (separado)
  Consumer opn-oracle
  ├─ /ai/run (task_key)
  ├─ /oracle/* monitores y entity
  └─ opn_memory schema + future /memory/* retrieval
```

## OpenAPI aditiva (propuesta; implementación MEMSOL-03+)

Prefijo `/api/v1/dossiers/{dossier_id}/…`. problem+json. Idempotency-Key en POST de aceptación y
preguntas. ETag/`version` en PATCH drafts.

| Método | Ruta | Permiso | Notas |
|---|---|---|---|
| GET | `/intent` | dossier.read | revisión vigente + lista corta |
| POST | `/intent/drafts` | dossier.write | crea draft |
| PATCH | `/intent/drafts/{id}` | dossier.write | ETag |
| POST | `/intent/drafts/{id}/accept` | dossier.write | 200; no activa monitores |
| POST | `/intent/drafts/{id}/reject` | dossier.write | |
| GET/POST | `/requirements` | dossier.read/write | |
| GET/POST | `/offerings` | dossier.read/write | |
| GET | `/activity` | dossier.read | read model (MEMSOL-04) |
| POST | `/conversations/{id}/messages` | dossier.read+ | **202** (MEMSOL-06) |
| POST | `/reports/custom` | report.generate | **202** (MEMSOL-07) |

## Permisos

Reutilizar claves existentes: `dossier.read`, `dossier.write`/`dossier.manage`, `report.generate`,
`task.write`, `integration.manage` para monitores. Superadmin: tenant target + motivo + audit.

## Migración / backfill / rollback

| Paso | Política |
|---|---|
| Expand | tablas nuevas + `current_intent_revision_id` nullable + columnas provenance nullable |
| Backfill | por cada dossier con `profile_config` no vacío: crear IntentRevision `accepted` v1 proyectada; contar filas pre/post |
| Dual-write | materialización escribe profile_config **y** revision mientras dure contract |
| Contract | dejar de escribir profile_config en rutas nuevas (fase posterior) |
| Rollback | flags off; columnas nullable; no drop en el mismo release |

Recuento: ejecutar `SELECT count(*) FROM strategic_dossiers WHERE profile_config <> '{}'` en
migración de test/prod antes del backfill (no inventar cero).

## Audit events

`intent.draft_created`, `intent.accepted`, `intent.rejected`, `intent.superseded`,
`requirement.created|updated|retired`, `offering.created|updated`,
`automation.needs_review`, `question.enqueued|succeeded|failed|cancelled`,
`report.custom_enqueued|ready|failed`, `memory.context_built`, `memory.feedback_proposed`.

## Alternativas descartadas

| Alternativa | Motivo |
|---|---|
| Solo agrandar `profile_config` | sin historial ni provenance de acciones |
| Catálogo tenant de offerings en v1 | complejidad prematura |
| SQL Oracle→Signal | viola fronteras y multi-tenant |
| pgvector por defecto | sin eval vs FTS |
| LLM elige monitores al aceptar intake | autoactivación prohibida |
| Segundo orquestador de jobs en Signal para UI Oracle | BackgroundJob Oracle es la verdad de producto |

## Consecuencias

- MEMSOL-02 endurece Signal memory sin depender del schema Oracle.
- MEMSOL-03 implementa tablas/API IntentRevision + backfill.
- Tasks/Q&A/informes esperan snapshots y provenance de esta ADR.
