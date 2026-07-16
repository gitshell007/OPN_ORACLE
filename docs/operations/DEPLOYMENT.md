# Despliegue de producción

Este runbook describe la Etapa B. A 11 de julio de 2026 la infraestructura base, TLS, PostgreSQL y
Redis están provisionados; la capa de aplicación permanece detenida de forma fail-closed hasta
materializar el secreto de Graph y completar los gates de bootstrap/backup. El control cotidiano se
realiza con `scripts/oracle-control.sh`, documentado en `CONTROL_CENTER.md`.

## Modelo de release inicial

Mientras no se elija registry, el modelo propuesto construye un artefacto versionado en el host:

```text
/opt/opn-oracle/releases/<release-id>/
/opt/opn-oracle/current -> releases/<release-id>
/etc/opn-oracle/oracle.env
/etc/opn-oracle/secrets/*
/var/backups/opn-oracle/
```

No copies `.git`, `.env`, credenciales ni resultados de tests. El release ID debe ser inmutable
(commit + timestamp o digest aprobado). `oracle.env` parte de
`infra/production/oracle.env.example`; nunca contiene contraseñas. El manifiesto exacto de secrets
está en `infra/production/SECRETS.md`.

Los secretos consumidos por API/migrate/workers necesitan UID/GID numérico `10001:10001` y modo
`0400`. `postgres_admin_password` y `redis_password` pueden quedar `root:root 0400`; los secretos
`postgres_migrator_password` y `postgres_app_password` deben pertenecer al UID/GID `postgres` de la
imagen, que se verificará antes de aplicarlos (habitualmente 999, nunca supuesto a ciegas). Verifica
el comportamiento de bind mounts de la versión de Compose instalada: no confíes en `uid/mode` del
YAML. `/etc/opn-oracle` y releases deben ser `0750` o más restrictivos según el usuario deploy.

## Preflight

Con la segunda sesión SSH abierta y después del backup autorizado:

```bash
cd /opt/opn-oracle/current
docker version
docker compose version
ORACLE_SECRETS_DIR=/etc/opn-oracle/secrets \
  docker compose --env-file /etc/opn-oracle/oracle.env \
  -f compose.prod.yml config --quiet
sudo nginx -t
ss -lntp
```

`config --quiet` debe terminar 0. No publiques su salida en tickets: aunque el Compose usa secret
files, la configuración no secreta puede ser operativamente sensible. Confirma que 5432/6379 no
están publicados y que 3000/8000 solo se enlazarán a `127.0.0.1`.

## Modo rápido de despliegue

Mientras Oracle está en construcción/UAT, el camino normal es rápido y local:

1. preparar un release nuevo desde el commit validado, sin `.git`, `.env`, secretos ni artefactos de
   tests;
2. crear backup lógico local en `/var/backups/opn-oracle`;
3. verificar restore aislado para ese mismo backup;
4. activar con `oracle-control update <release-id>`;
5. ejecutar health/smoke público.

No se parchea el release activo in-place. Si el cambio es pequeño, el release puede prepararse desde
un `git archive` o copiando el árbol validado a `/opt/opn-oracle/releases/<release-id>` y generando
`RELEASE_SHA256SUMS`. Esto cuesta poco más que un `git pull`, pero mantiene rollback mediante el
symlink `/opt/opn-oracle/current`.

Ejemplo desde una copia local ya validada y pusheada:

```bash
commit="$(git rev-parse --short HEAD)"
release="$(date -u +%Y%m%dT%H%M%SZ)-quick-$commit"
git archive --format=tar HEAD | ssh root@oracle.opnconsultoria.com \
  "install -d -m 0750 /opt/opn-oracle/releases/$release && tar -x -C /opt/opn-oracle/releases/$release"
ssh root@oracle.opnconsultoria.com \
  "cd /opt/opn-oracle/releases/$release && find . -type f ! -name RELEASE_SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > RELEASE_SHA256SUMS"
ssh root@oracle.opnconsultoria.com \
  "install -o root -g root -m 0755 /opt/opn-oracle/releases/$release/scripts/oracle-control.sh /usr/local/sbin/oracle-control"
```

Después, en el host:

```bash
release_id="ID_DEL_RELEASE_PREPARADO"
sudo oracle-control backup
sudo oracle-control restore-test /var/backups/opn-oracle/ID_BACKUP/MANIFEST.txt
sudo oracle-control update "$release_id"
sudo oracle-control health
/opt/opn-oracle/current/scripts/smoke-production.sh https://oracle.opnconsultoria.com
```

### Poda de imágenes por release

