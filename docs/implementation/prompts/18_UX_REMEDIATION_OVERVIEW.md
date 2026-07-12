# 18 — Remediación de UX/Workflow tras auditoría en vivo (índice)

> **Origen:** auditoría de funcionalidad, workflow y visual realizada el 2026-07-12 sobre
> producción (`oracle.opnconsultoria.com`, tenant de `mburgos@iacell.com`), creando un
> expediente real («Gigafactoría de baterías CATL-Stellantis», UUID
> `292d85e5-3dc1-4c2f-81a5-8a73a29e1fb4`) y ejercitando el arco señal → evidencia → IA.
>
> **Diagnóstico de fondo:** el motor funciona (ingesta real de Signal Avanza, IA gobernada
> Signal→Ollama con evidencia citada, trazabilidad). Lo que falla es **el arco que convierte
> la información en acción**: el usuario ve señales pero no puede transformarlas en
> oportunidades/riesgos/actores/decisiones. Hoy Oracle se *siente* como "una carpeta con IA
> encima" — precisamente lo que `AGENTS.md` dice que NO debe ser — no por falta de
> inteligencia, sino porque cada señal termina en un callejón sin salida.

## Cómo usar estos prompts

Ejecuta en el orden de severidad. Cada archivo es un prompt autónomo para Codex.

| Nº | Prompt | Severidad | Resumen |
|----|--------|-----------|---------|
| 19 | `19_FIX_SIGNAL_REVIEW_VERSION_CONFLICT.md` | **P1** | «Marcar revisada» falla siempre con "La revisión de señal cambió" (choque de `triage_version`). Desbloquea la acción central del inbox. |
| 20 | `20_SIGNAL_TO_STRATEGIC_ACTION_FLOW.md` | **P1** | El puente señal → oportunidad/riesgo/actor no es alcanzable ni descubrible desde la señal. Existe en API/servicio pero queda oculto tras la revisión rota. |
| 21 | `21_SIGNAL_TRIAGE_SCORING_AND_UNSCORED_STATE.md` | **P2** | Señales frescas muestran Puntuación 0 / Confianza 0% indistinguible de "sin puntuar"; triaje no puebla scoring ni «por qué importa». |
| 22 | `22_ACTOR_CANDIDATES_DISCOVERABILITY.md` | **P2** | La vista «Candidatos detectados» no se ofrece en estado vacío pese a que las señales nombran actores (CATL, Stellantis). Feature clave invisible. |
| 23 | `23_HOME_FIRST_RUN_AND_KPI_COHERENCE.md` | **P2/P3** | Inicio: muro de ceros para tenant nuevo; incoherencias KPI vs. «Requieren atención» y conteo de «Expedientes activos». |
| 24 | `24_DOSSIER_SUMMARY_OBJECTIVES_HYPOTHESES.md` | **P3** | El Resumen y Configuración no muestran objetivos ni las 2 hipótesis que crea la base inicial; no hay UI de hipótesis. |
| 25 | `25_UX_COHERENCE_NITS_BUNDLE.md` | **P3** | Lote de fricciones: scroll reset en Configuración, etiqueta del monitor, breadcrumb del expediente, fecha de fuente, señales duplicadas y filtro de idioma. |

## Reglas comunes a TODOS los prompts (no repetir, aplican siempre)

1. **Antes de tocar código**, sigue el orden de lectura de `AGENTS.md §3` y respeta las
   decisiones vinculantes `§2` y el flujo de trabajo `§18–21`. Interfaz canónica: **Vector**
   (`CANONICAL_UI=vector`); no toques los prototipos `/concept-a`, `/concept-b`.
2. **Backend Flask es la autoridad.** No metas lógica de negocio en Node. Toda mutación pasa
   por `/api/v1`, con permiso, tenant scoping y validación.
3. **Si cambia el contrato**, regenera OpenAPI y cliente: `npm run api:openapi` →
   `npm run api:client:generate` → `npm run api:client:check` (sin drift).
4. **Tests obligatorios** proporcionales al cambio: backend (unit + integración PG/Redis si
   aplica), frontend (Vitest), y Playwright para recorridos afectados. No afirmes que una
   prueba pasó si no la ejecutaste; incluye comando y resultado.
5. **Verificación por bloque:** `apps/api` → `make lint`, `make typecheck`, `make test`
   (y `make test-integration` si hay `TEST_*`); raíz → `npm run lint`, `npm run typecheck`,
   `npm run test`, `npm run build`, y `npm run test:e2e` cuando toque flujo.
6. **Microcopy en español de España**, sin anglicismos técnicos visibles (tenant, score, job…).
   WCAG 2.2 AA; el color no puede ser la única señal.
7. **Al terminar cada prompt**, actualiza `docs/implementation/STATUS.md` con lo hecho,
   comandos, migraciones y bloqueos, y registra cualquier decisión no trivial en
   `DECISIONS.md`. Entrega el resumen final con el formato de `AGENTS.md §21`.
8. **No inventes datos ni actives gasto cloud.** La política IA sigue gobernada por Signal
   (Ollama local); no habilites OpenRouter/Gemini.

## Cómo reproducir en vivo

Existe un expediente de prueba con un monitor `production` activo y una señal real ya
ingerida (primera piedra de Figueruelas, `elespanol.com`). Úsalo para reproducir y validar,
o crea uno equivalente. Cada prompt indica el punto exacto de reproducción.
