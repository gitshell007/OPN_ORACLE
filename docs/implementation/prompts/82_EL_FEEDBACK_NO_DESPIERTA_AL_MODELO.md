# 82 — El feedback no despierta al modelo (P2 · API + UX)

> Prompt de producto para Codex, **backend + frontend**. Es el P2 del plan aprobado:
> feedback relevante/no-relevante y replanificación explícita gobernada. Se apoya en tres
> entregas ya en `master`: el wizard gobernado (78, `232def3`, D-063), su UI con procedencia
> y unión (80, `d7b2885`, D-066) y los contratos recuperables (81, `fa5dce6`, D-068).
>
> Precondición de arranque: el informe del 81 declaró que la suite backend integrada
> completa no se ejecutó por una carrera de reset del PostgreSQL compartido. Antes de
> escribir una línea, ejecútala en limpio y deja constancia; si la carrera reaparece,
> arréglala o aíslala — este prompt añade una migración y no se construye sobre una suite
> que no ha corrido entera.
>
> La regla que da nombre al prompt: registrar feedback es escribir una fila, jamás una
> llamada IA. El modelo solo opina cuando el usuario pide replanificar, una vez, y su
> propuesta pasa por las mismas fronteras humanas de siempre.

## 1 — La memoria del feedback

Nuevo modelo tenant-scoped (migración Alembic con RLS, patrón de la 0022) — el plan lo
llamaba `ProcurementSearchFeedback`:

- FK compuesta al perfil (`profile_id`, `tenant_id`), la **versión del plan** sobre la que
  se opinó, el `folder_id` de la licitación, veredicto `relevant | not_relevant`, motivo de
  vocabulario cerrado (`wrong_sector | amount | region | buyer | other`) con nota libre
  opcional, usuario y timestamps.
- Decide y justifica la semántica de repetición: el último veredicto de un usuario sobre un
  mismo `folder_id` manda, y qué pasa con el histórico. Lo innegociable: el agregado del
  punto 2 debe ser determinista — mismo feedback, mismo digest.
- Endpoints mínimos: registrar, retirar (deshacer) y listar por perfil, con rate limits
  declarados y tenant scoping probado. Registrar y retirar son las operaciones que la UI de
  resultados dispara con un toque; su latencia importa.

En la UI de resultados: control ligero por tarjeta («No relevante» con selector de motivo de
un toque; «Relevante» como afirmación opcional), la tarjeta se atenúa con **deshacer**
visible, y el microcopy gestiona la expectativa exacta: «Lo tendremos en cuenta cuando pidas
revisar el plan» — ni parece que no hace nada, ni parece magia instantánea. Estilo neutro:
esto es dato, no IA (D-066).

## 2 — El digest determinista: qué hemos aprendido, sin modelo

La acumulación se explota con aritmética, no con LLM — la misma filosofía que dio el 81,8 %:

- Agregado reproducible por perfil: conteos por veredicto y motivo; términos plegados (el
  tokenizador versionado `spanish-procurement-stopwords-v1` de siempre) y CPVs frecuentes en
  los títulos/cpv de las licitaciones rechazadas frente a las relevantes. De ahí salen
  **candidatos a exclusión y a refuerzo**, cada uno con su cuenta visible.
- Reutiliza las primitivas de `comparable_procurement.py` (`title_terms`, normalización CPV);
  no dupliques tokenizadores.
- Exponlo en la API (endpoint propio o embebido en el GET del perfil, decide) para que la UI
  pueda mostrar «3 rechazos por sector · términos frecuentes en lo rechazado: mantenimiento,
  limpieza» antes de que nadie llame al modelo. El digest lleva hash: la replanificación lo
  usará como parte del `input_hash`.

## 3 — Replanificación explícita gobernada

- Una acción humana («Revisar el plan con este feedback», estilo `vector-ai` — aquí sí hay
  IA), una única generación gobernada. El contexto: descripción original, plan aceptado vN y
  el digest del punto 2. Decide si es una versión v2 del prompt del agente (el registry ya
  versiona con changelog) o una sección de contexto del v1; documenta el porqué.
- La salida es el mismo schema estricto con la misma postvalidación (CPV contra taxonomía,
  descartes visibles). Idempotencia heredada: mismo plan + mismo digest → mismo artifact,
  sin segunda llamada.
- La UI la presenta como el **diff que quedó aplazado en el 81**: por chip, añadido /
  retirado / conservado respecto al plan aceptado, con la procedencia de siempre. Las reglas
  D-066 no se relajan: los chips del usuario y los confirmados se conservan, lo medido que
  el modelo retire aparece como brecha con unión de un clic, y quitar sigue siendo acto del
  usuario. Aceptar pasa por `acceptances` y produce v(n+1); la correlación de D-068 ya sabe
  contarlo al reabrir.
- El CTA de replanificar puede activarse cuando exista feedback nuevo desde la última
  aceptación (un conteo, visible), pero **nunca** se dispara solo ni se sugiere con urgencia
  fabricada.

## 4 — Lo que este prompt NO abre

La detección incremental de licitaciones nuevas en vigilancias y su notificación sin repetir
lo ya revisado es la fase siguiente (necesita memoria de vistos por búsqueda guardada y, en
producción, los monitores de Signal). No la empieces: el feedback de este prompt opina sobre
resultados que el usuario ya tiene delante.

## Verificación exigida

- La suite backend integrada **completa** en limpio, con la carrera del reset resuelta o
  explicada y aislada — es la primera casilla, no la última.
- Tests backend: semántica de repetición del feedback; digest determinista (mismo feedback →
  mismo hash; feedback distinto → digest distinto); tenant scoping en feedback y digest;
  replanificación con `AI_MODE=mock` sobre un escenario sembrado (rechazos por sector con
  términos concretos → el digest los capta y el plan mock propone exclusiones coherentes);
  contador de `AIUsageLedger`: N feedbacks y sus digests → **cero** llamadas; una
  replanificación → **exactamente una**.
- Tests frontend: feedback con deshacer y microcopy; conteo de feedback nuevo; diff por chip
  con las tres categorías y conservación de chips de usuario tras replanificar; 422
  estructurados pintados en su campo (el contrato del 81 no debe regresionar).
- Migración aplicada, revertida y reaplicada en limpio.
- **Cada test nuevo verificado por mutación**: di qué mutaste y qué test cayó.
- Gates completos de ambos lados nombrados por separado, OpenAPI + cliente sin deriva, y el
  spec Playwright del wizard extendido con el camino feedback → replanificar → aceptar v2.
- Smoke visual con sesión real si hay Signal configurado; si no, declarado como en el 81.

## Qué NO hacer

- Ni una llamada IA al registrar, retirar, listar o digerir feedback. Ni umbrales que
  disparen replanificación sola.
- Nada de pesos opacos ni aprendizaje implícito: el digest es conteo explicable con cifras a
  la vista. Si algún día hay ranking aprendido, será otra decisión con su propio prompt.
- No toques la vigilancia incremental, los monitores de Signal ni las notificaciones.
- No relajes D-063 (fronteras humanas), D-066 (procedencia y unión) ni D-068 (correlación
  por contrato). La replanificación es una generación más, no un canal privilegiado.
- No pgvector, no embeddings: el gate P3 sigue cerrado hasta que un eval demuestre que el
  recall determinista se queda corto.
