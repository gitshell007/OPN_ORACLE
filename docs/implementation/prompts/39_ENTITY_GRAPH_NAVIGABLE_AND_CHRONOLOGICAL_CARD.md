# 39 — Grafo navegable (zoom, encuadre y cronograma) y ficha cronológica (P1 · UX)

> Prompt de producto para Codex. Feedback directo del responsable tras usar la ficha 360º en
> producción el 2026-07-17 sobre `ITURRI SA` (295 nodos, 300 enlaces, 65 actos BORME).
> **No es una queja estética: la funcionalidad es inusable tal cual está.** Todo lo que se pide
> aquí es posible con los datos que Signal ya devuelve; no hace falta tocar el proveedor.

## Hallazgo 1 — El grafo nace ilegible y sin controles

Con `ITURRI SA` el grafo pinta 295 nodos amontonados en una maraña donde no se lee ni una
etiqueta. Causa, en `src/components/entity-intel/entity-intel.tsx`:

- El layout usa `fit: true` (línea ~483), que obliga a que **los 295 nodos quepan en el viewport**.
  Cytoscape baja el zoom hasta el mínimo y todo se solapa.
- El rango de zoom existe (`minZoom: 0.35`, `maxZoom: 2.2`, líneas ~386-387) pero **no hay ningún
  control en la interfaz** para usarlo. La rueda del ratón funciona, pero nada lo indica y en
  portátil sin ratón es inservible.

**Lo que se pide:**

1. **Encuadre inicial legible, no «todo cabe»**: la vista arranca centrada en la entidad
   consultada, a un zoom donde las etiquetas se lean. El resto del grafo se explora navegando, no
   se apelotona de entrada. Decide el criterio y documéntalo (p. ej. encuadrar la entidad central
   y su primer nivel, y dejar el resto fuera del viewport inicial).
2. **Controles visibles de zoom**: acercar, alejar, y volver al encuadre inicial. Accesibles por
   teclado y con `aria-label`, no solo iconos. Respeta `minZoom`/`maxZoom` o ajústalos si el nuevo
   encuadre lo exige, pero razona el cambio.
3. Con 295 nodos, plantéate si `randomize: true` en fcose ayuda o estorba: hoy cada carga da un
   dibujo distinto de la misma empresa, lo que impide reconocer la forma del grafo entre visitas.

## Hallazgo 2 — Falta el cronograma

Se pide un **control de rango temporal con dos manejadores** que vaya desde la fecha del primer
registro hasta la del último, y que **filtre el grafo en vivo** al moverlo.

**El dato ya está en el cliente**: `entity-intel.tsx` (líneas ~305-306) ya mapea `date` y `active`
de cada arista. Signal las devuelve. No hay que pedir nada nuevo al proveedor.

Decisiones que debes tomar **y documentar**, porque cambian lo que el usuario entiende:

- **Aristas sin fecha**: ¿se muestran siempre, se ocultan, o se agrupan aparte? Un vínculo sin
  fecha no es un vínculo inexistente; ocultarlo en silencio sería mentir por omisión.
- **Nodos que se quedan sin aristas visibles**: ¿desaparecen o quedan atenuados? Que no salten de
  posición al filtrar: **no relayoutes** con cada movimiento del slider, o el grafo se vuelve
  ilegible por otro motivo.
- **Relación con «Solo vínculos activos»**: ya existe ese toggle. Deja claro cómo se combinan los
  dos filtros y que el usuario entienda qué está viendo.
- Rendimiento: filtrar 300 aristas en cada `input` del slider debe ir fluido; usa el estilo de
  Cytoscape (clases) en vez de reconstruir elementos.

Accesibilidad obligatoria (AGENTS.md §13, WCAG 2.2 AA): manejables con teclado, con valores
anunciados, y el rango legible en texto — no solo la posición del manejador.

## Hallazgo 3 — La ficha obliga a irse a BOE, y esconde el 92% de los datos

Al abrir la ficha de un nodo hay que pinchar el enlace y leer el BORME en boe.es para enterarse de
algo. **No es necesario: el dato ya lo tenemos.**

Verificado contra Signal en producción para `ITURRI SA`:

```
TOTAL: 65   DEVUELTOS: 65   (con limit=100)
CLAVES POR ACTO: [action, company, date, person, province, role, source_url]
{"company": "ITURRI SA", "person": "PEREZ LANAQUERA CESAR IGNACIO", "role": "Apoderado",
 "action": "cese", "date": "2026-04-06", "province": "SEVILLA",
 "source_url": "https://www.boe.es/diario_borme/txt.php?id=BORME-A-2026-64-41"}
```

Y lo que hace hoy `src/components/entity-intel/entity-detail-dialog.tsx`:

- `recentActs()` (línea ~102) hace `registry.items.slice(0, 5)`: **muestra 5 actos de 65**. El
  recorte es arbitrario y silencioso: el usuario no sabe que faltan 60.
- Cada acto se pinta como `<strong>{role ?? act_type}</strong>` + `{action} · {date}` (líneas
  ~301-311): **descarta `person` y `province`**, que son la mitad de la información. En una ficha
  de empresa, cada acto trata sobre una persona concreta, y su nombre no aparece por ningún lado.
- El acto entero es un enlace a BOE. La fuente debe ser una **cita**, no la única forma de leer el
  contenido.

**Lo que se pide:**

1. Mostrar la información que ya tenemos **dentro de la ficha**: persona, cargo, acción, fecha y
   provincia. El enlace a BOE se queda como cita verificable, no como vía de escape.
2. **Organizar los actos por tiempo**, que es lo que se pidió y sigue sin hacerse: una línea
   temporal descendente legible, agrupada por año o por fecha, donde se vea la secuencia de
   nombramientos y ceses de un vistazo.
3. **Nada de recortes silenciosos**: si por espacio hay que paginar o plegar, dilo en la interfaz
   («65 actos») y da forma de ver el resto. Un `slice(0, 5)` sin avisar es el patrón que
   AGENTS.md §16 y la auditoría del 17-07 ya señalaron: aparentar completitud sin tenerla.

**Límite honesto que debes respetar:** Signal **no** devuelve el texto íntegro del acto BORME; solo
esos siete campos. No inventes contenido ni des a entender que la ficha reemplaza al BORME oficial.
Si el responsable quisiera el detalle completo (importes de ampliación de capital, objeto social),
eso requiere trabajo en Signal: **no lo hagas aquí**, anótalo en `OPEN_QUESTIONS.md` como pregunta
al productor.

---

## Criterios de aceptación

- [ ] `ITURRI SA` abre con un grafo **legible sin tocar nada**, centrado en la entidad consultada.
- [ ] Hay controles de zoom visibles y usables con teclado; se puede volver al encuadre inicial.
- [ ] El cronograma filtra el grafo en vivo entre la primera y la última fecha; el criterio para
      aristas sin fecha está decidido, documentado y es visible para el usuario.
- [ ] Los nodos no saltan de sitio al mover el slider.
- [ ] La ficha de un nodo muestra persona, cargo, acción, fecha y provincia sin salir de la app.
- [ ] Los actos se presentan en orden temporal y **no hay recorte silencioso**: se ve el total.
- [ ] Tests de UI con Cytoscape mockeado (ya existe el patrón) cubren encuadre, zoom y filtrado.
- [ ] `npm run lint`, `npm run typecheck`, `npx vitest run` y `npm run build` verdes.
- [ ] Backend: si no lo tocas, dilo. Si lo tocas, `scripts/api-test.sh --unit` **ejecutado**.
- [ ] `STATUS.md` actualizado con lo que se hizo y lo que quedó fuera.

## Verificación (obligatoria, con datos reales)

No vale un fixture de tres nodos: el bug solo aparece con volumen. Verifica en producción con
`ITURRI SA` (295 nodos, 300 enlaces, 65 actos) y con al menos una entidad pequeña, para comprobar
que el encuadre funciona en ambos extremos. Aporta capturas del antes y el después.

## No hacer

- No toques el contrato ni el proxy de `entity-intel`: los datos ya llegan.
- No ocultes datos para que el grafo «se vea mejor»: filtrar es del usuario, no tuyo.
- No sustituyas el enlace a BOE: es la evidencia citable (AGENTS.md §9), solo deja de ser la única
  puerta a la información.
- No metas librerías nuevas de gráficos: ya está Cytoscape con fcose.
- No des por bueno el resultado sin abrirlo en el navegador. La captura del responsable es de
  producción, con datos reales; la tuya también debe serlo.
