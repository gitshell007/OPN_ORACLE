# 31 — Signal: gobernar report_writer, meeting_briefing y weekly_change para opn-oracle (P1)

> **Repositorio productor: `/Users/gitshell/PycharmProjects/opn_signal`** (Signal Avanza), NO el de
> Oracle. Lee su propio `AGENTS.md`/convenciones. Este prompt cierra el gate de dependencia que los
> prompts 29/30 dejaron abierto y **también arregla la generación de informes** (pre-existente).

## Problema (verificado en producción el 2026-07-13)

En Oracle producción (`AI_MODE=signal`), toda inferencia va por Signal (`POST /api/v1/ai/run`).
La verificación en vivo encontró:

- El **informe** «Plan de acción» quedó **Fallido**; un trabajo IA quedó «Fallido · 10%».
- El **briefing de reunión** no publica; el **digest semanal** tampoco.

Causa raíz confirmada en el host de Signal (`178.105.143.191`): el consumidor **`opn-oracle` solo
tiene** `allowed_tasks = ["dossier_situation_summary", "signal_triage", "evidence_reviewer"]`
(`app/admin/routes.py:233`). Las task keys **`report_writer`, `meeting_briefing` y `weekly_change`
no existen en absoluto** en el repositorio de Signal, así que Signal las rechaza y Oracle recibe un
fallo. Oracle está bien implementado (encola, conserva versión previa, valida schema); lo que falta
es la contraparte gobernada en Signal, como se hizo para `dossier_situation_summary`.

## Objetivo

Habilitar en Signal, para el consumidor `opn-oracle`, las tres tasks gobernadas
`report_writer`, `meeting_briefing` y `weekly_change`, replicando el patrón de
`dossier_situation_summary` (Ollama primario + Ollama Titan fallback, **cloud cerrado**), con sus
límites propios. Con ello Oracle podrá generar informes, briefings y digests reales.

## Punteros de código (Signal) — verificados

- Template de task: `app/services/ai_governance.py:71`
  `ORACLE_DOSSIER_SITUATION_SUMMARY_TASK = { provider: "ollama", model, fallback_provider:
  "ollama_titan", fallback_model, latency_class, temperature 0.1, max_output_tokens 3000,
  json_mode, structured_output, require_explicit_task, timeout_seconds 180, fallback_on_status
  [429], ollama_options {num_ctx 32768, keep_alive}, cloud cerrado }`.
- Registro en catálogo: `app/services/ai_governance.py:254`
  (`"dossier_situation_summary": dict(ORACLE_DOSSIER_SITUATION_SUMMARY_TASK)`) y trato especial del
  consumidor oracle en `:456`.
- Preset del consumidor `opn-oracle`: `app/admin/routes.py:233` (`allowed_tasks`) y `:242`
  (`**ORACLE_DOSSIER_SITUATION_SUMMARY_TASK` en `task_settings`).
- Tests de referencia: `tests/test_api_ai_run.py` (catálogo/allowlist por consumidor) y
  `tests/test_admin_ai_settings.py` (preset).

## Alcance (en el repo de Signal)

1. **Definir tres tasks** análogas a `ORACLE_DOSSIER_SITUATION_SUMMARY_TASK`, dimensionando límites
   por caso:
   - `report_writer`: informe extenso → mayor `max_output_tokens` (p. ej. 4500–6000) y
     `timeout_seconds` acorde; `num_ctx` suficiente.
   - `meeting_briefing`: briefing estructurado → tokens/timeout intermedios.
   - `weekly_change`: digest → tokens/timeout intermedios.
   Mantener `provider: ollama` + `fallback_provider: ollama_titan`, `json_mode`,
   `structured_output`, `require_explicit_task`, y **cloud/OpenRouter cerrado** (sin activarlo).
2. **Registrarlas** en el catálogo del consumidor oracle (junto a `dossier_situation_summary`) y en
   el preset `opn-oracle`: añadir las tres a `allowed_tasks` y a `task_settings`.
3. **Modelos**: usar los presets Ollama ya definidos para Oracle (primario `qwen3.5:9b`, fallback
   Titan `qwen3.6:27b`), reutilizando las mismas constantes/variables de configuración; no
   introducir modelos nuevos ni gasto cloud.
4. **Tests**: extender los de catálogo/allowlist para afirmar que `opn-oracle` incluye ahora las
   tres tasks y que otros consumidores (p. ej. `opn-nexus`) siguen sin verlas. Sanitización de
   `per_task_settings` y fallback como en la task existente.
5. Respetar la aislación por consumidor: estas tasks solo para `opn-oracle`.

## Criterios de aceptación

- [ ] `task_catalog_for_consumer("opn-oracle")` incluye `report_writer`, `meeting_briefing` y
      `weekly_change`, cada una con provider Ollama + fallback Titan y cloud cerrado.
- [ ] Un consumidor no-oracle no obtiene estas tasks.
- [ ] Suite de Signal verde (la fase Oracle tenía 466/466; no regresar).
- [ ] Sin activar ninguna vía cloud.

## Despliegue y verificación cruzada (obligatorio)

1. Desplegar Signal según su runbook (servicios `opn-signal-api/worker/beat`), conservando config
   previa como han hecho las notas de STATUS de Oracle (`settings.env.pre-*`).
2. **Verificación end-to-end desde Oracle** (no basta el deploy de Signal): en producción de Oracle,
   expediente CATL `292d85e5-3dc1-4c2f-81a5-8a73a29e1fb4`:
   - Generar un **informe** (plantilla «Plan de acción») → debe pasar de «Fallido» a publicado con
     contenido citado.
   - **Preparar reunión** en «Reunión de posicionamiento con Gobierno de Aragón» → debe publicar un
     briefing real.
   - Generar el **digest** en «Qué ha cambiado» → contenido real.
   Todos sin errores de consola y con evidencia citada; sin evidencia suficiente, honesto.
3. Registrar en el STATUS de Signal y en `docs/implementation/STATUS.md` de Oracle (release/notas,
   comandos, resultado) y cerrar la dependencia en `OPEN_QUESTIONS.md`.

## No hacer

- No activar OpenRouter/cloud ni añadir modelos de pago.
- No exponer estas tasks a otros consumidores.
- No tocar el código de Oracle en este prompt: el arreglo es 100% del lado de Signal. (Si al
  verificar aparece un desajuste de contrato Oracle↔Signal, regístralo y trátalo aparte.)
