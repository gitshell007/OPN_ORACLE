# Modelo de amenazas inicial de OPN Oracle

**Estado:** revisado; debe actualizarse en cada fase  
**Método:** análisis por activos, fronteras de confianza y abuso  
**Última revisión:** 2026-07-11 (fase 13: QA integral y hardening)

## 1. Alcance y baseline

Este modelo cubre la arquitectura objetivo: navegador/Next.js, Nginx, Flask/Gunicorn, PostgreSQL, Redis, Celery, almacenamiento de documentos, proveedores IA y Signal Avanza. No sustituye una revisión de código, pentest ni evaluación de infraestructura.

El repositorio contiene ya la aplicación Vector conectada a Flask, sesiones server-side, PostgreSQL
con RLS, Redis, Celery, documentos, Signal desacoplado, runtime IA cerrado por defecto, informes y
auditoría. Los dos conceptos con fixtures permanecen aislados como prototipos de desarrollo y no se
publican en producción. Esta revisión acredita únicamente el entorno local probado: infraestructura,
TLS, backups, restore, scanners de imagen y proveedores externos siguen siendo gates posteriores.

Solo se usan datos sintéticos. No se conectarán datos reales ni se declarará producción lista hasta
completar las evidencias de fases 14–16, incluidas rotación de secretos, aislamiento de parser,
restore real, scan de imagen, smoke exterior y validación de CSP/TLS.

## 2. Activos y objetivos de seguridad

Activos principales:

- expedientes, señales, evidencias, documentos, actores, oportunidades, riesgos y decisiones de cada tenant;
- identidades, memberships, roles, sesiones y tokens de recuperación/invitación;
- secretos de aplicación, cifrado, Signal, correo, IA, PostgreSQL y Redis;
- prompts, resultados IA, feedback y `AIAuditLog`;
- payloads Signal, webhooks, cursores y credenciales de integración;
- jobs, informes, backups y audit trail;
- disponibilidad e integridad de la plataforma.

Objetivos:

1. confidencialidad e incomunicabilidad entre tenants;
2. autorización server-side para cada acción y recurso;
3. trazabilidad de cambios y conclusiones estratégicas;
4. integridad e idempotencia de ingesta y jobs;
5. recuperación probada sin pérdida silenciosa;
6. exposición mínima de datos y secretos.

## 3. Fronteras de confianza

```text
Navegador no confiable
  -> Internet/TLS -> Nginx
  -> Flask (identidad, tenant, permisos, validación)
       -> PostgreSQL (fuente de verdad)
       -> Redis (sesiones, límites, caché y broker; no fuente de verdad)
       -> Celery workers (procesamiento asíncrono)
       -> almacenamiento de documentos
       -> Signal Avanza / proveedores IA / correo
```

Todo dato del navegador, documento, webhook, proveedor, cola y modelo IA es no confiable hasta validarlo. La red privada reduce exposición, pero no sustituye autenticación, autorización ni validación.

## 4. Matriz inicial de amenazas

### T01 — Fuga cross-tenant e IDOR

**Escenario:** un usuario altera UUIDs, filtros, relaciones anidadas, exports o IDs de jobs para leer, modificar, inferir o enumerar datos de otro tenant.

**Controles preventivos**

- `tenant_id` obligatorio en todo recurso de negocio y constraints/índices compuestos cuando proceda.
- Tenant derivado de sesión y membership; nunca confiado desde body/query/header.
- Scoping central en repositorios/servicios y permiso por acción/recurso.
- Validación tenant-safe de relaciones, uploads, joins, jobs y exports.
- PostgreSQL RLS como defensa en profundidad y UUID no enumerables.
- Respuestas `404`/`403` uniformes sin oráculo de existencia.

**Controles detectivos**

- `AuditEvent` con actor, tenant, acción, recurso, resultado y request ID.
- Alertas por accesos denegados repetidos, enumeración y accesos cross-tenant de plataforma.
- Métricas de fallos de autorización sin registrar contenido sensible.

**Pruebas exigidas**

- Matriz negativa tenant A/tenant B para list, get, create, update, delete, relaciones, búsqueda, export y jobs.
- Tests que manipulan `tenant_id`, UUID, filtros, cursores y relaciones anidadas.
- Tests de RLS con conexión/contexto equivalente al productivo.

### T02 — Robo o fijación de sesión

**Escenario:** un atacante obtiene, reutiliza o fija una cookie, mantiene acceso tras logout o explota una sesión no rotada después de elevar privilegios.

**Controles preventivos**

