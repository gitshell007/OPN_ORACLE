# Informe de readiness de seguridad y calidad

**Fecha:** 2026-07-11  
**Commit base observado:** `2ab0e14` (`master`) con árbol de trabajo no consolidado  
**Alcance:** aplicación local full-stack hasta fase 13; no audita todavía el servidor remoto  
**Veredicto:** lista para iniciar la auditoría **read-only** de fase 14; **NO production ready**

## Resumen ejecutivo

La revisión encontró y corrigió cuatro problemas high: colisión de rutas Signal que eludía el
adaptador/outbox, actualización concurrente de monitores sin precondición, dependencia
`cryptography` vulnerable y almacenamiento ilimitado de muestras en métricas. También corrigió dos
colisiones GET documentales. No quedan critical/high de aplicación conocidos abiertos tras los
gates locales, pero producción continúa bloqueada por controles de infraestructura y recuperación
que solo pueden verificarse en fases 14–15.

## Entorno y evidencia ejecutada

- Backend: Python 3.11.15, PostgreSQL 16.14 y Redis 8.8 reales, roles migrator/runtime y RLS.
- `uv run pytest` con integración: **233/233**, cobertura **85,95 %**.
- Ruff y mypy estricto: correctos; OpenAPI reexportado y cliente TypeScript sin drift.
- Frontend: ESLint/TypeScript correctos; **21 archivos / 64 tests**; build Next correcto.
- Playwright full-stack: **24 passed / 6 skips intencionales**; F13 focal 7/1. Incluye axe WCAG
  2.2 A/AA, teclado, foco, consola, headers y tres hard reloads con `/auth/me` 200/200/200.
- Smoke productivo `next start`: CSP report-only sin `unsafe-eval`, anti-clickjacking, nosniff,
  referrer/permissions, no-store y sin `X-Powered-By`; HSTS ausente deliberadamente hasta TLS.
- DAST local no destructivo contra Gunicorn: **13/13** (headers, CORS, auth, no-store, métricas
  ocultas, traversal/XSS/SQLi acotados y sin traces). No se escaneó producción ni terceros.
- Scans: npm audit 0; pip-audit 0 tras upgrade; Semgrep 5 reglas/225 targets, 0; secret patterns 0.
  Trivy no está instalado: scan de imagen queda gate explícito.
- Baseline local read-only: 4 clientes/10 s, 326 requests, 0 errores. p95: login 129,60 ms,
  expedientes 23,11 ms, señales 23,42 ms, búsqueda 28,16 ms, jobs 23,33 ms. Es smoke local, no
  capacidad productiva. Tres `EXPLAIN ANALYZE` bajo runtime/RLS usaron índices y se repetirán con
  volumen staging.
- Cleanup: base/Redis temporales de cierre eliminados; no se llamó a servicios de pago o terceros.

## Findings

