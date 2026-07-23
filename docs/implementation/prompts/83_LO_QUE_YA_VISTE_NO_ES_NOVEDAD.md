# 83 — Lo que ya viste no es novedad: vigilancia incremental (P2.5 · API + UX)

> Prompt de producto para Codex, **backend + frontend**. Cierra el carril de búsqueda de
> licitaciones: la vigilancia guardada deja de ser una consulta que se repite y pasa a
> avisar solo de lo que el usuario **no ha visto todavía**. Se apoya en todo lo anterior:
> ámbito temporal honesto (74), perfil comparable (76), wizard gobernado (78, D-063), su UI
> (80, D-066), contratos recuperables (81, D-068) y feedback + replanificación (82,
> `da5142a`).
>
> La regla: la novedad es un hecho determinista —un `folder_id` que no estaba en la memoria
> de vistos—, nunca una valoración del modelo. Ni una llamada IA en todo este prompt.

## 1 — Restricciones medidas que definen el diseño

- Las vigilancias son **solo `active`**: Signal v1 no conserva búsquedas guardadas con otro
  ámbito (`_validate_saved_search_temporal_scope`, 422 en otro caso). El incremental vive
  sobre licitaciones abiertas, que es justo donde la novedad importa.
- El índice de licitaciones abiertas es pequeño y medido: **2.247 totales, 637 activas**
  (línea base 2026-07-23). Recorrer una vigilancia entera es barato; no hace falta cursor
  remoto ni paginación heroica. Pero `tenders` tiene rate limit 60/min y caché de 90 s: el
  barrido se presupuesta por tenant y por ciclo, y se declara.
- Signal v1 **no ofrece ordenación ni cursor estable** (D-043, propuesta v2 pendiente): la
  detección no puede depender de «lo que llegó después de X», solo de comparar identidades.
  Esa es la razón de ser de la memoria de vistos.
- Ya existe toda la fontanería durable: colas `signals`/`notifications`/`maintenance`,
  `BackgroundJob` con dispatch por beat cada 30-60 s, recuperación de jobs colgados, y
  tareas `notifications.send_digest` / `notifications.evaluate_alerts` con separación
  permanente/reintentable. **Reutilízala; no inventes un scheduler paralelo.**

## 2 — Memoria de vistos

Modelo tenant-scoped (migración Alembic con RLS, patrón de la 0023): por vigilancia guardada
y `folder_id`, cuándo se vio por primera vez y cuándo se marcó como revisado, más la huella
del ítem para detectar cambios materiales.

- **Decide y justifica qué es «cambio material»** de una licitación ya vista: un hash sobre
  campos que importan al analista (importe, deadline, estado canónico, título/objeto). Un
  cambio de `feed_updated_at` sin cambio de contenido **no** es novedad — si no, cada ciclo
  reabriría todo. Documenta qué campos entran en la huella y por qué, con un item real
  medido de ejemplo.
- Semántica de «revisado»: qué acción del usuario marca un ítem como visto. Decide entre
  explícito (botón), implícito (abrir la vigilancia), o ambos con distinto peso — y
  justifícalo. Lo innegociable: el usuario debe poder entender por qué algo dejó de ser
  novedad, y el feedback del 82 (relevante/no-relevante) sobre un ítem implica visto.
- Retención: define cuánto vive la memoria de una vigilancia borrada y de ítems ya cerrados,
  con tarea de limpieza en la cola `maintenance` (hay precedente: `documents-retention`).

## 3 — El barrido incremental

Tarea durable por vigilancia (cola `signals`, despachada por beat con la cadencia que
decidas y declares; los TTL de 90 s no justifican barridos de un minuto):

- Ejecuta la búsqueda guardada, compara identidades y huellas contra la memoria, y produce
  un resultado explícito: **nuevos**, **cambiados** (con qué campo cambió) y **ya vistos**.
- **Idempotente y reanudable**: dos ejecuciones seguidas sin cambios en Signal no producen
  novedad nueva; una ejecución interrumpida a mitad no pierde ni duplica. Es el invariante
  que el resto de vuestros jobs ya cumple y que aquí se prueba explícitamente.
