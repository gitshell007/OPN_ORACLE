# 44 — Paquete de UX de la ficha de entidad: sugerencias, grafo, filtro, pestañas y vínculo a expediente (P1)

> Prompt de producto para Codex. Seis mejoras de la ficha de entidad (`Actores`), todas verificadas
> en producción el 2026-07-17. Comparten componente y zona, por eso van juntas. Cada una lleva su
> diagnóstico ya hecho: no adivines la causa, está medida. Verifica en el navegador con datos reales
> (`ITURRI SA`, `ITURRI, S.A`); si no tienes sesión, decláralo como no verificado.

## 7.1 — Las sugerencias se quedan congeladas en las 3 primeras letras

Al escribir `ITURRI` en el buscador de entidad aparecen nombres que no pegan: `ITUAS SL`, `ITUBRE
SL`, `ITUGRA SL`, `ITUTCO SOCIEDAD LIMITADA`…

**Diagnóstico, confirmado contra Signal en vivo:** esa lista es **exactamente** la respuesta de
Signal para la consulta `ITU` (3 caracteres, el mínimo que dispara el suggest):

```
ITU    -> ITUITU SL, ITUAS SL, ITUBRE SL, ITUGRA SL, ITULLI SL, ITUMZA SL, ITURRI SA, ITUTCO SL
ITURR  -> ITURRI SA, ITURRIN SA, ITURRARAN SA, ITURRITEK SL, ...   (limpio)
ITURRI -> ITURRI SA, ITURRIN SA, ITURRI-BIDE SL, ...                (limpio)
```

**Signal funciona bien.** El bug es del frontend: las sugerencias de la primera consulta (`ITU`) no
se sustituyen al seguir tecleando. O no se re-dispara el suggest en cada pulsación, o las respuestas
llegan desordenadas y una respuesta lenta de `ITU` sobrescribe a la de `ITURRI` (carrera clásica).

**Se pide:** que las sugerencias reflejen siempre la consulta actual. Debounce en la entrada y
descarte de respuestas obsoletas (ignora toda respuesta cuya consulta no sea la del input en ese
momento — un contador de secuencia o un `AbortController` por consulta). Al vaciar el campo, se
limpian. Afecta al buscador de entidad de `src/components/entity-intel/entity-intel.tsx` y, si el de
adjudicatario de procurement tiene el mismo patrón, arréglalo igual y dilo.

## 7.2 — El grafo se comprime para caber; debe tener separación fija y dejar desplazar

El prompt 41 arregló que el grafo se dibujara en línea (siembra determinista en espiral de Vogel, ya
desplegada y correcta). Pero sigue **encajándose entero en el marco**: con 295 nodos, fcose los
comprime hasta que se solapan las etiquetas. El usuario prefiere **separación constante y legible,
aunque haya que desplazarse (pan)**, a que quepa todo de un vistazo ilegible.

**Se pide:** que el layout persiga una **distancia mínima fija entre nodos** (longitud de arista
ideal / `nodeSeparation` de fcose que no dependa del número de nodos), y que la vista inicial se
centre en la entidad consultada a un zoom donde se lean las etiquetas, dejando que el usuario haga
pan para recorrer el resto. No `fit` a todo el grafo. Revisa `initialGraphFocus` (~línea 393) y los
parámetros de fcose (~línea 660). No toques la siembra de Vogel ni los controles de zoom del 41:
funcionan.

## 7.3 — El filtro temporal debe ocultar, no atenuar

Hoy el cronograma **atenúa** (`is-dimmed`) los vínculos y nodos fuera del rango de fechas; la leyenda
incluye «Nodo fuera del rango». El usuario quiere que **desaparezcan**, no que queden grises.

**Se pide:** que `applyTemporalGraphFilter` (~línea 414) oculte los elementos fuera de rango
(`display: none` de Cytoscape) en vez de atenuarlos, **sin relayout** (que los que quedan no salten
de sitio — esto ya se respeta y debe seguir así). Quita de la leyenda lo que deje de aplicar.

**Ojo:** esto **revierte una decisión previa** — `STATUS.md` afirma que los nodos fuera de rango
«quedan atenuados». Actualiza `STATUS.md` y registra el cambio en `DECISIONS.md` para que la
documentación no se contradiga (una contradicción así ya nos mordió en la auditoría del 17-07).

