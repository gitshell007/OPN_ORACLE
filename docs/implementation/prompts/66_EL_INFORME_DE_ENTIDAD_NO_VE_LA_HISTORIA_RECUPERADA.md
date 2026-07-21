# 66 — El informe de entidad no ve la historia BORME recién recuperada (P1)

> Signal ha reindexado el BORME hacia atrás y ahora sirve actos desde 2009. **La ficha ya los
> muestra; el informe de IA no.** La causa es un tope que puse yo y que dejó de ser adecuado en
> cuanto cambió la forma de los datos.
>
> Medido en producción hoy, 2026-07-21. No hay que investigar la causa: está identificada. Lo que
> hay que decidir es el criterio de selección.

## Qué ha cambiado y qué se rompió

Antes de la reindexación, el índice de actos por entidad de Signal empezaba en 2019-2020. Ahora:

| Entidad | Actos antes | Actos ahora | Acto más antiguo |
|---|---:|---:|---|
| ITURRI SA | 65 | **81** | 2009-12-04 (antes 2020-12) |
| BURGOS CANTO MIGUEL (persona) | 17 | **26** | 2009-02-03 (antes 2020-04) |
| TELEFONICA SA | 120 | **705** | 2016-12 o anterior |
| INDRA SISTEMAS SA | 365 | **1.630** | — |
| EULEN | 205 | **475** | — |

La ficha web está bien: pagina de 50 en 50 (`REGISTRY_PAGE_SIZE`) y muestra todo.

**El informe de IA no.** `compact_entity_dossier` hace `_items(registry)[:registry_limit]` con
`registry_limit = 25`, y Signal devuelve los actos **del más reciente al más antiguo**. Es decir,
el informe se queda con los 25 más recientes.

Para ITURRI eso es demoledor, porque su distribución está muy sesgada:

```
2009:2  2011:4  2013:3  2014:1  2015:2  2016:3  2018:1
2020:1  2021:7  2022:2  2024:1  2025:3  2026:51
```

**51 de los 81 actos son de 2026.** Los 25 más recientes son todos de 2026, así que el informe no
ve ni un solo acto anterior a ese año: los 17 años de historia recuperados quedan fuera del
análisis y fuera de las citas.

El informe **sí declara** el recorte («Oracle solo ha pasado 25 actos registrales de 81») y sus
métricas agregadas sí cubren el corpus completo, porque se calculan en Python sobre todo. Así que
no miente. Pero puede afirmar «81 actos desde 2009» y a la vez ser incapaz de citar o comentar
nada anterior a 2026, que es justo la profundidad histórica que el cliente acaba de ganar.

## Por qué el tope existe (no lo quites sin leer esto)

`REGISTRY_ITEM_LIMIT = 25` no es arbitrario. Está medido en producción y documentado en el propio
fichero: cada acto se convierte en una fuente citable que el modelo enumera en su índice de
fuentes, así que **el número de actos fija el suelo de longitud de la salida**. Con 65 actos el
informe agotaba los 16.000 tokens y moría con `Invalid JSON: EOF`; con 25 se completa.

Existe además un techo global de 45 fuentes citables entre todos los tipos
(`EVIDENCE_SOURCE_TOTAL_LIMIT`), con reparto por turnos para que ninguna fuente desaparezca.

**Subir el tope a ciegas reintroduce un fallo que costó tres días de producción.** El problema no
es cuántos actos caben: es **cuáles** se eligen.

## Qué hay que conseguir

Que el informe vea una muestra que **represente la historia**, no solo la actualidad, sin superar
el presupuesto de salida.

No te doy la fórmula: decídela y justifícala. Pero el criterio de aceptación es concreto y
comprobable con el caso real:

- Con ITURRI SA (81 actos, 51 de ellos en 2026), la selección que ve el modelo **debe incluir actos
  anteriores a 2020**.
- La selección debe seguir siendo **determinista**: dos ejecuciones con el mismo corpus eligen los
  mismos actos, porque de ahí sale el `corpus_hash` y los UUID de evidencia reservada.
- El recorte se sigue declarando en `source_limits`, y ahora debe decir también **qué criterio** se
  usó, no solo cuántos actos se pasaron. Un analista que lea «25 de 81» tiene derecho a saber si
  son los últimos 25 o una muestra repartida en el tiempo.

Algunas direcciones razonables, por si ayudan: repartir el cupo por periodos (los más recientes
pesan más, pero cada tramo histórico conserva representación), o garantizar los N más recientes más
los M más antiguos más los hitos intermedios. Lo que **no** vale es un muestreo aleatorio: rompe el
determinismo.

Ten en cuenta que el sesgo no es igual en todas las entidades: EULEN y TELEFONICA reparten sus
actos de forma más uniforme, mientras que ITURRI e INDRA los concentran en los últimos años. La
solución tiene que funcionar en ambos casos, no solo en el que motiva este prompt.

## Verificación exigida

- Test con un corpus sintético que reproduzca el sesgo de ITURRI (la mayoría de actos en el año más
  reciente) y compruebe que la selección incluye actos antiguos. **Verifícalo por mutación**:
  volviendo al recorte `[:25]` por recencia, el test debe caer.
- Test de determinismo: dos llamadas con el mismo corpus devuelven exactamente la misma selección.
- Test de que el criterio queda declarado en `source_limits`.
- Suite completa con integración en verde y cobertura por encima del umbral.
- `ruff check`, `ruff format --check` y `mypy` nombrados por separado.

## Qué NO hacer

- **No subas `REGISTRY_ITEM_LIMIT` ni `EVIDENCE_SOURCE_TOTAL_LIMIT` como solución principal.** Si
  tras implementarlo crees que el tope debería moverse, dilo con la medición que lo respalde, pero
  no es el arreglo que se pide aquí.
- No toques la ficha web: pagina bien y ya muestra todo el histórico.
- No cambies el cálculo de `computed_metrics`: ya cubre el corpus completo y es correcto.
- No introduzcas aleatoriedad en la selección.
- No toques el prompt v2 del informe ni pidas nada a Signal: su parte está hecha.
