# OPN Oracle — Plan director de implementación full-stack

**Estado:** plan de ejecución para construir la aplicación completa  
**Backend obligatorio:** Python + Flask  
**Frontend:** Next.js/React/TypeScript u otra tecnología ya existente en el repositorio, sin lógica de negocio autoritativa en Node  
**Infraestructura objetivo:** PostgreSQL, Redis, Celery, Gunicorn, Nginx y TLS para `oracle.opnconsultoria.com`  
**Unidad central:** expediente estratégico (`StrategicDossier`)  
**Capa de señales:** Signal Avanza mediante adaptador desacoplado

---

## 1. Decisiones vinculantes

1. El backend de negocio, autenticación, autorización, persistencia, auditoría, integraciones y tareas se implementa en **Python con Flask**.
2. Next.js puede ejecutar el servidor de renderizado del frontend, pero no puede convertirse en un backend paralelo. No se usarán Route Handlers, Server Actions ni una base de datos desde Node para lógica crítica.
3. La aplicación usará autenticación por **sesión de servidor**, con cookie `HttpOnly`, `Secure` y `SameSite`, datos de sesión en Redis y protección CSRF. No se almacenarán JWT ni tokens de sesión en `localStorage`.
4. El producto será multi-tenant desde el principio. Todo dato de negocio tendrá un contexto de tenant explícito y pruebas automáticas de aislamiento.
5. PostgreSQL será la fuente de verdad. Redis servirá para sesiones, rate limiting, caché y broker/result backend de Celery; nunca será la fuente de verdad del producto.
6. Las tareas largas, sincronizaciones, análisis, informes y notificaciones se ejecutarán con Celery. Las peticiones web no deben esperar a procesos de IA, parsing o Signal.
7. Signal Avanza estará detrás de un contrato estable (`SignalAvanzaAdapter`). Se implementará primero un mock y después el cliente HTTP real.
8. Todo insight importante generado por IA tendrá fuentes/evidencias, versión de prompt, modelo, confianza y registro de auditoría.
9. La infraestructura será reproducible. Para un único servidor se recomienda Docker Compose para la aplicación y servicios internos, con Nginx y Certbot en el host.
10. Ningún secreto se incluirá en Git, prompts, commits, logs, capturas o documentación. Las credenciales se inyectarán mediante variables/secretos del entorno de despliegue.

---

## 2. Arquitectura objetivo

```text
Internet
   |
   v
oracle.opnconsultoria.com : 443
   |
[Nginx en el host]
   |-- /api/*  --> 127.0.0.1:8000 --> Gunicorn --> Flask (Python)
   |-- /       --> 127.0.0.1:3000 --> Next.js frontend
   |
   +-- Certificado Let's Encrypt / Certbot

Red privada de Docker Compose
   |
   |-- api              Flask + Gunicorn
   |-- web              Next.js
   |-- worker-default   Celery: señales, notificaciones, mantenimiento
   |-- worker-ai        Celery: análisis, informes, memoria
   |-- beat             Celery scheduler
   |-- postgres         PostgreSQL
   |-- redis            Redis con ACL/password, no expuesto a Internet
   +-- opcional: flower/metrics, solo red privada o acceso restringido
```

### Flujo de una operación

```text
Frontend
  -> /api/v1/... (misma origin, cookie de sesión + CSRF)
  -> Flask valida identidad, tenant, rol y payload
  -> servicio de dominio ejecuta la operación en PostgreSQL
  -> si hay trabajo pesado crea BackgroundJob y encola Celery
  -> Celery procesa de forma idempotente
  -> frontend consulta estado o recibe notificación
```

### Flujo de señales

```text
Expediente -> Watchlist -> SignalMonitor
  -> SignalAvanzaAdapter.create/update/sync
  -> Signal Avanza entrega señales por webhook o cursor
  -> Oracle guarda payload bruto + señal normalizada
  -> Celery realiza triage, entidades, oportunidad/riesgo
  -> usuario revisa, corrige o promueve
  -> feedback alimenta la memoria del expediente
```

---

## 3. Estructura de repositorio recomendada

Adaptar sin reescribir destructivamente el frontend existente.

