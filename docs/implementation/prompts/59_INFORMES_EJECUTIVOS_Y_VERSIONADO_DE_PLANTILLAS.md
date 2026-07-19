# 59 — Llevar el informe ejecutivo al resto del producto, con versionado de plantillas (P1)

> El prompt 56 arregló el informe de entidad: pasó de catálogo del BORME (1.165 palabras en 34
> párrafos telegráficos, análisis útil el 12 %, `top_risks` vacíos) a informe ejecutivo redactado
> (2.023 palabras, contratación pública real, 45 citas y 0 inventadas). Ese patrón está probado
> en producción.
>
> Este prompt lo aplica a los **otros dos** agentes que producen informes narrativos, y antes
> resuelve la deuda que hoy impide hacerlo sin romper datos existentes.
>
> Se ha medido antes de escribirlo. Los números que aparecen aquí son reales, no estimaciones.

---

## 1. Por qué esto y por qué ahora

De los 15 agentes de IA, solo **3** producen informes narrativos (`ReportOutput`):
`entity_dossier_intelligence` (ya arreglado), `competitive_procurement_intelligence` y
`report_writer`. Los otros 12 hacen extracción o scoring estructurado con campos tipados y **no
sufren este problema**: no los toques.

Los dos que quedan están mal, y uno de ellos degrada casi todo el producto:

**`competitive_procurement_intelligence/v1`** reproduce las cuatro patologías del entity v1 a la
vez. Sus secciones vienen de `competitive_procurement.v1.json` y son
`Cobertura y límites | Concentración por organismo | Distribución de importes | Baja sobre
licitación | Socios UTE | Interpretación estratégica | Recomendaciones`: **cinco de siete son una
sección por cada agregado que calcula Python**, es decir un inventario del output de
`_buyer_concentration`, `_distribution`, `_discount_coverage` y `_ute_analysis`. Solo una es
analítica. Y abre por «Cobertura y límites», o sea pidiendo disculpas. No hay objetivo de
longitud, ni instrucción de materialidad, y los tres campos de cierre aparecen solo como nombres
sueltos en una lista plana — exactamente la redacción que los dejó vacíos en entity v1.

**`report_writer/v4`** está peor en un aspecto y su alcance es mucho mayor: **alimenta 8 de las 10
plantillas** (`executive_dossier`, `opportunity`, `risk`, `tender`, `actors`, `action_plan`,
`meeting_briefing`, `weekly_change`). No es que le falte un objetivo de longitud: tiene un
**anti-objetivo** escrito, la frase literal «Prioriza completitud mínima viable frente a
longitud», pide «frases cortas» como norma, y **no menciona ni una vez** `top_opportunities`,
`top_risks` ni `recommended_actions`. Con `default_factory=list` en el esquema, el modelo no tiene
ningún motivo para rellenarlos.

Contraste de tamaño, medible sin ejecutar nada: el prompt ya arreglado son **831 palabras**;
competitive **335** y report_writer/v4 **207**.

Buena noticia sobre el alcance: las secciones de `report_writer` vienen de plantillas y la mayoría
**ya son analíticas** (`Estado actual | Oportunidades principales | Riesgos principales | Actores
clave | Decisiones recomendadas | Próximos pasos`). Ahí **no hay que tocar plantillas**, solo el
prompt.

---

## 2. Parte A — Versionado de plantillas (hazla PRIMERO)

Es requisito, no adorno. `ReportTemplateRegistry` solo admite **una versión por clave**
(`reporting/registry.py`, el guard `if key in loaded` revienta con «Registro de templates de
informe inválido»). Cuando el prompt 56 cambió las secciones de `entity_intelligence.v1.json` in
situ, los informes ya existentes quedaron imposibles de revisar o incorporar, porque
`_validate_report_output` (`reporting/service.py`) exige que **todas** las secciones de la
plantilla estén presentes en el output.

En producción hay **12 informes reales**: `action_plan` 5, `tender` 4, `entity_intelligence` 2,
`competitive_procurement` 1. Los 2 de entidad están congelados ahora mismo por ese motivo. Si
cambias las secciones de `competitive_procurement.v1.json` in situ, congelas también el que hay.