## 7.4 — Abrir la información con doble clic, no con clic simple

Hoy un solo `tap` sobre un nodo abre la ficha de detalle (`instance.on("tap", "node", onTap)`,
~línea 716). Con grafos densos, un clic para hacer pan abre modales sin querer.

**Se pide:** que el detalle se abra con **doble clic / doble tap**; el clic simple queda para
seleccionar/hacer pan. Usa el gesto de doble pulsación de Cytoscape (o el umbral de dos taps
seguidos si tu versión no lo emite nativo). Mantén accesible por teclado la apertura del detalle del
nodo enfocado.

## 7.5 — Pestañas activas visibles y tablas ordenables

Dos cosas en la ficha 360º (`src/components/entity-intel/entity-dossier.tsx`):

- **Pestaña activa sin resaltar.** Las pestañas (Perfil / Órganos y cargos / Grafo / Noticias) usan
  Radix `Tabs`, que ya marca la activa con `data-state="active"` en el DOM — pero **el CSS no la
  estiliza**: en `concept-a.css`, `.entity-tabs` no tiene regla para `[data-state="active"]`.
  Añádela (subrayado o fondo, con contraste AA) para que se vea cuál está elegida.
- **Tablas sin ordenar ni filtrar.** La tabla de «Órganos y cargos» (y cualquier datatable de la
  ficha) debe poder ordenarse y filtrarse. Usa el patrón de datatable ya existente en el proyecto
  (TanStack Table, AGENTS.md §13) en vez de inventar otro. Como mínimo: ordenar por fecha, cargo y
  persona, y un filtro de texto. La ordenación por defecto, cronológica descendente.

## 7.7 — Falta el botón para añadir el actor a un expediente

Desde la ficha de una entidad no hay forma de vincularla a un expediente.

**Hallazgo:** el backend **ya tiene la capacidad** — `DossierActor` y `create_dossier_actor`
(`apps/api/src/opn_oracle/oracle/…`) existen y tienen permiso `actor.write`. El hueco es de interfaz.

**Matiz que debes resolver, no ignorar:** las entidades de esta ficha son **externas** (vienen de
Signal en vivo), y `DossierActor` vincula un **Actor interno** del tenant. Así que «añadir esta
entidad a un expediente» exige **materializar primero un Actor interno** a partir de la entidad de
Signal (nombre, tipo, identificador registral si lo hay, y traza de que procede de Signal), y luego
crear el `DossierActor`. Comprueba si ya existe un camino de alta de actor desde entidad externa
(pudo crearse en F1/F2); si existe, reúsalo; si no, créalo respetando tenant scoping, permisos y
evidencia (AGENTS.md §7 y §9). Selector de expediente destino, como en el «Fijar» de adjudicaciones.

Si materializar el actor resulta ser más de lo que cabe aquí, **para y dilo**: es preferible
entregar 7.1–7.5 y dejar 7.7 documentado en `OPEN_QUESTIONS.md` con el diseño, que meter a medias un
alta de actor sin evidencia ni aislamiento.

---

## Criterios de aceptación

- [ ] Las sugerencias siempre corresponden a la consulta actual; sin resultados obsoletos.
- [ ] `ITURRI SA` abre un grafo legible con separación constante y pan; no comprimido para caber.
- [ ] El filtro temporal oculta los elementos fuera de rango, sin relayout; leyenda y docs al día.
- [ ] El detalle de nodo se abre con doble clic; el clic simple no lo abre.
- [ ] La pestaña activa se distingue; las tablas de la ficha se ordenan y filtran.
- [ ] Existe un control para vincular la entidad a un expediente (o queda documentado por qué no).
- [ ] `npm run lint`, `npm run typecheck`, `npx vitest run`, `npm run build` verdes; y
      `scripts/api-test.sh --unit` si tocas backend (`uv` en `~/.local/bin/uv`).
- [ ] Verificado en el navegador con `ITURRI SA`; capturas antes/después.

## No hacer

- No toques la siembra de Vogel ni los controles de zoom del prompt 41.
- No arregles el suggest en Signal: Signal responde bien, el bug es del cliente.
- No materialices un Actor interno sin evidencia ni tenant scoping por ir rápido (7.7).
- No dejes la documentación contradiciendo el comportamiento nuevo del filtro (7.3).
- Nada de `bash -n`/typecheck como sustituto de abrir la app y mirarla.