- Cookie opaca `HttpOnly`, `Secure` en producción y `SameSite=Lax`; TLS obligatorio.
- Sesión server-side en Redis y registro revocable `UserSession` en PostgreSQL.
- Rotación tras login, fresh login, contraseña, rol y acciones sensibles.
- Timeout inactivo/absoluto, logout actual/all y revocación inmediata.
- Argon2id y rate limiting para login/reset/invitación; tokens aleatorios de un uso almacenados hasheados.
- No almacenar sesión o JWT en `localStorage`.

**Controles detectivos**

- Auditoría de login, fallos, rotación, logout, revocación y cambios sensibles.
- Avisos de nuevas sesiones y detección prudente de anomalías sin fingerprint invasivo.
- Alertas por abuso de credenciales y rate limits.

**Pruebas exigidas**

- Verificación automatizada de flags de cookie en producción.
- Reutilización de ID previo tras login/rotación y revocación/logout.
- Timeouts, logout-all, reset token de un uso y mensajes anti-enumeración.

### T03 — CSRF

**Escenario:** un sitio tercero provoca una mutación con la cookie del usuario.

**Controles preventivos**

- Token CSRF ligado a sesión en todas las mutaciones; cabecera `X-CSRF-Token`.
- `SameSite=Lax`, validación estricta de `Origin`/`Referer` como defensa adicional y CORS cerrado al origen autorizado.
- `GET`, `HEAD` y `OPTIONS` sin efectos laterales.
- Webhooks separados de sesión web y autenticados por firma.

**Controles detectivos**

- Log seguro y métrica de rechazos CSRF/origen por ruta.
- Alerta por picos de rechazos, sin registrar el token.

**Pruebas exigidas**

- Mutaciones sin token, con token erróneo, de otra sesión, expirado y desde origen no permitido.
- Confirmar que ninguna ruta `GET` cambia estado.

### T04 — XSS y ejecución de contenido activo

**Escenario:** nombres, extractos, HTML de documentos o texto generado por IA se renderizan como código y roban datos o realizan acciones con la sesión.

**Controles preventivos**

- Escape por defecto en React; prohibir `dangerouslySetInnerHTML` salvo sanitización revisada.
- Sanitización allowlist de rich text, URLs y contenido importado.
- CSP con nonces/hashes, `frame-ancestors`, headers de seguridad y dependencias controladas.
- No incluir secretos ni tokens reutilizables en DOM, URL o `localStorage`.
- Visualizar documentos potencialmente activos en aislamiento o servirlos como descarga segura.

**Controles detectivos**

- Reportes CSP a endpoint protegido, SAST/dependency scanning y revisión de sinks peligrosos.
- Registro de sanitización/rechazo por tipo, no del payload completo.

**Pruebas exigidas**

- Payloads XSS almacenados/reflejados en todos los campos, errores, evidencia e IA.
- Tests de CSP y sanitizador; E2E que confirma que scripts/event handlers no ejecutan.

### T05 — Fuga de credenciales y datos sensibles

**Escenario:** secretos aparecen en Git, prompts, comandos, logs, errores, imágenes, builds del frontend o backups.

**Controles preventivos**

- Secretos por entorno/secret store, ficheros con permisos restrictivos y rotación documentada.
- Variables públicas de Next.js separadas: ningún secreto con prefijo expuesto al navegador.
- Redacción central en logging y errores; listas de campos sensibles.
- Credenciales de integración cifradas en reposo; mínimo privilegio y claves separadas por entorno.
- Prohibición de secretos en argumentos Celery, OpenAPI, URLs y documentación.

**Controles detectivos**

- Secret scanning pre-commit/CI, inspección de bundles y escaneo de logs/artefactos.
- Auditoría de lectura/rotación de credenciales y alertas del proveedor cuando existan.

**Pruebas exigidas**

- Fixtures canario para verificar redacción en logs/problem responses/jobs.
- Escaneo del repo, historial entregable, contenedores y bundle frontend.
- Ejercicio de rotación sin interrupción y revocación de la clave anterior.

### T06 — Webhook falsificado o replay de Signal Avanza

**Escenario:** un tercero inyecta señales falsas o repite un evento válido para alterar análisis, scores o jobs.

**Controles preventivos**

- HMAC versionado sobre bytes exactos, timestamp y comparación constant-time.
- Ventana temporal anti-replay, `event_id` único e idempotencia por provider ID/hash.
- Secretos rotables, límites de tamaño/tasa y schema estricto.
- Persistencia atómica de entrega antes de encolar; separación de payload bruto y normalizado.

**Controles detectivos**

- `WebhookDelivery` conserva estado, hash, timestamp e intentos sin secretos.
- Alertas por firma inválida, desfase temporal, duplicados y tasa anómala.

