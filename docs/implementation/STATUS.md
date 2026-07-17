# Estado de implementación de OPN Oracle

Actualizado: 2026-07-17
Rama observada: `master`  
Interfaz canónica: `CANONICAL_UI=vector`

## Correcciones P0/P1 · prompts 40, 41 y 42

- Prompt 40: el modo unitario de `scripts/api-test.sh --unit` ya no puede dar un verde con tests
  ocultos. `test_integration_alerts.py` deja de registrar como plugin global la fixture `autouse`
  de integración que hacía `pytest.skip`, y el wrapper falla si aparece cualquier skipped o si se
  ejecutan menos de 284 tests unitarios. `.codex-screenshots/` queda ignorado como artefacto local.
- Prompt 40: `oracle-control` añade `--yes`/`--non-interactive` para automatizaciones sin pausas que
  retengan `/run/lock/opn-oracle-control.lock`. Las frases reforzadas siguen exigiendo
  `ORACLE_CONTROL_CONFIRM_PHRASE` exacta y los gates de `update` se pasan por entorno.
- Prompt 41: el grafo de entidades conserva `fcose` determinista, pero recibe posiciones iniciales
  no degeneradas por nodo. No se han modificado zoom, cronograma ni ficha modal.
- Prompt 42: `DOCUMENT_ALLOW_OFFICIAL_UNSCANNED` permite, por defecto desactivado, aceptar PDFs
  oficiales PLACSP `ready + not_configured` solo con `DOCUMENT_SCANNER_MODE=noop`. La excepción se
  registra en `scan_result`, genera audit event, se propaga a la provenance de evidencia y aparece
  en Vector como «Fuente oficial · sin antivirus». `infected` y `error` siguen bloqueados siempre.

## Proceso P0 · CI en PR y release atado a SHA verde

- `ci.yml` vuelve a ejecutarse automáticamente en `pull_request` hacia `master` y conserva
  `workflow_dispatch`; no hay trigger en `push`.
- `release.yml` añade un job previo que consulta GitHub Actions y bloquea la publicación de
  imágenes si el workflow `CI` no tiene una ejecución `success` para el SHA exacto del release.
- La protección de rama queda documentada como cambio manual pendiente tras UAT en
  `docs/operations/BRANCH_PROTECTION.md`; no se ha configurado desde el repositorio.
- Se añade `scripts/api-test.sh` para ejecutar el gate backend desde shell no interactivo sin
  depender de que `.zshrc` añada `~/.local/bin` al `PATH`.
- Validación local del wrapper en este host: `zsh -c 'scripts/api-test.sh'` resuelve `uv`, ejecuta
  `uv sync --frozen`, `uv lock --check`, Ruff, formato y mypy; al no haber Docker ni URLs
  PostgreSQL/Redis de integración, falla cerrado antes de `pytest` para no saltar integraciones ni
  rebajar cobertura.

## Corrección pendiente de revisión · informe documental PLACSP

- `createDocumentReport` envía `Idempotency-Key` al backend y la UI conserva una clave estable por
  intento de generación del informe documental. Un reintento tras fallo crea una clave nueva, pero un
  doble disparo accidental del mismo intento puede hacer replay contra el contrato backend.
- El barrido de idempotencia confirma que las mutaciones del cliente que corresponden a endpoints
  con validación explícita de `Idempotency-Key` están cubiertas: backups/restore de plataforma,
  creación/acción de monitores, resumen IA, promoción de señal, cierre de reunión, generación/retry
  de informes, informe documental PLACSP y exportaciones.
- Los snapshots de adjudicaciones PLACSP agregadas conservan `award_amount` como suma de lotes y
  `award_date` como fecha única o rango. Los lotes con forma de CIF/NIF, como `A41050113`, dejan de
  mostrarse como número de lote y quedan documentados como revisión pendiente en Signal.
- Corrección Prompt 38: las adjudicaciones PLACSP fijadas desde ahora conservan `documents` e
  `is_ute` dentro de `snapshot.entries`; el snapshot agregado eleva `is_ute=true` cuando cualquier
  lote lo sea. Los documentos se normalizan a `uri`, `doc_type` y `file_name`, se deduplican por
  `uri` y quedan disponibles para el informe documental PLACSP. Los snapshots antiguos no se migran:
  para recuperar documentos/UTE en un expediente ya fijado hay que desfijar y volver a fijar el
  `folder_id`.
- La lista blanca de snapshots PLACSP deja de descartar campos nuevos en silencio: toda clave de
  Signal debe estar clasificada como preservada o consumida; si aparece una clave desconocida se
  registra warning operativo y el contrato unitario falla al ampliar fixtures sin clasificarla.
- Pulidos menores: evidencia de tarjeta fijada acortada, prioridad de siguientes acciones en
  español, error permanente de `BackgroundJob` con causa raíz sanitizada y dropdown de sugerencias de
  adjudicatario en lista vertical legible.

## Corrección pendiente de revisión · adjudicaciones PLACSP

- Signal deriva `is_ute` del adjudicatario al serializar, sin cambio de esquema ni backfill. Desde
  Prompt 38 Oracle conserva ese campo en adjudicaciones nuevas fijadas al expediente y Vector puede
  mostrar el distintivo «UTE · En consorcio» también en pins PLACSP. Los pins anteriores a la
  corrección no contienen ese dato y requieren refijado manual si se quiere ver el distintivo.

## Corrección pendiente de revisión · folder_id PLACSP con barras

- Signal acepta `folder_id` con `/` en los lookups `registry/awards/{folder_id:path}`,
  `registry/tenders/{folder_id:path}` y `registry/tenders/{folder_id:path}/summary`.
  Oracle mantiene `_quote_path_part(..., safe="")`; la convención queda documentada en ambos lados:
  uvicorn decodifica `%2F` antes del routing y Signal usa `:path` para tratar la barra como parte
  del identificador. Se añadieron fixtures reales `EMERGENCIACR2026/671`, `89/2026/27006` y
  `OBR/CNT/2026000031`, además de curl local contra uvicorn real.

## Corrección pendiente de revisión · artefactos persistentes

- El almacenamiento local de documentos e informes pasa de `/tmp/oracle-storage` a un volumen
  nombrado compartido en `/var/lib/oracle-storage`, montado por API, worker y Beat. La imagen crea
  el punto de montaje como `10001:10001` antes de ejecutar como usuario no privilegiado.
- Los artefactos que ya se perdieron en el `/tmp` efímero de producción no se pueden recuperar. Se
  recomienda una tarea posterior que marque en base de datos como no disponibles los registros cuyo
  objeto ya no exista, para comunicar un 404/410 claro en lugar de un 403 de descarga.

## Mejora pendiente de revisión · inteligencia de entidades

- Actores conserva el tipo de búsqueda de entidades en `sessionStorage`, propaga Persona/Empresa al
  navegar por fichas y sincroniza la consulta al cambiar entre entidades del grafo.
- El proxy `entity-intel` genera variantes server-side para personas en formato nombre-apellidos y
  apellidos-nombre antes de consultar Signal, manteniendo la caché por la consulta original del
  usuario y sin cambiar el contrato público.
- El grafo incorpora hover con atenuación de vecinos, ficha modal accesible para empresas/personas,
  relaciones directas navegables con confirmación y tests de UI con Cytoscape mockeado.
- F2 añade proxies Flask cacheados para `registry` y `dossier`, manteniendo `actor.read`, API key
  server-side, tenant externo solo para la ficha agregada y mensaje explícito cuando Signal tenga el
  servicio de entidades apagado en su administrador.
- La ruta `/app/actors/entity/[type]/[norm]` pasa a ficha 360º con cabecera, pestañas de Perfil,
  Órganos y cargos, Grafo y secciones condicionales. El copy distingue fechas de publicación BORME,
  límites de fuente, homónimos no desambiguados y ausencia de capital social o porcentajes.
- El grafo queda en modo forense por defecto (`active_only=false`), muestra vínculos cesados con
  trazo discontinuo, navega con `norm`, expone toggle «Solo vínculos activos» y resetea el estado de
  confirmación del modal al cambiar de entidad. La vista rápida consulta `registry` por `norm` y
  muestra perfil, últimos actos y contadores.
- Prompt 39: el grafo de entidades deja de arrancar con `fit` global y layout aleatorio. El
  encuadre inicial es determinista y prioriza legibilidad: centra la entidad consultada, incluye el
  primer nivel solo cuando no satura la vista y, en grafos densos como ITURRI SA, arranca en la
  entidad central a zoom legible para explorar navegando. Se añaden controles visibles y accesibles
  de acercar, alejar y reencuadrar.
- Prompt 39: se añade cronograma de doble manejador sobre fechas de aristas. El filtro se aplica
  mediante clases Cytoscape, sin reconstruir elementos ni relayout al mover el rango. Los vínculos
  sin fecha permanecen visibles y se explican en la UI; los nodos sin vínculos visibles se ocultan
  en lugar de atenuarse. El toggle «Solo vínculos activos» sigue combinándose como filtro de carga: si está
  activo, el rango temporal opera sobre los vínculos activos ya cargados.
- Prompt 39: la ficha modal de entidad sustituye el recorte silencioso de 5 actos por una
  cronología descendente de todos los actos cargados, mostrando persona, cargo, acción, fecha,
  provincia y cita BOE. Se solicita `limit=100` al registro para cubrir casos como ITURRI SA
  (65 actos) sin paginación local silenciosa, y la UI aclara que Signal no entrega el texto íntegro
  del BORME.
- Prompt 44: el suggest de entidad descarta respuestas obsoletas y limpia resultados al vaciar la
  consulta; el autocomplete de adjudicatarios de procurement queda reforzado con la misma barrera de
  secuencia.
- Prompt 44: el grafo deja de hacer `fit` inicial, mantiene separación fija de `fcose`, centra la
  entidad consultada a zoom legible y deja pan para explorar grafos densos como ITURRI SA. El detalle
  de nodo se abre por doble clic/doble tap; el clic simple solo selecciona.
- Prompt 44: la ficha 360º distingue visualmente la pestaña activa, convierte las tablas a TanStack
  Table con filtro de texto y ordenación —fecha descendente por defecto en órganos/cargos— y añade
  un control `actor.write` para materializar la entidad de Signal como Actor interno y vincularla a
  un expediente con provenance `signal_entity_intel`.

## Corrección pendiente de revisión · citas de informes

- `report_writer/v4` ordena al modelo citar fuentes mediante `[N]` y no exponer UUIDs en texto.
  Como defensa adicional, el ensamblador del informe sustituye UUIDs de evidencia en toda la prosa
  por su cita autoritativa, o por una referencia genérica cuando no forman parte del snapshot.

## Corrección pendiente de revisión · presentación de fuentes

- El visor de informes convierte el snapshot técnico de cada evidencia en una cita legible con
  medio, título, tipo, fecha y enlace seguro cuando estén disponibles. `locator`, `provenance` e
  identificadores externos dejan de mostrarse en la interfaz de negocio.

## Fase 4 · proxy Oracle de contratación pública PLACSP

- Oracle incorpora el proxy Flask `/api/v1/procurement` hacia Signal para adjudicaciones,
  licitaciones abiertas, resumen LLM cacheado por Signal, stats y búsquedas guardadas de
  licitaciones.
- Se reutiliza la configuración existente `SIGNAL_AI_*`, el allowlist HTTPS, timeouts, rechazo de
  redirects, límite de respuesta, mapeo de errores y resolución de tenant externo del patrón
  `entity-intel`. No hay variables nuevas ni llamadas directas desde navegador a Signal.
- Separación de autenticación validada en tests: los datos globales PLACSP usan solo `X-API-Key`;
  las búsquedas guardadas bajo `/api/v1/oracle/tender-searches*` añaden
  `X-OPN-External-Tenant-ID` derivado de la conexión `signal-avanza` activa.
- Permisos: adjudicaciones con `actor.read`, licitaciones y lecturas de búsquedas con
  `opportunity.read`, mutaciones de búsquedas con `opportunity.write`, stats con `signal.read`.
- Caché local: adjudicaciones 600 s, licitaciones abiertas 90 s, summaries sin caché local porque
  Signal gobierna su caché LLM.
- Fase 4b implementada: `dossier_procurement_items` permite fijar snapshots PLACSP a un expediente,
  crea evidencia interna asociada para citas en `tender.v1` y expone `POST/GET/DELETE` bajo
  `/api/v1/dossiers/{dossier_id}/procurement`.
- Corrección F4b: la resolución de snapshots ya usa los lookups directos de Signal por `folder_id`
  (`registry/tenders/{folder_id}` y `registry/awards/{folder_id}`), las adjudicaciones multilote se
  guardan en `snapshot.entries` y la evidencia queda tipada como `source_kind='procurement'` en vez
  de entrar en cuarentena `legacy_unresolved`.
- Checks focales F4b: `uv run pytest -q --no-cov tests/test_procurement.py tests/test_contract.py`
  **24/24**, `uv run mypy` y `uv run ruff check` focales correctos.
- Cierre PLACSP del 2026-07-15: Signal deja commiteados los lookups por `folder_id` requeridos por
  Oracle (`registry/tenders/{folder_id}` y `registry/awards/{folder_id}`), el runbook documenta el
  orden Signal → backfill PLACSP → Oracle, y `scripts/smoke-production.sh` cubre presencia protegida
  de `entity-intel`, `procurement/tenders`, `procurement/awards` y redirect anónimo de `/app/actors`
  a login. Smoke local combinado Next/API: correcto.

## Resolución operativa · scope `entity:read` en Signal

- Tras actualizar el consumer `opn-oracle` en Signal, Oracle producción pudo consultar el grafo real
  de `IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA`: respuesta 200 con 50 nodos, 101 enlaces y
  `truncated=false`. El bloqueo por `403 insufficient_scope` de Prompt 34/F1 deja de estar vigente.

## Prompt 33 · asentamiento del pipeline IA de informes, briefings y digest

- Diagnóstico read-only en producción realizado antes del cambio:
  - job `8f9b716e-7718-4b03-a1e1-ac6ae108d4f6` (`oracle.report.generate`) agotó tres intentos.
    El único `AIAuditLog` real (`564c8434-508f-4473-a2c8-2f0f02d0d8e8`) quedó `failed` con
    `error_code=UnboundLocalError` tras una ventana de 06:30:37 a 06:34:27 UTC. Los intentos
    posteriores no llegaron a Signal porque `execute_agent` bloqueaba cualquier audit previo
    fallido del mismo job/agente con «La ejecución IA de este job ya fue reclamada».
  - job `be3839d6-f5d8-4f79-8e2d-c15f10a2e2f4` (`oracle.meeting_briefing.refresh`) cayó en
    `permanent_failure`; su audit `f62f8a4e-f55e-428e-829a-8e23ac1dfc88` registró
    `error_code=AIUnavailable` casi inmediato el 2026-07-13 18:16:22 UTC, consistente con la
    etapa previa a la allowlist/tareas de Signal.
  - La política IA del tenant productivo estaba habilitada en `signal` con `qwen3.5:9b`, pero
    `max_output_tokens=2600`; por tanto `report_writer`, `meeting_briefing` y `weekly_change`
    no podían aprovechar los presupuestos gobernados ya configurados en Signal.