```text
opn-oracle/
├── AGENTS.md
├── README.md
├── OPN_Oracle_Codex_Memory.md
├── docs/
│   ├── architecture/
│   │   ├── 0001-fullstack-boundaries.md
│   │   ├── 0002-auth-sessions.md
│   │   ├── 0003-multitenancy.md
│   │   ├── 0004-signal-contract.md
│   │   └── 0005-production-topology.md
│   ├── api/
│   ├── operations/
│   ├── security/
│   └── implementation/
│       ├── STATUS.md
│       ├── DECISIONS.md
│       └── OPEN_QUESTIONS.md
├── apps/
│   ├── web/                         # Next.js/React/TypeScript
│   └── api/                         # paquete Python instalable
│       ├── pyproject.toml
│       ├── src/opn_oracle/
│       │   ├── app.py               # create_app
│       │   ├── config.py
│       │   ├── extensions.py
│       │   ├── wsgi.py
│       │   ├── celery_app.py
│       │   ├── common/
│       │   ├── auth/
│       │   ├── platform/
│       │   ├── tenants/
│       │   ├── oracle/
│       │   ├── integrations/
│       │   ├── ai/
│       │   ├── notifications/
│       │   └── cli/
│       ├── migrations/
│       └── tests/
├── packages/
│   ├── api-client/                  # cliente TS generado desde OpenAPI
│   └── ui/                          # opcional, componentes compartidos
├── infra/
│   ├── compose/
│   ├── nginx/
│   ├── systemd/
│   ├── scripts/
│   └── backups/
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
└── Makefile
```

Si el repositorio ya tiene otra estructura sólida, conservarla y documentar el mapeo.

---

## 4. Plan por fases y puertas de control

### Fase 0 — Auditoría del repositorio y decisiones pendientes

**Objetivo:** conocer el estado real antes de instalar, migrar o borrar nada.

**Trabajo:**

- inspeccionar Git, ramas, cambios no committeados, gestor de paquetes y frontend A/B;
- identificar si ya se eligió Vector o Meridian;
- inventariar componentes, fixtures, repository abstraction y rutas;
- inspeccionar si existe backend, Docker, CI/CD o configuración de servidor;
- crear ADRs y `docs/implementation/STATUS.md`;
- acordar estructura definitiva del monorepo;
- congelar el límite: Python manda, frontend representa.

**Puerta:** no iniciar integración visual completa hasta definir `CANONICAL_UI=vector|meridian`. El backend puede construirse antes.

**Salida:** informe de auditoría, decisiones, riesgos y plan adaptado al repo.

---

### Fase 1 — Fundación profesional Flask

**Objetivo:** disponer de una API Python ejecutable, testeable y documentada.

**Trabajo:**

- paquete Python con `pyproject.toml` y dependencias fijadas mediante lockfile;
- Flask con application factory, blueprints, extensiones desacopladas y configuración por entorno;
- SQLAlchemy 2.x, migraciones Alembic/Flask-Migrate y PostgreSQL;
- OpenAPI 3, validación de request/response y errores `application/problem+json`;
- request/correlation ID, logging JSON y redacción de secretos;
- endpoints `/health/live`, `/health/ready` y `/api/v1/meta`;
- Gunicorn y Dockerfile multi-stage;
- Ruff, mypy, pytest, cobertura y pre-commit;
- Compose de desarrollo con PostgreSQL y Redis.

**Puerta:** lint, tipos, tests, migración inicial, build de imagen y health checks deben pasar.

---

### Fase 2 — PostgreSQL y multi-tenancy

**Objetivo:** establecer un modelo de datos que impida fugas entre clientes.

**Entidades de plataforma:**

- `Tenant`, `Workspace`, `User`, `TenantMembership`;
- `Role`/`Permission` o matriz de permisos versionada;
- `Invitation`, `PasswordResetToken`, `UserSession`;
- `AuditEvent`, `ApiCredential`, `IntegrationConnection`;
- `UserSettings`, `NotificationPreference`.

**Entidades Oracle:**

- `StrategicDossier`, `DossierObjective`, `Hypothesis`;
- `Watchlist`, `SignalMonitor`;
- `Signal`, `DossierSignal`, `Evidence`;
- `Opportunity`, `RiskItem`;
- `Actor`, `DossierActor`, `Relationship`;
- `Meeting`, `Briefing`, `Report`, `Decision`, `Task`;
- `Document`, `DocumentChunk`, `Insight`, `Feedback`;
- `AIAuditLog`, `BackgroundJob`, `WebhookDelivery`, `OutboxEvent`.

**Reglas:**

