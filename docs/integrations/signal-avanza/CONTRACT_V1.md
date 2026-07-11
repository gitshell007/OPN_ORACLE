# Contrato v1 entre OPN Oracle y Signal Avanza

**Estado:** confirmado bilateralmente contra el productor
**Versión del contrato:** `2026-07-01`
**Última revisión:** 2026-07-11
**Fuente de verdad del productor:** `opn_signal/docs/integrations/oracle/openapi/v2026-07-01.json`

## 1. Alcance y gate de activación

Este documento conserva el contexto de consumidor de OPN Oracle. El contrato normativo es el
OpenAPI fechado del productor indicado arriba: base URL
`https://signal.opnconsultoria.com/api/v1/oracle`, autenticación `X-API-Key`, tenant en
`X-OPN-External-Tenant-ID` y scopes `monitor:write`, `signal:read`, `webhook:manage`.

El contrato fue contrastado con el repositorio y el entorno productivo de Signal. Por tanto:

- el namespace y la versión quedan fijados por el OpenAPI fechado;
- el modo HTTP exige host allowlisted, HTTPS, contrato confirmado y credenciales cifradas;
- cada tenant de Oracle debe figurar expresamente en la allowlist del consumer `opn-oracle`;
- polling y webhook HMAC V2 convergen en la misma ingesta idempotente.

No deben introducirse credenciales, dominios reales de clientes ni payloads licenciados en estos documentos o fixtures.

## 2. Decisiones provisionales y cuestiones abiertas

| Área | Propuesta de Oracle | Estado |
|---|---|---|
| Base URL | Configuración por conexión; HTTPS obligatorio en producción | Abierto: URL y política de allowlist |
| Versión HTTP | Namespace externo orientativo `/api/v1/oracle` | Abierto: confirmar con Signal |
| Autenticación | Credencial service-to-service por conexión/tenant Signal, nunca credencial de navegador | Abierto: esquema de cabecera/token, scopes y expiración |
| Scopes | `monitor:write`, `signal:read`, `webhook:manage` | Abierto |
| Tenant mapping | La credencial autenticada resuelve un account/tenant Signal; IDs de tenant enviados por Oracle no autorizan | Principio cerrado; mecanismo abierto |
| Idempotencia | `Idempotency-Key` en creaciones, acciones y sync; misma clave con body distinto = `409` | Semántica propuesta; TTL abierto |
| Concurrencia | Versión de configuración y `If-Match`/campo `version` | Abierto: mecanismo exacto |
| Cursor | Opaco, estable, ligado a credencial y monitor | Principio cerrado; retención/expiración abiertos |
| Paginación | `limit`, `next_cursor`, `has_more`; máximo configurable | Abierto: límites y valor por defecto |
| Firma webhook | HMAC-SHA256 de `<timestamp>.<raw_body>` | Propuesta; encoding/cabeceras por confirmar |
| Retención | Signal no entrega contenido que su licencia no permita; Oracle aplica retención a raw/inbox | Abierto: ventanas exactas |
| Ordering | Oracle no presupone orden global de webhooks | Provisional |
| Timestamps | RFC 3339 UTC, por ejemplo `2026-07-10T08:00:00Z` | Propuesto |

## 3. Modelo de seguridad

Cada `IntegrationConnection` de Oracle representa una relación inequívoca con una cuenta/tenant de Signal. Las credenciales API y los secretos webhook se almacenan cifrados, son rotables y nunca llegan al navegador ni aparecen en logs o respuestas posteriores a su alta.

Signal debe derivar el tenant efectivo de la credencial autenticada. Oracle puede enviar identificadores opacos propios para correlación, pero Signal no debe confiar en un `tenant_id` de Oracle como autorización. A la inversa, Oracle resuelve el tenant de un webhook mediante la suscripción/conexión receptora, nunca mediante un tenant declarado en el payload.

Las llamadas HTTP requieren TLS en producción, timeouts explícitos, redirects desactivados y una política SSRF para endpoints configurables. Los retries se limitan a errores transitorios y operaciones idempotentes. `Retry-After` se respeta en `429` y `503`.

## 4. Ciclo de vida del monitor

Estados externos propuestos: `draft`, `active`, `paused`, `disabled` y `error`. Transiciones mínimas:

```text
draft -> active -> paused -> active
  |        |          |
  +--------+----------+-> disabled
active|paused -> error -> active|paused|disabled
```

- `POST /monitors` crea o devuelve idempotentemente un monitor.
- `PATCH /monitors/{id}` modifica configuración y aumenta `config_version`.
- `POST /monitors/{id}/pause` detiene nuevos runs sin borrar histórico.
- `POST /monitors/{id}/resume` reactiva la programación.
- la desactivación/borrado es lógica y su ruta exacta queda abierta; Oracle no presupone borrado físico.
- `POST /monitors/{id}/sync` solicita una ejecución/sincronización idempotente; que sea síncrona o acepte un job queda por confirmar.

Cada operación saliente conserva una clave de idempotencia estable. Oracle usa outbox transaccional y no bloquea una petición web mientras Signal responde.

### 4.1 Configuración propuesta