**Pruebas exigidas**

- Contract tests de firma válida/inválida, body alterado, timestamp antiguo/futuro y secreto rotado.
- Repetir el mismo evento concurrentemente y demostrar una sola materialización.

### T07 — Jobs duplicados, fuera de tenant o inconsistentes

**Escenario:** retries, caídas o entregas repetidas generan informes/insights duplicados, procesan el tenant incorrecto o dejan cambios parciales.

**Controles preventivos**

- Tareas idempotentes con clave de operación y constraints durables.
- `BackgroundJob` en PostgreSQL; Redis no es historial autoritativo.
- Payload mínimo basado en IDs; tenant validado de nuevo dentro del worker.
- Transacciones cortas, outbox/inbox para límites transaccionales, retry con backoff/jitter y timeouts.
- Colas separadas y cancelación cooperativa; no serializar ORM, cookies o secretos.

**Controles detectivos**

- Logs con job/correlation/tenant ID, métricas de retry, duplicados, dead-letter lógico y duración.
- Reconciliador de jobs huérfanos/atascados y panel de re-procesado autorizado.

**Pruebas exigidas**

- Worker real: redelivery, ejecución concurrente, caída antes/después del commit y reinicio.
- Manipulación de tenant/job ID y verificación de exactamente un efecto observable.

### T08 — Upload malicioso y parsing inseguro

**Escenario:** archivo con malware, path traversal, bomba de descompresión, polyglot o parser vulnerable consume recursos o accede al sistema.

**Controles preventivos**

- Allowlist de formatos, verificación de magic bytes, tamaño/páginas/ratio y nombres generados por servidor.
- Almacenamiento fuera del webroot, sin ejecución, con permisos mínimos y cifrado.
- Escaneo antimalware y cuarentena; parsing en worker aislado con límites CPU/memoria/tiempo y sin red por defecto.
- Descarga con `Content-Disposition`, MIME seguro y autorización tenant-scoped.
- Hash, estado de procesamiento y política de retención/borrado.

**Controles detectivos**

- Métricas/alertas de rechazos, timeouts, crashes de parser y malware.
- Auditoría de upload, descarga, cuarentena y borrado sin registrar contenido.

**Pruebas exigidas**

- EICAR en entorno de prueba, extensión/MIME discordante, zip bomb controlada, path traversal y PDF defectuoso.
- Acceso cruzado a objeto y descarga antes de superar cuarentena.

**Estado fase 10:** implementados magic/allowlist, límites de streaming/PDF/ZIP/CSV, storage UUID,
ClamAV fail-closed, download `ready+clean`, worker por versión con fencing y FTS bajo RLS. El
sandbox de contenedor y la reconciliación automática de huérfanos de storage quedan como gates de
infraestructura; no se afirma aislamiento de parser solo por usar timeouts Celery.

### T09 — Prompt injection, exfiltración y evidencia falsa

**Escenario:** documentos o señales ordenan al modelo ignorar políticas, exfiltrar contexto, inventar fuentes o producir una conclusión estratégica no sustentada.

**Controles preventivos**

- Tratar fuentes como datos no confiables y delimitar instrucciones del sistema frente al contenido recuperado.
- Mínimo contexto necesario, redacción de datos sensibles y adaptador de proveedor con política de datos.
- Salida estructurada validada; hechos, inferencias y recomendaciones separados.
- Evidencia obligatoria con IDs resolubles, confianza, prompt versionado y revisión de calidad/humana en acciones sensibles.
- Herramientas allowlist, sin acceso arbitrario a red/DB y sin ejecutar texto del modelo.
- No guardar como insight válido una salida que incumple schema o citas.

**Controles detectivos**

- `AIAuditLog` con hashes, fuentes, modelo, versión, latencia y coste estimado.
- Detector/evals de inyección y citas inexistentes; alertas por alta tasa de invalidación.
- Feedback humano y trazabilidad de promociones/decisiones.

**Pruebas exigidas**

- Corpus adversarial multilingüe con instrucciones incrustadas y datos canario.
- Citas inexistentes, evidencia de otro tenant, salida fuera de schema y tool call no permitido.
- Evals deterministas de groundedness y separación hecho/inferencia/recomendación.

### T10 — Abuso de `platform_super_admin`

**Escenario:** una cuenta de plataforma consulta datos privados sin necesidad, cambia roles o actúa en un tenant sin trazabilidad.

**Controles preventivos**

