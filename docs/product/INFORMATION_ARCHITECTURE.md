# Arquitectura de información de OPN Oracle

**Estado:** especificación objetivo para Prompt 12  
**Interfaz canónica:** `CANONICAL_UI=vector`  
**Ámbito:** aplicación autenticada, cuenta, administración de tenant y plataforma  
**Fuente de contrato:** `docs/api/openapi.json`; este documento no amplía la API Flask

## 1. Decisión y principios

Vector Command Center es el único lenguaje de producto que se seguirá ampliando. Horizon permanece temporalmente como referencia del escaparate A/B, aislado bajo `/concept-b/*`; no recibe nuevas funcionalidades productivas ni aporta tokens, navegación o layouts a `/app`.

La arquitectura se rige por estas reglas:

1. `StrategicDossier` es el centro del producto. Las vistas globales agregan recursos de los expedientes autorizados; las vistas contextuales explican y permiten actuar dentro de un expediente concreto.
2. El shell global responde «¿qué requiere atención en mi portfolio?». El shell de expediente responde «¿qué sé y qué hago en este expediente?».
3. Cuenta personal, administración organizativa y plataforma son contextos separados. Nunca se mezclan en el menú principal.
4. Las tablas son el inventario operativo principal. Tarjetas, gráficas, calendario y grafo complementan la tabla; no la sustituyen cuando se necesita comparar o seleccionar.
5. El riesgo protege el avance, pero oportunidades, señales y siguientes acciones conservan prioridad en jerarquía y microcopy.
6. Un destino productivo tiene una ruta real. Los anchors del prototipo no son navegación.
7. La visibilidad cliente mejora la experiencia, pero Flask sigue autorizando cada petición. Un deep link sin permiso muestra un 403 útil dentro del shell correcto.
8. No se construyen agregados en Node ni encadenando una petición por expediente. Si OpenAPI no ofrece un listado global, la ruta se prepara con un estado honesto hasta completar el contrato Flask.

## 2. Modelo de contextos

| Contexto | Prefijo | Pregunta que resuelve | Navegación | Regla de datos |
|---|---|---|---|---|
| Producto global | `/app` | ¿Qué ocurre en todos mis expedientes autorizados? | Sidebar Vector global | Solo tenant/workspace activo y recursos autorizados |
| Expediente | `/app/dossiers/[dossierId]` | ¿Qué ocurre y qué debo hacer en este expediente? | Sidebar global + subnavegación persistente del expediente | `dossierId` validado por backend; nunca se infiere acceso por conocer el UUID |
| Cuenta | `/app/account` | ¿Cómo gestiono mi identidad y preferencias? | Subnavegación de cuenta | Datos del usuario autenticado; no configuración del tenant |
| Administración | `/app/admin` | ¿Cómo administro el tenant activo? | Subnavegación administrativa | Permisos administrativos y contexto del tenant siempre visibles |
| Plataforma | `/platform` | ¿Cómo administro organizaciones y salud global? | Shell Vector diferenciado | No concede acceso implícito a negocio de tenants |

El tenant activo es obligatorio en `/app`; cambiarlo invalida toda caché tenant-scoped, cierra drawers/modales del tenant anterior y navega a `/app`. El workspace se muestra junto al tenant solo cuando el backend y la membership permitan selección real; no se presenta un selector decorativo.

## 3. Árbol de navegación objetivo

```text
OPN Oracle
├── Producto (/app)
│   ├── Trabajo estratégico
│   │   ├── Inicio (/app)
│   │   ├── Expedientes (/app/dossiers)
│   │   └── Qué ha cambiado (/app/changes)
│   ├── Inteligencia
│   │   ├── Señales (/app/signals)
│   │   ├── Oportunidades (/app/opportunities)
│   │   ├── Riesgos (/app/risks)
│   │   └── Actores (/app/actors)
│   └── Ejecución
│       ├── Reuniones (/app/meetings)
│       ├── Tareas (/app/tasks)
│       └── Informes (/app/reports)
├── Expediente (/app/dossiers/[dossierId])
│   ├── Resumen
│   ├── Señales
│   ├── Oportunidades
│   ├── Riesgos
│   ├── Actores
│   ├── Reuniones
│   ├── Tareas
│   ├── Documentos
│   ├── Informes
│   ├── Decisiones
│   └── Configuración
├── Cuenta (/app/account)
│   ├── Perfil
│   ├── Seguridad
│   ├── Sesiones
│   ├── Preferencias
│   └── Notificaciones
├── Administración del tenant (/app/admin)
│   ├── Organización
│   ├── Miembros
│   ├── Roles y permisos
│   ├── Workspaces
│   ├── Integraciones
│   │   └── Signal Avanza
│   ├── Auditoría
│   └── Trabajos
└── Plataforma (/platform)
    ├── Estado general
    ├── Organizaciones
    │   └── Detalle de organización
    ├── Usuarios
    ├── Trabajos
    ├── Integraciones
    ├── Auditoría
    └── Sistema
```