- UUID, timestamps con zona horaria y restricciones explícitas;
- índices por `tenant_id`, fechas, estado y scores;
- una señal puede vincularse a varios expedientes mediante `DossierSignal`;
- tenant scoping en servicios/repositorios y, como defensa en profundidad, políticas RLS en tablas tenant-scoped;
- transacciones claras; migraciones revisadas, reversibles cuando sea posible y versionadas;
- tests negativos de aislamiento por cada módulo.

**Puerta:** un usuario de tenant A no puede leer, modificar, inferir ni enumerar recursos de tenant B, incluso alterando IDs.

---

### Fase 3 — Login, superadministración, tenants y sesiones

**Objetivo:** identidad y autorización enterprise sin tokens inseguros en el navegador.

**Backend:**

- Flask-Login para identidad de sesión;
- Flask-Session con Redis para sesión server-side;
- CSRF para mutaciones, cookies seguras y rotación de sesión;
- Argon2id para contraseñas;
- rate limiting, backoff/bloqueo temporal y mensajes anti-enumeración;
- endpoints de login, logout, `me`, cambio de contraseña, sesiones activas y revocación;
- CLI segura para crear el primer `platform_super_admin` sin password hardcodeado;
- creación/suspensión/reactivación de tenants;
- invitación de propietario/admin del tenant;
- RBAC con permisos comprobados en backend;
- auditoría de login, logout, fallos, revocación, cambios de rol y acceso superadmin.

**Frontend:**

- login, sesión caducada, acceso denegado y recuperación/invitación;
- guardas de ruta sin confiar solo en el cliente;
- menú de usuario, perfil, contraseña, preferencias y sesiones;
- portal de superadmin y administración de tenant;
- selector de tenant si el usuario pertenece a varios.

**Puerta:** pruebas de CSRF, cookie flags, revocación inmediata, tenant isolation, rate limit y control de permisos.

---

### Fase 4 — API del dominio Oracle

**Objetivo:** sustituir fixtures por datos persistentes manteniendo la UX elegida.

**Módulos:**

1. Expedientes, objetivos, hipótesis y estado.
2. Watchlists y monitores.
3. Inbox de señales, revisión, descarte y promoción.
4. Oportunidades y riesgos con scoring explicado.
5. Actores, roles y relaciones.
6. Tareas, decisiones, hitos y reuniones.
7. Informes, briefings y living summary.
8. Auditoría y feedback.

**Características API:**

- `/api/v1` versionada;
- paginación, filtros, búsqueda, ordenación y selección para datatables;
- ETag u optimistic concurrency para evitar sobrescrituras silenciosas;
- idempotency keys en operaciones sensibles;
- OpenAPI generado y cliente TypeScript reproducible;
- respuestas y errores coherentes;
- permisos por acción y recurso.

**Puerta:** paridad funcional con los flujos de la demo y pruebas de contrato frontend/backend.

---

### Fase 5 — Celery y Redis

**Objetivo:** sacar del request todos los trabajos lentos o reintentables.

**Colas recomendadas:**

- `default`: tareas generales;
- `signals`: sincronización, normalización y triage;
- `ai`: análisis y generación;
- `documents`: parsing, chunking y embeddings;
- `notifications`: email e in-app;
- `maintenance`: limpieza, digest y retención.

**Requisitos:**

- Celery integrado con application factory y contexto Flask;
- tareas idempotentes, límites de tiempo, reintentos con backoff y jitter;
- estado durable en `BackgroundJob`, no depender solo del result backend;
- correlation ID, tenant ID y actor en logs;
- worker y beat separados;
- endpoints de estado/cancelación cuando sea seguro;
- limpieza de resultados y sesiones caducadas;
- tests con worker real en integración.

**Puerta:** caída/reinicio de worker no duplica operaciones ni deja registros inconsistentes.

---

### Fase 6 — Integración Oracle ↔ Signal Avanza

**Objetivo:** recibir señales reales sin acoplar Oracle al código interno de Signal.

**Oracle:**

- `SignalAvanzaAdapter` con `MockSignalAvanzaAdapter` y `HttpSignalAvanzaAdapter`;
- credenciales cifradas y rotables;
- creación/actualización/pausa de monitor;
- sync por cursor y webhook firmado;
- idempotencia, deduplicación, raw payload, normalización y trazabilidad;
- outbox para órdenes salientes e inbox para eventos entrantes;
- DLQ lógica/tabla de entregas fallidas y re-procesado manual;
- panel de salud de integración.

**Signal (otra sesión):**

