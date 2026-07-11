# Contrato inicial de la API de OPN Oracle

**Estado:** propuesto para la fundación Flask  
**Versión del documento:** 0.1  
**Última revisión:** 2026-07-10

## 1. Propósito y estado real

Este documento fija las reglas transversales del futuro contrato HTTP entre el frontend y el backend autoritativo de OPN Oracle. No es todavía una especificación OpenAPI ni afirma que los endpoints estén implementados.

En el estado actual del repositorio:

- existe un prototipo Next.js con App Router;
- las pantallas consumen la interfaz TypeScript `OracleRepository` mediante `MockOracleRepository`;
- expedientes, señales y preferencias se resuelven con fixtures y `localStorage`;
- no existen aún una aplicación Flask, autenticación, OpenAPI, PostgreSQL, Redis ni Celery;
- la documentación antigua que habla de una futura conexión con FastAPI queda superada: el backend autoritativo será Flask.

La migración debe preservar la separación visual del frontend y reemplazar progresivamente el mock por un cliente TypeScript generado desde el OpenAPI de Flask. Ningún componente productivo debe importar fixtures ni acceder directamente a PostgreSQL, Redis, Signal Avanza o un proveedor de IA.

## 2. Frontera y transporte

- La API productiva vive bajo `/api/v1` y la sirve Flask.
- Nginx expone frontend y API bajo el mismo origen; `/api/*` se enruta a Gunicorn/Flask y `/` a Next.js.
- Producción solo admite HTTPS. HTTP redirige a HTTPS.
- JSON es el formato ordinario. Los errores usan `application/problem+json`.
- Las fechas se expresan como RFC 3339 con zona horaria; los identificadores públicos son UUID no enumerables.
- Node/Next.js no implementa autorización autoritativa, reglas de dominio, acceso a base de datos, jobs ni integraciones críticas.
- El OpenAPI generado por Flask es la fuente de verdad del contrato. El cliente TypeScript generado se versiona o se genera reproduciblemente y se valida en CI contra la especificación.

Endpoints transversales fuera del namespace de negocio:

| Endpoint | Finalidad | Autenticación |
|---|---|---|
| `GET /health/live` | Vida del proceso, sin comprobar dependencias | No |
| `GET /health/ready` | Disponibilidad de dependencias críticas | Restringible en producción |
| `GET /api/v1/meta` | Versión de API, build y capacidades no sensibles | No |
| `GET /api/v1/openapi.json` | Especificación OpenAPI | Pública solo si se acepta expresamente |

Los health checks no incluyen secretos, SQL, hosts internos ni trazas.

## 3. Autenticación, sesión y CSRF

La aplicación web usa sesión opaca server-side, no JWT de navegador:

1. Flask autentica al usuario y crea o rota un identificador de sesión aleatorio.
2. El navegador recibe únicamente una cookie de sesión opaca con `HttpOnly`, `Secure` en producción y `SameSite=Lax` salvo decisión documentada.
3. El estado de sesión reside en Redis y su registro durable/revocable en `UserSession` reside en PostgreSQL.
4. El frontend usa `credentials: "include"` en las llamadas que lo requieran.
5. Toda mutación autenticada exige un token CSRF ligado a la sesión, enviado en `X-CSRF-Token`. El token se obtiene mediante un endpoint dedicado o bootstrap autenticado y se mantiene en memoria, no en `localStorage`.
6. Login, elevación de privilegios, cambio de contraseña y operaciones sensibles rotan la sesión. Logout y revocación invalidan el estado server-side de inmediato.

Los métodos `POST`, `PUT`, `PATCH` y `DELETE` requieren CSRF. `GET`, `HEAD` y `OPTIONS` deben ser seguros e idempotentes y nunca mutar estado. Los webhooks máquina-a-máquina no usan CSRF: emplean autenticación propia, firma HMAC, timestamp e idempotencia.

Familia prevista de autenticación:

```text
POST   /api/v1/auth/login
POST   /api/v1/auth/logout
POST   /api/v1/auth/logout-all
GET    /api/v1/auth/csrf
GET    /api/v1/me
GET    /api/v1/me/sessions
DELETE /api/v1/me/sessions/{session_id}
POST   /api/v1/auth/password-reset/request
POST   /api/v1/auth/password-reset/confirm
POST   /api/v1/invitations/{token}/accept
```

Las respuestas de login, invitación y recuperación no permiten enumerar usuarios. Se aplican rate limits por IP, identidad candidata y tenant cuando proceda. Contraseña, cookie, identificador de sesión, CSRF y tokens de invitación/reset nunca aparecen en logs ni respuestas posteriores a su uso.

## 4. Contexto de tenant y autorización

Todo recurso de negocio pertenece a un tenant salvo que el esquema lo declare explícitamente global de plataforma.

