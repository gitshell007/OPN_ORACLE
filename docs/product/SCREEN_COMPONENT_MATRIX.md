# Matriz de pantallas y componentes

**Fecha de contrato:** 2026-07-11  
**Interfaz canónica:** Vector Command Center  
**Uso:** especificación de implementación para el prompt 12. Los nombres de componentes son contratos objetivo, no una afirmación de que ya existan.

Esta matriz cruza las pantallas exigidas por la arquitectura de información con el OpenAPI y las rutas Flask actuales. `Disponible`, `Parcial` y `Pendiente` tienen el significado definido en [ROUTE_PERMISSION_MATRIX.md](./ROUTE_PERMISSION_MATRIX.md). Una pantalla con API pendiente debe mostrar un estado honesto o permanecer fuera de navegación; no puede usar fixtures productivos, consultas directas a PostgreSQL ni Route Handlers de Next.js.

## Patrones compartidos

| Componente objetivo | Responsabilidad |
|---|---|
| `VectorAppShell` | Sidebar persistente/contraíble, cabecera global, skip link, tenant/workspace, breadcrumbs, búsqueda, Crear, notificaciones y usuario. Una sola definición de menú para desktop y móvil. |
| `DossierShell` | Header persistente del expediente y once pestañas en orden estable; `Más` accesible cuando no caben. |
| `TenantAdminShell` | Contexto del tenant y subnavegación solo para permisos administrativos efectivos. |
| `PlatformShell` | Apariencia diferenciada y aviso permanente “Contexto de plataforma”. |
| `ServerDataTable` | Búsqueda, sort, filtros, paginación, selección por teclado, columnas, densidad, URL state y vista móvil por cards/columnas esenciales. Los filtros solo se habilitan si el endpoint los soporta. |
| `InspectionDrawer` | Inspección sin perder tabla para señal, oportunidad, riesgo, actor, job y evidencia; restaura foco al cerrar. |
| `EntityCreateDialog` | Modal breve para expediente, tarea, reunión, promoción e invitación; validación accesible y bloqueo durante submit. |
| `DestructiveActionDialog` | Confirmación explícita; nombre escrito para archivo/eliminación de impacto alto; nunca `window.confirm`. |
| `JobProgress` | Estado durable, progreso, error saneado, correlation ID, cancel/retry condicionado y enlace a `/app/admin/audit?view=processes` o al recurso. |
| `EvidenceDrawer` | Extracto, clasificación, provenance, locator y apertura/descarga autorizada de fuente. |
| `ScoreBreakdown` | Score, componentes, pesos, explicación, fecha, evidencia, confianza y override humano; nunca solo color. |
| `PermissionGate` | Oculta/deshabilita acciones para UX. La API sigue siendo autoridad y los errores 403/404 se representan. |

### Estado común obligatorio

| Código | Estado / representación |
|---|---|
| S0 | `loading`: skeleton que conserva estructura, sin spinner de página completa. |
| S1 | `empty`: explicación y acción autorizada útil. |
| S2 | `no-results`: filtros activos, botón Limpiar filtros. |
| S3 | error recuperable: resumen, Reintentar y request ID cuando exista. |
| S4 | sesión expirada/401: estado claro y vuelta a login con `next` interno. |
| S5 | 403: panel de acceso insuficiente dentro del shell; no redirigir en bucle. |
| S6 | 404 recurso oculto/no accesible: “No disponible”, sin revelar tenant o existencia. |
| S7 | 409/412/428: conflicto de versión/precondición, recargar y comparar antes de sobrescribir. |
| S8 | 422: errores ligados a campos o regla de dominio. |
| S9 | 429: respetar y mostrar `Retry-After`. |
| S10 | trabajo `queued/running/failed/succeeded/cancelled`: `JobProgress`, polling cancelable y feedback persistente. |
| S11 | expediente archivado: banner de solo lectura y acciones mutables ocultas/deshabilitadas. |
| S12 | dependencia degradada: banner discreto solo si afecta a la tarea; no inventar datos. |

Todas las rutas autenticadas prueban además S4 y ausencia de secretos/tokens en `localStorage`/`sessionStorage`. Todas las tablas críticas prueban teclado, nombre accesible, foco visible, S0–S3, 403 y responsive 390 × 844 sin scroll horizontal como única solución.

## Shell global y utilidades persistentes

