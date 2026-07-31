# MEMSOL-08 · Resiliencia y gobierno de modelos (plan medible)

## Cadena de timeouts objetivo

```text
primary + fallback + red < HTTP Oracle client < Celery soft < hard < BackgroundJob lease
```

## Tasks nuevas Memoria Sol (propuesta, flags OFF)

| task_key | primario | fallback | timeout_s | max_out | enabled default |
|---|---|---|---|---|---|
| dossier_question_answer | ollama | ollama_titan | 120 | 4000 | false |
| report_brief_planner | ollama | ollama_titan | 90 | 2000 | false |
| custom_report_writer | ollama | ollama_titan | 300 | 6500 | false |
| memory_extraction (existente) | ollama | ollama_titan | 45 | 2000 | per flags |

## Fallos a inyectar (Dev, consumer sintético)

1. primario timeout → fallback ok
2. 429 / 5xx primario → fallback
3. schema inválido → retry acotado → failed terminal
4. Signal caído → job failed accionable
5. muerte worker tras claim → recover stale / no double cost
6. cancel tras running → settlement cancelled; fencing rechaza ready

## No hacer

- No cambiar `report_writer` por inferencia
- No fallback cloud ante policy/budget/classification
- No settlement sin execution token

## Gate

Suite fault-injection local documentada; métricas attempt N/M, provider/model por intento.
