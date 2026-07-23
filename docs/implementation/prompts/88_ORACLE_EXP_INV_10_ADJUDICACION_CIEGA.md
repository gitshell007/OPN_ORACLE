# Prompt 88 · ORACLE-EXP-INV-10 · cola de adjudicación ciega

## Objetivo

Preparar la comparación de las 24 unidades A/B una vez ambas estén revisadas, sin hacer promoción
automática, sin revelar `sample_id` a la cola y sin usar resultados de Ollama.

## Uso local

Desde `apps/api`, cuando A y B hayan avanzado sus hojas:

```bash
~/.local/bin/uv run python ../../scripts/spikes/oracle_exp_inv_adjudicate.py \
  --write-queue
```

La cola privada queda bajo `gold/adjudication/queue.json`. Contiene solo `adjudication_id`, los dos
identificadores opacos, las referencias de cuarentena y los campos que difieren. El mapa de
coordinación se usa únicamente para emparejar A/B y no se copia al resultado.

## Reglas

- Una pareja no aparece hasta que A y B tengan `review_status="completed"`.
- Una coincidencia exacta cuenta como acuerdo, pero no como gold adjudicado: no se promueve nada
  sin el cierre humano definido para el protocolo.
- La cola rechaza si A y B recibieron distinto material, si sus hojas no encajan con sus índices o
  si alguno de estos contiene `sample_id`, URL, adjudicatario estructurado o salida de modelo.
- La persona adjudicadora decide cada desacuerdo sobre el material original; la utilidad solo
  prepara la cola y resume progreso.

## Gate

Con el pack actual el resultado esperado es 24 parejas pendientes, cero completas, cero desacuerdos
y cero adjudicadas. El análisis de precisión/recall y cualquier promoción continúan bloqueados hasta
que se complete y congele la adjudicación humana.
