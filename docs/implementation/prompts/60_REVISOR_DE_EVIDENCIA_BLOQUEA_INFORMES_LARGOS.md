# 60 — El revisor de evidencia trunca y bloquea los informes largos (P0, producción)

> Bug de producción encontrado al verificar el prompt 59. **El informe competitivo no se puede
> generar**: no falla el informe, falla el paso de revisión que viene después.
>
> Diagnóstico ya hecho con evidencia. Léelo antes de tocar nada: la causa aparente no es la real.

## Qué pasa, medido

Job `8e313bbf-f879-4e42-9667-fc649ceab890` en producción, expediente «Concurso bomberos»,
adjudicatario `ITURRI S.A`, plantilla `competitive_procurement` v2:

```
failed | progress 65 | El job no pudo completarse.
Causa: 1 validation error for EvidenceReviewerOutput
       Invalid JSON: EOF while parsing a val...
```

Lo importante: el error es de **`EvidenceReviewerOutput`**, no de `ReportOutput`. El informe se
generó; lo que se corta es el **revisor de evidencia** que corre después.

Tardó ~5 minutos antes de fallar, con el job clavado en `progress 65`.

## Por qué

En `ai/service.py` (≈líneas 526-540), tras generar cualquier agente que no sea el propio revisor,
se lanza una segunda llamada:

- El revisor recibe **el informe completo** como entrada: `effective_payload | {"candidate_output": output}`.
- Su presupuesto de salida es `min(reviewer_prompt.max_output_tokens, policy.max_output_tokens)`.
- Y `reviewer_prompt.max_output_tokens` sale del catch-all de `ai/registry.py`:
  `if name != "dossier_situation_summary": return 2000`.

Es decir: **2000 tokens fijos, heredados de cuando todos los informes eran cortos.** Los prompts 56
y 59 triplicaron la longitud de los informes (de ~1.100 palabras troceadas a 1.200-2.000
redactadas) y nadie revisó el presupuesto del revisor. Subir el techo del informe **movió el fallo
aguas abajo**.

### Por qué el informe de entidad no falla y este sí

No es que el de entidad esté a salvo: es que va por **OpenRouter/gemini-2.5-flash**, mientras que
`competitive_procurement_intelligence` está gobernado en Signal sobre **`ollama/qwen3.5:9b`
local**. El de entidad genera 1.778-2.023 palabras sin problema; el competitivo, con el mismo
contrato pero modelo local, se queda sin salida en la revisión.

**No des por bueno que el de entidad está bien solo porque hoy pasa.** Comparte el mismo revisor y
el mismo techo de 2000: está igual de expuesto, y solo lo salva un modelo más capaz.

## Qué investigar antes de decidir el arreglo

No apliques la solución obvia («subir 2000 a X») sin comprobar esto primero, porque puede ser
tratar el síntoma —error que ya cometimos con este mismo módulo, subiendo el techo del informe de
5000 a 8000 y a 16000 sin que convergiera nunca:

1. **¿Qué devuelve realmente el revisor?** Mira `EvidenceReviewerOutput` en `ai/schemas.py`. Si su
   contrato le obliga a repetir contenido del informe (fragmentos, listas de claims), el problema
   no es el techo sino el contrato: un revisor debería emitir un **veredicto**, no una copia. En
   ese caso la salida correcta es acotar su contrato, no ampliarlo.
2. **¿Cuánto entra?** El revisor recibe el informe entero más el payload original, que en el
   competitivo incluye los agregados de contratación. Comprueba si el problema es de contexto de
   entrada y no de salida.
3. **¿Necesita el revisor el informe completo?** Su cometido es comprobar groundedness y
   seguridad: quizá le baste con los claims y sus `evidence_ids` más la lista de evidencia
   permitida, no con la prosa. Sería una reducción de entrada que además abarata cada informe.

## Qué hay que conseguir

- Que el informe competitivo se genere completo en producción con el modelo local que tiene hoy
  asignado. Si tras el análisis concluyes que **qwen3.5:9b no da** para este contrato, dilo
  explícitamente en el resumen con la evidencia: sería una decisión de Signal (mover la task a
  cloud), no un parche de Oracle, y es información valiosa. **No la escondas subiendo números
  hasta que cuele.**
- Que el revisor deje de ser un techo silencioso: su presupuesto debe estar **en relación** con lo
  que revisa, no ser una constante heredada. Si acaba siendo un número fijo, que lleve un
  comentario explicando de dónde sale y qué lo invalidaría, como los demás topes medidos de este
  repo.
- Que el fallo, si vuelve a ocurrir, **diga qué pasó**. Hoy el usuario ve «El job no pudo
  completarse» tras cinco minutos en el 65 %, sin distinguir «el informe salió mal» de «el informe
  salió bien y falló la revisión». Son dos problemas distintos y hoy se ven igual.

## Invariantes que no puedes romper

- **El revisor no es opcional.** Es el control de groundedness: no lo desactives ni lo hagas
  «best-effort» para que el informe pase. Un informe que se publica sin revisar es peor que un
  informe que falla.
- **Signal manda en las tareas gobernadas.** Si tu arreglo pasa por cambiar el presupuesto de una
  task gobernada, Oracle no puede hacerlo solo: hay que pedirlo a Signal. Declara esa dependencia
  en el resumen, no la asumas.
- No subas ningún techo por encima de 16000 sin medir.

## Criterios de aceptación

- Test que reproduzca el fallo: un informe largo (1.200+ palabras) pasando por el revisor con el
  presupuesto actual **debe fallar** antes del arreglo y pasar después. Verifícalo por mutación.
- Test de que el mensaje de error distingue «fallo al generar» de «fallo al revisar».
- Suite completa con integración en verde y cobertura por encima del umbral.
- `ruff check`, `ruff format --check` y `mypy` nombrados por separado con su salida.
- El resumen declara: qué resultó ser la causa real, si hace falta algo en Signal, y qué mediste
  para elegir el valor final.

## No hacer

- No toques el prompt ni la plantilla del informe competitivo: acaban de entregarse y el informe
  se genera bien. El fallo está aguas abajo.
- No desactives ni hagas opcional al revisor de evidencia.
- No subas el techo del revisor «a ojo» sin responder antes a las tres preguntas de investigación.
