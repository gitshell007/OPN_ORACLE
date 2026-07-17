# 43 — Informe de inteligencia competitiva en contratación pública (P1, feature nueva)

> Prompt de producto para Codex. Primer intento deliberado: el responsable ya ha avisado de que el
> resultado habrá que ajustarlo. Lo que **no** es negociable es la honestidad del análisis: es
> mejor un informe que diga «no puedo calcular esto y por qué» que uno que invente una media sobre
> una muestra sesgada. Lee entero el apartado «Lo que he verificado» antes de diseñar nada.

## Qué se quiere

Un informe generado por IA sobre el comportamiento de un adjudicatario en contratación pública,
que responda a preguntas de estrategia comercial:

- **¿Dónde se presenta más?** Concentración por organismo licitador: quién le compra, cuánto y con
  qué frecuencia.
- **¿Por qué cantidades licita?** Distribución de importes: dónde juega, tramos, atípicos.
- **¿Cuál es su baja media sobre el importe de licitación?** Cuánto rebaja frente al presupuesto
  inicial (ver la advertencia crítica más abajo).
- **¿Con quién se suele presentar?** Socios recurrentes en UTE.

Es asíncrono: se lanza y queda pendiente hasta que la tarea de IA en Signal termina.

---

## Lo que he verificado (2026-07-17, en producción — no lo des por supuesto, confírmalo)

### 1. Los modelos NO se eligen desde Oracle

Signal ya tiene los tres proveedores en `app/config.py`: `ollama_base_url`, `ollama_titan_base_url`
y `openrouter_base_url`. Y `POST /api/v1/ai/run` resuelve proveedor y modelo con
`resolve_ai_task_choice(db, consumer, settings, task_key, requested_provider, requested_model)`
según los ajustes de cada consumer. Además tiene:

- `llm_provider_order = "ollama,openrouter"` — orden de failover configurable.
- `openrouter_monthly_budget_usd` — tope mensual que, al superarse, **degrada a Ollama en vez de
  romper**.
- `GET /api/v1/llm/providers` y `/llm/providers/models` — catálogo consultable.

Oracle ya llama así: `ai/provider.py:726` envía `"task_key": request.agent`.

**Por tanto: registra una `task_key` nueva y deja que Signal elija proveedor y modelo.** No cablees
`ollama`/`titan`/`openrouter` ni nombres de modelo en Oracle: violaría el `SignalAvanzaAdapter`
(AGENTS.md §10) y obligaría a desplegar Oracle para cambiar de modelo. Las task_keys existentes son
`tender_summary`, `oracle_chat` y `oracle_reasoning` — sigue ese patrón.

Si la task_key nueva hay que darla de alta también en Signal, **no lo hagas desde este repo**:
documenta en `OPEN_QUESTIONS.md` qué hay que registrar allí y con qué nombre.

### 2. ⚠️ La «media a la baja» puede no ser calculable — verifícalo ANTES de prometerla

La adjudicación **no trae el importe de licitación inicial**. Claves reales que devuelve Signal en
`registry/awards/{folder_id}`:

```
award_amount, award_date, buyer, cpv, documents, folder_id, is_ute, lot_id,
region, source_url, status, title, winner
```

Para la baja hace falta emparejar la adjudicación con su licitación y usar el `amount` de esta.
Pero al probarlo en producción con `EMERGENCIACR2026/671`:

```
GET /api/v1/registry/tenders/EMERGENCIACR2026%2F671 → 404 Not Found
```

**No existe licitación para ese expediente**, y tiene sentido: `EMERGENCIACR2026` es tramitación de
**emergencia**, adjudicada directamente sin concurso. No hubo licitación, luego no hay baja. Lo
mismo ocurrirá con los negociados sin publicidad.

Además, el cliente de Oracle **no tiene método de lookup de licitación por `folder_id`**:
`tenders()` busca por keywords/CPV/importe, y solo existe `awards_by_folder`. Habría que añadirlo.

**Lo primero que debes hacer es medir la cobertura**: sobre una muestra real de adjudicaciones de un
adjudicatario, ¿qué porcentaje tiene licitación con importe? Reporta el número antes de construir
nada encima. Según salga:

- Si la cobertura es alta, calcula la baja y **declara siempre sobre cuántas adjudicaciones**.
- Si es baja, **dilo y no publiques una media**: una baja media calculada sobre el subconjunto que
  casualmente tiene licitación es un sesgo de supervivencia, y presentarla como «su baja media»
  sería falso. Mejor: «no calculable para N de M adjudicaciones (emergencia/negociado)».

Nunca imputes, estimes ni rellenes el importe inicial que falte.

### 3. El corpus no puede ser solo lo fijado al expediente

El encargo dice «todas las licitaciones que se añadan al expediente», pero el expediente de prueba
tiene **una** adjudicación fijada. Estadísticas de concentración sobre una muestra de uno no
significan nada, y presentarlas como análisis sería ruido con formato de informe.

El histórico real sí es consultable: `ProcurementClient.awards(company=..., limit, offset)` devuelve
las adjudicaciones del adjudicatario. **Mi recomendación**, que debes razonar y confirmar o rebatir:

- **Corpus del análisis:** el histórico completo del adjudicatario en Signal (paginado, con un tope
  razonable y declarado).
