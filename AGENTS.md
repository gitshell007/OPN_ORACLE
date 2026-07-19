# AGENTS.md — OPN Oracle Full-Stack

## 1. Misión del repositorio

Este repositorio contiene **OPN Oracle**, un producto independiente de inteligencia estratégica cuya entidad central es el **expediente estratégico** (`StrategicDossier`). Oracle convierte señales, documentación y relaciones dispersas en oportunidades, riesgos, actores, reuniones, decisiones, tareas e informes trazables.

El producto es transversal y debe funcionar para cualquier sector. Defensa, energía, grafeno, Iberdrola, S.I.G. u otros casos solo pueden aparecer como ejemplos sintéticos o fixtures opcionales; nunca como restricciones del dominio.

Oracle es **ofensivo por defecto**: ayuda a descubrir oportunidades, alianzas, convocatorias, cambios y siguientes acciones. La capa de riesgo protege el avance estratégico sin dominar la experiencia.

---

## 2. Decisiones técnicas vinculantes

1. El backend autoritativo es **Python + Flask**.
2. El frontend puede usar Next.js/React/TypeScript y ejecutar un servidor Node para renderizado, pero Node no puede contener lógica de negocio, acceso a PostgreSQL, autenticación autoritativa, jobs ni integraciones críticas.
3. Toda API productiva vive bajo Flask, preferiblemente en `/api/v1`.
4. La base de datos es PostgreSQL y la aplicación es multi-tenant desde el inicio.
5. Redis se usa para sesiones server-side, rate limiting, caché y Celery; no es la fuente de verdad.
6. Celery ejecuta tareas lentas, reintentables y programadas. No ejecutes IA, parsing, Signal o informes largos dentro de una petición HTTP.
7. Signal Avanza queda detrás de `SignalAvanzaAdapter`; nunca acoples dominio o UI a su API concreta.
8. La autenticación web usa cookie de sesión opaca, `HttpOnly`, `Secure`, `SameSite`, CSRF y revocación server-side. No uses JWT ni tokens de sesión en `localStorage`.
9. Toda salida IA relevante debe tener evidencia, confianza, prompt versionado y auditoría.
10. Los despliegues de producción deben ser reproducibles, reversibles y no exponer PostgreSQL ni Redis a Internet.

---

## 3. Fuentes de verdad y orden de lectura

Antes de modificar código, busca y lee en este orden:

1. `AGENTS.md`.
2. `OPN_Oracle_Codex_Memory.md` o `OPN_Oracle_Codex_Memory(1).md`.
3. `01_IMPLEMENTATION_PLAN.md` o `docs/implementation/PLAN.md`.
4. `docs/implementation/STATUS.md`, `DECISIONS.md` y `OPEN_QUESTIONS.md`.
5. El prompt específico de la fase actual.
6. `README.md`, ADRs, OpenAPI, scripts, configuración y tests.
7. El código existente de la zona afectada.

Si hay contradicción:

- prevalece la instrucción explícita más reciente de la tarea actual;
- después este `AGENTS.md`;
- después la memoria de producto;
- después los ADRs aceptados;
- después la documentación técnica existente.

No resuelvas silenciosamente una contradicción importante. Regístrala en `DECISIONS.md` o `OPEN_QUESTIONS.md`.

---

## 4. Interfaz canónica

La decisión de producto vigente es:

```text
CANONICAL_UI=vector
```

**Vector Command Center** es la base canónica: navegación lateral, alta densidad operativa y datatables como patrón principal.

El repositorio conserva temporalmente **Horizon Decision Canvas** como material del escaparate comparativo, pero no debe recibir duplicación de funcionalidades productivas. Su retirada se hará de forma controlada cuando las rutas de Vector hayan migrado a la aplicación autenticada y existan pruebas que protejan el cambio.

Reglas:

- aplica el design system y el shell de Vector a login, producto, administración y plataforma;
- no mezcles tokens o layouts de Horizon en la interfaz productiva;
- comparte únicamente dominio, cliente API y utilidades neutrales;
- documenta la retirada del prototipo alternativo antes de borrarlo;
- no bloquees el backend por la existencia temporal de las rutas `/concept-b/*`.

---

## 5. Límites de arquitectura

### Frontend

