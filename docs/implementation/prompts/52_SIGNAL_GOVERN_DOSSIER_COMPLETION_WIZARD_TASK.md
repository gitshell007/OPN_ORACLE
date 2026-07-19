# 52 — Signal: gobernar dossier_completion_wizard para opn-oracle (P1)

> **Repositorio productor: `/Users/gitshell/PycharmProjects/opn_signal`** (Signal Avanza), NO el de
> Oracle. Lee su propio `AGENTS.md`/convenciones. Cierra el gate de dependencia de los prompts 50 y
> 51 de Oracle (asistente de mejora del expediente). Mismo patrón que el prompt 31.

## Contexto

Oracle añade (prompt 50) el agente `dossier_completion_wizard`: diagnóstico de completitud de un
expediente + preguntas al usuario + acciones recomendadas, con salida JSON estructurada y ejecución
por rondas. Oracle enviará `POST /api/v1/ai/run` con `task_key = "dossier_completion_wizard"` y
**no cablea proveedor ni modelo**: el modelo primario lo decide Signal por task y consumer. Sin el
alta en Signal, la llamada devolverá `403 task_not_allowed` — exactamente el bloqueo que sufre hoy
`entity_dossier_intelligence` (prompt 45, registrado en `OPEN_QUESTIONS.md` de Oracle).

## Alcance (en el repo de Signal)

1. **Definir la task** `dossier_completion_wizard` análoga a
   `ORACLE_DOSSIER_SITUATION_SUMMARY_TASK` (`app/services/ai_governance.py`): el **modelo primario
   vigente de Ollama para las tasks de Oracle** (hoy `qwen3.5:9b`) + fallback Titan
   (`qwen3.6:27b`), **cloud cerrado**, `json_mode`, `structured_output`, `require_explicit_task`,
   reutilizando las mismas constantes/variables de configuración. Dimensiona límites propios:
   salida media (diagnóstico + preguntas + acciones) y contexto mediano-grande (snapshot de
   completitud del expediente); parte de tokens/timeout intermedios, como `meeting_briefing` en el
   prompt 31, y ajusta con criterio.
2. **Registrarla** en el catálogo del consumidor oracle y en el preset `opn-oracle`
   (`allowed_tasks` + `task_settings`), sin exponerla a ningún otro consumidor.
3. **Tests:** catálogo/allowlist (`opn-oracle` la ve; otros consumidores no), sanitización de
   `per_task_settings` y fallback elegible/no elegible, como en las tasks existentes.
4. **Aprovecha el viaje (opcional, con autorización):** sigue pendiente el alta de
   `entity_dossier_intelligence` (bloqueo del prompt 45). Si el responsable lo autoriza
   explícitamente, dala de alta en el mismo cambio/deploy; si no, no la toques y déjalo dicho en el
   informe final.

## Despliegue y verificación cruzada (obligatorio)

1. Desplegar Signal según su runbook (servicios `opn-signal-api/worker/beat`), conservando la
   config previa como en despliegues anteriores.
2. **Verificación end-to-end desde Oracle** (no basta el deploy de Signal): con el prompt 50
   desplegado, lanzar una ronda del asistente sobre un expediente real (vía UI si el 51 ya está, o
   vía API si no); debe volver salida estructurada válida, sin `task_not_allowed` y con el
   proveedor/modelo reales registrados.
3. Registrar el resultado en el STATUS de Signal y en `docs/implementation/STATUS.md` de Oracle, y
   cerrar la dependencia en `OPEN_QUESTIONS.md` de Oracle.

## Criterios de aceptación

- [ ] `task_catalog_for_consumer("opn-oracle")` incluye `dossier_completion_wizard` con Ollama
      primario + fallback Titan y cloud cerrado.
- [ ] Ningún consumidor no-oracle obtiene la task.
- [ ] Suite de Signal verde, sin regresiones.
- [ ] E2E desde Oracle sin `task_not_allowed`, registrado en ambos STATUS y cerrado en
      `OPEN_QUESTIONS.md`.

## No hacer

- No activar OpenRouter/cloud ni añadir modelos de pago.
- No exponer la task a otros consumidores.
- No tocar código de Oracle en este prompt: si al verificar aparece un desajuste de contrato
  Oracle↔Signal, regístralo y trátalo aparte.
- No dar de alta `entity_dossier_intelligence` sin autorización explícita del responsable.
