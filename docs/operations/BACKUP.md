# Backup

## Objetivo y procedimiento

Mantener un punto diario recuperable y 30 días locales. Seguir
[BACKUP_RESTORE.md](./BACKUP_RESTORE.md). Para despliegues rápidos se esperan directorio, catálogo
`available` y evidencia de restore aislado; el receipt remoto no bloquea releases salvo que se
active `ORACLE_REQUIRE_OFFSITE_RECEIPT=1`.

La copia cifrada off-host sigue siendo recomendada antes de pasar de UAT a operación estable.

## Fallo y escalado

Revisar `journalctl -u opn-oracle-backup-*`, espacio e inodos. No borrar manualmente para ganar
espacio; usar la rotación validada o ampliar almacenamiento.
