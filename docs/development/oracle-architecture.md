# Arquitectura viva de OPN Oracle

Actualizado: 2026-07-31  
Fuente estructurada: `docs/development/oracle-roadmap.json`  
Interfaz canónica: `CANONICAL_UI=vector`

## Lectura de la auditoría

Este documento describe el estado comprobado en el repositorio en la fecha indicada. No sustituye
los ADR técnicos aceptados ni convierte una ruta existente en una capacidad validada. El dashboard
renderiza esta arquitectura junto con el roadmap y conserva los huecos de evidencia.

## Flujo autoritativo

```text
Navegador
  -> Next.js/React (presentación, navegación, caché de server state)
  -> /api/v1 con cookie de sesión opaca + CSRF
  -> Nginx/TLS
  -> Gunicorn / Flask (identidad, tenant, permisos, dominio, OpenAPI)
       -> PostgreSQL (fuente de verdad)
       -> Redis (sesiones, rate limits, caché, broker)
       -> Celery (jobs durables por IDs, colas por capacidad)
       -> SignalAvanzaAdapter (mock o HTTP)
       -> proveedores IA detrás de adapter/policy
       -> almacenamiento/scanner de documentos
```

## Componentes comprobados

| Componente | Evidencia | Estado de auditoría |
|---|---|---|
| Flask application factory | `apps/api/src/opn_oracle/app.py` | Comprobado |
| OpenAPI y cliente TypeScript | `docs/api/openapi.json`, `packages/api-client/src/generated/schema.ts` | Comprobado |
| Tenant context, permisos y auditoría | `apps/api/src/opn_oracle/tenants/`, `apps/api/src/opn_oracle/auth/permissions.py`, `apps/api/src/opn_oracle/platform/audit.py` | Comprobado con revisión abierta |
| Dominio de expediente | `apps/api/src/opn_oracle/oracle/models.py`, `routes.py`, `service.py` | Comprobado |
| Signal e ingesta | `apps/api/src/opn_oracle/integrations/signal_avanza.py`, `service.py`, `webhooks.py` | Implementado; contrato externo bajo revisión |
| IA y revisión | `apps/api/src/opn_oracle/ai/`, `apps/api/src/opn_oracle/reporting/` | Implementado; gates operativos abiertos |
| Documentos/evidencia | `apps/api/src/opn_oracle/documents/` | Implementado; entorno observado deshabilitado |
| Vector autenticado | `src/app/app/`, `src/components/`, `packages/api-client/` | Implementado; migración completa en curso |
| Jobs | `apps/api/src/opn_oracle/celery_app.py`, `jobs/`, `oracle/jobs.py` | Comprobado |
| CI y operación | `.github/workflows/`, `infra/`, `scripts/`, `docs/operations/` | Comprobado con gates que deben repetirse |

## Multi-tenancy y seguridad

Todo recurso de negocio debe tener `tenant_id` o estar clasificado como global de plataforma. El
tenant activo se deriva de sesión/membership; el frontend no autoriza ni puede elegir libremente
un tenant. Las operaciones sensibles exigen permisos, CSRF, versión/idempotencia cuando aplica y
`AuditEvent`. PostgreSQL/RLS es defensa en profundidad, no sustituto de los controles Flask.

La sesión es opaca y server-side. Redis no es la fuente de verdad de negocio. Las descargas de
artefactos se vinculan a tenant, usuario y sesión. Los secretos de Signal, correo y proveedores IA
deben quedar cifrados, rotables y fuera de logs.

## Procesos asíncronos

Celery separa `default`, `signals`, `ai`, `documents`, `notifications` y `maintenance`. Las tareas
reciben IDs pequeños, tenant/correlation context, reintentan con backoff y actualizan
`BackgroundJob`. No se ejecutan parsing, IA, sincronización externa ni informes largos dentro de
una petición HTTP.

## Fronteras de integración

- Signal Avanza solo se usa detrás de `SignalAvanzaAdapter`; el frontend nunca lo invoca.
- IA usa proveedores, prompts y schemas versionados; outputs sin schema/evidencia no son insights válidos.
- Documentos requieren scanner, límites, almacenamiento permitido, procesamiento asíncrono y retención.
- Informes congelan snapshot de evidencia y template antes de crear artefactos.
- Procurement presenta snapshots y límites de cobertura; no afirma ranking global o participantes nominales sin fuente.

## Puntos de auditoría

1. Login, logout, elevación, cambio de contraseña y revocación de sesión.
2. Selección/uso de tenant por superadmin con motivo explícito.
3. Mutaciones idempotentes y conflictos de versión.
4. Ingesta Signal: event/provider/hash, raw y normalizado.
5. IA: input/output hashes, prompt version, modelo, latencia, coste, evidencia y revisión.
6. Documentos: hash, scanner, intento, chunk, retención y actor.
7. Informes: snapshot, revisión, artefacto y descarga.
8. Release: SHA, backup, migración, smoke, rollback y estado del entorno.

## Fronteras pendientes

- Sustituir completamente fixtures/localStorage de prototipo en Vector.
- Cerrar E2E de procurement y gates PDF/revisor.
- Validar credenciales, región, redacción, presupuesto y kill switch de IA/Signal por entorno.
- Medir cobertura nominal de participantes antes de modelar exhaustividad.
- Actualizar la documentación histórica de `REPOSITORY_MAP.md` y `STATUS.md` cuando se consolide la rama de trabajo.
