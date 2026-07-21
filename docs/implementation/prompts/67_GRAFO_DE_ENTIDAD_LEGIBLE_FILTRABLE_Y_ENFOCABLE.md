# 67 — El grafo de entidad es ilegible: espacio, filtro por rol y foco al seleccionar (P1 · UX)

> Prompt de producto para Codex, **frontend**. El grafo funciona técnicamente —trae los datos
> correctos y el layout es determinista— pero es inservible para un analista: con 141 nodos los
> nombres se pisan unos a otros y no hay forma de reducir el ruido.
>
> Verifícalo en el navegador con datos reales. Si no tienes sesión, decláralo como no verificado.

## El caso real que motiva esto

`/app/actors/entity/person/CASADO%20FERNANDEZ%20GONZALO`. Datos medidos hoy contra producción:

- **141 nodos** (132 personas, 9 empresas) y **186 aristas**
- Todas las aristas tienen fecha (186 de 186)
- Distribución de roles:

| Rol | Aristas |
|---|---:|
| Apoderado | **149** |
| Adm. Solid | 20 |
| Adm. Unico | 13 |
| Consejero | 9 |
| socio único / Socio único | 3 + 1 |
| Auditor | 2 |
| Presidente | 1 |
| Secretario | 1 |

Fíjate en dos cosas: **«Apoderado» es el 80 % de las aristas** (es el ruido que tapa la estructura
de gobierno), y **«socio único» aparece con dos capitalizaciones distintas**. Cualquier lista de
roles que construyas tiene que normalizar, o el filtro mostrará entradas duplicadas.

## Estado actual del código (para que no lo busques)

Todo está en `src/components/entity-intel/entity-intel.tsx`:

- Layout `fcose` con `GRAPH_FIXED_NODE_SEPARATION = 96`, `GRAPH_FIXED_EDGE_LENGTH = 190`,
  `padding: 42`. Semilla determinista en espiral de Vogel (`GRAPH_SEED_GOLDEN_ANGLE`,
  `GRAPH_SEED_RADIUS`) con `randomize: false`.
- Nodos de **30×30 px** con `label: "data(label)"` **siempre visible**, `font-size: 9`,
  `text-max-width: 130px`, `text-wrap: wrap`.
- `onZoom` **solo** actualiza el porcentaje de zoom; no gestiona etiquetas.
- `onTap` **solo** hace `setSelected(node)` y abre el diálogo en doble pulsación.
- Ya existen dos filtros que ocultan **sin relayout**, mediante clases: el temporal
  (`is-time-filtered`, `is-undated`, `is-orphaned-after-filter`) y el checkbox «Solo vínculos
  activos» (`activeOnly`, que recarga desde el servidor).
- `edgeRole(edge)` ya extrae el rol de cada arista. **El dato existe; no hay que tocar backend.**

## 1 — Legibilidad: los nombres se pisan

Subir la separación no basta y quiero que entiendas por qué antes de tocar los números: con 141
nodos, a un zoom que permita ver el grafo entero, **141 etiquetas compiten por el mismo espacio**.
Aunque separes los nodos, el problema reaparece porque el usuario se aleja para abarcarlo.

Necesitas resolver las dos mitades:

- **Espacio**: revisa `nodeSeparation` e `idealEdgeLength`. Ten en cuenta que un nodo mide 30 px y
  su etiqueta hasta 130 px de ancho: la separación actual (96) es menor que la anchura de una
  etiqueta, así que dos nodos vecinos se solapan por definición.
- **Densidad de etiquetas**: decide cuándo se muestra cada nombre. Opciones razonables, elige y
  justifica: por umbral de zoom, por importancia del nodo (el centro y los de mayor grado siempre),
  o solo las del nodo bajo el cursor / seleccionado y sus vecinos. **No elimines las etiquetas**:
  el analista necesita leer nombres, no bolitas de colores.

Criterio de aceptación: en la vista inicial de `CASADO FERNANDEZ GONZALO`, **ninguna etiqueta
visible se solapa con otra de forma que impida leerla**. Compruébalo a ojo en el navegador y
describe qué ves; esto no se puede demostrar solo con un test.

## 2 — Filtro por tipo de vínculo

