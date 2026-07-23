# ORACLE-EXP-INV-01 · protocolo de medición v1

**Estado:** protocolo de spike; no es una política productiva ni autoriza investigar personas reales

**Fecha de corte del diseño:** 2026-07-23

## 1. Unidad y lenguaje

La unidad PLACSP es `folder_id + lot_id + revision`. La unidad BORME es una aserción registral
publicada con acto, fecha y localizador. El protocolo separa:

- `source_missing`: la fuente no publica el dato;
- `document_missing`: el expediente no ofrece el documento necesario;
- `parser_miss`: el dato existe pero el extractor no lo recupera;
- `identity_ambiguous`: el dato no individualiza de forma segura;
- `contract_field_missing`: Signal/Oracle no transporta un campo presente en origen.

«No localizado» nunca significa «no existe» ni «no se presentó».

## 2. Jerarquía de fuentes y uso

| Fuente | Uso en el spike | Persistencia | Límite |
|---|---|---|---|
| PLACSP sindicación 643 | marco alojado, resultados, ganador y recuento comunicado | solo métricas/hashes; bruto temporal en `.work` | no representa la familia agregada autonómica |
| PLACSP agregada | medir brecha territorial en muestra ampliada | igual | heterogeneidad del productor |
| documentos PLACSP | rol nominal, lote y localizador | extracto aceptado; bruto según D-028 | disponibilidad y formato irregulares |
| BORME/AEBOE | cargos, ceses, representación y socio único publicados | localizador/hash; sin identificador personal crudo | publicación histórica, no padrón vigente |
| Registro Mercantil | contraste puntual autorizado de nodos críticos | solo dato promovido/licencia/coste | pago, autenticación y condiciones de uso |
| Signal Avanza | productor vivo de runtime | contrato/versionado de Signal | el consumer local aislado aún no está disponible |
| Ollama local | extracción, triaje y crítica sobre corpus congelado | métricas y output sintético | nunca fuente ni autoridad de identidad |

Referencias oficiales:

- [Datos abiertos PLACSP](https://contrataciondelestado.es/wps/portal/DatosAbiertos).
- [Especificación de sindicación PLACSP](https://contrataciondelsectorpublico.gob.es/datosabiertos/especificacion-sindicacion.pdf).
- [API de datos abiertos del BOE](https://www.boe.es/datosabiertos/api/api.php).
- [FAQ de BORME](https://www.boe.es/datosabiertos/faq/borme.php).

## 3. Muestra PLACSP de decisión

La muestra ampliada tendrá 96 unidades, seleccionadas con PRNG y semilla congelados: 12 por cada
celda de:

```text
fuente {alojada 643, agregada}
× antigüedad {0–18 meses, 19–60 meses}
× complejidad {simple, multilote/multiganador/UTE}
```

Equilibrio marginal mínimo:

- 20 obras, 20 servicios y 20 suministros;
- 20 compradores AGE, 20 autonómicos y 20 locales/otros.

Si no aparecen al menos ocho casos de UTE, desierto/anulado, recuento ≥5 o PDF escaneado/tabla, se
crea un `top-up` separado. Esos casos no entran en tasas de prevalencia. Con `n=96`, una proporción
global en el peor caso tiene aproximadamente ±10 puntos al 95 %; cada celda de 12 solo sirve para
diagnóstico.

Etiquetas:

- fuente, expediente, lote y revisión;
- estado y ganador/grupo UTE;
- `ReceivedTenderQuantity = absent | n | conflict`, ámbito y duplicación;
- documentos, accesibilidad, formato, OCR y alcance de lista;
- participante literal, identificador si consta y rol
  `awardee | bidder_confirmed | lost | excluded | withdrawn | mentioned_unknown | unknown`;
- URL, SHA-256, fecha de corte y página/tabla/fragmento.

`lost` exige que el mismo lote pruebe la oferta y otro adjudicatario. Una UTE cuenta como grupo salvo
que la fuente defina otra semántica. El recuento repetido por varios ganadores se computa una vez por
lote y revisión.

## 4. Muestra BORME de decisión

La muestra ampliada tendrá 72 aserciones: 12 de cada estrato.

1. gobierno por persona física;
2. gobierno por persona jurídica;
3. representante físico de administrador jurídico;
4. socio único físico;
5. socio único jurídico;
6. sociedades profesionales, correcciones y otros casos difíciles.

Cada estrato combina seis publicaciones recientes y seis históricas, al menos cuatro provincias y,
cuando exista, una mitad con cese o revocación.

Etiquetas:

- literal de sociedad y contraparte;
- `counterpart_kind = person | company | unknown`, solo cuando la fuente lo demuestra;
- rol literal/normalizado, acción, fecha de publicación/efectiva y calidad;
- provincia, identificador BORME, URL y localizador;
- `identifier_present` booleano, nunca DNI/NIF personal crudo;
- corrección/errata y relación temporal.

Un match de Signal se contrasta por fuente, fecha, literal y rol. El nombre normalizado solo genera
un candidato.

## 5. QA y gates

- 25 % de doble etiquetado ciego y 100 % de ambiguos/PII.
- Wilson 95 % con numerador y denominador por celda.
- Adjudicaciones 643: Signal resuelve ≥95 %, concordancia exacta de expediente/lote/ganador ≥99 %
  y URL oficial 100 %.
- Recuento: concordancia XML ≥99 %, ámbito por lote/revisión y vacío como `unknown`.
- Participación documental: documento descargable ≥90 %, rol nominal ≥60 % global y ≥40 % por
  celda, localizador 100 %. La validación posterior necesita al menos 150 aserciones positivas sin
  error crítico para sostener el objetivo de precisión ≥98 % mediante regla de tres.
- BORME candidato: localizador 100 %, precisión de relación ≥99 %, recall ≥95 % por estrato y cero
  identificadores personales sin enmascarar.
- Tipo de contraparte automático: precisión ≥99 % y cobertura conocida ≥95 % en estratos jurídicos.
- Auto-merge de personas: no-go con independencia de la métrica.
- «Todos los participantes»: listas completas/reconciliadas ≥95 % en cada celda y cobertura tanto
  alojada como agregada.

Estos porcentajes son **gates operativos sobre estimaciones puntuales**, no una afirmación de
potencia estadística por celda. Con `n=12`, incluso 12/12 deja un límite inferior Wilson 95 % de
aproximadamente 75,8 %; con 96/96, aproximadamente 96,2 %. El informe mostrará siempre numerador,
denominador e intervalo y no convertirá un piloto pequeño en una garantía poblacional. Los 150
positivos sin error crítico son el corpus mínimo posterior para sostener el objetivo de precisión,
no sustituyen el muestreo por fuente y complejidad.

## 6. Frontera Signal/Oracle

El spike puede leer la fuente oficial y conservar temporalmente bruto en `.work`; no crea un
repositorio paralelo. El runtime futuro continúa pidiendo a Signal entidad, contratación y corpus
documental. Oracle conserva manifest, hashes, localizadores, claims y extractos promovidos. Retener
payloads/PDF completos exige revisar D-028 con licencia, volumen, retención y borrado explícitos.

Los benchmarks directos contra Ollama son instrumentación local. En producto, las llamadas usarán
task keys gobernadas por Signal y registrarán política, provider/model digest, tokens, latencia y
fallback efectivos.
