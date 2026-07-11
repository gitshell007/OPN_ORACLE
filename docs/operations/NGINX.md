# Operación de Nginx

Nginx termina TLS en el host y es el único proxy confiable. Flask usa
`TRUSTED_PROXY_COUNT=1`; los puertos `3000` y `8000` deben permanecer enlazados exclusivamente a
loopback. Las plantillas versionadas están en `infra/nginx/` y no se instalan automáticamente.

## Archivos

| Origen versionado | Destino host |
|---|---|
| `infra/nginx/00-oracle-log-format.conf` | `/etc/nginx/conf.d/00-oracle-log-format.conf` |
| `infra/nginx/snippets/oracle-api-proxy.conf` | `/etc/nginx/snippets/oracle-api-proxy.conf` |
| `infra/nginx/snippets/oracle-web-proxy.conf` | `/etc/nginx/snippets/oracle-web-proxy.conf` |
| `infra/nginx/oracle-http.conf` | `/etc/nginx/sites-available/oracle.conf` durante bootstrap |
| `infra/nginx/oracle-https.conf` | `/etc/nginx/sites-available/oracle.conf` tras ACME |

Antes de copiar, guarda el site y snippets existentes en un directorio timestamped bajo
`/var/backups/opn-oracle/config/`. Propietario `root:root`, modo `0644`; activa el site mediante
symlink en `sites-enabled` y desactiva el default solo después de comprobar que no sirve otro
producto.

## Gate y validación

Estas acciones pertenecen a la Etapa B y requieren aprobación. En una sesión SSH de respaldo:

```bash
sudo nginx -t
sudo systemctl reload nginx
curl --fail --resolve oracle.opnconsultoria.com:80:127.0.0.1 \
  http://oracle.opnconsultoria.com/health/live
```

No uses `restart` si basta `reload`. Comprueba después listeners, status de Nginx y logs. El formato
`oracle_safe` usa `$uri`, no `$request_uri`, y omite argumentos, cookies, autorización y referrer.
Enmascara además el segmento secreto del webhook Signal. No lo sustituyas por el formato combined.

## Política de rutas

- `/api/` → Flask/Gunicorn en `127.0.0.1:8000`, sin caché ni buffering.
- `/` → Next standalone en `127.0.0.1:3000`.
- `/health/live` es público y no consulta dependencias.
- `/health/ready` solo admite clientes loopback.
- `/internal/*` y `/metrics` responden `404` en el edge.
- el webhook Signal limita el cuerpo a 1 MiB; el límite general es 26 MiB.
- no se habilita WebSocket porque la aplicación no lo usa.

Revisa rotación de `/var/log/nginx/oracle-*.log`; los logs técnicos no sustituyen el audit trail de
PostgreSQL.
