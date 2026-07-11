# ADR 0007 — Topología de producción en servidor único

- **Estado:** accepted
- **Fecha:** 2026-07-10

## Contexto

El repositorio no contiene Docker, Nginx, TLS ni CI/CD. El objetivo declarado es `oracle.opnconsultoria.com` en un único servidor. Se han facilitado credenciales en conversación, pero esta fase es exclusivamente local/read-only respecto a infraestructura y no las ha utilizado.

## Decisión

Usar Docker Compose como topología por defecto para API Flask/Gunicorn, frontend Next.js, PostgreSQL, Redis, workers Celery y beat. Nginx en el host terminará TLS y enruta `/api/*` a Flask en loopback y `/` a Next.js en loopback. Certbot gestionará certificados.

PostgreSQL y Redis vivirán exclusivamente en red privada de Compose, sin publicar puertos a Internet. Los secretos se inyectarán fuera de Git con permisos restrictivos. Los releases deberán tener health/readiness, migración única, backup previo y rollback documentado.

## Alternativas consideradas

- **Instalación manual de procesos en el host:** descartada como opción por defecto por menor reproducibilidad y rollback más frágil.
- **Kubernetes:** descartado para un único servidor por coste operativo desproporcionado.
- **Exponer PostgreSQL/Redis al host o Internet:** descartado salvo túnel/mantenimiento excepcional y documentado.
- **TLS dentro del contenedor de aplicación:** no seleccionado; Nginx/Certbot del host simplifican terminación y renovación.

## Consecuencias y riesgos

- Compose dev y prod necesitarán overlays/configuración distintos sin duplicación insegura.
- Migraciones no se ejecutarán en cada réplica/worker, sino una vez por release.
- La disponibilidad queda limitada por un único host hasta diseñar alta disponibilidad.
- Backup sin restauración probada no se considerará control válido.
- Las credenciales compartidas fuera de un canal secreto deben rotarse antes de usar el servidor.

## Cuestiones pendientes

- Auditar de forma read-only OS, recursos, servicios, firewall, DNS A/AAAA y puertos antes de cualquier cambio.
- Confirmar email de Let's Encrypt, destino cifrado de backups, retención y RPO/RTO.
- Confirmar política de imágenes/registry, dominio definitivo y mecanismo CI/CD.
- Preparar diff y rollback; cualquier mutación de servidor requiere autorización explícita posterior.
