# Rollback de producción

Rollback no autoriza pérdida de datos ni downgrade improvisado. Antes de cada release conserva el
artefacto anterior, el Compose renderizado sin valores, la configuración Nginx y un backup
verificado. Mantén una sesión SSH de respaldo durante cambios de red.

En el modo rápido actual, el backup se considera operativo para rollback de aplicación cuando su
checksum y restore aislado cumplen `BACKUP_RESTORE.md`. Un dump presente pero no restaurado no es
suficiente. La copia cifrada off-host vuelve a ser obligatoria únicamente con
`ORACLE_REQUIRE_OFFSITE_RECEIPT=1`.

## Aplicación

Después de un `oracle-control update` fallido desde `mutation_started`, no asumas que los punteros
han vuelto al release anterior: ejecuta `oracle-control health` y revisa coherencia antes de decidir
rollback o forward-fix.

1. Detener nuevas mutaciones si el fallo puede corromper estado; no borres volúmenes.
2. Recoger estado, health y logs redactados del release fallido.
3. Apuntar `/opt/opn-oracle/current` al release anterior mediante sustitución atómica del symlink.
4. Validar su `compose.prod.yml` y recrear `web`, `api`, `worker-core` y `beat`; no reiniciar
   PostgreSQL/Redis salvo necesidad demostrada.
5. Ejecutar smoke loopback y HTTPS y confirmar jobs antes de reabrir tráfico.

Si el esquema nuevo es compatible por expand/contract, vuelve solo la aplicación. Si no lo es, usa
forward-fix o restaura en un entorno aislado y verifica antes de sustituir datos. Un `alembic
downgrade` solo es admisible cuando la migration concreta declara pérdida nula y se ha probado con
snapshot representativo.

## Nginx/TLS

Restaura el backup del site, ejecuta `nginx -t` y usa `systemctl reload nginx`. Ante un fallo de TLS
mantén únicamente challenge/maintenance por HTTP: nunca login ni API con datos. No borres claves o
certificados durante el rollback.

## Recursos y red

- Si falta memoria, pausa primero colas de documentos/IA y después workers no críticos; protege DB.
- Redis puede reconstruirse solo tras confirmar que PostgreSQL conserva jobs durables; las sesiones
  se perderán y los usuarios deberán reautenticarse.
- No reviertas UFW desde la única sesión activa. Usa consola o segunda sesión y conserva 22/tcp.
- No desinstales paquetes como mecanismo de rollback funcional.

Tras recuperar, registra release, síntomas, timestamps, decisión, backup usado y pruebas. No marques
el incidente resuelto hasta completar health, login/CSRF, RLS, Celery, restart y verificación de
backup/restore.
