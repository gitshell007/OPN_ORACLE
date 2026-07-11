# Estrategia integral de pruebas

**Versión:** fase 13 · 2026-07-11  
**Ámbito:** OPN Oracle full-stack, antes de infraestructura productiva  
**Regla de salida:** un `critical` o `high` abierto bloquea las fases 14–16

## Objetivos

La estrategia prioriza aislamiento entre tenants, autorización server-side, integridad de trabajos
asíncronos y trazabilidad de evidencia. No se considera suficiente una ruta feliz ni una prueba con
SQLite cuando el control depende de PostgreSQL, RLS, Redis o semántica de entrega Celery.

Cada requisito debe tener una prueba identificable en `TEST_MATRIX.md`. Los gaps se registran con
owner, severidad y gate; no se convierten en «aprobados» por no disponer aún de infraestructura.

## Capas

1. **Unitarias y de contrato:** validación, schemas, scoring, redacción, seguridad de URLs,
   adapters deterministas, OpenAPI y código sin I/O externo.
2. **Integración real:** PostgreSQL con roles `oracle_migrator`/`oracle_app`, RLS forzada, Redis
   separado por DB lógica, worker Celery real cuando la semántica de entrega importa y storage
   local temporal privado.
3. **API y componente:** Flask test client para errores/headers/contratos; Vitest + Testing Library
   para estados, permisos y transporte sin reemplazar la autorización backend.
4. **E2E:** Chromium contra Next.js, Gunicorn, PostgreSQL y Redis reales; datos sintéticos sembrados
   de forma determinista; escritorio y móvil.
5. **No funcional:** accesibilidad, hardening, análisis de dependencias/código/secretos, rendimiento,
   DAST local permitido, migración/restore y smoke de infraestructura.

## Infraestructura reproducible

- `uv.lock` y `package-lock.json` son obligatorios; se usan `uv sync --frozen` y `npm ci`.
- Las suites de integración crean una base desechable, aplican todas las migraciones y usan el rol
  runtime `NOBYPASSRLS`. No se acepta SQLite como evidencia de aislamiento.
- Redis usa una DB reservada por suite y se verifica vacía tras cleanup. El estado durable de jobs
  permanece en PostgreSQL.
- Los E2E usan `scripts/run-auth-e2e-api.sh`: base y Redis dedicados, seed sintético convergente,
  Gunicorn local y cleanup con terminación de conexiones.
- El mock LLM y el adapter Signal son deterministas y no efectúan llamadas pagadas ni a terceros.
  Los tests HTTP de Signal deben usar transporte/fake server local, nunca el servicio real.
- `LocalObjectStorage` apunta a un directorio temporal privado por test. Un test que cree objetos
  debe borrar directorio, filas, base y Redis incluso tras fallo.
- La fecha visible, IDs semilla y resultados no usan `Math.random()`; cada worker/suite usa nombres
  únicos para evitar colisiones. La paralelización solo se habilita tras parametrizar DB/Redis/puertos.

## Datos y factories

Las fixtures son sintéticas, tenant-aware y crean al menos tenant A, tenant B, usuario ordinario,
tenant-admin y superadmin. Toda factory tenant-scoped recibe `tenant_id` explícito. Los payloads
adversariales se mantienen pequeños y seguros: no se almacena malware real ni una bomba expandible;
EICAR solo se usa contra un scanner de prueba aislado.

## Política de seguridad negativa

Para cada recurso tenant-scoped se prueban, donde aplique: UUID B con sesión A, filtro/búsqueda que
intenta inferir B, relación hija/padre discordante, IDs bulk mixtos, descarga/export, job y clave de
storage. La misma lectura se prueba a nivel servicio/API y mediante SQL con `oracle_app`. Un 404/403
seguro no debe revelar si el recurso ajeno existe.

Auth cubre fijación y rotación de sesión, flags de cookie, CSRF en todas las mutaciones, origen,
enumeración/rate limit, replay de tokens, revocación inmediata, cambio de tenant, usuario/tenant
suspendido, open redirect y escalada de privilegios. El frontend ocultando un botón nunca cuenta
como control.

## Resiliencia

Las tareas con efecto observable prueban redelivery, ejecución concurrente, crash antes/después de
commit o efecto externo, fencing de lease/token, límite de reintentos y recuperación. Signal cubre
firma, replay, duplicado, cursor, orden y respuestas 429/5xx/timeout. IA cubre schema, evidencia,
inyección, redacción, cuota, timeout y reviewer; CI mantiene proveedores externos deshabilitados.

## Rendimiento

`docs/quality/PERFORMANCE_BUDGET.md` contiene presupuestos iniciales, no capacidad prometida. El
escenario de carga mide login/me, portfolio, filtros de señales, mutación ligera, job, búsqueda y
enqueue de informe. Se registran versión, recursos, dataset, concurrencia, p50/p95/p99 y errores.
No se extrapola producción desde un portátil. Los endpoints críticos se revisan además por N+1,
índices y `EXPLAIN (ANALYZE, BUFFERS)` sobre datos sintéticos representativos.

## Gates por cambio y por release

En cada PR: lockfiles, Ruff/format/mypy, pytest, drift de OpenAPI, ESLint/TypeScript/Vitest, build,
secret scan y auditorías de dependencias triagadas. Si toca migraciones: base→head, `flask db check`,
downgrade/reupgrade y RLS/grants. Si toca auth/tenant/job: suites negativas reales obligatorias.

Antes de release: E2E completo, axe/teclado/consola, baseline de carga en staging equivalente,
DAST permitido, scan de imagen/SBOM, restore real, renovación TLS/headers desde el exterior y smoke
de API/web/worker/beat/storage. Estos últimos permanecen bloqueados hasta fases 14–15.

El baseline DAST local se ejecuta con el runtime Python soportado del proyecto:

```bash
uv run --project apps/api python tests/security/dast_baseline.py \
  --base-url http://127.0.0.1:5001
```

El script rechaza targets no-loopback salvo `--allow-staging`; esa opción solo se usa sobre staging
propio con autorización y nunca equivale a permiso para escanear producción.

## Evidencia y triage

Los resultados se anotan en `docs/security/READINESS_REPORT.md` con comando, fecha, entorno y
salida resumida. Severidad: `critical` (fuga/ejecución/credencial), `high` (bypass o pérdida durable),
`medium` (defensa degradada), `low` (hardening/deuda). Solo se acepta riesgo con owner, razón,
caducidad y control compensatorio; `critical/high` no se aceptan para producción.