| Superficie | Datos / componentes | Acciones y permisos | Estados | E2E mínimo |
|---|---|---|---|---|
| Cabecera global | Tenant/workspace de `/auth/me`; breadcrumbs desde registro tipado; `GlobalSearch`; `CommandPalette`; `CreateMenu`; `NotificationBell`; `UserMenu` | Cambiar tenant con `/auth/switch-tenant`; limpiar toda caché tenant-scoped antes de pintar el nuevo contexto. Crear muestra solo acciones completables por permiso y por endpoint disponible. | S0, S3, S4, S9, S12 | `SHELL-01`: cambiar tenant no deja datos anteriores. `SHELL-02`: `Ctrl/⌘K`, Escape, trap/restauración de foco. `SHELL-03`: menú Crear no ofrece acciones sin permiso/backend. |
| Sidebar/drawer móvil | Diez destinos principales agrupados; Administración inferior; Cuenta desde usuario; badge de señales/notificaciones solo desde recuento real | Persistir solo preferencia visual no sensible; orden estable al ocultar entradas. Drawer con nombre accesible y cierre por Escape/backdrop/botón. | S4, S5 | `SHELL-04`: navegación completa por teclado desktop/tablet/móvil. `SHELL-05`: viewer no ve mutaciones; auditor conserva Documentos/Auditoría. |
| Búsqueda global | Objetivo: expedientes, señales, oportunidades, riesgos, actores, documentos, informes y reuniones. Backend actual `GET /search` solo cubre documentos/chunks. | Navegar al resultado; no almacenar contenido sensible localmente. | S0–S3, S9; estado “Búsqueda integral pendiente” mientras falte API | `SHELL-06`: no mezclar búsqueda documental con búsqueda integral; resultado autorizado abre deep link y cross-tenant no aparece. |

## Pantallas globales de producto