Responsable de:

- presentación y navegación;
- formularios y validación de conveniencia;
- tablas, gráficos, mapas y feedback visual;
- caché de server state;
- accesibilidad y responsive;
- route guards para UX, sin considerarlos autorización;
- consumo del cliente TypeScript generado desde OpenAPI.

No responsable de:

- contraseñas, hashing o sesiones;
- autorización final;
- queries directas a PostgreSQL;
- secretos de integraciones;
- Celery/jobs;
- llamadas directas a Signal o proveedores IA desde el navegador;
- reglas críticas de scoring o tenant isolation.

### Backend Flask

Responsable de:

- identidad, sesiones y autorización;
- tenant context y aislamiento;
- lógica de dominio y persistencia;
- API, OpenAPI y validación;
- Signal Avanza, IA y otras integraciones;
- Celery y jobs;
- auditoría, evidencias y secretos;
- generación de informes y notificaciones.

### Infraestructura

- Nginx termina TLS y enruta `/api` a Flask y `/` al frontend.
- Gunicorn sirve Flask; nunca uses `flask run` en producción.
- PostgreSQL y Redis solo viven en red privada/loopback.
- Certbot gestiona el certificado de `oracle.opnconsultoria.com`.
- Docker Compose es la opción por defecto para un único servidor, salvo que el repositorio o servidor tenga una plataforma ya aceptada.

---

## 6. Convenciones del backend Python

### 6.1 Estructura

Usa application factory y extensiones desacopladas:

```text
apps/api/src/opn_oracle/
  app.py
  config.py
  extensions.py
  wsgi.py
  celery_app.py
  common/
  auth/
  platform/
  tenants/
  oracle/
  integrations/
  ai/
  notifications/
  cli/
```

Cada módulo puede contener:

```text
models.py
schemas.py
repository.py
service.py
permissions.py
routes.py
tasks.py
errors.py
```

No coloques toda la aplicación en un único `app.py`.

### 6.2 Calidad

- Python con type hints.
- Ruff para lint/format.
- mypy o pyright según lo ya presente.
- pytest y cobertura.
- SQLAlchemy 2.x style.
- Alembic/Flask-Migrate para cada cambio de esquema.
- Dependencias fijadas y lockfile reproducible.
- Nada de imports circulares por app global; usa `current_app` o inyección explícita.

### 6.3 API

- prefijo `/api/v1`;
- OpenAPI generado;
- validación de entrada y salida;
- errores coherentes `application/problem+json`;
- request ID y correlation ID;
- paginación, filtros y ordenación server-side;
- idempotency key donde haya riesgo de duplicado;
- optimistic concurrency/ETag o `version` en edición sensible;
- no devuelvas modelos ORM sin schema explícito;
- no filtrar trazas o SQL al cliente.

---

## 7. Multi-tenancy

### 7.1 Regla absoluta

Todo recurso de negocio debe pertenecer a un tenant o estar explícitamente clasificado como global de plataforma. No existe una consulta tenant-scoped sin tenant context.

### 7.2 Controles

- `tenant_id` en tablas de negocio;
- scoping central en repositorios/servicios;
- autorización por acción y recurso;
- PostgreSQL RLS como defensa en profundidad cuando se implemente;
- UUIDs no enumerables;
- índices y constraints por tenant;
- audit event para accesos cross-tenant;
- tests negativos de IDOR y aislamiento.

No confíes en un `tenant_id` enviado por el cliente. Derívalo de la sesión/membership o de una selección validada.

### 7.3 Superadmin

`platform_super_admin` puede gestionar tenants, pero no debe navegar datos privados de un tenant sin:

- seleccionar tenant objetivo;
- permiso explícito;
- motivo de acceso;
- evento de auditoría;
- interfaz diferenciada del uso normal.

---

## 8. Autenticación y sesiones

### Stack orientativo

- Flask-Login;
- Flask-Session con Redis;
- Flask-WTF/CSRFProtect o control equivalente;
- Argon2id mediante `argon2-cffi`;
- Flask-Limiter con backend Redis;
- tokens de invitación/reset aleatorios, de un solo uso y almacenados hasheados.

### Reglas

