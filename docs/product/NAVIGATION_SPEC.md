# Especificación de navegación Vector

**Interfaz canónica:** `CANONICAL_UI=vector`  
**Aplicación:** `/app`  
**Objetivo:** una única navegación densa, predecible, autorizada y reutilizable en escritorio y móvil

## 1. Anatomía del shell autenticado

El shell Vector se compone, en orden estructural, de:

1. skip link `Saltar al contenido principal`;
2. sidebar global;
3. cabecera global;
4. subnavegación contextual cuando corresponde;
5. contenido principal con `id` estable;
6. portales de drawer, modal, command palette y toasts.

No se muestra el nombre `Vector` al usuario final. La marca es `OPN Oracle`; `Datos sintéticos` solo aparece en entornos o datasets que realmente lo sean.

## 2. Sidebar global

### 2.1 Cabecera

- logo OPN Oracle enlazado a `/app`;
- selector de tenant y, cuando exista contrato real, workspace;
- estado expandido/contraído persistido por usuario como preferencia visual;
- al contraer, iconos mantienen tooltip y nombre accesible.

El selector solo se habilita con más de una membership válida. Durante un cambio de tenant:

1. bloquea una segunda selección;
2. llama al endpoint Flask de cambio;
3. invalida cachés tenant-scoped y estado de tablas;
4. cierra overlays abiertos;
5. navega a `/app`;
6. anuncia el nuevo tenant mediante `aria-live` y toast.

Ante error, conserva tenant, ruta y datos anteriores; no muestra una transición optimista incompleta.

### 2.2 Grupos y orden

```text
Trabajo estratégico
  Inicio
  Expedientes
  Qué ha cambiado

Inteligencia
  Señales
  Oportunidades
  Riesgos
  Actores

Ejecución
  Reuniones
  Tareas
  Informes
```

La entrada activa usa `aria-current="page"`, peso, borde/indicador y contraste; el color no es la única señal. Badges:

- `Qué ha cambiado`: cambios no revisados;
- `Señales`: pendientes de revisión, máximo visible `99+`;
- otros badges solo si una API autorizada ofrece un conteo accionable.

Un badge no modifica el nombre accesible de forma ruidosa; el lector de pantalla recibe, por ejemplo, `Señales, 7 pendientes`.

### 2.3 Zona inferior

- `Administración`, solo si al menos una subruta está autorizada;
- ayuda/atajos, si es funcional;
- control de expandir/contraer;
- menú de usuario.

`Ajustes de cuenta` se abre desde el menú de usuario y puede existir como acceso inferior, pero no compite con las diez áreas de trabajo.

## 3. Cabecera global

De izquierda a derecha:

1. control de navegación móvil/tablet cuando proceda;
2. breadcrumbs;
3. búsqueda global / disparador de command palette;
4. indicador compacto de degradación que afecte al usuario;
5. botón `Crear`;
6. campana de notificaciones;
7. menú de usuario cuando no esté alojado en el sidebar compacto.

La cabecera permanece visible al hacer scroll en tablas largas. No tapa el foco ni duplica el título de página.

### 3.1 Breadcrumbs

Se generan desde el registro central de rutas y el contexto cargado, no mediante comprobaciones parciales de `pathname`.

Ejemplos:

```text
Oracle / Expedientes
Oracle / Expedientes / Proyecto Aurora / Señales
Oracle / Administración / Signal Avanza
Plataforma / Organizaciones / Nébula Labs
```

- `Oracle` enlaza a `/app` en producto.
- Los segmentos intermedios enlazan a su índice.
- El último usa `aria-current="page"` y no es un link redundante.
- Mientras se carga el nombre de un recurso, se usa un skeleton, nunca el UUID como label visible salvo fallback de error.
- En móvil se acortan visualmente, pero el nombre accesible conserva la ruta completa.

### 3.2 Menú `Crear`

Las acciones aparecen en orden estable y solo si son completables en el contexto y con el permiso actual:

| Acción | Contexto | Permiso mínimo | Resultado |
|---|---|---|---|
| Nuevo expediente | Global | `dossier.write` | Modal de datos mínimos |
| Nueva tarea | Global o expediente | `task.write` | Modal; expediente preseleccionado cuando existe |
| Nueva reunión | Global o expediente | `meeting.write` | Modal breve |
| Cargar documento | Solo con expediente seleccionado | `documents.manage` | Selector/upload del expediente |
| Crear oportunidad manual | Preferentemente expediente | `opportunity.write` | Formulario contextual |
| Crear riesgo manual | Preferentemente expediente | `risk.write` | Formulario contextual |

