# Consola de control de producción

`scripts/oracle-control.sh` es la interfaz operativa de OPN Oracle para un único servidor. Reúne
estado, health, logs, reinicios, backups, restores aislados, releases, rollback, Nginx, TLS y
recursos sin exponer valores secretos. Está pensada para ejecutarse como `root` o mediante `sudo`:

```bash
sudo oracle-control
sudo oracle-control status
sudo oracle-control health
sudo oracle-control logs api
```

Sin argumentos abre un menú interactivo a color. `NO_COLOR=1` desactiva colores para capturas o
terminales que no los soporten. Las rutas se pueden cambiar con `ORACLE_APP_ROOT`,
`ORACLE_ENV_FILE`, `ORACLE_SECRETS_DIR`, `ORACLE_BACKUP_ROOT`, `ORACLE_DOMAIN`,
`ORACLE_CONTROL_AUDIT_LOG` y `ORACLE_CONTROL_LOCK`, aunque producción debe conservar los valores
por defecto documentados.

## Comandos

| Comando | Efecto |
|---|---|
| `status` | Release activo, systemd, Compose, UFW y listeners relevantes. |
| `health` | Liveness/readiness, web, HTTPS, ping Celery y unicidad de beat. |
| `validate` | Checksums del release, Compose, Nginx, metadata de secrets, red, SSH y UFW. |
| `resources` | Carga, RAM/zram, discos y consumo/espacio Docker. |
| `logs SERVICIO` | Logs acotados por líneas/tiempo; solo servicios permitidos. |
| `tls` | Subject, issuer, SAN, vigencia y estado del timer Certbot. |
| `start`, `stop`, `restart` | Gestiona solo API, web, worker y beat; preserva PostgreSQL/Redis. |
| `restart-service SERVICIO` | Reinicia un servicio de la allowlist; DB/Redis requieren frase exacta. |
| `backup` | Ejecuta el backup lógico existente y ofrece un restore aislado. |
| `restore-test` | Restaura en red, volumen y contenedor efímeros sin puertos publicados. |
| `update` | Activa un release inmutable después de checksums y gates de backup. |
| `rollback` | Cambia solo la aplicación; jamás ejecuta downgrade de esquema. |
| `nginx-reload` | Ejecuta `nginx -t` antes de un reload, nunca un restart directo. |
| `tls-dry-run` | Ensaya Certbot y solo recarga Nginx si la configuración valida. |

Los comandos mutables necesitan TTY y confirmación. Un lock `flock` evita operaciones simultáneas.
Cada mutación terminada se registra en `/var/log/opn-oracle-control.log` con actor, acción,
resultado, release y duración, sin argumentos ni secretos. El fichero es `root:root 0600` y se
rechaza si es un enlace simbólico.

## Actualización segura

La consola no hace `git pull` sobre producción. Primero debe existir un release completo e
inmutable en `/opt/opn-oracle/releases/<release-id>` con `RELEASE_SHA256SUMS`. Después:

```bash
sudo oracle-control update <release-id>
```

La operación solicita tres ficheros regulares: manifiesto de backup, evidencia del restore aislado
y receipt de copia cifrada off-host. Verifica la correspondencia backup/restore, pide la frase
`ACTIVAR <release-id>`, cambia `current` y `ORACLE_RELEASE` de forma atómica y delega la migración y
el despliegue al script productivo. Si el despliegue falla, restaura los punteros de aplicación,
pero nunca intenta revertir automáticamente una migración; se debe diagnosticar y aplicar un
forward-fix compatible.

## Rollback

```bash
sudo oracle-control rollback <release-id>
```

Solo debe usarse si el release elegido es compatible con el esquema ya aplicado. No restaura datos,
no ejecuta Alembic downgrade y no borra volúmenes. Si el smoke falla, recupera el puntero al release
anterior. Consulta también `docs/operations/ROLLBACK.md`.

## Límites deliberados

La consola nunca ejecuta `docker compose down`, `down -v`, `DROP DATABASE`, `pg_restore` sobre la
base productiva, `git pull`, fuerza un push ni imprime contenido de secret files. PostgreSQL y Redis
quedan activos en las paradas normales. Los servicios aceptados son exactamente `api`, `web`,
`worker-core`, `beat`, `postgres` y `redis`; ningún texto del usuario se evalúa como un comando.

## Instalación en el host

En el host actual se instala una copia controlada fuera del release para no modificar un artefacto
inmutable ya firmado:

```bash
sudo install -o root -g root -m 0755 scripts/oracle-control.sh /usr/local/sbin/oracle-control
sudo oracle-control status
```

Los releases nuevos deben incluir el script en su manifest SHA-256. Durante su preparación se puede
actualizar la copia de `/usr/local/sbin` con exactamente el artefacto ya verificado; nunca se modifica
un release activo después de firmar su manifest.