- cookie `HttpOnly`, `Secure` en producción y `SameSite=Lax` salvo razón documentada;
- rotar session ID tras login, elevación, cambio de contraseña o cambios sensibles;
- timeout inactivo y absoluto;
- tabla `UserSession` para listar y revocar;
- logout actual y logout-all;
- fresh login para contraseña, roles, integraciones o acciones de alto riesgo;
- mensajes anti-enumeración;
- rate limits para login/reset/invite;
- no self-registration pública salvo requisito explícito;
- nunca guardar password, session ID, CSRF o reset token en logs.

El frontend debe enviar cookies con `credentials: include` cuando sea necesario y adjuntar CSRF en mutaciones.

---

## 9. Dominio Oracle

Entidades mínimas:

- `StrategicDossier`;
- `DossierObjective`;
- `Hypothesis`;
- `Watchlist`;
- `SignalMonitor`;
- `Signal` y `DossierSignal`;
- `Evidence`;
- `Opportunity`;
- `RiskItem`;
- `Actor`, `DossierActor`, `Relationship`;
- `Meeting`, `Briefing`;
- `Report`, `Decision`, `Task`;
- `Document`, `DocumentChunk`;
- `Insight`, `Feedback`;
- `AIAuditLog`, `BackgroundJob`.

### Reglas de producto

- `StrategicDossier` sigue siendo la unidad central.
- Una señal puede vincularse a varios expedientes.
- Hechos, inferencias, recomendaciones y decisiones son conceptos separados.
- Cada score debe tener explicación, fecha, evidencia y confianza.
- No hardcodees sectores en el core.
- No generes conclusiones sin fuentes.
- No conviertas Oracle en CRM, carpeta, Sentinel renombrado o simple feed.

---

## 10. Signal Avanza

Implementa:

```python
class SignalAvanzaAdapter(Protocol):
    def create_monitor(...): ...
    def update_monitor(...): ...
    def pause_monitor(...): ...
    def sync_signals(...): ...
    def get_signal(...): ...
```

Debe haber:

- `MockSignalAvanzaAdapter` determinista;
- `HttpSignalAvanzaAdapter` real;
- contrato/versionado;
- HMAC/timestamp en webhooks;
- idempotencia por event ID/provider ID/hash;
- cursor incremental;
- raw payload y payload normalizado;
- retries y registro de entregas fallidas;
- credenciales cifradas y rotables.

No llames a Signal directamente desde componentes frontend.

---

## 11. Celery y Redis

### Tareas

- idempotentes;
- con retry/backoff/jitter;
- con soft/hard time limit;
- con tenant ID y correlation ID;
- con estado durable en `BackgroundJob`;
- transacciones cortas;
- sin pasar objetos ORM serializados por la cola;
- payloads pequeños basados en IDs;
- sin secretos en argumentos o logs.

### Colas

- `default`;
- `signals`;
- `ai`;
- `documents`;
- `notifications`;
- `maintenance`.

No uses Redis como único historial de tareas. Worker y beat deben ser procesos/servicios separados.

---

## 12. IA y prompts de runtime

- proveedores detrás de adapter;
- prompts en archivos versionados (`name/version`);
- salidas validadas con Pydantic/JSON Schema;
- temperatura y límites definidos por caso;
- evidencia obligatoria;
- hechos/inferencias/recomendaciones separadas;
- incertidumbre explícita;
- `AIAuditLog` con hashes, sources, modelo, prompt version, latencia y coste estimado;
- redacción de datos sensibles antes de modelos externos;
- feedback humano persistente;
- evals y fixtures deterministas.

Si una respuesta no cumple schema, no la guardes como insight válido. Registra error y reintenta de forma limitada.

---

## 13. Frontend y UX

### Stack por defecto

Si ya existe, respétalo. Si falta:

- Next.js App Router;
- React + TypeScript estricto;
- Tailwind + shadcn/ui + Radix;
- TanStack Query y TanStack Table;
- React Hook Form + Zod;
- Lucide;
- Recharts y React Flow solo cuando aporten valor;
- Vitest y Playwright.

### Reglas