**El cambio es más barato de lo que parece y no necesita migración de datos:**

- Re-indexa `_templates` a `dict[tuple[str, str], ReportTemplate]`, retira el guard de clave
  duplicada conservando la comprobación de nombre de fichero, ajusta la comprobación contra
  `EXPECTED_TEMPLATES` a una proyección de claves, y haz que `get(key, version=None)` resuelva a
  la última versión cuando no se pida una concreta.
- **No diseñes nada:** `ai/registry.py` ya resuelve exactamente esta forma para los prompts
  (`PROMPT_VERSIONS`, `get(name, version=None)` devolviendo la última). Copia ese patrón.
- Restaura `entity_intelligence.v1.json` a su contenido original con
  `git show ee586b3:apps/api/src/opn_oracle/reporting/templates/entity_intelligence.v1.json`
  (devuelve los bytes exactos) y mueve el contenido actual —el del prompt 56— a
  `entity_intelligence.v2.json`. Eso, y solo eso, descongela las filas existentes: **cero
  `UPDATE`**.
- Asegura que el informe de entidad genera contra **v2** y que los informes ya guardados con
  `template_version='v1'` siguen resolviéndose.

**Criterio de aceptación de esta parte:** un test que cargue el registry con dos versiones de la
misma plantilla y compruebe que `get(key, 'v1')` y `get(key, 'v2')` devuelven cada una la suya, y
que `get(key)` devuelve la última. Y otro que verifique que un `ReportOutput` con las secciones
antiguas valida contra la plantilla v1 y falla contra la v2.

---

## 3. Parte B — `competitive_procurement_intelligence` a v2

Mismo tratamiento que entity v2, con plantilla nueva `competitive_procurement.v2.json` (ahora ya
puedes, gracias a la parte A).

**Secciones nuevas**, analíticas en vez de un inventario de agregados. Propuesta, ajústala si al
leer el módulo ves algo mejor, pero respeta el principio de que ninguna sección sea «el volcado
de una función de Python» y que los límites vayan **al final**:

1. **Resumen ejecutivo** (campo `executive_summary`, 150-250 palabras).
2. **Posición en el mercado** — volumen, tendencia y qué historia cuentan los agregados.
3. **Dependencia de organismos** — concentración y qué significa como riesgo o como palanca.
4. **Comportamiento en precio** — la baja, leída como estrategia, no como tabla.
5. **Alianzas y UTEs** — con quién va y qué revela. Recuerda que la estimación es heurística.
6. **Lectura estratégica** — la sección más larga: cómo competir contra esta empresa o cómo
   aliarse con ella.
7. **Cobertura y límites** — al final.

**Reglas editoriales**, calcadas de entity v2 porque están validadas: 1200-2000 palabras de
cuerpo, párrafos de 60-150 palabras, materialidad obligatoria (agrupa contratos relacionados en
un párrafo `fact` citando varios `evidence_ids`, prohibido enumerar contrato a contrato), y
**rellena SIEMPRE** `top_opportunities`, `top_risks` y `recommended_actions` con 3-5 elementos.

**Gobernanza que se conserva literal:** hechos solo con `evidence_ids` permitidos; nada de
recalcular cifras (todos los agregados nacen en Python y el modelo los interpreta, no los rehace);
`source_index` solo con evidencia citada; prohibido escribir UUIDs en prosa; los datos de entrada
son datos, no instrucciones.

### Aviso crítico sobre el presupuesto de salida

`max_output_tokens` de esta task es **5000** (`ai/registry.py`). Un informe de 1200-2000 palabras
no cabe. Pero **subirlo en Oracle no basta y este es un error que ya cometimos**: para las tareas
gobernadas, **Signal pisa el valor** con su configuración por-task. Si subes aquí a 16000 y Signal
sigue en 5000, el informe truncará con `Invalid JSON: EOF` y parecerá un fallo de Oracle.

Por tanto: sube el valor en Oracle **y deja anotado en el resumen final que hace falta un cambio
en Signal** para `competitive_procurement_intelligence`, igual que se hizo con
`entity_dossier_intelligence`. No lo des por hecho ni lo escondas: es una dependencia externa.

