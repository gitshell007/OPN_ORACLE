# 97 — Licitaciones: CPV, retrieval multivector y ejecución multi-sonda (ayuda al agente)

**Prompt:** `97`  
**Depende de / complementa:** `96_LICITACIONES_BUSCAR_CON_ORACLE.md`  
**Ámbito:** Oracle (wizard, post-proceso del plan, execute) + opcional Signal (índice/enriquecimiento)  
**Objetivo de este documento:** dar al agente de implementación el **análisis ya hecho**, la **arquitectura óptima** y un **plan verificable**, sin redescubrir el problema desde cero.

---

## 0. Cómo usar este prompt

1. Lee primero `AGENTS.md` y el prompt **96** (definición de hecho de «Buscar con Oracle»).
2. Este **97** baja al **cómo** mejorar la traducción texto→CPV y la ejecución de búsqueda de forma **multi-sector** (no solo defensa).
3. No hardcodees verticales (defensa, bomberos, energía) en el core ni en el prompt de runtime de la IA.
4. Prefiere capas deterministas + taxonomía local antes que un prompt monstruo con `if sector`.

---

## 1. Problema resumido (para el agente)

### 1.1 Qué quiere el usuario

Escribe en lenguaje natural (cualquier sector), por ejemplo:

- defensa / vehículos militares / blindados / comunicaciones, o  
- EPIs y extinción para bomberos, o  
- baterías, obras, TIC, etc.

y espera **licitaciones PLACSP en la tabla central** tras **Aceptar y buscar**, no solo un plan versionado ni vigilancias vacías en el panel derecho.

### 1.2 Qué hay en el sistema (medido)

| Pieza | Realidad |
|--------|----------|
| Índice de licitaciones | **Signal**, tabla `placsp_open_tenders` (~225k filas, ~1,8k activas típico) |
| Campos de búsqueda hoy | `title`, `summary_feed` (~150 chars media), `buyer`; filtro `cpv` JSON; URL y `documents[]` |
| Búsqueda Signal keywords | `ILIKE` sobre title/summary/buyer; semántica documentada **`keywords: OR`** entre tokens y columnas |
| Taxonomía CPV en Oracle | Fichero `oracle/data/cpv_2008_es.json` (~**9454** códigos ES), **no** tabla SQL |
| API suggest CPV | `GET /api/v1/procurement/cpv/suggest?q=` |
| Plan IA | Agente `tender_search_wizard` (IA gobernada vía Signal: Ollama/OpenRouter/etc.) → plan con `candidate_cpv` + términos |
| Ejecución inmediata deseada | Multi-sonda + fusión por `folder_id`: `POST /api/v1/procurement/search-plans/execute` |
| Vigilancia Signal | Contrato estrecho (ideal: **1 keyword + 1 CPV**); no es el resultado principal |

### 1.3 Por qué “falla” aunque el índice tenga mercado

1. El **título/resumen del feed** no contiene las mismas palabras que el usuario o la IA.  
2. El **CPV** sí clasifica el mercado, pero si la IA no propone CPV buenos (o propone ruido tipo `3511*` cuando el usuario pedía defensa), la búsqueda se va al mercado equivocado o a 0.  
3. Confundir **panel de vigilancias** con **tabla de resultados**.  
4. Filtros agresivos (p. ej. buyer genérico «Ministerio de Defensa») matan el recall (órganos reales = parques, mandos, secciones).  
5. Un prompt con **condiciones por sector** no escala y contradice el producto transversal.

### 1.4 Caso defensa (ejemplo, no dominio del core)

Texto: *Equipamiento para vehículos del ministerio de defensa o del ejército… blindados, transporte, comunicaciones…*

- En índice activo hay mercado fuerte en **CPV `35400000`** (p. ej. repuestos TOA/ATP/carros, parques de sistemas acorazados).  
- Keywords sueltas tipo `blindados`/`militares` a menudo **0 hits** en title/summary.  
- Por eso CPV + multi-sonda importan más que “más términos en el prompt”.

---

## 2. Principio de diseño (óptimo, multi-sector)

```text
Usuario (texto libre, cualquier vertical)
    → IA propone plan (términos + CPV candidatos)   [genérico]
    → Post-proceso: validar taxonomía + RETRIEVAL CPV por texto  [determinista, multi-sector]
    → CPV_final = unión validada (IA ∪ retrieval), top-K
    → execute multi-sonda (términos + CPV) sin buyer/región del plan
    → Tabla central de resultados
    → Vigilancia opcional (1 kw + 1 CPV prioritario)
```

**El prompt de la IA codifica el contrato, no el mapa de industrias.**  
**La taxonomía + retrieval codifican el mundo.**  
**La multi-sonda usa CPV y términos sin `if defensa` / `if bomberos`.**

### 2.1 Qué NO hacer