| Ruta | Propósito y fuente de datos | Componente; campos/filtros | Acciones / overlays y permisos | Estados específicos | E2E mínimo |
|---|---|---|---|---|---|
| `/app` | Command center. API **parcial**: `/dossiers`, `/notifications`, `/reports`, `/jobs`; faltan agregados de cambios/oportunidades/riesgos/reuniones/tareas. | `CommandCenter`; expedientes con atención, señales priorizadas, oportunidades, riesgos, reuniones, tareas y máximo 5 cambios. Cada cifra es enlace a filtro real. | Accesos contextuales y `CreateMenu`; cada bloque se omite por permiso, no se sustituye por cero engañoso. | S0/S1/S3 por bloque, S12; placeholder honesto para agregados pendientes. | `HOME-01`: cada KPI navega a URL filtrada. `HOME-02`: auditor/viewer solo ven módulos autorizados. `HOME-03`: fallo parcial no inutiliza toda la página. |
| `/app/dossiers` | Inventario. API **disponible**, salvo filtros sector/geografía/riesgo y export de expedientes. | `DossierTable`; nombre, tipo, estado, propietario, oportunidad, riesgo, señales nuevas, próximo hito, actualización, acciones. Backend: search/status/type/owner/date/score/sort/page/selected IDs; filtros extra quedan deshabilitados y etiquetados pendientes. | Abrir fila; `CreateDossierDialog` (`dossier.write`); editar (`dossier.write`); pausar; `ArchiveDossierDialog` (`dossier.archive`). No mostrar Exportar porque no existe dataset. | S0–S9; S11 por fila archivada. | `DOS-G-01`: filtros/sort/página sobreviven URL y request. `DOS-G-02`: crear añade fila. `DOS-G-03`: viewer sin acciones; conflicto ETag recuperable. |
| `/app/changes` | Máximo 5–10 cambios priorizados. API **pendiente**: hace falta read model, marcar revisado y asociación con evidencia/acción. | `ChangesTable`; qué, expediente, tipo, por qué importa, evidencia, confianza, fecha, recomendación. Filtros fecha/expediente/tipo/relevancia/revisado. | Marcar revisado; crear tarea; abrir contexto/evidencia. No habilitar hasta existir contrato. | S0–S5 y estado explícito de función no disponible, sin feed fixture. | `CHG-01` pendiente de API: listado finito, marcar revisado persiste y crear tarea conserva contexto. |
| `/app/signals` | Inbox global. API **parcial**: detalle/review/promote existen; listado global falta. | `SignalTable`; estado, título, expedientes, tipo/fuente, relevancia, confianza, credibilidad, publicación, ingesta, revisor. Filtros equivalentes pendientes del listado global. | `SignalDrawer`; revisar/descartar (`signal.review`), promover (`signal.promote`) mediante `PromoteSignalDialog`, retriage (`ai.execute`), crear tarea/asociar/corregir solo al existir endpoint exacto. | S0–S10; estado global no disponible. | `SIG-G-01` pendiente: revisar actualiza fila y badge. `SIG-G-02`: promoción idempotente crea oportunidad/riesgo. `SIG-G-03`: viewer inspecciona pero no muta. |
| `/app/opportunities` | Cartera agregada. API **parcial**: listados por dossier y detalle existen; global falta. | `OpportunityTable` por defecto y board opcional; oportunidad, expediente, tipo, estado, total, fit, valor, urgencia, confianza, owner, deadline, siguiente acción. | `OpportunityDrawer`, `ScoreBreakdown`; crear/editar/transición con `opportunity.write`; evidencia/actores/riesgos bloqueantes. Export CSV disponible si `export.create`. | S0–S10; global no disponible; deadline no se comunica solo con color. | `OPP-G-01` pendiente: filtros globales y deep link. `OPP-G-02`: editar con ETag/conflicto. `OPP-G-03`: export respeta filtros/columnas y permisos. |
| `/app/risks` | Registro agregado. API **parcial**: listados por dossier y detalle existen; global falta. | `RiskTable` + matriz secundaria; riesgo, expediente, categoría, estado, score, impacto, probabilidad, velocidad, controlabilidad, owner, revisión, mitigación. | `RiskDrawer`, `ScoreBreakdown`; editar mitigación, aceptar/cerrar/reabrir según transiciones y `risk.write`; export autorizado. | S0–S11; matriz tiene alternativa tabular/leyenda. | `RISK-G-01` pendiente: críticos de varios expedientes. `RISK-G-02`: viewer no edita. `RISK-G-03`: matriz y tabla representan el mismo conjunto. |
| `/app/actors` | Directorio tenant-global. API **disponible** con composición para roles/expedientes. | `ActorTable` + `ActorGraph`; nombre, tipo, organización, roles, dossiers, influencia, accesibilidad, alineamiento, actividad, confianza de identidad. Search/type/date/sort/page; filtros relacionales pueden exigir composición. | `ActorDrawer`; crear/editar/merge/relación con `actor.write`. Grafo con búsqueda, filtros, leyenda, zoom, foco y distinción inferida/confirmada. | S0–S9; grafo degradado conserva tabla. | `ACT-G-01`: actor compartido muestra dos dossiers. `ACT-G-02`: teclado accede al equivalente tabular. `ACT-G-03`: merge requiere motivo y no cruza tenant. |
| `/app/meetings` | Agenda global. API **parcial**: listado solo por dossier. | `MeetingTable` y calendario ligero opcional; fecha/hora, título, dossier, participantes, objetivo, briefing, owner, seguimiento. Filtros fecha/dossier/estado/owner pendientes del global. | `CreateMeetingDialog`, `MeetingDrawer`; generar/abrir briefing, notas, tareas posteriores, completar/cancelar según `meeting.write`. | S0–S10; global no disponible. | `MEET-G-01` pendiente: crear y ver en agenda. `MEET-G-02`: generar briefing muestra job y abre resultado. `MEET-G-03`: zona horaria correcta. |
| `/app/tasks` | Trabajo personal/equipo. API **parcial**: listado solo por dossier. | `TaskTable`; tarea, dossier, origen, owner, prioridad, estado, límite, creación. Segmentos Mis tareas/Equipo/Vencidas/Próximas/IA/Sin asignar. | `CreateTaskDialog`, edición/transiciones con `task.write`; distinguir sugerencia IA de decisión humana; export CSV autorizado. | S0–S10; global no disponible; vencimiento no solo color. | `TASK-G-01` pendiente: completar tarea actualiza segmento. `TASK-G-02`: origen IA etiquetado. `TASK-G-03`: viewer no muta ni ve controles falsos. |
| `/app/reports` | Biblioteca global. API **disponible**: `/reports`, `/report-templates`. | `ReportTable`; título, tipo/template, dossier, versión, estado, solicitante, fecha, evidencias, acciones. Filtros backend search/status/template/page; otros filtros no se simulan. | `GenerateReportDialog` (`report.generate`), abrir, retry, revisión, publicar por permisos; export CSV y `JobProgress`. | S0–S10; capability PDF explícita; `failed` con error saneado. | `REP-G-01`: generar devuelve job y aparece en tabla. `REP-G-02`: filtros server-side. `REP-G-03`: analyst no publica; admin sí. |
| `/app/reports/[reportId]` | Informe completo, secciones y citas. API **disponible**. | `ReportViewer`; metadata/version/clasificación, hechos/inferencias/recomendaciones, confianza, preguntas, source index y artefactos. | `EvidenceDrawer`; revisar/comentar (`report.review`), revisión nueva, publicar (`report.publish`), retry (`report.generate`), link/descarga (`report.read`). Página completa, no modal. | S0, S3–S8, S10; superseded/read-only; PDF no habilitado se explica. | `REP-D-01`: cita abre evidencia exacta. `REP-D-02`: publicar exige rol y versión. `REP-D-03`: enlace temporal no sirve otra sesión/usuario ni tras expirar. |
| `/app/notifications` | Inbox propio. API **disponible**. | `NotificationCenter`; severidad + texto, tipo, título, recurso, fecha, read/dismiss. Paginación; filtros locales solo sobre página o se omiten hasta soporte backend. | Abrir solo link interno validado; read/read-all/dismiss; enlace a preferencias. | S0–S6/S9; expiradas y no visibles no se presentan. | `NOT-01`: leer y descartar persisten. `NOT-02`: URL externa/malformada no navega. `NOT-03`: badge coincide con unread_count. |
| `/app/exports` | Historial propio de exportaciones. API **disponible**. | `ExportTable`; dataset, estado, solicitado, filas, expiración, error saneado. Paginación; no inventar filtros no soportados. | `ExportRequestDialog` desde tabla origen; abrir estado; download-link al estar ready. Dataset revalida permiso (`audit.export` para audit). | S0–S10; `expired`/410 ofrece regenerar, no descargar. | `EXP-01`: CSV neutraliza fórmula. `EXP-02`: job progresa y descarga autorizada. `EXP-03`: no ve export ajeno ni dataset cuyo permiso se revocó. |
| `/app/exports/[exportId]` | Estado de una exportación y descarga. API **disponible**. | `ExportDetail`; intención, columnas/filtros, estado, filas, checksum/expiración y job. | Descargar mediante enlace temporal; regenerar crea nueva intención explícita. | S0, S3–S6, S9/S10 y 410. | `EXP-D-01`: refresh conserva estado durable. `EXP-D-02`: link expira y está ligado a tenant/usuario/sesión/fingerprint. |