Añade un control que permita mostrar u ocultar aristas por rol, **con todos los roles marcados por
defecto** (el comportamiento actual no cambia si el usuario no toca nada).

- La lista de roles se **deriva de los datos del grafo cargado**, no se codifica a mano: los roles
  vienen de Signal y varían por entidad.
- **Normaliza para agrupar**: «socio único» y «Socio único» son el mismo rol y deben aparecer una
  sola vez. Muestra el número de vínculos de cada rol junto a su nombre, como en la tabla de
  arriba: es lo que permite ver de un vistazo que «Apoderado» es el 80 %.
- Sigue el patrón ya establecido: ocultar por clases **sin relayout**, como el filtro temporal. El
  grafo no debe saltar ni recolocarse al marcar y desmarcar.
- **Debe componerse con los filtros que ya existen.** Un nodo o arista oculto por el filtro
  temporal sigue oculto aunque su rol esté marcado, y viceversa. Reutiliza o generaliza la lógica
  de `is-orphaned-after-filter` para que los nodos que se quedan sin vínculos visibles desaparezcan
  también, sea cual sea el filtro que los dejó huérfanos.

## 3 — Foco al seleccionar un nodo

Hoy pulsar un nodo solo rellena el panel lateral «Lectura rápida». Debe además **aislar ese nodo y
sus relaciones directas**, ocultando el resto.

- Al volver a pulsarlo (o al deseleccionar), se restaura la vista completa.
- Al aislar, el analista se queda con pocos nodos: aprovéchalo para **darles el espacio y las
  etiquetas que en la vista completa no caben**. Aquí sí tiene sentido reencuadrar o recolocar,
  porque el usuario ha pedido explícitamente concentrarse en algo.
- Al restaurar, la vista debe volver a ser **usable**, no al caos anterior: es la queja original del
  usuario, así que la solución del punto 1 tiene que seguir aplicándose después de restaurar.
- Ya existe `closedNeighborhood()` en `initialGraphFocus`; probablemente puedas reutilizar esa idea.
- El doble clic ya abre el diálogo de detalle: **no rompas ese gesto** al añadir el nuevo.

## Invariantes que no puedes romper

- **La semilla determinista.** El layout usa espiral de Vogel con `randomize: false` porque sin
  posiciones sembradas fcose producía grafos degenerados. No vuelvas a `randomize: true` ni quites
  la semilla.
- **Los filtros existentes siguen funcionando**: el temporal y «Solo vínculos activos».
- **Accesibilidad**: los controles nuevos se operan con teclado, tienen etiqueta accesible y
  contraste AA. Los nodos ocultos no deben quedar accesibles por tabulación ni anunciarse a un
  lector de pantalla.
- **Rendimiento**: este grafo tiene 141 nodos, pero hay entidades mucho mayores (INDRA acumula
  1.630 actos registrales). Filtrar y aislar no puede recorrer el grafo entero varias veces por
  cada clic.

## Verificación exigida

- Tests de que el filtro por rol se construye desde los datos, agrupa capitalizaciones distintas y
  parte con todo marcado.
- Test de composición: con el filtro temporal activo, marcar y desmarcar un rol no vuelve a mostrar
  lo que el filtro temporal oculta.
- Test de que seleccionar aísla los vecinos directos y deseleccionar restaura.
- **Cada test nuevo verificado por mutación**: di qué mutaste y qué test cayó.
- `npm run typecheck`, `npm run lint`, `npx vitest run` y `npm run build`, nombrados por separado.
- Verificación visual en el navegador sobre `CASADO FERNANDEZ GONZALO` con sesión real, describiendo
  qué se ve antes y después. Si no puedes, decláralo como no verificado en el resumen.

## Qué NO hacer

- No toques el backend ni pidas nada a Signal: los roles ya vienen en las aristas.
- No sustituyas fcose por otro motor de layout: el problema es de configuración y de densidad de
  etiquetas, no del algoritmo.
- No ocultes nodos por defecto ni cambies lo que se ve al entrar sin tocar nada, más allá de la
  mejora de espaciado y etiquetas. El usuario debe seguir viendo el grafo completo al abrirlo.
- No añadas dependencias nuevas para esto.