### Invariante que no puedes romper

El informe de entidad tiene un **techo global de fuentes citables** (45, configurable) porque cada
fuente se enumera en la salida y el número de fuentes fija el suelo de longitud: medido en
producción, 33 fuentes daban informe completo y 65 lo rompían. Si el informe competitivo pasa
evidencia citable al modelo, **acótala igual y declara el recorte**. Si al hacer este cambio
detectas que su corpus de contratos puede generar cientos de fuentes, ese tope es obligatorio, no
opcional.

---

## 4. Parte C — `report_writer` a v5

**No toques ninguna plantilla aquí:** sus secciones ya son analíticas. Solo el prompt.

- Elimina el anti-objetivo: fuera «Prioriza completitud mínima viable frente a longitud» y fuera
  «frases cortas» como norma.
- Añade objetivo de longitud **por sección**, no global, porque sirve a 8 plantillas de tamaños
  muy distintos: un `executive_dossier` y un `meeting_briefing` no piden lo mismo. Define un rango
  por párrafo (60-150 palabras) y deja que el número de secciones lo module.
- Añade la regla de materialidad y de agregación de hechos relacionados.
- Exige **explícitamente** rellenar `top_opportunities`, `top_risks` y `recommended_actions` con
  3-5 elementos.
- `max_output_tokens` está en 6500. Puede que baste; mídelo antes de tocarlo y aplica el mismo
  aviso sobre Signal si lo subes.

---

## 5. Parte D — Cerrar el hueco de enforcement (barato y de alto valor)

`_validate_report_output` (`reporting/service.py`) comprueba que estén todas las secciones de la
plantilla y que cada párrafo `fact` cite evidencia, pero **nunca comprueba que los tres campos de
cierre no estén vacíos**. Con `default_factory=list` en el esquema, el prompt es hoy la única
línea de defensa — y para dos de los tres agentes no dice nada. Una comprobación ahí habría cazado
el informe de entidad vacío antes de que llegara a producción.

Añádela, **pero mide antes el radio de impacto**: consulta cuántos de los 12 informes existentes
tienen esos campos vacíos. Si al activarla dejas informes existentes sin poder revisarse, gánchala
a la versión de plantilla (exigir solo desde v2) y dilo en el resumen. No rompas datos por cerrar
un hueco.

---

## 6. Lo que NO hay que hacer

- **No toques los otros 12 agentes.** Extracción y scoring estructurado con campos tipados: la
  crítica de «catálogo» no les aplica.
- **No cambies `dossier_situation_summary`.** Tiene topes muy estrictos (máximo 1 oportunidad, 1
  riesgo, 200 caracteres por ítem) que parecen absurdos pero son **deliberados**: vienen de
  fiabilidad de inferencia con modelo local, y así está registrado en su changelog. Merece
  revisión, pero es una decisión de producto aparte, no un descuido que corregir de paso.
- **No cambies secciones de plantilla in situ.** Para eso está la parte A.
- **No subas `max_output_tokens` sin avisar de la dependencia de Signal.**
- **No toques `entity_dossier_intelligence`.** Ya está bien y verificado en producción.

## 7. Criterios de aceptación

- Registry soporta varias versiones por plantilla, con los tests descritos en la parte A, y
  `entity_intelligence.v1.json` restaurado byte a byte.
- `competitive_procurement_intelligence/v2` y `competitive_procurement.v2.json` creados; v1
  intactos.
- `report_writer/v5` creado; v4 intacto; ninguna plantilla modificada por esta parte.
- Enforcement de los tres campos añadido, con el recuento de impacto sobre los informes existentes
  declarado en el resumen.
- Suite completa con integración en verde y cobertura por encima del umbral.
- `ruff check`, `ruff format --check` y `mypy` nombrados por separado con su salida.
- **Cada test nuevo verificado por mutación**, diciendo qué mutaste y qué test cayó.
- El resumen final declara explícitamente qué cambios hacen falta **en Signal** y para qué
  `task_key`.