- endpoints de monitores y señales;
- modelo de task/monitor Oracle;
- webhook con HMAC, timestamp y event ID;
- reintentos, cursores, filtros y contrato versionado;
- sandbox y pruebas E2E.

**Puerta:** prueba de contrato y E2E con un monitor, dos sincronizaciones y un webhook repetido sin duplicados.

---

### Fase 7 — Agentes IA, prompts y auditoría

**Objetivo:** implementar inteligencia estructurada, verificable y versionada.

**Servicios/agentes:**

- Intake;
- Signal Triage;
- Entity Resolution;
- Opportunity Analyst;
- Risk Analyst;
- Actor & Partnership;
- Meeting Briefing;
- Report Writer;
- Memory Curator;
- Evidence/Quality Reviewer.

**Reglas:**

- proveedor/modelo detrás de adaptador;
- prompts en archivos versionados, nunca strings dispersos;
- salidas JSON validadas con Pydantic/JSON Schema;
- hechos, inferencias y recomendaciones separados;
- evidencia obligatoria y nivel de confianza;
- datos sensibles redactados según política;
- auditoría de prompt version, hashes, sources, latencia y coste estimado;
- feedback humano y re-procesado;
- evals con casos sintéticos y regresión.

**Puerta:** ninguna conclusión importante sin evidencia; outputs inválidos se rechazan y reintentan de forma controlada.

---

### Fase 8 — Documentos, evidencias y búsqueda

**Objetivo:** convertir documentos internos en contexto trazable.

**Trabajo:**

- storage adapter local/S3-compatible;
- subida con tipo/tamaño permitido, checksum y estado;
- parsing de PDF, DOCX, TXT y transcripciones;
- fragmentos con localización y vínculo a documento;
- PostgreSQL full-text y, si se aprueba, pgvector;
- permisos y tenant isolation en archivos y chunks;
- eliminación/retención y antivirus opcional;
- citas desde informes hasta fragmento original.

**Puerta:** descargar o buscar un documento de otro tenant es imposible; cada cita abre la evidencia correcta.

---

### Fase 9 — Aplicación frontend completa

**Objetivo:** convertir la dirección visual elegida en producto real.

**Áreas:**

- login y recuperación;
- command center/portfolio;
- expediente y sus pestañas;
- signal inbox y panel de detalle;
- oportunidades, riesgos, actores y relaciones;
- reuniones, informes, tareas y decisiones;
- centro de notificaciones;
- cuenta, sesiones y preferencias;
- administración de usuarios, roles e integraciones;
- portal superadmin;
- estados loading/empty/error/offline;
- tablas server-side, filtros guardados, deep links y permisos visuales;
- accesibilidad WCAG 2.2 AA y responsive.

**Puerta:** no quedan fixtures en las rutas productivas; Playwright cubre los flujos críticos.

---

### Fase 10 — Calidad, seguridad y observabilidad

**Objetivo:** demostrar que el sistema es operable y resistente.

**Calidad:**

- unit, integration, contract y E2E;
- cobertura útil por dominio, no solo porcentaje;
- pruebas de concurrencia, idempotencia y migraciones;
- test de aislamiento multi-tenant obligatorio;
- pruebas de carga smoke con Locust.

**Seguridad:**

- SAST/dependency audit y secret scan;
- rate limits, CSRF, XSS/CSP, clickjacking, upload hardening;
- no exposición de OpenAPI/admin/metrics en producción sin control;
- logs sin secretos ni datos sensibles;
- revisión de permisos y auditoría.

**Observabilidad:**

- logs JSON con request ID/job ID;
- health/readiness;
- métricas de API, DB, Celery y Signal;
- error tracking configurable;
- panel/alertas mínimas;
- audit logs separados de logs técnicos.

**Puerta:** checklist de seguridad y runbook de incidentes revisados.

---

### Fase 11 — Servidor, PostgreSQL, Nginx y certificado

**Objetivo:** desplegar de forma reproducible en el servidor al que apunta el dominio.

**Orden seguro:**

1. Recibir credenciales por canal seguro y variables temporales, nunca en Git.
2. Conectar por SSH y ejecutar **auditoría solo lectura**.
3. Confirmar host, OS, recursos, servicios existentes, puertos y espacio.
4. Verificar DNS A/AAAA de `oracle.opnconsultoria.com` y que 80/443 llegan al host.
5. Hacer backup de configuraciones y base existente si la hubiera.
6. Instalar/validar Docker Engine + Compose, Nginx y Certbot por métodos soportados.
7. Configurar firewall sin modificar SSH de forma arriesgada.
8. Desplegar stack en red privada; PostgreSQL y Redis no se publican.
9. Ejecutar migraciones y bootstrap del superadmin.
10. Configurar Nginx para frontend y `/api`.
11. Obtener certificado Let's Encrypt y validar renovación automática.
12. Ejecutar smoke tests externos, reinicio controlado y rollback test.
13. Activar backups, rotación de logs y monitorización.