## Pantallas del expediente

Todas usan `DossierShell`, conservan `dossierId` al cambiar de pestaña y muestran S6 para un recurso inaccesible. El header contiene título, tipo, estado, owner, oportunidad, riesgo, señales nuevas, actualización y acción contextual; no calcula autoridad en el cliente.

| Ruta | Propósito / API | Componente; campos y filtros | Acciones / overlays y permisos | Estados específicos | E2E mínimo |
|---|---|---|---|---|---|
| `/app/dossiers/[dossierId]` | Resumen vivo. API **disponible**. | `DossierOverview`; living summary, objetivo, hipótesis, cambios, top oportunidades/riesgos, actores, siguiente acción, hitos, decisiones, evidencia/confianza y salud Signal. | Editar/contexto con `dossier.write`; ejecutar agente con `ai.execute`; abrir tiles en pestaña filtrada. | S0–S12; sin summary muestra crear/generar solo si autorizado. | `DOS-01`: header/pestañas mantienen contexto. `DOS-02`: tile abre filtro contextual. `DOS-03`: archived es solo lectura. |
| `/app/dossiers/[dossierId]/signals` | Inbox contextual. API **disponible**. | `SignalTable` + `SignalDrawer`; mismas columnas globales, ya filtradas al dossier. Backend search/status/type/date/score si el modelo lo admite; no fingir filtros ausentes. | Revisar/descartar/promover/retriage por permisos; promoción pide título, dossier, owner y siguiente acción. | S0–S11. | `SIG-01`: review y promote reales. `SIG-02`: señal N:M conserva dossier correcto. `SIG-03`: usuario sin write solo inspecciona. |
| `/app/dossiers/[dossierId]/opportunities` | Oportunidades contextuales. API **disponible**. | `OpportunityTable` + drawer/score; columnas de cartera y filtros status/type/owner/date/score/search soportados. | Crear/editar/transicionar (`opportunity.write`), vincular evidence/actor/signal, exportar dataset filtrado. | S0–S11, S7 ETag. | `OPP-01`: CRUD/scoring explicado. `OPP-02`: evidence abre origen. `OPP-03`: export queda dossier-scoped. |
| `/app/dossiers/[dossierId]/risks` | Riesgos contextuales. API **disponible**. | `RiskTable` + matriz secundaria + score; filtros soportados. | Crear/editar mitigación/transición y vínculos con `risk.write`; exportar. | S0–S11, S7. | `RISK-01`: crear/editar y conservar cálculo. `RISK-02`: transición inválida 422 útil. `RISK-03`: viewer read-only. |
| `/app/dossiers/[dossierId]/actors` | Actores/relaciones del dossier. API **disponible**. | `DossierActorTable` + grafo; roles, influencia, relevancia, fuerza, acceso, alineamiento, priority, evidencia. | Asociar actor, editar contexto y relaciones (`actor.write`); `ActorDrawer`; grafo siempre complementario. | S0–S11, identidad ambigua explícita. | `ACT-01`: asociar actor existente no duplica canonical. `ACT-02`: relación inferida distinguible. `ACT-03`: tabla usable sin grafo. |
| `/app/dossiers/[dossierId]/meetings` | Reuniones y briefings. API **disponible**. | `MeetingTable`; fecha, participantes, objetivo, estado, briefing y seguimiento. Filtros nested soportados limitados. | Crear/editar/completar/cancelar; `MeetingDialog`; generar briefing y ver `JobProgress`; tareas posteriores. | S0–S11. | `MEET-01`: crear y completar. `MEET-02`: briefing con evidencias. `MEET-03`: timezone y foco correctos. |
| `/app/dossiers/[dossierId]/tasks` | Acciones contextuales. API **disponible**. | `TaskTable`; título, origen, owner, prioridad, estado, límite, creación. Search/status/owner/date. | Crear/editar/cambiar estado (`task.write`); `TaskDialog`; exportar. | S0–S11, S7. | `TASK-01`: crear/completar. `TASK-02`: IA vs humano. `TASK-03`: tarea ajena/no accesible no se enumera. |
| `/app/dossiers/[dossierId]/documents` | Upload, documentos, búsqueda y evidence. API **disponible**. | `DocumentTable`, `DocumentUpload`, `DossierSearch`; filename, media type, estado, clasificación, tamaño, versión, uploader/fecha. Filtros de búsqueda document/type/date según API. | Cargar/reprocesar/soft-delete/create evidence (`documents.manage`); descargar/ver evidence (`documents.read`); `EvidenceDrawer`. | S0–S12; processing/quarantine/failed/deleted; upload progress. | `DOC-01`: upload→job→ready. `DOC-02`: cita abre locator. `DOC-03`: MIME/path/cross-tenant y quarantine bloqueados. |
| `/app/dossiers/[dossierId]/reports` | Informes contextualizados. API **disponible**. | `ReportTable` filtrada al dossier; columnas y filtros status/page. | Generar, abrir, retry y export según permisos; `GenerateReportDialog`; `JobProgress`. | S0–S11. | `REP-01`: generación idempotente. `REP-02`: fallo/retry visible. `REP-03`: dossier archived no genera. |
| `/app/dossiers/[dossierId]/decisions` | Memoria decisional. API **disponible**. | `DecisionTable`; decisión, estado, rationale, autor/owner, fecha, evidencia. Search/status/date. | Crear, aprobar/rechazar/supersede y vincular evidence (`task.write`); `DecisionDialog`. | S0–S11, transición 422. | `DEC-01`: crear y aprobar con evidencia. `DEC-02`: viewer no muta. `DEC-03`: historial no se sobrescribe. |
| `/app/dossiers/[dossierId]/settings` | General, objetivos/hipótesis, watchlists/Signal, alertas, colaboradores, plantillas, auditoría y archivo. API **parcial**. | `DossierSettings`; formularios por sección; `ObjectiveTable`, `HypothesisTable`, `WatchlistEditor`, `MonitorHealth`, `AlertPolicyForm`, `CollaboratorTable`, `DossierAuditTable`. Plantillas de dossier y borrado físico no tienen API. | Guardar con permiso específico; sync/pausa monitor; política heredada; colaboradores; `ArchiveDossierDialog`; audit read-only. Credenciales Signal nunca aquí. | S0–S12; dirty-state; inherited; degraded; archived; 409 version. | `SET-01`: cambiar watchlist/monitor y ver health. `SET-02`: herencia de alertas. `SET-03`: último acceso/owner protegido. `SET-04`: auditor solo ve secciones autorizadas. |