- El `tenant_id` efectivo se deriva de la sesión, de una membership activa y, para usuarios multi-tenant, de una selección de tenant validada por el backend.
- Un `tenant_id` recibido en query, body o cabecera no concede acceso y no sustituye el contexto de sesión.
- Los repositorios y servicios Flask aplican scoping centralizado; los permisos se comprueban por acción y recurso.
- PostgreSQL RLS se añadirá como defensa en profundidad, no como sustituto de las comprobaciones de aplicación.
- Una consulta por UUID inexistente o perteneciente a otro tenant devuelve una respuesta que no revela su existencia. La política `404` frente a `403` se fijará de forma uniforme en OpenAPI.
- Las operaciones de plataforma y las de tenant usan namespaces y permisos diferenciados.

El cambio de tenant activo será una mutación auditada y protegida por CSRF. Un `platform_super_admin` no obtiene acceso implícito a datos privados: debe seleccionar tenant, disponer del permiso, registrar un motivo y generar un `AuditEvent`.

## 5. Convenciones de recursos

### 5.1 Colecciones, paginación y ordenación

Las colecciones grandes se paginan y filtran en servidor. Forma inicial propuesta:

```http
GET /api/v1/dossiers?page[number]=1&page[size]=25&sort=-updated_at,title&filter[status]=active&filter[query]=alianza
```

- `page[number]` empieza en 1.
- `page[size]` tiene un valor por defecto y un máximo definidos por endpoint.
- `sort` contiene campos permitidos; `-` indica descendente.
- `filter[...]` solo acepta filtros documentados; texto libre se normaliza y limita.
- Campos desconocidos o no permitidos producen `400`, no se interpolan en SQL.

Respuesta de colección propuesta:

```json
{
  "items": [],
  "page": {
    "number": 1,
    "size": 25,
    "total_items": 0,
    "total_pages": 0
  },
  "links": {
    "self": "/api/v1/dossiers?page[number]=1&page[size]=25",
    "next": null,
    "prev": null
  }
}
```

Para señales o auditoría con mucha escritura podrá adoptarse cursor opaco por endpoint, documentándolo sin mezclar ambas formas en la misma colección.

### 5.2 Escrituras, concurrencia e idempotencia

- `POST` de creación devuelve `201 Created` y `Location`.
- Operaciones aceptadas en segundo plano devuelven `202 Accepted` y una representación de job o enlace a ella.
- Ediciones sensibles usan `version` o `ETag`/`If-Match`; un conflicto devuelve `409` o `412` según la semántica fijada en OpenAPI.
- Creaciones con riesgo de repetición aceptan `Idempotency-Key`. La clave se limita por actor, tenant, operación y ventana temporal; reutilizarla con otro payload es un conflicto.
- Los borrados son explícitos. Archivo, borrado lógico y borrado irreversible son operaciones distintas y requieren permisos diferentes.

### 5.3 Request y correlation ID

- Cada respuesta incluye `X-Request-ID` generado o validado por Flask.
- `X-Correlation-ID` enlaza petición, outbox, job, integración y auditoría; un valor cliente se valida y limita antes de propagarse.
- Ambos identificadores pueden aparecer en errores y logs. Nunca contienen PII ni secretos.

## 6. Formato de error

Los errores usan RFC 9457 (`application/problem+json`) y no exponen traza, SQL, configuración ni detalles internos:

```json
{
  "type": "https://oracle.opnconsultoria.com/problems/validation-error",
  "title": "La solicitud no es válida",
  "status": 422,
  "detail": "Revisa los campos indicados.",
  "instance": "/api/v1/dossiers",
  "code": "validation_error",
  "request_id": "01J...",
  "errors": [
    {"field": "title", "code": "required", "message": "Indica un título."}
  ]
}
```

`detail` y los errores de campo son seguros para usuario. `code` es estable para clientes; `title` y `message` pueden localizarse. Estados mínimos previstos: `400`, `401`, `403`, `404`, `409`, `412`, `415`, `422`, `429` y `500`. `429` incluye `Retry-After` cuando sea calculable.

## 7. Jobs asíncronos

Parsing, IA, generación de informes, sincronización Signal, notificaciones y otros trabajos lentos nunca bloquean una petición HTTP.

```text
POST /api/v1/dossiers/{id}/reports       -> 202 + BackgroundJob
GET  /api/v1/jobs/{job_id}               -> estado durable
POST /api/v1/jobs/{job_id}/cancel        -> solicitud de cancelación si es segura
```

Un job contiene como mínimo `id`, `kind`, `status`, progreso seguro, timestamps y enlaces al recurso resultado/error. El acceso está scoped por tenant y permisos. PostgreSQL conserva el estado durable en `BackgroundJob`; Redis/Celery no es la fuente de verdad.

Las tareas reciben IDs pequeños, `tenant_id` validado y `correlation_id`, nunca objetos ORM, cookies o secretos. Son idempotentes, tienen timeouts y retry con backoff/jitter. La cancelación es cooperativa: no se promete si la operación ya está confirmada. Los errores públicos del job se redactan; el diagnóstico detallado queda en logs protegidos.

## 8. Módulos previstos

