# ORACLE-EXP-INV-02 · marcos oficiales congelados

**Fecha:** 2026-07-23

**Veredicto:** `GO` para etiquetar los marcos ya congelados; `NO-GO` para presentar todavía recall
de participantes/BORME o concordancia Signal. INV-02 completa el sorteo, no el gold humano.

## 1. Corrección aplicada antes de medir

El protocolo v1 de INV-01 mezclaba revisiones, lotes, familias de publicación y positivos
seleccionados por el mismo parser. Ejecutarlo literalmente habría producido una precisión
artificial. El [protocolo v1.1](77_investigation_protocol_v1_1.md) introduce:

- última revisión por colección+`entry/id`;
- máximo un lote por expediente en el core;
- alojada y agregada con denominadores separados;
- challenge sets raros fuera de prevalencia;
- muestra BORME de artículos elegida antes del detector;
- `counterpart_kind=unknown` hasta que una fuente autorizada demuestre el tipo;
- Signal comparado después del sorteo y sin exigir campos que su contrato v1 no transporta.

La semilla pública
`ORACLE-EXP-INV-02|frame-v1.1|2026-07-23` tiene SHA-256
`fbf46a773446f9b3e18a7862db9e6129d430d4f312b94af1c77f00b0ac8b1250`.

## 2. PLACSP: 96 unidades sorteadas

Se congelaron cuatro ZIP oficiales mensuales:

| Familia | Periodo | Bytes | SHA-256 |
|---|---:|---:|---|
| alojada 643 | 2022-01 | 45.799.404 | `2aaeabe528a9eb7ee5886483d3d99b43f5656bea05a02539d0e296bb9ee292a7` |
| alojada 643 | 2025-01 | 146.382.691 | `bda70aa0a7437d031e5d3f6114e5a637920ea1a460e1aba67d200209ae5eab7f` |
| agregada 1044 | 2022-01 | 5.542.586 | `4da1466802391d0e0bc7cceb394ad261e19821e1b2f9f205e61e1000bc65b0fe` |
| agregada 1044 | 2025-01 | 11.010.552 | `b7da8bbe279655985cff7f4c69667386ce2c5134467a74bfd5071aaf156c1dc6` |

El parser encontró 101.594 revisiones. Tras conservar primero la última entrada, exigir después
`TenderResult` y limitar a una unidad por productor+expediente quedaron 39.873 candidatos. Las ocho celdas
alcanzaron 12/12:

| Familia | Periodo | Simple disponibles | Complejas disponibles | Sorteadas |
|---|---:|---:|---:|---:|
| alojada | 2022-01 | 9.177 | 2.105 | 24 |
| alojada | 2025-01 | 13.515 | 2.825 | 24 |
| agregada | 2022-01 | 4.277 | 1.116 | 24 |
| agregada | 2025-01 | 5.503 | 1.355 | 24 |

Cobertura estructurada observada en el challenge set:

| Campo/flag | Alojada (n=48) | Agregada (n=48) |
|---|---:|---:|
| ganador estructurado | 47/48 | 45/48 |
| identificador del ganador cuando existe | 47/47 | 45/45 |
| `ReceivedTenderQuantity` | 48/48 | 47/48 |
| alguna referencia documental | 46/48 | 25/48 |
| desierto/sin ganador en algún resultado | 5/48 | 3/48 |
| UTE estructurada por literal | 1/48 | 1/48 |
| multiganador | 1/48 | 3/48 |
| recuento ≥5 | 12/48 | 6/48 |

Estos números describen el challenge set equilibrado y **no son prevalencia nacional**. La menor
presencia documental en agregada puede ser propiedad del canal reducido, no un fallo del parser.
El ledger local conserva URLs, literales y campos para comprobar descarga, relevancia, contenido
nominal, rol por lote y reconciliación. Esos cinco denominadores aún están sin etiquetar.

Hash reproducible de las 96 filas locales seleccionadas:
`2df77b21306b7562e143585f67085b618b3689c36c40ed5d514559a6b36735ae`.

## 3. BORME: marco independiente antes del detector

Se enumeraron todos los días de enero de 2022 y enero de 2025 mediante la API oficial:

| Periodo | Días publicados | 404 sin boletín | XML provinciales | Artículos |
|---|---:|---:|---:|---:|
| 2022-01 | 20 | 11 | 610 | 44.044 |
| 2025-01 | 21 | 10 | 647 | 51.667 |

De 95.711 artículos se sortearon 36 por periodo antes de ejecutar los detectores. El ledger de 72
artículos está preparado para segmentación exhaustiva y doble ciego; solo tras esa tarea podrá
medirse recall. Hash de la selección:
`c98b12f1a1a26806bd3bee920209ae8daa9fc5901384e2272cbe81d16e64fa90`.

