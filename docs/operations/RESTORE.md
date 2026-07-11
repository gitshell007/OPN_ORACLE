# Restore

## Objetivo y procedimiento

Recuperar PostgreSQL sin sobrescribir la base activa. Seguir
[BACKUP_RESTORE.md](./BACKUP_RESTORE.md): checksums, restore aislado y después
`restore-production.sh` con operación aprobada y TTY. Se espera base nueva validada, swap por
rename y base anterior conservada.

## Fallo y rollback

Si el smoke falla, revertir el swap y preservar ambas bases. Nunca usar `DROP DATABASE`, `--clean`
ni `docker compose down -v`.