## Cuenta

| Ruta | Propósito / API | Componente; campos | Acciones / permisos | Estados | E2E mínimo |
|---|---|---|---|---|---|
| `/app/account` | Landing/redirect a Perfil. Routing sin API propia. | `AccountShell` | Redirigir de forma estable, sin flash de otra sección. | S4 | `ACC-00`: navegación y deep links de las cinco secciones. |
| `/app/account/profile` | Perfil. API **parcial**: `/auth/me` solo lectura. | `ProfileForm`; nombre, email, rol efectivo, tenant/workspace. Campos no editables hasta PATCH real. | Guardar queda ausente, no decorativo. | S0/S3/S4; estado “edición no disponible”. | `ACC-01`: identidad viene de `/me`; no muestra guardar falso. |
| `/app/account/security` | Cambio de contraseña. API **disponible**. | `PasswordChangeForm`; contraseña actual/reautenticación, nueva y confirmación, policy visible. | Reautenticar y cambiar; no persistir valores; F5. | S3–S5/S8/S9; éxito invalida/rota según backend. | `ACC-02`: recent-auth, policy, éxito/error y campos limpiados. |
| `/app/account/sessions` | Sesiones server-side. API **disponible**. | `SessionTable`; dispositivo/browser, última actividad, creada, expiración, tenant, actual. | Revocar una / otras; `SessionRevokeDialog`; F5. | S0–S9; sesión desaparecida idempotente. | `ACC-03`: revocar otra sesión; actual claramente marcada; no session ID expuesto. |
| `/app/account/preferences` | Idioma, timezone, densidad, tema y accesibilidad. API **pendiente**. | `PreferencesForm`; no usar repository mock/localStorage como estado productivo. | Guardar oculto/deshabilitado con explicación hasta API. | Estado honesto pendiente; S4. | `ACC-04` pendiente: guardar, recargar y aplicar densidad/nav por usuario. |
| `/app/account/notifications` | Preferencias por tipo/canal, quiet hours y digest. API **disponible**. | `NotificationPreferencesForm`; tipos, in-app/email, digest daily/weekly/off, timezone, quiet start/end; alertas de seguridad bloqueadas. | Guardar (`notifications.manage`), restablecer a valores del servidor. | S0/S3–S5/S8/S9; dirty/saved. | `ACC-05`: persistencia, quiet hours y seguridad no desactivable. |

