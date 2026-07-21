> **Investigación primero, arreglo después.** No propongas una solución hasta poder explicar por
> qué el mismo revisor, con el mismo proveedor y el mismo modelo, funciona en dos rutas y falla
> siempre en una tercera. Ya se han descartado tres hipótesis por prueba directa en producción;
> están abajo para que no las repitas.

# 64 — El revisor de evidencia falla solo en la ruta del informe de entidad (P1)

## Estado actual

- **Producción está sana**: se revirtió el release. El informe de entidad funciona.
- **El código está en `master`** (prompt 63 + la corrección de «solo evidencia citada»). Lo
  revertido es el release activo, no el repositorio. No hay que reescribir nada de eso.
- Lo que falta es entender por qué ese código rompe el informe en producción.

Se han hecho **dos despliegues con rollback** por este motivo. El siguiente intento debe salir con
una explicación, no con otra corrección a ciegas.

## Los hechos, medidos

Job real en producción, informe de entidad de `ITURRI SA`, tres reintentos:

```
generate  -> succeeded   (las 3 veces)
reviewer  -> failed      (las 3 veces: ValidationError, ValidationError, ValueError)
```

Del log del worker, en cada intento: **los tres `POST /api/v1/ai/run` a Signal devuelven HTTP 200.**

Recuento histórico del revisor por agente que lo dispara:

| Agente | reviewer OK | reviewer falla |
|---|---:|---:|
| `report_writer` | 6 | 0 |
| `competitive_procurement_intelligence` | 3 | 1 |
| `entity_dossier_intelligence` | **0** | **3** |

## Hipótesis ya descartadas (no las repitas)

1. **«Es el modelo local `qwen3.5:9b`».** Falso. Signal movió `evidence_reviewer` a cloud;
   verificado desde el worker: `provider: openrouter`, `model: google/gemini-2.5-flash`. Falla
   igual.
2. **«Es Signal».** Falso. Los tres POST devuelven 200. El fallo ocurre en Oracle al interpretar la
   respuesta.
3. **«Es el tamaño de la entrada».** Ya se corrigió: el revisor recibe solo la evidencia citada, no
   las 45 fuentes (commit `8714eaf`). Sigue fallando.

## Dónde está el fallo exactamente

El `ValidationError` nace dentro de `SignalGovernedLLMProvider.generate_structured`
(`ai/provider.py`), en `schema.model_validate_json(normalized_output)`: **el JSON del revisor no
encaja con `EvidenceReviewerOutput`**.

Uno de los tres intentos falló con `ValueError` en vez de `ValidationError`, lo que apunta a
`validate_evidence(reviewer, allowed_evidence_uuids)` en `oracle/entity_dossier_report.py`: el
revisor citando evidencia fuera de la allowlist. **Que fallen de dos formas distintas es
información**: no es un error determinista de forma, hay variabilidad en la respuesta del modelo.

## La pregunta que hay que responder

**¿Qué tiene de distinto el contexto que la ruta de entidad envía al revisor, frente al que envía
`execute_agent`?** No es el proveedor, ni el modelo, ni el tamaño de la evidencia. Tiene que estar
en el contenido o la forma del contexto.

Compara lado a lado:

- Cómo construye `ai/service.py` el `reviewer_context` en la ruta que funciona.
- Cómo lo construye `oracle/entity_dossier_report.py` (que importa `_reviewer_context` del mismo
  sitio, así que la diferencia estará en **qué le pasa**, no en la función).

Y captura la respuesta real: **loguea el `normalized_output` del revisor antes de validarlo**, en
una ejecución real. Todo lo demás es especular; sin ver el JSON que devuelve, no se puede cerrar
esto. Puedes hacerlo con un script instrumental como el del spike 61, sin desplegar.

### Pista con la que empezar

Signal declaró en su entrega que `evidence_reviewer` conserva **`structured_output=false`**. Sin
salida estructurada forzada, el modelo puede devolver campos extra o formas distintas, y
`EvidenceReviewerOutput` hereda de `StrictModel` (`strict=True`, `extra="forbid"`), que los
rechaza sin contemplaciones.

**Pero cuidado: esa pista sola no explica los hechos.** Si fuera solo `structured_output=false`,
también fallaría para `report_writer`, que usa el mismo revisor con la misma configuración y va 6
de 6. Cualquier hipótesis que propongas **tiene que explicar esa asimetría**. Si tu explicación no
la cubre, no es la explicación.

## Qué hay que entregar

1. **La causa raíz, demostrada**, no deducida: con el JSON real que devuelve el revisor en la ruta
   de entidad y la diferencia concreta frente a la ruta que funciona.
2. El arreglo correspondiente, con test que **falle antes y pase después**, verificado por
   mutación.
3. Si la causa está en Signal (por ejemplo, que haya que activar `structured_output` para esa
   task), **dilo y no lo implementes en Oracle**: sería una dependencia externa, como ya ocurrió
   con los presupuestos de tokens.
4. Si tras investigarlo concluyes que **activar el revisor en esta ruta no compensa**, dilo con
   argumentos. Es una salida legítima: el informe de entidad ya valida estructuralmente sus citas
   (medido: 45 citadas, 45 permitidas, 0 inventadas), y un control que rechaza 3 de 3 informes
   correctos es un bloqueo, no un control. El prompt 63 ofrecía esa opción y sigue en pie.

## Deuda menor a corregir de paso

En `oracle/entity_dossier_report.py` conviven dos estilos de validación: líneas 1202 y 1311 usan
`model_validate` (modo Python) mientras la 1608 usa `model_validate_json`. Hoy no es la causa —el
proveedor ya devuelve modelos validados—, pero es la misma asimetría que provocó el fallo de los
UUID hace unos días. Unifícala.

## Invariantes

- Los tres agentes de informe conservan su revisión donde ya funciona. No la desactives para que
  pase el de entidad.
- No toques el paquete compacto del revisor (prompt 60) ni la corrección de evidencia citada
  (`8714eaf`).
- El wizard sigue exento y con su validación determinista.
- **No despliegues sin generar un informe de entidad real.** Van dos rollbacks por dar por bueno un
  cambio verificado solo con tests.