```json
{
  "client_monitor_id": "2e48dd66-8996-4e96-a2bb-f7e81cf422f2",
  "query": "transición energética",
  "keywords": ["hidrógeno verde"],
  "entities": [{"name": "Organización de ejemplo", "type": "organization"}],
  "languages": ["es", "en"],
  "geographies": ["ES", "EU"],
  "source_types": ["official_publication", "tender_or_grant"],
  "cadence": "PT1H",
  "status": "active",
  "callback_subscription_id": "sub_ext_example",
  "config_version": 3,
  "config_hash": "sha256:0123456789abcdef"
}
```

`client_monitor_id` es opaco para Signal. `callback_subscription_id` no es un secreto. Formato y límites de `query`, `entities`, geographies, cadence y sources siguen abiertos. Oracle conserva internamente dossier, watchlist y tenant; no necesita transmitirlos.

## 5. Sincronización incremental

Ruta propuesta:

```http
GET /api/v1/oracle/signals?monitor_id=mon_ext_example&cursor=opaque&limit=100
```

Respuesta propuesta:

```json
{
  "items": [],
  "next_cursor": "opaque-next",
  "has_more": false,
  "counts": {"returned": 0}
}
```

El cursor debe estar ligado a la credencial y monitor, representar un orden determinista y no revelar secuencias internas. Signal debe definir duración, respuesta ante cursor inválido/expirado y snapshot semantics. Oracle solo avanza su cursor después de confirmar la transacción de la página completa; un elemento inválido se registra sin convertir una entrega parcial en pérdida silenciosa.

Webhook y polling pueden coexistir. Oracle deduplica por conexión/proveedor, ID externo y hash de contenido; recibir la misma señal por ambos canales no crea dos señales.

## 6. Señal externa mínima

```json
{
  "id": "sig_ext_example",
  "monitor_id": "mon_ext_example",
  "type": "official_publication",
  "title": "Convocatoria de ejemplo",
  "summary": "Resumen sintético sin contenido licenciado.",
  "source": {
    "name": "Fuente pública de ejemplo",
    "url": "https://example.invalid/source/1",
    "published_at": "2026-07-10T08:00:00Z",
    "credibility_score": 82
  },
  "language": "es",
  "entities": [{"name": "Organización de ejemplo", "type": "organization"}],
  "tags": ["convocatoria"],
  "categories": ["innovacion"],
  "content_hash": "sha256:0123456789abcdef",
  "observed_at": "2026-07-10T08:05:00Z",
  "created_at": "2026-07-10T08:05:10Z",
  "provenance": {
    "connector": "official-feed",
    "monitor_config_version": 3
  }
}
```

Los tipos candidatos son `news`, `official_publication`, `social_signal`, `company_signal`, `market_signal`, `regulatory_signal`, `tender_or_grant`, `relationship_signal`, `internal_document`, `risk_signal` y `opportunity_signal`. **La cobertura real de cada tipo está abierta y Signal debe declararla; Oracle no la presume.** Los scores procedentes de Signal conservan su origen y no sustituyen scoring, evidencia ni decisión de Oracle.

Campos nuevos compatibles pueden ignorarse o conservarse como metadata segura. Campos obligatorios, enums, formatos y contenido/excerpt permitidos por licencia deben cerrarse en los contract tests.

## 7. Errores, rate limit y retry

Signal debe devolver un formato estable compatible con Problem Details:

```json
{
  "type": "https://signal.example.invalid/problems/rate-limit",
  "title": "Rate limit exceeded",
  "status": 429,
  "detail": "Retry later.",
  "code": "rate_limited",
  "request_id": "req_example",
  "retryable": true
}
```

- `400/422`: entrada inválida, no retry automático.
- `401/403`: credencial/scope, no retry; conexión degradada.
- `404`: recurso no visible para esa credencial.
- `409`: idempotency key reutilizada con payload distinto o conflicto de versión.
- `429`: retry transitorio respetando `Retry-After`.
- `5xx/503` y timeout: retry limitado con backoff/jitter y circuit breaker.

Oracle propaga un `X-Correlation-ID` seguro. Nombre de request ID, cuotas, códigos definitivos, máximo de intentos y semántica de `Retry-After` por fecha/segundos siguen abiertos.

## 8. Compatibilidad y cierre del contrato

La versión mayor se expresa en la ruta. Cambios aditivos y opcionales pueden permanecer en v1; eliminar/renombrar campos, cambiar auth, firma, idempotencia, cursor o semántica requiere deprecación o una nueva versión mayor. Los productores deben tolerar consumidores que ignoran campos nuevos; los enums requieren estrategia explícita para valores desconocidos.

Para pasar de provisional a confirmado se requiere:

1. inventario real del repositorio Signal y tabla de divergencias;
2. OpenAPI v1 publicado por Signal y comparado con `openapi-signal-v1.yaml`;
3. confirmación de auth, scopes, tenant mapping, límites, retención, firma y rotación;
4. fixtures sintéticos compartidos y contract tests en ambos repositorios;
5. E2E con create/update/pause/resume, webhook + sync duplicado, `429`, retry y rotación;
6. matriz de compatibilidad y runbook reproducibles.

Hasta completar los seis puntos, `SIGNAL_AVANZA_ENABLED=false` y el modo HTTP no es apto para producción.