- Lista de 50 sectores con CPV fijos en el prompt de runtime.  
- Meter los 9454 CPV en el prompt del modelo.  
- Confiar solo en la IA sin validar códigos.  
- Buscar solo keywords sin CPV.  
- Hacer el crawler de pliegos en Oracle (debe ser Signal si se hace).  
- Tratar defensa como único vertical en el core.

### 2.2 Capas recomendadas

| # | Capa | Multi-sector | Notas |
|---|------|--------------|--------|
| 1 | Prompt corto del wizard | Sí | “CPV de 8 dígitos, específicos, no inventar; si dudas, pocos CPV” |
| 2 | Taxonomía `cpv_2008_es.json` | Sí | Validar code+label |
| 3 | `retrieve_cpv_for_text(text) → top K` | Sí | Trigram/FTS o similar sobre etiquetas del JSON |
| 4 | Fusión IA ∪ retrieval + límites | Sí | Top 5–15 CPV, preferir más específicos |
| 5 | `execute_search_plan` multi-sonda | Sí | Sin buyer/región del plan |
| 6 | Ranking de fusión | Estructural | Especificidad CPV, anti-SDA multi-CPV; **no** lista de industrias |
| 7 | Feedback replan | Sí | Ya existe carril de feedback; no hardcodear verticales |
| 8 | (Opcional Signal) enriquecer texto pliego | Sí | Full-text / tokens; fuera del MVP Oracle si no hay contrato |

---

## 3. Estado ya aterrizado (verificar en el árbol; no asumir sin smoke)

Referencias de trabajo reciente (puede haber avanzado):

- Prompt **96**: definición de hecho «Aceptar y buscar» → tabla central.  
- `POST /api/v1/procurement/search-plans/execute` — multi-sonda + merge `folder_id`.  
- Vigilancia: 1 keyword + CPV prioritario; sin buyer/región del plan en saved-search.  
- Fix path `tender-searches/<search_id>`.  
- Ranking con **prefijos CPV prioritarios** (354, 357, 341…): **útil para defensa pero sesgo**; este prompt pide **generalizarlo** con score de retrieval, no ampliar la lista de prefijos por sector.

Si el código no coincide, manda el código y documenta el delta en `STATUS.md`.

---

## 4. Trabajo pedido al agente (prioridad)

### P0 — Retrieval CPV multi-sector (Oracle)

Implementar algo equivalente a:

```text
retrieve_cpv_for_text(description: str, *, limit: int = 10) -> list[{code, label, score}]
```

- Fuente: `load_cpv_taxonomy()` / `cpv_2008_es.json`.  
- Matching: prefijo numérico si el usuario escribe dígitos; si no, similitud sobre **etiquetas** (y tokens del texto).  
- Sin red, sin LLM, cacheable en proceso.  
- Reutilizar o extender la lógica de `suggest_cpv_codes` si ya cubre parte del caso; el retrieval del **texto largo del usuario** puede necesitar más que el suggest de 2–8 chars del autocomplete.

**Enganche:** tras generar/aceptar el plan (o en `postvalidate` / justo antes de `execute_search_plan`):

```text
candidate_cpv = merge_and_validate(
  plan.candidate_cpv,
  retrieve_cpv_for_text(original_description or plan.intent_summary)
)
```

Reglas de merge (estructurales):

- Solo códigos que existan en taxonomía.  
- Etiqueta canónica de la taxonomía (no la del modelo si diverge).  
- Cap de N CPV (p. ej. 10–15).  
- Preferir códigos más específicos (más dígitos significativos / menor “anchura” jerárquica) cuando hay empate.  
- No borrar todos los CPV de la IA si el retrieval devuelve vacío; y viceversa.

### P0 — Ejecución

- **Aceptar y buscar** debe llamar a **execute** (multi-sonda) para rellenar la tabla.  
- No reintroducir `buyer`/`region` del plan en execute ni en saved-search.  
- Si 0 resultados: mensaje accionable (quitar CPV ruidosos, añadir términos de título reales, etc.), no solo versionar.

### P1 — Quitar sesgo de “prefijos defensa” como estrategia principal

- Sustituir o complementar la lista fija `_PRIORITY_CPV_PREFIXES` por **score del retrieval** o por orden de `candidate_cpv` ya fusionado.  
- Mantener solo penalizaciones estructurales (p. ej. ítems con >15 CPV en la licitación = SDA basura).

### P1 — Prompt del wizard (runtime, versionado)

- Cambio **mínimo** al prompt `tender_search_wizard`: contrato CPV (8 dígitos, específicos, no inventar).  
- **Prohibido** añadir bloques “si el usuario habla de defensa…”.  
- Nueva versión de prompt (`vN`) + registro en audit/PROMPT_VERSIONS según el patrón del repo.

### P2 — Signal (solo si el gate lo pide o hay capacidad)

