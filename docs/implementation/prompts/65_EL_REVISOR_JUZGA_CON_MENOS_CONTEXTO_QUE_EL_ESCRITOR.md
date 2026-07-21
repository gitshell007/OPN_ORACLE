> **Causa demostrada con sondas contra producción. No es un fallo de Signal, del modelo ni del
> presupuesto de tokens.** Empieza leyendo esto entero: las tres hipótesis obvias ya se probaron y
> se descartaron, y repetirlas cuesta días.

# 65 — El revisor de evidencia juzga con menos contexto que el escritor (P1)

## Estado actual

El informe de entidad **funciona en producción** (release `ca55269`) porque su ruta no ejecuta el
revisor. Se intentó activarlo tres veces —prompt 63 y dos redespliegues— y las tres hubo que hacer
rollback. Este prompt es para decidir qué hacer, con el diagnóstico ya cerrado.

## Lo que se probó y quedó descartado

No vuelvas sobre esto:

1. **«Es el modelo local».** Signal movió `evidence_reviewer` a `openrouter/gemini-2.5-flash`.
   Siguió fallando.
2. **«Es el tope de salida».** Signal lo subió de 900 a 4000. Siguió fallando.
3. **«Es la agregación de hechos del prompt v2».** Se probó un hecho agregado citando 3 evidencias
   y otro atómico citando 1: **ambos `pass`**.
4. **«El modelo alucina».** Falso, y verificado en base de datos: la afirmación que el revisor
   señala («casi 80 años de historia») **sí está en el corpus del job**.

## La causa

Sonda que replica la llamada real del revisor sobre un informe ya guardado:

```
claims=27  (con evidencia=6, sin evidencia=21)   tipos: 21 inference, 6 fact
27 claims -> pide 4000 (techo de la formula) -> out=4000, JSON cortado
 6 claims -> pide 1740                       -> out=975,  JSON valido, verdict=fail
solo los 6 hechos citados                    -> out=1124, JSON valido, verdict=fail
```

Con presupuesto de sobra, **el veredicto sigue siendo `fail`**. Lo que señala es
`missing_evidence` sobre frases como «casi 80 años de historia» o «líder en soluciones
integrales».

Y aquí está el fondo: **el revisor recibe menos información que el escritor.**

`_reviewer_context` (en `ai/service.py`) le pasa `candidate_claims` y `evidence` —los extractos de
la evidencia citada— pero **no el `entity_dossier` desde el que se redactó el informe**. El informe
se escribe desde un corpus rico (perfil registral, grafo, noticias, patentes, CNMV, contratación)
del que **solo una parte es citable**. Toda afirmación apoyada en el dossier pero no en un extracto
citable le parece infundada al revisor, y el `fail` es sistemático.

**Esto explica por fin la asimetría entre agentes**, que nos tuvo dos días dando palos de ciego:
en `report_writer` el contexto **son** las evidencias del expediente, así que claims y evidencia
salen del mismo sitio y cuadran (6 revisiones, 0 fallos). En la ruta de entidad no.

## Qué hay que decidir

Tres salidas legítimas. **Elige con criterio y explica por qué**; no es una decisión mecánica.

**A. Darle al revisor el mismo contexto autorizado que tuvo el escritor.** Es lo más correcto
conceptualmente: nadie puede juzgar bien con menos información de la que tuvo quien escribió. Pero
ojo con lo que ya aprendimos en el prompt 60: meterle el corpus entero fue justo lo que lo hizo
truncar. Habría que pasarle una versión compacta del dossier, no el dossier completo, y medir.

**B. Acotar qué se le manda a revisar.** Que el revisor evalúe solo los claims con `evidence_ids`
—los que afirman hechos citados— y no las 21 inferencias, que por contrato no citan. Es más barato,
pero **ojo: no basta por sí solo.** Se probó y también da `fail`, porque el texto de esos 6 hechos
también se apoya en el dossier. Solo funcionaría combinado con A.

**C. Declarar honestamente que esa ruta usa otro control.** El informe de entidad **ya tiene
validación estructural de citas**: `validate_evidence` rechaza cualquier `evidence_id` fuera de la
allowlist, y así se midió en producción (45 citadas, 45 permitidas, 0 inventadas). Sería reconocer
que el veredicto semántico no aplica aquí y dejar `requires_evidence_review: False` con el motivo
escrito. Es la opción honesta si A resulta caro; lo que no vale es dejar la tabla diciendo `True`
mientras la ruta no lo ejecuta.

**Mi recomendación**, para que la tengas como punto de partida y no como orden: **A si sale barato,
C si no.** B es complementaria, nunca suficiente. Lo que no haría es seguir gastando despliegues en
afinar tokens: ese camino ya se agotó dos veces.

## El problema secundario, real pero no urgente

Con 27 claims la fórmula `min(4000, 1200 + claims*90)` pide su techo y la respuesta se corta. Si
eliges A o B, dimensiona también esto: el coste del revisor crece con el número de claims, y los
informes ya no son cortos. Pero **no lo trates como la causa**: se subió a 4000 y no arregló nada.

## Invariantes

- `report_writer` y `competitive_procurement_intelligence` conservan su revisión y siguen pasando.
  Si tu cambio los rompe, es un fallo grave.
- No relajes el revisor globalmente ni conviertas su veredicto en aviso.
- No toques el prompt v2 del informe de entidad para que «diga menos»: el informe es bueno y su
  contenido está respaldado por el corpus. El problema es qué ve el revisor, no qué escribe el
  informe.
- No pidas nada más a Signal: han hecho dos cambios correctos y ninguno era la causa.

## Verificación exigida

Sea cual sea la opción:

- Un informe de entidad real **se genera y completa** en producción. Es la prueba que ha faltado
  tres veces; sin ella no está hecho.
- Si eliges A o B: `generate` **y** `reviewer` aparecen ambos en éxito en auditoría.
- Si eliges C: la tabla y el código dicen lo mismo, y el resumen explica qué control queda vigente
  en esa ruta.
- Los otros dos informes siguen revisándose. Demuéstralo mutando y di qué test cayó.
- Suite completa con integración, cobertura sobre el umbral, y `ruff check`, `ruff format --check`
  y `mypy` nombrados por separado.
