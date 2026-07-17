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

- **Estado:** accepted
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