- Cambios implementados:
  - `SignalGovernedLLMProvider` ya no puede terminar en `UnboundLocalError` cuando el segundo
    intento de reparación JSON también falla; ahora publica solo si valida schema/evidencia,
    aplica saneamiento de citas no autorizadas cuando es seguro o propaga el error raíz.
  - `execute_agent` conserva la no duplicación de ejecuciones activas y el replay de artefactos
    `succeeded`, pero permite nuevos `AIAttempt` cuando el audit del mismo job/agente está
    terminalizado como fallo. Los reintentos Celery vuelven a ser reales sin cambiar el contrato
    único de `AIAuditLog`.
  - Los jobs IA reintentables conservan la última causa en `BackgroundJob.error_message` en vez de
    ocultarla tras un mensaje genérico; los jobs no IA mantienen microcopy sanitizada.
  - Prompts v2 compactos y versionados para `report_writer`, `meeting_briefing` y `weekly_change`;
    presupuestos: 6.500, 3.500 y 4.200 tokens. Se mantiene `dossier_situation_summary/v5`.
  - Límite de Signal AI por llamada sube a 300 s y Celery a 690/720 s para cubrir writer+reviewer
    local. Migración `20260714_0017` eleva el presupuesto de salida de políticas IA existentes
    habilitadas a 6.500.
- Comprobaciones locales ejecutadas antes de commit: `uv run ruff format --check .` correcto,
  `uv run ruff check .` correcto, `uv run mypy src/opn_oracle` correcto, tests backend focales
  41/41, Vitest 96/96, ESLint correcto, TypeScript correcto, `next build` correcto y Alembic head
  `20260714_0017`. Las integraciones focales de reintento quedaron preparadas y se omiten sin
  `TEST_*` locales.

## Operación · despliegue rápido UAT

- El runbook de producción pasa a tener un modo rápido por defecto para construcción/UAT: release
  nuevo en `/opt/opn-oracle/releases`, backup lógico local en `/var/backups/opn-oracle`, restore
  aislado validado, `oracle-control update` y health/smoke.
- El receipt de copia cifrada off-host deja de bloquear despliegues rápidos. Se conserva como modo
  estricto mediante `ORACLE_REQUIRE_OFFSITE_RECEIPT=1` y vuelve a ser obligatorio antes de operación
  estable con datos críticos.
- `scripts/deploy-production.sh`, `scripts/backup-production.sh` y `scripts/oracle-control.sh`
  quedan alineados con esa política: backup local + evidencia de restore son obligatorios; receipt
  remoto es opcional salvo modo estricto.

Revisión lingüística de la aplicación actualizada el 2026-07-12: se sustituyeron códigos de
fuente como `company_signal`, subtítulos técnicos de las áreas globales y mensajes como «Directorio
canónico» por textos de negocio en español. Las claves internas se conservan únicamente en tipos,
configuración y contratos no visibles para el usuario.

## Redespliegue P24 · objetivos e hipótesis

- El fix de ordenación de objetivos e hipótesis (`5ceae64d87bfdb8441510319c8addf3b168df9e4`)
  superó CI y quedó activo como release inmutable
  `20260713T045300Z-p24-5ceae64`. No introduce migración: la base permanece en
  `20260712_0015`.
- Gate de operación superado con backup previo, restauración aislada y recibo de copia cifrada
  externa. Se validaron manifest, Compose, Nginx, permisos de secretos y exposición de red.
- Smoke HTTPS, liveness/readiness, login web, Celery y un único Beat correctos. La comprobación
  autenticada del expediente CATL confirmó el panel «Objetivos e hipótesis» con un objetivo y dos
  hipótesis, sin «Paginación u ordenación no válida» ni errores de consola.
- Reejecución del prompt 26 completada el 2026-07-13: producción ya estaba en el release objetivo
  `20260713T045300Z-p24-5ceae64`, por lo que no se reactivó el mismo artefacto. Se creó el backup
  local `/var/backups/opn-oracle/20260713T084438Z-20260713T045300Z-p24-5ceae64/MANIFEST.txt`, su
  restore aislado quedó validado en
  `/var/backups/opn-oracle/restore-evidence/20260713T084438Z-20260713T045300Z-p24-5ceae64.RESTORE_EVIDENCE.txt`,
  y se repitieron smoke público, `oracle-control health`, `oracle-control validate`, Alembic head
  `20260712_0015` y verificación visual autenticada del panel CATL sin errores de consola.

## Mejora implementada · actores desde fuentes y altas manuales

- Actores separa «Actores vinculados» de «Candidatos detectados». La segunda vista deduplica las
  entidades estructuradas de las señales del expediente, propone tipo y etiquetas y conserva las
  fuentes concretas que originaron cada candidato.
- La importación requiere revisión humana y crea o reutiliza el actor canónico, lo vincula al
  expediente y registra tipo, etiquetas, roles, procedencia y auditoría. La misma pantalla permite
  crear actores manuales o vincular actores ya existentes.
- Oportunidades y Riesgos incorporan alta manual con descripción, valoración inicial y siguiente
  acción o mitigación. Tareas mantiene su alta manual y ahora muestra la validación dentro del
  diálogo en lugar de ocultarla tras la superposición.
- API nueva: lectura de `/dossiers/{id}/actor-candidates` e importación mediante
  `/dossiers/{id}/actor-candidates/{candidate_id}/import`. OpenAPI y cliente TypeScript se
  regeneraron sin drift. No hay migración ni variables nuevas: las etiquetas usan los metadatos
  JSON estructurados del actor y los candidatos se derivan de fuentes autorizadas.
- Comprobaciones locales: Ruff, mypy sobre 97 módulos, contrato backend 8/8, backend 106/106 con
  169 integraciones omitidas por entorno, frontend 85/85, ESLint, TypeScript y build correctos.
  La integración PostgreSQL/Redis de candidatos queda preparada y no se ejecutó por falta de las
  variables `TEST_*` locales.

## Mejora implementada · resumen nocturno persistente del expediente

- Celery Beat solicita cada noche, a las 03:15 en `Europe/Madrid`, una generación durable para
  todos los expedientes no archivados de cada organización activa con política IA habilitada.
- Cada expediente y fecha local comparten una clave idempotente: una repetición de Beat no duplica
  el trabajo, pero la noche siguiente crea una nueva versión aunque no cambie el contexto.
- Entrar en un expediente solo lee el último `AIArtifact`/`LivingSummary`. «Actualizar análisis»
  exige `Idempotency-Key`: repetir la misma petición deduplica y una nueva pulsación fuerza otra
  generación. La versión anterior se conserva durante el proceso o ante fallo.
- Signal gobierna `qwen3.5:9b` como primario y Ollama Titan `qwen3.6:27b` como fallback técnico;
  una indisponibilidad temporal ahora activa retry/backoff en lugar de fallo definitivo.
- No hay migración ni secretos nuevos. Configuración: `ORACLE_CELERY_TIMEZONE`,
  `ORACLE_NIGHTLY_SUMMARIES_ENABLED`, `ORACLE_NIGHTLY_SUMMARIES_HOUR` y
  `ORACLE_NIGHTLY_SUMMARIES_MINUTE`.
- Comprobaciones locales: Ruff, mypy, contrato/OpenAPI/cliente sin drift, 25 pruebas backend,
  3 pruebas frontend, ESLint, TypeScript y build correctos. La integración PostgreSQL/Redis focal
  queda preparada y se omitió al no existir las variables `TEST_*` locales.
- Producción: release `20260712T085932Z-settle-safe-summary`; cuatro expedientes no archivados con
  `LivingSummary` persistido y artefacto `valid` en `qwen3.5:9b`. Smoke interno/público, worker,
  Beat, manifest, Compose, Nginx, permisos de secretos y exposición de red validados. El smoke
  visual confirmó carga sin regeneración al entrar y cero errores de consola.

## Mejora implementada · eliminación múltiple de expedientes

- El listado muestra «Eliminar seleccionados» al marcar uno o varios expedientes de la
  página visible. El diálogo exige resolver una suma variable y avisa de que la
  eliminación es permanente y solo recuperable desde copia de seguridad.
- `POST /api/v1/dossiers/bulk-delete` acepta hasta 100 UUID, requiere
  `dossier.delete`, verifica que la persona sea propietaria o administradora de todos
  ellos y bloquea las filas en una única transacción. Si uno deja de estar disponible,
  no se elimina ninguno.
- La migración `20260712_0013` permite que las referencias de auditoría a un expediente
  eliminado queden en `NULL` sin perder el evento, el identificador del recurso ni sus
  metadatos de borrado. La migración `20260712_0014` concede al rol de ejecución
  únicamente el `DELETE` que necesita esta operación. OpenAPI y el cliente TypeScript
  se regeneraron.
- Comprobaciones locales: OpenAPI/client sin drift, Vitest focal 7/7, ESLint,
  TypeScript, build de Next, Ruff y mypy correctos; contrato Flask 7/7 sin umbral de
  cobertura. La integración PostgreSQL/Redis que prueba cascada y auditoría queda
  preparada pero no se ejecutó porque faltan las tres variables `TEST_*` en local.
- Producción: release inmutable `20260712T075929Z-grant-dossier-delete`, migración
  `20260712_0014`, health interno/público y Celery correctos. La prueba Playwright
  eliminó un expediente sintético mediante la suma `7 + 9`: el listado pasó de cinco a
  cuatro resultados, la fila desapareció y PostgreSQL confirmó tanto el borrado como el
  evento de auditoría conservado con `dossier_id = NULL`.

| Fase | Estado | Fecha | Responsable | Comprobaciones | Bloqueos | Siguiente paso |
|---|---|---|---|---|---|---|
| 00 · Orquestación | done | 2026-07-10 | Codex | Pack completo leído; decisiones, preguntas, checklist y baseline creados | Ninguno | Fase 01 |
| 01 · Auditoría | done | 2026-07-10 | Codex | Mapa, 7 ADR, contrato, threat model; `npm ci`, lint, tipos, tests, build y E2E | Ninguno para fase 02 local | Ejecutar `prompts/02_FLASK_FOUNDATION.md` |
| 02 · Fundación Flask | done | 2026-07-10 | Codex | `uv`, Ruff, mypy, 26 tests con PG/Redis, migración, OpenAPI y Gunicorn | Docker no disponible para validar Compose | Fase 03 |
| 03 · PostgreSQL y multi-tenancy | done | 2026-07-10 | Codex | 50 tests; 12 integraciones PG/Redis, RLS, roles, migraciones y drift | Docker no disponible para ejecutar Compose | Ejecutar `prompts/04_AUTH_SESSIONS_RBAC.md` |
| 04 · Auth, sesiones y RBAC | done | 2026-07-10 | Codex | 70 tests con PG/Redis; 87,66 %; Ruff, formato y mypy | SMTP síncrono se migra a Celery en fase 07 | Fase 05 |
| 05 · Frontend auth/admin | done | 2026-07-10 | Codex | Cliente OpenAPI; lint, tipos, 16 tests, build de 21 rutas, 13 E2E reales y QA visual | Deuda no bloqueante documentada | Fase 06 |
| 06 · Dominio Oracle | done | 2026-07-10 | Codex | 83 tests PG/Redis; 85,09 %; migraciones 0004/0005, RLS, OpenAPI/cliente y snapshot N:M | `Document/Chunk` se completa en fase 10 | Fase 07 |
| 07 · Celery/Redis | done | 2026-07-10 | Codex | 108 tests; 85,43 %; 49 integraciones PG/Redis/worker; migración 0006 y cliente | Smoke Compose no ejecutable sin Docker CLI | Fase 08 |
| 08 · Signal lado Oracle | done | 2026-07-11 | Codex | Contrato productor 2026-07-01 confirmado; API key/scopes/tenant, cursor e HMAC V2 alineados | Provisionamiento y E2E productivo en curso | Cerrar activación real |
| 09 · Runtime IA | done | 2026-07-11 | Codex | 154 tests; 85,41 %; PG/Redis/Celery real; migración 0008, prompts, schemas, evals, auditoría y fencing | Proveedor externo no definido; runtime mock/disabled fail-closed | Fase 10 |
| 10 · Documentos/evidencias | done | 2026-07-11 | Codex | 170 tests; 85,08 %; PG/Redis/Celery real; migración 0009, storage/parsers, FTS, evidence, retención, OpenAPI/cliente y Vector | S3/ClamAV productivos y sandbox de parser requieren configuración de infraestructura | Fase 11, no iniciada por alcance actual |
| 11 · Informes/notificaciones | done | 2026-07-11 | Codex | Migración 0010; informes, alertas, notificaciones/digests, exportaciones y Vector; 221 tests y 86,08 % | Ninguno bloqueante | Fase 11A |
| 11A · Arquitectura de información | done | 2026-07-11 | Codex | 5 especificaciones; registro tipado, shell/layouts, 44 rutas, creación real; GO adversarial | Ninguno bloqueante | Fase 12 |
| 12 · Frontend completo | done | 2026-07-11 | Codex | Vector conectado a Flask; 223 tests backend, 59 frontend, build de 45 rutas y 17 E2E | Ninguno bloqueante | Fase 13 |
| 13 · QA y seguridad | done | 2026-07-11 | Codex | 233 backend, 64 frontend, 24 E2E; scans/DAST/load/axe/readiness y GO adversarial | Ninguno de aplicación; release sigue bloqueado por infra/restore | Fase 14 read-only |
| 14 · Infra/TLS | done | 2026-07-11 | Codex | Graph validado; migración 0010; stack sano; HTTPS/smoke; superadmin y login real | Ninguno de infraestructura base | Fase 15 |
| 15 · CI/CD y backups | in_progress | 2026-07-11 | Codex | GitHub Actions en PR a master, release GHCR por SHA validado, SBOM, backup diario systemd, retención 30 días, catálogo/UI superadmin, manual y restore root blue/green | Falta configurar branch protection tras UAT, GitHub environments/secrets y automatizar la copia cifrada off-host diaria | Verificar CI remoto en PR y restore periódico desde descarga off-host |
| 16 · Aceptación/release | in_progress | 2026-07-11 | Codex + usuario | Producción accesible; primer tenant y owner invitado con Playwright; Graph entregó el correo; expediente `v0.1.0-rc.1` generado con `NO-GO` explícito | Aceptación del owner/UAT funcional, CI remoto y restore descargado pendientes | Cerrar gates y repetir aceptación |

