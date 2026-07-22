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

- **Estado:** superseded by D-031 for CI/release gating; host activation still manual/protected
- **Fecha:** 2026-07-11
- **Contexto:** el remote autoritativo es GitHub y no existía pipeline versionado.
- **Decisión:** PR/push ejecutan frontend, integración PostgreSQL/Redis/Celery, migraciones, scans,
  imágenes y SBOM. `workflow_dispatch` publica candidatos GHCR etiquetados solo por commit.
  Producción conserva `oracle-control.sh`; el workflow falla cerrado mientras no exista un canal de
  despliegue aprobado.
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

## D-017 — Resumen persistente nocturno del expediente

- **Estado:** accepted
- **Fecha:** 2026-07-12
- **Contexto:** el Oráculo ya publicaba versiones persistentes, pero dependía de una petición
  manual y reutilizaba indefinidamente un trabajo exitoso si el contexto no cambiaba.
- **Decisión:** Celery Beat crea cada noche, a las 03:15 en `Europe/Madrid`, un trabajo durable por
  expediente no archivado. La clave nocturna se limita a expediente y fecha local. El botón usa
  `Idempotency-Key`: repetir la misma petición deduplica, una nueva pulsación crea otra versión.
- **Consecuencias:** entrar en el expediente es siempre lectura; la versión anterior permanece
  visible durante la generación o si Signal/Ollama falla. El primario es `qwen3.5:9b` y el
  fallback técnico es Ollama Titan `qwen3.6:27b`, ambos gobernados por Signal.

## D-018 — Candidatos de actor derivados de fuentes

- **Estado:** accepted
- **Fecha:** 2026-07-12
- **Contexto:** el directorio de actores solo permitía vincular registros previamente existentes y
  no ofrecía una revisión intermedia de empresas, personas u organismos mencionados en señales.
- **Decisión:** las entidades estructuradas de señales vinculadas se presentan como candidatos
  tenant/dossier-scoped. La lista es derivada y reproducible; importarla exige confirmación humana
  de tipo, etiquetas y roles, crea o reutiliza el actor canónico y conserva la procedencia.
- **Alternativas:** crear actores automáticamente al ingerir; ejecutar NER libre sobre cada visita;
  persistir una segunda copia de todas las entidades detectadas.
- **Consecuencias:** no se confunde una mención con un actor confirmado, no se añade una tabla
  duplicada de candidatos y la procedencia de cada mención permanece visible.

## D-019 — Recuperación conservadora y ledger de revisión de candidatos

- **Estado:** accepted
- **Fecha:** 2026-07-12
- **Contexto:** algunas señales históricas o contratos parciales no contienen `entities`, aunque el
  título o resumen nombren claramente organizaciones. Además, un candidato descartado reaparecía al
  derivar de nuevo la lista desde sus fuentes.
- **Decisión:** normalizar primero entidades de Signal y payloads conocidos; solo ante ausencia se
  aplican patrones textuales conservadores, siempre como candidatos pendientes. Los descartes e
  importaciones se registran por tenant, expediente y clave canónica en un ledger con RLS, revisor,
  fuentes y auditoría. El ledger no copia el contenido completo del candidato.
- **Alternativas:** crear actores automáticamente; ejecutar un NER remoto durante cada lectura;
  ocultar descartes solo en estado de frontend.
- **Consecuencias:** señales antiguas como la de CATL/Stellantis producen candidatos sin una llamada
  externa y los descartes sobreviven a recargas. Los patrones pueden omitir menciones ambiguas, por
  lo que Signal continúa siendo la fuente preferente de entidades estructuradas.

## D-020 — Promoción encadenada, no atómica, desde una señal nueva

- **Estado:** accepted
- **Fecha:** 2026-07-12
- **Contexto:** promover exige una señal revisada, pero obligar a cerrar y reabrir el drawer añadía
  fricción al flujo central.
- **Decisión:** la interfaz encadena revisión y apertura del formulario de promoción usando las
  mutaciones existentes, cada una con sus garantías propias. La promoción conserva su
  `Idempotency-Key`; no se añade un endpoint compuesto.
- **Consecuencias:** el usuario puede convertir una señal nueva con continuidad visible, sin ocultar
  la revisión humana ni debilitar la idempotencia o concurrencia del backend.

## D-021 — Pre-scoring de triaje marcado como provisional

- **Estado:** accepted
- **Fecha:** 2026-07-12
- **Contexto:** `signal_triage` ya calcula una valoración auditable con evidencia, pero mientras el
  job no termina el valor persistido `0` se confundía con una valoración real de cero.
- **Decisión:** exponer un estado calculado de puntuación en la API sin alterar el valor numérico:
  pendiente antes de triaje, provisional tras triaje y revisado tras intervención humana.
- **Consecuencias:** la UI no inventa puntuaciones, puede priorizar las señales que ya tienen una
  valoración provisional y comunica con honestidad cuándo aún espera el triaje local gobernado por
  Signal.

## D-022 — Despliegue rápido con backup local verificado

- **Estado:** accepted
- **Fecha:** 2026-07-13
- **Contexto:** los despliegues de iteración estaban quedando bloqueados por un receipt off-host
  cifrado que todavía no tiene proveedor automatizado. La evidencia manual en OneDrive añadía
  fricción y no mejoraba proporcionalmente el ciclo UAT.
