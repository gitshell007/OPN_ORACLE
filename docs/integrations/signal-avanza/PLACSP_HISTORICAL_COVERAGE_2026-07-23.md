# Línea base de cobertura temporal PLACSP

**Medición:** 2026-07-23, Europe/Madrid
**Entorno:** producción Oracle autenticada, a través del proxy Flask
**Signal inspeccionado:** `opn_signal@8a36860`

## Resultado ejecutivo

Signal demuestra un histórico amplio de **adjudicaciones**, pero no un archivo aislable y probado
de **licitaciones/pliegos**. Por ello:

- `historical` se trata como adjudicaciones;
- `all` significa «todo el índice de licitaciones que Signal expone hoy», no «histórico completo»;
- Oracle no ofrece «solo inactivas» ni fusiona dos consultas;
- la cobertura de pliegos queda como dependencia explícita de Signal v2.

## Mediciones nuevas

La ruta productiva `/api/v1/procurement/stats` devolvió:

| Corpus | Métrica | Valor bruto |
|---|---:|---:|
| registro general | entradas | 12.951.651 |
| registro general | días procesados | 6.412 |
| registro general | ventana declarada | 2009-01-02 a 2026-07-23 |
| adjudicaciones PLACSP | entradas | 1.304.161 |
| adjudicaciones PLACSP | compradores distintos | 12.980 |
| adjudicaciones PLACSP | adjudicatarios distintos | 141.739 |
| adjudicaciones PLACSP | fuentes procesadas | 26 |
| licitaciones PLACSP | total del índice | 2.247 |
| licitaciones PLACSP | activas | 637 |
| licitaciones PLACSP | compradores distintos | 1.174 |

El recorrido real de Vector confirmó:

- filtro por defecto: 637 resultados;
- opción antigua «Todas»: 637 resultados, por lo que no era «todas»;
- llamada nativa equivalente a `active=false`: 2.247 resultados; en Signal v1 significa quitar el
  predicado de activas, no seleccionar solo inactivas.

## Anomalías que impiden prometer cobertura temporal

- adjudicación mínima declarada: `0001-01-03`;
- adjudicación máxima declarada: `2029-06-14`;
- fecha límite mínima del índice de licitaciones: `2020-06-29T14:00:00Z`;
- fecha límite máxima: `2035-05-30T23:59:00Z`;
- estados brutos observados: `PUB` y `EV`, sin enum contractual;
- el modelo de licitación de Signal no contiene `published_at`;
- la ruta fija su orden internamente y no admite sort;
- las búsquedas guardadas fuerzan activas y descartan el alcance temporal.

Las fechas sentinela, futuras y antiguas se conservan como evidencia de calidad; no se reinterpretan
ni se ocultan en esta medición.

## Evidencia previa todavía vigente

La auditoría previa registró **1.251 adjudicaciones de ITURRI** y una muestra de 30 referencias en
la que **0 de 30** resolvieron la licitación original. Esos datos sustentan el enfoque
award-céntrico, pero no se presentan como una repetición de hoy.

No se repitió una muestra estratificada por años de los lookups de Signal porque el workspace no
contiene una credencial de servicio de Signal y el proxy Oracle no expone el lookup unitario de
licitación al navegador. Inventar o extraer esa credencial violaría la frontera de seguridad. La
repetición queda como gate bilateral de v2: Signal debe producir la muestra desde el corpus
autoritativo, con manifiesto de versión y criterios de selección reproducibles.

## Inspección de implementación

En Signal v1:

- `active` tiene valor por defecto `true`;
- solo se añade `is_active=true` cuando el parámetro es verdadero;
- `active=false` no añade filtro;
- no existe alcance histórico nativo;
- no hay rangos por publicación/adjudicación ni orden configurable;
- `run` de una búsqueda guardada fuerza `active=true`.

En Oracle P0:

- omitir alcance deja que Signal aplique su compatibilidad actual;
- `scope=active` y `scope=all` se traducen a una única petición;
- `scope=historical` y rangos no soportados responden `422` antes de llamar;
- estados no contratados se muestran como `unknown`;
- las búsquedas no activas no se pueden guardar en v1;
- un test de integración cuenta `AIUsageLedger` antes y después del listado.

## Próxima medición

Signal debe reconstruir un índice sombra y publicar, por versión:

- recuentos por año y estado;
- fechas válidas y número de anomalías;
- expedientes con pliego y con adjudicación;
- tasa de resolución de adjudicación a expediente/pliego;
- muestra estratificada reproducible;
- orden y cursor de lectura.

Oracle repetirá entonces el test bilateral y solo habilitará `scope=historical` para licitaciones si
la cobertura queda demostrada.
