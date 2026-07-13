# 29 — Briefing de reunión generado por IA (Meeting Briefing Agent) (P2)

> Lee `18_UX_REMEDIATION_OVERVIEW.md` (reglas comunes). Al terminar, **despliega** con el modo
> rápido UAT (D-022) y **verifica en vivo**. Es una feature de IA: aplica la política gobernada por
> Signal (D-015), sin activar cloud.

## Problema (auditoría en vivo 2026-07-13)

En una reunión, «Preparar reunión» crea un **«Documento preparatorio» vacío** («Añade hechos y
evidencias antes de usarlo»). No hay briefing generado: el usuario recibe un folio en blanco. El
producto (memoria §9.4/§14.7) define el Meeting Briefing Agent para producir **contexto, mapa de
actores, objetivos, estrategia de conversación, preguntas, objeciones esperables e información
sensible + tareas posteriores**, con evidencia. Además, el alta de reunión es mínima: solo Título
y Objetivo, **sin fecha ni participantes/actores**.

## Estado real del código (verificado)

- El prompt de IA **`meeting_briefing`** YA existe en el registro
  (`apps/api/src/opn_oracle/ai/prompts/meeting_briefing/`), como existe `dossier_situation_summary`.
- La ruta `POST /meetings/{id}/briefings` (`oracle/routes.py:1293` `briefing_create`) crea un
  registro `Briefing` **manual y vacío**; no invoca al agente.
- **Blueprint a replicar (ya funciona en producción):** el «Oráculo del expediente»
  (`dossier_situation_summary/v1`) — ver el bloque «Task implementada · Oráculo contextual» en
  `docs/implementation/STATUS.md`. Piezas: `oracle/summary.py`, job `oracle.dossier_summary.refresh`
  (cola `ai`), `SignalGovernedLLMProvider` (`ai/provider.py`) sobre `POST /api/v1/ai/run`,
  persistencia `AIContextSnapshot`/`AIArtifact`/`AIAuditLog`, panel
  `src/components/dossiers/dossier-oracle-summary-panel.tsx`.

## Objetivo

Que «Preparar reunión» genere un **briefing estructurado por IA** con evidencia citada, siguiendo
el mismo patrón gobernado del Oráculo; y enriquecer el alta de reunión con **fecha** y
**participantes** (actores del expediente).

## Alcance

1. **Backend — briefing por IA:** un job Celery en cola `ai` que construye el snapshot de contexto
   de la reunión (objetivo, expediente: objetivos/hipótesis, actores vinculados, señales/
   oportunidades/riesgos relevantes, memoria viva) con redacción y detección de prompt injection
   heredadas del runtime, invoca el agente `meeting_briefing` vía `SignalGovernedLLMProvider`,
   valida el output con schema estricto (secciones separando hechos/inferencias/recomendaciones,
   `evidence_ids` verificados) y lo persiste como `Briefing` publicado + `AIArtifact`/`AIAuditLog`.
   Idempotencia por snapshot, versión anterior conservada ante fallo (igual que el Oráculo).
2. **Frontend — reunión:** «Preparar reunión» pasa a **solicitar el briefing IA** (estado en
   curso, aviso de proveedor, conservar versión previa), y el detalle muestra el briefing en
   bloques escaneables (contexto, actores, objetivos, preguntas, objeciones, siguientes acciones)
   con sus fuentes y feedback, al estilo del panel del Oráculo. Mantener la opción de notas
   manuales si aporta, pero el valor principal es el briefing generado.
3. **Alta de reunión enriquecida:** añadir **fecha/hora** y selección de **participantes** entre
   los actores del expediente (persistir en `Meeting`/`meeting_actors`, que ya existen). La fecha
   debe reflejarse en la lista (hoy «Fecha pendiente») y alimentar el aviso de «Reuniones próximas»
   de Inicio.
4. **Contrato:** regenerar OpenAPI y cliente si cambia (`api:client:check` sin drift).

## Dependencia Signal (gate, verificar primero)

Producción usa `AI_MODE=signal`: la inferencia va por Signal. **Verifica que Signal gobierna la
task `meeting_briefing`** (catálogo/allowlist para `opn-oracle`). Si no la expone, coordina el lado
productor (`/Users/gitshell/PycharmProjects/opn_signal`) replicando lo que se hizo para
`dossier_situation_summary` (catálogo aislado, preset Ollama/Titan, sin cloud), o **deja la feature
gated** con copy honesto hasta que Signal la exponga. No actives fallback cloud.

## Criterios de aceptación

- [ ] «Preparar reunión» produce un briefing con secciones citadas a evidencia; sin evidencia
      suficiente, lo dice honestamente (no inventa), como hace el Oráculo.
- [ ] La reunión admite fecha y participantes (actores); la fecha aparece en lista e Inicio.
- [ ] Reintentar deduplica por snapshot; un fallo de proveedor conserva la versión previa.
- [ ] Tests backend (context builder de reunión, validación de schema, idempotencia, fencing) y
      frontend (estado en curso, render del briefing). Suite completa verde.
- [ ] Migración solo si el esquema lo exige; `Briefing`/`meeting_actors` ya existen.

## Despliegue y verificación en producción (obligatorio)

1. Si toca migración, seguridad o contrato: lanza el **CI completo manual** (`workflow_dispatch`,
   D-024) y confírmalo verde. Si no, checks locales proporcionales.
2. Modo rápido UAT (D-022): backup local + restore aislado, release inmutable,
   `sudo oracle-control update`, smoke + `oracle-control health`.
3. Verificación funcional autenticada (expediente CATL `292d85e5-…`): crear/usar una reunión con
   fecha y participantes, pulsar «Preparar reunión» y confirmar que aparece un briefing con
   fuentes; sin errores de consola.
4. Actualiza `STATUS.md` (release-id, comandos, resultado) y `DECISIONS.md`/`OPEN_QUESTIONS.md`
   según corresponda (incluida la dependencia Signal).

## No hacer

- No llamar a Ollama/OpenRouter directamente desde Oracle ni activar cloud.
- No publicar un briefing que no valide el schema; regístralo en auditoría y reintenta acotado.