- **Decisión:** el modo normal de despliegue durante construcción/UAT exige backup lógico local,
  checksums y restore aislado, pero no receipt off-host. Los releases siguen preparándose como
  artefactos separados en `/opt/opn-oracle/releases` y se activan con `oracle-control update` para
  mantener rollback. El modo estricto se conserva con `ORACLE_REQUIRE_OFFSITE_RECEIPT=1`.
- **Consecuencias:** los cambios pequeños pueden desplegarse casi al ritmo de copiar el commit y
  reiniciar servicios, sin perder rollback ni restore probado. La pérdida total del servidor sigue
  siendo riesgo aceptado para UAT y debe cerrarse antes de operación estable con datos críticos.

## D-023 — Deduplicación de ingesta por URL canónica y título/fuente

- **Estado:** accepted
- **Fecha:** 2026-07-13
- **Contexto:** Signal Avanza y los buscadores pueden entregar la misma historia con IDs de
  proveedor distintos, por búsquedas o fuentes diferentes. La idempotencia por `provider_signal_id`
  y `external_id` evita replays exactos, pero no evita duplicados semánticamente idénticos de la
  misma URL.
- **Decisión:** añadir una clave secundaria de deduplicación persistida en `signals.dedupe_key`.
  Cuando hay URL, se usa `url:<canonical_source_url>`; la canonicalización baja esquema/host a
  minúsculas, elimina fragmento, puerto por defecto, barra final y parámetros de tracking
  (`utm_*`, `gclid`, `fbclid`, `gbraid`, `wbraid`, `msclkid`, `mc_cid`, `mc_eid`). Cuando no hay
  URL, se usa `title:<source_name_normalized>:<title_normalized>` con `casefold` y espacios
  colapsados. La búsqueda queda indexada por `tenant_id`, `provider_connection_id` y `dedupe_key`.
- **Alternativas:** matching difuso/semántico, índice funcional sin columna persistida o limpieza
  automática de duplicados históricos.
- **Consecuencias:** se conserva una única señal nueva por historia dentro de una misma
  conexión+tenant, pero cada entrega mantiene su `SignalIngestionRecord` y sus contadores. No se
  fusionan datos históricos ni historias de fuentes distintas sin URL; una limpieza retroactiva
  deberá ser una operación explícita con evidencia y rollback.

## D-024 — CI completo manual durante la fase UAT rápida

- **Estado:** superseded by D-031
- **Fecha:** 2026-07-13
- **Contexto:** durante la construcción UAT se están haciendo varios commits pequeños y despliegues
  rápidos. Ejecutar backend integrado, migraciones, build de imágenes, Trivy y SBOM en cada push
  aporta seguridad, pero ralentiza el ciclo y genera ruido de notificaciones por commits
  intermedios que quedan corregidos minutos después.
- **Decisión:** desactivar temporalmente los disparadores automáticos del workflow `CI` en push y
  pull request. El CI completo se conserva como `workflow_dispatch` manual para validaciones antes
  de releases, puntos de control o cambios de mayor riesgo.
- **Consecuencias:** aumenta la agilidad y baja el ruido de GitHub. La responsabilidad del agente
  antes de desplegar pasa a ejecutar checks locales proporcionales y lanzar el CI manual cuando el
  cambio toque migraciones, seguridad, contratos críticos o vaya a convertirse en release estable.
  Antes de pasar de UAT a operación estable se deben restaurar triggers automáticos o un gate
  equivalente.

## D-031 — CI automático en PR y release atado al SHA validado

- **Estado:** accepted
- **Fecha:** 2026-07-17
- **Contexto:** el modo UAT rápido dejó `ci.yml` solo manual y `release.yml` podía publicar imágenes
  sin comprobar que el mismo commit hubiera superado CI. El prompt 35 demostró el riesgo: código con
  tests y lint en rojo pudo haberse publicado si no hubiera mediado revisión humana.
- **Decisión:** restaurar CI automático en `pull_request` hacia `master`, conservar
  `workflow_dispatch` para validaciones manuales puntuales y no añadir trigger en `push`. Antes de
  publicar imágenes, `release.yml` consulta GitHub Actions con el `GITHUB_TOKEN` y falla cerrado si
  no existe un run `CI` completado con `success` para el SHA exacto que se va a publicar.
- **Alternativas:** CI en cada push; mantener CI manual durante UAT; confiar en checks locales del
  agente antes de publicar.
- **Consecuencias:** se conserva velocidad en ramas, pero la puerta de publicación queda atada a un
  SHA validado. La protección de rama de `master` queda como cambio manual pendiente en GitHub para
  después de UAT, con checks requeridos documentados en `docs/operations/BRANCH_PROTECTION.md`.

## D-032 — Clasificación explícita de campos en snapshots PLACSP

- **Estado:** accepted
- **Fecha:** 2026-07-17
- **Contexto:** el snapshot durable de adjudicaciones PLACSP usaba una lista blanca silenciosa. Al
  ampliar Signal el contrato con `documents` e `is_ute`, Oracle fijaba adjudicaciones como
  `succeeded` pero descartaba esos campos; el informe documental recibía cero pliegos y Vector no
  podía mostrar el distintivo UTE en pins ya fijados.
