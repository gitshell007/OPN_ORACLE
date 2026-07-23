# 76 — La comparable se mide, no se le pregunta al modelo (P1 · carril Oracle)

> Prompt de producto para Codex, **solo backend + script de evaluación**. Sin interfaz: la UI
> de esto llega con el wizard, en el prompt siguiente. Es el carril «Solo Oracle» declarado en
> `docs/integrations/signal-avanza/CONTRACT_V2_PROPOSAL.md` §1: perfil determinista de una
> empresa comparable y taxonomía CPV. No depende de que Signal acepte el contrato v2.
>
> Contexto de producto: cuando el usuario diga «somos parecidos a ITURRI», Oracle debe poder
> responder con hechos —qué CPVs, compradores e importes tiene esa empresa en sus
> adjudicaciones— **antes** de que ningún LLM opine. Ese perfil alimentará al wizard como
> grounding y sirve desde ya como conjunto de evaluación. El nombre de la comparable es
> siempre una entrada del usuario, nunca una regla sectorial del producto.

## 1 — Perfil determinista de comparable: los ladrillos ya existen

`oracle/competitive_procurement.py` ya resuelve lo difícil, reutilízalo en vez de reescribirlo:

- `fetch_award_history` (línea 190): pagina `cached_awards` con `AWARD_PAGE_SIZE`, espera el
  rate limit (`_call_waiting_out_rate_limit`, línea 167), corta en `max_rows` y devuelve
  `provider_total` y `truncated`. ITURRI tiene ~1.251 adjudicaciones ≈ 13 páginas: el coste
  por perfil es real, no lo dupliques por descuido.
- `_cpv_codes` (298), `_normalized_name`/`_company_core` (126/130), `pinned_award_winners`
  (146, maneja UTEs), `_buyer_concentration` (351), `_distribution` (308).

Campos medidos hoy en un item de adjudicación (los únicos que este módulo consulta):
`award_amount`, `award_date`, `buyer`, `cpv`, `folder_id`, `is_ute`, `source_url`, `title`,
`winner`. **No hay región ni `published_at`**: el perfil no puede prometer «regiones
frecuentes» y no debe inventarlas; si algún día llegan, será por contrato, no por heurística.

El perfil de una comparable (entrada: nombre de empresa) contiene, todo determinista:

- CPVs frecuentes con conteo, etiquetados con la taxonomía de la sección 2.
- Compradores habituales con concentración (reusa `_buyer_concentration`).
- Distribución de importes y ventana temporal observada (primer/último `award_date`;
  recuerda las fechas anómalas documentadas en `PLACSP_HISTORICAL_COVERAGE_2026-07-23.md` —
  `0001`, `2029`—: se muestran como vienen, no se corrigen ni se filtran en silencio).
- Términos frecuentes de `title`: tokenización y stopwords castellanas deterministas, sin
  LLM. Decide conscientemente qué hacer con la morralla administrativa («suministro»,
  «servicio de», «expediente»): una lista de stopwords propia del dominio, versionada y
  testeada, no un filtro mágico.
- Participación en UTEs (`is_ute`) y `provider_total` vs filas realmente agregadas, con
  `truncated` visible — patrón D-044: un tope silencioso convierte una muestra en falsa
  exhaustividad.

Expónlo como endpoint nuevo bajo `/api/v1/procurement` (el agregador actual solo se usa desde
informes de dossier en `oracle/routes.py` y jobs; este perfil no exige dossier). Decide y
justifica permiso (`actor.read` como awards, o `opportunity.read`), rate limit conservador
—cada perfil son ~13 llamadas a Signal— y caché con TTL (patrón `EntityIntelCache` de
`integrations/procurement.py:40-42`), porque el perfil de una misma empresa no cambia
intradía. El perfil es agregado derivado y cacheado: **no** persistas filas de adjudicaciones
ni crees todavía modelos `ProcurementSearchProfile` — la memoria tenant-scoped llega con el
wizard.

## 2 — Taxonomía CPV: no existe en el repo, y es dato público estático

Verificado hoy: no hay ninguna taxonomía CPV en el código. El vocabulario CPV es el del
Reglamento (CE) 213/2008, público, estable desde 2008, ~9.454 códigos con descripción en
castellano, descargable de EU Vocabularies/SIMAP.