Incidencia UAT corregida el 2026-07-11: el login del `platform_super_admin`
sin tenant activo dirige a `/platform/tenants`, y una entrada manual en `/app`
redirige al mismo portal en lugar de mostrar un falso acceso restringido.

Incidencia UAT corregida el 2026-07-11: la invitación de owner ya no envía el
campo redundante `role`, rechazado por el allowlist Flask de `invite-owner`.
El release productivo `20260711T165300Z-invite-owner-fix` quedó sano y el flujo
real se verificó con Playwright: usuario y membership `invited`, rol `owner`,
invitación vigente y job `notifications.send_email`/Graph `succeeded` al primer intento.

Revisión UX solicitada tras el primer acceso del owner: los identificadores técnicos de
procesos, colas, estados y roles se presentan ahora con lenguaje de negocio en español; la
tarjeta de trabajos recientes tiene altura acotada y desplazamiento interno; se corrigieron
los márgenes de estados y resúmenes del expediente, el vacío de informes y la posición de
cierre del modal. Las referencias visibles a Flask, tenant, score, portfolio, workspace y
briefing se sustituyeron en las rutas productivas por microcopy comprensible.
El QA real con el owner detectó además el rol crudo `owner` en el pie de navegación y
el estado transitorio `portfolio`; ambos se corrigieron a `Propietario` y `cartera`.

Segunda auditoría lingüística: se retiraron de las superficies productivas las referencias
residuales a backend, endpoint, score, RBAC, tenant, job, mock, probes, slug y checksum. Los
estados, planes, acciones de auditoría, monitores y revisiones documentales usan ahora etiquetas
de negocio; URL se conserva únicamente como aclaración universal junto a «dirección base».

## Mejora de creación de expedientes · perfiles iniciales por tipo

- El selector de tipo deja de ser solo clasificatorio en el alta: Proyecto, Mercado, Cuenta
  estratégica, Licitación o convocatoria, Alianza, Asunto regulatorio y Otro explican su alcance
  y proponen una base de trabajo editable.
- Con la opción confirmada, `POST /api/v1/dossiers` crea de forma atómica un objetivo, dos
  hipótesis y una watchlist con palabras clave y fuentes sugeridas, marcada para revisión y
  versionada como perfil `v1`. No hay migración ni variables nuevas.
- La opción `create_starter_profile` es opt-in para consumidores de API y está activada por defecto
  en el diálogo; desactivarla conserva un expediente vacío. No se crean monitores ni se contacta
  Signal Avanza automáticamente.
- Comprobaciones locales: OpenAPI y cliente regenerados sin drift; Ruff, formato y mypy focales;
  contrato Flask 7/7 sin cobertura; ESLint, TypeScript, frontend 74/74 y build correctos. La
  integración PostgreSQL/Redis focal no se ejecutó porque este entorno no tiene
  `TEST_DATABASE_URL`, `TEST_RUNTIME_DATABASE_URL` ni `TEST_REDIS_URL` configuradas.

## Task preparada · Oráculo contextual del expediente

- Prompt ejecutable creado en `docs/implementation/prompts/17_DOSSIER_ORACLE_ASSISTANT.md` y task
  Oracle en `docs/implementation/tasks/ORACLE_DOSSIER_ASSISTANT.md`.
- Frontera acordada: Oracle controla retrieval, permisos, evidencia, persistencia y UI; Signal
  gobierna la inferencia con la task `dossier_situation_summary`.
- Política de catálogo: Ollama `qwen3.5:9b` primario y OpenRouter
  `google/gemini-3.5-flash` secundario gated. El preset y la configuración productiva mantienen
  únicamente Ollama/Ollama Titan; no se activa gasto cloud sin presupuesto, clasificación,
  redacción, tratamiento de datos y autorización adicional.
- La task coordinada de Signal se registra en su propio repositorio. El estado de implementación
  Oracle queda detallado en el bloque siguiente.

## Task implementada · Oráculo contextual del expediente

- Oracle incorpora el agente `dossier_situation_summary/v1` con schema Pydantic estricto,
  prompt versionado, validación recursiva de `evidence_ids` y adapter `SignalGovernedLLMProvider`
  sobre `POST /api/v1/ai/run`. No hay llamadas directas a Ollama/OpenRouter desde Oracle.
- El snapshot del expediente amplía el context builder con objetivos, hipótesis, memoria viva,
  evidencias, señales vinculadas, oportunidades, riesgos, actores, reuniones, decisiones y tareas,
  con redacción y detección de prompt injection heredadas del runtime IA.
- `oracle.dossier_summary.refresh` sustituye el stub de `oracle.memory.refresh` para este flujo:
  encola en `ai`, deduplica por hash de snapshot, persiste `AIContextSnapshot`/`AIArtifact`/
  `AIAuditLog`, publica solo outputs validados como versión visible en `LivingSummary` y conserva
  la versión anterior si una ejecución falla.
- API añadida bajo `/api/v1/dossiers/{dossier_id}/oracle-summary`: lectura actual, refresh,
  versiones, detalle de versión con snapshot y feedback atribuido. OpenAPI y cliente TypeScript
  regenerados sin drift.
- Vector muestra el panel «Oráculo del expediente» en la portada del expediente, con titular,
  resumen, cobertura, confianza, bloques escaneables, historial, estado de refresh, aviso de
  proveedor secundario y feedback.
- Configuración nueva: `AI_MODE=signal`, `SIGNAL_AI_BASE_URL`, `SIGNAL_AI_ALLOWED_HOSTS`,
  `SIGNAL_AI_API_KEY(_FILE)` y `SIGNAL_AI_TIMEOUT_SECONDS`. Producción usa Signal para las tareas
  autorizadas con modelos Ollama propios; el fallback cloud permanece deshabilitado.
- Toolchain frontend fijada exactamente a `typescript@5.8.3` para evitar la rotura de `typescript@latest`
  con OpenAPI/ESLint.
- Comprobaciones locales: Ruff, mypy, OpenAPI/client check, runtime IA y proveedor 29/29,
  backend 104/104 con 65 integraciones omitidas por entorno, frontend focal 2/2, ESLint,
  typecheck y build Next correctos. No se ejecutó smoke visual autenticado porque este entorno no
  tiene stack Flask/PostgreSQL/Redis de UAT ni sesión real activa.
- La dependencia homóloga de Signal queda implementada y validada: catálogo aislado para
  `opn-oracle`, preset productivo Ollama/Titan sin cloud y suite completa de Signal con 466/466
  tests. Se corrigió además la prueba Oracle del adapter para reflejar el contrato HTTP real de
  Signal (`task_key` + `input`, identidad derivada de la API key y respuesta bajo `result`).
- Despliegue productivo completado el 2026-07-12. La verificación previa al E2E detectó que
  `worker-core` no consumía la cola declarada `ai`; el release
  `20260712T004620Z-ai-worker-queue` añadió las seis colas y un test de paridad Compose/Celery.
- El E2E real sobre el expediente de mercado permitió ajustar el runtime local sin activar cloud:
  prompt ejecutivo versionado hasta `v5`, `qwen3.5:9b` primario, Titan 27B secundario, reparación
  JSON compacta, timeout 210 s y presupuesto de 2.600 tokens. Los intentos inválidos quedaron en
  auditoría y nunca se publicaron.
- La rehidratación de UUID desde JSONB usa ahora semántica JSON estricta. El reintento operatorio
  auditado reutilizó el artefacto ya validado sin repetir inferencia: job
  `4df20429-3f37-4d45-bed5-aab5dd2d52ae` `succeeded`, artefacto versión 1 `valid`, resumen vivo
  publicado con confianza 72 y cobertura 4/4. El smoke autenticado mostró el panel completo, sus
  fuentes, historial y feedback sin errores de consola; las prioridades visibles se traducen a
  español.

## Fase implementada · Señales reales y triaje con Ollama gobernado

- Los expedientes de mercado y licitación pueden inicializar perfiles de partida trazables.
- La configuración de monitores Signal acepta únicamente tipos de fuente soportados y conserva
  consultas, entidades, palabras clave, idiomas, geografías, cadencia y retención.
- Los errores de entrega de la bandeja de salida dejan el monitor en estado visible de error.
- El triaje de señales se ejecuta mediante la task gobernada `signal_triage` de Signal, con
  evidencia y auditoría; en producción requiere habilitar la política del tenant y el consumer.

## Baseline conocido

- Frontend Next.js/React/TypeScript ejecutable en la raíz.
- Vector Command Center es la interfaz elegida.
- Horizon Decision Canvas permanece como prototipo comparativo temporal y no es canónico.
- Existe una aplicación Flask completa con PostgreSQL/Redis, migraciones, aislamiento multi-tenant y Celery; el despliegue remoto y CI/CD siguen pendientes.
- `main.py` es un ejemplo de PyCharm y no constituye backend.
- La capa actual `MockOracleRepository` y `localStorage` pertenecen al prototipo; no serán autoridad productiva.

## Cierre de la fase 01

- Instalación reproducible: `npm ci` correcto; npm informa de 2 vulnerabilidades moderadas transitivas.
- `npm run lint`: correcto.
- `npm run typecheck`: correcto.
- `npm run test`: 1 archivo y 3 tests correctos.
- `npm run build`: correcto; 8 páginas generadas y 2 rutas dinámicas detectadas.
- `npm run test:e2e`: 7 correctos y 1 omitido intencionadamente en móvil.
- Servidor remoto: no inspeccionado ni modificado; corresponde a la fase 14 y requiere auditoría read-only previa.

## Cierre de la fase 02

- Backend Flask modular en `apps/api`, Python 3.11 y dependencias fijadas en `uv.lock`.
- Application factory, configuración fail-fast, SQLAlchemy/Migrate, OpenAPI, Problem Details, request IDs, logs redactados, health/meta y Gunicorn.
- Dockerfile no-root y `compose.dev.yml` para API, PostgreSQL y Redis; Compose no se ejecutó porque Docker no está instalado en este entorno.
- `uv lock --check`, Ruff, formato y mypy: correctos.
- Suite completa con PostgreSQL 16 y Redis reales: 26 tests correctos y 91,93 % de cobertura.
- Migración upgrade/downgrade validada sobre base efímera y eliminada al terminar.
- OpenAPI exportado y configuración Gunicorn validada.

## Cierre de la fase 03

- Dieciséis modelos de plataforma para tenants, workspaces, identidad, memberships, RBAC, sesiones, tokens, auditoría e integraciones.
- Migración `20260710_0002` con CITEXT, constraints compuestas, índices, permisos, `ENABLE/FORCE RLS`, grants mínimos y funciones endurecidas.
- Separación real entre `oracle_migrator` (`BYPASSRLS`) y `oracle_app` (`NOBYPASSRLS`, sin DDL ni memberships heredadas).
- `TenantContext` transaccional con guard frente a cambios pre-tenant→tenant, A→B y savepoints dentro de la misma transacción.
- Resolución de tenant mediante membership y acceso superadmin explícito, con motivo y auditoría persistida.
- Tokens opacos almacenados solo como SHA-256; credenciales de integración vinculadas con FK compuesta tenant-safe.
- `uv lock --check`, Ruff, formato y mypy sobre 32 módulos: correctos.
- Suite completa con PostgreSQL 16 y Redis reales: 50/50 tests correctos; 12 de integración y 89,79 % de cobertura conjunta.
- Upgrade/downgrade, owner/ACL/search path de funciones, ausencia de drift y limpieza de base/roles efímeros verificadas.
- Docker Compose no se ejecutó porque Docker no está instalado; YAML, Dockerfile e init script fueron validados estáticamente.
- Servidor remoto no inspeccionado ni modificado.

## Cierre de la fase 04

- Autenticación con sesiones opacas en Redis, cookies endurecidas, expiración idle/absoluta, rotación fail-closed, revocación y recent-auth.
- Argon2id con rehash de parámetros heredados; CSRF por cabecera y origen; rate limiting y respuestas anti-enumeración.
- Flujos de login, logout, recuperación, cambio de contraseña, invitaciones, cambio de tenant y administración tenant/plataforma.
- RBAC, protección transaccional del último owner, límites RLS/IDOR y auditoría global mediante funciones `SECURITY DEFINER` verificadas.
- OpenAPI tipado para todas las rutas de la fase y CLI seguro para bootstrap del primer superadmin.
- `uv lock --check`, Ruff, formato y mypy: correctos.
- Suite completa con PostgreSQL 16 y Redis reales: 70/70 tests correctos y 87,66 % de cobertura; round-trip de migraciones validado.
- Deuda aceptada para fase 07: hacer asíncrono el envío de recuperación para eliminar diferencias temporales del adaptador SMTP.
- Servidor remoto no inspeccionado ni modificado.

## Cierre de la fase 05

- Cliente TypeScript generado desde OpenAPI con transporte cookie/CSRF, renovación de CSRF, `Problem Details`, request IDs, cancelación y reintentos seguros solo para lecturas.
- Estado de autenticación centralizado, selección explícita entre múltiples tenants y protección de rutas Vector, tenant-admin y plataforma; Horizon permanece como referencia no canónica sin duplicar auth.
- Flujos funcionales de login, recuperación, reset, invitación, cambio de tenant, logout, perfil, contraseña, sesiones, miembros, roles y portal de plataforma.
- Persistencia local de la demo aislada por tenant y redirecciones `next` limitadas a rutas internas permitidas.
- `npm ci`, drift del cliente OpenAPI, lint y typecheck: correctos; 16/16 tests unitarios/de componente y build de producción con 21 rutas correctos.
- E2E contra Flask, PostgreSQL 16 y Redis reales: 13 ejecuciones correctas y 3 recorridos largos omitidos solo en móvil; los recursos efímeros se limpian al finalizar.
- La revalidación adversarial cubre CSRF fresco tras sesión expirada, recuperación ante fallo de cambio de tenant, logout no optimista, tenant-admin sin permiso y superadmin sin acceso al producto.
- Revisión visual en 1280 px y 390 × 844: navegación, administración, control de acceso y responsive sin errores de consola ni overflow horizontal.
- Deuda no bloqueante: preferencias siguen en el repositorio mock, administración aún no expone paginación/actividad completa y la UI de roles simplifica a un rol aunque la API admite varios.
- `npm audit` mantiene 2 vulnerabilidades moderadas transitivas; no se realizó una actualización masiva de dependencias fuera de alcance.

## Cierre de la fase 06

