# Backup y restauración de producción

PostgreSQL es la fuente de verdad. Redis no se incluye en el backup: sus sesiones, cachés y
resultados efímeros deben poder reconstruirse a partir de PostgreSQL y los usuarios volverán a
autenticarse tras una pérdida de Redis. Mientras `DOCUMENTS_ENABLED=false`, no existe todavía un
repositorio de objetos que respaldar; antes de habilitar documentos hay que ampliar este runbook
con objetos, metadatos y claves de cifrado.

## Garantías y límites

`scripts/backup-production.sh`:

- ejecuta `pg_dump` desde el contenedor `postgres` ya sano, mediante el socket local y sin exponer
  una contraseña en argumentos o logs;
- crea formato custom comprimido (`gzip`, nivel 6), sin owner pero preservando ACL, y valida el catálogo con
  `pg_restore --list` antes de publicar el directorio final;
- guarda un snapshot de `compose.prod.yml`, plantillas Nginx, contrato de secretos y un inventario
  de `oracle.env`; conserva solo release/versión y redacta los demás valores. Nunca lee ni copia
  `/etc/opn-oracle/secrets`, y rechaza posibles secretos inline en el fichero de entorno;
- genera `MANIFEST.txt`, `ARTIFACT_CHECKSUMS.sha256` y `CONFIG_CHECKSUMS.sha256`;
- escribe primero en un directorio `.partial` y lo mueve al nombre final solo tras validar todo.

Para la fase actual de construcción/UAT, el resultado local verificado sí habilita un despliegue
rápido: manifiesto local, checksums y restore aislado. La copia cifrada off-host queda recomendada,
pero no bloquea releases salvo que el operador active `ORACLE_REQUIRE_OFFSITE_RECEIPT=1`.

Cuando haya uso estable con datos que no puedan perderse, debe volver a exigirse una copia cifrada a
un destino off-host con credencial de escritura limitada, retención/inmutabilidad y monitorización.
El destino, RPO, RTO, rotación y procedimiento de borrado continúan siendo decisiones operativas
explícitas; no se simula una copia remota cuando no existe proveedor configurado.

`scripts/restore-test-production.sh` no acepta host, URL ni nombre de destino. Siempre crea:

- una red Docker interna y aleatoria;
- un volumen efímero nuevo;
- un contenedor `postgres:17-bookworm` sin puertos publicados;
- una base fija denominada `oracle_restore_test`.

Restaura en una única transacción y exige `alembic_version`, al menos una tabla de usuario y cero
índices inválidos. El `trap` elimina contenedor, volumen y red tanto en éxito como en error. La
evidencia registra hashes y contadores, nunca filas ni secretos.

## Crear un backup

Ejecutar desde el release activo con `postgres` sano:

```bash
sudo ORACLE_ENV_FILE=/etc/opn-oracle/oracle.env \
  ORACLE_BACKUP_ROOT=/var/backups/opn-oracle \
  ./scripts/backup-production.sh --create
```

El script devuelve la ruta exacta de `MANIFEST.txt`. No uses la salida de `docker compose config`
ni copies el directorio de secretos dentro del backup. Conserva `root:root 0700/0400` en staging y
aplica las ACL del agente de backup únicamente al origen que necesita leer.

## Probar el restore aislado

```bash
sudo ./scripts/restore-test-production.sh \
  --verify-isolated \
  /var/backups/opn-oracle/ID_BACKUP/MANIFEST.txt
```

Por defecto la evidencia se escribe en
`/var/backups/opn-oracle/restore-evidence/ID_BACKUP.RESTORE_EVIDENCE.txt`. Puede cambiarse solo a
otra ruta absoluta, local y no enlazada:

```bash
sudo ORACLE_RESTORE_EVIDENCE_ROOT=/var/lib/opn-oracle/restore-evidence \
  ./scripts/restore-test-production.sh --verify-isolated /ruta/MANIFEST.txt
```

Para validar después que una evidencia pertenece exactamente al manifiesto y dump actuales:

```bash
./scripts/restore-test-production.sh \
  --check-evidence \
  /ruta/MANIFEST.txt \
  /ruta/RESTORE_EVIDENCE.txt
```

Cambiar un byte del dump, manifiesto, snapshot o evidencia invalida el gate. La evidencia local no
demuestra la copia off-host; en modo estricto el pipeline de backup debe adjuntar además el
receipt/version ID del proveedor y verificar periódicamente una descarga desde ese destino.

## Gate de release

En un upgrade rápido con volumen PostgreSQL existente, antes de Alembic se exigen tres pruebas:

1. `MANIFEST.txt` y todos sus checksums válidos;
2. evidencia válida de restore aislado para ese mismo hash;
3. release anterior y procedimiento de rollback disponibles.

El verificador local del punto 2 es:

```bash
./scripts/restore-test-production.sh --check-evidence \
  "$ORACLE_BACKUP_MANIFEST" "$ORACLE_BACKUP_RESTORE_EVIDENCE"
```

El modo estricto añade una cuarta prueba: receipt comprobado de la copia cifrada off-host. Se activa
con `ORACLE_REQUIRE_OFFSITE_RECEIPT=1` y `ORACLE_BACKUP_OFFSITE_RECEIPT=/ruta/receipt`.

