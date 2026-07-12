# Estado de implementación de OPN Oracle

Actualizado: 2026-07-12
Rama observada: `master`  
Interfaz canónica: `CANONICAL_UI=vector`

El árbol de trabajo está limpio tras integrar y publicar los cambios del Oráculo contextual.

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
| 15 · CI/CD y backups | in_progress | 2026-07-11 | Codex | GitHub Actions PR/push, candidato GHCR por SHA, SBOM, backup diario systemd, retención 30 días, catálogo/UI superadmin, manual y restore root blue/green | Falta configurar GitHub environments/secrets y automatizar la copia cifrada off-host diaria | Activar CI en GitHub y restore periódico desde descarga off-host |
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
