# Matriz expand/contract · memoria dual (plan MDEV-01; no aplicar en Dev)

## Principio

- Expand: columnas/tablas nuevas nullable o con default seguro; código dual-write/read.
- Contract: retirar campos solo tras deploy que deja de leerlos.
- Backfill: job idempotente con recuentos pre/post y downgrade documentado.

## Signal

| Cambio | Fase | Expand | Contract | Backfill | Recuentos |
|---|---|---|---|---|---|
| `consumer_memory_settings` table o JSON versionado | MDEV-02/03 | crear tabla + etag | n/a | default OFF para todos | consumers, settings rows |
| `api_credentials.bound_external_tenant_id` | MDEV-02 | columna nullable | require non-null | bind keys existentes 1:1 o revocar | credentials |
| memory sources multi-scope links | MDEV-05 | rows por scope | n/a | re-scope pilot→dossier en UAT sintético | sources by scope |
| alembic `20260731_mem_lifecycle` en Dev | MDEV-10 | upgrade | downgrade script | 0 rows affected expected | alembic_version_memory |

## Oracle

| Cambio | Fase | Expand | Contract | Backfill | Recuentos |
|---|---|---|---|---|---|
| tenant memory mode + IntegrationConnection signal-memory | MDEV-04 | columns/settings | n/a | default disabled | tenants, connections |
| dossier_memory_profiles | MDEV-04 | tabla etag | n/a | none | profiles |
| evidence materialization from signal items | MDEV-05/06 | evidence rows | n/a | on-demand | evidence |

## No en MDEV-01

No se aplican migraciones en Dev ni se activan flags.
