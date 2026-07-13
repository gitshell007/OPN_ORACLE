# Plan propuesto de cambios de producción

**Estado:** artefactos locales preparados; aplicación remota **NO autorizada**  
**Target:** `oracle.opnconsultoria.com`, servidor único auditado en F14-A  
**Downtime previsto:** ninguno para servicios existentes; el host no sirve web actualmente

Este documento describe el diff. No se aplicará ninguna acción de Etapa B hasta aprobación escrita
del usuario después de revisar `SERVER_AUDIT_2026-07-11.md`. Los cambios SSH requieren una
aprobación separada y una sesión de respaldo.

## Decisiones requeridas antes de aplicar

1. Rotar inmediatamente la contraseña root expuesta, por consola/sesión interactiva y sin historial.
2. Confirmar email de Let's Encrypt y autorización para aceptar términos/emitir certificado.
3. Confirmar destino, cifrado, retención, RPO y RTO de backups off-host antes de operación estable
   con datos críticos; no bloquea el modo rápido UAT.
4. Confirmar método de entrega: build versionado en servidor o imágenes de registry.
5. Confirmar email/nombre del primer superadmin; contraseña solo interactiva.
6. Confirmar Microsoft Graph (`Mail.Send`, consentimiento, client secret) y remitente. Signal HTTP, IA real y documentos deben seguir deshabilitados hasta
   completar contratos/proveedores/S3/ClamAV/sandbox.
7. Decidir si se amplía RAM a 8 GiB antes de datos reales. El plan base cabe de forma ajustada en
   4 GiB únicamente con features externas deshabilitadas y concurrencia 1.

## Cambios locales preparados

Sin mutar el servidor se ha preparado y revisado el diff de:

| Ruta | Propósito |
|---|---|
| `Dockerfile.web` | build multi-stage Next, runtime Node no-root y `next start` |
| `compose.prod.yml` | web/API/worker/beat/PostgreSQL/Redis, redes y secrets; sin tags `latest` |
| `infra/nginx/{oracle-http,oracle-https}.conf` | HTTP ACME temporal y HTTPS final |
| `infra/redis/redis.conf` | persistencia, `noeviction`, protected mode y ACL montada como secret |
| `infra/postgres/init/*` | roles migrator/runtime leyendo secretos desde files, sin exponerlos |
| `scripts/deploy-production.sh` | gate de backup, migration única y smoke; no toca Nginx/UFW/SSH |
| `docs/operations/{DEPLOYMENT,NGINX,TLS,SERVICE_MAP,ROLLBACK}.md` | runbooks exactos |

El `compose.dev.yml` no se reutilizará tal cual: publica DB/Redis a loopback, usa entorno development
y demasiados workers para este host. Se conservará para desarrollo.

## Cambios remotos propuestos

| Ruta/recurso | Owner/permisos propuestos | Acción |
|---|---|---|
| `/opt/opn-oracle/releases/<release>` | root:oracle-deploy 0750 | artefacto versionado |
| `/opt/opn-oracle/current` | symlink root:root | activar release atómicamente |
| `/etc/opn-oracle/oracle.env` | root:oracle-deploy 0640 o más restrictivo | config sin imprimir valores |
| `/etc/opn-oracle/secrets/*` | UID del consumidor y 0400, ver manifiesto | DB, Redis, Flask, integrations |
| `/var/backups/opn-oracle` | root:oracle-deploy 0750 | backups locales UAT, rotación y restore aislado |
| `/etc/nginx/sites-available/oracle.conf` | root:root 0644 | proxy/ACME/TLS sin secretos |
| `oracle-deploy` | password bloqueado, key-only | usuario de despliegue tras validar segunda sesión |

No se copiará `.git` si se despliegan artefactos/imágenes. No se tocarán puerto/config SSH ni se
cerrará la sesión root existente en el mismo cambio de despliegue.

## Paquetes host

Usar repositorios soportados de Ubuntu 26.04, tras `apt-get update` autorizado:

- `docker.io` y `docker-compose-v2` o método oficial si se justifica y fija;
- `nginx`;
- `certbot` y `python3-certbot-nginx`;
- utilidades mínimas de backup/monitoring que se concreten en F15.

No instalar PostgreSQL/Redis host, no hacer distro-upgrade y no desinstalar servicios existentes.

## Firewall propuesto

Orden seguro, con una sesión SSH de respaldo:

1. verificar puerto SSH 22 y acceso por clave;
2. permitir `22/tcp`, `80/tcp`, `443/tcp` en IPv4/IPv6;
3. habilitar UFW con política deny incoming / allow outgoing;
4. confirmar que 3000/8000 solo enlazan `127.0.0.1` y que 5432/6379 no se publican;
5. mostrar estado/diff y verificar una segunda conexión SSH.

No se cambia el puerto SSH. El hardening posterior propuesto (`PasswordAuthentication no`,
`PermitRootLogin prohibit-password`) solo se aplica con aprobación separada, `sshd -t`, console o
sesión de respaldo y reload, nunca restart a ciegas.

## Topología Compose adaptada a 4 GiB

```text
Internet -> Nginx host :80/:443
              -> 127.0.0.1:3000 web Next
              -> 127.0.0.1:8000 API Gunicorn
                         -> red internal: PostgreSQL 17 / Redis 7.4
                         -> worker consolidado concurrency=1 / beat único
```

- `web`: 1 instancia, límite inicial 512 MiB.
- `api`: 2 workers × 2 threads, límite inicial 640 MiB; ajustar tras carga.
- `worker-core`: colas default, maintenance, signals, documents y notifications, concurrencia 1,
  límite inicial 768 MiB. AI no arranca mientras `AI_ENABLED=false`.
- `beat`: 1 instancia, 128 MiB.
- PostgreSQL 17 major fijado, volumen durable, límite inicial 768 MiB.
- Redis 7.4, AOF, ACL, `noeviction`, volumen, límite inicial 384 MiB.
- reservas/límites se validarán con `docker compose config --quiet` y smoke; los números no son
  capacidad final y pueden exigir ampliar el host.
- `web`/`api` solo bind loopback; PostgreSQL/Redis sin `ports:`. Redes `edge` e `internal`.
- restart policies, init, healthchecks y log rotation `json-file` con tamaño/archivos acotados.

## Configuración de aplicación inicial

- `APP_ENV=production`, OpenAPI/debug/mock prototypes deshabilitados.
- `FRONTEND_ORIGIN=https://oracle.opnconsultoria.com`, `TRUSTED_PROXY_COUNT=1`.
- `HSTS_ENABLED=false` durante validación inicial; habilitar solo tras HTTPS estable.
- `METRICS_ENABLED` únicamente si el scrape queda en red privada con token rotado; nunca Nginx
  público.
- `AI_ENABLED=false`, Signal HTTP deshabilitado, PDF disabled y `DOCUMENTS_ENABLED=false` hasta
  cerrar gates productivos.
- sesiones/rate/broker/result usan DB/prefijos Redis separados; Redis nunca es autoridad de negocio.
- roles DB migrator/runtime separados; migration se ejecuta una vez por release.

## Nginx y TLS

1. Crear config HTTP temporal y webroot ACME; `nginx -t` antes de reload.
2. Proxy `/api/` a 8000 y `/` a 3000 con request/proxy headers exactos, no-store sensible, límites
   de upload coherentes y sin `/metrics` público.
3. Verificar por `curl --resolve` y health antes de ACME.
4. Emitir certificado una vez con email aprobado; usar staging si hay reintentos.
5. Redirigir HTTP→HTTPS, verificar chain/SAN/fechas y `certbot renew --dry-run`.
6. Aplicar CSP report-only y recoger reports; enforcement/nonces tras validar Next. HSTS prudente
   después de estabilidad, sin preload.

## Backup y migración

