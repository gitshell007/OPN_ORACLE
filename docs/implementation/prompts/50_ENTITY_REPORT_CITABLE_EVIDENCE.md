# 50 — El informe de entidad no cita evidencia: todo sale como inferencia (P1 · calidad de IA)

> Prompt de producto para Codex. Iteración del prompt 45. No es un bug: es la consecuencia honesta de
> un diseño incompleto, y el responsable quiere cerrarlo porque «hechos con evidencia» es el lema del
> producto. Verifica con `ITURRI SA` en producción; si no tienes sesión, decláralo.

## El síntoma, verificado en producción

El informe de IA de entidad de `ITURRI SA` salió **entero en `inferences`**, con **`facts: []`,
`evidence_ids: []` y `source_index: []` vacíos**. La IA razonó bien (incluso desambiguó homónimos),
pero no ancló ni un solo hecho en una fuente citable. Para un sistema cuyo eje es la trazabilidad
(AGENTS.md §9), un informe sin hechos ni evidencia es media promesa.

## Por qué pasa — no es alucinación, es diseño

En `apps/api/src/opn_oracle/oracle/entity_dossier_report.py`:

- Línea ~338 pasa al modelo **`"allowed_evidence_ids": []`** — no hay ninguna evidencia que pueda
  citar.
- Línea ~170 el prompt le **instruye** a formular como inferencia todo hecho sin evidencia citable.

Es decir: el modelo hizo **exactamente lo correcto** con lo que se le dio. El hueco es que el corpus
de la ficha —que `compact_entity_dossier` sí incluye— **no se materializa como `Evidence`**. Los
datos citables están ahí:

- Cada acto BORME de `registry.items` trae su **`source_url`** al BOE (persona, cargo, acción, fecha,
  provincia, enlace).
- Cada noticia de `news.items` trae su URL.
- Las relaciones del grafo traen su origen BORME.

Contraste: el informe **documental** de procurement sí cita porque materializa `Evidence` de los
fragmentos del documento (`_ensure_chunk_evidence` / `create_evidence` en `procurement_report.py`) y
pasa esos IDs como `allowed_evidence_ids`.

## Qué se pide

Materializar el corpus de la ficha como **evidencia citable** para que el modelo produzca hechos
anclados, no solo inferencias:

1. Convertir en `Evidence` (tenant-scoped) los elementos citables del corpus —al menos los actos
   BORME con su `source_url`, y las noticias con su URL—, con un **locator** que apunte a la fuente
   (el enlace a BOE / a la noticia) y los campos legibles (persona, cargo, acción, fecha).
2. Pasar esos `evidence_id` como `allowed_evidence_ids` al modelo, para que pueda citar y separe
   **hechos con evidencia** de inferencias. El prompt debe animar a anclar en evidencia cuando exista,
   sin inventar (mantén el resto de la disciplina de honestidad del 45).
3. Que el informe muestre la fuente citada de forma legible (como ya hace el visor de informes con la
   evidencia de procurement), no un UUID crudo.

## La restricción que debes resolver, no ignorar

El informe de entidad **se genera sin expediente** (área de espera del prompt 45, D-035:
`dossier_id` NULL hasta incorporar). Pero `Evidence` es tenant-scoped y se vincula a expediente por
la tabla `EvidenceDossier`. Así que decide y documenta **cuándo** se crea la evidencia y cómo viaja
al expediente al incorporar:

- Crear la `Evidence` tenant-scoped en la generación (sin dossier) y **vincularla al expediente al
  incorporar**, junto con el informe; o
- Guardar las referencias de fuente en el snapshot del área de espera y **materializar la evidencia
  al incorporar**, cuando ya hay dossier.

Elige la que mantenga la coherencia con el área de espera y no deje evidencia huérfana si el informe
nunca se incorpora. Regístralo en `DECISIONS.md`.

## Límite honesto (mantener del prompt 45)

Signal no da el texto íntegro del acto BORME, solo los campos de la ficha. La evidencia citable es
**el enlace a la fuente oficial + los campos**, no el contenido completo. El informe no debe
aparentar haber leído el BORME entero; sigue declarando ese límite. Los homónimos siguen sin
desambiguar automáticamente: una evidencia BORME de «Iturri» no prueba que sea la misma entidad.

## Criterios de aceptación

- [ ] Un informe de entidad nuevo produce **hechos con `evidence_ids`** que resuelven a fuentes
      reales (BOE/noticia), no solo inferencias vacías.
- [ ] La evidencia se ve legible en el informe, con su enlace; nada de UUID crudo.
- [ ] La creación/vinculación de evidencia respeta el área de espera (D-035) sin dejar huérfanos;
      decisión en `DECISIONS.md`.
- [ ] Se mantienen los descargos de honestidad del 45 (límite de fuente, homónimos).
- [ ] `scripts/api-test.sh --unit` **ejecutado** (`uv` en `~/.local/bin/uv`) + lint/typecheck/tests
      del frontend si tocas UI.
- [ ] Verificado con `ITURRI SA`: el informe cita al menos un acto BORME con su enlace.

## No hacer

- No hagas que el modelo cite evidencia que no existe: primero materialízala, luego permítela.
- No dejes evidencia huérfana si el informe no se incorpora a un expediente.
- No presentes el enlace BORME como «leí el acto completo»: es cita de fuente, no el contenido.
- No dupliques la creación de evidencia: reutiliza `create_evidence`/el patrón de procurement donde
  encaje.