## Administración del tenant

| Ruta | Propósito / API | Componente; campos/filtros | Acciones / permisos | Estados | E2E mínimo |
|---|---|---|---|---|---|
| `/app/admin` | Landing por capacidades. API **parcial** por composición. | `AdminLanding`; tiles solo de organization/members/roles/workspaces/integrations/audit/jobs autorizados. | Navegar; no mostrar áreas pendientes como operativas. | S0/S3–S5. | `ADM-00`: owner ve todo soportado; auditor solo Auditoría; editor no ve entrada. |
| `/app/admin/organization` | Organización y defaults. API **parcial**: solo alert-policy. | `OrganizationForm`; objetivo nombre/slug/timezone/idioma/estado + `TenantAlertPolicyForm`. Campos sin API quedan read-only/pendientes. | Guardar policy (`tenant.settings.manage`); no branding/secrets ficticios. | S0/S3–S5/S7/S8. | `ADM-01`: actualizar umbrales; otros campos no envían requests inexistentes. |
| `/app/admin/members` | Members/invitations. API **disponible**. | `MemberTable`; persona/email, estado, roles, última actividad/invitación. Filtros/paginación según endpoint; no fingir server-side si no están. | `InviteMemberDialog`; resend, roles, suspend/remove; F5; protección último owner. | S0–S9; pending invite; last-owner conflict. | `ADM-02`: invitar, reenviar, cambiar rol y retirar; no platform roles. |
| `/app/admin/roles` | Matriz de roles. API **parcial**: GET read-only. | `RolePermissionMatrix`; rol, descripción, permisos agrupados. | Sin CRUD hasta endpoint; asignación de role se hace en Members. | S0–S5; read-only explícito. | `ADM-03`: permisos coinciden con backend; no controles de edición decorativos. |
| `/app/admin/workspaces` | Workspaces y membresía. API **pendiente**. | `WorkspaceTable`; nombre, estado, miembros, dossiers, actualización. | Crear/archivar/asignar no se habilitan. | Estado de función pendiente. | `ADM-04` pendiente: CRUD, último admin y aislamiento tenant. |
| `/app/admin/integrations` | Catálogo. API **parcial**: solo Signal. | `IntegrationCatalog`; proveedor, estado, última comprobación/sync, incidencias. | Abrir Signal; no mostrar conectores no implementados como disponibles. | S0–S5/S12. | `ADM-05`: estado Signal real; catálogo no inventa salud. |
| `/app/admin/integrations/signal-avanza` | Gestión Signal. API **disponible**. | `SignalAdmin`; conexión, credencial siempre enmascarada, health, sync/error, monitores activos. | Crear/test/rotate/disable (F5), reconcile; no secret en DOM/respuestas. | S0–S9/S10/S12; fail-closed HTTP real. | `ADM-06`: test/rotate/disable/reconcile; secret nunca aparece; analyst 403. |
| `/app/admin/audit` | Auditoría tenant y procesos. API **disponible**. | `AuditTable` y vista `Procesos`; usuario/actor, acción, resource, fechas, resultado, tipo de job, progreso, creado/actualizado y fallos destacados. | Abrir contexto; export audit solo `audit.export` y watermark; `/app/admin/jobs` redirige a `?view=processes`. | S0–S10; stale/retry/cancel. | `ADM-07/08`: auditor lee/exporta; procesos visibles con fecha; scope de `/jobs` sigue por solicitante/dossier hasta decisión RBAC. |

