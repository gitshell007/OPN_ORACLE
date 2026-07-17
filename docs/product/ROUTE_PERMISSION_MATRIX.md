# Matriz de rutas y permisos

**Fecha de contrato:** 2026-07-11  
**Interfaz canónica:** `CANONICAL_UI=vector`  
**Ámbito:** arquitectura objetivo que debe completar el prompt 12; no implica que todas las páginas o API estén implementadas hoy.

La autorización final pertenece a Flask. La visibilidad de navegación y los `PermissionGate` solo mejoran la experiencia. Los roles indicados son los defaults sembrados por `platform/rbac.py`; un rol custom o una modificación posterior se evalúa por permisos efectivos, no por el nombre del rol.

## Leyenda

### Roles

| Código | Rol de tenant |
|---|---|
| O | `owner` |
| A | `admin` |
| E | `editor` |
| N | `analyst` |
| V | `viewer` |
| U | `auditor` |
| P | `platform_superadmin`; corresponde a `User.platform_role == "super_admin"` en el backend actual |

`P` no recibe permisos de negocio de un tenant automáticamente. Para datos privados sigue siendo necesario seleccionar un tenant, aportar motivo, tener autorización explícita y generar auditoría.

### Estado de API

| Estado | Significado |
|---|---|
| **Disponible** | El contrato está en `docs/api/openapi.json` y existe implementación Flask. |
| **Parcial** | Existen operaciones útiles, pero falta una agregación, mutación, filtro o autorización necesaria para completar la pantalla. |
| **Pendiente** | No existe hoy un endpoint Flask equivalente. La fase 12 no debe sustituirlo con fixtures ni lógica Node. |

### Respuesta de acceso

| Código | Comportamiento |
|---|---|
| F1 | Usuario anónimo: `401`; conservar solo un `next` interno seguro y enviar a `/login`. |
| F2 | Usuario autenticado sin permiso: estado 403 dentro del shell, explicación y retorno seguro. La entrada se oculta, sin recolocar caóticamente el resto del menú. |
| F3 | Falta de acceso al expediente/recurso, ID ajeno o cross-tenant: el backend responde `404` para no revelar existencia; la UI muestra “No disponible”, no “Prohibido”. |
| F4 | Plataforma sin rol `super_admin`: 403 diferenciado, sin cargar datos ni intentar cambiar de tenant. |
| F5 | Acción sensible sin autenticación reciente: `401 recent_auth_required`; pedir contraseña y reintentar solo por acción explícita. |

## Permisos por rol predeterminado

