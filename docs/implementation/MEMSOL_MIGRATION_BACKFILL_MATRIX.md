# Matriz de migración / backfill · Memoria Sol

## Oracle (MEMSOL-03)

| Artefacto | Estrategia | Recuento | Rollback |
|---|---|---|---|
| `dossier_intent_revisions` | expand create | n/a | drop solo si vacío y no prod |
| `intelligence_requirements` | expand create | n/a | idem |
| `dossier_offerings` | expand create | n/a | idem |
| `strategic_dossiers.current_intent_revision_id` | expand nullable FK | all dossiers | nullify |
| provenance columns on watchlist/monitors/watches | expand nullable | count resources | nullify |
| Backfill IntentRevision from profile_config | job/script contado | `profile_config <> '{}'` | mark supersede drafts only; keep rows |
| Dual-write profile_config | contract later | — | stop dual-write flag |

**Política:** expand/contract; una migración por release; no drop en el mismo release que el backfill.

## Signal (MEMSOL-02)

| Artefacto | Estrategia | Notas |
|---|---|---|
| CAS/heartbeat/cancel en analysis_requests | expand columns if missing | flags remain OFF |
| Remove pilot defaults from productive paths | code | `memory_target_entities` no default productivo |
| Isolation negative tests | tests | consumer/tenant/dossier |
| Internal memory retrieval endpoint | additive API OFF by default | no release force-on |

## Filas afectadas

Ejecutar antes del backfill Oracle (no inventar):

```sql
SELECT count(*) FROM strategic_dossiers WHERE profile_config IS NOT NULL AND profile_config::text NOT IN ('{}', 'null');
SELECT count(*) FROM strategic_dossiers WHERE type = 'market';
SELECT count(*) FROM strategic_dossiers WHERE type = 'competitive_intelligence';
```