## Plataforma

| Ruta | Propósito / API | Componente; campos/filtros | Acciones | Estados | E2E mínimo |
|---|---|---|---|---|---|
| `/platform` | Landing global. API **pendiente**. | `PlatformOverview`; no mostrar métricas inventadas. Puede redirigir temporalmente a Tenants. | Navegar a superficies disponibles. | S4/S5 y estado pendiente. | `PLAT-00`: no superadmin recibe 403; superadmin no ve negocio tenant. |
| `/platform/tenants` | Tenants. API **disponible**. | `PlatformTenantTable`; nombre/slug, estado, usuarios, fechas/salud solo si respuesta real; paginación/filtros soportados. | `CreateTenantDialog`; abrir detalle; recent-auth para crear. | S0–S9. | `PLAT-01`: listar/crear; usuario tenant 403. |
| `/platform/tenants/[tenantId]` | Administración de tenant sin datos privados. API **disponible**. | `PlatformTenantDetail`; metadata, estado y audit técnico permitido. | Patch, suspend/reactivate, invite owner; F5; sin impersonation. | S0–S9; confirmación reforzada. | `PLAT-02`: suspend/reactivate/invite; ningún fetch de dossiers. |
| `/platform/users` | Usuarios globales. API **disponible**. | `PlatformUserTable`; identidad/estado/platform role y memberships resumidas solo según schema. | Lectura y navegación segura; sin edición si no hay endpoint. | S0–S5/S9. | `PLAT-03`: listado sin PII innecesaria; no controles de edición falsos. |
| `/platform/jobs` | Colas/jobs globales. API **pendiente**. | `PlatformJobTable`; campos objetivo saneados, sin payload. | Ninguna hasta contrato protegido. | Estado pendiente. | `PLAT-04` pendiente: scope global, secretos redactados y retry autorizado. |
| `/platform/integrations` | Salud global. API **pendiente**. | `PlatformIntegrationHealth`; proveedor, estado agregado, backlog/latencia/error safe. | Ninguna credencial ni acceso tenant implícito. | Estado pendiente/S12. | `PLAT-05` pendiente: datos agregados sin revelar tenants/secretos. |
| `/platform/audit` | Auditoría global. API **disponible**. | `PlatformAuditTable`; actor, tenant, acción, resource, resultado, fecha, request/correlation ID. | Filtrar/abrir metadata segura. No existe export global específico documentado. | S0–S6/S9. | `PLAT-06`: solo superadmin; filtro tenant no abre negocio. |
| `/platform/system` | Salud técnica protegida. API **pendiente**; health live/ready no basta. | `PlatformSystemHealth`; API, DB, Redis, workers/beat y storage solo si contrato saneado. | Refresh manual; enlaces a runbook, no secretos. | S0/S3/S5/S12. | `PLAT-07` pendiente: degradación real, endpoints protegidos y sin detalles explotables. |