- Dominio persistente y transversal con `StrategicDossier` central, señales tenant-globales contextualizadas mediante `DossierSignal`, oportunidades, riesgos, actores, relaciones, reuniones, decisiones, tareas, insights, informes, feedback y resúmenes vivos.
- Migraciones `20260710_0004` y `20260710_0005`: FKs compuestas tenant-safe, `ENABLE/FORCE RLS`, permisos, índices, constraints, historial de estado, optimistic concurrency y rollback completo.
- Autorización por expediente para owner, tenant-admin y colaboradores activos; administración de colaboradores restringida y revocable; 404 tenant/resource-safe.
- Scoring `oracle-scoring-v1` exacto y configurable para señales, oportunidades, riesgos y actores, con explicación, historial y overrides humanos atribuidos.
- Promoción de señal transaccional e idempotente, con prueba concurrente; archivo de expediente atómico y bloqueo de mutaciones hijas.
- `EvidenceDossier` conserva el contexto N:M y migra snapshots de fase 0004 con señales compartidas sin pérdida ni fuga entre expedientes.
- API con CRUD, estados, auditoría, relaciones M:N, paginación, búsqueda, filtros tipados, selección por IDs, ETag/If-Match y seed sintético convergente de ocho expedientes.
- OpenAPI cerrado y cliente TypeScript regenerado: 144 operaciones revisadas, 32 `DELETE` 204 y 18 `PATCH` versionados, sin respuestas 2xx vacías ni drift.
- Validación final con PostgreSQL 16 y Redis reales: 83/83 tests y 85,09 % de cobertura; Ruff, formato, mypy (49 fuentes), Alembic base→0005, `flask db check`, cliente OpenAPI y typecheck TypeScript correctos.
- Recursos efímeros eliminados: cero bases/roles temporales y Redis DB 14 vacío.
- Hook explícito diferido: documentos/chunks y `Evidence.document_id` se completan en fase 10; el flujo document-only permanece bloqueado hasta entonces.

## Cierre de la fase 07

- Integración Celery mediante application factory única, serialización JSON/UTC y colas separables `default`, `signals`, `ai`, `documents`, `notifications` y `maintenance`.
- `BackgroundJob` durable con payload allowlisted/hasheado, estados, progreso, intentos, heartbeat, lease de ejecución, fencing por `task_id`, cancelación cooperativa, retries con jitter, errores saneados y publicación reconciliable.
- `JobSchedule` bajo RLS con dispatcher `FOR UPDATE SKIP LOCKED`, creación de job y avance atómicos, schedules interval/daily/weekly y cálculo wall-clock con timezone/DST.
- Workers y beat configurados en Compose con Redis separado para sesiones, rate limit, broker DB 3 y resultados DB 4; YAML validado, pero Docker CLI no está instalado para ejecutar `docker compose config` o smoke de contenedores.
- API de jobs tenant/resource-safe con listado, polling, ETag/If-Match, cancelación, retry manual y auditoría.
- Recuperación de contraseña persist-only desde HTTP y envío asíncrono sin tokens en argumentos; Capture usa idempotencia y SMTP aplica semántica durable at-most-once ante resultado incierto.
- Mantenimiento recorre también tenants suspendidos/archivados; cleanup, recovery de workers stale y reconciliación de publicaciones probados bajo RLS.
- Mock funcional de sincronización Signal conectado al task stub, listo para ser sustituido por el adaptador completo de fase 08.
- Migración `20260710_0006`, snapshot real 0005→0006 (`completed`→`succeeded`) y `flask db check` sin drift.
- Validación final: 108/108 tests, 85,43 % de cobertura y 49 integraciones con PostgreSQL, Redis y worker Celery real; Ruff, formato, mypy, lockfile, OpenAPI/cliente, ESLint, typecheck y tests frontend correctos.
- Recursos efímeros eliminados: base de prueba borrada y Redis DB 13 vacío.

## Cierre de la fase 08

- Contrato consumidor provisional de Signal Avanza documentado con OpenAPI externo esperado, webhooks, mapping y campos abiertos; no se presenta como contrato confirmado del productor.
- `SignalAvanzaAdapter` desacopla dominio y transporte; el mock es determinista y el HTTP valida schemas, timeouts, allowlist, redirects, segmentos de ruta, `Retry-After`, correlación e idempotencia.
- El transporte HTTP real permanece deliberadamente **fail-closed**: aunque la configuración y el contrato provisional existen, no se habilita hasta disponer de pinning de IP con preservación segura de Host/SNI, protección frente a DNS rebinding, confirmación bilateral y E2E contractual.
- Credenciales cifradas con AES-256-GCM, keyring versionado, AAD tenant/conexión/tipo/versión, fingerprints HMAC tenant-scoped, rotación y solape acotado de secretos webhook; secretos nunca se devuelven ni se registran.
- Migración `20260710_0007` con conexiones versionadas, namespace de señales por conexión, snapshots de configuración, inbox, outbox, runs e ingesta; FKs compuestas tenant-safe, constraints, índices, `ENABLE/FORCE RLS` y funciones `SECURITY DEFINER` mínimas para resolución y reconciliación global.
- Outbox transaccional con hash ligado a conexión, monitor, evento y payload; reserva idempotente mediante advisory transaction lock e `intention_hash` estable. Dos requests concurrentes de creación producen un único watchlist, monitor y evento; replay idéntico devuelve el ganador y una intención distinta devuelve 409.
- Polling incremental paginado y webhook firmado convergen en la misma ingesta; deduplicación por conexión/ID/hash, detección de cambios, cursor solo tras éxito, locks por monitor, procedencia, enlace N:M y triage durable.
- Webhook sin sesión ni CSRF, con resolución tenant fuera del body, HMAC/timestamp, current+previous secret, hard cap de stream, replay conflictivo, raw cifrado, persist-first e inbox asíncrono reconciliable.
- Workers y beat recuperan outbox/inbox tras fallo de broker o claim stale; delivery separa estado deseado/observado, actualiza salud y usa idempotencia del proveedor para limitar duplicados tras crash.
- API tenant/resource-safe para conexiones, test, rotación, disable, reconcile, monitores por expediente, PATCH versionado, pause/resume/sync y health; autorización final por expediente, no solo por permiso global.
- Upgrade desde base hasta 0007, `flask db check`, downgrade/reupgrade y downgrade adversarial con dos conexiones que comparten ID externo/hash validados sin pérdida de unicidad ni fallo de migración.
- Validación final backend con PostgreSQL, Redis y worker Celery reales: 126/126 tests correctos y 85,06 % de cobertura; Ruff, formato y mypy correctos.
- OpenAPI Flask reexportado y cliente TypeScript regenerado sin drift; ESLint y typecheck correctos, 19/19 tests frontend y build Next.js correcto con 22 rutas.
- Limitaciones reales: contrato productor Signal aún no confirmado, HTTP real bloqueado como se indica arriba, no se ejecutó smoke Docker/Compose por ausencia de Docker CLI y el endpoint webhook usa una subscription key opaca en ruta que exige redacción en access logs de producción.
- Servidor remoto no inspeccionado ni modificado; la auditoría read-only y cualquier despliegue siguen reservados para las fases de infraestructura.

## Cierre de la fase 09

- Runtime IA desacoplado con `LLMProvider`, modos `disabled` y mock determinista; no existe proveedor externo ni fallback silencioso y el mock queda prohibido en producción.
- Registry inmutable de once prompts runtime versionados (`v1`) cargados como recursos, con metadata, contrato, modelo, límites, changelog y hash; incluye intake, triage, entity resolution, oportunidad, riesgo, actores, briefing, informes, memoria, reviewer y cambios semanales.
- Schemas Pydantic estrictos y conceptuales: hechos, inferencias y recomendaciones separados; scores 0–100; estructuras anidadas para entidades, deduplicación, escenarios, mitigaciones, actores, preguntas, objeciones, párrafos, fuentes, memoria y cambios. Todos los `evidence_ids`, también anidados, se validan contra el snapshot tenant/dossier.
- Context builder acotado por tokens con objetivos, hipótesis, living summary y evidencia N:M; dedupe/manifest/hashes, clasificación, redacción recursiva e indicadores de prompt injection. El contenido ingerido se trata explícitamente como dato no confiable.
- Migración `20260710_0008` con attempts, snapshots/context evidence, artifacts, human reviews, tenant policies y usage ledger; ampliación de `AIAuditLog`, FKs compuestas tenant-safe, constraints, índices, permisos y `ENABLE/FORCE RLS`.
- Ejecución exclusiva por Celery en cola `ai`, cuotas tenant-globales serializadas en PostgreSQL, allowlist de modelos, límites diarios/tokens/concurrencia/presupuesto y kill switch global/tenant. Los resultados son candidatos y nunca ejecutan acciones ni sobrescriben decisiones humanas.
- Fencing adversarial por execution token, estado, lease y ledger reservado en generación, reviewer y settlement. Recovery rota tokens y libera reservas; una prueba con proveedor bloqueado confirmó que un worker stale no puede resucitar audit, crear artefacto ni liquidar coste. El reviewer renueva lease alineada con el hard time limit Celery.
- Fallos de provider/reviewer y veredicto inválido terminalizan audit/attempt/ledger sin persistir output válido; feedback y revisión humana crean historial/override sin modificar el output histórico. APIs de enqueue, retriage, feedback, review y lectura audit aplican permisos, expediente y tenant.
- Evals offline con diecisiete fixtures sintéticos y métricas explícitas de schema pass, cobertura de evidencia, unsupported claims, clasificación, aceptación, latencia y coste; no se realizan llamadas pagadas.
- Validación final con PostgreSQL 16, Redis y worker Celery reales: 154/154 tests y 85,41 % de cobertura. Re-review adversarial final aprobado, incluido el caso recovery durante una llamada provider en vuelo.
- Ruff, formato, mypy, lockfile, Alembic base→0008, ausencia de drift, downgrade 0008→0007 y reupgrade correctos. OpenAPI reexportado, cliente TypeScript regenerado sin drift; ESLint, typecheck, 19 tests frontend y build Next.js de 22 rutas correctos.
- Limitaciones reales: solo existen adapters disabled/mock; habilitar un proveedor real exige contrato, credenciales, revisión de privacidad/clasificación, estimador de coste y allowlists. Con proveedores reales lentos deberá limitarse la renovación del reviewer al deadline absoluto de Celery.
- Servidor remoto no inspeccionado ni modificado.

## Cierre de la fase 10

- Migración `20260711_0009` con `Document`, versiones inmutables, chunks, attempts y políticas de retención; FKs compuestas tenant-safe, `ENABLE/FORCE RLS`, GIN FTS y enlace exacto de `Evidence` a documento/versión/chunk.
- Upgrade desde base, ausencia de drift, downgrade a 0008, reupgrade y snapshots legacy adversariales validados sin perder IDs ni provenance; evidencias históricas bloquean el borrado físico de su fuente.
- Storage desacoplado: filesystem privado y atómico para desarrollo/test; S3-compatible permanece fail-closed salvo endpoint HTTPS con IP global fijada y allowlist. Checksums SHA-256, límites streaming y cuota tenant serializada.
- Scan con noop explícito no descargable y adapter ClamAV `INSTREAM`; parsers acotados para PDF, DOCX, TXT/Markdown, CSV, VTT/SRT y transcripción JSON. No hay OCR ni pgvector sin política/proveedor aprobado.
- Pipeline Celery `documents` con `BackgroundJob` transaccional, publication reconciliable, `DocumentProcessingAttempt`, lease CAS en transacción fresca, fencing por token/versión y recovery que abandona el token expirado y stagea retry seguro.
- Chunking estructural conserva página, párrafo, speaker/timestamps, offsets exactos, checksum y provenance; reprocesar crea una versión nueva y no rompe citas históricas.
- APIs tenant/resource-safe para upload, listado, detalle, download `ready+clean`, soft delete, reprocess, búsqueda global/por expediente y creación/lectura de evidence. Tests cross-tenant explícitos cubren get/download/search/evidence/reprocess/delete.
- Retención con legal hold, purge idempotente de contenido y reconciliación de objetos huérfanos; hashes, IDs, locators y metadata de citas se conservan según política.
- RBAC canónico actualizado para que tenants/roles creados después de 0009 reciban permisos IA/documentales; owner/admin completos, editor/analyst operativos, viewer/auditor con lectura documental.
- Vector enlaza desde portfolio a expedientes PostgreSQL con UUID real y ofrece upload, tabla, búsqueda y drawer de evidence. Las fichas fixture por slug muestran un estado sintético honesto y realizan cero llamadas documentales.
- Revisión adversarial final: **APPROVED**. Validación backend con PostgreSQL, Redis y worker Celery reales: 170/170 tests y 85,08 % de cobertura; Ruff, mypy y lockfile correctos.
- OpenAPI reexportado y cliente TypeScript regenerado sin drift; ESLint y typecheck correctos, 21/21 tests frontend y build Next.js de 22 rutas correcto.
- Smoke visual desktop autenticado: portfolio → expediente PostgreSQL UUID → panel Documentos, sin alertas; la ficha slug sintética también fue revisada. La revisión visual móvil no se completó por la limitación de viewport de la herramienta.
- Limitaciones reales: credenciales/servicios S3 y ClamAV no configurados; sandbox de parser mediante contenedor sin red y límites CPU/memoria queda para infraestructura. No se desplegó ni inspeccionó el servidor remoto.
- La fase 11 continúa `in_progress`: el alcance se amplió posteriormente para continuar con el resto del pack.

## Cierre de la fase 11

- Ocho templates versionados, snapshot de contexto/evidencia verificable, Evidence Reviewer,
  revisiones humanas, publicación serializada, artefactos HTML/JSON y PDF fail-closed.
- Notificaciones in-app, preferencias por tipo/canal, seguridad no desactivable, email asíncrono,
  quiet hours y digest diario/semanal con lotes congelados de hasta 50 elementos, hash SHA-256,
  expiración y retries que no absorben eventos posteriores.
- Evaluator durable para siete alertas: señal/riesgo altos, vencimiento de oportunidad, fallo de
  integración/job, reunión próxima e informe listo; políticas tenant/dossier heredables, bundling,
  cooldown, quiet hours, advisory lock, ledger idempotente y destinatarios filtrados por RBAC.
- Exportaciones CSV asíncronas con allowlist, alcance por expediente/usuario, neutralización de
  fórmulas, watermark de auditoría, revalidación de permisos, links ligados a fingerprint,
  tenant/usuario/sesión y fencing de storage por lease.
- Vector ofrece biblioteca/visor de informes, centro de notificaciones, preferencias y centro de
  exportaciones en rutas `/app`, con aliases provisionales `/concept-a`.
- Snapshots de informe verifican contenido, opciones y hash de template; el tampering falla de forma
  controlada, terminaliza informes mutables y no deja artefactos. Publicación, generación y
  exportaciones mantienen fencing y limpieza de objetos parciales.
