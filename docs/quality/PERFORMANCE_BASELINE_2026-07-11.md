# Baseline local de rendimiento · 2026-07-11

## Alcance y límites

Medición read-only de humo, no prueba de capacidad productiva. Se ejecutó en loopback sobre macOS
Darwin 25.5 arm64, 12 CPU lógicas y 64 GiB RAM, con Gunicorn de un worker `gthread`, PostgreSQL
16.14 y Redis 8.8 locales. El dataset fue el seed sintético E2E de Asterion, muy inferior al volumen
objetivo de staging. No hubo Nginx, TLS, latencia de red, contenedores ni concurrencia de workers.

Comando: `oracle_load.py`, 4 clientes, 10 s, think time 100 ms, mutaciones deshabilitadas. Las
credenciales sintéticas se suministraron por entorno y no aparecen en el resultado.

## Resultado

- 326 requests totales, incluidas 4 autenticaciones y sus CSRF.
- 0 respuestas inesperadas y 0 errores de worker.

| Escenario | Requests | p50 | p95 | p99 |
|---|---:|---:|---:|---:|
| login | 4 | 127,95 ms | 129,60 ms | 129,60 ms |
| `/auth/me` | 64 | 17,93 ms | 24,67 ms | 24,99 ms |
| expedientes | 55 | 16,08 ms | 23,11 ms | 25,28 ms |
| señales filtradas | 61 | 17,86 ms | 23,42 ms | 23,86 ms |
| búsqueda global | 65 | 21,54 ms | 28,16 ms | 29,14 ms |
| jobs | 69 | 16,24 ms | 23,33 ms | 55,08 ms |

Todos los valores quedan dentro del presupuesto provisional, pero no validan el presupuesto de
staging: faltan volumen representativo, HTTPS/Nginx, 10–25 usuarios durante 5 min, mutaciones,
enqueue de informes/jobs, telemetría de recursos y tres repeticiones. Por tanto, este baseline
reduce riesgo de regresión local pero **no autoriza producción ni determina capacidad del host**.

## Planes SQL focales

Se ejecutó `EXPLAIN (ANALYZE, BUFFERS)` bajo `oracle_app`, con RLS y `SET LOCAL` de tenant/actor,
sobre el seed de ocho expedientes:

| Consulta | Plan observado | Tiempo ejecución |
|---|---|---:|
| expedientes por tenant + `updated_at` | `ix_dossiers_tenant_status_updated`, sin seq scan | 0,161 ms |
| señales contextuales + score | `ix_dossier_signals_inbox` + índice de señales, nested loop | 0,183 ms |
| jobs por tenant + fecha | `ix_background_jobs_tenant_status`, sin seq scan | 0,024 ms |

Los planes confirman que el rol runtime/RLS usa índices en este dataset, pero el nested loop de
señales y las estimaciones de una fila deben repetirse tras `ANALYZE` con el volumen objetivo. No se
afirma ausencia de regresión a escala basándose en ocho filas.