**Puerta crítica:** antes de cualquier cambio destructivo o de sustituir un servicio existente, detenerse y pedir confirmación con el diff exacto.

---

### Fase 12 — CI/CD, backup, UAT y release

**Objetivo:** que el producto pueda actualizarse y recuperarse de forma segura.

**Trabajo:**

- pipeline de lint, types, tests, build, migración dry-run y security scan;
- artefactos/imágenes versionados, sin tags flotantes;
- despliegue con release ID, backup previo, migración y smoke test;
- rollback de aplicación; estrategia explícita para migraciones no reversibles;
- backup diario PostgreSQL cifrado y copia fuera del servidor;
- prueba de restauración documentada;
- UAT con tenant sintético;
- checklist de go-live y handover operativo.

**Puerta:** no declarar producción lista sin una restauración probada y una renovación de certificado simulada.

---

## 5. Modelo de identidad y permisos

### Roles de plataforma

- `platform_super_admin`: gestiona tenants y configuración global; cada acceso cross-tenant queda auditado.
- `platform_support` opcional: acceso limitado y temporal, sin datos sensibles por defecto.

### Roles de tenant

- `tenant_owner`: control total del tenant y facturación/configuración sensible.
- `tenant_admin`: usuarios, roles, integraciones y configuración.
- `editor`: modifica expedientes y contenido.
- `analyst`: revisa señales, crea insights e informes.
- `viewer`: lectura.
- `auditor`: lectura de evidencias y auditoría, sin edición.

### Principios

- backend autoritativo; ocultar un botón no es autorización;
- menor privilegio;
- fresh login para acciones sensibles;
- cambios de rol revocan/rotan sesiones según riesgo;
- acceso superadmin con motivo obligatorio y audit event;
- permisos evaluados sobre `tenant_id`, resource owner y action.

---

## 6. Contrato de sesiones

- Cookie opaca; datos de sesión en Redis.
- `HttpOnly=true`, `Secure=true` en producción, `SameSite=Lax` por defecto.
- nombre de cookie no genérico y `Path=/`.
- rotación del identificador al iniciar sesión, elevar privilegios o cambiar contraseña.
- timeout inactivo y timeout absoluto configurables.
- tabla `user_sessions` para mostrar/revocar dispositivos.
- logout individual y logout de todas las sesiones.
- no registrar cookie, password, CSRF ni token de reset.
- CSRF requerido en POST/PUT/PATCH/DELETE.
- rate limits diferenciados para login, reset e invitación.

---

## 7. Contrato mínimo de API

```text
/api/v1/auth/*
/api/v1/platform/tenants/*
/api/v1/tenants/current/*
/api/v1/users/*
/api/v1/sessions/*
/api/v1/dossiers/*
/api/v1/signals/*
/api/v1/opportunities/*
/api/v1/risks/*
/api/v1/actors/*
/api/v1/relationships/*
/api/v1/tasks/*
/api/v1/meetings/*
/api/v1/reports/*
/api/v1/documents/*
/api/v1/notifications/*
/api/v1/integrations/signal-avanza/*
/api/v1/audit/*
/api/v1/jobs/*
```

OpenAPI será la fuente para generar el cliente TypeScript. Los componentes no deben construir URLs manualmente de forma dispersa.

---

## 8. Datos y secretos que harán falta

No incluir valores secretos en este documento. Antes de producción se necesitará:

- host/IP, puerto SSH, usuario y método de autenticación;
- confirmación de `sudo` y sistema operativo;
- email para Let's Encrypt;
- URL del repositorio y estrategia de despliegue;
- `POSTGRES_PASSWORD` y roles de base de datos;
- credenciales Redis/ACL;
- `SECRET_KEY`, clave de cifrado de integraciones y CSRF;
- email del primer superadmin; el password se introduce de forma interactiva o one-time;
- SMTP/proveedor de email para invitaciones y reset;
- API base, API key y webhook secret de Signal Avanza;
- proveedor/modelo de IA y credenciales;
- destino de backups externos;
- almacenamiento de documentos (local/S3-compatible);
- Sentry/monitorización si se usa.

