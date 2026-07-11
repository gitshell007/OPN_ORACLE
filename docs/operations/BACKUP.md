# Backup

## Objetivo y procedimiento

Mantener un punto diario recuperable, 30 días locales y copia cifrada off-host. Seguir
[BACKUP_RESTORE.md](./BACKUP_RESTORE.md). Se esperan directorio, catálogo `available`, evidencia
de restore y receipt remoto; la ausencia de cualquiera bloquea releases.

## Fallo y escalado

Revisar `journalctl -u opn-oracle-backup-*`, espacio e inodos. No borrar manualmente para ganar
espacio; usar la rotación validada o ampliar almacenamiento.

