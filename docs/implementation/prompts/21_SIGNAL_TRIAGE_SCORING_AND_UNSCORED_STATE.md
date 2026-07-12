# 21 — Scoring de triaje y estado «sin puntuar» de señales frescas (P2)

> Lee `18_UX_REMEDIATION_OVERVIEW.md` y las reglas comunes. Severidad **P2**.

## Problema observado (evidencia de auditoría)

La señal recién ingerida muestra **Puntuación 0 / 100**, **Confianza 0 %** y
**«Por qué importa: Pendiente de revisión humana»**, mientras otras señales del tenant puntúan
53–67. En la lista, esa señal aparece como «Puntuación 0», **indistinguible de una señal
valorada con 0** — justo cuando el producto (OPN_Oracle_Codex_Memory.md §13) promete ayudar a
**priorizar** qué señal importa. El triaje asíncrono extrajo el «hecho observado» correctamente,
pero no pobló relevancia/novedad/impacto/confianza ni «por qué importa».

## Contexto de código

- `apps/api/src/opn_oracle/oracle/service.py` `review_signal_link()` calcula `overall_score`
  a partir de `relevance/novelty/strategic_impact/confidence` (+ credibilidad de la fuente).
  En una señal no revisada esos campos son 0 → score 0.
- El triaje gobernado por IA es `signal_triage` (prompt versionado en `apps/api/src/opn_oracle/
  ai/prompts/`, ejecución en cola `ai` vía Signal). Verifica si **debe** poblar el pre-scoring
  y «por qué importa» de forma automática, o si por diseño se deja todo a la revisión humana.

## Objetivo

Que el usuario distinga «sin puntuar» de «puntuación 0», y que las señales lleguen con una
**valoración previa útil** (aunque provisional y claramente marcada como no revisada) para poder
priorizar sin tener que abrir cada una.

## Alcance e implementación sugerida

1. **Modelo de estado de puntuación:** introducir/《exponer》 un estado explícito `sin puntuar`
   (p. ej. `overall_score == null` frente a `0`, o un flag `scored`), y propagarlo al schema de
   salida y al cliente TS. Regenera OpenAPI/cliente.
2. **Frontend (lista y drawer):** mostrar «Sin puntuar» / «Pendiente de triaje» en vez de «0»
   cuando no hay valoración; ordenar/filtrar por puntuación tratando lo no puntuado aparte.
   Diferenciar visualmente sin depender solo del color (WCAG).
3. **Triaje automático (decidir y documentar):** define si `signal_triage` debe rellenar un
   pre-scoring provisional + «por qué importa» al ingerir. Si sí, impleméntalo por Celery
   gobernado por Signal (Ollama), con evidencia y auditoría, marcado como *provisional/no
   revisado*; si no, documenta en `DECISIONS.md` que el scoring es exclusivamente humano y ajusta
   el copy para que sea honesto («pendiente de tu valoración»).
4. Asegurar que revisar una señal recalcula y persiste el score (ya lo hace `review_signal_link`)
   y que el valor se refleja inmediatamente en la lista.

## Criterios de aceptación

- [ ] Una señal sin valorar se muestra como «Sin puntuar», no como «0».
- [ ] Existe (o se documenta explícitamente que no existe) un pre-scoring automático provisional,
      y el copy es honesto en ambos casos.
- [ ] Tras revisar, la puntuación y confianza reales aparecen en lista y detalle.
- [ ] Orden y filtro por puntuación tratan lo no puntuado de forma coherente.
- [ ] Tests: backend del cálculo/estado de score; frontend del render «sin puntuar» vs valor.

## Verificación

`apps/api`: `make lint typecheck test` (+ integración). Raíz: `lint typecheck test build`;
`api:client:check`. Actualiza `STATUS.md` y `DECISIONS.md` con la decisión de triaje.

## No hacer

- No inventes puntuaciones sin evidencia ni base; si es provisional, márcalo como tal.
- No actives gasto cloud; el triaje sigue gobernado por Signal (Ollama local).
