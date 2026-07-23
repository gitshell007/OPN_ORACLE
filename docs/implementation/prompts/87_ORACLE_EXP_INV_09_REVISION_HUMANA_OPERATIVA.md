# Prompt 87 · ORACLE-EXP-INV-09 · revisión humana operativa

## Objetivo

Permitir que dos personas completen el gold documental INV-03 sin exponer el mapa de
coordinación, URLs, adjudicatarios estructurados ni salida de Ollama.

## Uso local

Desde `apps/api`, cada anotador consulta su cola privada:

```bash
~/.local/bin/uv run python ../../scripts/spikes/oracle_exp_inv_reviewer.py \
  --annotator a --status
```

Para revisar la siguiente hoja pendiente, abrir únicamente sus objetos ya cuarentenados y guardar
la respuesta humana:

```bash
~/.local/bin/uv run python ../../scripts/spikes/oracle_exp_inv_reviewer.py \
  --annotator a --open --review
```

El segundo anotador usa `--annotator b`. A y B no deben compartir sus `blank.json` ni sus respuestas
antes de la adjudicación. Para retomar una hoja concreta se puede añadir `--annotation-id <id-opaco>`;
una hoja completada exige `--reopen-completed` para evitar sobreescrituras accidentales.

## Criterio de anotación

- Responder `s`, `n` o `?` a cada campo. `?` conserva `null`: significa «no determinable con este
  material», no «no revisado».
- `review_status="completed"` y su timestamp distinguen una revisión terminada de una hoja aún
  pendiente, incluso cuando hay campos no determinables o referencias `not_acquired`.
- `participants` y `ambiguities` se introducen como listas JSON. No se inventan participantes al
  faltar un documento; se explica la limitación en `ambiguities` o `notes`.
- La utilidad solo abre objetos que siguen dentro de `quarantine/` y cuyo nombre hash coincide con
  el índice opaco; no descarga, no consulta Signal y no invoca Ollama.

## Gate

El comando valida antes de cada operación que hoja e índice tienen exactamente el mismo conjunto
de `annotation_id` y que el índice no contiene `sample_id`, URL, adjudicatario ni salida de modelo.
Una etiqueta humana no se considera gold adjudicado hasta que la coordinación compare A/B y una
persona resuelva desacuerdos.
