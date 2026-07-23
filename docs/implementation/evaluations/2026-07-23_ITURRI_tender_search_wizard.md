# Evaluación del wizard de búsqueda · ITURRI

Fecha de ejecución: `2026-07-23`.

## Veredicto

La regresión determinista corregida de `AI_MODE=mock`, con veinte CPV y veinte términos,
recuperó **127 de 154 adjudicaciones: 82,5 %** y supera por 0,7 puntos la línea base de
**126/154: 81,8 %**. El control temporal estricto, aprendido solo del 80 % antiguo, empata
exactamente el **81,8 %**. El mock cumple el gate, pero no prueba calidad del modelo real:
se limita a copiar los candidatos medidos del grounding.

El intento inicial con Ollama `qwen3.5:9b` demostró que su compilador de gramática no acepta
este JSON Schema y respondió HTTP 400. Se incorporó un boundary gobernado específico para el
wizard: `format=json`, `think=false` y validación Pydantic obligatoria antes de admitir la
salida. La repetición a través de `OllamaLLMProvider.generate_structured` funcionó, pero el plan
recuperó **101/154: 65,6 %**, **−16,2 puntos** frente a la línea base.

Por tanto, el gate del mock y el de compatibilidad Ollama quedan verdes; el gate de calidad del
modelo real permanece abierto.

## Corpus y planes

- Fuente: histórico de adjudicaciones de Signal, consultado desde el runtime de producción
  existente, exclusivamente en lectura.
- Empresa solicitada: `ITURRI, S.A`; normalizada por Signal: `ITURRI`.
- Filas: 1.252; expedientes agrupados: 769; truncado: no.
- Entrenamiento: 615 expedientes, `2017-11-27` → `2025-08-26`.
- Holdout: 154 expedientes, `2025-08-27` → `2026-07-16`.
- Cinco filas fuente no tenían fecha, pero ningún expediente agrupado quedó fuera del split.

| Plan | CPV | Términos | CPV hits | Term hits | Combinado |
|---|---:|---:|---:|---:|---:|
| Línea base determinista | 20 | 20 | 70/154 (45,5 %) | 110/154 (71,4 %) | **126/154 (81,8 %)** |
| Mock inicial, antes de corrección | 10 | 10 | 50/154 (32,5 %) | 95/154 (61,7 %) | **105/154 (68,2 %)** |
| `AI_MODE=mock` corregido, grounding completo | 20 | 20 | — | — | **127/154 (82,5 %)** |
| Control mock, grounding train-only | 20 | 20 | 70/154 (45,5 %) | 110/154 (71,4 %) | **126/154 (81,8 %)** |
| Ollama `qwen3.5:9b`, adapter gobernado | 3 | 23 | — | — | **101/154 (65,6 %)** |

El primer plan mock, conservado para documentar la regresión que motivó la corrección, fue:

```json
{
  "candidate_cpv": [
    "18100000",
    "18143000",
    "34144210",
    "18110000",
    "34144212",
    "18141000",
    "35113400",
    "35812000",
    "44482100",
    "18000000"
  ],
  "include_terms": [
    "proteccion",
    "personal",
    "incendios",
    "equipos",
    "vehiculos",
    "individual",
    "vestuario",
    "extincion",
    "bomberos",
    "uniformidad"
  ],
  "synonyms": [],
  "exclude_terms": []
}
```

El proveedor `mock-oracle-v1` corregido y la post-validación real se ejecutaron localmente con
`AI_MODE=mock`: 20 CPV válidos, 20 términos, cero descartes y `scope=active`. El holdout se
evaluó después contra Signal en lectura. No se ejecutó `execute_agent` contra producción:
habría creado `AIArtifact`, `AIAuditLog` y `BackgroundJob`, contradiciendo el requisito de no
modificar producción.

## Ejecución Ollama real

Se usó el prompt `tender_search_wizard/v1.md`, el contexto medido de ITURRI y el modelo local
`qwen3.5:9b`, sin base de datos ni llamadas externas. La primera versión del adapter, con
`format=TenderSearchWizardOutput.model_json_schema()`, falló antes de inferir:

```text
HTTP 400 · Failed to initialize samplers: failed to parse grammar
```

El adapter se corrigió de forma acotada al agente: el wizard usa `format=json` y `think=false`,
pero no cruza el boundary si `TenderSearchWizardOutput.model_validate_json` falla. La ejecución
final a través de `OllamaLLMProvider.generate_structured`, seguida de la post-validación real,
obtuvo:

- latencia registrada por el adapter: 62.522 ms;
- tokens: 1.284 de entrada y 468 de salida;
- JSON válido conforme a `TenderSearchWizardOutput`;
- tres términos descartados por duplicidad o conflicto;
- tres CPV válidos y 23 términos/sinónimos normalizados;
- recall combinado: **101/154 = 65,6 %**;
- brecha: **−16,2 puntos porcentuales**.