- **Foco del informe:** las referencias fijadas al expediente, que son las que le importan al
  usuario y las que aportan evidencia citable.
- Y que el informe **diga siempre sobre cuántas adjudicaciones está hablando** y de qué periodo.

Decide también qué identifica al adjudicatario: la denominación registral exacta. Ojo con los
homónimos y las variantes (`ITURRI, S.A` vs `ITURRI SA`), que ya nos han mordido antes.

### 4. Los socios de UTE están en texto libre

`is_ute` es booleano y los socios van dentro de `winner`, como cadena. Ejemplos reales del
autocompletado: `ITURRI SA Y FABRICA ESPAÑOLA DE CONFECCIONES SA UTE`, `ITURRI SA – GAUZON IBERICA
SLU LEY 18/1982`, `ITURRI, S.A. - GAUZON IBERICA, S.L.U. UTE LEY 18/1982 A CONSTITUIR`.

Extraer socios de ahí es heurística, no dato estructurado. Hazlo si quieres, pero **marca la
confianza como lo que es** y no presentes una lista de socios inferida por parsing como un hecho
verificado. Si el parseo no es fiable, dilo y anota en `OPEN_QUESTIONS.md` que la separación de
socios de UTE debería resolverse en Signal, en origen.

---

## Alcance A — La tarea asíncrona

Sigue el patrón que ya existe y funciona (`oracle.procurement_document_report.generate`):

- Job de Celery en la cola `ai`, con `BackgroundJob` durable, reintentos con backoff, límites de
  tiempo y `correlation_id` (AGENTS.md §11). **No lo hagas dentro de la petición HTTP.**
- `POST` que encola y devuelve `202` con `job_id`, **con Idempotency-Key** (el bug del prompt 36:
  no lo repitas — el cliente debe enviarla, generada por intento de usuario, no por render).
- La llamada a Signal `/ai/run` es **síncrona y lenta**: `ORACLE_SIGNAL_AI_TIMEOUT_SECONDS` está en
  210 s en producción y Ollama puede tardar minutos. El job debe tolerarlo y reflejar el estado
  (`queued` → `running` → `succeeded`/`failed`) para que la UI pueda mostrar «pendiente».
- Si Signal degrada a otro proveedor por presupuesto o failover, **el informe debe registrar qué
  proveedor y modelo lo generaron**. Es parte de la auditoría (AGENTS.md §12).

## Alcance B — El análisis

Los números los calcula **Oracle en Python, no el modelo**. Un LLM no es una calculadora: que sume
importes o promedie bajas es pedirle que se equivoque en silencio. El reparto correcto:

- **Oracle calcula** y pasa al modelo los agregados ya hechos: conteos por organismo, importes
  totales y medianas, tramos, baja media (si procede) con su N, socios detectados y periodo cubierto.
- **El modelo redacta e interpreta**: qué significan esos números para la estrategia, qué patrón se
  ve, qué no se puede concluir.

Salida validada con schema (AGENTS.md §12), con hechos, inferencias y recomendaciones **separados**,
confianza explícita y `evidence_ids` apuntando a las adjudicaciones fijadas. Prompt versionado en
`ai/prompts/` con `name/version`, como los demás. `AIAuditLog` con modelo, versión de prompt,
latencia y coste estimado.

Estadística honesta: mediana además de media (los importes de contratación tienen colas largas y una
sola adjudicación grande desplaza la media), y **nunca un porcentaje sin su denominador**.

## Alcance C — La interfaz

Botón en la pestaña de Licitaciones del expediente, junto a «Informe documental». Estado pendiente
visible mientras el job corre (no un spinner infinito: que se vea que está encolado y se pueda
volver luego). El informe aparece en la pestaña Informes con sus citas.

Y lo más importante: **que se lea qué no se ha podido calcular y por qué**. Si la baja no es
calculable para 8 de 12 adjudicaciones, eso es un hallazgo de negocio —contratación de emergencia—,
no una carencia que esconder.

---

## Criterios de aceptación

- [ ] Cobertura de la baja **medida y reportada** antes de construir el análisis.
- [ ] La task_key la resuelve Signal; Oracle no cablea proveedor ni modelo.
- [ ] Los agregados los calcula Python; el modelo solo redacta e interpreta.
- [ ] El informe declara siempre corpus, periodo, N y lo no calculable.
- [ ] Job asíncrono con estado visible, Idempotency-Key y tolerancia a llamadas de minutos.
- [ ] Proveedor y modelo usados quedan registrados en el informe y en `AIAuditLog`.
- [ ] `scripts/api-test.sh --unit` **ejecutado** (`uv` en `~/.local/bin/uv`), más lint/typecheck/tests
      del frontend. Nada de `bash -n` como sustituto de ejecutar (ver el bug de `gate_path`).
- [ ] Verificado con datos reales: adjudicatario `ITURRI, S.A` en producción. Si no tienes sesión,
      **decláralo como no verificado**.

## No hacer

- No inventes ni estimes el importe de licitación que falte: sin él, no hay baja.
- No publiques una media sin decir sobre cuántos casos se calcula.
- No cablees modelos ni proveedores en Oracle.
- No dejes que el LLM haga aritmética.
- No presentes socios de UTE inferidos por parsing de texto como dato verificado.
- No metas esto en la petición HTTP: es un job.