---

## 9. Riesgos principales y mitigación

| Riesgo | Mitigación |
|---|---|
| El frontend A/B aún no tiene ganador | Construir backend independiente y bloquear consolidación visual hasta `CANONICAL_UI` |
| Fuga entre tenants | Scoping central, RLS, IDs no secuenciales, tests negativos y auditoría |
| Node se convierte en backend paralelo | Prohibir DB/auth/business logic en Next; Flask es la autoridad |
| Sesiones robadas o no revocables | Redis server-side, rotación, tabla de sesiones, cookies seguras, CSRF y fresh login |
| Tareas duplicadas | Idempotency keys, locks, outbox/inbox y estado durable de jobs |
| Signal cambia su API | Adapter, contrato versionado, mock y contract tests |
| IA inventa conclusiones | Evidencia obligatoria, structured output, reviewer, auditoría y feedback humano |
| Despliegue rompe servidor existente | Auditoría read-only, backups, diff previo, red privada y rollback |
| Certificado no se emite | Verificar DNS/AAAA/puertos antes; staging ACME para pruebas |
| Redis/PostgreSQL expuestos | No publicar puertos; firewall y red interna |
| Pérdida de datos | backups cifrados, offsite y restore test |
| Migración irreversible | expand/contract, backup, revisión manual y release gate |

---

## 10. Definición global de terminado

OPN Oracle se considera listo para producción solo cuando:

1. El frontend elegido funciona con datos reales de Flask, sin fixtures productivos.
2. El backend es Python/Flask y no hay lógica de negocio autoritativa en Node.
3. PostgreSQL, Redis, Celery worker y beat tienen health checks y reinicio seguro.
4. Login, logout, invitaciones, sesiones, superadmin, tenants y RBAC están probados.
5. El aislamiento multi-tenant tiene pruebas automatizadas y defensa en profundidad.
6. Los módulos Oracle principales tienen CRUD, filtros y auditoría.
7. Signal funciona por adapter con idempotencia y prueba E2E.
8. Los outputs IA son estructurados, auditables y basados en evidencias.
9. La aplicación tiene estados de carga/error/vacío y pruebas E2E críticas.
10. `oracle.opnconsultoria.com` sirve HTTPS válido, HTTP redirige y la renovación está probada.
11. PostgreSQL y Redis no son accesibles desde Internet.
12. Existe pipeline CI/CD, backup offsite, restauración probada y rollback documentado.
13. No hay secretos en Git ni logs.
14. La documentación operativa permite a otra persona desplegar, diagnosticar y restaurar.

---

## 11. Orden de ejecución de los prompts

1. `prompts/00_MASTER_ORCHESTRATOR_SOL.md`
2. `prompts/01_REPOSITORY_AUDIT.md`
3. Sustituir el `AGENTS.md` de raíz por el incluido en este pack.
4. `prompts/02_FLASK_FOUNDATION.md`
5. `prompts/03_DATABASE_MULTITENANCY.md`
6. `prompts/04_AUTH_SESSIONS_RBAC.md`
7. `prompts/05_FRONTEND_AUTH_ADMIN.md`
8. `prompts/06_ORACLE_CORE_DOMAIN.md`
9. `prompts/07_CELERY_REDIS.md`
10. `prompts/08_SIGNAL_ORACLE_SIDE.md`
11. En el repositorio de Signal: prompts de `signal/SIGNAL_TASK_PROMPTS.md`.
12. `prompts/09_AI_RUNTIME_AND_AUDIT.md`
13. `prompts/10_DOCUMENTS_EVIDENCE_SEARCH.md`
14. `prompts/11_REPORTS_NOTIFICATIONS_EXPORTS.md`
15. `prompts/12_FRONTEND_PRODUCT_COMPLETION.md`
16. `prompts/13_TESTING_SECURITY_OBSERVABILITY.md`
17. `prompts/14_PRODUCTION_INFRA_TLS.md`
18. `prompts/15_CICD_BACKUPS_RUNBOOK.md`
19. `prompts/16_FINAL_ACCEPTANCE_RELEASE.md`

Cada prompt debe ejecutarse en una sesión nueva o con contexto limpio cuando el repositorio haya cambiado de forma importante. Sol debe leer `AGENTS.md`, la memoria y `docs/implementation/STATUS.md` al comenzar.
