# Matriz expand/contract · memory dual (MDEV-01 REWORK)

No se aplica ninguna migración en hosts Dev/Prod en MDEV-01.

## Signal expand (propuesto MDEV-02)

| Cambio | Expand | Backfill | Recuentos pre | Downgrade |
|---|---|---|---|---|
| `consumer_tenant_credentials` | CREATE TABLE nullable-free | 0 rows | consumers N; credentials 0 | DROP TABLE |
| partial unique active per consumer+tenant | CREATE UNIQUE INDEX ... WHERE status='active' | n/a | 0 | DROP INDEX |
| `consumer_memory_dossier_grants` | CREATE TABLE | 0 rows | grants 0 | DROP TABLE |
| optional deprecate sole use of `consumers.api_key_hash` for memory | dual-read | n/a | credentials active by tenant | keep column |

## Oracle expand (MDEV-04)

| Cambio | Expand | Backfill | Recuentos | Downgrade |
|---|---|---|---|---|
| IntegrationConnection provider `signal-memory` | filas nuevas | 0 | connections | delete rows |
| tenant memory mode disabled\|shadow\|augment | columna/default disabled | all disabled | tenants | drop column later |

## Contract phase later

Retirar path legacy memory sin tenant-bound solo cuando recuento de credenciales active cubra todos los tenants Oracle Dev canarios.