- Migración base→0010, ausencia de drift, downgrade a 0009 y reupgrade correctos; RLS `ENABLE/FORCE`,
  grants y constraints tenant-safe verificados. Re-review adversarial: **GO / APPROVED**.
- Validación final: Ruff, formato y mypy correctos; PostgreSQL/Redis reales, 221/221 tests y 86,08 %
  de cobertura; OpenAPI/cliente sin drift; frontend lint, tipos, 28/28 tests y build de 32 páginas;
  E2E real contra Flask/PostgreSQL/Redis: 15 correctos y 3 skips móviles intencionados.
- Revisión visual en 1440 × 900 y 390 × 844 de informes, notificaciones y exportaciones: sin overflow
  horizontal ni errores de consola. Se añadió la declaración de scroll de Next.js al layout raíz.
- Deuda no bloqueante: falta una prueba con dos evaluadores físicamente concurrentes; el OpenAPI
  podría tipar los mapas de alertas con mayor precisión; permanecen tres recorridos largos omitidos
  solo en móvil.

## Cierre de la fase 11A

- `CANONICAL_UI=vector` aplicado en `/app`; Horizon permanece aislado como referencia temporal y
  no recibe funcionalidad productiva.
- Cinco entregables cerrados en `docs/product`: arquitectura de información, especificación de
  navegación, responsive, matriz ruta/permiso y matriz pantalla/componente/API/E2E.
- Registro central y estrictamente tipado para los diez destinos globales, cuenta, administración,
  plataforma y once secciones de expediente; menú derivado de permisos, breadcrumbs semánticos y
  ninguna navegación productiva mediante anchors o rutas `/concept-*`.
- Shell Vector con skip link, command palette, tenant/rol visibles, menú personal separado, centro
  de notificaciones, sidebar persistente y drawer móvil con trap/restauración de foco y bloqueo de
  scroll. Configuración de expediente permite lectura y reserva mutaciones al backend/RBAC.
- Layouts diferenciados para producto, expediente, cuenta, administración y plataforma; rutas aún
  sin frontend conectado muestran placeholders honestos y la API disponible/parcial/pendiente.
- Menú `Crear` y command palette crean un expediente real contra Flask. Si no se indica workspace,
  el backend selecciona el workspace activo predeterminado del tenant; OpenAPI y cliente generado
  reflejan `workspace_id` opcional y existe regresión PostgreSQL.
- Revisión adversarial: **GO / APPROVED**. Backend final 222/222 y 86,09 %; Ruff, formato y mypy
  correctos. Frontend OpenAPI sin drift, lint/typecheck, 32/32 tests y build de 44 rutas correctos.
  E2E real: 15 correctos y 3 skips móviles intencionados, incluida creación real de expediente.
- Revisión visual en 1440 × 900 y 390 × 844: shell, menú completo, placeholders, drawer móvil,
  foco de apertura/cierre, ausencia de overflow horizontal y consola final limpia.
- Deuda para fase 12: sustituir fixtures productivos, conectar read models y tablas globales,
  resolver títulos de expediente en breadcrumbs y ampliar `Crear` solo con flujos completables.

## Cierre de la fase 12

- `/app` es ya una aplicación Vector conectada a Flask: inicio, cambios, búsqueda global,
  inventarios de expedientes/señales/oportunidades/riesgos/actores/reuniones/tareas, detalle de
  expediente, documentos, informes, ajustes, administración tenant y portal de plataforma.
- Los read models globales están acotados por tenant, expediente y permisos. La UI productiva no
  importa fixtures ni `MockOracleRepository`; los mocks permanecen aislados en los dos prototipos.
- El expediente permite revisar/descartar/promover señales, transicionar oportunidades, riesgos y
  tareas, vincular actores, crear reuniones y briefings, gestionar documentos/evidencias y editar o
  archivar la configuración con optimistic concurrency. Los monitores se degradan sin bloquear la
  configuración cuando el usuario carece de permiso Signal.
- Los prototipos A/B siguen disponibles en desarrollo, pero producción redirige `/` y `/concept-*`
  a `/app`; un build con `ORACLE_ENABLE_UI_PROTOTYPES=1` falla deliberadamente para impedir una
  publicación accidental.
- `scripts/create-chatgpt-exam-zip.sh` genera un paquete full-stack por whitelist y excluye secretos,
  entornos, caches, dependencias, resultados E2E y metadatos del IDE/Git.
- Validación backend final: Ruff y mypy correctos; PostgreSQL/Redis reales, 223/223 tests y 85,86 %
  de cobertura. OpenAPI reexportado y cliente TypeScript sin drift.
- Validación frontend final: ESLint, TypeScript y build correctos; 19 archivos y 59/59 tests;
  45 rutas generadas. Playwright contra Flask/PostgreSQL/Redis: 17 correctos y 5 skips móviles
  intencionados, incluida la subida y procesamiento documental real.
- Revisión visual realizada en 1440 × 900, 1280 × 800, 1024 × 768 y 390 × 844; ajustes e inventario
  móvil sin overflow horizontal. Reauditoría independiente: **GO**, sin P0/P1.
- Deuda no bloqueante para fase 13: traducir algunos estados raw; automatizar axe, teclado y consola;
  completar el grafo visual de actores; resolver breadcrumbs por título; y publicar contratos Flask
  antes de ampliar organización/workspaces o agregados operativos cross-tenant. El backend tampoco
  permite reabrir tareas terminales y cambios declara honestamente que no soporta `mark-reviewed`.

## Cierre de la fase 13

- Estrategia, matriz de cobertura y presupuesto de rendimiento trazables en `docs/quality`; threat
  model actualizado e informe `docs/security/READINESS_REPORT.md` con severidad, owner, estado y
  gates. Revisión adversarial final: **GO para fase 14 read-only; NO-GO para producción**.
- La revisión automática de superficies detectó dos rutas `PATCH signal-monitors` equivalentes. Se
  retiró el CRUD genérico: el update pasa siempre por Signal, exige `If-Match`, bloquea la fila,
  versiona configuración y conserva outbox/idempotencia. También se separaron search/evidence
  documental de las rutas core y se impide cualquier ruta Flask equivalente.
- Suite multi-tenant dinámica: toda tabla tenant-scoped mantiene RLS `ENABLE/FORCE`, el rol runtime
  no ve filas sin contexto y cada mutación está inventariada bajo CSRF. Una sesión abierta pierde un
  permiso RBAC revocado en la petición siguiente y tenant-admin devuelve 403.
- Métricas protegidas `/internal/metrics` con rutas templadas, latencia, auth/rate limit y pool;
  token obligatorio y 404 indistinguible. El histograma usa nueve buckets+suma+contador acotados,
  con regresión de 10.000 observaciones; no retiene una muestra por request.
- Headers Flask/Next, cache no-store, anti-clickjacking, nosniff, referrer/permissions y CSP web
  report-only sin `unsafe-eval`. HSTS permanece desactivado hasta confirmar TLS; Next elimina la
  cabecera de versión. Axe WCAG 2.2 A/AA, teclado, foco, consola y recargas de sesión automatizados.
- Scans: npm audit 0; pip-audit 0 tras actualizar `cryptography` 46.0.7→48.0.1 por
  `GHSA-537c-gmf6-5ccf`; Semgrep 0; secret patterns 0. Trivy no disponible y queda gate de imagen.
- DAST local contra Gunicorn: 13/13. Los probes y el harness de carga rechazan userinfo/targets no
  HTTP(S), no siguen redirects y exigen `--allow-staging` fuera de loopback.
- Baseline read-only: 4 clientes/10 s, 326 requests y 0 errores; p95 login 129,60 ms, expedientes
  23,11 ms, señales 23,42 ms, búsqueda 28,16 ms y jobs 23,33 ms. Tres planes SQL bajo runtime/RLS
  usaron índices; el dataset de ocho expedientes no permite inferir capacidad productiva.
- Validación backend final con PostgreSQL/Redis reales: **233/233**, cobertura **85,95 %**, Ruff y
  mypy correctos; OpenAPI 163 paths/240 operaciones y cliente sin drift. Frontend: 21 suites/64
  tests, lint, tipos y build; Playwright full-stack: 24 correctos y 6 skips intencionados.
- Runbooks cubren API, DB/pool, Redis, Celery, Signal, certificado, disco, backup, sesión comprometida
  y sospecha cross-tenant. Producción permanece bloqueada por CSP nonce/enforcement, métricas
  multiproceso, carga/ZAP staging, Trivy/SBOM, TLS exterior, S3/ClamAV/sandbox y backup/restore real.
- Observación no confirmada: un sweep antiguo vio `/auth/me` 200→401 durante recargas solapadas; no
  se reprodujo en test focal ni E2E completo y el trace no se conservó. Se mantiene como P2 visible.

## Avance de la fase 14 · Etapa A

- Auditoría remota realizada exclusivamente por clave SSH en `BatchMode`, sin usar la contraseña
  compartida, sin leer secretos y sin modificar paquetes, archivos, servicios, firewall o datos.
- Host `oracle`, Ubuntu 26.04 LTS/kernel 7.0, 2 vCPU, 3,7 GiB RAM, 75 GiB (3 % usado), sin swap,
  UTC/NTP activo, carga baja y ninguna unidad fallida. Fingerprints SSH internos/externos coinciden.
- DNS A de `oracle.opnconsultoria.com` coincide con IPv4; no hay AAAA/CAA. El host tiene IPv6 global.
  Externamente solo 22 está abierto; 80/443 y 3000/8000/5432/6379 están cerrados o filtrados.
- El servidor está limpio: sin Docker/Compose, Nginx/Apache/Caddy, Certbot, PostgreSQL, Redis,
  repositorio, despliegue o backup Oracle. `/opt` y `/srv` no contienen conflicto.
- UFW está inactivo y no se observaron reglas nftables. `sshd` permite root y password; como una
  contraseña root fue expuesta en conversación, se clasifica como blocker crítico hasta rotación.
- Recursos ajustados: el plan propone worker consolidado de concurrencia 1, features externas
  deshabilitadas, límites y evaluar 8 GiB antes de parsing/IA/carga real. El guest reporta TSA sin
  microcode y requiere confirmación del proveedor.
- Inventario: `docs/operations/SERVER_AUDIT_2026-07-11.md`. Diff, orden, backup, verificación y
  rollback propuestos: `docs/operations/PRODUCTION_CHANGE_PLAN.md`.
- Gate activo: **ningún cambio de Etapa B** hasta que el usuario revise el informe y autorice por
  escrito. Rotación/hardening SSH exige aprobación separada y sesión/console de respaldo.

## Avance local de la fase 14 · artefactos sin aplicación remota

- Frontend productivo standalone con `Dockerfile.web` multi-stage Node 24, UID/GID 10001,
  filesystem read-only compatible y healthcheck. El build standalone arrancó localmente:
  `/login` 200 y `/` 307→`/app`.
- `compose.prod.yml` define PostgreSQL 17, Redis 7.4 con ACL/AOF/noeviction, migración única bajo
  perfil `release`, API/web solo en loopback, DB/Redis sin ports, worker consolidado concurrencia 1,
  beat único, egress limitado, resource limits, restart/log rotation y redes separadas.
- Configuración Flask con allowlist `*_FILE`, rutas absolutas, conflicto inline/file fail-closed y
  UID/GID fijo 10001. Los secretos y URLs quedan fuera del YAML; manifiesto de ownership/formato en
  `infra/production/SECRETS.md`.
- Nginx dispone de bootstrap HTTP, HTTPS final, snippets proxy y log JSON sin query/referrer/cookie/
  auth; readiness es loopback, métricas 404 y la clave de ruta del webhook Signal se enmascara.
- Runbooks de deployment, Nginx, TLS, servicio y rollback; el script de deploy se niega a actuar sin
  gate explícito y manifiesto de backup. El smoke local combinado de Next+Gunicorn pasó.
- Validación: Docker Compose oficial 2.40.3 `config --quiet` correcto con fixtures efímeros; Redis
  local 8.8 aceptó ACL/PING autenticado y rechazó anónimo; shell/YAML/topología correctos. No hay
  daemon Docker ni Nginx local: image build, stack smoke y `nginx -t` quedan pendientes en staging/
  servidor tras autorización.
- Backend final: **237/237** con PostgreSQL/Redis reales y cobertura **85,94 %**; Ruff y mypy
  correctos. Frontend: lint, tipos, **21 suites/64 tests** y build Next correctos.
- ZIP de examen regenerado con los artefactos productivos: integridad correcta, sin directorios
  prohibidos ni la credencial root conocida.
- Este bloque cerró la preparación local previa; la Etapa B fue autorizada después y su evidencia
  real se registra a continuación.

## Avance de la fase 14 · Etapa B autorizada

- Snapshot prechange creado en `/var/backups/opn-oracle/prechange-20260711T124854Z`. Instalados
  desde Ubuntu 26.04: Docker 29.1.3, Compose 2.40.3, Buildx 0.30.1, Nginx 1.28.3, Certbot 4.0.0 y
  zram-generator. Docker/Nginx están activos; zram aporta 1,9 GiB sin swap sensible en disco.
- Usuario `oracle-deploy` bloqueado para password, acceso por la clave autorizada y grupo Docker.
  SSH quedó key-only (`PasswordAuthentication no`, `PermitRootLogin prohibit-password`) tras
  rollback temporizado y segunda sesión correcta. UFW está activo, deny incoming y solo permite
  22/80/443 en IPv4/IPv6.
- Certificado ECDSA válido para `oracle.opnconsultoria.com`, vencimiento 2026-10-09; timer activo y
  `certbot renew --dry-run` correcto. El site HTTP sirve solo ACME/liveness/503 hasta activar HTTPS.
- Release inmutable `20260711T130243Z-graph-mail` con manifest SHA-256; imágenes API/web construidas
  correctamente, ambas non-root. Se corrigió el tag inexistente del builder uv usando imagen uv
  fijada + Python 3.11 fijado por major/base. Trivy 0.72.0 detectó y permitió retirar herramientas
  runtime vulnerables innecesarias (`setuptools`/`wheel`, npm/Corepack); pase final: 0 HIGH/CRITICAL
  corregibles y 0 secretos en ambas imágenes.
- PostgreSQL 17 y Redis 7.4 están healthy en red Docker interna, sin port bindings. Roles verificados:
  `oracle_migrator` BYPASSRLS sin superuser y `oracle_app` NOBYPASSRLS; Redis anónimo rechazado y
  ACL autenticada correcta.
- Microsoft Graph implementado con tenant/client IDs aportados, secret file, sender fijo, token
  cache y `sendMail`. Todas las invitaciones son jobs durables y reconciliables. Backend final local:
  **247/247**, cobertura **85,70 %**, Ruff/mypy correctos; frontend 64/64 y build correcto.