- Antes de migrar: snapshot/provider o backup de cualquier volumen existente (aunque el host está
  limpio) y copia de configs creadas.
- Arrancar PostgreSQL/Redis, crear roles con secrets, ejecutar Alembic una sola vez como migrator.
- Crear backup lógico inicial PostgreSQL + manifiesto/checksum y probar restore en un entorno
  aislado antes de aceptar datos reales.
- El storage documental sigue deshabilitado; cuando se habilite, backup incluye objetos y claves.
- La copia local verificada cuenta como gate de despliegue rápido/UAT. El destino off-host y la
  credencial write-limited se definen antes de operar datos críticos.

## Orden de aplicación propuesto

1. Rotación de root expuesto y verificación key-only en segunda sesión.
2. Backup/snapshot inicial y captura de estado.
3. Crear usuario/rutas/permisos; instalar paquetes.
4. Configurar y verificar UFW sin perder SSH.
5. Entregar release y secrets sin mostrarlos; validar Compose quiet.
6. Arrancar DB/Redis; migrar una vez; backup lógico inicial.
7. Arrancar API/worker/beat/web; smoke loopback y logs redactados.
8. Configurar Nginx HTTP; abrir/verificar 80.
9. Emitir TLS autorizado; verificar HTTPS/renewal; abrir/verificar 443.
10. Bootstrap superadmin interactivo; login/CSRF/cookie/RLS/job/restart.
11. Conservar release/config anterior y entregar evidencia; no habilitar datos reales todavía.

## Verificación

- `docker compose config --quiet`; imágenes por digest/tag fijado y non-root donde proceda.
- listeners: solo 22/80/443 públicos; 3000/8000 loopback; DB/Redis solo red interna.
- `/health/live`, `/health/ready`, `/api/v1/meta`; `/internal/metrics` 404 desde Internet.
- cookie Secure/HttpOnly/SameSite, CSRF/origin, CSP report-only, headers y logs sin secretos.
- RLS con rol runtime, migrator sin servir tráfico y runtime sin DDL/BYPASSRLS.
- worker/beat, enqueue/poll, reinicio controlado y ausencia de jobs duplicados.
- certificado, redirect, chain, hostname, fechas, timer y renewal dry-run.
- backup/checksum/restore, disco, memoria, pool y colas.

## Rollback

- Mantener sesión SSH y configuración Nginx anterior; `nginx -t` antes de cada reload.
- Volver el symlink `current` al release anterior y recrear servicios con Compose validado.
- Si una migración no tiene downgrade seguro, preferir forward-fix o restore verificado; nunca
  improvisar `downgrade` con datos reales.
- Ante fallo de TLS, restaurar server block HTTP de challenge/maintenance sin servir login por HTTP.
- Ante presión de memoria, pausar worker/documentos/IA antes que DB; no cambiar límites a ciegas.
- UFW: revertir solo desde sesión/console de respaldo conservando SSH; nunca bloquear la conexión
  activa.
- Los paquetes instalados pueden quedar; rollback funcional no requiere desinstalarlos.

## Riesgos

- Host único: sin HA; caída del host implica indisponibilidad.
- 4 GiB es ajustado para parsing/IA; producción completa puede requerir upgrade.
- Password root actualmente comprometido y auth por password habilitado: blocker absoluto.
- Sin backup off-host/restore descargado, no hay autorización para operación estable con datos
  críticos.
- CSP enforcement, HSTS, S3/ClamAV/sandbox, Trivy/SBOM y carga staging siguen abiertos.
- Docker group equivale prácticamente a root; el modelo de permisos del deploy debe aprobarse.

## Gate de aprobación

La Etapa B no empieza hasta recibir una respuesta explícita que apruebe este inventario/plan y,
por separado, el cambio SSH. La aprobación debe confirmar al menos rotación root, paquetes,
firewall, paths, Compose, Nginx, emisión Let's Encrypt, ventana, backup y rollback.
