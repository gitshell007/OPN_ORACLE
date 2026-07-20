No todavia: qwen3.5:9b por secciones alcanza la forma editorial del informe cloud, pero no su calidad gobernada sin un validador/retry estricto de citas y exactitud por seccion.

# Spike 61 - Generacion local por secciones

## Resumen

La hipotesis queda parcialmente validada. Cuando qwen3.5:9b escribe una seccion acotada, produce prosa larga, legible y sin parrafos telegraficos. El informe ensamblado por Python entro en la horquilla editorial: 1.757 palabras, 0 parrafos por debajo de 45 palabras y solapamiento lexico bajo entre secciones.

La parte que no queda resuelta es gobernanza. En la ejecucion completa, el modelo no uso los alias de cita aunque estaban permitidos y explicados. No invento evidencias ni UUIDs, pero dejo los parrafos sin `evidence_ids`, lo que en el flujo real deberia fallar como evidencia insuficiente. Una prueba de control posterior, con la instruccion literal de terminar cada parrafo con `[E1]`, si produjo 3/3 parrafos citados con evidencia permitida; por tanto parece resoluble, pero solo con validacion automatica y retry por seccion.

## Datos usados

- Produccion leida por SSH en modo solo lectura, con consultas `SELECT` contra PostgreSQL dentro del compose productivo. No se ejecuto `INSERT`, `UPDATE`, `DELETE`, migracion, job, deploy ni Signal.
- Linea base mala: report `3e56d28d-321d-46f0-a228-fe92995ae32b`, `competitive_procurement.v2`, `ollama / qwen3.5:9b`, prompt `competitive_procurement_intelligence/v2`.
- Referencia cloud: report `4338f53d-501f-4e75-981d-1649a2c52610`, `entity_intelligence.v2`, `openrouter / google/gemini-2.5-flash`, prompt `entity_dossier_intelligence/v2`.
- Corpus competitivo real: `ITURRI S.A`, expediente `Concurso bomberos`, snapshot `competitive_procurement_analysis` ya congelado por Oracle.
- Modelo local del spike: `ollama / qwen3.5:9b`, descargado localmente para esta medicion.

## Metricas comparadas

| Version | Modelo | Palabras | Parrafos <45 palabras | Solapamiento lexico medio | Citas | Citas inventadas | Tiempo |
|---|---:|---:|---:|---:|---:|---:|---:|
| Qwen monolitico competitivo | `ollama/qwen3.5:9b` | 1.118 | 5 | 0,177 | 19 | 0 | job 314,6 s; proveedor 169,9 s |
| Qwen por secciones | `ollama/qwen3.5:9b` | 1.757 | 0 | 0,094 | 0 | 0 | 143,3 s |
| Gemini referencia entidad | `openrouter/gemini-2.5-flash` | 1.794 | 0 | 0,062 | 71 | 0 | job 56,4 s; proveedor 50,9 s |

Nota: el contador del spike usa el mismo tokenizador para las tres versiones. La medicion historica del informe competitivo daba 1.075 palabras; con este contador reproducible salen 1.118, pero la comparacion relativa no cambia.

## Palabras por seccion

| Seccion qwen por secciones | Palabras | Parrafos |
|---|---:|---:|
| Resumen ejecutivo | 231 | 3 |
| Posicion en el mercado | 270 | 3 |
| Dependencia de organismos | 254 | 2 |
| Comportamiento en precio | 197 | 2 |
| Alianzas y UTEs | 197 | 2 |
| Lectura estrategica | 292 | 3 |
| Cobertura y limites | 316 | 3 |

La seccion suelta pedida primero, `Dependencia de organismos`, salio bien en forma: 269 palabras, 2 parrafos de 141 y 128 palabras, 17,8 s. Fallo en citas: no uso `[E1]`.

## Repeticion

El enfoque por secciones redujo la repeticion frente al monolitico: el solapamiento lexico medio bajo de 0,177 a 0,094. En lectura manual no se nota como informe pegado con piezas repetidas; `Lectura estrategica` reutiliza ideas de posicion, compradores y precio, pero lo hace de forma esperable para una seccion de sintesis.

La mitigacion con resumen previo no mejoro: subio el total a 1.971 palabras, aumento el solapamiento a 0,119 y anadio 11,6 s. Tambien genero parrafos demasiado largos en `Lectura estrategica` (172 y 162 palabras), fuera del contrato de 60-150. Para este caso, el resumen previo no merece la pena.

## Contradicciones y derivas

