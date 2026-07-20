# 63 — La tabla dice una cosa y el código hace otra: unificar la revisión de salidas IA (P1)

> Diagnóstico ya hecho contra producción. **Nada está roto ahora mismo**: los informes se generan
> y el asistente funciona. Lo que hay es una declaración que no se cumple y un agente sin control,
> y las dos cosas empeoran solas si se añaden agentes nuevos.
>
> Este prompt cierra las dos deudas que dejó el prompt 62.

## 1 — Lo que descubrimos al verificar el wizard

El prompt 62 introdujo `PromptDefinition.requires_evidence_review` y la tabla
`EVIDENCE_REVIEW_REQUIRED` en `ai/registry.py`, para que el asistente de expediente pudiera
saltarse un control que no le corresponde. Fue el arreglo correcto y funciona: el wizard completó
por fin dos rondas en producción.

Pero al contrastar los intentos por agente en `ai_attempts` apareció esto:

```
dossier_completion_wizard         -> generate: 2 succeeded, reviewer: 0   (correcto, está exento)
entity_dossier_intelligence       -> generate: 9 succeeded / 13 failed, reviewer: 0
```

**`entity_dossier_intelligence` está declarado como `requires_evidence_review: True` y no ha
ejecutado el revisor ni una sola vez en todo su histórico.**

La causa son dos caminos de generación distintos:

- `report_writer` y `competitive_procurement_intelligence` pasan por `reporting/service.py`, que
  llama a `execute_agent` (`ai/service.py`) y por tanto ejecuta el revisor.
- El informe de entidad usa su propia ruta, `_run_waiting_area_agent` en
  `oracle/entity_dossier_report.py`, que invoca `provider_from_config(...).generate_structured(...)`
  directamente y **nunca llama al revisor**.

Matiz importante para dimensionarlo bien y no sobreactuar: el informe de entidad **sí tiene control
estructural de citas**. El proveedor rechaza `evidence_ids` fuera de los permitidos, y así se midió
en producción: 45 citadas, 45 permitidas, **0 inventadas**. Lo que no se ejecuta es el **veredicto
semántico** del agente revisor. No es que el informe esté sin proteger; es que le falta una de las
dos capas y la tabla afirma que la tiene.

## 2 — Las dos deudas a cerrar

### A. Que `requires_evidence_review` signifique algo en todas las rutas

Hoy es una declaración que solo se honra si el agente pasa por `execute_agent`. Hay que resolverlo,
y **hay más de una forma legítima**:

- Que la ruta del informe de entidad ejecute el revisor como las demás.
- O que el flag deje de ser una promesa incumplible: por ejemplo, que sea el propio punto de
  ejecución quien garantice el control, de modo que ninguna ruta pueda generar sin pasar por él.

Elige con criterio y explica por qué. Lo que **no** vale es dejar la tabla diciendo `True` donde no
se ejecuta nada: o se cumple, o se declara honestamente que esa ruta no lo aplica y por qué.

**Ojo con el efecto secundario:** si activas el revisor en la ruta de entidad, ese informe pasa a
tener un paso más que puede fallar, y hoy funciona. Mide qué ocurre con un informe real antes de
darlo por bueno, y ten presente lo que aprendimos en el prompt 60: el revisor debe recibir el
paquete compacto de claims, **no la prosa completa**, o volveremos a truncar.

### B. Un control de salida para el asistente de expediente

El wizard quedó sin control semántico. Tiene validación de esquema, auditoría, cuotas, contexto de
tenant y trazabilidad, pero **nada verifica que lo que dice tenga sentido**. Y no es un agente
inocuo: propone al usuario acciones ejecutables con datos precargados (`create_signal_monitor`,
`pin_procurement`, `create_actor`, `create_risk`).

El revisor de groundedness no le sirve, porque el wizard afirma ausencias. Lo que sí tiene sentido
verificar en un diagnóstico:

- Que los `section_diagnostics` se refieren a secciones del enum y **cubren el expediente real**:
  si dice `signals: empty` es comprobable en base de datos, y si el expediente tiene señales, el
  diagnóstico es falso.
- Que las `questions` apuntan a huecos que **existen de verdad**, no a información que el
  expediente ya tiene.
- Que las `recommended_actions` tienen `kind` válido y su `prefill` es coherente con el tipo.
- Que no afirma hechos sobre el negocio del cliente que no puede saber.

Fíjate en que **buena parte de eso es verificable en Python contra la base de datos, sin IA**. Un
diagnóstico que dice «no hay actores» cuando hay dos es un fallo objetivo y barato de detectar. Ese
es el camino que yo exploraría primero: control determinista antes que un segundo agente.

## 3 — Invariantes

- Los tres agentes de informe conservan su revisión. Si tu cambio deja alguno sin revisar, es un
  fallo grave.
- **No toques el paquete compacto del revisor** (prompt 60).
- La tabla `EVIDENCE_REVIEW_REQUIRED` debe seguir indexándose **directamente**, no con
  `.get(name, False)`. Que un agente nuevo sin declarar reviente al arrancar es deliberado: el
  defecto seguro es fallar ruidosamente, no saltarse el control en silencio.
- El wizard debe seguir sin pasar por el revisor de groundedness: su contrato no cita evidencia y
  eso no ha cambiado.

## 4 — Verificación exigida

- Un informe de entidad real se genera correctamente **después** de tu cambio. Si activaste el
  revisor en esa ruta, demuéstralo con una ejecución completa, no solo con tests.
- Un informe cuya salida cite evidencia no permitida **falla** en las tres rutas. Demuéstralo
  mutando y di qué test cayó en cada una.
- El wizard sigue completando dos rondas, y su control nuevo **detecta un diagnóstico falso**:
  monta el caso (un expediente con actores donde el wizard afirme `actors: empty`) y comprueba que
  se detecta. Un control que nunca dispara no es un control.
- Suite completa con integración en verde y cobertura por encima del umbral.
- `ruff check`, `ruff format --check` y `mypy` nombrados por separado.

## 5 — Qué NO hacer

- No relajes el revisor de groundedness ni lo degrades a aviso.
- No metas al wizard en el revisor de evidencia «ya que estamos»: es el fallo que acabamos de
  arreglar.
- No construyas un segundo agente de IA para validar al wizard si el control determinista cubre lo
  esencial. Más IA para revisar IA es más superficie de fallo y más coste; justifícalo si lo
  propones.
- Si al hacerlo descubres que activar el revisor en la ruta de entidad rompe algo, **para y
  repórtalo** en vez de forzarlo: ese informe funciona hoy y es el más usado del producto.
