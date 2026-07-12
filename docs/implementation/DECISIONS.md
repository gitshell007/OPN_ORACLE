# Decisiones de implementación

## D-001 — Interfaz canónica Vector

- **Estado:** accepted
- **Fecha:** 2026-07-10
- **Contexto:** el prototipo ofrecía Vector y una segunda dirección visual.
- **Decisión:** `CANONICAL_UI=vector`. Vector Command Center será la base de navegación, densidad y componentes productivos.
- **Alternativas:** mantener dos aplicaciones completas; elegir la segunda propuesta; crear un híbrido inmediato.
- **Consecuencias:** la integración Flask y la arquitectura definitiva se aplicarán a Vector. El segundo concepto no recibirá duplicación de features productivas y podrá retirarse cuando la migración esté asegurada.

## D-002 — Flask es el backend autoritativo

- **Estado:** accepted
- **Fecha:** 2026-07-10
- **Contexto:** el repositorio actual es un frontend con repositorio mock.
- **Decisión:** toda lógica de negocio, persistencia, autenticación, autorización, jobs e integraciones vivirá en Python/Flask bajo `/api/v1`.
- **Alternativas:** FastAPI; Route Handlers/Server Actions de Next.js; backend Node.
- **Consecuencias:** Next.js queda limitado a presentación/rendering. Los tipos cliente derivarán de OpenAPI.

## D-003 — Evolución incremental del repositorio

- **Estado:** accepted
- **Fecha:** 2026-07-10
- **Contexto:** mover ahora el frontend sin tests de integración aumentaría el riesgo sobre cambios no committeados.
- **Decisión:** crear inicialmente `apps/api` y conservar el frontend en la raíz. La migración a `apps/web` se evaluará de forma separada cuando Flask y los comandos de monorepo estén estabilizados.
- **Alternativas:** mover inmediatamente todo a `apps/web`; mantener repositorios separados.
- **Consecuencias:** menor disrupción inicial, a cambio de una estructura transitoria documentada.

## D-004 — Sesiones opacas server-side

- **Estado:** accepted
- **Fecha:** 2026-07-10
- **Decisión:** Flask-Login + Flask-Session/Redis, cookie `HttpOnly`, `Secure` en producción, `SameSite=Lax`, CSRF y revocación durable.
- **Alternativas:** JWT en navegador; proveedor auth externo.
- **Consecuencias:** no se almacenarán tokens de sesión en `localStorage`; el frontend validará identidad con `/auth/me`.

## D-005 — Multi-tenancy con doble control

- **Estado:** accepted
- **Fecha:** 2026-07-10
- **Decisión:** scoping central de repositorios/servicios y PostgreSQL RLS con runtime role sin `BYPASSRLS`.
- **Alternativas:** aislamiento solo en aplicación; base por tenant.
- **Consecuencias:** toda tabla de negocio incorpora `tenant_id`, pruebas negativas e índices/constraints tenant-aware.

## D-006 — Trabajo lento mediante Celery

- **Estado:** accepted
- **Fecha:** 2026-07-10
- **Decisión:** Signal, IA, documentos, informes y notificaciones lentas se ejecutan como jobs Celery durables e idempotentes.
- **Alternativas:** trabajo síncrono en requests; colas solo Redis sin estado DB.
- **Consecuencias:** Redis no será fuente de verdad y `BackgroundJob` registrará estado durable.

## D-007 — Integraciones por adapters

- **Estado:** accepted
- **Fecha:** 2026-07-10
- **Decisión:** Signal Avanza, LLM, email y object storage tendrán protocolos estables con mocks deterministas y adapters reales configurables.
- **Alternativas:** llamadas directas desde UI/servicios de dominio.
- **Consecuencias:** la aplicación puede desarrollarse sin credenciales reales y falla de forma controlada cuando un proveedor está deshabilitado.

## D-008 — Topología de producción inicial

- **Estado:** accepted for local release artifacts; remote application gated
- **Fecha:** 2026-07-11
- **Decisión:** Docker Compose para web/API/worker/beat/PostgreSQL/Redis, con Nginx y Certbot en el host; solo web/API enlazados a loopback. En el host actual de 3,7 GiB se consolida un worker con concurrencia 1 y se mantienen IA, documentos y Signal HTTP deshabilitados.
- **Alternativas:** servicios host; plataforma existente; imágenes desde registry.
- **Consecuencias:** la auditoría confirma un host limpio y sin conflictos, pero la aplicación remota sigue detrás del gate explícito de fase 14. Antes de carga real intensiva se recomienda ampliar a 8 GiB y separar colas.

## D-009 — Secret files explícitos en producción

- **Estado:** accepted
- **Fecha:** 2026-07-11
- **Contexto:** URLs de PostgreSQL/Redis/Celery contienen credenciales y no deben interpolarse en Compose ni aparecer en argumentos o logs.
- **Decisión:** `Settings` admite únicamente un allowlist de variables `*_FILE` con ruta absoluta y falla si coexisten valor inline y archivo. Compose monta ficheros externos; API/web usan UID/GID fijo `10001` y Redis genera su ACL en tmpfs desde un secret file.
- **Alternativas:** `.env` con todos los secretos; Docker Swarm/Kubernetes secrets; secret manager externo.
- **Consecuencias:** el host debe aplicar ownership numérico por consumidor y `0400`; las URLs completas se consideran secretas. Migrar a un secret manager seguirá siendo compatible con archivos materializados efímeramente.

## D-010 — Correo transaccional mediante Microsoft Graph

