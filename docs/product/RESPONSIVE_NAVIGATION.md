# Navegación responsive de OPN Oracle

**Sistema visual:** Vector Command Center  
**Prioridad:** escritorio profesional, con operación completa en tablet y móvil  
**Viewports de aceptación:** 1440×900, 1280×800, 1024×768 y 390×844

## 1. Estrategia por rango

Los breakpoints responden al espacio útil, no al user-agent.

| Rango de viewport | Modo | Sidebar global | Subnavegación contextual | Tabla |
|---|---|---|---|---|
| `>= 1280px` | Escritorio amplio | Expandido por defecto; contraíble y persistido | Tabs/rutas visibles; `Más` solo si hay overflow real | Columnas operativas configurables |
| `1024–1279px` | Escritorio compacto | Rail compacto por defecto; se puede expandir superpuesto | Prioriza sección activa y primeras rutas; resto en `Más` | Columnas esenciales + selector de columnas |
| `768–1023px` | Tablet | Rail compacto o drawer; nunca roba el contexto principal | Barra horizontal controlada o selector `Sección`; activa siempre visible | Lista/tabla reducida con drawer de detalle |
| `< 768px` | Móvil | Drawer modal desde botón de cabecera | Selector de sección debajo del header de expediente | Cards/lista operativa; no tabla completa como única opción |

Las preferencias de sidebar se guardan por usuario para desktop/tablet, no por tamaño global. En móvil siempre inicia cerrado en cada navegación completa.

## 2. Escritorio amplio

### Shell

- sidebar persistente con ancho suficiente para labels completos;
- cabecera sticky con breadcrumbs, búsqueda, `Crear`, salud y notificaciones;
- contenido usa el ancho restante y un máximo solo en páginas editoriales, no en datatables;
- sidebar y cabecera no producen doble scroll;
- contraer sidebar no cambia orden, permisos ni rutas.

### Expediente

- encabezado contextual en dos líneas como máximo;
- métricas compactas con label y valor, no tarjetas gigantes;
- subnavegación de once secciones en una línea cuando quepa;
- al hacer scroll, se conserva una versión compacta con título, estado y sección activa.

### Overlays

- drawer de inspección: entre 420 y 560 px según contenido, nunca más del 50 % del viewport sin motivo;
- modal corto: ancho acorde al formulario, con acciones visibles;
- command palette centrada y acotada, con lista scrollable independiente.

## 3. Escritorio compacto y tablet

### Sidebar

- en 1024–1279 px se muestra como rail de iconos; expandirlo lo superpone al contenido, evitando reflow de tablas;
- en 768–1023 px puede conservar rail si hay espacio útil; si el contenido crítico cae por debajo de 720 px, usa drawer;
- iconos tienen tooltip, label accesible y target mínimo de 44×44 CSS px;
- grupos siguen siendo comprensibles al contraer mediante separadores y nombres en tooltip, sin depender solo del color.

### Cabecera

- breadcrumbs se truncan en el centro, no al principio ni en el destino;
- el trigger de búsqueda puede reducirse a icono + atajo accesible;
- `Crear` conserva texto cuando haya espacio; si se reduce a icono, su nombre accesible sigue siendo `Crear`;
- indicador de salud y campana no se esconden en avatar;
- las acciones de baja frecuencia pasan a `Más`, no las acciones primarias.

### Subnavegación

- la sección activa permanece visible;
- no se cambia el orden de las once rutas;
- el desbordamiento usa un menú `Más` con estado activo anunciado;
- en tablet estrecha, un botón `Sección: Señales` abre un popover/listbox con todas las rutas; no es un select nativo si pierde iconos/estado necesario, pero debe operar con teclado como listbox/menu.

### Contenido operativo

- filtros secundarios se alojan en un popover/drawer `Filtros` con conteo de activos;
- búsqueda, filtro principal, ordenar y crear permanecen visibles;
- selección masiva aparece como barra contextual y no empuja la cabecera fuera de pantalla;
- drawers pueden ocupar 60–70 % del ancho; siempre queda contexto suficiente o pasan a página completa.

## 4. Móvil

### Cabecera móvil

Orden:

1. botón `Abrir navegación`;
2. título corto o breadcrumb actual;
3. búsqueda;
4. notificaciones;
5. menú de acciones.

La cabecera no supera dos filas. Tenant activo se muestra dentro del drawer y en los contextos donde cambiarlo sea relevante; no se oculta de forma que el usuario desconozca la organización activa.

### Drawer de navegación

- `role="dialog"` o patrón equivalente con nombre `Navegación principal`;
- focus trap mientras está abierto;
- `Escape`, scrim y botón explícito cierran;
- al cerrar, el foco vuelve al botón de apertura;
- al elegir ruta, cierra antes de anunciar la nueva página;
- body queda bloqueado sin salto horizontal;
- incluye selector de tenant, grupos globales, administración autorizada y menú de usuario;
- no incluye rutas Horizon ni controles solo hover.

### Expediente móvil

El header prioriza:

- volver a Expedientes;
- título (máximo dos líneas);
- estado textual;
- acción primaria;
- selector de sección.

Scores y metadata secundarios se agrupan en `Ver contexto del expediente`, accesible y expandible. No se obliga a recorrer once tabs horizontales.

### Listados

Cada fila de tabla se transforma en card/list item semántico con:

- título y estado;
- expediente cuando la vista es global;
- 2–4 campos decisivos para la tarea;
- deadline/prioridad cuando aplique;
- acción primaria visible;
- menú secundario;
- target completo accesible sin anidar botones dentro de links inválidos.

El orden de información por recurso:

| Recurso | Campos esenciales móviles |
|---|---|
| Expediente | título, estado, owner, oportunidad/riesgo, última actualización |
| Señal | estado, título, expediente, relevancia/confianza, fecha |
| Oportunidad | título, expediente, score, estado, deadline, siguiente acción |
| Riesgo | título, expediente, score/nivel, estado, owner, mitigación próxima |
| Actor | nombre, tipo, roles, expedientes, influencia, confianza de identidad |
| Reunión | fecha, título, expediente, briefing, seguimiento |
| Tarea | título, expediente, owner, prioridad, estado, fecha límite |
| Informe | título, expediente, tipo, versión, estado, fecha |

Paginación, filtros y orden siguen en servidor. El usuario puede cambiar a tabla solo si el ancho lo permite; el scroll horizontal infinito no es la solución predeterminada.

### Drawers y páginas

- la inspección rápida se presenta como bottom sheet alto o página completa, según longitud;
- evidencia breve puede usar sheet; informe, briefing y configuración usan página completa;
- una sheet deja visible un handle solo como refuerzo, nunca como único control de cierre;
- acciones persistentes respetan safe areas y no tapan contenido/foco.

## 5. Menús, filtros y creación

### Menú `Crear`

- escritorio: dropdown anclado al botón;
- tablet: dropdown o popover ancho;
- móvil: bottom sheet con acciones autorizadas y contexto actual;
- al elegir una acción se cierra el menú y se abre el modal/página correspondiente con foco correcto;
- no se apilan dos focus traps a la vez.

### Filtros

- desktop: barra visible con filtros frecuentes;
- tablet: búsqueda + filtros esenciales y botón `Filtros (n)`;
- móvil: búsqueda, orden y botón `Filtros (n)`; el resto en sheet;
- `Aplicar` refleja estado en URL; `Limpiar` restaura defaults;
- cerrar sin aplicar conserva el estado anterior;
- los chips activos se pueden retirar por teclado.

### Command palette

- usa casi todo el ancho móvil con márgenes de 16 px;
- el teclado virtual no oculta el resultado activo;
- altura basada en `dvh`, no `vh` fijo;
- resultados conservan grupos y permisos;
- `Ctrl/⌘K` funciona con teclado externo, pero existe siempre trigger táctil.

## 6. Accesibilidad transversal

### Estructura y foco

- primer control: skip link visible al foco hacia `#main-content`;
- landmarks únicos y nombrados: `nav`, `header`, `main`, secundarios cuando proceda;
- orden DOM coincide con el orden visual esencial;
- foco visible con contraste AA en todos los modos;
- no se mueve foco por un simple cambio responsive;
- tras navegación, foco al `h1` o al inicio de `main` según patrón acordado;
- cerrar modal/drawer restaura el disparador, incluso tras error.

### Controles

- targets mínimos de 44×44 px en touch;
- tooltips no contienen información exclusiva y funcionan con foco;
- `aria-expanded`, `aria-controls`, `aria-current` y nombres accesibles reflejan estado real;
- badges y estados incluyen texto, icono o nombre accesible además de color;
- menús usan primitives con navegación teclado, typeahead y focus trap donde corresponda;
- modales tienen título, descripción, cierre y errores vinculados a campos.

### Movimiento y contraste

- con `prefers-reduced-motion: reduce`, drawers/modales aparecen sin desplazamiento animado y no hay scroll suave;
- el modo de alto contraste conserva bordes, foco y estado activo;
- zoom de navegador al 200 % no produce pérdida de funciones ni solapamiento;
- tamaños de texto no bajan de 14 px para datos operativos ordinarios; microcopy secundaria debe seguir siendo legible.

## 7. Safe areas, scroll y viewport

- usar `100dvh` para shells móviles;
- aplicar `env(safe-area-inset-*)` en cabecera, drawer y acciones sticky;
- `html/body` no deben ocultar overflow horizontal para enmascarar un bug;
- cada tabla o grafo puede tener su propio viewport solo cuando se anuncia y opera con teclado;
- overlays bloquean scroll de fondo y lo restauran exactamente;
- sticky headers no tapan anchors de accesibilidad ni headings enfocados (`scroll-margin-top`).

## 8. Estados responsive especiales

| Estado | Comportamiento |
|---|---|
| Loading | Skeleton con la misma geometría móvil/desktop; no salto de layout masivo |
| Empty | Mensaje, explicación y acción permitida; en móvil sin ilustración dominante |
| No results | Mantiene búsqueda/filtros visibles y ofrece limpiarlos |
| 403 | Shell y contexto visibles, acción segura para volver |
| 409 | Formulario conservado; comparación/recarga en layout legible |
| 429 | Tiempo de espera anunciado; botón temporalmente deshabilitado |
| Error de red | Contexto y filtros conservados; retry accesible |
| Sesión caducada | Página/modal de sesión sin exponer contenido tenant anterior |

## 9. Criterios de validación

En cada viewport de aceptación se comprueba:

- cero overflow horizontal en shell, menús, dialogs y formularios;
- navegación completa con teclado;
- foco no oculto por cabeceras sticky;
- apertura/cierre y retorno de foco de sidebar, filtros, command palette, modal y drawer;
- sección activa perceptible sin depender de color;
- tenant y contexto producto/admin/plataforma identificables;
- orden lógico idéntico entre desktop y móvil;
- tablas convertidas en lista/cards útiles en 390×844;
- acciones primarias visibles y secundarias accesibles;
- zoom 200 % y `prefers-reduced-motion`;
- ningún enlace productivo a anchor del portfolio ni a `/concept-a/*` o `/concept-b/*`.

La revisión visual debe registrar capturas de al menos `/app`, `/app/dossiers`, un expediente con sección contextual, `/app/account/sessions`, `/app/admin/members` y `/platform/tenants`, usando identidades con permisos diferentes cuando sea posible.