| Permiso | O | A | E | N | V | U |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| `dossier.read` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `dossier.write` | ✓ | ✓ | ✓ | — | — | — |
| `dossier.archive` | ✓ | ✓ | ✓ | — | — | — |
| `signal.read` | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| `signal.review`, `signal.promote` | ✓ | ✓ | ✓ | ✓ | — | — |
| `opportunity.read`, `risk.read` | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| `opportunity.write`, `risk.write` | ✓ | ✓ | ✓ | ✓ | — | — |
| `actor.read` | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| `actor.write` | ✓ | ✓ | ✓ | — | — | — |
| `meeting.read` | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| `meeting.write` | ✓ | ✓ | ✓ | — | — | — |
| `task.read` | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| `task.write` | ✓ | ✓ | ✓ | ✓ | — | — |
| `report.read` | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| `report.generate`, `report.review` | ✓ | ✓ | ✓ | ✓ | — | — |
| `report.publish` | ✓ | ✓ | — | — | — | — |
| `documents.read` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `documents.manage` | ✓ | ✓ | ✓ | ✓ | — | — |
| `ai.execute`, `ai.review` | ✓ | ✓ | ✓ | ✓ | — | — |
| `notifications.read`, `notifications.manage` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `export.create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `audit.read`, `audit.export` | ✓ | ✓ | — | — | — | ✓ |
| `tenant.users.manage`, `tenant.settings.manage`, `tenant.integrations.manage` | ✓ | ✓ | — | — | — | — |

## Rutas públicas y de autenticación

| Ruta | Etiqueta / finalidad | Permiso | Roles | 403 / visibilidad | API principal | Estado API |
|---|---|---|---|---|---|---|
| `/login` | Acceso con sesión opaca | Público; solo anónimo | Todos | Un usuario autenticado va a una ruta segura | `POST /api/v1/auth/login`, `GET /api/v1/auth/csrf` | Disponible |
| `/forgot-password` | Solicitar recuperación anti-enumeración | Público | Todos | No aplica | `POST /api/v1/auth/forgot-password` | Disponible |
| `/reset-password` | Establecer contraseña con token de un solo uso | Público | Todos | Token inválido/caducado muestra estado seguro | `POST /api/v1/auth/reset-password` | Disponible |
| `/accept-invitation` | Aceptar invitación y activar membership | Público | Todos | Token inválido/caducado muestra estado seguro | `POST /api/v1/auth/accept-invitation` | Disponible |

## Rutas globales de producto

| Ruta | Etiqueta / finalidad | Permiso de entrada | Roles default | 403 / navegación | API principal consumida | Estado API |
|---|---|---|---|---|---|---|
| `/app` | Inicio; situación global y siguiente mejor acción | `dossier.read`; cada módulo comprueba su permiso | O, A, E, N, V, U | F1/F2; primer destino del grupo Trabajo estratégico | `GET /dossiers`, `/notifications`, `/reports`, `/jobs`; faltan agregados de oportunidades, riesgos, reuniones, tareas y cambios | Parcial |
| `/app/dossiers` | Inventario de expedientes | `dossier.read` | O, A, E, N, V, U | F1/F2; menú principal. Crear requiere `dossier.write` | `GET/POST /dossiers`, `PATCH /dossiers/{id}`, `POST /dossiers/{id}/archive` | Disponible; filtros sector/geografía/riesgo y export de expedientes pendientes |
| `/app/changes` | Cambios priorizados, no feed infinito | `dossier.read`; módulos por permiso | O, A, E, N, V, U | F1/F2; menú principal; badge solo con recuento real | No existe listado/read model de cambios ni endpoint para marcar revisado | Pendiente |
| `/app/signals` | Bandeja global de señales autorizadas | `signal.read` | O, A, E, N, V | F1/F2; menú principal; badge `99+` solo con recuento backend | Solo `GET /dossiers/{id}/signals` y `GET /signals/{id}`; revisión/promoción disponibles | Parcial: falta listado global |
| `/app/opportunities` | Cartera agregada de oportunidades | `opportunity.read` | O, A, E, N, V | F1/F2; menú principal | Solo `GET /dossiers/{id}/opportunities` y `GET/PATCH /opportunities/{id}` | Parcial: falta listado global |
| `/app/risks` | Registro agregado de riesgos | `risk.read` | O, A, E, N, V | F1/F2; menú principal | Solo `GET /dossiers/{id}/risks` y `GET/PATCH /risks/{id}` | Parcial: falta listado global |
| `/app/actors` | Directorio y grafo accesible | `actor.read` | O, A, E, N, V | F1/F2; menú principal | `GET/POST /actors`, `GET/PATCH /actors/{id}`, `GET/POST /relationships` | Disponible; agregados de roles/expedientes pueden requerir composición |
| `/app/meetings` | Agenda, briefings y seguimiento | `meeting.read` | O, A, E, N, V | F1/F2; menú principal | Solo `GET /dossiers/{id}/meetings`, detalle y briefings | Parcial: falta listado global |
| `/app/tasks` | Trabajo personal y de equipo | `task.read` | O, A, E, N, V | F1/F2; menú principal | Solo `GET /dossiers/{id}/tasks` y `GET/PATCH /tasks/{id}` | Parcial: falta listado global |
| `/app/reports` | Biblioteca global y estado de informes | `report.read` | O, A, E, N, V | F1/F2; menú principal | `GET /reports`, `GET /report-templates`, `POST /dossiers/{id}/reports` | Disponible |
| `/app/reports/[reportId]` | Visor, citas, revisión, publicación y versiones | `report.read` + acceso al expediente | O, A, E, N, V | F1/F2/F3; enlace contextual, no entrada principal | `GET /reports/{id}`, revisiones, reviews, publish, retry y download-link | Disponible |
| `/app/notifications` | Centro de notificaciones del usuario | `notifications.read` | O, A, E, N, V, U | F1/F2; campana y menú de usuario | `GET /notifications`, read, read-all y dismiss | Disponible |
| `/app/exports` | Centro de exportaciones solicitadas | `export.create`; el dataset vuelve a validar permiso | O, A, E, N, V, U | F1/F2; acceso desde menús Exportar/Informes, no ocupa el menú principal | `GET/POST /exports` | Disponible |
| `/app/exports/[exportId]` | Estado y descarga temporal de una exportación propia | `export.create` + owner/scope; `audit.export` para auditoría | O, A, E, N, V, U | F1/F2/F3; enlace contextual | `GET /exports/{id}`, `POST /exports/{id}/download-link`, descarga | Disponible |

Los datasets CSV disponibles son `signals`, `opportunities`, `risks`, `actors`, `tasks`, `reports` y `audit`. La exportación de auditoría exige además `audit.export`. No existe dataset `dossiers` ni `meetings` en el backend actual.

## Rutas del expediente

Además del permiso indicado, todas exigen acceso al expediente mediante ownership, administración o colaboración activa. Un UUID ajeno produce F3.

| Ruta | Etiqueta / finalidad | Permiso de entrada | Roles default | 403 / navegación | API principal consumida | Estado API |
|---|---|---|---|---|---|---|
| `/app/dossiers/[dossierId]` | Resumen y living summary | `dossier.read` | O, A, E, N, V, U | F1/F2/F3; primera pestaña | `GET /dossiers/{id}`, objectives, hypotheses, living-summary, monitors/health | Disponible |
| `/app/dossiers/[dossierId]/signals` | Señales contextualizadas | `signal.read` | O, A, E, N, V | F1/F2/F3; pestaña oculta sin permiso | `GET /dossiers/{id}/signals`, `GET /signals/{id}`, review/promote/retriage | Disponible |
| `/app/dossiers/[dossierId]/opportunities` | Oportunidades del expediente | `opportunity.read` | O, A, E, N, V | F1/F2/F3 | `GET/POST /dossiers/{id}/opportunities`, detalle/links | Disponible |
| `/app/dossiers/[dossierId]/risks` | Riesgos del expediente | `risk.read` | O, A, E, N, V | F1/F2/F3 | `GET/POST /dossiers/{id}/risks`, detalle/links | Disponible |
| `/app/dossiers/[dossierId]/actors` | Actores y relaciones contextualizados | `actor.read` | O, A, E, N, V | F1/F2/F3 | `GET/POST /dossiers/{id}/actors`, `GET/POST /relationships`, links de evidencia | Disponible |
| `/app/dossiers/[dossierId]/meetings` | Reuniones y briefings | `meeting.read` | O, A, E, N, V | F1/F2/F3 | `GET/POST /dossiers/{id}/meetings`, detalle y briefings | Disponible |
| `/app/dossiers/[dossierId]/tasks` | Tareas del expediente | `task.read` | O, A, E, N, V | F1/F2/F3 | `GET/POST /dossiers/{id}/tasks`, `GET/PATCH /tasks/{id}` | Disponible |
| `/app/dossiers/[dossierId]/documents` | Documentos, búsqueda y evidencias | `documents.read` | O, A, E, N, V, U | F1/F2/F3 | documents, dossier search y evidence | Disponible |
| `/app/dossiers/[dossierId]/reports` | Informes del expediente | `report.read` | O, A, E, N, V | F1/F2/F3 | `GET/POST /dossiers/{id}/reports`, templates | Disponible |
| `/app/dossiers/[dossierId]/decisions` | Registro de decisiones y motivos | `task.read` | O, A, E, N, V | F1/F2/F3 | `GET/POST /dossiers/{id}/decisions`, detalle/evidence | Disponible |
| `/app/dossiers/[dossierId]/settings` | Configuración, watchlists, monitores, alertas, colaboradores y auditoría contextual | `dossier.read`; cada sección/mutación exige su permiso específico | O, A, E, N, V, U | F1/F2/F3; última pestaña; secciones no autorizadas ocultas sin cambiar orden | dossier PATCH, objectives/hypotheses/watchlists, monitors, alert-policy, collaborators y dossier audit | Parcial: no hay API de plantillas de expediente ni borrado físico; varias secciones son solo lectura por rol |

Permisos de acción en configuración: General/objetivos/hipótesis/colaboradores `dossier.write`; archivo `dossier.archive`; monitores `signal.review`; documentos `documents.manage`; política de alertas del dossier `dossier.write`; auditoría `audit.read`. El expediente archivado queda en solo lectura aunque el usuario conserve permisos.

## Rutas de cuenta

Todas requieren sesión válida, pero no un permiso tenant. Deben seguir accesibles a un `platform_superadmin` sin tenant activo cuando el endpoint lo permita.

| Ruta | Etiqueta / finalidad | Permiso | Roles | 403 / navegación | API principal consumida | Estado API |
|---|---|---|---|---|---|---|
| `/app/account` | Landing o redirección estable a Perfil | Autenticado | O, A, E, N, V, U | F1; menú de usuario | `GET /auth/me` | Disponible como routing, sin endpoint propio |
| `/app/account/profile` | Perfil personal | Autenticado | O, A, E, N, V, U | F1; menú de usuario | `GET /auth/me`; no existe `PATCH` de perfil | Parcial: lectura sí, edición pendiente |
| `/app/account/security` | Contraseña y autenticación reciente | Autenticado + F5 para guardar | O, A, E, N, V, U | F1/F5; menú de usuario | `POST /auth/reauthenticate`, `POST /auth/change-password` | Disponible |
| `/app/account/sessions` | Sesiones activas y revocación | Autenticado + F5 para revocar | O, A, E, N, V, U | F1/F5; menú de usuario | `GET /auth/sessions`, delete y revoke-others | Disponible |
| `/app/account/preferences` | Idioma, zona horaria, densidad, tema y accesibilidad | Autenticado | O, A, E, N, V, U | F1; menú de usuario | No existe API de `UserSettings`; el `localStorage` del prototipo no es autoridad productiva | Pendiente |
| `/app/account/notifications` | Canales, tipos, quiet hours y digest | `notifications.manage` | O, A, E, N, V, U | F1/F2; menú de usuario y centro de notificaciones | `GET/PATCH /notification-preferences` | Disponible |

## Administración del tenant

La entrada “Administración” se muestra si el usuario tiene al menos uno de `tenant.users.manage`, `tenant.settings.manage`, `tenant.integrations.manage` o `audit.read`; dentro solo aparecen las áreas autorizadas. No se mezclan estas rutas con preferencias personales.

| Ruta | Etiqueta / finalidad | Permiso de entrada | Roles default | 403 / navegación | API principal consumida | Estado API |
|---|---|---|---|---|---|---|
| `/app/admin` | Landing de áreas administrativas autorizadas | Cualquiera de los cuatro permisos administrativos indicados | O, A, U (U solo ve Auditoría) | F1/F2; zona inferior del sidebar | Composición de endpoints hijos | Parcial |
| `/app/admin/organization` | Datos organizativos y política general | `tenant.settings.manage` | O, A | F1/F2; submenu admin | Solo `GET/PATCH /alert-policy` cubre umbrales; no hay API de tenant actual editable | Parcial |
| `/app/admin/members` | Miembros, invitaciones, estado y roles | `tenant.users.manage` | O, A | F1/F2 | `GET/POST /tenant-admin/members`, patch/delete/resend/roles | Disponible |
| `/app/admin/roles` | Roles y matriz de permisos | `tenant.users.manage` | O, A | F1/F2 | `GET /tenant-admin/roles`; no hay CRUD de roles o permisos | Parcial: solo lectura |
| `/app/admin/workspaces` | Inventario y miembros de workspaces | `tenant.settings.manage` | O, A | F1/F2 | No hay endpoints de workspaces | Pendiente |
| `/app/admin/integrations` | Catálogo y salud de conexiones | `tenant.integrations.manage` | O, A | F1/F2 | Solo endpoints de Signal Avanza | Parcial: catálogo multi-integración pendiente |
| `/app/admin/integrations/signal-avanza` | Credencial enmascarada, test, rotación, salud y reconcile | `tenant.integrations.manage` | O, A | F1/F2/F5 para credenciales | `/integrations/signal-avanza`, test, rotate, disable y reconcile | Disponible |
| `/app/admin/audit` | Auditoría tenant y procesos en segundo plano con dos vistas internas | `audit.read`; exportar exige `audit.export`; procesos usan el alcance autorizado de `/jobs` | O, A, U | F1/F2/F3 | `GET /tenant-admin/audit`; `GET /jobs`; export dataset `audit` | Disponible; `/app/admin/jobs` redirige a `?view=processes` |

## Portal de plataforma

El portal usa shell diferenciado y aviso persistente “Contexto de plataforma”. Ninguna ruta abre datos de negocio de un tenant por defecto.

| Ruta | Etiqueta / finalidad | Permiso | Roles | 403 / navegación | API principal consumida | Estado API |
|---|---|---|---|---|---|---|
| `/platform` | Estado general / landing | Rol de plataforma `super_admin` | P | F1/F4; primera entrada del shell plataforma | No existe agregado de estado de plataforma | Pendiente; puede redirigir temporalmente a tenants |
| `/platform/tenants` | Tenants globales | Rol `super_admin` | P | F1/F4; navegación plataforma | `GET/POST /platform/tenants` | Disponible |
| `/platform/tenants/[tenantId]` | Detalle administrativo sin datos de negocio | Rol `super_admin` | P | F1/F4; IDs no autorizados no revelan negocio | get/patch, suspend, reactivate e invite-owner | Disponible |
| `/platform/users` | Directorio global de usuarios | Rol `super_admin` | P | F1/F4 | `GET /platform/users` | Disponible |
| `/platform/jobs` | Colas y jobs globales saneados | Rol `super_admin` | P | F1/F4 | No hay endpoint global de jobs | Pendiente |
| `/platform/integrations` | Salud global de integraciones sin secretos | Rol `super_admin` | P | F1/F4 | No hay endpoint global de integraciones | Pendiente |
| `/platform/audit` | Auditoría de plataforma | Rol `super_admin` | P | F1/F4 | `GET /platform/audit` | Disponible |
| `/platform/system` | Salud técnica resumida y protegida | Rol `super_admin` | P | F1/F4 | `/health/live` y `/health/ready` no constituyen una API autenticada de panel de sistema | Pendiente |

## Rutas históricas y compatibilidad

Estas rutas no forman parte de la IA final:

| Ruta histórica | Destino contractual | Regla |
|---|---|---|
| `/app/portfolio` | `/app` | Redirección temporal, preservando filtros seguros cuando proceda. |
| `/app/settings` | `/app/account/preferences` | Redirección; no mantener una segunda pantalla de ajustes. |
| `/concept-a/*` | Ruta `/app/*` equivalente | Alias temporal de Vector; no recibe funcionalidad nueva independiente. |
| `/concept-b/*` | Material comparativo Horizon | No ampliar. Su retirada exige plan documentado y pruebas de rutas canónicas; no se considera ruta productiva. |

## Huecos de contrato que bloquean pantallas completas

1. Endpoints globales server-side para señales, oportunidades, riesgos, reuniones y tareas.
2. Read model de Inicio y “Qué ha cambiado”, incluido estado revisado.
3. API durable de perfil editable y preferencias generales de usuario.
4. Organización actual y CRUD/memberships de workspaces.
5. CRUD de roles custom, si se confirma que entra en el primer release.
6. Permiso/contrato definitivo de la vista de procesos dentro de `/app/admin/audit`; hoy la API `/jobs` se rige por `dossier.read` y scope de recurso.
7. Endpoints globales de jobs, integraciones y estado seguro de plataforma.
8. Búsqueda global de entidades: `GET /search` busca documentos/chunks; no cubre todavía expedientes, señales, oportunidades, riesgos, actores, informes y reuniones como exige la command palette.