Si una acción global requiere elegir expediente, el selector solo muestra expedientes autorizados y activos. No se ofrece cargar documento fuera de un expediente.

### 3.3 Indicadores de salud

Solo aparecen si afectan al trabajo del usuario: integración degradada, job propio fallido o servicio temporalmente no disponible. El indicador abre un popover accesible con impacto y enlace real a contexto; no expone payload, secreto ni stack trace. No se usan estados técnicos como decoración permanente.

## 4. Menú de usuario

El trigger muestra iniciales/avatar, nombre y rol efectivo. El panel incluye:

1. nombre y email;
2. tenant/workspace activo;
3. rol efectivo;
4. `Mi cuenta` → `/app/account/profile`;
5. `Seguridad y sesiones` → `/app/account/security` o sessions;
6. `Preferencias` → `/app/account/preferences`;
7. `Notificaciones` → `/app/account/notifications`;
8. `Cambiar organización`, solo con varias memberships;
9. `Atajos de teclado`;
10. `Portal de plataforma`, solo para `platform_super_admin`;
11. `Cerrar sesión`.

La administración del tenant no vive dentro del menú de usuario. `Cerrar sesión` no es optimista: si Flask falla, la sesión sigue representándose como activa y se informa del error.

## 5. Navegación del expediente

### 5.1 Encabezado contextual

Debajo de la cabecera global muestra:

- vuelta a Expedientes;
- título y tipo;
- estado;
- propietario;
- niveles de oportunidad y riesgo con texto además de color;
- señales nuevas;
- última actualización;
- acción primaria de la sección;
- menú `Más` para acciones infrecuentes y archivo.

No se repite en cada página como implementación independiente: el layout del expediente carga y comparte el contexto. Cambiar entre secciones no desmonta innecesariamente cabecera ni navegación.

### 5.2 Orden de secciones

```text
Resumen · Señales · Oportunidades · Riesgos · Actores · Reuniones · Tareas
· Documentos · Informes · Decisiones · Configuración
```

Las secciones son links a rutas reales, no tabs controladas solo por estado React ni anchors. El orden lógico no cambia por ancho. Cuando no quepan, `Más` contiene únicamente el desbordamiento final y anuncia `aria-haspopup="menu"`; la sección activa permanece visible siempre que sea posible.

### 5.3 Cambio rápido de expediente

Puede añadirse si usa expedientes recientes obtenidos sin datos sensibles persistidos localmente. Mantiene la sección equivalente cuando existe (por ejemplo, de señales a señales) y cae en Resumen si no. La selección no evita la comprobación de acceso del backend.

## 6. Subshells de cuenta y administración

### Cuenta

La navegación secundaria contiene Perfil, Seguridad, Sesiones, Preferencias y Notificaciones. El título permanente es `Mi cuenta`; no muestra herramientas de tenant. En móvil se convierte en selector de sección accesible.

### Administración

La navegación secundaria contiene Organización, Miembros, Roles y permisos, Workspaces, Integraciones, Auditoría y Trabajos. Muestra el tenant administrado en todas las páginas. Las entradas no autorizadas se ocultan, pero un deep link devuelve 403 útil.

### Plataforma

Usa el mismo sistema visual Vector con color/aviso de contexto diferenciado, no Horizon. Contiene Estado general, Organizaciones, Usuarios, Trabajos, Integraciones, Auditoría y Sistema solo cuando hay soporte. Una franja persistente dice `Contexto de plataforma`; volver a Oracle enlaza a `/app`.

## 7. Búsqueda global y command palette

El mismo trigger abre una experiencia común con `⌘K` o `Ctrl+K`. El foco entra en el campo de búsqueda; `Escape` cierra y lo devuelve al trigger.

### 7.1 Resultados

Se agrupan, en este orden:

1. expedientes;
2. señales;
3. oportunidades;
4. riesgos;
5. actores;
6. documentos;
7. informes;
8. reuniones.