- **Decisión:** los snapshots PLACSP pasan a declarar claves preservadas y claves consumidas para
  derivar campos. `documents` se preserva solo con `uri`, `doc_type` y `file_name`, deduplicado por
  `uri` y con límites duros; `is_ute` se conserva por entrada y se eleva al agregado si cualquier
  lote lo marca. Cualquier clave nueva que Signal devuelva sin clasificación genera warning
  operativo y debe añadirse a tests contractuales como preservada, consumida o descartada de forma
  deliberada.
- **Consecuencias:** Oracle deja de perder ampliaciones del contrato en silencio sin bloquear
  cambios aditivos de Signal en runtime. Los snapshots ya fijados antes de esta decisión no se
  migran automáticamente; si un expediente necesita documentos o UTE para un `folder_id` antiguo,
  debe desfijarse/refijarse o ejecutarse una reparación explícita y auditable.

## D-025 — Reintentos IA tras fallo terminalizado

- **Estado:** accepted
- **Fecha:** 2026-07-14
- **Contexto:** `execute_agent` trataba cualquier `AIAuditLog` previo del mismo job/agente como
  una reclamación definitiva, aunque el intento hubiese terminado en `failed`. Esto convertía un
  fallo transitorio de Signal/Ollama o del asentamiento JSON en tres intentos Celery inútiles y
  enmascaraba la causa raíz con `AIPolicyDenied`.
- **Decisión:** un audit `succeeded` con artefacto sigue deduplicando y se reutiliza; un audit
  `pending/running` sigue bloqueando ejecuciones simultáneas; un audit `failed/denied` puede
  reabrirse de forma controlada para crear nuevos `AIAttempt` dentro del mismo `BackgroundJob` y
  agente. Se conserva la constraint única `(tenant_id, background_job_id, agent)` de
  `ai_audit_logs`; el historial de cada entrega queda en `ai_attempts`.
- **Consecuencias:** los reintentos Celery vuelven a invocar realmente al proveedor gobernado. La
  no duplicación se mantiene para ejecuciones activas y artefactos ya publicados, y la auditoría
  conserva los intentos fallidos con su `error_code` original en `AIAttempt`.

## D-026 — Normalización segura de salidas IA para informes

- **Estado:** accepted
- **Fecha:** 2026-07-14
- **Contexto:** `report_writer` usa modelos locales gobernados por Signal que pueden devolver JSON
  semánticamente útil pero con deriva de forma: listas de strings donde el contrato exige objetos,
  prioridades no canónicas, índices de fuente inventados o párrafos marcados como `fact` sin
  evidencia. Rechazar todo el informe al final hacía fallar el flujo de usuario aunque existiera una
  versión publicable como inferencia trazable.
- **Decisión:** Oracle normaliza solo deriva recuperable antes de la validación Pydantic estricta:
  convierte strings a objetos mínimos, normaliza prioridades, elimina evidencias no autorizadas,
  degrada hechos sin cita a inferencias acotadas y reconstruye siempre `source_index` desde el
  snapshot inmutable de evidencias. La validación estricta y el reviewer siguen siendo obligatorios.
- **Consecuencias:** se reduce fragilidad ante modelos locales sin publicar hechos no citados ni
  aceptar fuentes inventadas. Si la salida no puede normalizarse de forma segura, el job sigue
  fallando y queda auditado para diagnóstico.

## D-027 — Grafo de entidad renderizado con Cytoscape detrás de Flask

- **Estado:** accepted
- **Fecha:** 2026-07-14
- **Contexto:** la fase F1 del prompt 34 necesita explorar relaciones de empresas y personas desde
  Signal sin acoplar el navegador al proveedor ni guardar todavía un subgrafo en expedientes.
- **Decisión:** Vector renderiza el grafo con Cytoscape.js y layout `fcose`, cargados de forma
  dinámica solo en la ruta de entidad. El navegador llama exclusivamente a Flask
  `/api/v1/entity-intel/*`; Flask aplica permiso `actor.read`, rate limit, allowlist del host,
  timeout, caché corto y cabecera `X-OPN-External-Tenant-ID` derivada de la conexión Signal activa.
- **Alternativas:** SVG propio, React Flow, llamadas directas desde Next a Signal o persistir el
  grafo desde F1.
- **Consecuencias:** F1 ofrece visualización interactiva básica y verificable sin abrir secretos ni
  decidir todavía recomendaciones, guardado o vinculación a expedientes. React Flow queda reservado
  para futuros flujos editables; Cytoscape es más adecuado para grafos densos de relación.

## D-028 — PLACSP se consulta y fija desde Oracle con Signal como productor

- **Estado:** accepted; follow-up 4b implemented
- **Fecha:** 2026-07-14
- **Contexto:** Signal ya indexa adjudicaciones y licitaciones PLACSP. Oracle necesita consumirlas
  desde la experiencia estratégica sin exponer claves, CORS ni contratos de productor al navegador.
- **Decisión:** Oracle publica `/api/v1/procurement/*` como proxy Flask. Los datos globales
  (`registry/awards`, `registry/tenders`, summaries y stats) usan solo `X-API-Key`; las búsquedas
  guardadas usan además `X-OPN-External-Tenant-ID` resuelto desde la conexión `signal-avanza`
  activa. Además, Oracle puede fijar licitaciones/adjudicaciones concretas al expediente en
  `dossier_procurement_items` como snapshot durable y crear una evidencia interna asociada para que
  `tender.v1` cite esos hechos con `evidence_ids`. La resolución del snapshot se hace por lookup
  directo de Signal (`registry/tenders/{folder_id}` y `registry/awards/{folder_id}`), no por búsqueda
  textual. Las adjudicaciones multilote se guardan como un pin único por `folder_id` con
  `snapshot.entries`.