Los grupos conservan su orden aunque un permiso o una capacidad no estén disponibles. Se oculta el destino no autorizado; no se recolocan los destinos restantes de forma distinta en cada sesión.

## 4. Mapa de rutas globales

| Ruta | Label | Finalidad | Patrón principal | Contrato Flask disponible a 2026-07-11 |
|---|---|---|---|---|
| `/app` | Inicio | Prioridades, cambios y siguiente acción del portfolio | Resumen denso con enlaces filtrados | Parcial: expedientes, informes, jobs y notificaciones; no existe endpoint agregado de inicio |
| `/app/dossiers` | Expedientes | Inventario, filtros y creación | DataTable server-side | `GET/POST /api/v1/dossiers` |
| `/app/changes` | Qué ha cambiado | Cambios priorizados y revisables | Lista acotada + filtros | No existe endpoint global específico |
| `/app/signals` | Señales | Inbox global de revisión | DataTable + drawer | Solo listado contextual `/api/v1/dossiers/{id}/signals`; no hay listado global |
| `/app/opportunities` | Oportunidades | Cartera agregada | DataTable; board opcional | Solo listado contextual `/api/v1/dossiers/{id}/opportunities` |
| `/app/risks` | Riesgos | Registro agregado | DataTable; matriz secundaria | Solo listado contextual `/api/v1/dossiers/{id}/risks` |
| `/app/actors` | Actores | Directorio compartido y relaciones | DataTable + grafo accesible | `GET /api/v1/actors`, `GET /api/v1/relationships` |
| `/app/meetings` | Reuniones | Agenda, briefings y seguimiento | Lista; calendario opcional | Solo listado contextual `/api/v1/dossiers/{id}/meetings` |
| `/app/tasks` | Tareas | Trabajo personal y de equipo | DataTable/lista agrupable | Solo listado contextual `/api/v1/dossiers/{id}/tasks` |
| `/app/reports` | Informes | Biblioteca y generación | DataTable + viewer | `GET /api/v1/reports`, templates y workflow de reporting |
| `/app/notifications` | Notificaciones | Inbox personal completo | Lista filtrable | `GET /api/v1/notifications` y acciones de lectura/descarte |
| `/app/exports` | Exportaciones | Estado y descarga de exports solicitados | DataTable + detalle | `GET/POST /api/v1/exports` y artefactos autorizados |

`Notificaciones` y `Exportaciones` son rutas funcionales, pero no añaden dos entradas al bloque principal de diez destinos: notificaciones se abre desde la campana y el menú de usuario; exportaciones desde acciones de tabla y su historial contextual.

Cuando falte el listado global, Prompt 12 puede crear la ruta, navegación, filtros y estados, pero debe mostrar «Esta vista agregada necesita soporte del API» y guiar a los listados contextuales. Queda prohibido simular datos, importar fixtures productivos o hacer fan-out N+1 desde el navegador.

## 5. Rutas del expediente

El encabezado de expediente persiste al cambiar de sección y siempre presenta título, tipo, estado, propietario, oportunidad, riesgo, señales nuevas, última actualización, acción primaria contextual y menú `Más`. El estado archivado se anuncia como solo lectura antes de cualquier acción.

| Orden | Ruta | Contenido principal | APIs existentes relevantes |
|---:|---|---|---|
| 1 | `/app/dossiers/[dossierId]` | Living summary, objetivos, hipótesis, cambios, prioridades, actores, decisiones e integración | dossier, living summary, objectives, hypotheses, status history, audit |
| 2 | `/app/dossiers/[dossierId]/signals` | Señales del expediente y triage | dossier signals, signal detail/review/promote/retriage |
| 3 | `/app/dossiers/[dossierId]/opportunities` | Oportunidades, score, evidencia, actores y señales | dossier opportunities, opportunity detail y relaciones M:N |
| 4 | `/app/dossiers/[dossierId]/risks` | Riesgos, mitigación, score, evidencia, actores y señales | dossier risks, risk detail y relaciones M:N |
| 5 | `/app/dossiers/[dossierId]/actors` | Actores contextuales y relaciones | dossier actors, actor detail, relationships |
| 6 | `/app/dossiers/[dossierId]/meetings` | Reuniones, briefings y seguimientos | dossier meetings, meeting detail/actors/evidence, briefings |
| 7 | `/app/dossiers/[dossierId]/tasks` | Tareas del expediente | dossier tasks, task detail |
| 8 | `/app/dossiers/[dossierId]/documents` | Upload, procesamiento, búsqueda y evidencias | dossier documents/search/evidence; document lifecycle |
| 9 | `/app/dossiers/[dossierId]/reports` | Informes filtrados por expediente | dossier reports, report workflow y artefactos |
| 10 | `/app/dossiers/[dossierId]/decisions` | Registro decisional con motivos y fuentes | dossier decisions, decision detail/evidence |
| 11 | `/app/dossiers/[dossierId]/settings` | General, objetivos, watchlist, monitores, alertas, colaboradores y auditoría | dossier patch/archive, objectives, hypotheses, watchlists, monitors, alert policy, collaborators, audit |

