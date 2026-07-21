# 68 — Licitaciones: acciones desalineadas, sin orden y filtros a ciegas (P1 · UX)

> Prompt de producto para Codex, **frontend** salvo un punto que quizá toque la API de Oracle.
> Todo lo que sigue está medido hoy contra producción con sesión real, en `/app/procurement`.
> Verifica en el navegador; si no tienes sesión, decláralo como no verificado.

## 1 — Las acciones de cada resultado no forman grupo

Medido en el DOM sobre tarjetas reales (`.procurement-card`), los dos botones de una misma tarjeta:

| Botón | x | y | ancho |
|---|---:|---:|---:|
| Resumen | 302 | 660 | 111 |
| Fijar | 829 | 682 | 77 |

Están a **527 px de distancia horizontal** y **desalineados 22 px en vertical**. Son dos acciones
sobre el mismo expediente, pero visualmente no se leen como un par: una queda pegada al contenido y
la otra suelta a la derecha, ni siquiera a la misma altura.

Agrúpalas como lo que son —las acciones de esa tarjeta— con alineación y separación coherentes.
Revisa también el resto de botones de la página: hay 62 en total, así que si el patrón se repite en
la cabecera de resultados o en el panel de fijados, arréglalo con el mismo criterio en vez de
parchear solo la tarjeta.

Ten en cuenta el comportamiento en pantallas estrechas: si el grupo no cabe, debe apilarse de forma
predecible, no romper la tarjeta.

## 2 — Ordenar por fecha (y el detalle que lo complica)

Hoy **no se puede ordenar**. Los resultados llegan en el orden que decida Signal.

Cada licitación trae dos fechas: `deadline` (fin de plazo) y `feed_updated_at` (última
actualización en el feed). Decide cuál o cuáles tienen sentido ofrecer y justifícalo: para un
analista que busca a qué presentarse, el plazo suele mandar.

**Aquí está la trampa, y quiero que la resuelvas conscientemente:** la API de Oracle **no acepta
ningún parámetro de orden** (`TendersQuerySchema` en `integrations/procurement_routes.py` solo
admite `keywords`, `cpv`, `min_amount`, `max_amount`, `deadline_before`, `buyer`, `region`,
`active`, `limit`, `offset`). Y los resultados vienen **paginados**.

Ordenar solo lo que hay en pantalla produciría una mentira sutil: el usuario creería estar viendo
"las licitaciones que vencen antes" cuando en realidad son "las que vencen antes **de esta
página**". Eso es peor que no ordenar.

Tienes dos salidas legítimas. Elige y explica:

- Ordenar en servidor, lo que exige añadir el parámetro a la API de Oracle y comprobar si Signal
  puede ordenar; si no puede, decláralo como límite en vez de simularlo.
- Ordenar en cliente **dejando explícito en la interfaz** que el orden aplica al conjunto cargado,
  no a todo el corpus.

Lo que no vale es ordenar la página en silencio.

## 3 — Autocompletado de órgano comprador: ya tienes la fuente

`GET /api/v1/procurement/suggest?kind=buyer&q=...` **existe y funciona**. Verificado en producción
hoy:

```
q=ayunt&kind=buyer -> ["Ayuntamiento de Soneja", "Ayuntamiento de Loriguilla",
                       "Ayuntamiento Pleno de Ayuntamiento de Puente Genil", ...]
```

El esquema ya valida `kind` como `winner | buyer`, y la ruta tiene su límite de 90/minuto y su
caché de 300 s. **No hay que tocar backend para esto.**

Requisito del usuario: el campo sigue siendo de **texto libre**. Las sugerencias ayudan, no
obligan; si el analista escribe algo que no está en la lista, la búsqueda se hace igual.

Cuida lo de siempre en un autocompletado: no dispares una petición por cada tecla, permite navegar
y elegir con teclado, y no dejes que el desplegable tape el resto del formulario.

## 4 — Autocompletado de región: no hay fuente, decide de dónde sale

`suggest` **no admite `kind=region`**: solo `winner` y `buyer`. Pero los resultados sí traen el
campo `region`, con valores reales medidos hoy:

```
Madrid · Lugo · Valencia/València · Cuenca · Ávila · A Coruña · Málaga · España
```

Fíjate en dos cosas antes de elegir: son mayoritariamente **provincias**, pero aparece también
**"España"** (ámbito nacional), y hay grafías compuestas como **"Valencia/València"**. Cualquier
lista que construyas tiene que respetar los valores tal y como vienen, porque son los que se envían
como filtro: si "normalizas" a "Valencia", el filtro deja de casar.

Opciones razonables, elige y justifica:

- Acumular en Oracle las regiones ya vistas en resultados y en licitaciones fijadas, y ofrecerlas.
  Ventaja: cero dependencias y siempre coherente con lo que existe. Inconveniente: al principio
  está vacío y solo aprende de lo que el usuario ya ha buscado.
- Pedir a Signal un `kind=region` en `suggest`. Es lo más limpio a largo plazo, pero **no lo des por
  hecho**: si eliges esta vía, déjalo declarado como dependencia externa y entrega mientras tanto
  algo que funcione sin ella.

Igual que el comprador: **texto libre**, las sugerencias no cierran el campo.

## Verificación exigida

- Tests de que el autocompletado de comprador consulta `suggest` con `kind=buyer`, no bloquea la
  escritura libre y no lanza una petición por pulsación.
- Test del criterio de orden que elijas, incluido el caso paginado: debe quedar claro en la
  interfaz qué conjunto se está ordenando.
- Test de la agrupación de acciones de la tarjeta.
- **Cada test nuevo verificado por mutación**: di qué mutaste y qué test cayó.
- `npm run typecheck`, `npm run lint`, `npx vitest run` y `npm run build`, nombrados por separado.
- Si tocas la API de Oracle: `ruff check`, `ruff format --check`, `mypy src`, suite con integración
  y regeneración de OpenAPI y del cliente TypeScript.
- Verificación visual en `/app/procurement` con sesión real, describiendo el antes y el después de
  la tarjeta.

## Qué NO hacer

- No conviertas comprador ni región en desplegables cerrados: el usuario pidió expresamente poder
  escribir lo que quiera.
- No ordenes la página en silencio haciéndolo pasar por orden global.
- No inventes un catálogo de regiones a mano si no coincide con los valores que Signal envía: el
  filtro se compara contra esos valores.
- No toques el informe competitivo ni el panel de adjudicaciones: este prompt es la búsqueda de
  licitaciones.
