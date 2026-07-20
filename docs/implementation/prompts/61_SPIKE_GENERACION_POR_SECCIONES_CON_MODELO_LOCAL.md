# 61 — Spike: ¿puede un modelo local escribir el informe si se genera por secciones? (investigación)

> **Esto es un spike, no una funcionalidad.** El entregable es una respuesta con números y una
> recomendación, no un cambio en el producto. Si al final el enfoque no convence, el spike habrá
> cumplido igual: sabremos que no, y por qué.
>
> **No conectes nada a producción, no cambies el flujo de informes, no despliegues.** El código que
> escribas es instrumental y desechable; márcalo como tal.

## La pregunta que hay que responder

Los dos informes narrativos comparten contrato editorial (1200-2000 palabras, párrafos de 60-150
palabras, secciones analíticas). Generados en producción:

| | Modelo | Cuerpo | Párrafos telegráficos |
|---|---|---|---|
| Informe de entidad | `openrouter / gemini-2.5-flash` | 1.778 palabras | 0 |
| Informe competitivo | `ollama / qwen3.5:9b` | 1.075 palabras | 5 |

Mismo contrato, misma versión: la diferencia es el modelo. La hipótesis a validar es que **el
problema de qwen3.5:9b no es de capacidad sino de formato de la tarea**: no falla por escribir mal,
falla por tener que emitir 2.000 palabras estructuradas en un único JSON, respetando esquema, sin
repetirse y citando bien.

**Pregunta concreta:** si en vez de pedirle el informe entero le pedimos **una sección cada vez**
(~200-300 palabras, contexto acotado, sin JSON global que cerrar) y ensamblamos en Python, ¿alcanza
la calidad del informe generado con modelo cloud?

Esto importa porque, si la respuesta es sí, Oracle podría producir informes de calidad **sin que
los datos de los clientes salgan de la infraestructura propia**. La motivación no es el ahorro: es
la soberanía del dato.

## Qué medir (y contra qué comparar)

Usa datos reales, no sintéticos. Tienes en producción el corpus del informe competitivo de
`ITURRI S.A` (expediente «Concurso bomberos») y el del informe de entidad de `ITURRI SA`. Puedes
leerlos por SSH; **solo lectura, nada de INSERT/UPDATE/DELETE**.

Genera con `ollama / qwen3.5:9b`, sección a sección, el informe competitivo, y compáralo contra dos
referencias que ya existen:

- **Línea base mala:** el mismo informe generado de una vez con qwen (1.075 palabras, 5 párrafos
  telegráficos).
- **Referencia de calidad:** el informe de entidad con gemini (1.778 palabras, 0 telegráficos).

Métricas, todas objetivas y comparables:

1. **Palabras por sección y totales.** ¿Entra en la horquilla 1200-2000?
2. **Párrafos telegráficos** (menos de 45 palabras). El monolítico dio 5; gemini dio 0.
3. **Repetición entre secciones.** Este es el riesgo real del enfoque: secciones escritas por
   separado tienden a repetir las mismas ideas. Mide solapamiento léxico entre secciones y di si
   se nota al leerlo.
4. **Contradicciones.** ¿Alguna sección afirma algo incompatible con otra? Es el segundo riesgo
   propio de generar por partes.
5. **Validez de citas.** Cada `evidence_id` citado debe estar entre los permitidos. Cero
   inventados, igual que exige el flujo real.
6. **Tiempo total.** Suma de las llamadas. El monolítico tardó ~5 minutos; el presupuesto mental
   es «hasta una hora de noche», así que hay margen de sobra: interesa saber el número real.

## Qué probar, en este orden

**1. Sección suelta.** Empieza por una sola sección real («Dependencia de organismos» sirve) con su
contexto acotado: los agregados que le tocan, sus evidencias citables y nada más. ¿Sale una sección
de 200-300 palabras bien redactada? Si aquí ya falla, para y repórtalo: la hipótesis es falsa y te
has ahorrado el resto.

**2. Informe completo por secciones, ensamblado en Python.** El modelo escribe prosa por sección;
**Python construye el `ReportOutput`**: título, orden, índice de fuentes, métricas y estructura. El
modelo no debe emitir nunca el JSON global. Ese es el corazón del enfoque.

**3. Mitigación de la repetición.** Si el punto 3 de las métricas sale mal, prueba a pasar a cada
sección un resumen breve de lo ya escrito. Mide si mejora **y cuánto tiempo añade**.

**4. Opcional, solo si sobra tiempo:** una segunda pasada que critique y reescriba cada sección.
Con modelo local el coste es tiempo, no dinero. Mide si aporta.

## Invariantes que el spike debe respetar

Aunque sea desechable, tiene que demostrar que el enfoque es **compatible con la gobernanza**, o no
sirve de nada:

- Los hechos solo pueden citar evidencia permitida, y cada sección recibe **su propio subconjunto**
  de evidencia citable. Si una sección cita algo que no se le pasó, el enfoque falla.
- Ningún agregado lo calcula el modelo: importes, conteos y porcentajes salen de Python, como ya
  hace el flujo actual.
- Nada de UUIDs en la prosa.

## Lo que NO hay que hacer

- **No modifiques el flujo de informes en producción** (`ai/service.py`, `reporting/service.py`,
  los jobs). Ni un `if`. El spike vive aparte.
- No añadas prompts nuevos al registro de prompts ni plantillas nuevas al registro de plantillas:
  eso los convierte en contrato. Si necesitas texto de prompt, tenlo en el propio script del spike.
- No despliegues ni toques Signal.
- No optimices para que salga bien. Si el enfoque solo funciona con un caso escogido a mano, eso es
  el resultado y hay que decirlo.

## Entregable

Un documento en `docs/implementation/spikes/61_generacion_por_secciones.md` con:

1. **La respuesta a la pregunta**, en la primera línea: ¿alcanza la calidad del cloud, sí o no?
2. La tabla de métricas comparando las tres versiones (qwen monolítico, qwen por secciones,
   gemini de referencia).
3. Qué salió peor de lo esperado. En particular repetición y contradicciones entre secciones: son
   el talón de Aquiles del enfoque y no quiero leer solo lo que salió bien.
4. **Coste real de llevarlo a producción**, con tu criterio tras haberlo hecho: qué piezas habría
   que tocar, si la cadena de jobs por sección encaja con los checkpoints y el lease actuales, y
   qué se rompería. Ten en cuenta que `CELERY_TASK_TIME_LIMIT` está en 720 s, así que un flujo
   largo pide una cadena de jobs cortos, no un job gigante.
5. Tu recomendación: adelante, adelante con condiciones, o no merece la pena. **Una recomendación
   negativa bien argumentada es un resultado excelente**, no un fracaso del spike.

El script instrumental puede quedarse en el repo si es útil para repetir la medición, pero en una
ruta que deje claro que no es producción y sin engancharlo a ningún job.