## Pantallas públicas de autenticación

| Ruta | Componente / campos | Acciones y API | Estados | E2E mínimo |
|---|---|---|---|---|
| `/login` | `LoginForm`; email, contraseña, mostrar/ocultar, autofill/password manager | `/auth/csrf`, `/auth/login`; forgot password; `next` solo interno | loading, anti-enumeración, 429/Retry-After, error genérico | `AUTH-01`: éxito/fallo/rate limit; rechazo de `next` externo; teclado/autofill. |
| `/forgot-password` | `ForgotPasswordForm`; email | `/auth/forgot-password` | mismo éxito exista o no la cuenta; 429 | `AUTH-02`: anti-enumeración y no token en URL/log/storage. |
| `/reset-password` | `ResetPasswordForm`; nueva, confirmación, policy | `/auth/reset-password` | token usado/caducado seguro; 422 | `AUTH-03`: cambio válido, token one-time, limpieza de formulario. |
| `/accept-invitation` | `InvitationForm`; identidad contextual mínima y password si procede | `/auth/accept-invitation` | token usado/caducado; tenant suspendido | `AUTH-04`: aceptación, siguiente paso y no persistencia del token. |

## Flujos E2E transversales de aceptación

Además de los casos por pantalla, el prompt 12 debe cubrir como mínimo:

1. `FLOW-01`: encontrar expediente → abrir señales → inspeccionar evidencia → promover a oportunidad.
2. `FLOW-02`: localizar riesgos críticos de varios expedientes cuando exista listado global; hasta entonces el test queda bloqueado por API, no sustituido con fixtures.
3. `FLOW-03`: actor compartido entre dos expedientes en tabla y grafo accesible.
4. `FLOW-04`: crear reunión → generar briefing → registrar seguimiento/tarea.
5. `FLOW-05`: generar informe → revisar/publicar según rol → abrir cita → descargar artefacto.
6. `FLOW-06`: cambiar tenant y demostrar vaciado de caché/UI antes de la nueva carga.
7. `FLOW-07`: revocar sesión y comprobar invalidación real.
8. `FLOW-08`: administrar miembro y proteger último owner.
9. `FLOW-09`: test/reconcile de Signal sin exponer credenciales.
10. `FLOW-10`: consultar y exportar auditoría como auditor; editor obtiene 403.
11. `FLOW-11`: matrices de rol para viewer, analyst, admin, auditor y platform superadmin.
12. `FLOW-12`: desktop 1440 × 900, tablet 1024 × 768 y móvil 390 × 844; cero errores relevantes de consola, navegación por teclado y chequeo a11y automático más revisión manual.

## Dependencias backend explícitas para el prompt 12

| Necesidad de pantalla | Contrato que falta |
|---|---|
| Inicio y Qué ha cambiado | Read models agregados y acción de marcar cambio revisado. |
| Listados globales | `GET` global server-side de signals, opportunities, risks, meetings y tasks con filtros/sort/page. |
| Command palette integral | Búsqueda autorizada multi-entidad; la búsqueda actual es documental. |
| Perfil y preferencias | `PATCH` de perfil y `GET/PATCH UserSettings` durable. |
| Organización y workspaces | API del tenant actual y CRUD/memberships de workspace. |
| Roles editables | CRUD de roles/permisos, solo si producto confirma roles custom. |
| Admin jobs | Decisión RBAC y, si procede, permiso dedicado; hoy usa `dossier.read` + resource scope. |
| Plataforma completa | Agregados protegidos de overview, jobs, integraciones y system health. |

La implementación frontend debe priorizar primero las pantallas con API **Disponible**, integrar las **Parciales** solo hasta donde alcance el contrato real y dejar fuera de navegación cualquier acción **Pendiente** que no pueda completarse.
