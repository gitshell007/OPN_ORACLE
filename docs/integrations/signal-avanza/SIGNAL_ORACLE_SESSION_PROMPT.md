# Prompt para la sesión separada de Signal 

Trabaja **en el repositorio de Signal **, no en el repositorio de OPN Oracle. Tu objetivo es construir y demostrar la interfaz service-to-service que OPN Oracle consumirá para gestionar monitores y recibir señales normalizadas.

## Forma de trabajo obligatoria

1. Lee primero el `AGENTS.md` del repositorio Signal y toda su documentación de arquitectura, API, tenancy, autenticación, workers, scheduler, collectors, normalización, deduplicación, webhooks y despliegue.
2. Inspecciona el estado de Git y preserva todos los cambios existentes. No hagas resets, limpiezas ni migraciones destructivas.
3. Respeta el stack real de Signal. No migres de framework, base de datos, cola o modelo de tenancy por preferencia.
4. Oracle y Signal son productos distintos:
   - Signal ingiere, normaliza, deduplica y entrega señales.
   - Oracle aporta el contexto del expediente, interpreta y decide oportunidad, riesgo o acción.
5. No uses el `tenant_id` de Oracle como autorización interna de Signal. Debe existir un mapping explícito entre una credencial/conexión autenticada de Oracle y el tenant/account de Signal.
6. No copies credenciales a código, documentación, fixtures, logs o comandos. Usa variables de entorno y ejemplos vacíos.
7. Implementa por fases y ejecuta los checks reales después de cada bloque. Si la auditoría descubre una incompatibilidad o decisión de negocio bloqueante, documenta la divergencia y detente antes de implementar endpoints incorrectos.

## Fase S01 — Auditoría y contrato v1

Antes de escribir endpoints:

- inventaría stack, módulos, endpoints, persistencia, workers, scheduler, auth, tenancy y deployment;
- identifica la entidad existente más cercana a monitor/task/watch y decide si debe extenderse;
- mapea la cobertura real a estos tipos: `news`, `official_publication`, `social_signal`, `company_signal`, `market_signal`, `regulatory_signal`, `tender_or_grant`, `relationship_signal`, `internal_document`, `risk_signal` y `opportunity_signal`;
- marca expresamente los tipos no soportados; no simules cobertura;
- diseña auth service-to-service, scopes, tenant mapping, ciclo de vida del monitor, cursor, paginación, retención, rate limits, errores, versionado, idempotencia, webhooks, HMAC y replay protection.

Crea:

```text
docs/integrations/oracle/CONTRACT_V1.md
docs/integrations/oracle/OPEN_QUESTIONS.md
docs/integrations/oracle/THREAT_MODEL.md
docs/integrations/oracle/IMPLEMENTATION_PLAN.md
```

El contrato debe incluir ejemplos JSON completos y una lista exacta de divergencias respecto a lo que Signal ya soporta.

## Fase S02 — Monitor solicitado por Oracle

Implementa `OracleMonitor` o la extensión equivalente más natural en Signal:

- ID interno y tenant/account Signal;
- cliente externo `opn-oracle`;
- Oracle monitor ID opaco;
- idempotency key;
- estado `draft | active | paused | disabled | error`;
- query, keywords, entities, languages, geographies y source types;
- cadence;
- subscription/callback ID, nunca el secreto en claro;
- config version/hash;
- last run, cursor, health y error seguro;
- timestamps y política de retención.

Incluye migración, modelo, repositorio/servicio, transiciones válidas, validación, límites, scheduler sin runs duplicados, audit events, fixtures sintéticos y tests de aislamiento, idempotencia, conflictos de versión, pause/resume y duplicación del scheduler.

## Fase S03 — API consumida por Oracle

Adapta estos endpoints al estilo real de Signal manteniendo la semántica:

```text
POST   /api/v1/oracle/monitors
GET    /api/v1/oracle/monitors/{id}
PATCH  /api/v1/oracle/monitors/{id}
POST   /api/v1/oracle/monitors/{id}/pause
POST   /api/v1/oracle/monitors/{id}/resume
POST   /api/v1/oracle/monitors/{id}/sync
GET    /api/v1/oracle/signals?monitor_id=&cursor=&limit=
GET    /api/v1/oracle/signals/{id}
GET    /api/v1/oracle/health
```

Requisitos:

- credencial de servicio por integración/tenant, con scopes `monitor:write`, `signal:read` y `webhook:manage`;
- rotación, revocación, rate limiting y auditoría;
- sin autenticación de navegador ni CORS abierto;
- `Idempotency-Key` persistida con hash del request; misma clave y body distinto devuelve `409`;
- cursor opaco, estable, ligado a tenant y monitor, con orden determinista y comportamiento definido al expirar;
- errores estables tipo Problem Details, request ID, campo `retryable` y `Retry-After` en `429/503`;
- OpenAPI versionado y exportable.

Schema mínimo de una señal:

```json
{
  "id": "sig_ext_...",
  "monitor_id": "mon_ext_...",
  "type": "official_publication",
  "title": "...",
  "summary": "...",
  "source": {
    "name": "...",
    "url": "https://...",
    "published_at": "2026-07-10T08:00:00Z",
    "credibility_score": 82
  },
  "language": "es",
  "entities": [],
  "tags": [],
  "categories": [],
  "content_hash": "sha256:...",
  "observed_at": "2026-07-10T08:05:00Z",
  "created_at": "2026-07-10T08:05:10Z",
  "provenance": {
    "connector": "...",
    "monitor_config_version": 3
  }
}
```

No entregues contenido completo si la licencia solo permite excerpt/enlace; documéntalo en el contrato.

## Fase S04 — Webhooks hacia Oracle

Implementa subscriptions, outbox transaccional y worker de entrega. Envelope orientativo:

```json
{
  "event_id": "evt_...",
  "event_type": "signal.created",
  "api_version": "2026-07-01",
  "occurred_at": "2026-07-10T08:00:00Z",
  "delivery_attempt": 1,
  "monitor_id": "mon_ext_...",
  "data": {"signal": {}}
}
```

Firma HMAC SHA-256 sobre `<timestamp>.<raw_body>` con headers versionados. Exige HTTPS en producción, ventana anti-replay, comparación constant-time, secret rotatable con solape breve, timeouts, retries con backoff/jitter, `Retry-After`, dead-letter, replay manual auditado y event ID estable entre reintentos.

Protege contra SSRF: política de URL, DNS rebinding, metadata/IP privadas salvo despliegue privado explícito, redirects, límites de payload y header injection.

## Fase S05 — Contrato consumible y E2E

- congela y exporta OpenAPI/schema v1;
- crea fixtures sintéticos compartibles y contract tests ejecutables por Oracle;
- crea un fake/sandbox de Signal que Oracle pueda levantar sin secretos reales;
- prueba: crear monitor, ejecutar run, producir dos señales, webhook de una, sync de ambas incluyendo duplicado, deduplicación final, update/pause/resume, rotación, `429`, retry y replay;
- prueba version mismatch y compatibilidad;
- documenta comandos exactos y resultados reales.

Crea:

```text
docs/integrations/oracle/E2E_RESULTS.md
docs/integrations/oracle/RUNBOOK.md
docs/integrations/oracle/COMPATIBILITY_MATRIX.md
```

## Definición de terminado

No declares la integración lista hasta que:

- contrato, OpenAPI y fixtures estén versionados;
- tenant mapping y scopes sean inequívocos;
- aislamiento, idempotencia, cursor, firma, replay y rotación tengan tests;
- el fake/sandbox sea reproducible;
- los contract tests puedan entregarse al repositorio Oracle;
- lint, tipos, tests, migraciones y build del stack Signal pasen;
- todas las limitaciones y tipos no soportados estén documentados.

Al finalizar, entrega un resumen con archivos, migraciones, endpoints, variables nuevas sin valores, comandos ejecutados, resultados, divergencias, preguntas abiertas y la ruta exacta de los artefactos que debe importar la sesión de OPN Oracle.