- **Consecuencias:** Vector puede consultar contratación pública mediante permisos Oracle y
  seguridad server-side homogénea con `entity-intel`. Signal sigue siendo productor del dato vivo;
  Oracle conserva únicamente snapshots seleccionados por el usuario dentro del tenant/expediente.
  La evidencia creada por un pin usa `source_kind='procurement'` y una `provenance` honesta con
  `procurement_kind`, `folder_id` y `snapshot_sha256`; no entra en la cuarentena
  `legacy_unresolved`. El go/no-go de `tender.v1` continúa siendo recomendación revisable/humana, no
  una decisión automática.

## D-029 — Snapshot agregado para adjudicaciones PLACSP multilote

- **Estado:** accepted
- **Fecha:** 2026-07-17
- **Contexto:** la búsqueda de adjudicaciones puede devolver filas por lote con fecha e importe,
  mientras el pin por `folder_id` se guarda como un único snapshot agregado. La tarjeta fijada debe
  seguir mostrando los datos materiales que el proveedor entregó.
- **Decisión:** en adjudicaciones, Oracle conserva cada lote en `snapshot.entries` y eleva al nivel
  agregado `award_amount` como suma de importes publicados. Si todos los lotes comparten fecha,
  `award_date` guarda esa fecha; si hay varias fechas, guarda el rango `fecha_min/fecha_max`. Valores
  con forma de CIF/NIF español no se conservan como `lot_id`.
- **Consecuencias:** la UI puede mostrar importe y fecha sin perder el desglose de lotes, y evita
  presentar identificadores de adjudicatario como número de lote. Signal sigue siendo el productor
  autoritativo del XML/serialización PLACSP.

## D-030 — Activación de release sin restauración ciega tras mutaciones

- **Estado:** accepted
- **Fecha:** 2026-07-17
- **Contexto:** `oracle-control update` restauraba `current`, `CURRENT_RELEASE` y `ORACLE_RELEASE`
  al release anterior si `deploy-production.sh` fallaba. Cuando el fallo ocurría después de iniciar
  migraciones, arranque de contenedores o smoke loopback, esa restauración podía dejar punteros
  apuntando al release antiguo mientras los contenedores o el esquema ya reflejaban el release nuevo.
- **Decisión:** `deploy-production.sh` escribe una etapa de despliegue y `oracle-control update`
  solo restaura punteros si el fallo ocurre antes de `mutation_started`. Desde
  `mutation_started` en adelante conserva el release seleccionado, no revierte esquema y exige
  diagnóstico/forward-fix o rollback explícito si el esquema es compatible. `oracle-control health`
  incorpora una comprobación reusable de coherencia entre `current`, `CURRENT_RELEASE`,
  `ORACLE_RELEASE` y las imágenes en ejecución de `api`, `web`, `worker-core` y `beat`.
- **Consecuencias:** el operador ya no recibe una falsa sensación de rollback de aplicación tras
  un smoke fallido o una mutación parcial. La poda de imágenes solo sucede tras activación correcta
  y coherencia verificada; si la coherencia no puede garantizarse, el script lo declara
  explícitamente y no despliega/poda en silencio.

## D-031 — Excepción temporal para documentos oficiales PLACSP sin ClamAV

- **Estado:** accepted
- **Fecha:** 2026-07-17
- **Contexto:** la cadena documental PLACSP descarga y procesa PDFs oficiales, pero producción no
  tiene ClamAV desplegado. El scanner `noop` marca `scan_status=not_configured`, lo que bloqueaba el
  informe documental aunque la fuente fuese `contrataciondelestado.es` y el responsable haya
  pospuesto ClamAV.
- **Decisión:** `DOCUMENT_ALLOW_OFFICIAL_UNSCANNED=false` por defecto. Si se activa, y solo mientras
  `DOCUMENT_SCANNER_MODE=noop`, Oracle puede aceptar documentos `ready + not_configured` de
  `https://contrataciondelestado.es` para informes/citas PLACSP. Cada aceptación queda marcada en
  `document.scan_result.official_unscanned_acceptance`, se audita como
  `document.official_unscanned_accepted` y la UI muestra el badge «Fuente oficial · sin antivirus».
  Estados `infected` y `error` nunca se aceptan, aunque el flag esté activo.
- **Consecuencias:** se desbloquea el informe documental oficial sin fingir que el documento está
  limpio. Las rutas de lectura solo tratan como descargable/citable un documento limpio o ya marcado
  por esta aceptación auditada. La excepción debe retirarse cuando ClamAV quede desplegado.

## D-032 — Layout de grafo determinista con semillas no degeneradas

- **Estado:** accepted
- **Fecha:** 2026-07-17
- **Contexto:** tras hacer determinista el layout de entidades, `fcose` con `randomize=false` y sin
  posiciones iniciales podía arrancar desde una geometría degenerada; con ITURRI SA se observaron
  295 nodos en una diagonal.
