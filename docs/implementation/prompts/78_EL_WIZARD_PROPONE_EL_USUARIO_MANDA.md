# 78 — Wizard de búsqueda de licitaciones: la IA propone, el usuario manda (P1 · API)

> Prompt de producto para Codex, **solo backend**. La interfaz del wizard es el prompt
> siguiente (79), que consumirá lo que aquí se construye; no toques `/app/procurement`.
> Carril «Solo Oracle» de `CONTRACT_V2_PROPOSAL.md` §1. Depende de dos entregas ya en
> `master`: el ámbito temporal honesto (prompt 74, commit `a203371`) y el perfil determinista
> de comparables + taxonomía CPV (prompt 76, commit `5b205d2`).
>
> Producto: el usuario describe su empresa en lenguaje natural («fabricamos EPIs y vehículos
> contraincendios para bomberos», «somos parecidos a ITURRI») y una única ejecución IA
> gobernada devuelve un **plan de búsqueda estructurado y revisable**. La IA nunca busca, ni
> puntúa resultados, ni guarda vigilancias: propone un plan; el usuario lo corrige y manda.

## 1 — Agente gobernado `tender_search_wizard`

Sigue el patrón completo del wizard existente, que está medido y funciona:

- Registro en `ai/registry.py` con `PROMPT_VERSIONS` y las políticas por agente (el
  `dossier_completion_wizard` aparece en las líneas 56, 105, 143 y 164). Decide
  conscientemente la política de revisión: este agente emite un plan de búsqueda, no
  afirmaciones sobre evidencia; si concluyes `not_required`, documenta el porqué en el mismo
  bloque de comentarios donde está razonado D-039. No inventes una segunda vía de revisión:
  el boundary unificado del prompt 63 es el único.
- Modelo de salida `StrictModel` en `ai/schemas.py` registrado en `AGENT_OUTPUT_MODELS`
  (patrón `DossierCompletionWizardOutput`, líneas 531 y 555).
- Prompt versionado en `ai/prompts/tender_search_wizard/v1.md`.
- Ejecución asíncrona con `BackgroundJob` en la cola `ai` y endpoints tenant-scoped de
  encolar/último resultado (patrón `ai/routes.py:127-176`), pasando por `execute_agent`:
  `AIArtifact` idempotente por `input_hash` + `AIAuditLog`. Misma descripción del usuario =
  artifact cacheado, cero coste.
- Debe funcionar en los cuatro `AI_MODE`; `mock` determinista para CI y evals.

El plan v1 (schema estricto y versionado) contiene: `intent_summary`, `include_terms`,
`synonyms`, `exclude_terms`, `candidate_cpv`, `buyers`, `geographies`, `scope`,
`min_amount`/`max_amount`, `assumptions`, `questions`, `confidence`. El vocabulario de
`scope` es el del prompt 74: `active | historical | all` — y recuerda que `historical` hoy
devuelve 422 en tenders; el plan puede proponerlo, la ejecución lo declara no disponible.

**Grounding determinista antes de llamar al modelo.** El contexto se construye sin LLM:
la descripción del usuario y, si dio una comparable, su perfil vía
`cached_comparable_profile` (servicio interno, no la ruta HTTP — la ruta tiene rate limit
6/hora pensado para el navegador; el TTL de 6 h hace barata la reutilización). Los top CPVs,
términos y compradores del perfil entran como contexto citado, no como decisión tomada.

**Post-validación determinista de la salida.** Cada `candidate_cpv` pasa por
`normalize_cpv_code` + etiquetado de `cpv_taxonomy`; los códigos que no existen en la
taxonomía se descartan y se cuentan como descartados con motivo — el patrón visible de
`web_mentions.py` (`discarded_count`, `discarded_reasons`). Los términos se pliegan con el
mismo tokenizador y stopwords `spanish-procurement-stopwords-v1` del prompt 76, para que lo
que el plan propone case con lo que el matching mide. Nada alucinado llega al usuario como
válido.

## 2 — Memoria mínima: el perfil de búsqueda del tenant

Crea el modelo tenant-scoped (migración Alembic) que persiste la intención — nombre a tu
criterio, el plan lo llamaba `ProcurementSearchProfile`:

- Descripción original del usuario y comparables indicadas.
- Plan **aceptado** (JSON), su versión (entero que incrementa con cada aceptación) y hash.
- Referencia al `AIArtifact` que lo generó (auditoría) y al `tender_search` de Signal si el
  usuario guardó vigilancia.