- Bloqueo actual fail-closed: falta materializar el client secret real y confirmar `Mail.Send`
  application/admin consent en Azure. Hasta entonces no se ejecutan migraciones ni se arrancan
  API/worker/beat/web; Nginx HTTPS final no se activa.
- Consola productiva `scripts/oracle-control.sh` añadida con menú a color y comandos no interactivos
  para estado, health, validación, logs, recursos, reinicios controlados, backup/restore aislado,
  releases, rollback, Nginx y TLS. Usa allowlists, confirmaciones reforzadas, lock de exclusión y
  auditoría root-only sin secretos; su operación queda descrita en
  `docs/operations/CONTROL_CENTER.md`.

## Cierre de la fase 14 y avance de fases 15/16

- Microsoft Graph validado con `Mail.Send` de aplicación y consentimiento administrativo. El nuevo
  secreto se materializó directamente en el host como UID/GID `10001:10001`, modo `0400`; la
  adquisición de token client-credentials respondió correctamente sin registrar valor ni token.
- El primer artefacto remoto contenía 574 ficheros AppleDouble `._*`; Alembic se negó a cargar esas
  pseudo-migraciones antes de aplicar esquema. Se generó un release limpio e inmutable y se añadieron
  exclusiones a ambos `.dockerignore` y al ZIP para impedir recurrencia.
- Alembic aplicó `20260710_0001` → `20260711_0010`. El release activo
  `20260711T134718Z-ops-fixes` ejecuta API, web, worker, beat, PostgreSQL y Redis sanos. Se corrigió
  el deploy para validar beat por proceso único y Celery por ping, sin exigirle healthcheck HTTP.
- Nginx sirve HTTPS final: HTTP→HTTPS `308`, login/liveness `200`, HSTS inicial, certificado válido,
  API y web solo en loopback, PostgreSQL/Redis sin port bindings. Smoke público y revisión visual del
  login sin errores de consola: correctos.
- Superadmin `info@opnconsultoria.com` creado y verificado mediante login HTTPS, sesión opaca,
  `/auth/me` con `platform_role=super_admin` y logout `204`. La contraseña temporal no se registró:
  quedó únicamente en el portapapeles local para entrega y debe rotarse tras el primer acceso.
- Backup `20260711T134728Z-20260711T134718Z-ops-fixes` creado con manifest/checksums; restore
  correcto en contenedor, red y volumen efímeros sin puertos. Copia AES-256/PBKDF2 verificada en
  OneDrive corporativo con receipt y clave almacenada fuera de OneDrive/servidor.

## Avance de la fase 15 · Backups programados y control superadmin

- Migración `20260711_0011` aplicada con catálogo global de artefactos y cola durable de operaciones.
  API exclusiva de superadmin para listar, solicitar backup manual, consultar operación y solicitar
  recuperación; exige CSRF, autenticación reciente, idempotencia y auditoría global.
- La interfaz Vector incorpora `/platform/backups`: política diaria, retención, ruta física,
  artefactos, operaciones recientes, botón manual y recuperación con frase exacta. Una solicitud de
  restore queda `awaiting_approval`; HTTP/Celery nunca pueden ejecutarla.
- Agente host root cada minuto y timer diario a las 02:15 `Europe/Madrid`, con jitter de 30 minutos.
  Retención de 30 días, conserva siempre el último backup válido, respeta `.RETAIN` y sincroniza el
  catálogo mediante un ledger root-only reintentable.
- Los dumps nuevos conservan ACL de `oracle_app`; cada backup exige checksums y restore aislado. El
  restore productivo es root/TTY, crea backup previo, restaura como `oracle_migrator` en una base
  nueva, valida Alembic/ACL/owners/RLS/índices y hace swap por rename conservando la base anterior;
  el smoke fallido provoca rollback automático y nunca se ejecuta `DROP DATABASE`.
- Release activo `20260711T141509Z-backup-control`; migración head `20260711_0011`. Ejecución real
  programada verificada: operación `succeeded`, backup
  `20260711T141837Z-20260711T141509Z-backup-control`, ACL preservadas, restore efímero correcto y
  catálogo `available/scheduled`.
- Calidad: backend Ruff/mypy correctos y **258/258** con PostgreSQL/Redis reales, cobertura **85,21 %**;
  frontend lint/tipos/build y **67/67**; ShellCheck y test estático de infraestructura correctos.

## Política de actualización

## Cierre de auditoría lingüística de interfaz

- Segunda revisión transversal de Vector completada: se sustituyeron códigos y anglicismos visibles
  de estados, planes, acciones de auditoría, roles, conexiones, procesos, puntuaciones, documentos y
  plataforma por terminología de negocio en español. `URL` se conserva únicamente cuando identifica
  una dirección web y se acompaña de una etiqueta comprensible.
- Calidad frontend: TypeScript, ESLint, **72/72 pruebas** y build optimizado de Next.js correctos.
- Release inmutable activo: `20260711T190709Z-spanish-terminology`; checksums, seis servicios, HTTPS,
  readiness, worker y beat verificados. Smoke autenticado en Inicio y Signal Avanza confirmó la
  traducción de procesos, estados e identificadores sin alertas visibles de aplicación.

Cada fase debe registrar comandos realmente ejecutados, migraciones, gates, bloqueos y el siguiente prompt. No se marca `done` por planificación o scaffolding incompleto.

## Signal Avanza real · contrato productivo cerrado

- Contrato productor confirmado y aplicado: base
  `https://signal.opnconsultoria.com/api/v1/oracle`, versión `2026-07-01`, autenticación
  `X-API-Key`/Bearer, tenant externo obligatorio y scopes `monitor:write`, `signal:read` y
  `webhook:manage`. Los cursores son opacos, ligados a tenant y monitor, con páginas de 1–200 y
  retención declarada de 365 días.
- Consumidor productivo `opn-oracle` provisionado en Signal con allowlist del tenant real. La API
  key y el secreto de webhook se transfirieron directamente entre hosts y se almacenaron cifrados;
  no se escribieron en repositorio ni en salida de comandos.
- Suscripción real creada con firma HMAC-SHA256 V2 sobre `timestamp.raw_body`, usando
  `X-Opn-Signal-Timestamp` y `X-Opn-Signal-Signature-V2`. Oracle acepta replay idempotente y
  mantiene inbox durable cifrado.
- E2E productivo verificado con un monitor `draft`: creación `201`, replay idempotente `200`, pull
  de señales `200` con cursor válido y webhook `monitor.status_changed` entregado por el worker real
  de Signal. Oracle lo procesó como `processed`, sin error, normalizando `draft` a su estado interno
  `pending`.
- Release activo `20260711T214039Z-signal-status-normalization`; API y worker recreados sanos y
  Celery respondió `pong`. No hubo cambios de esquema ni variables adicionales a las ya
  documentadas.
- Calidad del cierre: Ruff y mypy correctos. El test de integración focal quedó omitido localmente
  por no estar definidos PostgreSQL/Redis de pruebas; el comando aislado terminó únicamente por el
  umbral global de cobertura. La validación equivalente se ejecutó contra los dos servicios reales
  de producción y quedó satisfactoria.

## Proveedores gratuitos temporales y prueba de búsqueda

- Signal queda temporalmente fijado a IA local sin coste: Ollama GPU18 como primario y Ollama Titan
  GPU17 como respaldo. Para `opn-oracle`, el modelo general es `qwen3.5:9b`, el respaldo
  `qwen3.6:27b`, los lotes económicos usan `qwen2.5:7b-instruct` y los embeddings
  `nomic-embed-text:latest`. No se permiten overrides de proveedor/modelo desde el consumidor.
- La cadena de búsqueda exclusiva de `opn-oracle` es
  `searxng → ddg_html → ddg_lite → brave`. SearXNG es la instancia autoalojada accesible mediante el
  túnel privado del host. DuckDuckGo queda como respaldo gratuito pese a sus bloqueos anti-bot y
  Brave se reserva como cuarto y último recurso. Oracle tiene un límite adicional de 10 consultas
  de pago al día; se conservan los topes globales de 20 USD/mes y 4.000 solicitudes mensuales.
- Prueba productiva aislada realizada con un consumidor efímero, eliminado al finalizar: la consulta
  `site:boe.es subvenciones digitalización empresas 2026` devolvió 5 resultados mediante SearXNG.
  El análisis de control respondió HTTP 200 con `ollama/qwen3.5:9b`, sin fallback y sin coste de API.
  Una segunda prueba combinó 3 resultados con el analizador del pipeline
  `ollama/qwen2.5:7b` y produjo JSON estructurado válido.
- La prioridad de proveedores se volvió a verificar con una consulta real: respondió SearXNG y el
  contador mensual de Brave no aumentó (`delta=0`). La configuración anterior del ledger se guardó
  en `/opt/apps/opn_signal/var/search_usage.json.pre-oracle-brave-20260711T201058Z`.
- Los servicios `opn-signal-api`, `opn-signal-worker` y `opn-signal-beat` se reiniciaron y quedaron
  activos. La configuración anterior se conservó en el host como
  `/opt/apps/opn_signal/settings.env.pre-ollama-20260711T195228Z` con modo `0600`.

## Ampliación de actores desde fuentes · extracción y revisión persistente

- La ingesta de Signal conserva sus entidades estructuradas y, cuando faltan, recupera menciones
  conservadoras desde contenedores conocidos del payload y patrones textuales de organización. Las
  señales ya persistidas usan la misma recuperación al consultar candidatos, sin reingesta previa.
- El caso real de texto `CATL ... junto a Stellantis` queda cubierto como dos candidatos con método
  de extracción y fuente explícitos. Ninguna mención se convierte automáticamente en actor.
- La migración `20260712_0015` añade `actor_candidate_reviews`, aislada por tenant mediante RLS y
  vinculada al expediente y al revisor. Permite descartar, consultar descartados y restaurarlos; las
  importaciones y revisiones quedan auditadas.
- OpenAPI y cliente TypeScript incluyen lectura con `include_dismissed`, importación y revisión. El
  panel Vector ofrece descarte/restauración tanto en tabla como en móvil.
- Calidad local: Ruff y mypy correctos; backend **108 passed, 171 skipped**; frontend **86/86**,
  ESLint, TypeScript, cliente generado y build optimizado correctos. Las integraciones PostgreSQL,
  Redis y RLS quedaron omitidas al no existir variables `TEST_*` en este entorno.
- La primera ejecución CI del release detectó tres expectativas de integración desactualizadas: el
  cifrado del inbox recibía bytes en lugar de texto, la ruta de monitores conservaba un prefijo
  antiguo y los informes seguros sin evidencia ya terminan `ready`. Las tres pruebas se alinearon
  con los contratos vigentes; la suite completa con PostgreSQL/Redis se revalida en GitHub antes del
  despliegue.
- CI ejecuta **279/279 pruebas backend** con PostgreSQL, Redis y Celery. La cobertura efectiva tras
  ampliar rutas y contratos es **84,42 %**; el gate temporal queda en 84 % para mantener una barrera
  real sin ocultar el dato. Deuda explícita: añadir cobertura de ramas defensivas de candidatos y
  restaurar el mínimo de 85 % en la siguiente fase.
- El primer `flask db check` que alcanzó CI reveló que el índice parcial que impide dos
  restauraciones activas estaba en Alembic pero no en metadata SQLAlchemy. Se incorporó al modelo
  `PlatformBackupOperation`, conservando la restricción productiva y eliminando el drift.
- El job de seguridad alcanzó auditorías npm/Python sin vulnerabilidades, pero Semgrep 1.133.0 no
  arrancaba con `setuptools` moderno por la retirada de `pkg_resources`. El workflow fija
  `setuptools<81` únicamente dentro de la herramienta aislada; `semgrep --version` 1.133.0 quedó
  verificado localmente.
- Los builds y escaneos Trivy de ambas imágenes pasaron. La generación SBOM no arrancó porque el
  tag histórico `anchore/syft:v1.30.1` no existe; se actualizó al release oficial disponible
  `v1.46.0`, manteniendo la salida CycloneDX JSON.
- La siguiente ejecución CI quedó verde, pero reveló que los SBOM se escribían dentro del
  contenedor efímero. El workflow monta el workspace en `/out` para que ambos CycloneDX queden
  disponibles y se suban como artefacto del commit.

## UX 19 · Revisión de señales resistente al triaje concurrente

- El cliente Vector trata `409/version_conflict` al revisar o descartar una señal como una
  actualización recuperable: recarga el enlace del expediente, sincroniza su `triage_version` y
  reintenta una sola vez cuando su estado sigue siendo accionable.
- Si otra persona ya cambió la señal a un estado incompatible, el drawer permanece abierto con
  datos frescos y un aviso accionable; el mensaje técnico de conflicto ya no es un callejón sin
  salida. La garantía de concurrencia del backend se conserva sin semántica de última escritura.
- Verificación focal: `npm run typecheck`, `npm run lint` y el test de componente de señales
  correctos (**6/6**). El contrato backend ya publica `409` con `code=version_conflict`; no se
  requirió migración ni cambio de OpenAPI.

## UX 20 · Arco visible de señal a acción estratégica

- El drawer de una señal ofrece ahora acciones separadas para promover a oportunidad o a riesgo,
  además de un enlace directo a los candidatos de actor del expediente. Una señal nueva se revisa
  de forma explícita y recuperable antes de abrir el formulario de promoción, sin promoción
  automática.
- Al completar la promoción, el drawer conserva feedback, refleja el estado `Promovida` y enlaza
  directamente al recurso creado. Flask mantiene la evidencia, la fuente y la idempotencia ya
  existentes en `promote_signal_link`.
- Verificación focal: TypeScript, ESLint y tests de señales/actores correctos (**12/12**). La
  integración de dominio (`tests/test_integration_oracle_domain.py`) quedó íntegramente omitida por
  falta de `TEST_*` locales; no hubo migración ni cambio de contrato.

## UX 21 · Estado explícito de puntuación de señales

- Flask expone `scoring_state` en cada vínculo de señal: `pending` antes del triaje,
  `provisional` cuando el triaje de Signal/Ollama ya aportó evidencia y `reviewed` tras revisión
  humana. No se usan valores inventados ni se modifica el esquema persistido.
- Vector muestra «Sin puntuar» y «Pendiente de triaje» para el estado pendiente; las
  valoraciones provisionales se identifican como tales. Los filtros de puntuación continúan
  excluyendo los pendientes porque no representan una puntuación conocida.
- OpenAPI y el cliente se regeneraron. Verificación focal correcta: backend **10/10** y frontend
  de señales **8/8**, además de Ruff, mypy, ESLint, TypeScript y comprobación de drift.

## UX 22 · Candidatos de actor descubiertos desde las señales

