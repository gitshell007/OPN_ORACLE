# 45 — Informe de IA sobre una entidad, con incorporación a expediente al terminar (P1, feature nueva)

> Prompt de producto para Codex. Feature nueva pedida por el responsable: generar con IA un informe
> de una entidad a partir de toda su ficha (grafo de relaciones, noticias, órganos y cargos) y, **una
> vez terminado** (puede tardar), preguntar a qué expediente incorporarlo. Reutiliza el patrón
> asíncrono ya probado del prompt 43. Depende de que exista el alta de actor externo del prompt 44
> (7.7); coordínalos.

## Lo que se quiere

Desde la ficha de una entidad (`Actores`), un botón «Informe de la entidad» que:

1. Lance un job de IA que analice **toda la información de la entidad**: perfil registral, órganos y
   cargos (BORME), grafo de relaciones y noticias.
2. Corra en segundo plano con estado visible (puede tardar minutos), como el informe competitivo.
3. Al **terminar**, pregunte al usuario **a qué expediente** incorporar el informe, y lo incorpore.

## Lo que he verificado (2026-07-17 — confírmalo, no lo des por supuesto)

**El corpus ya es una sola llamada.** `EntityIntelClient.dossier(name, kind, external_tenant_id)`
(`apps/api/src/opn_oracle/integrations/entity_intel.py:397`) devuelve `entity` + `sections` con la
ficha agregada que Signal ya compone (perfil, órganos, grafo, noticias según disponibilidad). No
tienes que orquestar cuatro llamadas: parte de esta. Complementa con `graph()` y `registry()` solo si
necesitas el detalle que la ficha agregada no traiga, y decláralo.

**La tensión arquitectónica central — resuélvela antes de codificar.** Los informes de este sistema
son **de expediente**: `Report.dossier_id` forma parte de las claves y constraints
(`oracle/models.py:866`), **no es nullable**. Pero aquí el informe se genera **sin expediente** y se
adjudica a uno **al final**. Esa contradicción es el corazón del diseño y no se puede ignorar.

Opciones (razónalas y elige, documentando en `DECISIONS.md`):

- **Área de espera de entidad:** el job genera el informe como artefacto **no adjuntado**, guardado
  contra el tenant + la identidad de la entidad (no contra un dossier). Al terminar, la UI pide
  expediente; incorporarlo **materializa** el informe como `Report` de ese expediente a partir del
  contenido ya generado. Es lo que mejor encaja con «preguntar al terminar», y evita tocar el
  esquema de `reports`. **Mi recomendación.**
- **`dossier_id` nullable:** invasivo — toca claves, constraints y todo el flujo de reports. Solo si
  demuestras que la opción anterior no es viable.
- **Elegir expediente al lanzar:** más simple, pero **contradice el requisito** («una vez esté
  finalizado»). No la elijas sin confirmarlo con el responsable.

**Depende del prompt 44 (7.7).** Incorporar el informe a un expediente implica que la entidad externa
pase a ser un `Actor` interno vinculado (`DossierActor`). Ese alta de actor desde entidad externa se
diseña en el prompt 44. Aquí **reúsalo**; no dupliques la lógica. Si el 44 aún no está, di que este
prompt queda bloqueado por esa dependencia en vez de improvisar el alta.

## Alcance A — El job asíncrono

Copia el patrón de `oracle.competitive_procurement_report.generate` (prompt 43), que ya funciona:

- Celery, cola `ai`, `BackgroundJob` durable, reintentos con backoff, `correlation_id`. Nunca en la
  petición HTTP.
- Signal `/ai/run` es lento (`ORACLE_SIGNAL_AI_TIMEOUT_SECONDS=210`) y Ollama tarda minutos: el job
  debe tolerarlo y reflejar `queued → running → succeeded/failed`.
- **Rate limit:** la ficha agregada es una llamada, pero si complementas con `graph`/`registry`
  reutiliza el helper de tolerancia a 429 del prompt 43 (`_call_waiting_out_rate_limit`) en vez de
  reescribirlo. No dejes que un 429 tumbe el job entero.
- Idempotency-Key generada por intento de usuario (no por render). El bug del prompt 36 no se repite.

## Alcance B — La gobernanza de IA

Idéntica disciplina que el prompt 43 (AGENTS.md §12):

- Oracle envía **solo la task_key** (algo como `entity_dossier_intelligence`). Signal decide
  proveedor, modelo, failover y presupuesto. No cablees `ollama`/`titan`/`openrouter` ni nombres de
  modelo en Oracle. Si la task_key hay que darla de alta en el administrador de Signal, documéntalo
  en `OPEN_QUESTIONS.md` (la del 43 ya existía; esta puede que no).
- Prompt versionado en `ai/prompts/entity_dossier_intelligence/v1.md`.
- Salida con schema: hechos, inferencias y recomendaciones **separados**, confianza explícita,
  incertidumbre declarada. `AIAuditLog` con proveedor y modelo realmente usados, versión de prompt,
  latencia y coste.
- **Honestidad obligatoria**, como en el 43: las fechas BORME son de publicación, no registrales; los
  homónimos no están desambiguados; el grafo no incluye capital ni porcentajes; las noticias pueden
  no ser de la entidad exacta. El informe debe declarar estos límites, no fingir certeza.

## Alcance C — La interfaz

- Botón «Informe de la entidad» en la ficha (`entity-dossier.tsx`), junto a lo existente.
- Estado pendiente visible mientras corre (como el panel del informe competitivo del 43: encolado,
  progreso, cancelar), **no** un spinner infinito. Que el usuario pueda salir y volver.
- **Al terminar**, un paso claro de «Incorporar a expediente» con selector de expediente destino. El
  informe no se pierde si el usuario no elige en el momento: queda disponible para incorporar luego.
- Un aviso realista de que puede tardar minutos.

## Criterios de aceptación

- [ ] Decisión sobre dónde vive el informe antes de adjudicarlo, razonada en `DECISIONS.md`.
- [ ] Job asíncrono con estado visible, Idempotency-Key y tolerancia a llamadas de minutos y a 429.
- [ ] Oracle no cablea proveedor ni modelo; los usados quedan en el informe y en `AIAuditLog`.
- [ ] El informe declara sus límites de fuente; hechos/inferencias/recomendaciones separados.
- [ ] Al terminar, se puede elegir expediente e incorporarlo, materializando el actor vía el 44.
- [ ] `scripts/api-test.sh --unit` **ejecutado** (`uv` en `~/.local/bin/uv`) + lint/typecheck/tests
      del frontend. Nada de `bash -n` como sustituto de ejecutar.
- [ ] Verificado con `ITURRI SA` en producción; si no hay sesión, declarado como no verificado.

## No hacer

- No metas el análisis en la petición HTTP: es un job.
- No cablees modelos ni proveedores en Oracle.
- No dejes que el LLM calcule nada que puedas calcular en Python (conteos de relaciones, de actos…).
- No fuerces elegir el expediente al lanzar sin confirmarlo: el requisito es preguntar al terminar.
- No dupliques el alta de actor externo del prompt 44 ni el helper de rate limit del 43: reúsalos.
- No presentes noticias u homónimos no desambiguados como hechos verificados de la entidad.
