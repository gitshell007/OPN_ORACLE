# 92 — El revisor tumba el informe de actores con evidencia real (P0 · IA)

> Prompt de corrección medido en producción. La causa no es snapshot vacío: hay 104 evidencias y el
> writer genera; la política `reject_output` de `report_writer` convierte `verdict=fail` del revisor
> en informe sin revision ni artefactos.

## Medido (2026-07-26)

- Tenant OPN Consultoría, owner real.
- `POST /reports/{be688a73-…}/retry` → hijo `c8d148ce-…`, job `f883d306-…`, ~166 s.
- Fallo: `El revisor de evidencia rechazó el output.` / `permanent_failure`.
- Fallo previo (24-jul): JSON truncado del revisor (`EOF while parsing`).

## Decisión

`report_writer` → `strip_claims` (D-081). Competitive conserva rechazo duro. No desactivar revisor.

## Criterio de aceptación

- Reintento de actores en Coches de Bomberos no deja al usuario sin entregable cuando el revisor
  solo objeta claims anclables.
- Tests de registry + integración (strip en report_writer, hard-fail en competitive).
- Mutación de política hace caer el test nuevo.
- Release en producción y reintento verificado.

## Fuera de alcance

PDF, documentos, routing ollama/signal (prompt 94), mensajes de error enriquecidos (prompt 93).