El OpenAPI actual solo expone búsqueda global de documentos/evidencias mediante `/api/v1/search`; cualquier búsqueda unificada adicional necesita contrato Flask. Hasta entonces, la palette ofrece navegación, acciones y resultados respaldados por APIs existentes, y etiqueta los grupos no disponibles sin inventar resultados. No persiste títulos, snippets ni consultas sensibles en `localStorage`.

### 7.2 Acciones

- navegar a cualquier destino autorizado;
- ejecutar las mismas acciones autorizadas del menú `Crear`;
- abrir expedientes recientes de la sesión;
- cambiar tenant/workspace cuando proceda;
- abrir cuenta y atajos.

No incluye `Cambiar a Horizon`, rutas `/concept-*`, acciones sin permiso ni mutaciones directas sin formulario/confirmación.

### 7.3 Teclado

- `↑`/`↓`: mover selección;
- `Enter`: abrir/ejecutar;
- `Escape`: cerrar;
- `Tab`: recorrer controles del diálogo sin escapar del focus trap;
- el elemento activo usa `aria-activedescendant` o roving tabindex consistente.

## 8. Estado de navegación y URL

- búsqueda, filtros, sort, página y vista de tablas se codifican en query params allowlisted;
- drawers deep-linkables usan estado de URL centralizado, no `#fragment`;
- volver desde detalle restaura la URL completa de origen;
- cambios de tenant descartan todos los parámetros tenant-scoped;
- un filtro inválido se normaliza a un valor seguro y se refleja en URL;
- ningún secreto, token de invitación/reset o contenido sensible se copia a rutas de producto;
- una mutación no altera la URL hasta tener confirmación de servidor, salvo estados de formulario locales.

## 9. Transiciones y feedback

| Evento | Comportamiento |
|---|---|
| Navegación ordinaria | Mantener shell; skeleton localizado en contenido; título/breadcrumb se actualizan juntos |
| Abrir drawer | Conservar tabla; focus al heading/control inicial; URL deep-linkable |
| Cerrar drawer | Restaurar URL y foco a la fila/control que lo abrió |
| Abrir modal | Focus trap, título/descripción accesibles, fondo inerte |
| Mutación exitosa | Actualizar desde servidor, cerrar solo cuando corresponda y anunciar resultado |
| 401/session expired | Estado de sesión caducada con retorno interno seguro |
| 403 | Mantener shell/contexto, explicar permiso y ofrecer destino válido |
| 404 tenant/resource-safe | Mensaje neutro; no confirmar existencia en otro tenant |
| 409 | Mantener cambios del usuario, explicar conflicto y ofrecer recargar/comparar |
| 429 | Respetar espera informada y deshabilitar temporalmente reintento |
| Offline/transitorio | Conservar contexto, mostrar retry; no presentar estado obsoleto como confirmado |

La animación es discreta, dura como máximo lo necesario para expresar jerarquía y se elimina con `prefers-reduced-motion`.

## 10. Eliminación de navegación heredada

Prompt 12 debe eliminar del shell productivo:

- `Command Center`, `Expedientes`, `Radar`, `Oportunidades`, `Riesgos` o `Actores` enlazados a `/app/portfolio#...`;
- enlaces de cuenta/admin a `/concept-a/*`;
- acceso `Cambiar a Horizon` en command palette;
- label `Vector` en la marca;
- breadcrumbs derivados con `pathname.includes(...)`;
- menú duplicado por separado para desktop/móvil.

Los anchors de accesibilidad, como el skip link hacia `#main-content`, sí permanecen: no son navegación de producto. Los anchors internos de un documento largo también pueden existir si no sustituyen una ruta funcional.

## 11. Validación basada en tareas

La navegación se acepta cuando un usuario con permisos adecuados puede, con teclado y sin enlaces muertos:

1. abrir un expediente y sus señales;
2. revisar una señal y promoverla;
3. localizar riesgos críticos globales o recibir un estado explícito si falta el API agregado;
4. abrir un actor compartido en contexto de expediente;
5. crear reunión y acceder a briefing;
6. completar una tarea;
7. generar, revisar y descargar informe;
8. cambiar tenant sin restos visuales del anterior;
9. revocar una sesión;
10. administrar un miembro;
11. revisar Signal Avanza;
12. consultar auditoría;
13. distinguir producto, administración y plataforma en todo momento.