- Enriquecimiento de texto de pliego / full-text: **repo `opn_signal`**, no Oracle.  
- No bloquear P0 Oracle por el crawler.

### P2 — UX

- Copy: resultados = tabla central; vigilancia = panel derecho.  
- Nombres cortos de vigilancia.  
- Empezar de cero / quitar CPV / no rehidratar basura.

---

## 5. Casos de prueba (obligatorios)

### 5.1 Defensa (regresión del dolor actual)

Input descripción defensa/vehículos/ejército.

- Tras merge, debe aparecer al menos un CPV de familia **354** o **357** si la taxonomía y el texto lo permiten (vía IA o retrieval).  
- `execute` con esos CPV no debe depender de que el título contenga “blindados”.  
- Smoke o test de loader: con CPV `35400000` el índice real tiene mercado activo (verificar en el entorno disponible).

### 5.2 Bomberos / EPIs (multi-sector)

Input tipo extinción/EPIs/bomberos.

- Retrieval/IA deben poder proponer CPV de familia **3511** / ropa trabajo, etc.  
- **No** forzar 354 solo porque el ranking “defensa” mande.  
- Execute devuelve algo coherente o vacío honesto.

### 5.3 Ambiguo

Texto vago (“suministros varios”).

- Pocos CPV, no explosión de 50 códigos.  
- Mensaje claro si 0 hits.

### 5.4 Taxonomía

- Código inventado por el modelo → descartado o corregido.  
- Label mismatch → etiqueta canónica.

### 5.5 Tests

- Unit: `retrieve_cpv_for_text` con frases sintéticas (defensa, bomberos, genérico).  
- Unit: merge IA ∪ retrieval.  
- Unit: execute merge (ya hay base en `test_procurement_search_preview.py`).  
- Wizard: Aceptar y buscar usa execute (no solo run de vigilancia).  
- Ningún test que afirme solo nombres de símbolos o strings del prompt.

---

## 6. Definición de hecho de este prompt

- [ ] Existe retrieval CPV local multi-sector enganchado al plan antes de execute.  
- [ ] No hay árbol de condiciones por sector en prompt de runtime ni en core.  
- [ ] Aceptar y buscar rellena tabla vía multi-sonda en happy path con CPV correctos.  
- [ ] Caso bomberos/EPIs no queda roto por sesgo defensa.  
- [ ] Tests + STATUS actualizados; commit en `master` con `Prompt: 97`; push.  
- [ ] Resumen con comandos y riesgos (Signal crawler fuera de alcance salvo acuerdo).

---

## 7. Archivos / zonas probables (Oracle)

- `apps/api/src/opn_oracle/oracle/cpv_taxonomy.py`  
- `apps/api/src/opn_oracle/oracle/data/cpv_2008_es.json`  
- `apps/api/src/opn_oracle/oracle/procurement_search_preview.py` (`execute_search_plan`, `saved_search_payload`)  
- `apps/api/src/opn_oracle/ai/tender_search_wizard.py` (postvalidate)  
- `apps/api/src/opn_oracle/ai/prompts/tender_search_wizard/*`  
- `apps/api/src/opn_oracle/integrations/procurement_routes.py`  
- `src/components/procurement/procurement-search-wizard.tsx`  
- Tests: `test_procurement_search_preview.py`, wizard vitest, opcional integración  

Signal (solo P2): `placsp_open_tenders`, `search_tenders`, futuros campos de texto enriquecido.

---

## 8. Preguntas abiertas (no bloquear P0)

1. ¿El retrieval CPV usa solo trigram/FTS o embeddings del catálogo? (MVP: lexical; embeddings después.)  
2. ¿Se enriquece el plan en el servidor en **generate** (al materializar el artifact) o solo en **accept/execute**? Preferible **accept/execute** (y opcionalmente generate para que la UI muestre CPV ya fusionados).  
3. ¿Signal expone búsqueda full-text de pliego en v1? Hoy no; no depender de ello para cerrar 97.

---

## 9. Resumen en una frase para el agente

**Haz que cualquier texto de usuario se traduzca a CPV de la taxonomía local (IA + retrieval determinista) y se ejecute en multi-sonda sin filtros de comprador ni reglas por sector; la tabla central es el resultado, la vigilancia es un subconjunto estrecho para avisos.**

---

## 10. Relación con el prompt 96

| 96 | 97 |
|----|-----|
| Problema de producto y UX de «Buscar con Oracle» | Cómo acertar CPV y ejecutar bien **en todos los sectores** |
| Definición de hecho de aceptar → resultados | Retrieval CPV + merge + des-sesgo defensa |
| Caso canónico defensa | Defensa como regresión + bomberos/ambiguo como multi-sector |

Cumplir 97 sin traicionar 96: el usuario sigue viendo **licitaciones en la tabla**, no un plan vacío ni un panel de vigilancias inútiles.
