# Mapa de servicios de producción

Topología inicial para el host único auditado de 2 vCPU y 3,7 GiB. Es una capacidad de arranque,
no una garantía para carga real; IA, documentos y Signal HTTP permanecen deshabilitados.

El host dispone de zram swap de 1,9 GiB con prioridad 100 como defensa frente a picos; no sustituye
la ampliación de RAM ni autoriza a aumentar concurrencia.

| Servicio | Exposición | Autoridad/datos | Límite inicial | Salud |
|---|---|---|---|---|
| Nginx host | `:80`, `:443` públicos | TLS y proxy | host | `nginx -t`, HTTPS |
| `web` | `127.0.0.1:3000` | presentación Next | 512 MiB | `/login` |
| `api` | `127.0.0.1:8000` | Flask/Gunicorn | 640 MiB | `/health/live` |
| `worker-core` | ninguno | Celery, jobs durables en PG | 768 MiB | inspect ping/proceso |
| `beat` | ninguno | scheduler único | 128 MiB | proceso + schedules DB |
| `postgres` | solo red Docker privada | fuente de verdad | 768 MiB | `pg_isready` |
| `redis` | solo red Docker privada | sesiones/caché/colas, no negocio | 384 MiB | `PING` autenticado |

Redis separa DB lógicas: aplicación `0`, sesiones `1`, rate limit `2`, broker `3` y resultados `4`.
PostgreSQL usa `oracle_migrator` con `BYPASSRLS` solo para release y `oracle_app` con
`NOBYPASSRLS` para API/workers. `migrate` es un job de release, no un daemon.

Flujo de red:

```text
Internet -> Nginx :80/:443 -> loopback :3000 web
                              loopback :8000 API
API/worker/beat -> red interna -> PostgreSQL / Redis
```

Solo un `beat`. La primera versión consolida colas operativas en un worker con concurrencia 1 por
la RAM disponible; ampliar a 8 GiB y separar colas antes de habilitar parsing o IA real. PostgreSQL
y Redis no llevan `ports:` en Compose y no deben aparecer en `ss -lntp` del host.
