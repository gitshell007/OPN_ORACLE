# MEMSOL-11 · Rollout preparado (NO ejecutar sin autorización)

**Producción autorizada en esta sesión: NO**

## Orden de despliegue

1. Signal Dev: migraciones memory lifecycle; flags OFF; smoke consumer sintético
2. Oracle Dev: migraciones intent/conversations; E2E bilateral mock/http
3. Shadow read-only corpus sintético
4. Activación por tenant/task con kill switch
5. **Signal producción primero** (compat hacia atrás)
6. **Oracle producción después** (migración una vez por release)
7. Monitor SLO/coste/stale/calidad
8. Rollback: flags off; conservar datos/artefactos; no borrar historia

## Pre-flight (a completar el día del release)

| Check | Estado |
|---|---|
| Backup Postgres Oracle | pendiente autorización |
| Backup Postgres Signal | pendiente autorización |
| `git status` limpio en servidores | pendiente |
| CI SHA exacto verde | pendiente |
| Consumer opn-oracle scopes | documentado |
| Abort criteria | error rate > umbral / coste / aislamiento |
| Rollback owner | TBD |

## Smoke Oracle Dev (evidencia 2026-07-31 · no es autorización de prod)

| Check | Estado medido |
|---|---|
| Host / canal | `oracle-dev` · `/etc/opn-oracle-dev` · release `96250a4` |
| Migraciones 0027/0028 | **aplicadas** (head `20260731_0028`) |
| Worker `-Q …,ai,…` | **active**; tasks MEMSOL registradas |
| Pregunta durable 202→Celery→terminal | **pass** job `e866fc53-…` queue `ai` |
| Custom brief plan | **pass** job `9c48b575-…` plan_status `proposed` |
| Cancel controlado + If-Match | **pass** job `dfed02aa-…` → `cancelled` (retry 409 esperado) |
| Flags AI/MEMORY | OFF / disabled en Dev |
| Producción | **no desplegada** |

## Abort / rollback

- Desactivar `MEMORY_ENGINE_ENABLED` y tasks nuevas (`enabled=false`)
- Revertir release Oracle vía `activate-release` previous
- No drop de tablas en rollback

## Change record template

- Fecha/hora Europe/Madrid:
- SHAs Signal/Oracle:
- Operador:
- Motivo:
- Evidencia smoke:
- Autorización explícita de sesión: **requerida**