El primer despliegue en un host auditado sin volumen previo debe usar un gate de bootstrap vacío
distinto; no debe fabricar un manifiesto ni relajar el gate de upgrades. Inmediatamente después de
migrar y antes de cargar datos reales, crea backup y restore aislado. La copia off-host se configura
cuando el proyecto pase de UAT a operación estable.

## Automatización diaria y retención de 30 días

La automatización se instala desde el release activo con:

```bash
sudo /opt/opn-oracle/current/scripts/install-backup-systemd.sh --install
```

`opn-oracle-backup-schedule.timer` encola una operación idempotente cada día a las 02:15
(`Europe/Madrid`), con hasta 30 minutos de dispersión. `opn-oracle-backup-agent.timer` procesa una
solicitud manual o programada cada minuto. El agente privilegiado reclama la operación mediante el
CLI Flask, ejecuta el dump, verifica un restore efímero y registra solo metadata no sensible.

La ubicación local es **`/var/backups/opn-oracle/<backup-id>/`**. Las evidencias viven en
`/var/backups/opn-oracle/restore-evidence/`. La configuración queda en
`/etc/opn-oracle/backup.conf` (`root:root 0600`). Se conservan 30 días por defecto. La rotación solo
elimina directorios reconocidos con manifiesto y checksums válidos, nunca borra el backup válido más
reciente, respeta el marcador `.RETAIN`, rechaza enlaces y no cruza otros filesystems.
Los nombres eliminados pasan por el canal estructurado root-only
`.pending-expirations/*.names`; el agente los marca `expired` en el catálogo y reintenta cualquier
ledger pendiente antes de reclamar otro trabajo. `--prune` directo se rechaza si no recibe el canal
estructurado; la vía normal es el agente para mantener filesystem y catálogo sincronizados.
La copia preventiva de un restore usa `ORACLE_SKIP_PRUNE=1`: una ventana de recuperación nunca es
el momento de eliminar puntos de restauración.

```bash
systemctl list-timers opn-oracle-backup-*.timer
journalctl -u opn-oracle-backup-schedule.service -u opn-oracle-backup-agent.service
sudo systemctl start opn-oracle-backup-schedule.service
sudo systemctl start opn-oracle-backup-agent.service
```

El botón manual de Super Admin crea una operación durable: no ejecuta shell desde HTTP ni entrega
privilegios al contenedor. El agente host es el único consumidor.

## Recuperación solicitada desde Super Admin

Una recuperación queda esperando aprobación: **ningún timer ejecuta restores**. Un operador root
debe abrir una ventana e iniciar el script en una TTY:

```bash
sudo /opt/opn-oracle/current/scripts/restore-production.sh \
  --operation-id UUID \
  --manifest /var/backups/opn-oracle/ID_BACKUP/MANIFEST.txt
```

Se exige la frase `RECUPERAR <operation-id> <backup-id>`, checksums, evidencia aislada y un backup
previo nuevo. El restore se ejecuta como `oracle_migrator` en una base nueva y valida Alembic,
tablas, índices, RLS, owners y permisos de `oracle_app`. Solo después detiene web/API/workers/beat y
hace swap por rename. La base anterior se conserva como `opn_oracle_before_<timestamp>`; nunca usa
`DROP`. Si el arranque o smoke falla, revierte el swap y conserva la base fallida para análisis.

El script reclama la operación con `backup-agent claim-restore` después de la frase root y la cierra
con `backup-agent complete` tras el smoke. Ante fallo intenta registrar un código genérico sin datos
de negocio. Conserva journal, evidencia y backup previo; un HTTP aislado no es evidencia suficiente.

## Copia off-host y política extendida

Cuando se configure el proveedor off-host:

- ejecutar backup lógico al menos diariamente y antes de cada migración;
- mantener varias ventanas (diaria/semanal/mensual) conforme al RPO y obligaciones aplicables;
- cifrar antes de salir del host y custodiar la clave fuera del mismo servidor;
- alertar por ausencia de backup, checksum fallido, falta de copia remota o restore fallido;
- ejecutar restore desde una descarga off-host, no solo desde staging local;
- registrar duración, tamaño y evidencia sin datos de negocio ni secretos;
- probar la recuperación completa trimestralmente y tras cambios de PostgreSQL/migraciones.

Nunca uses `docker compose down -v`, `DROP DATABASE`, `pg_restore --clean` contra producción ni una
URL proporcionada externamente para una prueba. Una recuperación real sobre producción requiere
incidente declarado, backup preservado, ventana aprobada y validación previa en entorno aislado.

## Evidencia inicial de producción · 2026-07-11

- backup ID: `20260711T134728Z-20260711T134718Z-ops-fixes`;
- manifest productivo: `/var/backups/opn-oracle/<backup-id>/MANIFEST.txt`;
- restore aislado: correcto, sin puertos, con evidencia en `restore-evidence/`;
- copia off-host: archivo cifrado AES-256-CBC con PBKDF2-SHA256 y 200.000 iteraciones en el
  OneDrive corporativo `DESARROLLO_PRODUCTOS/OPN_ORACLE/BACKUPS_PRODUCCION`;
- checksum del archivo cifrado:
  `e583adb80ebedd9883c6fabed41bdab599c755d1a03946b4c4b9aa12c0db7a63`;
- clave: fichero local `~/.config/opn-oracle/backup-encryption.key`, modo `0600`, fuera del servidor
  y fuera de OneDrive. Debe incorporarse a un gestor de secretos/escrow antes de considerar resuelto
  el escenario de pérdida simultánea del Mac operador.
