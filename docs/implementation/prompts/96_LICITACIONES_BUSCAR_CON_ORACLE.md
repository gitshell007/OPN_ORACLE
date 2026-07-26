# 96 — Búsqueda de licitaciones con Oracle (problema y solución deseada)

**Prompt:** `96`  
**Ámbito:** procurement / wizard «Buscar con Oracle» / Signal Avanza / UI Vector  
**Estado del problema (2026-07-26):** parcialmente mitigado en código (execute multi-sonda, vigilancia 1 keyword, layout wizard); la definición de hecho y la higiene de UX siguen siendo el norte de producto.

---

## 1. Contexto de producto

**OPN Oracle** es un producto de inteligencia estratégica. La entidad central es el **expediente** (`StrategicDossier`). Una capacidad crítica es convertir una **descripción en lenguaje natural** del negocio o del interés comercial en **licitaciones PLACSP accionables**, anclables a un expediente, con vigilancia y siguientes pasos (tareas, oportunidades, riesgos, decisiones).

Oracle debe ser **ofensivo por defecto**: descubrir oportunidades y siguientes acciones, no solo listar un feed.

El backend autoritativo es **Flask `/api/v1`**. La UI canónica es **Vector** (`CANONICAL_UI=vector`). Las licitaciones y búsquedas guardadas se resuelven vía **Signal Avanza** (adaptador), nunca desde el navegador.

---

## 2. Problema que estamos resolviendo

### 2.1 Enunciado (usuario)

El usuario describe qué vende o qué busca, por ejemplo:

> Equipamiento para vehículos del ministerio de defensa o del ejército en general: blindados, transporte, comunicaciones y accesorios

Espera que Oracle:

1. **Proponga un plan de búsqueda** (términos, sinónimos, exclusiones, CPV, compradores, ámbito).
2. Tras **Aceptar y buscar**, **muestre licitaciones reales** coherentes con esa intención.
3. Permita **revisar, descartar y ajustar** el plan (CPV, conservados, chips).
4. Permita **anclar** una licitación a un expediente y continuar el trabajo estratégico (tareas, oportunidades, riesgos, etc.).
5. Opcionalmente **guarde una vigilancia** para novedades, sin confundir vigilancia con “resultado de la búsqueda”.

### 2.2 Dolor observado en producción

1. **Aceptar no implicaba ver resultados útiles**  
   El flujo histórico versionaba el plan (`v1`, `v2`…) o creaba vigilancias Signal, pero el usuario **no veía un listado usable** de licitaciones alineadas con su texto.

2. **El plan de la IA es semánticamente razonable, pero la ejecución en Signal es demasiado restrictiva**  
   - Signal trata la lista de keywords de forma restrictiva (efecto AND / matching estricto).  
   - Un plan con muchos términos (`militares`, `vehiculos`, `blindados`, `defensa`, …) + CPV + comprador genérico tipo **«Ministerio de Defensa»** suele devolver **0 hits**.  
   - En el índice **sí hay mercado** (p. ej. CPV `35400000` → repuestos TOA/ATP/carros especiales en parques de sistemas acorazados), pero los títulos no contienen las mismas palabras que propone la IA.

3. **Confusión UX entre “resultado de búsqueda” y “vigilancia guardada”**  
   El panel derecho muestra vigilancias (nombres largos cortados, `Ejecutar` / `Editar` / `Eliminar`, “0 novedades”, frecuencia 15 min). El usuario cree que **eso es el resultado**; si está vacío o es ruido, concluye que “no funciona nada”.

4. **No se puede empezar limpio**  
   Reabrir el wizard rehidrata planes previos, CPV y “Conservados”; no es obvio descartar y regenerar sin arrastrar basura.

5. **Diseño del wizard**  
   Chips y Conservados se recortan bajo el footer; el diff de versiones es ilegible con muchos items.

6. **Calidad de CPV del modelo**  
   A veces CPV vacíos, o mezcla de defensa real (`354`/`357`) con ruido de extinción/seguridad genérica (`3511*`, SDA municipales multi-CPV).

---

## 3. Objetivo de producto (definición de hecho)

Cuando el usuario pega una descripción de interés (defensa, bomberos, energía, etc.) y pulsa **Aceptar y buscar**:

1. Se acepta un plan versionado (trazable, con artefactos IA).
2. Se **ejecuta de inmediato** una búsqueda que **rellena la tabla central de licitaciones** con resultados **razonablemente alineados**.
3. La **vigilancia** (si se crea) es un complemento, con nombre corto y contrato Signal estrecho, **no** el único canal de resultados.
4. El usuario puede:
   - quitar CPV/términos,
   - empezar de cero,
   - previsualizar sondas,
   - pinnear a expediente,
   - crear tarea/oportunidad/riesgo/decisión.
5. Cero confusión: **resultados = tabla principal**; **vigilancia = panel lateral / guardados**.

---

## 4. Restricciones técnicas (no negociables)

- Backend Flask autoritativo; Node solo presentación.
- Multi-tenant; `tenant_id` de sesión, no del cliente.
- Signal detrás de adaptador; no acoplar UI a su API.
- No llamar a Signal ni a IA desde el navegador.
- Jobs pesados fuera del request HTTP (Celery) cuando aplique.
- Toda salida IA relevante: evidencia, confianza, prompt versionado, auditoría.
- Signal v1 **no** ofrece un boolean query global ni ranking global fiable entre bloques.
- Por diseño de previsualización: las sondas son **independientes**; no inventar un ranking sintético “perfecto”, pero sí una **lista fusionada usable** para “Aceptar y buscar”.

Fuentes de verdad: `AGENTS.md`, memoria de producto, `docs/implementation/STATUS.md`, ADRs y OpenAPI.

---

## 5. Diseño de solución deseado

### 5.1 Plan (IA)

- Entrada: descripción (+ comparable opcional, geografía, importes).
- Salida: plan con `include_terms`, `synonyms`, `exclude_terms`, `candidate_cpv` (taxonomía oficial), `buyers`, `geographies`, `scope`, `confidence`.
- Post-validación: CPV oficiales, sin duplicados conflictivos de términos, descartes explícitos.

### 5.2 Ejecución inmediata (lo que el usuario llama “buscar”)

- **Multi-sonda**: hasta N términos y N CPV por separado (como preview).
- **Fusión por `folder_id`** para la tabla de resultados.
- **No aplicar** buyer/región del plan a las sondas (matching estricto de órganos mata el recall).
- **Priorizar** aciertos en CPV de defensa/vehículo (`354`, `357`, `341`…) y **penalizar** SDA multi-CPV genéricos.
- Endpoint preferido: `POST /api/v1/procurement/search-plans/execute`.

### 5.3 Vigilancia durable (Signal saved search)

- Contrato estrecho: **1 keyword + 1 CPV prioritario**, sin buyer/región genéricos de la IA.
- Nombre corto legible (no el `intent_summary` entero cortado en `…blindv1`).
- `Ejecutar` en el panel lateral puede reconsultar esa vigilancia, pero no debe ser el único camino al éxito.

### 5.4 UX wizard

- CTA principal: **Aceptar y buscar**.
- Acciones: Empezar de cero, Quitar todos (por categoría), × en Conservados, Descartar versión anterior.
- Layout: body scrolleable, footer fijo que no tape chips.
- Microcopy en español de España: separar claramente resultados vs vigilancia.

### 5.5 Recomendación de producto (pregunta abierta resuelta por defecto)

La tabla se llena con **execute multi-sonda**; la vigilancia es un **proxy estrecho** para novedades, documentado como tal.

No exigir que `Ejecutar` en el panel derecho reproduzca **exactamente** la misma lista fusionada, salvo que Signal evolucione el contrato.

---

## 6. Casos de prueba canónicos

### 6.1 Caso defensa (principal)

**Input:**

```text
Equipamiento para vehículos del ministerio de defensa o del ejército en general: blindados, transporte, comunicaciones y accesorios
```

**Esperado:**

- Plan con intención militar/vehículos y CPV preferibles `354*` / `357*` (no solo `3511*` extinción).
- Tras Aceptar y buscar: **tabla con licitaciones**; idealmente órganos tipo parques/mandos y títulos de repuestos/mantenimiento de flotas acorazadas (TOA, ATP, carros, etc.) cuando existan en el índice.
- Pin a expediente OK.
- Vigilancia opcional con nombre corto; no inundar el panel de basura de pruebas.