Después se generó una cola diagnóstica de 192 candidatos, 24 por periodo y familia amplia
(`governance`, `sole_shareholder`, `representative`, `difficult`). Todos llevan
`counterpart_kind=unknown`. El detector encontró candidatos, no verdad:

| Familia candidata | 2022-01 | 2025-01 |
|---|---:|---:|
| gobierno | 36.632 | 41.880 |
| socio único | 4.822 | 6.385 |
| representante | 1.103 | 1.772 |
| corrección/profesional/difícil | 1.483 | 1.950 |

La cola debe ser adjudicada manualmente para formar las 72 aserciones difíciles. Estado actual:
**0/72 etiquetas gold**. Hash de la cola local reproducida:
`c60bf2101e6b1b92fe4032eb2527458930d945d51f7c0ccb6c36d1c930edfe2d`.

## 4. Signal: comparación no ejecutada

No existe una credencial efímera en el workspace. El resultado correcto es
`not_run_missing_ephemeral_credential`, con denominador medido cero; no `0/96`.

El cliente del spike solo admite:

- `GET /api/v1/consumers/me`;
- `GET /api/v1/registry/awards/{folder_id}`.

Rechaza secretos por argumento, claves compartidas, symlinks, permisos de grupo/otros, hosts no
exactos, HTTP, redirects y otras rutas. Agrupa la consulta por expediente.

Hay además un bloqueo upstream: Signal v1 no aplica scopes read-only a `/registry`; una credencial
de consumer también autentica mutaciones. El cliente GET-only reduce el riesgo operativo, pero no
es una garantía server-side. Para ejecutar la concordancia se necesita consumer temporal dedicado,
slug verificado, rate limit reducido y pausa/revocación auditada al terminar.

La comparación futura tampoco podrá medir `folder_id+lot_id+revision`: Signal no transporta
revisión, `ReceivedTenderQuantity`, identificador oficial del ganador ni no adjudicatarios, y solo
indexa 643. Las 48 agregadas deben informar `source_not_indexed_v1`, no reducir el recall 643.

## 5. Reanudación y privacidad

Una descarga BORME devolvió 503 durante la primera pasada. Se abortó sin convertir el error en
ausencia, se añadió retry limitado y la corrida terminó reutilizando los 629 documentos ya
verificados. La repetición completa produjo exactamente los mismos tres hashes de selección.

Los ZIP, XML, nombres, textos, ledgers y sidecars están en `.work/77/default`, con permisos
restrictivos y 272 MB locales. Git ignora ese directorio. Lo versionado contiene únicamente
protocolo, código, tests, hashes, conteos y este resultado.

No se crearon migraciones, endpoints, jobs, task keys ni filas de dominio. Filas afectadas: cero.

## 6. Verificación

- 28/28 pruebas específicas de INV-02;
- Ruff check y `ruff format --check` correctos sobre implementación y tests nuevos;
- mypy correcto sobre los 113 módulos productivos;
- suite backend completa con PostgreSQL y Redis reales: 603 tests, 84,52 % de cobertura;
- `git diff --check` correcto y cero ficheros `.work` trackeados.

Las mutaciones restauradas hicieron fallar regresiones de: namespace PLACE, última revisión,
productor, elegibilidad, celda incompleta, redacción, selección BORME independiente, fecha/hash
BORME, tipo desconocido, permisos/symlink/multilínea, HTTPS/host, allowlist de rutas, quoting,
redirect, payload parcial, slug efímero, agrupación y denominadores 643/1044.

No se ejecutaron frontend, build web ni smoke visual porque no cambió la aplicación ni su contrato.
El primer intento de `scripts/api-test.sh` no encontró Docker/variables y abortó antes de pytest;
se ejecutó después la receta oficial local con PostgreSQL/Redis, que completó el gate.

## 7. Siguiente gate

1. Etiquetar a doble ciego los 72 artículos BORME y el 25 % estratificado de PLACSP.
2. Adjudicar la cola para obtener las 72 aserciones challenge sin inferir tipo por nombre.
3. Descargar y clasificar documentos PLACSP de las 96 unidades; separar URL, descarga, relevancia,
   contenido nominal, rol y reconciliación.
4. Abrir en Signal scopes `registry:read` aplicados server-side y crear un consumer efímero.
5. Ejecutar la concordancia 643 por expediente; declarar 1044 fuera del índice v1.

Hasta completar esos pasos continúan en `NO-GO`: participantes nominales, expansión por
`counterpart_kind`, auto-merge, recall BORME y la promesa «todos los participantes».