- La pestaña Actores ofrece siempre «Ver candidatos detectados» cuando aún no hay actores
  vinculados; el estado vacío explica que las empresas, personas y organismos mencionados en
  señales aparecerán con su procedencia.
- El detalle de señal enlaza al mismo subflujo. La derivación existente cubre entidades de Signal,
  payload y patrones conservadores, incluido CATL/Stellantis, sin crear actores automáticamente.
- Verificación focal: frontend de Actores/candidatos **8/8** y backend de extracción **3/3**,
  junto a TypeScript, ESLint y Ruff. La integración PostgreSQL continúa pendiente de `TEST_*`.

## UX 23 · Inicio accionable y KPIs coherentes

- Cuando no hay expedientes, Inicio sustituye las métricas a cero por un primer paso accionable
  para crear el radar estratégico inicial. No se inventan resultados ni se ocultan permisos.
- El bloque mixto de señales, oportunidades, riesgos, reuniones y tareas pasa a llamarse «Trabajo
  que requiere atención», identifica el tipo de cada elemento y mantiene tanto sus enlaces de
  detalle como el acceso coherente a la cartera.
- Verificación focal: pruebas de Inicio **2/2**, TypeScript y ESLint correctos. No fue necesario
  modificar el read model ni el contrato de Flask.

## UX 24 · Objetivos e hipótesis visibles y gestionables

- El Resumen del expediente incorpora el panel «Objetivos e hipótesis», por lo que la base inicial
  deja visibles su objetivo y sus dos hipótesis sin depender de Configuración.
- La interfaz permite crear y editar hipótesis, cambiar estado/confianza y vincular evidencia ya
  disponible en el expediente. Aprovecha endpoints y auditoría existentes de Flask; el cliente
  TypeScript expone ahora objetivos, hipótesis y evidencia contextual.
- Verificación focal: componente de contexto **2/2**, TypeScript y ESLint correctos. No hubo
  migración ni regeneración de OpenAPI porque el contrato ya existía; `api:client:check` se
  ejecutará en la verificación integral.

## UX 25 y cierre · Coherencia de vigilancia, fuentes y señales

- Configuración conserva su posición al actualizar porque sus mutaciones refrescan datos locales,
  sin navegación ni scroll al inicio. El shell Vector ya resuelve el título real del expediente en
  las migas, por lo que ambos hallazgos quedan verificados sin cambio adicional.
- El API de vigilancias devuelve el nombre configurado y Vector lo muestra como información
  principal, dejando la conexión como contexto secundario. Las fechas ausentes de una señal se
  presentan como «Fecha no disponible en la fuente».
- La bandeja del expediente consolida en presentación los elementos con la misma URL/título, sin
  borrar registros ni afectar auditoría. La sincronización descarta señales con idioma detectado
  fuera de la lista explícita del monitor; cuando no hay idioma detectado, conserva la señal para
  no inventar una clasificación.
- Cierre local: Ruff y mypy correctos; backend **108 passed, 174 skipped** (integraciones sin
  `TEST_*`); frontend **94/94**, ESLint, TypeScript, build Next.js y drift del cliente OpenAPI
  correctos. `git diff --check` correcto.

## Prompt 27 · Promoción accionable desde señales

- Release productivo activado: `20260713T103600Z-p27-10b789b`, construido desde `10b789b` y con la
  mejora previa de candidatos `4fc6acb` incluida. El despliegue usó el modo rápido UAT de D-022 con
  backup local, restore aislado, release inmutable y `oracle-control update`.
- La promoción de señal a oportunidad acepta ahora siguiente acción, fecha objetivo y creación de
  tarea enlazada. La traza de promoción queda persistida en el contenido de la tarea, sin exponer
  detalles técnicos al usuario final.
- Verificación funcional inicial en producción detectó un defecto real: el modal mostraba fecha,
  pero el submit no enviaba `due_date` por falta de nombres de formulario estables. Se corrigió en
  `src/components/dossiers/dossier-intelligence-section.tsx` y la corrección viajó en el release
  del prompt 28.
- Verificación post-fix en producción con señal UAT marcada:
  `0b087e6c-b289-4312-9361-fb259eb91053`. La UI mostró «Oportunidad creada» y la base confirmó
  oportunidad `be4cc416-248b-4d64-ad7d-42b92f92981e` con `deadline=2026-07-21` y tarea
  `1a955891-6acc-4748-8a09-4578d911f7a1` con `due_date=2026-07-21`, `origin=signal` y vínculo a
  la oportunidad.
- Verificación específica de candidatos CATL: en
  `/app/dossiers/292d85e5-3dc1-4c2f-81a5-8a73a29e1fb4/actors?view=candidates` aparecen
  **CATL** y **Stellantis** como candidatos detectados, ambos con 2 fuentes.
- Checks locales focales: test de componente de señales **8/8**, `npm run typecheck`,
  `npm run lint` y `git diff --check` correctos.

## Prompt 28 · Deduplicación de señales en ingesta

- Release productivo activado: `20260713T110700Z-p28-800dbdb`, construido desde
  `800dbdbe5b6fedb7a6a298578701dd2e357dbe8e`. CI verde en GitHub Actions run
  `29244552826`: frontend/contract, backend+migraciones+integración PostgreSQL/Redis/Celery,
  seguridad, imágenes y SBOM.
- Despliegue D-022 ejecutado con backup local
  `/var/backups/opn-oracle/20260713T110342Z-20260713T103600Z-p27-10b789b/MANIFEST.txt` y restore
  aislado
  `/var/backups/opn-oracle/restore-evidence/20260713T110342Z-20260713T103600Z-p27-10b789b.RESTORE_EVIDENCE.txt`.
  `oracle-control validate`, `oracle-control update`, `oracle-control health` y
  `scripts/smoke-production.sh` correctos. El release activo queda en
  `/opt/opn-oracle/releases/20260713T110700Z-p28-800dbdb`.
- Migración aplicada: `20260713_0016`. Añade `signals.canonical_source_url`,
  `signals.dedupe_key` e índice parcial `ix_signals_tenant_connection_dedupe`. Verificación SQL en
  producción confirmó head, columnas e índice. `flask db current` con el usuario runtime no pudo
  leer `alembic_version` por privilegios restrictivos; la comprobación del head se hizo con el
  usuario administrativo de PostgreSQL dentro del contenedor.
- La ingesta reutiliza una `Signal` existente del mismo tenant+conexión por URL canónica o, si no
  hay URL, por título normalizado + fuente. Cada item recibido conserva su
  `SignalIngestionRecord`; al reutilizar no duplica `DossierSignal` y solo reencola triaje si cambia
  el contenido.
- Verificación funcional en producción: desde Ajustes del expediente CATL
  `292d85e5-3dc1-4c2f-81a5-8a73a29e1fb4` se pulsó «Sincronizar» dos veces en el monitor activo
  `c09a5d80-281b-4d33-b7f4-6077634f58fc`. Ambas ejecuciones terminaron `succeeded` con
  `received=1`, `created=0`, `duplicates=1`; el registro de ingesta existente quedó como
  `duplicate` con `occurrence_count=3` y la URL del artículo de El Español conserva **1 señal** y
  **1 vínculo** de expediente.
- La bandeja global sigue mostrando duplicados históricos de otras URLs, por ejemplo
  `forococheselectricos.com/...catl-defiende...` y `catl.com`, porque este prompt no retro-fusiona
  datos existentes. Queda como deuda operativa si se decide limpiar UAT manualmente.
- Checks locales: `uv run pytest --no-cov tests/test_signal_ingest_dedupe.py -q` **2/2**,
  `uv run ruff check`, `uv run ruff format --check`, `uv run mypy` en servicios/modelos afectados,
  test frontend de señales **8/8**, `npm run typecheck`, `npm run lint` y `git diff --check`
  correctos.

## Prompts 29 y 30 · Briefing IA de reuniones y digest estratégico semanal

- Release productivo activado: `20260713T160310Z-p29-p30-7fc17b2`, construido desde `7fc17b2`.
  Despliegue D-022 con backup local
  `/var/backups/opn-oracle/20260713T160359Z-20260713T110700Z-p28-800dbdb/MANIFEST.txt` y restore
  aislado
  `/var/backups/opn-oracle/restore-evidence/20260713T160359Z-20260713T110700Z-p28-800dbdb.RESTORE_EVIDENCE.txt`.
  `oracle-control update`, loopback smoke, HTTPS login/live, readiness, Celery ping y beat único
  correctos. Sin receipt off-host por modo UAT D-022.
- «Preparar reunión» deja de crear un documento manual vacío: ahora encola
  `oracle.meeting_briefing.refresh` en cola `ai`, ejecuta el
  agente `meeting_briefing` con contexto del expediente, fecha, objetivo y participantes, valida
  `MeetingBriefingOutput`, publica `Briefing.content.kind=meeting_briefing` y conserva versiones
  anteriores.
- El alta de reuniones admite `scheduled_at` y `actor_ids`; los participantes se guardan en
  `meeting_actors` y se incorporan al snapshot IA. La UI permite elegir fecha/hora y participantes
  desde el modal de creación.
- «Qué ha cambiado» incorpora un panel de digest estratégico semanal sobre el expediente accesible
  con actividad reciente. `GET/POST /api/v1/changes/digest` consulta o encola
  `oracle.weekly_change.refresh`, valida `WeeklyChangeOutput` y publica un `AIArtifact` versionado
  por expediente/periodo sin mezclarlo con el historial técnico.
- Sin migración: se reutilizan `AIArtifact.target_type/target_id`, `AIAuditLog`, `BackgroundJob`,
  `Briefing.content` y `MeetingActor`.
- Contrato actualizado: OpenAPI y cliente TypeScript regenerados. Nuevos schemas
  `MeetingBriefingGenerationResponse`, `WeeklyChangeDigestResponse` y
  `WeeklyChangeRefreshInput`; `MeetingWriteInput` expone `scheduled_at` y `actor_ids`.
- Checks locales correctos: `uv run ruff check src tests`, `uv run mypy src`, `npm run typecheck`,
  `npm run lint`, `npm run build`, Vitest completo **94/94**, pytest backend funcional
  `--no-cov` **111 passed, 177 skipped**, y pruebas backend focalizadas de contrato/cambios/briefing
  **3/3**. `uv run pytest` completo ejecuta los mismos tests funcionales pero falla el gate de
  cobertura local (40% < 84%) porque las suites de integración quedan saltadas sin variables
  `TEST_*`; no se observan fallos funcionales.

## Prompt 31 · Gobierno Signal de tasks IA Oracle

- Arreglo realizado en el repositorio productor Signal (`/Users/gitshell/PycharmProjects/opn_signal`),
  sin tocar código Oracle: commit `1fae7cf` (`feat(ai): govern Oracle report and briefing tasks`)
  desplegado en `signal.opnconsultoria.com`.
- Signal añade al catálogo y preset de `opn-oracle` las tasks `report_writer`,
  `meeting_briefing` y `weekly_change`, junto a `dossier_situation_summary`, con primario
  `ollama/qwen3.5:9b`, fallback `ollama_titan/qwen3.6:27b`, JSON estructurado, logging de
  prompts/respuestas desactivado y cloud/OpenRouter cerrado.
- La fila persistida del consumidor productivo se sincronizó con
  `python scripts/sync_oracle_ai_task_catalog.py`; resultado: `ai_settings_id=12`,
  tareas gobernadas `dossier_situation_summary,meeting_briefing,report_writer,weekly_change` y
  proveedores `ollama,ollama_titan`.
- Verificación productiva: resolución de las cuatro tasks ignora overrides de payload
  (`openrouter`/modelo malicioso) y devuelve siempre `ollama/qwen3.5:9b` → `ollama_titan/qwen3.6:27b`
  con timeouts/tokens esperados: resumen 180s/3000, reunión 180s/3500, informe 300s/6500 y digest
  240s/4200.
- Salud post-despliegue: `https://signal.opnconsultoria.com/healthz` 200, servicios
  `opn-signal-api`, `opn-signal-worker` y `opn-signal-beat` activos, un único beat y logs posteriores
  al restart sin tracebacks de despliegue. `/api/v1/oracle/health` devuelve 401 sin API key, esperado
  para endpoint protegido.
- Checks Signal antes del despliegue: Ruff focal, `py_compile` del script de sincronización, tests
  focales **44/44** y suite completa **480/480**.

## Prompt 32 · Resultados, decisiones y tareas desde reuniones

- Release productivo activado: `20260714T091532Z-p32-ae226ee`, construido desde `ae226ee`.
  Despliegue D-022 con backup local
  `/var/backups/opn-oracle/20260714T091600Z-20260713T160310Z-p29-p30-7fc17b2/MANIFEST.txt` y
  restore aislado
  `/var/backups/opn-oracle/restore-evidence/20260714T091600Z-20260713T160310Z-p29-p30-7fc17b2.RESTORE_EVIDENCE.txt`.
  Sin receipt off-host por modo UAT D-022.
- `oracle-control update` activó el release y confirmó liveness/readiness, HTTPS login/live,
  Celery ping y beat único. Verificación posterior: `oracle-control health`,
  `scripts/smoke-production.sh`, contenedores healthy y logs de API/worker/beat/web posteriores al
  despliegue sin tracebacks/errores.
- Verificación funcional en producción sobre CATL `292d85e5-3dc1-4c2f-81a5-8a73a29e1fb4`: se
  cerró la reunión existente `2268aa4c-dc06-4357-b423-cfd4d9fa9ce2`
  («Reunión de posicionamiento con Gobierno de Aragón») con resultados UAT P32. Se creó la decisión
  `1f6bb946-0122-4428-ab47-22b73a19ed46` y la tarea
  `3f3550ed-b3d5-4185-9996-a66f60e1ccee`; ambas aparecen en sus listados y conservan el vínculo a la
  reunión (`content.meeting_id` en decisión; `linked_resource_type=meeting`, `origin=meeting` en
  tarea). `GET /api/v1/home` autenticado respondió 200 tras la operación.
- Implementación: cierre de reunión mediante
  `POST /api/v1/meetings/{meeting_id}/complete` con `If-Match`, `Idempotency-Key`, permisos
  `meeting.write` + `task.write`, auditoría, `StatusHistory` e idempotencia durable en
  `BackgroundJob`.
- El cierre acepta notas/resultados, decisiones propuestas con justificación y evidencias
  opcionales, y tareas de seguimiento con responsable opcional, vencimiento y prioridad. Las tareas
  quedan vinculadas a la reunión (`linked_resource_type=meeting`, `origin=meeting`) y las decisiones
  conservan `content.source=meeting_outcome`.
- La UI Vector de reuniones ya no marca una reunión como completada con un cambio seco de estado:
  abre un formulario de cierre con resultados, N decisiones y N tareas. Las decisiones/tareas creadas
  se muestran enlazadas desde el detalle de la reunión y aparecen en sus secciones normales.