- Incorpórala como **dato empaquetado en el repo** (JSON o CSV bajo el paquete Python, con
  fuente, fecha de descarga y versión documentadas en el propio archivo o un README junto a
  él). Nada de descargarla en runtime: el loader funciona offline y tiene test.
- Helper de validación y etiquetado: código → descripción, o `None` si no existe. Es la pieza
  que en el wizard descartará CPVs alucinados; aquí etiqueta los CPVs del perfil.
- **Mide antes el formato que envía Signal** en el campo `cpv` de adjudicaciones reales
  (¿`35110000`, `35110000-1`, listas separadas por comas?) y decide la normalización para que
  taxonomía y datos casen. Es la misma lección de la región en el prompt 68 y de D-043: un
  catálogo que no coincide con los valores reales de la fuente rompe el matching. Documenta
  el formato observado con ejemplos crudos.

## 3 — Evaluación sobre la comparable: el perfil se examina a sí mismo

La comparable con volumen conocida es ITURRI (1.251 adjudicaciones medidas), pero el harness
recibe el nombre por parámetro. Objetivo: medir si el perfil derivado de las adjudicaciones
de una empresa habría encontrado sus propias adjudicaciones. Es la línea base de recall que
después usará el wizard.

- **Partición temporal, no aleatoria**: deriva el perfil solo de las adjudicaciones más
  antiguas (por ejemplo el 80 % por `award_date`) y mide sobre el 20 % más reciente qué
  fracción queda cubierta por los top-K CPVs y por los términos frecuentes del perfil (match
  determinista sobre `title`). Simula «¿este perfil habría cazado el siguiente contrato?»,
  que es la pregunta de producto real. Filas con `award_date` no parseable: cuenta aparte,
  visible, jamás descartadas en silencio.
- Ejecución informativa adicional, claramente separada de la métrica: cuántas licitaciones
  devuelve hoy `scope=all` (índice de 2.247 medido en la línea base) para los top CPVs y
  términos del perfil. Es un humo de utilidad presente, no recall — el índice de tenders no
  contiene el histórico.
- El harness vive en `scripts/` (hay precedente en `scripts/spikes/`) o como eval del
  backend, a tu criterio, pero con comando reproducible documentado. El resultado se escribe
  como informe con fecha en `docs/integrations/signal-avanza/` o `docs/implementation/`,
  con las cifras crudas: recall por CPV, por términos, combinado, tamaño de cada partición y
  filas excluidas por fecha inválida.

## Verificación exigida

- Tests unitarios del agregador de perfil sobre fixtures locales: CPVs frecuentes, buyers,
  distribución, términos con stopwords, UTEs, y el caso `truncated=True`.
- Tests del loader CPV: código existente, inexistente, y el formato observado de Signal
  (con/sin dígito de control, según lo que midas).
- Test de **cero LLM**: construir un perfil no incrementa `AIUsageLedger` (el mismo patrón
  que ya usasteis en el prompt 74).
- **Cada test nuevo verificado por mutación**: di qué mutaste y qué test cayó.
- `ruff check`, `ruff format --check`, `mypy src`, suite completa con integración, y
  regeneración de OpenAPI + cliente TypeScript por el endpoint nuevo, nombrados por separado.
- Ejecución real del harness contra producción con la comparable de volumen, informe con
  fecha commiteado. Si no hay credenciales, cada cifra queda declarada como no verificada.

## Qué NO hacer

- Ni una llamada LLM en perfil, taxonomía o evaluación. Este prompt es 100 % determinista.
- No hardcodees ITURRI (ni ningún sector) como constante del producto: es entrada de usuario
  o parámetro del harness.
- No persistas adjudicaciones ni crees los modelos de memoria del wizard: D-028 sigue —
  Signal es el productor; el perfil es un agregado cacheado con TTL.
- No inventes regiones, fechas corregidas ni CPVs normalizados a un formato que Signal no
  envía: lo no medido se declara ausente.
- No empieces el wizard ni toques la UI de `/app/procurement`: ese es el prompt 77 y
  consumirá este endpoint como grounding.
