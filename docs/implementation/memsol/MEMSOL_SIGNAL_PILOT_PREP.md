# MEMSOL · Pilot Signal prep (NO activar)

**Producción / flags ON: NO en esta sesión.**  
Documento de preparación para un consumer sintético de Signal con memoria **apagada por defecto**.

## Objetivo

Tener un plan reproducible para un piloto bilateral Oracle↔Signal sin tocar prod ni habilitar cobros.

## Consumer sintético (placeholder)

| Campo | Valor propuesto |
|---|---|
| slug | `opn-oracle-memsol-pilot` |
| purpose | smoke MEMORY path con datos sintéticos |
| API key | generar con `app.deps.new_api_key_pair()` en Signal Dev **solo** |
| webhook | opcional / deshabilitado en piloto |

**No** rotar ni reutilizar keys de consumidores reales (`opn-oracle` prod, Sentinel, Nexus).

## Flags Signal (defaults OFF)

```bash
# settings.env / env del worker — valores seguros por defecto
MEMORY_ENGINE_ENABLED=0
MEMORY_INGESTION_ENABLED=0
MEMORY_EXTRACTION_ENABLED=0
MEMORY_ANALYST_ENABLED=0
MEMORY_SUMMARIES_ENABLED=0
MEMORY_REFRESH_ENABLED=0
MEMORY_REFRESH_ALLOW_LLM=0
```

Kill switch de producto (además de flags):

- Deshabilitar task_keys de memoria en `ConsumerAISettings` del consumer sintético (`enabled=false` / no en allowlist).
- `AITenantPolicy.kill_switch` en Oracle si se prueba UI (no aplica al host Signal).

## Métricas a observar (solo lectura)

| Métrica | Dónde |
|---|---|
| `ai_usage_logs` por consumer_id sintético | Signal `/admin/api-usage` |
| `memory_jobs` / journal worker queue `memory` | `journalctl -u opn-signal-worker` |
| Coste mes IA vs presupuesto | `/admin/api-usage` + `search_usage` |
| Errores 4xx/5xx en `POST /api/v1/ai/run` | logs API |

## Orden de activación (futuro, requiere autorización explícita)

1. Crear consumer sintético en Signal Dev.
2. Migraciones memory ya en `main` (MEMSOL-02) con flags **OFF**.
3. Smoke con `MEMORY_ENGINE_ENABLED=0` (debe no-op).
4. Solo con OK humano: flip **Dev** `MEMORY_ENGINE_ENABLED=1` + ingestion acotada.
5. Nunca prod en este documento.

## Rollback

1. `MEMORY_ENGINE_ENABLED=0` (y resto de MEMORY_* = 0).
2. Reiniciar `opn-signal-worker` + `opn-signal-beat`.
3. Confirmar ausencia de tareas `memory.*` en journal.
4. Conservar filas DB (no drop).
5. Borrar o desactivar consumer sintético si ya no se usa.

## Scaffold de entorno

Ver `signal_pilot.env.example` en este directorio (todos los flags a 0).

## Estado actual

| Item | Estado |
|---|---|
| Prep documentada | **sí** (este fichero) |
| Consumer sintético creado | **no** |
| Flags ON en cualquier entorno | **no** |
| Deploy prod | **no** |

## Piloto IA real ejecutado (2026-07-31)

- Consumer: `opn-oracle-memsol-pilot` (Signal Dev id 61).
- Tasks: `dossier_question_answer`, `report_custom_brief_plan` (Ollama qwen3.5:9b → Titan qwen3.6:27b).
- Oracle Dev: `AI_MODE=signal`, tenant `memsol-celery-smoke`, `MEMORY_ENGINE_ENABLED=0` en Signal.
- Evidencia en host: `/var/lib/opn-oracle-dev/memsol_ai_pilot_20260731T213008Z/`.
- Kill switch: deshabilitar `ConsumerAISettings.enabled` del consumer 61 (403 `consumer_ai_disabled`).
- Rollback Oracle: restaurar `/etc/opn-oracle-dev/oracle.env.bak-memsol-ai-*` y backup hotpatch en `/var/backups/opn-oracle-dev/memsol-ai-hotpatch-*`.
- **No activar MEMORY.** **No prod.**

## Fallback Ollama→Titan (gate 2026-08-01)

1. Backup `ConsumerAISettings` del consumer sintético (`opn-oracle-memsol-pilot` id 61).
2. Temporal (solo id 61): primary model inexistente (`…-MEMSOL-FALLBACK-GATE-DOES-NOT-EXIST`) + `fallback_on_status` con **404** (además de 408/429).
3. `POST /api/v1/ai/run` por task key → Titan real (`ollama_titan`/`qwen3.6:27b`, `fallback_used=true`).
4. **Path durable Oracle (obligatorio si Titan ok):** Celery `oracle.dossier_question.answer` y `oracle.report.custom_brief.plan` con `AI_MODE=signal`; GET message/report con `provider_path=signal` + `AIArtifact`; correlacionar `ai_usage_logs` (logger Signal: **1 fila final** efectiva titan, no fila separada del primario).
5. Coerción Titan en `apps/api/src/opn_oracle/ai/schemas.py` (confidence 0–1→0–100; notes/formats string→list) — necesaria para persistir salida Titan válida.
6. Kill switch: `enabled=false` → 403 `consumer_ai_disabled` + usage delta 0; re-enable limited + **restore backup bit-for-bit** (model `qwen3.5:9b`, `fallback_on_status=[429]`).
7. No OpenRouter. No prod. MEMORY off.

### Evidencia gate (redactada)

| Clave | IDs |
|---|---|
| Ask durable | job `459abd72-…` · message `259ab833-…` · artifact `685536d3-…` · usage **4471** |
| Brief durable | job `5dbe7a68-…` · report `1a30a856-…` · artifact `01b6bb59-…` · usage **4470** |
| Signal `/ai/run` only | usage **4461** (ask) · **4462** (brief) |
| Host Oracle | `/var/lib/opn-oracle-dev/memsol_fallback_oracle_capture_20260731T224331Z/` |

### Rollback

1. Restaurar `ConsumerAISettings` del consumer 61 desde backup (models `qwen3.5:9b`, `fallback_on_status=[429]`, tokens 2500/2000).
2. Confirmar `enabled=true` limited + `MEMORY_ENGINE_ENABLED=0`.
3. No dejar primary model inventado ni `fallback_on_status` ampliado en Dev.