- Portal y permisos separados; mínimo privilegio, fresh login y MFA cuando se implemente.
- Acceso a datos de tenant solo tras selección explícita, permiso, motivo y ventana limitada.
- No impersonación silenciosa; banner/contexto inequívoco y prohibición de acciones ambiguas.
- Gestión de primer superadmin por CLI segura, sin contraseña hardcodeada.

**Controles detectivos**

- Audit trail inmutable/separado para acceso cross-tenant, rol, tenant objetivo, motivo y resultado.
- Notificación y revisión periódica de actividad privilegiada y memberships.

**Pruebas exigidas**

- Superadmin sin tenant/motivo/permiso; escalada de rol y sesión stale tras quitar privilegios.
- Confirmar que toda lectura cross-tenant deja evento correlacionado.

### T11 — Exposición de PostgreSQL o Redis

**Escenario:** servicios internos quedan publicados a Internet, usan credenciales débiles o permiten movimiento lateral.

**Controles preventivos**

- Red privada/loopback, sin puertos públicos; UFW y reglas cloud mínimas.
- TLS donde cruce hosts, credenciales únicas, ACL/password en Redis y roles DB de mínimo privilegio.
- Separación de usuario de migración y runtime; rotación y configuración endurecida.
- Nginx es el único punto público de aplicación; métricas/Flower restringidos.

**Controles detectivos**

- Escaneo externo de puertos, logs de autenticación y alertas por conexiones/orígenes anómalos.
- Auditoría periódica de Compose, sockets y reglas firewall.

**Pruebas exigidas**

- Escaneo desde Internet y desde red de aplicación.
- Verificar que runtime no puede realizar DDL y que Redis rechaza acceso anónimo/no autorizado.

### T12 — Fallo de backup/restore y ransomware

**Escenario:** backups ausentes, corruptos, accesibles desde el servidor comprometido o incapaces de restaurar relaciones, blobs y secretos necesarios.

**Controles preventivos**

- Backups automatizados, cifrados, versionados y fuera del servidor con credencial de escritura limitada.
- Retención, RPO/RTO y procedimiento de restore documentados.
- Incluir PostgreSQL y objetos/documentos; Redis es reconstruible y no contiene negocio autoritativo.
- Protección contra borrado/immutabilidad cuando el proveedor lo permita y custodia separada de claves.

**Controles detectivos**

- Verificación de ejecución, tamaño, checksum, antigüedad y alerta por backup fallido.
- Restore tests programados en entorno aislado y registro de resultados.

**Pruebas exigidas**

- Restauración completa y puntual desde snapshot representativo; validación de tenant isolation e integridad referencial.
- Simulación de pérdida del servidor/Redis y medición real de RPO/RTO.
- Prueba de que el host de aplicación no puede borrar todas las copias históricas.

### T13 — Autorización confiada al frontend o mass assignment

**Escenario:** ocultar un botón se considera permiso o un body incluye campos como `role`, `tenant_id`, `owner_id`, score o estado no editables.

**Controles preventivos**

- Autorización final siempre en Flask y schemas de entrada allowlist por operación.
- DTOs separados de modelos ORM; no deserialización directa a ORM.
- Campos derivados y transiciones de estado controlados por servicio de dominio.

**Controles detectivos**

- Auditoría de denegaciones y cambios de campos sensibles.
- Alertas por intentos repetidos de parámetros desconocidos/sensibles.

**Pruebas exigidas**

- Llamadas directas a API sin controles visuales y matriz RBAC.
- Bodies con campos extra, nested IDs, tenant/owner/role/version manipulados.

### T14 — Denegación de servicio y abuso de costes

**Escenario:** búsquedas, uploads, exports, Signal o IA agotan CPU, DB, workers o presupuesto del proveedor.

**Controles preventivos**

- Rate limits por ruta/actor/tenant, límites de payload/página y queries allowlist con índices.
- Cuotas y concurrencia por tenant para IA, documentos, informes y sync.
- Timeouts, circuit breakers, colas separadas y backpressure.
- Health/readiness sin operaciones costosas ni datos sensibles.

**Controles detectivos**

- Métricas de latencia, saturación, cola, errores y coste por tenant/modelo.
- Alertas de crecimiento de cola, retries, queries lentas y consumo anómalo.

**Pruebas exigidas**

- Load tests con límites, payloads máximos y dependencias lentas/caídas.
- Verificar aislamiento de colas para que IA no bloquee autenticación o API ordinaria.

## 5. Controles transversales y evidencia de implantación

Cada fase debe mantener una matriz control → código/configuración → prueba → responsable. Como mínimo:

