# 70 — Una frase discutible tira el resumen nocturno entero (P1)

> Prompt para Codex. **La causa está medida, no hay que investigarla.** Lo que hay que decidir es
> el diseño de la respuesta a un veredicto negativo del revisor.
>
> Cuidado: este prompt roza una pieza que ya nos ha costado tres despliegues y tres rollbacks esta
> semana. Lee entero el apartado de invariantes antes de tocar nada.

## Lo que pasa, medido en producción

`dossier_situation_summary` es el resumen de situación de cada expediente y **se regenera cada
noche**. Es el artefacto de IA más producido del sistema.

Histórico de sus intentos de IA:

```
generate : 66 succeeded /  6 failed / 1 abandoned
reviewer : 48 succeeded /  8 failed
```

Los 6 fallos de generación eran el modelo local truncando, y ya están resueltos: Signal movió la
task a `openrouter/gemini-2.5-flash`. **Los 8 de revisión siguen ahí**, y ahora son la causa
dominante.

Lanzados cuatro resúmenes reales tras el cambio: 2 `succeeded`, 2 `failed`, y los dos fallos son
«El revisor de evidencia rechazó el output». Ninguno falló generando.

**Y fallan los expedientes mejor trabajados:**

| Expediente | Resultado | Evidencias |
|---|---|---:|
| Concurso bomberos | failed | **13** |
| Mercado baterías LFP Europa | failed | **7** |
| Gigafactoría CATL-Stellantis | succeeded | 3 |
| Prueba Playwright · Mercado | succeeded | 4 |

La mecánica lo explica: `ai/service.py` recibe **un veredicto único para todo el output** y, si es
`fail`, lanza y el job muere entero. Cuanta más evidencia tiene el expediente, más afirmaciones
escribe el modelo, y basta con que **una** resulte discutible para perder el resumen completo.

El resultado práctico es perverso: **cuanto mejor trabajas un expediente, más probable es que su
resumen nocturno desaparezca**. Y desaparece en silencio: el expediente conserva el resumen viejo y
nadie se entera de que el de anoche no llegó.

## Qué hay que conseguir

Que un reparo del revisor **no destruya el trabajo entero** en un artefacto que se regenera solo,
sin que por ello se publique como hecho nada que el revisor haya objetado.

No te doy la solución. Dos direcciones razonables, elige y justifica:

- **Quirúrgica**: retirar del resumen solo las afirmaciones objetadas y conservar el resto,
  declarando el recorte. Hay precedente en el repo: `_strip_unauthorized_evidence_blocks` en
  `ai/provider.py` hace justo eso para citas no autorizadas.
- **Marcada**: conservar el resumen completo señalado como pendiente de revisión, con las
  objeciones visibles para quien lo lea.

Ambas son defendibles. Lo que no vale es publicar sin más algo que el revisor ha objetado, ni
seguir tirando el resumen entero.

### Dato técnico que te ahorra una investigación

El revisor **dice qué claim objeta**: su salida trae `unsupported_claims[]` con `path`, `claim` y
`reason`. Y los claims se le envían **con su ruta JSON** (`_review_candidate_claims` incluye
`"path": path`, construido como `$.opportunities[0]`, `$.sections[1].paragraphs[0]`, etc.). Así que
mapear una objeción de vuelta al campo concreto del output es viable.

**Pero verifícalo contra una respuesta real antes de construir encima.** En una sonda manual, con
un contexto donde los claims iban sin `path`, el modelo se inventó uno (`candidate_claims[0].text`).
Si en el flujo real no devuelve la ruta que le dimos, necesitarás otro anclaje —por ejemplo casar
por texto del claim o por sus `evidence_ids`— y eso cambia el diseño. Compruébalo primero.

## Invariantes que no puedes romper

- **El revisor sigue siendo obligatorio donde lo es hoy.** `report_writer` y
  `competitive_procurement_intelligence` deben seguir fallando en duro: un informe que se publica y
  se comparte con afirmaciones sin respaldo es peor que un informe que no sale. Si tu cambio los
  ablanda, es un fallo grave.
- **No degrades el veredicto a aviso de forma global.** Si concluyes que la respuesta al `fail`
  debe depender del tipo de artefacto, declárala **por agente y de forma explícita**, como ya se
  hace con `EVIDENCE_REVIEW_REQUIRED` (ver D-039 y D-040). Nada de `if agent == "..."` escondido en
  el servicio.
- **Nada objetado se presenta como hecho.** Si retiras afirmaciones, el resumen declara que se
  retiraron. Si lo marcas, la marca tiene que verla quien lo lee, no solo quedar en un log.
- **No toques el paquete compacto del revisor** (prompt 60) ni pidas nada a Signal: su parte está
  hecha y el problema es de nuestro lado.

## Verificación exigida

- Los dos expedientes que fallan hoy son reproducibles y están en producción: **«Concurso
  bomberos»** (13 evidencias) y **«Mercado baterías LFP Europa»** (7). Su resumen debe completarse
  tras el cambio, sin que aparezca como hecho nada objetado.
- Un informe (`report_writer` o competitivo) con una cita no permitida **sigue fallando**.
  Demuéstralo mutando y di qué test cayó.
- Test de que el resumen declara lo que se retiró o lo que quedó pendiente de revisión, según la
  vía que elijas.
- Test del caso sano: un resumen sin objeciones no muestra ningún aviso. Un aviso que sale siempre
  deja de leerse.
- **Cada test nuevo verificado por mutación.** Localiza la línea exacta antes de mutar: esta semana
  dos mutaciones mal dirigidas han dado falsos negativos.
- `ruff check`, `ruff format --check`, `mypy src` y la suite con integración, nombrados por
  separado. Frontend si tocas la presentación.

## Qué NO hacer

- No ablandes el revisor ni subas ningún presupuesto: no es un problema de tokens.
- No hagas que el resumen se publique igual ignorando el veredicto.
- No cambies el prompt del resumen para que escriba menos afirmaciones y así evitar objeciones:
  sería empobrecer el producto para esquivar el síntoma, justo lo contrario de lo que se busca.
- Si al implementarlo descubres que las objeciones del revisor son mayoritariamente **falsos
  positivos** —afirmaciones que sí están respaldadas—, **para y repórtalo**: eso sería otro
  problema distinto y más grave, y merece su propio análisis en vez de un apaño.