- **Estado:** accepted
- **Fecha:** 2026-07-11
- **Decisión:** producción usa `MAIL_BACKEND=graph` con client credentials server-to-server, secreto por `GRAPH_CLIENT_SECRET_FILE` y `/users/{sender}/sendMail`. Tenant y client ID son configuración no secreta; el Object ID no participa en runtime.
- **Seguridad:** permiso de aplicación mínimo `Mail.Send` con consentimiento administrativo y alcance de buzón restringido cuando Exchange lo permita. Invitaciones, resets y notificaciones se entregan exclusivamente mediante `BackgroundJob`/Celery; no se envían desde requests HTTP.
- **Consecuencias:** Graph/SMTP se consideran proveedores no idempotentes y aplican semántica at-most-once ante resultado incierto. Habilitar producción exige credencial de aplicación válida y buzón remitente existente.

## D-011 — Releases sin metadata AppleDouble

- **Estado:** accepted
- **Fecha:** 2026-07-11
- **Contexto:** una transferencia desde macOS incorporó ficheros `._*.py` al release; Alembic los
  interpretó como módulos Python y detuvo el bootstrap por bytes nulos antes de aplicar esquema.
- **Decisión:** todo artefacto de release, contexto Docker y ZIP excluye `._*` y `.DS_Store`; el
  release se valida con SHA-256 después de limpiar metadata y nunca se corrige in-place tras firmarlo.
- **Consecuencias:** las correcciones operativas generan un release nuevo. Los builds transfieren
  únicamente contenido portable y conservan la trazabilidad del artefacto rechazado.

## D-012 — Control de backups separado por privilegio

- **Estado:** accepted
- **Fecha:** 2026-07-11
- **Contexto:** Flask y Celery no deben acceder al socket Docker, al filesystem de backups ni poder
  reemplazar la base de datos de la que dependen.
- **Decisión:** la web solo crea operaciones globales auditadas. Un agente systemd root reclama
  backups manuales/programados; los restores quedan `awaiting_approval` hasta un comando root/TTY
  concreto. La recuperación usa base nueva, validación y swap por rename con rollback preservado.
- **Alternativas:** montar Docker socket en API/worker; ejecutar `pg_restore` desde una request;
  restaurar destructivamente sobre la base actual.
- **Consecuencias:** el superadmin controla y solicita desde Vector sin recibir privilegios del host.
  La restauración necesita una breve coordinación operativa, pero nunca ejecuta `DROP`, conserva la
  base anterior y puede volver atrás tras un smoke fallido.

## D-013 — GitHub Actions y GHCR para candidatos inmutables

- **Estado:** accepted; activación productiva manual y protegida
- **Fecha:** 2026-07-11
- **Contexto:** el remote autoritativo es GitHub y no existía pipeline versionado.
- **Decisión:** PR/push ejecutan frontend, integración PostgreSQL/Redis/Celery, migraciones, scans,
  imágenes y SBOM. `workflow_dispatch` publica candidatos GHCR etiquetados solo por commit.
  Producción conserva `oracle-control.sh` y los tres gates de backup; el workflow falla cerrado
  mientras no exista un canal de despliegue aprobado.
- **Consecuencias:** CI no necesita credenciales productivas y no se introduce un bypass de los
  gates operativos ni una clave SSH en el repositorio.

## D-014 — Perfiles iniciales explícitos por tipo de expediente

- **Estado:** accepted
- **Fecha:** 2026-07-11
- **Contexto:** el tipo de expediente era únicamente una clasificación. Al crear un expediente,
  el usuario necesitaba un punto de partida coherente sin imponer un sector ni automatizar
  vigilancia externa.
- **Decisión:** el alta ofrece una base inicial editable, activada explícitamente desde la
  interfaz. En la misma transacción crea un objetivo, dos hipótesis y una watchlist con fuentes
  sugeridas y versión de perfil. No crea monitores ni realiza llamadas a proveedores externos.
- **Alternativas:** crear solo una etiqueta; crear monitores automáticamente; imponer plantillas
  inmutables por sector.
- **Consecuencias:** los expedientes API existentes conservan el comportamiento vacío por defecto;
  la interfaz informa del contenido antes de crearlo y permite desactivar la base inicial.

## D-015 — Oráculo contextual gobernado por Signal

- **Estado:** implemented; activación cloud gated
- **Fecha:** 2026-07-11
- **Contexto:** cada expediente necesita sintetizar documentación, señales y dominio en una visión
  actual, similar al patrón de Oráculo de Nexus, pero con evidencia y aislamiento propios de Oracle.
- **Decisión:** Oracle construirá el contexto, las citas, la auditoría y la UX; Signal será el único
  proxy de modelos mediante `dossier_situation_summary`. El primario será Ollama
  `qwen3.5:9b` y el fallback activo Ollama Titan `qwen3.6:27b`. OpenRouter/Gemini queda diseñado
  como opción futura, pero sin política activa.
- **Consecuencias:** no habrá llamadas directas a proveedores desde Oracle. El fallback cloud no se
  activa hasta fijar presupuesto, clasificación/redacción y política de tratamiento de datos.

## D-016 — TypeScript estable para toolchain frontend

- **Estado:** accepted
- **Fecha:** 2026-07-11
- **Contexto:** `typescript@latest` resolvió a 7.0.2 y rompió `openapi-typescript` y ESLint por
  APIs internas todavía no compatibles.
- **Decisión:** fijar `typescript@5.8.3` en devDependencies.
- **Consecuencias:** `npm run api:client:generate`, `npm run api:client:check`, `npm run lint`,
  `npm run typecheck`, tests y build vuelven a ser reproducibles sin workarounds temporales.