### 6.2 Caso vacío honesto

Si no hay hits:

- Mensaje claro: plan aceptado pero sin coincidencias en activas; sugerir quitar CPV ruidosos y chips de alto recall (`acorazados`, `repuestos`, `mantenimiento`).
- No versionar en bucle sin feedback.

### 6.3 Caso de higiene

- No dejar vigilancias de test (`tmantenim`, `Verif 9654`, etc.).
- Empezar de cero limpia estado local y no rehidrata Conservados sin acción del usuario.

---

## 7. Métricas de éxito

| Métrica | Objetivo |
|--------|----------|
| Tras Aceptar y buscar, % de sesiones con ≥1 resultado en tabla | Alto en dominios con inventario real (defensa CPV 354) |
| Clics extra hasta ver resultados | 0 (sin “Guardar vigilancia → Ejecutar” obligatorio) |
| Tasa de “0 resultados” con plan rico en CPV prioritarios | Baja |
| Confusión vigilancia vs resultados (feedback usuario) | Eliminada por copy + layout |
| Tiempo hasta pin a expediente | &lt; 2 minutos en happy path |

---

## 8. Fuera de alcance (por ahora)

- Query booleana global tipo Lucene en Signal v1.
- Histórico exclusivo de licitaciones (solo activas / índice disponible según contrato).
- Sustituir Signal; solo adaptar y traducir con honestidad.
- CRM o gestión completa de ofertas.

---

## 9. Trabajo ya aterrizado (referencia, no sustituye la definición de hecho)

Commits / releases orientativos (2026-07-26):

- Wizard: **Aceptar y buscar**, reset/descartar chips, layout.
- Fix rutas `tender-searches/<id>` (`search_id` path converter).
- No proyectar buyer/región del plan a la vigilancia Signal.
- `POST /api/v1/procurement/search-plans/execute` (multi-sonda + fusión + ranking defensa).
- Vigilancia: 1 keyword + CPV prioritario; nombres cortos.

Verificar siempre en el árbol y en `STATUS.md` qué está desplegado; no asumir que “está hecho” sin smoke.

---

## 10. Instrucciones para el agente de implementación

1. Leer `AGENTS.md` y este prompt antes de tocar código.
2. No “arreglar” solo el copy: verificar **comportamiento HTTP** (`search-plans/execute`, accept, pin, run de vigilancia).
3. Probar el caso defensa en integración con Signal real o producción autorizada.
4. Evitar reintroducir buyer del plan en filtros de ejecución inmediata.
5. No acumular vigilancias basura en pruebas; borrar las de test.
6. Actualizar `docs/implementation/STATUS.md`, tests y OpenAPI/cliente TS si cambia contrato.
7. Commitear en `master` por rutas explícitas, `pull --rebase`, push; trailer `Prompt: 96` cuando aplique.
8. Entregar resumen con comandos, resultados, riesgos y siguiente paso.

### Checklist de aceptación del agente

- [ ] Plan generado desde el texto de defensa (o fixture equivalente).
- [ ] **Aceptar y buscar** cierra (o avanza) y rellena la **tabla central** con ≥1 ítem cuando el índice tiene mercado (CPV 354).
- [ ] Panel de vigilancias no es el único camino al resultado; copy no confunde.
- [ ] Empezar de cero / quitar CPV / Conservados funciona.
- [ ] Pin de una licitación a un expediente OK.
- [ ] Tests unitarios del translate/execute y, si aplica, del wizard.
- [ ] Smoke o evidencia de despacho HTTP real en endpoints tocados.

---

## 11. Siguiente paso recomendado (si el prompt se retoma)

1. Smoke UI en producción con el caso defensa y captura de la tabla central.
2. Reducir ruido de CPV `3511*` / SDA en el plan o en el ranking cuando la intención es defensa vehicular.
3. Alinear `Ejecutar` del panel con un mensaje claro: “reconsulta la vigilancia estrecha, no la fusión multi-sonda”.
4. Higiene de vigilancias huérfanas en el tenant de demo.