Los CPV propuestos fueron `18100000`, `34144210` y `50110000`. El modelo amplió términos con
`contraincendio`, `epi`, `camiones`, `trajes`, `rescate` y variantes en singular, pero perdió
familias CPV y términos frecuentes suficientes para igualar la aritmética. Las exclusiones no
se aplicaron al recall por la limitación explicada más abajo.

Una petición diagnóstica directa previa, con el mismo override, tardó 25.353 ms y produjo el
mismo plan. Una primera repetición por el adapter devolvió contenido vacío tras una espera larga;
la siguiente terminó correctamente. Esto apunta a variabilidad operativa local que debe vigilarse,
pero no altera el resultado funcional: cualquier salida vacía o inválida se rechaza.

## Semántica real de `keywords` en Signal v1

Medición realizada con `scope=all` (`active=false`), consultas independientes y resultados
nativos sin fusionar. La cadena de varias palabras se comporta como **subcadena literal
contigua**, no como AND ni OR booleano. Las tildes también son significativas. Las comillas
no activan una sintaxis de frase: pasan a formar parte del texto buscado.

| `keywords` crudo | Total |
|---|---:|
| `proteccion` | 6 |
| `personal` | 65 |
| `proteccion personal` | 0 |
| `personal proteccion` | 0 |
| `"proteccion personal"` | 0 |
| `proteccion de datos` | 2 |
| `proteccion datos` | 0 |
| `equipos` | 65 |
| `incendios` | 28 |
| `equipos incendios` | 0 |
| `equipos de sonido` | 1 |
| `extinción` | 7 |
| `extincion` | 0 |
| `extinción de incendios` | 7 |
| `camión-escenario` | 1 |
| `camion-escenario` | 0 |

Ejemplos crudos devueltos:

- `proteccion de datos` → `SER/2026/0000114524`, «Servicio de Consultoria y Asistencia
  tecnica consistente en la evaluacion de impacto de proteccion de datos personales…»;
  `SE18986/2025`, «servicio de delegado/a de proteccion de datos…».
- `equipos de sonido` → `1857538P`, «El alquiler de un camión-escenario con equipos de
  sonido, iluminación, audiovisuales y personal técnico…».
- `extinción de incendios` → `10/2026-Suministros`, «Suministro de vestuario técnico…
  del servicio de extinción de incendios…»; `162/2026`, «adquisición de 400 cascos F2XR
  para rescate técnico y extinción de incendios…».

Consecuencia contractual: Oracle no debe concatenar chips. Una sonda por término tokenizado,
en bloques independientes y con presupuesto top-N, conserva la semántica real y evita fingir
un orden global.

## Semántica del recall offline

El arnés pliega `include_terms` y `synonyms` con
`spanish-procurement-stopwords-v1` y evalúa OR entre tokens sobre los títulos del holdout.
Los CPV se validan contra la taxonomía local y coinciden de forma exacta tras normalización.
`exclude_terms` no se puntúa: Signal v1 no ofrece un operador NOT demostrado y este ground
truth solo contiene positivos conocidos, no negativos con los que medir precisión.

Esta métrica offline mide la capacidad del plan completo. La vista previa productiva mantiene
un presupuesto menor de sondas visibles; no se deben confundir ambos límites.

## Reproducción

Con acceso configurado a Signal:

```bash
PYTHONPATH=apps/api/src \
python scripts/evaluate_comparable_profile.py \
  --company "ITURRI, S.A" \
  --plan-json /ruta/plan.json \
  --plan-label AI_MODE_mock_grounded \
  --skip-tender-smoke
```

El parámetro `--plan-json` acepta una ruta, JSON inline o un artefacto envuelto bajo `plan`,
`output`, `result` o `validated_output`.

## Limitaciones

- Los totales de licitaciones son una fotografía mutable del `2026-07-23`, no un contrato
  estable ni recall histórico.
- La sensibilidad a tildes se observó empíricamente, pero Signal todavía no la declara en un
  contrato versionado.
- Evaluar el grounding completo contra el holdout introduce fuga temporal. Por eso se ejecutó
  también el control train-only, que empata la línea base sin esa ventaja.
- El proveedor real sí se ejecutó localmente, pero no mediante el pipeline durable y no contra
  la base de datos de producción. El pipeline habría escrito auditoría.
- El FAIL inicial del mock se conserva como historial; la corrección top-20 ya supera el gate.
- El PASS 82,5 % con perfil completo contiene fuga temporal. El control train-only 81,8 % es la
  cifra causalmente comparable.
- La regresión mock no demuestra calidad del LLM: el resultado de Ollama (65,6 %) confirma que
  esa evaluación debe permanecer separada.
- AI_MODE=ollama funciona mediante el override acotado y validación posterior obligatoria. Queda
  pendiente mejorar el recall del plan real y medir la variabilidad de latencia/resultado.