No vi contradicciones frontales entre secciones. El problema real fue la deriva interpretativa:

- El texto habla a veces de "licitaciones con exito" cuando el corpus mide adjudicaciones publicadas, no licitaciones presentadas.
- En una variante menciona "entidades privadas" al describir compradores, aunque el corpus es contratacion publica.
- Interpreta algunos CPV como "servicios generales de mantenimiento", lectura demasiado libre para los agregados disponibles.
- En la variante con resumen previo afirma que grandes compradores militares garantizan un "minimo vital de ingresos recurrentes"; eso es una inferencia excesiva.

Esto queda por debajo de Gemini: la referencia cloud tambien interpreta, pero se mantiene mas cerca de los limites declarados y cita mas densamente.

## Validez de citas

La version seccional completa tuvo 0 citas, 0 inventadas y 0 UUIDs en prosa. Eso no basta para produccion: aunque no inventa fuentes, tampoco ancla los parrafos a evidencias.

Prueba de control: repeti solo `Dependencia de organismos` con una restriccion mas dura, "cada parrafo debe terminar literalmente con `[E1]`". Resultado: 287 palabras, 3 parrafos, 3/3 parrafos con `[E1]`, y Python mapeo las tres citas al evidence_id permitido `da7c972e-d918-40f0-beea-98608030ddc9`. Esto sugiere que el enfoque puede ser compatible con gobernanza, pero no por confianza en el modelo: necesita validador y retry automatico por seccion.

## Tiempo

- Seccion suelta: 17,8 s.
- Informe por secciones sin mitigacion: 143,3 s para 7 llamadas.
- Informe por secciones con resumen previo: 154,9 s para 7 llamadas.
- Prueba de control de citas: 20,8 s.

El tiempo puro de generacion local es aceptable para un proceso nocturno o asincrono. Aun asi, produccion no deberia meterlo en un unico job largo: con reviewer, retries, locks, fallos de Ollama y renderizado, se acerca demasiado al limite operativo. `CELERY_TASK_TIME_LIMIT=720 s` pide una cadena de jobs cortos con checkpoint por seccion.

## Coste real de productivizar

No es un cambio pequeno sobre el flujo actual. Hoy `process_report` y `execute_agent` asumen una llamada de agente, un output estructurado y un revisor obligatorio posterior. El enfoque seccional necesita una orquestacion nueva:

- Un plan de secciones versionado por plantilla, con `section_key`, presupuesto, subconjunto de agregados y subconjunto de evidencias permitidas.
- Un job padre de informe y jobs hijos por seccion, idempotentes por `report_id + section_key + corpus_hash + prompt_version`.
- Checkpoints durables por seccion para poder reintentar sin perder lo ya generado.
- Un validador por seccion: rango de palabras, parrafos 60-150, cero UUIDs, citas por alias solo dentro del subconjunto permitido, y fallo si hay hechos sin evidencia.
- Retry/repair por seccion cuando falten citas o el texto viole formato.
- Ensamblador Python que construya `ReportOutput`, `source_index`, `facts/inferences/recommendations` y snapshot final sin pedir JSON global al modelo.
- Revisor final obligatorio sobre el informe ensamblado, probablemente usando el paquete compacto del Prompt 60.
- Auditoria y usage ledger capaces de representar varias llamadas de generacion para un mismo informe.
- En Signal, si se mantiene la gobernanza de tasks, habria que definir o parametrizar una task seccional; no basta con reutilizar ciegamente la task global si Signal espera un output JSON completo.

Lo que se romperia si se enchufa de forma directa: lease unica del job, semantica actual de `AIArtifact`, conteo de intentos, error handling, revision de evidencia y expectativa de un unico schema Pydantic devuelto por el proveedor.

## Recomendacion

Adelante con condiciones, no como sustitucion inmediata.

El spike demuestra que el problema principal de qwen3.5:9b no es solo capacidad linguistica. Al quitarle el JSON global y repartir el trabajo por secciones, desaparecen los parrafos telegraficos y el informe entra en la horquilla 1.200-2.000 palabras. Esa parte es prometedora para soberania del dato.

Pero no alcanza todavia la calidad cloud porque falla una propiedad esencial: disciplina de evidencia. La siguiente fase deberia ser otro spike mas acotado, no una feature: generar solo dos secciones con prompt estricto de alias, validador automatico y un retry de reparacion, midiendo si llega a 100 % de parrafos citados sin aumentar derivas factuales. Si eso sale verde, entonces si merece disenar la cadena productiva de jobs por seccion.