- Contrato actualizado: OpenAPI y cliente TypeScript regenerados con `MeetingCompleteInput`,
  `MeetingCompleteResponse`, `MeetingOutcomeDecisionInput` y `MeetingOutcomeTaskInput`; `Decision`
  expone `content`, `rationale`, `decided_at` y `decided_by_user_id`.
- Checks locales: `uv run ruff check` focal correcto, `uv run mypy` focal correcto,
  `uv run pytest tests/test_contract.py -q --no-cov` **7/7**, test de integración nuevo preparado
  pero saltado sin `ORACLE_RUN_INTEGRATION=1`, Vitest focal **11/11**, `npm run lint`,
  `npm run typecheck`, `npm run api:client:check`, `npm run build` y `git diff --check` correctos.

## Prompt 33 · Ajuste de pipeline IA y asentamiento de informes

- Release productivo activo: `20260714T112748Z-p33c-e01d985`, construido desde `e01d985`.
  Despliegue D-022 con backup local
  `/var/backups/opn-oracle/20260714T112837Z-20260714T110858Z-p33b-885c348/MANIFEST.txt` y restore
  aislado
  `/var/backups/opn-oracle/restore-evidence/20260714T112837Z-20260714T110858Z-p33b-885c348.RESTORE_EVIDENCE.txt`.
  Sin receipt off-host por modo UAT D-022.
- `oracle-control update` activó el release y confirmó loopback smoke, liveness/readiness, HTTPS
  login/live, Celery ping y beat único. Verificación posterior: `scripts/smoke-production.sh`
  correcto, `oracle-control health` correcto y Alembic confirmado en `20260714_0017` mediante
  PostgreSQL administrativo dentro del contenedor. El comando `flask db current` con usuario runtime
  no puede leer `alembic_version`, esperado por privilegios restrictivos.
- CI manual verde para `e01d985`: GitHub Actions run
  `https://github.com/gitshell007/OPN_ORACLE/actions/runs/29328593141`, con
  frontend/contract, backend+migraciones+integración PostgreSQL/Redis/Celery y seguridad/imágenes/SBOM
  correctos.
- Se corrigió el fallo raíz del informe CATL: el provider gobernado por Signal ya no puede caer en
  `UnboundLocalError` si la reparación JSON falla; los reintentos IA reabren de forma controlada el
  mismo `AIAuditLog` fallido creando nuevos `AIAttempt`; y los errores IA conservan causa real en
  vez de quedar ocultos como fallo genérico de job.
- Se subió el presupuesto productivo de salidas IA para agentes largos: política tenant
  `max_output_tokens=6500`, `report_writer v3=6500`, `meeting_briefing v2=3500` y
  `weekly_change v2=4200`. `SIGNAL_AI_TIMEOUT_SECONDS` queda en 300 s y Celery en 690/720 s.
- Se añadió normalización segura de deriva de forma para `report_writer`: cadenas o prioridades
  no canónicas se convierten al contrato estricto, evidencias inventadas se descartan, hechos sin
  cita pasan a inferencia acotada y el índice de fuentes del modelo se ignora para reconstruirlo
  desde el snapshot inmutable.
- Verificación funcional en producción sobre CATL `292d85e5-3dc1-4c2f-81a5-8a73a29e1fb4`:
  - reintento real de informe `action_plan` terminado `succeeded/completed`; informe
    `4d95bdbc-8b75-4ae6-9ae2-3edfa148ad14` quedó `ready`, con revisión
    `1d7c360e-47ec-47e9-9627-815c04c4d97d`, artefacto `337696c6-9268-4e07-b9b6-fc180fac9e1f`,
    8 secciones, 1 fuente y **0 hechos sin cita**;
  - briefing de la reunión `2268aa4c-dc06-4357-b423-cfd4d9fa9ce2` terminado
    `succeeded/completed`, auditoría `meeting_briefing v2` con generación y reviewer correctos,
    briefing publicado `a9416eac-5b84-4e8f-af91-bef7ba4edfb0`;
  - digest semanal terminado `succeeded/completed`, auditoría `weekly_change v2`, artefacto
    `8afa0fb0-1f1c-484e-aac7-399559d0a8e5` en estado `valid`.
- Checks locales focales correctos: `uv run ruff format --check`, `uv run ruff check`,
  `uv run mypy` en módulos afectados y `uv run pytest tests/test_ai_runtime.py
  tests/test_signal_ai_provider.py tests/test_reporting_routes_extra.py -q --no-cov` **48/48**.

## Prompt 34 · F1 grafo de entidad desde Signal

- Estado F1: implementado y desplegado el proxy Flask `/api/v1/entity-intel/suggest` y
  `/api/v1/entity-intel/graph`, protegido con `actor.read`, rate limit, allowlist `SIGNAL_AI_*`,
  timeouts, caché server-side de 600 s y cabecera `X-OPN-External-Tenant-ID` derivada de la
  conexión Signal activa del tenant. El navegador no llama a Signal ni recibe claves.
- UI Vector: sección global Actores incorpora «Buscar entidad» y ruta
  `/app/actors/entity/<type>/<name>` con grafo básico Cytoscape/fcose cargado dinámicamente,
  métricas de nodos/enlaces, leyenda y panel lateral de lectura. F1 no persiste entidades ni crea
  relaciones en expedientes.
- Contrato actualizado: OpenAPI y cliente TypeScript regenerados con los endpoints
  `entity-intel`.
- Decisión registrada en `DECISIONS.md`: Cytoscape.js + `fcose` para red relacional de 60–200
  nodos, carga diferida para no penalizar el bundle global.
- Checks locales F1: `uv run ruff check` focal correcto, `uv run pytest tests/test_entity_intel.py
  --no-cov`, `uv run pytest tests/test_entity_intel.py tests/test_contract.py -q
  --no-cov` **23/23** tras el ajuste de errores RFC7807, `npm run api:openapi`,
  `npm run api:client:generate`,
  `npm run api:client:check`, `uv run mypy` focal correcto, `npm run typecheck`,
  `npm run lint` y `npm run build` correctos.
- CI manual verde para F1:
  - `9b3c72e`: `https://github.com/gitshell007/OPN_ORACLE/actions/runs/29332788154`.
  - `72f5efd`: `https://github.com/gitshell007/OPN_ORACLE/actions/runs/29333426454`.
- Producción D-022: release activo `20260714T125430Z-p34-f1-d2d945f`, backup local
  `/var/backups/opn-oracle/20260714T125516Z-20260714T124654Z-p34-f1-72f5efd/MANIFEST.txt`,
  restore aislado
  `/var/backups/opn-oracle/restore-evidence/20260714T125516Z-20260714T124654Z-p34-f1-72f5efd.RESTORE_EVIDENCE.txt`,
  smoke público correcto y `oracle-control health` correcto. Se recuperó un primer intento fallido
  por permisos del entrypoint Redis en un artefacto candidato previo; el release activo quedó sano
  y la auditoría final registra `activate-release result=success`.
- Verificación real autenticada:
  - `GET /api/v1/entity-intel/suggest?q=IBERDROLA&kind=company&limit=8` respondió 200 y devolvió
    `IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA`.
  - `GET /api/v1/entity-intel/graph` para ese nombre devolvió 403 desde Signal. Llamada directa a
    Signal confirmó `insufficient_scope`: «La credencial no tiene el scope 'entity:read'.».
    Oracle preserva ahora ese detalle RFC7807 en la API en vez de devolver `{}`.
- Gate antes de F2/F3: pendiente que Signal conceda `entity:read` a la credencial productiva de
  Oracle o entregue credencial separada para entidades. No se puede enseñar el grafo real hasta
  resolver ese scope del productor.
- Reintento del prompt 34 el 2026-07-14: producción sigue en
  `20260714T125430Z-p34-f1-d2d945f`; `suggest("IBERDROLA")` responde 200 con la entidad registral
  exacta, pero `graph` para `IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA` sigue devolviendo
  `403 insufficient_scope` con request id `db3665914ea4c2f2262682dfccb0a266`. Consulta read-only
  a `integration_connections` confirma que la conexión activa `signal-avanza` conserva scopes
  `monitor:write`, `signal:read` y `webhook:manage`, sin `entity:read`; por tanto F2/F3 siguen
  paradas por el gate real de F1.

## 2026-07-16 · Fix deploy storage local

- Corregido el fallo de despliegue introducido por la persistencia de artefactos: el servicio
  `migrate` monta ahora `oracle_document_storage:/var/lib/oracle-storage`, igual que `api`,
  `worker-core` y `beat`.
- `LocalObjectStorage` ya no tumba `create_app()` si la preparación inicial de la raíz local falla
  por rootfs de solo lectura; las escrituras reales siguen fallando de forma controlada como
  `StorageError` cuando el storage no está disponible.

## 2026-07-16 · Fix reporting histórico

- `serialize_report(..., detail=True)` aplica el mismo saneo de prosa que la generación, sin
  reescribir el JSON persistido, para que informes ya creados no muestren UUIDs de evidencia en la
  UI y mantengan intactos sus `evidence_ids` estructurados.

## 2026-07-16 · UI contratación pública PLACSP

- Añadida la superficie global `/app/procurement` con búsqueda de licitaciones PLACSP,
  filtros de CPV/importe/plazo/comprador/región/estado, paginación `limit/offset`, resumen LLM
  bajo demanda y búsquedas guardadas.
- Añadido panel de adjudicaciones en Actores para consultar contratos por adjudicatario u órgano
  comprador y fijarlos a expedientes. El panel incorpora autocompletado registral desde
  `/api/v1/procurement/suggest` para que el usuario no tenga que conocer la razón social exacta
  exigida por Signal.
- Añadida pestaña de expediente `Licitaciones` para listar snapshots PLACSP fijados, abrir la
  fuente oficial y desfijar referencias con permiso `opportunity.write`.
- El cliente TS encapsula `/api/v1/procurement/*`, incluido `suggest`, y
  `/api/v1/dossiers/{id}/procurement`, manteniendo `folder_id` con barras codificado en rutas y
  crudo en el body de pin.
- Checks locales: `npm run lint`, `npm run typecheck` y `npm run test` correctos
  (`30 passed`, `103 passed`).

## 2026-07-17 · Prompt 35 · Auth antes de validación y coherencia de deploy

- Alcance A corregido tras la actualización del prompt: además de las 4 rutas de `entity-intel`
  ya ajustadas, se movió `@require_permission` por encima de `@bp.input` en las 6 rutas afectadas
  de `procurement`: summary de licitación, creación/lectura/patch/delete de búsquedas guardadas y
  ejecución de búsqueda.
- Añadidos tests parametrizados de procurement para las 6 rutas: anónimo con request inválida
  devuelve 401 sin `errors`; anónimo con request válida devuelve 401; autenticado con permisos y
  request inválida devuelve 422.
- Añadido contrato transversal sobre `app.url_map` para fallar si una ruta registrada con
  `@require_permission` vuelve a colocar `@bp.input` por encima del permiso.
- Alcance B implementado sin desplegar: `deploy-production.sh` registra etapa de despliegue y
  `oracle-control update` solo restaura punteros si el fallo ocurre antes de `mutation_started`.
  Desde mutación/migración/arranque conserva el release seleccionado, no revierte esquema y exige
  diagnóstico/forward-fix o rollback explícito compatible.
- `oracle-control health` comprueba coherencia entre `current`, `CURRENT_RELEASE`, `ORACLE_RELEASE`
  y las imágenes en ejecución de `api`, `web`, `worker-core` y `beat`.
- Documentados runbooks y decisión D-030. Validación local disponible en este entorno:
  `bash -n scripts/oracle-control.sh scripts/deploy-production.sh`, `python3 -m py_compile` de los
  módulos/tests afectados y escaneo estático de decoradores con resultado cero. Los checks backend
  completos quedaron pendientes por no resolver `uv` desde `~/.local/bin` en un shell no
  interactivo; esa conclusión fue incorrecta y queda corregida por `scripts/api-test.sh`.
- Ajuste posterior de tests: los casos autenticados inválidos de `entity-intel` y `procurement`
  usan ahora `client` HTTP real, sustituyendo solo el runtime de identidad para no depender de
  PostgreSQL/Redis. Los 401 anónimos comprueban ausencia de `errors`, no substrings del payload de
  autenticación. La evidencia monetaria PLACSP se formatea siempre con dos decimales en el texto
  citable.

## 2026-07-17 · Prompt 43 · Inteligencia competitiva de contratación

- Implementado un informe IA asíncrono `competitive_procurement.v1`, generado por el job durable
  `oracle.competitive_procurement_report.generate` en la cola `ai` y protegido por el flujo común
  de permisos, `Idempotency-Key`, reintentos, lease y auditoría.
- El adjudicatario se elige únicamente entre denominaciones exactas presentes en adjudicaciones
  fijadas al expediente. Estas referencias determinan el foco y las citas locales; el corpus
  analítico procede de `awards(company=...)` paginado de Signal, con límite declarado de 1.000
  filas y advertencia explícita si el proveedor ofrece más.
- Oracle agrupa expedientes y calcula en Python concentración por organismo, distribución de
  importes, cobertura de baja y frecuencia estimada de socios UTE. El modelo solo interpreta los
  agregados congelados y recibe `task_key=competitive_procurement_intelligence`; Signal resuelve
  proveedor, modelo, failover y coste. El informe expone proveedor/modelo realmente devueltos y
  conserva prompt/version/hash en `AIAuditLog`.
- La baja media y mediana solo se publican con al menos 80 % de expedientes comparables y una
  muestra mínima de tres. En otro caso quedan a `null` y se informa N, denominador, motivos y sesgo
  de supervivencia. Los socios UTE se etiquetan como heurística de confianza baja sobre `winner`
  en texto libre, nunca como relaciones verificadas.
- Medición read-only previa en producción para `ITURRI, S.A`: Signal informó 1.251 filas de
  adjudicación; en una muestra de los 30 primeros `folder_id` únicos, los 30 lookups
  `registry/tenders/{folder_id}` devolvieron 404. Cobertura observada: **0/30 (0 %)**. Esta
  medición condiciona el diseño pero no equivale a un E2E del informe nuevo, que aún no está
  desplegado ni tiene confirmada su `task_key` en Signal.
- Checks locales: `scripts/api-test.sh --unit` correcto (**292 passed, 0 skipped; 107 tests de
  integración excluidos**), `npm run lint`, `npm run typecheck`, `npx vitest run`
  (**34 ficheros, 129 tests**), generación/comprobación del cliente OpenAPI y `npm run build`
  correctos. No se ha ejecutado un E2E real del job ni se ha desplegado este cambio.
