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

## Estado actual

| Item | Estado |
|---|---|
| Prep documentada | **sí** (este fichero) |
| Consumer sintético creado | **no** |
| Flags ON en cualquier entorno | **no** |
| Deploy prod | **no** |
EOF

# Also add env example scaffold in Oracle for reference (no secrets)
mkdir -p /Users/gitshellmini/PycharmProjects/OPN_ORACLE/.worktrees/oracle-dev-memsol-smoke/docs/implementation/memsol
cat > /Users/gitshellmini/PycharmProjects/OPN_ORACLE/.worktrees/oracle-dev-memsol-smoke/docs/implementation/memsol/signal_pilot.env.example <<'EOF'
# Scaffold only — copy to Signal Dev settings.env fragment. All OFF.
# Consumer slug suggestion: opn-oracle-memsol-pilot
MEMORY_ENGINE_ENABLED=0
MEMORY_INGESTION_ENABLED=0
MEMORY_EXTRACTION_ENABLED=0
MEMORY_ANALYST_ENABLED=0
MEMORY_SUMMARIES_ENABLED=0
MEMORY_REFRESH_ENABLED=0
MEMORY_REFRESH_ALLOW_LLM=0
EOF

SCRATCH="/var/folders/bk/s_sj4yz93_31tvsxq9z35t4h0000gn/T/grok-goal-cc1d3fd0d388/implementer"
cat > "$SCRATCH/memsol_signal_pilot_prep.txt" <<'EOF'
# Signal pilot prep paths
docs/implementation/memsol/MEMSOL_SIGNAL_PILOT_PREP.md
docs/implementation/memsol/signal_pilot.env.example
defaults: MEMORY_ENGINE_ENABLED=0 (and related OFF)
activation: not performed
prod: not deployed
EOF
cat "$SCRATCH/memsol_signal_pilot_prep.txt"