La poda de imágenes Docker se ejecuta en la rama de éxito de `oracle-control update`, no dentro de
`deploy-production.sh`. La razón operativa es que `oracle-control` es quien conoce con certeza el
estado de activación (`current`, `CURRENT_RELEASE` y `PREVIOUS_RELEASE`); si el smoke o el deploy
fallan, los punteros se restauran y no se borra ninguna imagen.

Tras una activación correcta, `oracle-control` elimina solo imágenes locales
`opn-oracle-api:<release>` y `opn-oracle-web:<release>` de releases antiguos. Conserva siempre el
release activo, `PREVIOUS_RELEASE` y las tres entradas más recientes de `/opt/opn-oracle/releases`,
dejando rollback barato y evitando que un histórico largo llene el disco.

## Backup gate

El gate rápido exige un manifiesto local con timestamp, release, snapshot/`pg_dump`, checksum y
evidencia de restore aislado. El script de despliegue exige `ORACLE_BACKUP_MANIFEST` y
`ORACLE_BACKUP_RESTORE_EVIDENCE` legibles y valida que la evidencia corresponde al manifiesto antes
de tocar la aplicación.

El flujo reproducible, sus garantías y el gate separado para un bootstrap vacío están definidos en
`docs/operations/BACKUP_RESTORE.md`. Para upgrades, valida además que la evidencia corresponde
exactamente al manifiesto antes de ejecutar Alembic:

```bash
./scripts/restore-test-production.sh --check-evidence \
  "$ORACLE_BACKUP_MANIFEST" "$ORACLE_BACKUP_RESTORE_EVIDENCE"
```

La copia cifrada off-host queda como modo estricto opcional. Para activarlo:

```bash
export ORACLE_REQUIRE_OFFSITE_RECEIPT=1
```

En ese modo, `oracle-control update` y `deploy-production.sh` vuelven a exigir
`ORACLE_BACKUP_OFFSITE_RECEIPT`.

## Aplicación

Tras registrar formalmente la aprobación de Etapa B:

```bash
cd /opt/opn-oracle/current
ORACLE_ENV_FILE=/etc/opn-oracle/oracle.env \
ORACLE_SECRETS_DIR=/etc/opn-oracle/secrets \
ORACLE_BACKUP_MANIFEST=/ruta/al/manifiesto-verificado \
ORACLE_BACKUP_RESTORE_EVIDENCE=/ruta/a/evidencia-restore \
./scripts/deploy-production.sh --apply-authorized-stage-b
```

El script valida config/secrets, construye imágenes, arranca PostgreSQL/Redis, ejecuta Alembic una
sola vez mediante el perfil `release`, arranca API/worker/beat/web y realiza smoke loopback. No
instala paquetes, no modifica Nginx/UFW/SSH, no emite TLS y no crea usuarios.

Después del smoke loopback, instala primero el Nginx HTTP siguiendo `NGINX.md`; emite el certificado
según `TLS.md`; después ejecuta:

```bash
./scripts/smoke-production.sh https://oracle.opnconsultoria.com
```

## Bootstrap y validación funcional

El primer superadmin se crea de forma interactiva, sin password en argumentos:

```bash
docker compose --env-file /etc/opn-oracle/oracle.env -f compose.prod.yml run --rm -it api \
  flask --app opn_oracle.wsgi:app admin bootstrap-superadmin \
  --email EMAIL_AUTORIZADO --name 'NOMBRE_AUTORIZADO' --confirm-production
```

El comando vuelve a pedir confirmación y password sin eco. Sustituye únicamente email/nombre tras
la aprobación; no guardes el comando con datos personales en un log público.

Verificación final de la fase:

- `docker compose ps` sano y un único beat;
- `/health/live`, readiness desde loopback y `/api/v1/meta`;
- login, CSRF, cookie `Secure`/`HttpOnly`/`SameSite=Lax` y logout/revocación;
- tenant A no accede a tenant B y runtime `oracle_app` conserva `NOBYPASSRLS`/sin DDL;
- enqueue/poll de job y respuesta del worker tras reinicio controlado;
- listeners externos solo 22/80/443; PostgreSQL/Redis privados;
- logs sin query strings, passwords, cookies, tokens o payloads secretos;
- certificado/redirect/renewal y backup/restore comprobados.

No habilites `DOCUMENTS_ENABLED`, Signal HTTP, IA real, PDF ni métricas públicas. Con 3,7 GiB,
parsing/IA requieren ampliar recursos y completar S3, ClamAV, sandbox y proveedores.

## Parada y diagnóstico

Usa `docker compose stop` para una parada controlada y conserva volúmenes. No uses `down -v` en
producción. Revisa `docker compose ps`, health y logs acotados; no vuelques `docker inspect` o el
entorno completo en salidas compartidas. Para fallo de release sigue `ROLLBACK.md`.
