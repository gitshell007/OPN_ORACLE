# Los informes de expediente devuelven cero secciones

**Fecha:** 2026-07-24
**Estado:** mitigado en `master`, pendiente de despliegue y de cerrar el hueco de snapshot
**Evidencia:** auditoría con acciones reales en producción, 4 generaciones consecutivas

## Síntoma

Ninguna generación desde la Biblioteca de informes terminó. Cuatro intentos, cuatro fallos,
con tres códigos distintos en la UI y ninguna causa accionable:

| Plantilla | Expediente | Código en la UI | Causa real (job) |
|---|---|---|---|
| `action_plan` | AUDIT-TEST (vacío) | `ValueError` | — |
| `action_plan` | CATL-Stellantis (con datos) | `ReportWorkflowError` | faltan las 8 secciones |
| `executive_dossier` | CATL-Stellantis (con datos) | `ReportWorkflowError` | faltan las 6 secciones |
| `actors` (reintento) | Coches de Bomberos | `EvidenceReviewError` | el revisor rechazó el output |

El usuario solo veía «Código seguro: X. Puedes reintentar sin sobrescribir este intento», y el
Inicio llegó a mostrar 4 de 5 «Informes recientes» en estado *Fallido*.

En los dos casos con datos **faltaban todas las secciones, no una**: no es la normalización de
headings que se relajó en `c418d70`, es que el modelo devolvió `sections: []`.

## Contraste que acota la causa

El mismo modelo, en el mismo host y a la misma hora, **sí** generó un informe completo desde la
ficha 360° de entidad (`Informe IA → Generar nuevo informe`): 100 %, 25 fuentes, incorporado al
expediente. Ese pipeline es `entity_dossier_report`, no `process_report`.

Luego no es «la IA está caída». Es este pipeline.

## Causa raíz

Es la misma que en [informe-actores-sin-contexto-de-actores.md], extendida a más plantillas:
**el snapshot congelado no transporta las entidades sobre las que la plantilla pide escribir.**

`_frozen_report_snapshot` congelaba actores y relaciones **solo** cuando
`template.key == "actors"`. Para el resto se congelaba `actors: []`. Pero:

- `executive_dossier` exige «Actores clave», «Oportunidades principales» y «Riesgos principales».
- `action_plan` exige «Acciones», «Responsables propuestos», «Dependencias», «Hitos»,
  «Riesgos de ejecución» y «Decisiones necesarias».

El snapshot lleva `objectives`, `hypotheses`, `living_summary`, `procurement_items`, `evidence`, y
—solo si vienen seleccionados por `options`— **una** `opportunity`, **un** `risk` y **una**
`meeting`. No lleva listas de oportunidades, riesgos, tareas, decisiones ni hitos.

Se le pide al modelo un plan de acción sin acciones y un ejecutivo sin actores. Ante eso devuelve
la lista vacía, y la validación tira el informe entero.

Agravantes propios de este pipeline, todos corregidos aquí:

1. **El prompt no ordenaba emitir una sección por heading.** `report_writer/v5` decía que las
   secciones «vienen fijadas por la plantilla», pero la lista real solo viajaba dentro del JSON de
   contexto, en `requested_scope.required_sections`. Nunca se le decía «devuelve exactamente una
   por cada una» ni «no devuelvas `sections` vacío».
2. **Un muestreo malo mataba el informe al primer intento.** El fallo de contrato se mapeaba a
   `PermanentJobError`: `attempts: 1`, sin segunda pasada y sin dar entrada al respaldo gobernado
   en Signal, aunque el snapshot estuviera intacto y el mismo contexto pudiera producir un output
   válido.
3. **La causa no llegaba al usuario.** El informe guardaba el mensaje genérico «No se pudo generar
   el informe» y la UI mostraba el nombre de la excepción. El texto útil —redactado por Oracle a
   partir de la plantilla, no por el modelo— solo existía en el job.
4. **Todo fallo aparece al 10 %.** `process_report` no marca ningún checkpoint, así que hereda el
   10 % fijo que `execute_durable` pone al arrancar. `entity_dossier_report` sí los marca
   (15/30/45/60/90) y por eso su barra se mueve.

## Qué se ha corregido

- `report_writer/v6`: sección «Secciones obligatorias» que apunta a
  `requested_scope.required_sections`, exige una sección por heading en orden y literal, prohíbe
  `sections` vacío y ordena **emitir igualmente** la sección declarando el hueco cuando falten
  datos, en vez de omitirla.
- `ReportOutputContractError`: separa «el modelo no cumplió el contrato» de «el snapshot está
  corrupto». Los tres pipelines que comparten `process_report` lo tratan como reintentable; la
  manipulación de snapshot sigue siendo permanente.
- El informe guarda la causa real de contrato en `error_message` en lugar del texto genérico.
- El snapshot congela actores y relaciones también para `executive_dossier`
  (`TEMPLATES_WITH_ACTOR_SECTIONS`).

## Qué falta

1. Congelar **listas** de oportunidades y riesgos para `executive_dossier`, y tareas, decisiones e
   hitos para `action_plan`, con el mismo criterio de límites y truncamiento declarado.
2. Revisar con el mismo criterio `opportunity`, `risk`, `meeting_briefing` y `tender`, que ya
   estaban señaladas en el diagnóstico anterior.
3. Checkpoints de progreso en `process_report`: hoy todo fallo se ve al 10 %.
4. La UI debe mostrar `error_message` en vez del código de la excepción.

## Nota sobre el modelo

`c418d70` propuso mover `report_writer` a cloud porque `ollama/qwen3.5:9b` devolvía `sections: []`.
Un modelo más capaz mejora el margen, pero **no arregla esto**: sobre un snapshot sin acciones ni
actores redactaría mejor prosa sobre el mismo vacío. El enrutado por `task_key` se gobierna en
Signal y no se toca desde este repositorio.