- cliente API tipado generado desde OpenAPI;
- no importar fixtures en rutas productivas;
- permisos del frontend solo mejoran UX, no sustituyen backend;
- datatables con paginación/ordenación/filtros server-side;
- loading, skeleton, empty, error, forbidden y session-expired;
- formularios accesibles con errores claros;
- WCAG 2.2 AA;
- microcopy en español de España;
- no usar color como única señal;
- mantener calidad enterprise, sobria y no decorativa.

### Pantallas obligatorias

- login/reset/invite;
- portfolio/command center;
- expediente completo;
- signal inbox;
- oportunidades y riesgos;
- actores/relaciones;
- reuniones, informes, tareas y decisiones;
- notificaciones;
- ajustes de cuenta y sesiones;
- usuarios/roles/integraciones del tenant;
- portal de superadmin.

---

## 14. Seguridad de servidor y producción

Antes de tocar un servidor:

1. Realiza auditoría read-only.
2. Confirma hostname/IP/OS/recursos/servicios.
3. Verifica DNS A y AAAA.
4. Haz backup de configuraciones relevantes.
5. Presenta diff de cambios.
6. No cambies SSH ni firewall de manera que pueda bloquear el acceso sin confirmación.
7. No desinstales ni sobrescribas servicios existentes sin autorización.

Producción:

- Gunicorn detrás de Nginx;
- TLS válido y redirect HTTP→HTTPS;
- Certbot renewal probado;
- PostgreSQL/Redis no publicados;
- Redis con ACL/password y red privada;
- UFW solo con puertos necesarios;
- `.env`/secret files con permisos restrictivos;
- backups cifrados y fuera del servidor;
- logs rotados;
- health checks;
- deploy y rollback documentados.

Nunca pegues secretos en comandos que queden en history cuando exista una alternativa segura.

---

## 15. Base de datos y migraciones

- cada cambio de modelo requiere migración;
- revisa el SQL autogenerado;
- no ejecutes `drop`, truncado o pérdida de columna sin backup y aprobación;
- usa expand/contract para cambios incompatibles;
- migrations deben ejecutarse una vez por release, no por cada worker;
- incluye downgrade cuando sea seguro; documenta cuando no lo sea;
- prueba migración desde un snapshot representativo;
- no edites una migration ya aplicada en producción; crea una nueva.

PostgreSQL es la fuente de verdad. Redis puede borrarse sin perder datos de negocio, aunque haya que reautenticar o reencolar.

---

## 16. Testing obligatorio

### Backend

- unit tests de servicios y scoring;
- integration tests con PostgreSQL real de prueba;
- API tests de permisos, validación y errores;
- tenant isolation tests por recurso;
- auth/CSRF/rate limit/session revocation;
- Celery integration con worker;
- contract tests de Signal;
- migration tests.

### Frontend

- unit/component tests donde aporten valor;
- Playwright para login, navegación, CRUD, sesión y permisos;
- accesibilidad automática + revisión manual;
- responsive y errores de consola;
- contract con API client generado.

### Producción

- smoke test HTTPS;
- health/readiness;
- migración;
- worker/beat;
- cert renewal dry-run;
- backup y restore test;
- restart test.

No afirmes que una prueba pasó si no se ejecutó. Incluye comando y resultado.

---

## 17. Observabilidad y auditoría

- logs JSON;
- `request_id`, `correlation_id`, `job_id`, `tenant_id` y actor cuando proceda;
- redacción de secretos y PII sensible;
- `/health/live` sin dependencias;
- `/health/ready` con DB/Redis y dependencias críticas;
- métricas protegidas;
- error tracking configurable;
- audit trail separado de logs técnicos;
- retención y exportación de auditoría.

Un `AuditEvent` debe registrar quién, tenant, acción, recurso, resultado, timestamp, request ID y metadata segura.

---

## 18. Flujo de trabajo obligatorio para Codex

1. Inspecciona Git y no destruyas cambios del usuario.
2. Lee las fuentes de verdad.
3. Actualiza `docs/implementation/STATUS.md`.
4. Formula un plan corto y verificable para la fase.
5. Implementa; no te detengas tras planificar salvo gate explícito.
6. Ejecuta checks después de cada bloque.
7. Revisa diffs y migraciones.
8. Abre la app y realiza smoke visual cuando afecte al frontend.
9. Actualiza documentación y decision log.
10. Entrega resumen exacto de archivos, comandos, resultados, riesgos y siguientes pasos.