- logs JSON redactados con `request_id`, `correlation_id`, `tenant_id`, actor y `job_id` cuando aplique;
- audit trail de negocio separado del log técnico;
- validación de entrada/salida y errores `application/problem+json` sin trazas;
- dependencias fijadas, escaneo de vulnerabilidades y parcheo con rollback;
- revisión de migraciones y constraints tenant-scoped;
- OpenAPI y cliente TS verificados en CI;
- headers TLS/CSP y configuración de cookie comprobados contra el entorno desplegado;
- pruebas negativas de tenant y permisos como gate obligatorio.

## 6. Riesgos residuales y supuestos

- `HttpOnly` reduce robo de cookie por XSS, pero XSS aún puede actuar con la sesión; CSP, sanitización y autorización siguen siendo esenciales.
- RLS es defensa en profundidad: una política incorrecta puede causar fuga o indisponibilidad y necesita tests propios.
- HMAC demuestra conocimiento del secreto, no la veracidad semántica de una señal; la evidencia y revisión humana siguen siendo necesarias.
- Idempotencia reduce duplicados, no garantiza exactamente una vez en sistemas distribuidos; los efectos deben diseñarse para replay.
- Un proveedor IA externo amplía la frontera de confianza y requiere decisión contractual de residencia, retención y uso de datos.
- Backups cifrados no sirven sin custodia y restore tests de claves.

## 7. Cuestiones pendientes

1. Clasificación de datos, residencia, retención y requisitos regulatorios por tenant.
2. RPO/RTO, proveedor de backups y política de inmutabilidad.
3. Proveedor de objetos/documentos, antivirus y sandbox de parsers.
4. MFA obligatoria y método para superadmin y roles sensibles.
5. Política de soporte cross-tenant, aprobación y notificación al tenant.
6. CSP final compatible con Next.js, visor de documentos y herramientas de observabilidad.
7. Contrato real de Signal Avanza: firma, rotación, rangos de red y retención de payload bruto.
8. Proveedores IA permitidos, regiones, no-training/retención y política de redacción.
9. KMS/secret manager y estrategia de rotación de claves de cifrado.
10. Objetivos de rate limit, cuota y presupuesto por tenant.
11. Política de `404` frente a `403` y nivel de detalle del audit trail visible al tenant.
12. Plan de pentest, gestión de vulnerabilidades y respuesta a incidentes antes de producción.

## 8. Gates antes de datos reales o producción

- No conectar datos reales mientras el frontend use `localStorage` como persistencia de negocio.
- No exponer login sin cookie/CSRF/rate limit/revocación probados.
- No habilitar un módulo tenant-scoped sin tests negativos de aislamiento.
- No habilitar uploads sin cuarentena, límites y parsing aislado.
- No habilitar Signal HTTP sin firma, replay protection e idempotencia.
- No persistir resultados IA como insights válidos sin schema, evidencia y auditoría.
- No desplegar PostgreSQL/Redis con puertos públicos.
- No aceptar producción sin backup y restore test exitosos, health checks y rollback documentado.

## 9. Evidencia añadida en fase 13

- Matriz dinámica de todas las tablas tenant-scoped: RLS `ENABLE/FORCE`, rol runtime sin contexto y
  matriz negativa API/RLS; el conjunto PostgreSQL/Redis quedó verde.
- Inventario automático de mutaciones protegidas por CSRF y detección de rutas Flask equivalentes.
  La revisión detectó y corrigió una colisión `PATCH signal-monitors` que evitaba el adaptador,
  outbox e idempotencia, además de dos colisiones GET documentales.
- Los monitores Signal exigen ahora `If-Match`, bloqueo de fila e idempotencia; la versión stale
  devuelve conflicto sin sobrescribir configuración.
- Headers API, no-store, CSP de API, HSTS con gate explícito, cabeceras web y CSP web report-only;
  HSTS y CSP enforcement web quedan pendientes de TLS/Nginx y nonce productivo.
- Métricas HTTP de baja cardinalidad, latencia, auth/rate limit y pool DB disponibles solo tras
  habilitación y bearer token; la agregación multi-worker y métricas de colas/proveedores requieren
  la plataforma de observabilidad de fase 14.
- Auditoría de dependencias corrigió `cryptography` 46.0.7 afectada por
  `GHSA-537c-gmf6-5ccf` a 48.0.1. npm audit, pip-audit, reglas Semgrep y scan de secretos quedaron
  sin hallazgos; Trivy/SBOM de imagen permanece como gate al construir la imagen productiva.
- DAST local no destructivo, axe/teclado/consola y baseline de carga local añadidos. La capacidad
  productiva, ZAP en staging, certificados, puertos externos y restore no se infieren de estas
  pruebas y permanecen bloqueantes para release.
