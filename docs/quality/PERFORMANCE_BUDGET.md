# Presupuesto inicial de rendimiento

**Estado:** provisional hasta medir staging con recursos equivalentes a producción  
**Fecha:** 2026-07-11

Estos objetivos son gates de ingeniería iniciales, no una promesa de capacidad del servidor. La
fase 14 debe inventariar CPU, RAM, disco, red y topología; después se repite el baseline con un
dataset representativo y se ajustan los objetivos sin relajar errores de seguridad o integridad.

## Perfil de medición

- Calentamiento: 30 s; medición: mínimo 5 min; tres repeticiones.
- Carga inicial: 10 usuarios concurrentes y subida gradual a 25; sin think-time cero artificial.
- Dataset sintético mínimo: 10 tenants, 100 expedientes/tenant, 10.000 señales/tenant, 2.000 tareas,
  500 documentos/chunks y 500 informes/tenant.
- Misma región/red que staging; HTTPS/Nginx/Gunicorn/PostgreSQL/Redis/workers habilitados.
- Informar p50/p95/p99, throughput, error rate por escenario, saturación CPU/RAM/IO, pool DB y colas.
- Los 401/403/409/422 esperados no se ocultan: se reportan separados, pero una prueba nominal debe
  mantener < 1 % de respuestas inesperadas y cero fuga cross-tenant.

## Objetivos provisionales

| Escenario | p95 | p99 | Error inesperado | Observación |
|---|---:|---:|---:|---|
| `GET /health/live` | 100 ms | 250 ms | < 0,1 % | Sin dependencias |
| login + selección tenant | 900 ms | 1.500 ms | < 0,5 % | Argon2 es deliberadamente costoso |
| `GET /auth/me` | 250 ms | 500 ms | < 0,5 % | Incluye sesión Redis y validación durable |
| portfolio/lista expedientes | 400 ms | 800 ms | < 1 % | Página 25, sort/index allowlist |
| señales con filtros | 500 ms | 1.000 ms | < 1 % | Página 25 y búsqueda acotada |
| búsqueda global | 650 ms | 1.250 ms | < 1 % | Query <= 100 caracteres |
| create/update ligero | 600 ms | 1.200 ms | < 1 % | Incluye auditoría y optimistic concurrency |
| enqueue job/informe | 500 ms | 1.000 ms | < 1 % | Mide persist+publish, no ejecución |
| polling de job | 300 ms | 600 ms | < 1 % | Sin polling más frecuente que 1 s/cliente |

Además: utilización sostenida objetivo < 70 % CPU, pool DB < 80 %, ausencia de swap y colas sin
crecimiento durante 10 min tras retirar la carga. Estos umbrales se validarán, no se asumirán.

## Herramienta

`tests/performance/oracle_load.py` usa solo la librería estándar y credenciales sintéticas por
variables de entorno. Por defecto es read-only; `ORACLE_PERF_MUTATIONS=1` habilita creación/edición,
enqueue de informe y polling en una base desechable. Nunca debe ejecutarse contra producción sin
autorización explícita.

Ejemplo local/staging aislado:

```bash
ORACLE_PERF_EMAIL='owner@example.test' \
ORACLE_PERF_PASSWORD='solo-dato-sintetico' \
ORACLE_PERF_TENANT_ID='<uuid>' \
ORACLE_PERF_DOSSIER_ID='<uuid>' \
uv run --project apps/api python tests/performance/oracle_load.py \
  --base-url http://127.0.0.1:5001 \
  --duration 60 --concurrency 10 --output perf-local.json
```

No pongas contraseñas en flags, logs o archivos de resultado. Un origen no loopback exige
`--allow-staging` y autorización explícita; la herramienta no sigue redirects a otros hosts.

## Query plans y N+1

Antes del gate de staging se capturan `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` para dossiers,
señales filtradas, búsqueda global, jobs y documentos FTS, bajo el rol runtime/RLS. Un plan con
sequential scan sobre una tabla grande, spill a disco o estimación desviada > 10× abre finding.
El frontend de actores ya agrupa IDs; cualquier endpoint que crezca una consulta por fila se
considera regresión y debe medirse con contador SQL en integración.