Para tareas amplias, usa subagentes aislados por módulo: backend, frontend, DB, tests, seguridad e infraestructura. Integra y revisa todo antes de finalizar.

### Commits

Si el usuario autoriza commits:

- un commit lógico por fase o unidad coherente;
- mensajes descriptivos;
- no mezclar reformateos masivos;
- no hacer force push;
- no borrar ramas.

---

## 19. Comandos esperados

Adapta a las herramientas existentes, pero proporciona equivalentes:

```bash
# Backend
make api-install
make api-lint
make api-typecheck
make api-test
make api-migrate
make api-run

# Frontend
make web-install
make web-lint
make web-typecheck
make web-test
make web-build
make web-e2e

# Stack local
make dev-up
make dev-down
make logs
make test

# Producción / validación
make compose-config
make smoke
make backup
make restore-test

# Backend completo sin Docker cuando ya existen PostgreSQL/Redis locales de prueba
cd apps/api
ORACLE_RUN_INTEGRATION=1 \
TEST_DATABASE_URL='postgresql+psycopg://oracle_migrator:ci-migrator-only@127.0.0.1:5432/oracle_test' \
TEST_RUNTIME_DATABASE_URL='postgresql+psycopg://oracle_app:ci-app-only@127.0.0.1:5432/oracle_test' \
TEST_REDIS_URL='redis://127.0.0.1:6379/14' \
~/.local/bin/uv run pytest -q
```

No introduzcas un Makefile si el repositorio ya tiene una solución equivalente sólida; documenta los comandos reales.

En esa receta de integración, no asumas que el shell interactivo ajusta el `PATH`: usa la ruta real
de `uv` o exporta explícitamente `~/.local/bin`. Dos escollos conocidos de aislamiento: Celery
puede reconfigurar logging con `disable_existing_loggers` al arrancar worker real, y
`configure_logging` limpia `root.handlers` al construir la app, lo que puede retirar el handler de
`caplog`.

---

## 20. Definición de terminado por cambio

Un cambio no está terminado hasta que:

- cumple el requisito funcional;
- aplica tenant scoping y permisos;
- tiene validación y errores;
- tiene tests adecuados;
- no expone secretos;
- actualiza OpenAPI y cliente TS si cambia contrato;
- incluye migración si cambia esquema;
- documenta configuración/variables nuevas;
- los endpoints nuevos o modificados se prueban por despacho HTTP real (`client.get/post/...`),
  no invocando funciones de vista;
- cada test nuevo se verifica mutando el comportamiento que cubre; el resumen declara qué mutó y
  qué test cayó;
- ningún test afirma sobre código fuente, docstrings, comentarios ni nombres de símbolo: prueba
  comportamiento observable, estado, contrato HTTP o artefactos;
- si introduce configuración, recorre dataclass, parseo, `compose.prod.yml` y
  `infra/production/oracle.env.example`, y comprueba que la variable llega al contenedor;
- si corrige un fallo, barre el repo buscando el mismo patrón y declara búsqueda y resultado;
- si toca un valor con medición registrada en comentario o `DECISIONS.md`, explica por qué sigue
  siendo seguro;
- si altera un contrato con datos existentes, incluye recuento de filas afectadas;
- la suite de integración se ejecuta; si no, queda como riesgo abierto con motivo;
- lint, tipos, tests y build pasan;
- no hay errores relevantes de consola;
- `STATUS.md` refleja el estado real.

---

## 21. Formato del resumen final de Codex

Siempre informa:

1. objetivo completado;
2. decisiones tomadas;
3. archivos principales;
4. migraciones y variables nuevas;
5. comandos ejecutados y resultado;
6. pruebas no ejecutadas y motivo;
7. riesgos/deuda real;
8. cambios manuales o credenciales aún necesarios;
9. mutaciones aplicadas y resultado;
10. barrido del patrón: qué se buscó, dónde y qué apareció;
11. invariantes tocados: mediciones o decisiones registradas afectadas;
12. siguiente prompt/fase recomendada.

Evita “todo funciona” sin evidencias concretas. Nombra gates solo cuando se hayan ejecutado todos
sus comandos: “Ruff correcto” exige `ruff check` y `ruff format --check`.