La configuración del expediente referencia una conexión Signal gestionada por el tenant; nunca muestra ni edita credenciales. La edición extensa y los flujos de varias etapas usan página completa, no un modal.

## 6. Cuenta, administración y plataforma

### 6.1 Cuenta personal

| Ruta | Contenido | Disponibilidad de contrato |
|---|---|---|
| `/app/account/profile` | Identidad visible y perfil | Lectura en `/api/v1/auth/me`; no hay mutación de perfil en OpenAPI |
| `/app/account/security` | Contraseña y reautenticación reciente | `/api/v1/auth/change-password`, `/reauthenticate` |
| `/app/account/sessions` | Sesiones activas y revocación | `/api/v1/auth/sessions*` |
| `/app/account/preferences` | Idioma, zona, densidad, tema y accesibilidad | No existe endpoint general de preferencias en OpenAPI |
| `/app/account/notifications` | Canales, digest y quiet hours | `/api/v1/notification-preferences` |

`/app/account` redirige a `/app/account/profile`. No se presenta como guardada ninguna preferencia que el backend todavía no pueda persistir. La densidad del shell puede persistirse localmente como preferencia puramente visual, aislada por usuario, sin contenido sensible.

### 6.2 Administración del tenant

| Ruta | Permiso de entrada | Contrato disponible |
|---|---|---|
| `/app/admin/organization` | `tenant.settings.manage` | Sin endpoint de edición del tenant actual |
| `/app/admin/members` | `tenant.users.manage` | `/api/v1/tenant-admin/members*` |
| `/app/admin/roles` | `tenant.users.manage` | `GET /api/v1/tenant-admin/roles`; no hay CRUD de roles |
| `/app/admin/workspaces` | `tenant.settings.manage` | Sin endpoints de workspaces en OpenAPI |
| `/app/admin/integrations` | `tenant.integrations.manage` | Listado/configuración Signal Avanza disponible |
| `/app/admin/integrations/signal-avanza` | `tenant.integrations.manage` | `/api/v1/integrations/signal-avanza*` |
| `/app/admin/audit` | `audit.read` | `GET /api/v1/tenant-admin/audit` y vista interna de procesos con `/api/v1/jobs*`; `/app/admin/jobs` redirige a `?view=processes` |

`/app/admin` abre una landing que solo incluye áreas autorizadas. Cada pantalla repite nombre del tenant activo y etiqueta `Administración de la organización`. Las capacidades sin contrato usan estado no disponible, nunca formularios falsamente editables.

### 6.3 Plataforma

| Ruta | Contrato disponible |
|---|---|
| `/platform` | Resumen derivable parcialmente de tenants/users/audit; no hay endpoint dashboard |
| `/platform/tenants` | `GET/POST /api/v1/platform/tenants` |
| `/platform/tenants/[tenantId]` | get/patch/suspend/reactivate/invite-owner |
| `/platform/users` | `GET /api/v1/platform/users` |
| `/platform/jobs` | No existe listado global de plataforma |
| `/platform/integrations` | No existe salud global de integraciones |
| `/platform/audit` | `GET /api/v1/platform/audit` |
| `/platform/system` | Solo `/health/live`, `/health/ready` públicos/técnicos; no existe API de sistema para esta pantalla |

El shell muestra permanentemente `Contexto de plataforma`. `platform_super_admin` no ve contenido de negocio de un tenant por defecto y no existe suplantación. Un salto futuro a contexto tenant exigirá selección explícita, motivo, permiso y auditoría; no se implementa por navegación cliente.

## 7. Navegación entre recursos

Las transiciones preservan el contexto y evitan callejones sin salida:

- Una fila global abre un drawer para inspección rápida. `Abrir en expediente` navega a la sección contextual equivalente y conserva un retorno a la vista global con sus filtros.
- Una señal puede pasar, según permiso, a revisión, descarte, promoción a oportunidad/riesgo, tarea o asociación a expediente. La promoción usa modal breve; al completar abre el recurso creado en el mismo expediente.
- Oportunidad y riesgo enlazan señales, actores y evidencias sin perder el expediente. Los paneles de evidencia distinguen fuente pública/interna y hechos/inferencias/recomendaciones.
- Actor global muestra expedientes relacionados; elegir uno abre `/app/dossiers/[dossierId]/actors` con el actor enfocado. Relaciones inferidas y confirmadas nunca se presentan igual.
- Reunión enlaza briefing, actores, documento/nota y tareas de seguimiento. Briefing complejo abre página completa.
- Informe enlaza expediente, job y evidencia. La cita abre evidence drawer; descargar usa únicamente el flujo de artefacto autorizado.
- Notificación valida que su link sea interno y autorizado; si el recurso ya no es accesible, permanece legible sin revelar datos y ofrece volver al centro.
- Los cambios de estado que alteran una fila actualizan tabla, contadores y detalle desde servidor; no se deriva autoridad de un estado optimista cliente.

Todo drawer de inspección debe ser deep-linkable mediante estado de URL centralizado, pero no mediante un fragmento `#...`. Volver/cerrar restaura consulta, orden, filtros, página, selección y foco de la vista anterior.

## 8. Patrones de presentación

| Necesidad | Patrón |
|---|---|
| Crear expediente mínimo, tarea, reunión, promoción o invitación | Modal accesible |
| Inspección de señal, oportunidad, riesgo, actor, job o evidencia | Drawer |
| Edición compleja, configuración, informe y briefing | Página completa |
| Inventario y comparación | DataTable server-side compartida |
| Grafo o matriz | Vista secundaria con alternativa tabular |
| Reversible y de bajo impacto | Toast con deshacer cuando el backend lo permita |
| Destructiva | Modal explícito; confirmación reforzada para archivo/borrado de alto impacto |

No se usa `window.confirm`. Loading, empty, no-results, 403, 409, 422, 429 y error recuperable forman parte del patrón de cada pantalla.

## 9. Transición desde el prototipo

La migración a rutas productivas es semántica, no una sustitución textual de prefijos:

| Origen actual | Destino productivo |
|---|---|
| `/app/portfolio` | `/app` |
| `/app/portfolio#expedientes` | `/app/dossiers` |
| `/app/portfolio#radar` | `/app/signals` |
| enlace «Oportunidades» a `#prioridades` | `/app/opportunities` |
| enlace «Riesgos» a `#prioridades` | `/app/risks` |
| `/app/portfolio#actores` | `/app/actors` |
| `/app/settings` | `/app/account/preferences` |
| `/concept-a/portfolio` y anchors equivalentes | misma ruta `/app/*` semántica |
| `/concept-a/settings/profile` | `/app/account/profile` |
| `/concept-a/settings/security` | `/app/account/security` |
| `/concept-a/settings/sessions` | `/app/account/sessions` |
| `/concept-a/admin/members` | `/app/admin/members` |
| `/concept-a/admin/audit` | `/app/admin/audit` |
| `/concept-a/admin/integrations` | `/app/admin/integrations` |
| `/concept-a/reports*`, notifications, exports | equivalente bajo `/app/*` |

Los enlaces internos se corrigen antes de añadir redirects. Los redirects preservan parámetros seguros de filtro, pero descartan fragments antiguos. Horizon `/concept-b/*` se retira de cualquier entrada o command palette productivos; sus rutas se conservan como referencia aislada hasta que exista una decisión de retirada y pruebas de regresión. No se redirige silenciosamente mientras siga declarado como escaparate temporal.

## 10. Gates para Prompt 12

Antes de considerar aplicada esta arquitectura:

- el menú desktop y móvil deriva de un único registro tipado de rutas y permisos;
- `/app` y las once secciones de expediente tienen destino real, aunque un contrato faltante muestre estado honesto;
- no quedan links productivos a `portfolio#...`, `/concept-a/*` o `/concept-b/*`;
- cuenta, admin y plataforma tienen layouts y breadcrumbs propios;
- los permisos y APIs exactos se mantienen en `ROUTE_PERMISSION_MATRIX.md` y `SCREEN_COMPONENT_MATRIX.md`;
- cualquier gap de API señalado aquí se resuelve en Flask/OpenAPI o permanece explícitamente no disponible; nunca mediante lógica autoritativa en Node;
- la navegación se valida con teclado y en 1440×900, 1280×800, 1024×768 y 390×844.
