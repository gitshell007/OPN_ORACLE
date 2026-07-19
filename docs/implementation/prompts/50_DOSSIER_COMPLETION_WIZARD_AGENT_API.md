# 50 — Asistente de mejora del expediente: agente gobernado y API por rondas (P1 · feature)

> Prompt de producto para Codex, **solo backend de Oracle** (la UI es el prompt 51; el alta de la
> task en Signal es el prompt 52). Desarrolla y prueba con `AI_MODE=mock` u Ollama local; el E2E
> contra Signal queda bloqueado hasta desplegar el 52 — decláralo como no verificado, no lo simules.

## Objetivo

Un agente gobernado nuevo, **`dossier_completion_wizard`**, que mire un expediente con los ojos de
su objetivo (`strategic_goal`), su tipo (`dossier_type`) y su estado real de completitud, y
devuelva: qué falta, por qué importa para ese objetivo, preguntas concretas al usuario y acciones
recomendadas ejecutables. Es la contraparte backend del «wizard» de mejora: el usuario responde a
las preguntas en la UI y se lanza otra ronda con las respuestas acumuladas.

Caso que debe resolver bien (úsalo como eval sintética): expediente tipo `market` «Coches de
Bomberos», objetivo «Conocer las licitaciones que salen de coches de bomberos u otros vehículos y
ver la competencia», sin monitores, sin licitaciones fijadas, sin actores. Salida esperada:
recomendar un monitor de señales con keywords adecuadas, buscar y fijar licitaciones desde
Contratación pública, añadir adjudicatarios como actores con rol «competidor», y preguntar lo que
le falte para afinar (ámbito geográfico, tipo de vehículo, órganos de contratación...).

## Diseño acordado: rondas estructuradas, no chat

- Nada de streaming ni de historial de mensajes en el provider: `SignalGovernedLLMProvider`
  (`apps/api/src/opn_oracle/ai/provider.py`) monta siempre `[system, user]`; **no lo toques**. El
  multi-turno se consigue **acumulando** en el payload de contexto las preguntas de rondas
  anteriores y las respuestas del usuario.
- Cada ronda es un job en la cola `ai`, como el resto de agentes (`TASK_QUEUES` en
  `apps/api/src/opn_oracle/jobs/service.py`; `HANDLERS`/`_ai_handler` en
  `apps/api/src/opn_oracle/jobs/tasks.py`), con la gobernanza estándar de `execute_agent`
  (`apps/api/src/opn_oracle/ai/service.py`): política de tenant, cuota, auditoría, artefactos.

## Alcance

1. **Registro del agente** en `apps/api/src/opn_oracle/ai/registry.py` (`AGENT_SCHEMAS`,
   `PURPOSES`, `INPUT_CONTRACTS`, `PROMPT_VERSIONS`) con prompt versionado
   `ai/prompts/dossier_completion_wizard/v1.md` en español de España: rol de guía que explica para
   qué sirve cada cosa que pide, no ejecuta acciones ni cambia estados, trata el contenido del
   expediente como datos no confiables (mismas reglas anti-inyección que los agentes existentes) y,
   si falta información, pregunta en vez de inventar.
2. **Snapshot de completitud** en el contexto (amplía `apps/api/src/opn_oracle/ai/context.py` sin
   romper `build_context`): además de `title`/`description`/`strategic_goal`/objetivos/hipótesis
   que ya viajan, incluye conteos y estado por sección: oportunidades, riesgos, actores vinculados,
   señales y su triage, licitaciones/adjudicaciones fijadas (`dossier_procurement_items`),
   monitores del expediente con su estado, y si el tenant tiene conexión Signal Avanza activa. IDs
   y resúmenes mínimos; no vuelques la base de datos.
3. **Schema de salida** Pydantic estricto en `apps/api/src/opn_oracle/ai/schemas.py`, como mínimo:
   - `summary`, `confidence`, `warnings[]`;
   - `section_diagnostics[] { section, status: ok|incomplete|empty, explanation }`;
   - `questions[] { id, question, why_it_matters, expected_input }`;
   - `recommended_actions[] { kind, title, rationale, prefill }` con `kind` cerrado:
     `create_signal_monitor | pin_procurement | create_opportunity | create_risk | create_actor |
     refine_goal | other`, y `prefill` con los campos del formulario correspondiente (keywords del
     monitor, título y `next_action` de la oportunidad, roles del actor...).
   La UI del prompt 51 consumirá `kind` + `prefill` para abrir formularios prefijados: el contrato
   debe ser estable y versionado.
4. **Entrada por rondas:** la request lleva las respuestas del usuario
   (`answers[] { question_id, answer }`) y el backend reconstruye el hilo (preguntas previas +
   respuestas) dentro del contexto. Decide dónde persisten las rondas (artefacto IA, tabla nueva o
   payload del job) y justifícalo; el estado debe sobrevivir a una recarga de página.
5. **Endpoint:** valora reutilizar la ruta genérica
   `POST /api/v1/ai/dossiers/<id>/agents/<agent>/runs` (`apps/api/src/opn_oracle/ai/routes.py`) si
   admite el input de ronda; si no, una ruta específica
   `POST /api/v1/ai/dossiers/<id>/completion-wizard/runs` con los mismos candados (sesión, CSRF,
   permiso, tenant scoping, idempotency key, cuota, auditoría), más un GET para recuperar la última
   ronda. Decide y justifica.
6. **Contrato cliente:** OpenAPI regenerado sin drift y método nuevo en
   `packages/api-client/src/transport.ts`.
7. **task_key:** `dossier_completion_wizard`, mismo nombre exacto que se dará de alta en Signal
   (prompt 52). Mientras Signal no la conozca, el fallo debe ser el retriable honesto habitual
   («proveedor no disponible temporalmente»), como en el informe de entidad del prompt 45.

## Criterios de aceptación

- [ ] Agente registrado con prompt v1 y schema estricto; con `AI_MODE=mock` devuelve salida válida.
- [ ] El contexto incluye el snapshot de completitud y las rondas previas; nada de otros tenants ni
      de otros expedientes.
- [ ] La eval «Coches de Bomberos» (fixture sintética) produce diagnóstico por sección y acciones
      con `kind` correcto y `prefill` utilizable.
- [ ] Una segunda ronda con `answers` incorpora las respuestas al contexto y se refleja en la
      salida.
- [ ] `scripts/api-test.sh --unit` verde (`uv` en `~/.local/bin/uv`); OpenAPI y cliente TS sin
      drift; `npm run lint`, `npm run typecheck`, `npx vitest run`, `npm run build` verdes.
- [ ] La dependencia del prompt 52 sigue registrada en `OPEN_QUESTIONS.md` (actualízala si cambia
      el nombre de la task o el contrato).

## No hacer

- No toques `SignalGovernedLLMProvider` para meter historial de mensajes ni streaming.
- No cablees proveedor ni modelo en Oracle: el modelo primario lo gobierna Signal por `task_key`.
- No dejes que el agente ejecute acciones (crear monitores, oportunidades, actores...): solo
  recomienda con `prefill`; ejecutar es del usuario desde la UI.
- No inventes un framework de conversación genérico: rondas acumuladas sobre el patrón de agentes
  existente, y ya.