Los nombres finales se fijarán en OpenAPI. El mapa inicial es:

| Módulo | Namespace orientativo | Responsabilidad |
|---|---|---|
| Identidad y sesión | `/api/v1/auth`, `/api/v1/me` | Login, logout, perfil, sesiones y preferencias |
| Plataforma | `/api/v1/platform` | Tenants y operaciones de superadmin diferenciadas |
| Administración tenant | `/api/v1/tenant` | Usuarios, memberships, roles e integraciones |
| Expedientes | `/api/v1/dossiers` | `StrategicDossier`, objetivos, hipótesis y watchlists |
| Señales | `/api/v1/signals`, `/api/v1/signal-monitors` | Inbox, revisión, vínculos y monitores |
| Oportunidades y riesgos | `/api/v1/opportunities`, `/api/v1/risks` | Triage, scoring explicado, evidencia y estado |
| Actores | `/api/v1/actors`, `/api/v1/relationships` | Actores, roles y relaciones |
| Acción | `/api/v1/meetings`, `/api/v1/tasks`, `/api/v1/decisions` | Reuniones, briefings, tareas y decisiones |
| Documentos y evidencia | `/api/v1/documents`, `/api/v1/evidence` | Upload, parsing, chunks, fuentes y trazabilidad |
| Informes e insights | `/api/v1/reports`, `/api/v1/insights` | Informes, resultados IA y feedback humano |
| Asíncrono | `/api/v1/jobs` | Estado durable y cancelación segura |
| Notificaciones | `/api/v1/notifications` | Bandeja y preferencias |
| Auditoría | `/api/v1/audit-events` | Consulta/exportación autorizada del audit trail |
| Signal Avanza | `/api/v1/integrations/signal-avanza` | Salud, monitores, sync y webhook firmado |

Una `Signal` puede asociarse a varios expedientes mediante `DossierSignal`; por ello el contrato productivo no conservará la suposición actual del fixture `Signal.dossierId` como relación única.

## 9. Signal Avanza y webhooks

El frontend nunca llama a Signal Avanza. Flask usa `SignalAvanzaAdapter` con implementaciones mock determinista y HTTP real.

Los eventos entrantes:

- se autentican con HMAC sobre los bytes exactos, timestamp y versión de firma;
- se rechazan fuera de una ventana anti-replay;
- se deduplican por `event_id`, `provider_id` y/o hash estable;
- conservan payload bruto y normalizado con acceso restringido y política de retención;
- responden rápido después de persistir de forma atómica la entrega; el procesamiento se delega a Celery;
- registran intentos y fallos en `WebhookDelivery`, con reprocesado autorizado.

Los secretos de webhook/API se almacenan cifrados y son rotables. Nunca aparecen en el OpenAPI, logs o UI.

## 10. Versionado y compatibilidad

- `/api/v1` marca la versión mayor del contrato.
- Cambios aditivos compatibles se publican dentro de `v1` con OpenAPI actualizado.
- Renombrar/eliminar campos, cambiar semántica o endurecer requisitos de forma incompatible requiere deprecación y una nueva versión mayor o una estrategia de transición explícita.
- Campos nuevos deben ser tolerables para clientes; enums requieren una política de evolución documentada antes de generar el cliente TS.
- La versión del prompt IA, del adaptador Signal y del payload de webhook es independiente de la versión HTTP y se registra explícitamente.
- CI debe detectar cambios incompatibles del OpenAPI y regeneración pendiente del cliente.

## 11. Requisitos de prueba del contrato

Antes de sustituir el mock deben existir, como mínimo:

- tests de schema request/response y `application/problem+json`;
- tests de cookie, CSRF y revocación server-side;
- tests negativos cross-tenant/IDOR para cada recurso;
- tests de permisos por acción y recurso;
- tests de paginación, filtros, allowlist de ordenación y límites;
- tests de concurrencia e idempotency key;
- tests de job scoped, retry e idempotencia con worker real de integración;
- contract tests del mock y HTTP de `SignalAvanzaAdapter`, incluidas firma y replay;
- generación reproducible y typecheck del cliente TypeScript;
- E2E frontend usando el cliente generado, no fixtures productivos.

## 12. Cuestiones pendientes

1. Elegir framework de schemas/OpenAPI compatible con Flask y la generación TypeScript.
2. Fijar la política uniforme `404`/`403` para recursos ajenos sin introducir oráculos de existencia.
3. Decidir paginación offset frente a cursor por cada colección de alta escritura.
4. Definir máximos de página, filtros y campos ordenables por endpoint.
5. Definir origen y ciclo de vida exactos del token CSRF y la estrategia para SSR de Next.js.
6. Elegir `ETag`/`If-Match` o campo `version` como convención principal.
7. Acordar retención de jobs, audit events, payloads Signal y documentos.
8. Cerrar el contrato técnico real de Signal Avanza, sus versiones de firma y rotación de claves.
9. Determinar si OpenAPI y métricas serán públicos, internos o protegidos en producción.