| ID | Sev. | Finding / evidencia | Estado | Mitigación, owner y gate |
|---|---|---|---|---|
| F13-01 | High | Dos `PATCH /signal-monitors/{id}` equivalentes permitían resolver el CRUD genérico y saltar adapter/outbox/idempotencia | **Corregido** | CRUD genérico retirado; ruta Signal única. Tests de rutas ambiguas. Owner backend |
| F13-02 | High | Update de monitor sin control optimista podía perder cambios concurrentes | **Corregido** | `If-Match`, `FOR UPDATE`, config version e idempotency replay/stale 409. Owner backend |
| F13-03 | High | `cryptography 46.0.7`, `GHSA-537c-gmf6-5ccf` | **Corregido** | 48.0.1; pip-audit 0 y tests crypto/Signal/documentos verdes. Owner dependencies |
| F13-04 | High | Histograma retenía una lista por cada request y crecía sin límite | **Corregido** | 9 buckets acumulados + sum/count; regresión con 10.000 muestras. Owner observability |
| F13-05 | Medium | Rutas GET equivalentes hacían inalcanzables search/evidence documental | **Corregido** | `/documents/search` y `/documents/evidence/{id}`; `/search` y `/evidence/{id}` quedan core |
| F13-06 | Medium | Endpoint legacy `/watchlists/{id}/monitors` aún admite monitor local fuera del contrato Signal | Abierto, feature limitada | Retirar/migrar antes de habilitar Signal real. Owner integrations; Signal HTTP sigue fail-closed |
| F13-07 | Medium | Política de campos desconocidos no es uniforme en todos los DTO de dominio | Abierto | Inventariar schemas allowlist y rechazar extras sin romper compatibilidad. Owner API; campos sensibles ya excluidos |
| F13-08 | Medium | CSP web necesita inline bootstrap y permanece report-only | Riesgo temporal aceptado | Nonce por request, recoger reports y pasar a enforcement tras TLS/Nginx. Owner web/SRE, fase 14 |
| F13-09 | Medium | Un sweep antiguo vio `/auth/me` 200→401 con cookie presente durante recargas sin esperar; trace no conservado | No confirmado | Regresión aislada y full E2E verdes; monitorizar/reproducir bajo carga. Owner auth, no se oculta como PASS probado |
| F13-10 | Medium | Métricas in-process no agregan todos los workers ni cubren aún colas/Signal/IA/docs | Abierto | Scrape por worker o adapter externo; completar series y alertas sin labels sensibles. Owner SRE, fase 14 |
| F13-11 | High release gate | Sandbox de parser, S3 y ClamAV productivos no verificados | **Bloquea documentos/release** | Producción ya falla cerrado sin S3+ClamAV; aislar worker sin red y límites CPU/RAM en fase 14 |
| F13-12 | High release gate | No existe todavía backup/restore productivo medido | **Bloquea release** | Backup cifrado/off-host y restore real con RPO/RTO en fase 15 |
| F13-13 | Medium release gate | Trivy/SBOM, ZAP staging, TLS/cert/puertos y carga representativa no ejecutados | **Bloquea release** | Ejecutar sobre imagen/staging propios en fases 14–15; nunca sobre terceros |
| F13-14 | Medium | Faltaba demostrar revocación RBAC mientras la sesión permanece abierta | **Corregido** | Integración elimina permiso, `/auth/me` lo pierde y tenant-admin devuelve 403 en la siguiente petición |

No hay findings `critical` abiertos. Los high de código están corregidos; F13-11/F13-12 son gates
de release explícitos y no se rebajan por estar fuera del entorno local.

## Controles implantados

- Aislamiento: matriz dinámica de tablas tenant, RLS `ENABLE/FORCE`, runtime sin contexto, relaciones
  nested, jobs, downloads, exports y auditoría A/B.
- Auth: inventario automático de mutaciones CSRF, rotación/revocación, cookies, origen, rate limit,
  replay de reset/invite, cambio tenant, usuario/tenant suspendido y open redirect.
- Resiliencia: idempotencia, leases/fencing, outbox/inbox, worker real, Signal HMAC/replay, IA
  deterministic/evidence allowlist y documentos/retención.
- Observabilidad: logs redactados y correlacionados; métricas HTTP de baja cardinalidad, auth/rate
  limit y pool, ocultas con 404 salvo enable+bearer; acumulación de memoria acotada.
- Web: no-store, anti-clickjacking, nosniff, policies, CSP report-only, WCAG/teclado/consola.
- Operación: runbooks para API, DB/pool, Redis, Celery, Signal, cert, disco, backup, sesiones y
  sospecha cross-tenant.

## Riesgos aceptados y decisiones pendientes

- `password_reset_tokens` es global de forma deliberada para resolver tokens anónimos de alta
  entropía; se conserva solo hash y el servicio limita el acceso.
- Signal HTTP, proveedor IA real, renderer PDF y datos reales permanecen deshabilitados/fail-closed.
- La observación de sesión F13-09 se acepta solo para continuar la investigación; cualquier
  reproducción estable o revocación errónea la elevará a high y bloqueará release.
- HSTS no se activa hasta validar HTTPS desde fuera. Las credenciales de servidor compartidas en
  conversación deben rotarse y suministrarse por un canal secreto antes de usarse en despliegue.

## Gate hacia fase 14

Se puede iniciar `14_PRODUCTION_INFRA_TLS.md` **solo en modo auditoría read-only**: inventario de
host, DNS, puertos, recursos y configuración. Antes de mutar el servidor se exige credencial
rotada, backup previo, diff/rollback y autorización de cambio. No es seguro publicar tráfico real,
datos reales ni habilitar HSTS/Signal/IA/documentos hasta cerrar sus gates.