- **Decisión:** mantener `randomize=false`, pero pasar a Cytoscape posiciones iniciales
  deterministas basadas en una espiral de ángulo áureo y hash estable por nodo. No se modifican los
  controles de zoom, el cronograma ni la ficha modal validados en el prompt anterior.
- **Consecuencias:** el resultado sigue siendo reproducible entre sesiones, pero `fcose` ya no parte
  de una línea/colapso cuando el proveedor entrega grafos grandes.

## D-033 — Agregados deterministas y cobertura explícita para inteligencia competitiva

- **Estado:** accepted
- **Fecha:** 2026-07-17
- **Contexto:** las adjudicaciones de Signal ofrecen un histórico paginado por adjudicatario, pero
  la licitación inicial no forma parte de cada fila y puede no existir en el registro de
  licitaciones. Además, `winner` contiene variantes registrales y socios UTE en texto libre.
- **Decisión:** el foco del informe se limita a una denominación exacta de una adjudicación fijada,
  mientras el corpus se obtiene de `awards(company=...)` hasta 1.000 filas. Oracle deduplica y
  agrega por `folder_id` en Python. La baja solo se publica con cobertura comparable de al menos
  80 % y tres expedientes; de lo contrario se omite y se declara N/denominador y sesgo de
  supervivencia. Los socios UTE se presentan como heurística de confianza baja. El LLM recibe los
  resultados congelados mediante una `task_key` gobernada por Signal y no recalcula valores.
- **Consecuencias:** el informe es reproducible, citable y explícito sobre truncamiento, identidad,
  ausencia de datos y calidad de parsing. Un adjudicatario con más de 1.000 filas no se describe
  como histórico completo. Cambiar umbrales o parsing exige una nueva versión del análisis/prompt.

## D-034 — Filtro temporal oculto y encuadre legible en grafos de entidad

- **Estado:** accepted
- **Fecha:** 2026-07-17
- **Contexto:** el prompt 39 dejó un cronograma que atenuaba nodos fuera de rango y un encuadre
  inicial orientado a mostrar mucho contexto. En producción, con ITURRI SA, el usuario prefirió
  una lectura operativa: elementos fuera de rango fuera de la vista y etiquetas legibles aunque el
  grafo no quepa completo.
- **Decisión:** el filtro temporal de entidades oculta aristas fuera de rango y nodos que quedan sin
  vínculos visibles mediante clases Cytoscape con `display: none`, sin reconstruir elementos ni
  relanzar layout. El encuadre inicial no usa `fit`; centra la entidad consultada con zoom legible y
  `fcose` persigue separación fija entre nodos.
- **Consecuencias:** la UI abandona la decisión previa de atenuar nodos fuera de rango. La leyenda y
  `STATUS.md` deben hablar de ocultación, no de atenuación. En grafos densos se prioriza exploración
  por pan sobre “verlo todo” comprimido.

## D-035 — Área de espera para informes IA de entidad

- **Estado:** accepted
- **Fecha:** 2026-07-17
- **Contexto:** el informe de una entidad se solicita desde la ficha global de Actores y el
  responsable quiere elegir el expediente destino solo cuando la generación termine. A la vez,
  `Report.dossier_id` y `AIArtifact.dossier_id` son no-null y forman parte de constraints y claves
  de informes de expediente.
- **Decisión:** no se hace nullable `Report.dossier_id` y no se fuerza elegir expediente al lanzar.
  El job `oracle.entity_dossier_report.generate` crea un artefacto de espera tenant+entidad: salida
  `ReportOutput`, métricas calculadas en Python, hash de corpus y `AIAuditLog` con `dossier_id=NULL`
  guardados en `BackgroundJob.result_ref`. Al incorporar, Oracle materializa un `Report` normal del
  expediente elegido, crea el `AIArtifact` ya con `dossier_id`, actualiza la auditoría con el
  expediente y materializa la entidad externa como Actor interno usando el flujo del prompt 44.
- **Consecuencias:** el informe no se pierde si el usuario abandona la ficha antes de elegir
  expediente, y el esquema de reporting conserva su invariante de informes siempre asociados a un
expediente. La primera versión permite una única incorporación por job porque `AIArtifact` es
único por `audit_log_id`; si producto necesita reutilizar el mismo análisis en varios expedientes,
deberá versionarse un flujo de copia/materialización separado.

## D-036 — Evidencia citable diferida para informes IA de entidad

- **Estado:** accepted
- **Fecha:** 2026-07-17
- **Contexto:** la ficha de entidad contiene actos BORME con `source_url` y noticias con URL, pero
  el informe IA de entidad recibía `allowed_evidence_ids=[]`. Como el prompt obliga a no publicar
  hechos sin evidencia, todo acababa degradado a inferencia aunque hubiera fuentes citables. A la
  vez, por D-035 el informe nace en un área de espera sin expediente destino.
- **Decisión:** durante la generación se construye un índice de fuentes citables desde el corpus
  compacto y se reservan UUIDs deterministas para cada fuente. Esos IDs se pasan al modelo como
  `allowed_evidence_ids` y se guardan en `BackgroundJob.result_ref` como
  `pending_evidence_sources`, pero no se insertan filas `Evidence` mientras el informe siga en
  espera. Al incorporar el informe, Oracle materializa esas fuentes como `Evidence` con
  `source_kind='entity_intel'`, las enlaza al expediente mediante `EvidenceDossier`, las congela en
  `ReportSnapshotEvidence`/`ReportEvidence` y reconstruye el `source_index` autoritativo desde el
  snapshot, no desde etiquetas libres del modelo.