- Sin novedades no se notifica **nada**. El silencio es el estado correcto y frecuente: una
  vigilancia que avisa cada día de lo mismo se desactiva mentalmente en una semana, y
  entonces el producto ha perdido su único canal proactivo.
- Errores de Signal degradan, no rompen: el barrido falla como reintentable
  (`ProcurementProviderError` ya distingue `retryable`) y la UI muestra la última ejecución
  con éxito y su fecha, nunca un cero silencioso que parezca «no hay nada nuevo».

## 4 — Notificación agrupada y honesta

- Reutiliza el camino durable de notificaciones ya existente. Agrupa por vigilancia y por
  ciclo: «3 licitaciones nuevas en *Equipamiento de emergencias*», con el detalle de los
  ítems y su enlace a la vigilancia. Nunca un aviso por licitación.
- Respeta las preferencias de notificación existentes; si no encajan, decláralo como
  dependencia en vez de crear un canal paralelo. Frecuencia y desactivación por vigilancia
  son del usuario, y activarlas es opt-in explícito — coherente con D-063: nada se enciende
  solo.
- El contenido es determinista: título, comprador, importe, deadline, estado canónico y
  motivo de match (los mismos badges verificables de la búsqueda). Ningún resumen generado.

## 5 — UI: la novedad se ve, y se puede vaciar

- En el aside «Vigilancia» de `/app/procurement`: contador de novedades por búsqueda
  guardada, fecha de la última ejecución con éxito y estado de la anterior si falló.
- Al abrir una vigilancia, los ítems nuevos y cambiados se distinguen visualmente (badge
  «Nuevo» / «Cambió: deadline»), con acción de marcar como revisado —individual y en
  bloque— y **deshacer**, igual que el feedback del 82. Estilo neutro: esto es dato, no IA.
- Si una vigilancia lleva tiempo sin novedades, dilo con normalidad («Sin novedades desde
  el 20-07»). Es información, no un fallo que disimular.

## Verificación exigida

- Tests backend: detección de nuevos/cambiados/ya vistos sobre fixtures; huella que ignora
  `feed_updated_at` puro y detecta cambio material; idempotencia (dos barridos seguidos → 0
  novedades nuevas); reanudación tras interrupción; sin novedades → **ninguna**
  notificación encolada; error de proveedor → reintentable y última ejecución con éxito
  preservada; tenant scoping y RLS en memoria de vistos; retención.
- Test de **cero LLM**: un ciclo completo de barrido + notificación no incrementa
  `AIUsageLedger`.
- Tests frontend: contador de novedades, badges nuevo/cambiado, marcar revisado con
  deshacer, estado de última ejecución fallida.
- Migración aplicada, revertida y reaplicada en limpio; RLS validado A/B.
- **Cada test nuevo verificado por mutación**: di qué mutaste y qué test cayó.
- Gates completos de ambos lados nombrados por separado, suite backend integrada **entera**
  (con el bloqueo advisory que resolvió la carrera), OpenAPI + cliente sin deriva, Vitest
  completo, build y Playwright del wizard extendido con el camino de vigilancia.
- Smoke con sesión real si hay Signal configurado; si no, declarado como no verificado.

## Qué NO hacer

- Ni una llamada IA: ni para decidir novedad, ni para resumir el aviso, ni para priorizar.
- No notifiques cuando no hay novedades, ni por ítem, ni ignorando preferencias.
- No inventes cursores ni órdenes que Signal no ofrece (D-043); no amplíes la vigilancia a
  `historical`/`all` mientras el 422 siga siendo la verdad medida.
- No crees un scheduler propio ni un canal de notificación paralelo al durable existente.
- No marques ítems como revisados por efecto colateral de un barrido: revisar es del
  usuario.
- No abras el P3 (embeddings/pgvector): sigue cerrado hasta que un eval demuestre que el
  recall determinista se queda corto.