- Timestamps de creación/última aceptación.

El plan aceptado lo fija un endpoint explícito de aceptación con el plan editado por el
usuario en el cuerpo (re-validado: CPVs contra taxonomía, scope contra vocabulario). El
agente jamás escribe el plan aceptado. No crees todavía `ProcurementSearchRun` ni
`ProcurementSearchFeedback`: son P2, y este prompt no es el sitio.

## 3 — Ejecutar el plan es traducirlo, y hay dos incógnitas medibles

La ejecución/preview de un plan es 100 % determinista sobre los endpoints existentes
(`cached_tenders` con `scope`). Antes de decidir la traducción plan → consultas:

- **Mide la semántica de `keywords` multi-término en Signal** (¿AND, OR, frase?). El harness
  del 76 sondeó término a término y no la respondió. De esa medición depende si un plan de
  20 términos es una consulta o veinte; documenta el resultado con ejemplos crudos en el
  informe de cierre.
- **Presupuesta las sondas por chip.** Los contadores por término/CPV (los que la UI del 79
  mostrará junto a cada chip) son consultas independientes: tenders tiene rate limit 60/min y
  caché de 90 s. Un plan de 20 términos + 20 CPVs no puede costar 40 peticiones por
  refresco. Decide y declara el límite (sondar solo top-N, agregar bajo demanda, o un
  contador global por bloque), con el mismo criterio de topes visibles de D-044.

Guardar vigilancia reutiliza `create_tender_search` con una restricción medida: Signal v1
solo conserva búsquedas guardadas de **activas** (`_validate_saved_search_temporal_scope`,
`procurement_routes.py:167-177`, responde 422 en otro caso). El guardado es active-only y
siempre una acción humana explícita; la exploración histórica/all vive en la sesión.

## 4 — El modelo tiene que ganarle (o empatarle) a la aritmética

Extiende `scripts/evaluate_comparable_profile.py` para aceptar un plan arbitrario en JSON y
evaluarlo contra el mismo holdout temporal. Criterio de aceptación: el plan generado por el
wizard con grounding de ITURRI debe alcanzar en ese holdout **al menos el recall combinado de
la línea base determinista (81,8 %, informe 2026-07-23)** — o la brecha queda documentada
con cifras y explicación. Si la única aportación del LLM fuese empeorar el agregado puro,
queremos saberlo antes de ponerle interfaz. Ejecuta también el eval con `AI_MODE=mock` para
que CI tenga una regresión determinista del pipeline completo.

## Verificación exigida

- Tests del agente con `mock`: plan válido, CPV inventado descartado con motivo visible,
  scope inválido rechazado, idempotencia por `input_hash` (misma descripción → mismo
  artifact, sin segunda llamada).
- Tests de la aceptación del plan: re-validación del cuerpo editado, incremento de versión,
  tenant scoping (un tenant no ve ni acepta perfiles de otro).
- Test de **cero LLM** en traducción, sondas y guardado: solo la generación/regeneración del
  plan incrementa `AIUsageLedger`, y exactamente en uno por ejecución.
- Test del guardado active-only contra el 422 medido.
- **Cada test nuevo verificado por mutación**: di qué mutaste y qué test cayó.
- `ruff check`, `ruff format --check`, `mypy src`, suite completa con integración, migración
  aplicada y revertida en limpio, y regeneración de OpenAPI + cliente TypeScript, nombrados
  por separado.
- Ejecución real del eval del punto 4 contra producción en lectura, informe con fecha en
  `docs/implementation/evaluations/`. Sin credenciales: cifras declaradas no verificadas.
- La medición de `keywords` multi-término documentada con ejemplos crudos.

## Qué NO hacer

- Ni una llamada LLM por licitación, por sonda o por guardado: la única llamada es la
  generación del plan (y sus regeneraciones explícitas).
- No guardes vigilancias automáticamente ni aceptes planes sin acción humana explícita.
- No crees los modelos de runs/feedback (P2) ni toques pgvector/embeddings (P3, y solo si el
  eval demuestra que el recall determinista se queda corto).
- No fusiones consultas para simular órdenes o ámbitos que Signal no ofrece: D-043 y el 422
  de `historical` siguen mandando.
- No presentes al usuario CPVs sin validar contra la taxonomía ni términos sin plegar con el
  tokenizador versionado.
- No toques la UI: el prompt 79 la construirá con las indicaciones de UX ya acordadas
  (chips con estado candidato, contadores en vivo, estilo IA solo donde hay IA).