- **Consecuencias:** el LLM puede formular hechos citables sin inventar fuentes y sin que queden
  evidencias huérfanas si el usuario nunca incorpora el informe. La evidencia refleja exactamente
  lo que Signal expone (enlace BORME/noticia y extracto normalizado), no el texto registral completo
  ni una desambiguación de homónimos que Oracle no posee.

## D-037 — Informe ejecutivo de entidad con agregados deterministas y muestra acotada

- **Estado:** accepted
- **Fecha:** 2026-07-18
- **Contexto:** el informe de entidad v1 convertía la ficha BORME en un catálogo, descartaba
  patentes/CNMV y no incorporaba contratación pública. Añadir todas las adjudicaciones como fuentes
  granulares habría reproducido el agotamiento de salida observado con los actos registrales.
- **Decisión:** Oracle calcula en Python los agregados de adjudicaciones por expediente
  (`folder_id`): importes totales/anuales, órganos, CPV principal, UTE y periodo. El informe de
  entidad no ejecuta la sonda de baja. El modelo recibe como evidencia solo las adjudicaciones de
  mayor importe que tengan URL, con defecto configurable
  `ENTITY_INTEL_MAX_AWARD_SOURCES=15`; el corpus, el recorte, la ausencia de CIF y el hecho de que
  solo se observan contratos ganados se declaran explícitamente. Patentes EPO y comunicaciones
  CNMV entran en el corpus compacto con topes y citas. Un fallo de la fuente de adjudicaciones
  degrada solo esa sección.
- **Consecuencias:** el prompt `entity_dossier_intelligence/v2` puede concentrar la salida en una
  lectura ejecutiva de 1.200-2.000 palabras sin delegar aritmética al LLM ni subir el presupuesto
  de 16.000 tokens. El v1 y `ReportOutput` permanecen intactos; la evidencia sigue materializándose
  únicamente al incorporar el informe por D-035/D-036.

## D-038 — Protocolo de verificación cruzando costuras

- **Estado:** accepted
- **Fecha:** 2026-07-19
- **Contexto:** los fallos recientes que llegaron a producción no estaban en la lógica de negocio,
  sino en fronteras que un editor no ve: despacho HTTP real, contenedor, provider externo,
  serialización desde base de datos, runtime de librerías y presupuesto de modelo. Parte del riesgo
  vino de prompts incompletos, especialmente cuando no declaraban invariantes ya medidos.
- **Decisión:** la definición de terminado exige probar endpoints por despacho HTTP real, verificar
  cada test nuevo por mutación, evitar tests sobre texto fuente, demostrar el cableado completo de
  configuración operativa, barrer patrones tras corregir fallos, declarar mediciones tocadas,
  contar filas afectadas por cambios de contrato y ejecutar integración o dejar su ausencia como
  riesgo abierto. Se añaden invariantes automáticos para configuración, rutas APIFlask, errores de
  red, techo global de fuentes citables y relectura JSON de modelos IA estrictos.
- **Consecuencias:** un verde local sin integración o sin mutación deja de ser una entrega completa.
  Los prompts futuros deben enunciar explícitamente los invariantes conocidos que el cambio pueda
  romper; si contradicen una medición registrada, Codex debe parar y señalarlo.

## D-039 — Plantillas versionadas e informes ejecutivos con cierre obligatorio

- **Estado:** accepted
- **Fecha:** 2026-07-19
- **Contexto:** las plantillas de reporting solo admitían una versión por clave. Al cambiar
  `entity_intelligence.v1` in situ, los informes ya creados con las secciones anteriores quedaron
  imposibles de revisar porque la validación exige que el output contenga todas las secciones de la
  plantilla asociada. El mismo riesgo aplicaba a `competitive_procurement`, que ya tiene informes
  reales en producción.
- **Decisión:** `ReportTemplateRegistry` queda indexado por `(key, version)` y `get(key)` resuelve
  la última versión disponible. `entity_intelligence.v1` se restaura byte a byte desde el histórico
  y el contrato ejecutivo vigente pasa a `entity_intelligence.v2`. El informe competitivo añade
  `competitive_procurement.v2` y `competitive_procurement_intelligence/v2`, con secciones
  analíticas, materialidad obligatoria y `Cobertura y límites` al final. `report_writer/v5`
  mantiene las plantillas existentes, pero elimina el anti-objetivo de brevedad mínima y exige
  campos ejecutivos de cierre.
- **Consecuencias:** los informes históricos siguen resolviendo su versión exacta sin migración de
  datos. Los informes nuevos congelan en el snapshot que los tres campos de cierre son obligatorios;
  las revisiones antiguas `v1` sin esa marca no quedan bloqueadas por el nuevo gate. Oracle declara
  16.000 tokens para `competitive_procurement_intelligence/v2`, pero Signal debe alinear la task
  gobernada para evitar truncado externo.

## D-040 — Control estructural para el informe IA de entidad

