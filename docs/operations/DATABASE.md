# PostgreSQL

## Objetivo y procedimiento

Mantener la fuente de verdad y RLS. Seguir [DEPENDENCIES.md](./runbooks/DEPENDENCIES.md): readiness,
conexiones, locks, espacio, índices, Alembic y `oracle_app` `NOBYPASSRLS` sin DDL.

## Fallo

No improvisar SQL de escritura. Preservar evidencia y detener migraciones concurrentes; usar
restore o forward-fix documentado.
