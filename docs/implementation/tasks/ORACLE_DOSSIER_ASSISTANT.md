# Task Oracle — Oráculo contextual dentro de cada expediente

**Estado:** implemented-oracle / pending-signal  
**Prioridad:** alta  
**Dependencia externa:** task homóloga de Signal `dossier_situation_summary`  
**Prompt ejecutable:** `docs/implementation/prompts/17_DOSSIER_ORACLE_ASSISTANT.md`

## Resultado esperado

Cada expediente dispone de un resumen de situación versionado, trazable y actualizable que analiza
documentación, evidencias, señales, objetivos, hipótesis, actores, oportunidades, riesgos,
reuniones, decisiones y tareas del propio expediente.

## Alcance Oracle

- adapter IA gobernado por Signal, sin llamadas directas a proveedores;
- retrieval tenant/dossier-scoped y snapshot reproducible;
- prompt/schema `dossier_situation_summary/v1`;
- job Celery durable y sustitución del stub de memoria;
- persistencia versionada y auditoría completa;
- API de lectura, refresh, versiones y feedback;
- panel Vector «Oráculo del expediente» con citas y estados completos;
- pruebas de aislamiento, evidencia, worker, contrato, UI y evals.

## Política acordada

- primario: `ollama/qwen3.5:9b`;
- secundario: `openrouter/google/gemini-3.5-flash`;
- fallback solo por fallos técnicos/política, nunca por preferencia semántica;
- el gasto cloud requiere límites específicos y gate de privacidad antes de activación.

## Fuera de alcance inicial

- ejecutar automáticamente recomendaciones o decisiones;
- búsqueda web directa desde Oracle;
- usar datos de otros expedientes sin vínculo/evidencia explícitos;
- reemplazar informes formales o decisiones humanas;
- chat libre sin retrieval y citas.

## Estado Oracle 2026-07-11

Implementado en Oracle: adapter gobernado por Signal, snapshot tenant/dossier-scoped, prompt/schema
`dossier_situation_summary/v1`, job Celery durable, persistencia versionada en artefactos IA,
publicación visible en `LivingSummary`, API, cliente TypeScript, panel Vector y tests locales.

Pendiente externo: task homóloga en Signal y gates de activación cloud/presupuesto/privacidad.