- **Estado:** accepted
- **Fecha:** 2026-07-21
- **Contexto:** activar `evidence_reviewer` en `entity_dossier_intelligence` falló en tres
  despliegues productivos aunque la generación del informe sí completaba. Se descartaron modelo
  local, proveedor Signal, presupuesto de salida y agregación de hechos. La causa demostrada es que
  el informe de entidad se redacta desde un corpus autorizado rico (`entity_dossier`, métricas,
  grafo, noticias, patentes, CNMV y contratación), mientras el revisor universal solo recibe claims
  compactos y extractos de evidencia citable. Por tanto juzga con menos contexto que el escritor y
  produce falsos `missing_evidence` sistemáticos.
- **Decisión:** `entity_dossier_intelligence` queda declarado con
  `requires_evidence_review=false`. Su ruta no ejecuta `evidence_reviewer`; conserva el control
  estructural de citas mediante `validate_evidence`, que rechaza cualquier `evidence_id` fuera de
  la allowlist pendiente y materializa esas fuentes solo al incorporar el informe a un expediente.
  `report_writer` y `competitive_procurement_intelligence` mantienen el revisor semántico porque en
  esos flujos el contexto del escritor y el del revisor sí comparten la misma base de evidencias.
- **Consecuencias:** la tabla de gobierno y el comportamiento real vuelven a decir lo mismo. El
  informe de entidad queda protegido contra citas inventadas, pero no contra una valoración
  semántica externa de groundedness. Reabrir esta decisión exige diseñar y medir un contexto
  compacto específico para el revisor de entidad; no basta con subir tokens, cambiar modelo ni
  revisar solo claims citados.

## D-041 — Muestra temporal determinista para actos BORME en informes de entidad

- **Estado:** accepted
- **Fecha:** 2026-07-21
- **Contexto:** Signal reindexó BORME hacia atrás y ahora entrega historial desde 2009 para algunas
  entidades. La ficha web pagina correctamente todo el histórico, pero el informe IA mantenía
  `REGISTRY_ITEM_LIMIT=25` y tomaba los primeros 25 actos por recencia. En entidades sesgadas como
  ITURRI SA, con 51 de 81 actos en 2026, eso dejaba fuera toda la historia recuperada aunque los
  agregados de Python sí cubrieran el corpus completo.
- **Decisión:** se mantiene `REGISTRY_ITEM_LIMIT=25` y `EVIDENCE_SOURCE_TOTAL_LIMIT=45`; no se
  resuelve subiendo presupuesto. Cuando hay más actos que cupo, Oracle selecciona una muestra
  temporal determinista (`temporal_coverage_v1`): mayoría de actos recientes, reserva de cola
  histórica y puntos intermedios por fecha de publicación. La muestra se devuelve en el orden
  original de Signal para no alterar la lectura ni la numeración de evidencias.
- **Consecuencias:** el informe puede citar y comentar profundidad histórica sin reabrir el fallo
  de JSON truncado por enumerar demasiadas fuentes. El recorte se declara en `source_limits` junto
  con el criterio usado. Cambiar cuotas o topes exige nueva medición contra informes reales largos.

## D-042 — Etiquetado progresivo y visibilidad compuesta en grafos de entidad

- **Estado:** accepted
- **Fecha:** 2026-07-21
- **Contexto:** en grafos densos, separar más los nodos no resuelve por sí solo la colisión porque
  el usuario debe alejarse para abarcar el conjunto. CASADO FERNANDEZ GONZALO tiene 141 nodos y
  186 aristas; mostrar simultáneamente todos los nombres y roles hace ilegible la estructura.
- **Decisión:** se eleva la separación fija a 156 px y la longitud ideal de arista a 250 px, sin
  alterar la semilla Vogel ni `randomize=false`. En el encuadre completo se etiquetan siempre el
  centro y hasta ocho nodos de mayor grado; el resto aparece al acercar, al pasar el cursor o al
  aislar una vecindad. Fecha, rol normalizado y foco se resuelven en una única pasada de
  visibilidad por clases Cytoscape; los filtros no relanzan layout. Seleccionar un nodo encuadra
  sus relaciones directas y volver a pulsarlo restaura el encuadre determinista.
- **Consecuencias:** el grafo completo sigue presente al abrir, pero deja de competir por 141
  etiquetas simultáneas. La exploración detallada conserva nombres y roles bajo demanda. Los
  roles se derivan de Signal y se agrupan sin distinguir capitalización; cualquier filtro futuro
  debe añadirse al mismo cálculo compuesto para no revivir elementos ocultos por otro criterio.

## D-043 — Orden local honesto y vocabulario observado en licitaciones

- **Estado:** accepted
- **Fecha:** 2026-07-21
- **Contexto:** Oracle pagina licitaciones, pero ni su API ni el contrato conocido de Signal
  aceptan ordenación. Ordenar una página como si fuese el corpus completo sería engañoso. A la vez,
  Signal solo ofrece sugerencias para comprador/adjudicatario, no para región, cuyos valores pueden
  ser provincias, ámbitos nacionales o grafías compuestas que no admiten normalización segura.
- **Decisión:** el frontend ofrece plazo ascendente/descendente y actualización descendente solo
  sobre los resultados cargados y muestra siempre, al activarlo, el tamaño de esa página y el total
  que queda fuera del orden. Comprador consulta `suggest(kind=buyer)` con debounce y sigue libre.
  Región construye durante la sesión un vocabulario exacto a partir de las páginas recibidas,
  incluidas las ejecutadas desde búsquedas guardadas; una referencia fijada desde esta pantalla ya
  ha sido observada en su página. No se persiste ni se comparte entre tenants desde el navegador.
