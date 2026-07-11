# Plantillas Nginx de producción

Estas plantillas no instalan ni modifican nada por sí solas. La Etapa B de la fase 14 sigue sujeta
a aprobación explícita. Antes de copiarlas, conserva un backup del site anterior y confirma que
`127.0.0.1:8000` sirve Flask/Gunicorn y `127.0.0.1:3000` sirve el build productivo de Next.js.

## Archivos y contexto

- `00-oracle-log-format.conf` va en `/etc/nginx/conf.d/`; define mapas y `log_format` en contexto
  `http`. El log no contiene query string, referrer, cookies ni cabeceras de autorización y enmascara
  la clave de suscripción del webhook Signal.
- `snippets/oracle-api-proxy.conf` y `snippets/oracle-web-proxy.conf` van en
  `/etc/nginx/snippets/`.
- `oracle-http.conf` es el site bootstrap temporal para liveness y ACME; el resto responde 503 y
  nunca sirve login/API en claro.
- `oracle-https.conf` sustituye al site temporal solo cuando el certificado ya existe.

## Política de exposición

- `/api/` se envía a Flask y `/` a Next; los únicos upstreams son loopback.
- `/internal/*`, incluidas métricas, responde `404` desde el edge.
- `/health/live` es público porque solo expresa vida del proceso y no prueba dependencias.
- `/health/ready` se permite únicamente desde `127.0.0.1`/`::1`, porque revela el estado agregado
  de PostgreSQL y Redis.
- El webhook Signal conserva acceso público firmado, limita el cuerpo a 1 MiB y oculta la clave de
  suscripción en access logs. Su error log usa nivel `crit` para evitar que fallos ordinarios de
  upstream impriman la URI sensible.
- No se configura WebSocket porque la aplicación no lo utiliza.
- API y auth no se cachean en Nginx; Flask conserva la cabecera cliente `Cache-Control: no-store`.
  El límite global de 26 MiB corresponde a los 25 MiB de Flask más overhead multipart.

## Orden seguro de instalación

1. Copiar log format, snippets y `oracle-http.conf` con dueño `root:root` y modo `0644`.
2. Crear `/var/www/certbot/.well-known/acme-challenge` y validar `nginx -t` antes del reload.
3. Comprobar por HTTP los upstreams usando `curl --resolve`; no aceptar login ni datos reales en
   esta ventana temporal sin TLS.
4. Emitir el certificado con email y términos autorizados.
5. Sustituir el site por `oracle-https.conf`, ejecutar `nginx -t`, recargar y validar desde fuera.
6. Probar `certbot renew --dry-run`. HSTS empieza en un día, sin subdominios ni preload; ampliarlo
   únicamente tras observar estabilidad y disponer de rollback.

Nginx debe ser el único proxy confiable de Flask: la aplicación productiva usa
`TRUSTED_PROXY_COUNT=1`. No expongas directamente los puertos 3000 u 8000 fuera de loopback.