- **Consecuencias:** la UX mejora sin atribuir a Signal una capacidad no demostrada ni crear un
  catálogo incompatible. La región arranca con lo observado en la carga inicial y se enriquece al
  navegar; una sugerencia global persistente requerirá un contrato explícito de Signal o un
  almacenamiento tenant-scoped en Oracle.

## D-044 — Cobertura de patentes separada de disponibilidad de la fuente

- **Estado:** accepted
- **Fecha:** 2026-07-21
- **Contexto:** Signal limita a 25 las publicaciones de patentes que devuelve, aunque el payload
  incluye el total real de EPO. Además, una búsqueda por denominación exacta puede fallar con
  `epo_search_404`. Presentar 25 filas sin el total o esconder por completo una sección fallida
  convierte respectivamente una muestra en aparente exhaustividad y un error en aparente ausencia.
- **Decisión:** la ficha muestra aviso solo cuando `total > items.length` y conserva los valores
  exactos recibidos. Una sección fallida hace visible la pestaña con un estado de fuente no
  disponible; `epo_search_404` se explica como posible discordancia de denominación, sin afirmar
  ausencia. El contexto del informe conserva `received_items`, `total`, `truncated_by_source` y el
  recorte independiente de Oracle; `source_limits` verbaliza ambos niveles y cualquier fallo.
- **Consecuencias:** el límite no configurable de Signal y el límite de evidencia de Oracle siguen
  intactos, pero dejan de confundirse con el universo de patentes de la entidad. Una consulta
  correcta con cero resultados continúa sin pestaña; los fallos sí quedan visibles y auditables en
  el corpus del informe. Los informes históricos mantienen su snapshot; la corrección se aplica a
  generaciones nuevas y no reescribe artefactos existentes.

## D-045 — Respuesta explícita por agente al rechazo del revisor

- **Estado:** accepted
- **Fecha:** 2026-07-22
- **Contexto:** `dossier_situation_summary` se regenera cada noche y un único claim discutible
  hacía perder el output completo. En respuestas reales, el revisor devolvió para «Concurso
  bomberos» una ruta inventada sobre su paquete compacto (`$.candidate_claims[5].claim`) y para
  «Mercado baterías LFP Europa» la ruta original (`$.relevant_actors[0]`). En el primer caso el
  texto del claim coincidía exactamente y de forma única con el claim enviado, cuya ruta original
  también era `$.relevant_actors[0]`.
- **Decisión:** `EVIDENCE_REVIEW_FAILURE_POLICY` declara por agente `not_required`,
  `reject_output` o `strip_claims`. Solo `dossier_situation_summary` usa `strip_claims`:
  retira el bloque objetado, revalida schema y allowlist, y añade avisos visibles con el claim y el
  motivo. Una ruta solo se acepta si coincide con el claim enviado; en otro caso se exige
  coincidencia textual exacta y única. Objeciones no anclables, ambiguas o de seguridad global
  mantienen fallo duro. `report_writer` y `competitive_procurement_intelligence` quedan
  explícitamente en `reject_output`.
- **Consecuencias:** una objeción quirúrgica ya no destruye el resumen nocturno, pero tampoco se
  publica como hecho. La política efectiva queda congelada en el manifest del snapshot de
  auditoría. No cambian el paquete compacto, los prompts, Signal, los presupuestos ni la validación
  de citas permitidas; un informe rechazado o con evidencia ajena al snapshot sigue sin artefacto.

## D-046 — Perfil competitivo estructurado sin invadir el gobierno de Signal

- **Estado:** accepted
- **Fecha:** 2026-07-22
- **Contexto:** el alta genérica de expedientes no podía conservar oferta propia, competidores,
  ámbito, criterios bid/no-bid ni KPIs, y los actores manuales recibían puntuaciones que podían
  confundirse con confianza probada. La petición de proveedor primario/secundario contradice
  D-015 si Oracle elige modelos que pertenecen al catálogo gobernado de Signal.
- **Decisión:** `StrategicDossier.profile_config` conserva el intake competitivo versionado como
  `competitive-intelligence.v1`; el expediente nace activo salvo elección explícita de borrador y
  genera objetivos, hipótesis, vigilancia, actores competidores y tareas desde los datos revisados.
  La confianza del actor manual queda sin valor y con base «sin evidencias», separada de relevancia
  e influencia. Todo tenant nuevo recibe una `AITenantPolicy` fail-closed en la misma transacción.
  La administración muestra esa política y el estado de configuración, pero Signal sigue siendo
  la única autoridad de proveedor, modelo y fallback. Una recomendación del Oráculo solo se
  materializa tras confirmación y guarda la versión de origen.
- **Consecuencias:** el flujo ya no depende de texto genérico ni inventa confianza. Activar Gemini
  u OpenRouter, clasificar errores recuperables o cambiar modelos exige hacerlo en Signal y cerrar
  antes presupuesto, clasificación y redacción; Oracle no simula una conectividad que no ha
  probado. La configuración JSON permite evolucionar el intake con versión explícita sin crear
  columnas sectoriales.
