# ORACLE EXP · INVESTIGACIONES — Propuesta de metodología

Etiqueta: `#ORACLE#EXP#INVESTIGACIONES` · Estado: **borrador para revisión** · Fecha: 2026-07-23

Objetivo del documento: dado un objetivo de investigación (p. ej. la filial española de una
multinacional), mapear su red de administradores y sociedades vinculadas en varios niveles,
cruzar esa red con la contratación pública, y producir un informe con listados + narrativa
amplia con opinión — ejecutado en varias pasadas con Ollama local, aunque tarde horas.
Este documento propone la metodología, la arquitectura de pasadas, los prompts (borradores
para revisión) y el plan de fases. No es un documento de implementación: tras la revisión,
cada fase se bajará a prompts numerados en `docs/implementation/prompts/`.

---

## 1. Veredicto corto

**Se puede hacer, y ~70% del andamiaje ya existe en Oracle.** El grafo societario con
familias de roles, el histórico registral BORME vía Signal, el corpus PLACSP de
adjudicaciones, el protocolo de evidencia con citas validadas, los jobs durables con lease y
reanudación, y el runtime Ollama con salida estructurada son exactamente las piezas que esta
metodología necesita. Lo que falta es: (a) el agregado "Investigación" que encadena pasadas
con checkpoints, (b) la pasada de desambiguación de identidad (el problema técnico nº 1),
(c) tres prompts nuevos, y (d) los guardrails legales de la sección de opinión.

Hay **tres realidades duras** (verificadas contra las fuentes en julio 2026) que condicionan
el diseño y que hay que aceptar de entrada:

1. **Los licitadores que se presentan y no ganan NO están en el dato estructurado de
   PLACSP.** El XML CODICE solo publica el *número* de ofertas recibidas
   (`ReceivedTenderQuantity`) y la identidad del adjudicatario. La identidad de los
   presentados vive en PDFs adjuntos (actas de mesa, resoluciones de adjudicación, art. 63.3
   LCSP) con cobertura irregular según el órgano. Conclusión: el MVP cruza la red con
   **adjudicaciones** (+ nº de ofertas como señal de competencia); la minería de actas PDF es
   una fase avanzada, no un requisito de arranque.
2. **El BORME no publica NIF de personas ni socios/accionistas.** Solo nombres de cargos
   (nombramientos/ceses desde 2009) y, como excepción, el socio único de unipersonales. Dos
   "GARCÍA LÓPEZ, JOSÉ" son indistinguibles por el dato bruto. La expansión multinivel sin
   control de homonimia fabrica redes falsas: la pasada de desambiguación (heurística +
   Ollama + confirmación humana) es el corazón de la metodología, no un adorno.
3. **La "opinión" tiene límites legales claros.** El art. 19 LOPDGDD cubre datos de
   contacto/función de personas físicas, no valoraciones; la sanción AEPD del caso Camerdata
   (eInforma) y la doctrina del TS sobre ficheros de solvencia exigen calidad del dato y
   diligencia. Y el AI Act convierte en alto riesgo puntuar a personas físicas. Regla de
   diseño: **la opinión se emite sobre sociedades y sobre la estructura de la red; sobre
   personas físicas, solo hechos registrales fechados y citados, jamás valoraciones.**

---

## 2. Qué ya tenemos (mapa de reutilización)

| Necesidad de la metodología | Pieza existente | Estado |
|---|---|---|
| Histórico registral de una entidad (actos BORME, cargos, fechas) | Signal `registry/{company\|person}` vía `EntityIntelClient`; `cached_registry_view` pagina hasta 10.000 actos | Producción |
| Grafo de vínculos con familias de roles (gobierno/representación/auditoría/propiedad/liquidación) | `_GRAPH_ROLE_ALIASES` + contrato de roles en `entity_intel.py`; D-057/D-058 | Producción (profundidad 2, 300 nodos) |
| Adjudicaciones PLACSP por empresa + análisis agregado determinista | `ProcurementClient`, `build_entity_procurement_analysis`, `fetch_award_history` (paginado con backoff) | Producción |
| Protocolo de evidencia: citas validadas, `allowed_evidence_ids`, techos declarados, `source_limits` | `entity_dossier_report.py` + `validate_evidence` + tests de `test_verification_protocol.py` | Producción |
| Evidencia pendiente con UUID5 estable y materialización al incorporar | `build_pending_entity_evidence_sources` / `_materialize_pending_entity_evidence` | Producción |
| Jobs durables: lease + fencing, heartbeat, backoff, outbox, reanudación por beat | `BackgroundJob`, `execute_durable`, `recover_stale_jobs` | Producción |
| Ollama con salida estructurada (JSON Schema nativo), temperatura 0, coste 0 | `OllamaLLMProvider` (`format=schema`), `AI_MODE=ollama` | Producción |
| Candidatos de entidad con revisión humana (importar/descartar) | `ActorCandidateReview`, `actor_candidates.py` | Producción |
| Actores y relaciones persistentes multi-tenant con evidencia por vínculo | `Actor`, `Relationship`, `RelationshipEvidence` | Producción (poco explotado) |
| Filtro determinista de atribución exacta de nombre | `filter_entity_web_mentions` (`common/web_mentions.py`, prompt 73) | Sin commitear |
| Resolución de entidad con `needs_review` ante homónimos | Agente `entity_resolution` v1 | Producción |
| Descarga segura de PDFs oficiales PLACSP (allowlist, magic `%PDF-`, límites) | `procurement_report.py` (`PLACSP_DOCUMENT_HOSTS`) | Producción |

Lo que **no** existe: agregado de investigación multi-pasada, índice inverso
persona→sociedades a escala (hay que validar qué expone Signal), desambiguación de
homónimos, prompts de redacción por capítulos, y NIF en cualquier punto de la cadena
(la identidad hoy es `nombre + kind`).

---

## 3. Las fuentes, en frío (lo verificado)

**BORME.** API de datos abiertos del BOE: `GET https://www.boe.es/datosabiertos/api/borme/sumario/{AAAAMMDD}`
(header `Accept: application/json` obligatorio), con `url_xml` por ítem provincial. El XML de
BORME-A **no** está estructurado por acto: es texto corrido que exige gramática propia de
parseo (la librería `bormeparser`, archivada en 2024, sirve como especificación). Cobertura
digital desde 2009. Cargos publicados: Adm. Único/Solid./Mancom., Consejero, Con.Delegado,
Presidente, Secretario, Apoderado, Auditor, Liquidador… Sin NIF de personas, sin socios
(salvo socio único). Índice inverso persona→sociedades ya construido: **LibreBOR**
(comercial, ~0,21 €/crédito, mín. 2.000 créditos/mes) o gratuitos sin garantía
(OpenMercantil). *Para Oracle: Signal ya ingesta BORME; la pregunta operativa es si expone
consulta inversa a escala — a validar en F0.*

**PLACSP.** Tres feeds ATOM vivos con payload CODICE (perfil del contratante, plataformas
autonómicas agregadas, menores) + ZIPs históricos 2012–2026. El adjudicatario lleva
`PartyIdentification/cbc:ID @schemeName` = NIF / UTE / OTROS — es decir, **NIF casi siempre,
pero no siempre** (UTEs y extranjeras no). Licitadores no ganadores: solo en PDFs (ver §1).
TED (API v3, anónima) como complemento para umbrales UE. *Para Oracle: el corpus vive en
Signal; `winner` llega como texto libre sin NIF — mejora a pedir a Signal, no a duplicar.*

**Registros mercantiles.** No hay API pública self-service: nota mercantil ~9–18,50 € +
IVA por sede electrónica (trae NIF del administrador — el verificador definitivo para nodos
críticos). Comerciales con API: eInforma (~8–30 €/informe, registros desde céntimos),
Axesor, Iberinform — su valor añadido es precisamente la desambiguación con NIF.
OpenCorporates España: congelado desde 2011, inservible para cargos vigentes. Titularidad
real (RECTIR): solo con interés legítimo acreditado, sin API, tras STJUE C-37/20.

**Marco legal.** Base: interés legítimo (art. 6.1.f RGPD) con LIA documentada; el art. 19
LOPDGDD no cubre valoraciones de personas. Doctrina TS ficheros de solvencia: exactitud +
actualidad + pertinencia, no solo veracidad. Práctica del sector (World-Check, Informa D&B):
"la inclusión no implica riesgo", valoración como opinión orientativa, cada dato fechado y
trazado a fuente oficial. Retención de cargos cesados: vigencia registral + plazo de
prescripción de acciones de responsabilidad (4 años, art. 241 bis LSC) como referencia. AI
Act: informes sobre empresas no son alto riesgo; puntuar personas físicas sí (línea roja);
declarar asistencia de IA (art. 50.4, práctica defensiva estándar).

---

## 4. La metodología: 6 pasadas encadenadas

Principio rector (el mismo del informe competitivo actual): **todo lo que pueda ser
determinista, es determinista en Python; el LLM solo juzga ambigüedad y redacta.** Los
listados del informe final NO los escribe el modelo: salen de agregados computados. Ollama
entra en cuatro puntos: desambiguar homónimos, (fase avanzada) extraer licitadores de PDFs,
redactar capítulos y sintetizar la lectura estratégica.

Cada pasada es una **cadena de jobs cortos e idempotentes** (patrón `execute_durable`
existente), no un job monolítico de 5 horas: así el lease/heartbeat actual funciona sin
tocarlo, cada nivel del grafo es un checkpoint natural, y una caída a mitad de investigación
reanuda desde el último nivel cerrado, no desde cero.

```
P0 Semilla ──► P1 Núcleo ──► P2 Expansión (nivel a nivel) ──► P3 Contratación ──► P4 Consolidación ──► P5 Redacción
   config       registral      [checkpoint humano opcional]      de la red          evidencia+métricas    map-reduce
   humana       determinista   heurística + Ollama + humano      determinista       determinista          Ollama 9b/27b
```

### P0 — Semilla y alcance (minutos; determinista + humano)

Resolución del objetivo con `registry/suggest` + agente `entity_resolution` (existente):
nombre canónico + variantes (el patrón `person_name_variants` ya rota nombres españoles).
El usuario fija la **configuración de la investigación**, que queda congelada en el agregado:

- Profundidad: **2 niveles por defecto** (objetivo → sus cargos → otras sociedades de esos
  cargos), 3 como máximo explícito.
- Familias de roles a expandir: **gobierno + propiedad** por defecto; representación
  (apoderados) opcional — genera mucho ruido; auditoría/liquidación solo como anotación.
- Corte temporal: cargos cesados hace más de **4 años** no expanden (alineado con la
  retención legal de referencia; configurable).
- Techos: p. ej. 150 sociedades / 300 personas / 1.500 llamadas Signal por investigación.
- Enriquecimiento de pago (NIF): apagado/encendido por investigación (ver decisión D2).

### P1 — Núcleo registral (minutos; determinista)

Corpus completo del objetivo vía `cached_registry_view` (hasta 10.000 actos,
`history_complete`). Se extraen: cargos vigentes e históricos con fechas, y — oro para esta
investigación — **administradores persona jurídica** (sociedad A administra sociedad B:
vínculo empresa-empresa directo sin problema de homonimia personal) y declaraciones de
**socio único** (la única ventana de BORME al accionariado; así se detecta la matriz de una
filial sin comprar datos). Resultado: frontera de nivel 1, cada elemento con sus actos BORME
como evidencia pendiente (UUID5 estable, patrón existente).

### P2 — Expansión por niveles (la pasada larga nº 1; determinista + Ollama + humano)

Para cada persona/sociedad de la frontera, consulta inversa en Signal → sociedades donde
consta con cargo. Cada vínculo candidato pasa un **triaje de identidad en tres capas**:

1. **Heurística determinista** (gratis, resuelve la mayoría): rareza del nombre (frecuencia
   en el corpus), co-ocurrencia societaria (¿comparte otra sociedad con un nodo ya
   confirmado?), coherencia provincial y solapamiento temporal de cargos. Umbrales → alta /
   ambigua / descartada.
2. **Pasada Ollama `investigation_identity_match`** (qwen3.5:9b, llamadas cortas) solo sobre
   las ambiguas: recibe los dos perfiles registrales (actos, fechas, provincias,
   co-administradores) y emite `same | different | uncertain` + confianza + razonamiento.
   Nunca decide sola un merge: `same` con confianza alta se acepta con marca de método;
   `uncertain` va a cola humana.
3. **Cola de revisión humana** (patrón `ActorCandidateReview` existente: importar/descartar)
   para los `uncertain` y para todo nodo que vaya a expandirse al siguiente nivel con
   confianza < alta. Regla dura: **ningún nodo con identidad no confirmada genera
   expansión** (la homonimia no se propaga).

Vínculos aceptados → `Relationship` (tipo = rol canónico, `confidence`, `valid_from/to`) +
`RelationshipEvidence` → actos BORME. Al cerrar cada nivel: checkpoint (snapshot de frontera
en el agregado), throttle de cuota Signal (precedente `_call_waiting_out_rate_limit`), y
pausa opcional para revisión antes de abrir el siguiente nivel.

### P3 — Contratación pública de la red (decenas de minutos; determinista)

Para cada sociedad confirmada de la red: `fetch_award_history` +
`build_entity_procurement_analysis` (existentes). Como `winner` es texto libre sin NIF, cada
adjudicación se etiqueta con **confianza de identidad** reutilizando la lógica de atribución
exacta de nombre de `web_mentions` (secuencia completa de tokens + sufijo legal); las no
exactas se listan aparte como "posibles, sin confirmar". Agregados de red computados en
Python: importes y CPVs por sociedad y por nivel, concentración de compradores, y las dos
señales que dan sentido a la investigación:

- **Órganos de contratación compartidos**: dos o más sociedades de la red adjudicatarias del
  mismo comprador (el caso "el objetivo no licita con el Ministerio X, pero su red sí").
- **Densidad competitiva**: nº de ofertas recibidas (`ReceivedTenderQuantity`) en las
  licitaciones ganadas por la red, si Signal lo expone (a validar en F0).

Alcance declarado del MVP: solo adjudicaciones publicadas; sin tasa de éxito (no hay
presentadas); menores de plataformas agregadas fuera. Todo va a `source_limits` — el
protocolo actual ya sabe declarar recortes.

### P3b — Presentadas no ganadoras (fase avanzada, opt-in; Ollama sobre PDFs)

Para licitaciones seleccionadas (p. ej. las de órganos compartidos): descarga de
resoluciones/actas (precedente seguro de `procurement_report.py`: allowlist
`contrataciondelestado.es`, magic PDF, límites de tamaño) + pasada Ollama
`tender_bidder_extraction` que extrae la lista de licitadores del texto. Cobertura irregular
por órgano → cada extracción lleva la URL del documento como evidencia y confianza; lo no
extraíble se declara. Esta es la pasada "aunque tarde horas" por excelencia y se ejecuta
como cola aparte, reanudable.

### P4 — Consolidación y verificación (minutos; determinista + revisor)

Se congela el **corpus de la investigación**: snapshot con hash (patrón
`source_snapshot`/`corpus_hash` existente) para que P5 trabaje sobre datos inmutables aunque
la redacción tarde horas y las cachés TTL caduquen. Se construye la evidencia citable por
capítulo con techos propios (el cap global de 45 del dossier se queda corto: aquí se
presupuesta **por capítulo**, con `balance_evidence_sources` reutilizado para que ningún tipo
de fuente desaparezca). Métricas globales computadas (`arithmetic_policy`: el modelo no
recalcula nada).

### P5 — Redacción map-reduce (la pasada larga nº 2; Ollama)

Dos etapas, porque el contexto local es finito (8k tokens por defecto) y un informe de red
no cabe en una llamada:

- **Map — `investigation_chapter_writer`** (qwen3.5:9b): un capítulo por bloque — núcleo,
  red nivel 1, red nivel 2, contratación de la red, señales externas. Cada llamada recibe
  solo su porción del corpus + sus `allowed_evidence_ids`; emite párrafos
  `fact`/`inference` con citas bajo el contrato `ReportOutput` ya validado.
- **Reduce — `investigation_synthesis`** (qwen3.6:27b, el modelo grande del patrón wizard):
  recibe los capítulos ya escritos (sin corpus bruto) + métricas globales; redacta Resumen
  ejecutivo, **Lectura estratégica** (la opinión amplia: patrones de la red, dependencia del
  sector público, concentraciones llamativas, hipótesis marcadas como inferencia con
  confianza) y Cobertura y límites.

Verificación: pasada `evidence_reviewer` sobre map y reduce con política **`reject_output`**
(un informe de investigación con una cita rota no sale; ver decisión D5). El informe final =
plantilla nueva `investigation_network.v1.json` (mismo motor que `entity_intelligence.v2`):
narrativa con citas + **listados como tablas deterministas anexas** (sociedades por nivel
con confianza, cargos, adjudicaciones por sociedad, órganos compartidos) que no pasan por el
LLM.

### Presupuesto de tiempo orientativo (profundidad 2, red mediana: ~15 cargos, ~120 sociedades)

| Pasada | Llamadas | Tiempo de pared estimado |
|---|---|---|
| P0–P1 | ~5 Signal + 1 LLM corta | < 5 min |
| P2 | ~200–600 Signal (rate limit 30/min) + 100–300 LLM cortas 9b | 1–2,5 h |
| P3 | ~120 series paginadas Signal | 20–40 min |
| P4 | 0 LLM | < 5 min |
| P5 | 6–10 capítulos 9b + 1 síntesis 27b + revisor | 1–2 h |
| **Total** | | **~2,5–5 h** (P3b aparte: +1–3 h según nº de PDFs) |

Ajustes de runtime necesarios: `OLLAMA_TIMEOUT_SECONDS` (default 60 s) debe subir por tarea
(síntesis 27b: 1.800 s); la investigación necesita su propia `AITenantPolicy` o excepción
(el default `daily_call_limit=100` se agota en P2; `max_output_tokens=6500` recortaría la
síntesis). F0 debe medir tokens/s reales de ambos modelos en el hardware de producción.

---

## 5. Modelo de datos (mínimo nuevo, máximo reutilizado)

Nuevo agregado tenant-scoped `Investigation`: objetivo (entity_key), configuración congelada
(profundidad, familias, cortes, techos, enriquecimiento), estado de pasada
(`current_pass`, frontera serializada por nivel, contadores de presupuesto), snapshots con
hash por pasada, y FK a los `BackgroundJob` de cada pasada. La red confirmada se persiste en
lo que ya existe — `Actor` + `Relationship` + `RelationshipEvidence` — con una tabla de
enlace `InvestigationActor` (patrón `links.py`: PK compuesta con tenant). Ventaja directa:
la red queda viva en el expediente después del informe (moat de memoria acumulada, según
`ORACLE_COMPETITIVE_MOAT.md`), y una segunda investigación sobre un objetivo cercano reusa
identidades ya confirmadas por humanos.

Coherencia con D-015/D-046 (Signal como autoridad única de datos): las fuentes estructuradas
nuevas que esta metodología pide (consulta inversa a escala, `ReceivedTenderQuantity`,
`counterpart_kind`, y a futuro TED/BDNS) se piden a Signal, no se ingestan en Oracle. La
única excepción, con precedente ya en producción, es la descarga de PDFs oficiales de
PLACSP para P3b.

---

## 6. Guardrails legales (condiciones de salida del informe)

1. **Opinión solo sobre sociedades y estructura de red.** Sobre personas físicas: hechos
   registrales fechados con cita BORME, sin adjetivos, sin scoring (línea roja AI Act
   Anexo III 5.b). El prompt de síntesis lo prohíbe explícitamente y el revisor lo verifica.
2. **Lenguaje de red neutro**: "consta como administrador en" / "coincide temporalmente
   con", nunca "controla", "testaferro", "entramado" ni imputación de irregularidad. La
   coincidencia de red **no implica coordinación ni riesgo** — frase obligatoria en el
   informe (estándar World-Check).
3. **Cada afirmación con fuente + fecha de consulta** (el protocolo de evidencia actual ya
   lo impone); fechas BORME = fecha de publicación, declarado en límites.
4. **Retención**: cargos cesados > 4 años no se expanden ni se destacan (referencia art.
   241 bis LSC); aparecen solo como histórico citado si son materiales.
5. **LIA documentada** (interés legítimo: due diligence mercantil del cliente) + política
   pública de fuentes y derechos + canal de oposición/supresión con evaluación caso a caso
   (art. 14 RGPD: la sanción Camerdata cayó por esto, no solo por el art. 6).
6. **Disclaimer fijo en cabecera del informe** (borrador, adaptado de la práctica del
   sector):

   > Informe elaborado con asistencia de IA exclusivamente a partir de fuentes públicas
   > (BORME, PLACSP y menciones web citadas y fechadas), reproducidas tal como constan en
   > origen. Los vínculos societarios se basan en coincidencias registrales de cargos; la
   > aparición en este informe no implica riesgo, coordinación ni irregularidad alguna. La
   > sección "Lectura estratégica" es una opinión automatizada de carácter orientativo
   > sobre las sociedades analizadas: no constituye asesoramiento legal o financiero ni
   > valoración de personas físicas. Verifique la información en la fuente antes de decidir.
   > Derechos RGPD: [canal].

---

## 7. Borradores de prompts (para tu revisión)

Formato del registro actual (`## Tarea` / `## Reglas` / `## Contrato de salida`
obligatorias). Esquemas Pydantic nuevos en `ai/schemas.py` cuando se implemente.

### 7.1 `investigation_identity_match/v1.md` (P2, qwen3.5:9b, llamadas cortas)

```markdown
## Tarea
Recibes dos perfiles registrales con el mismo nombre o nombres muy similares: el PERFIL A
(un cargo ya confirmado en la investigación) y el PERFIL B (una aparición candidata en otra
sociedad). Cada perfil incluye: nombre publicado, sociedades donde consta, cargos, fechas de
nombramiento/cese y provincias de los registros. Decide si corresponden a la misma persona o
entidad.

## Reglas
- Solo puedes usar los datos de los perfiles. No inventes ni supongas datos externos.
- Señales a favor de identidad: co-ocurrencia en una misma sociedad; cargos simultáneos en
  sociedades del mismo grupo, provincia o sector; nombre infrecuente (tres o más tokens,
  apellidos poco comunes); continuidad temporal coherente.
- Señales en contra: solapamientos imposibles; provincias distantes sin ningún puente
  societario; nombre muy frecuente sin ninguna otra señal.
- El BORME no publica NIF: la certeza absoluta no existe. Con señales insuficientes,
  responde "uncertain" — nunca fuerces un veredicto.
- Un veredicto "same" con confianza < 70 se tratará como "uncertain" aguas arriba.

## Contrato de salida
JSON con: verdict ("same" | "different" | "uncertain"), confidence (0-100), signals_for
(lista de señales observadas, máx. 5), signals_against (ídem), rationale (una frase, máx.
40 palabras, sin datos no presentes en los perfiles).
```

### 7.2 `investigation_chapter_writer/v1.md` (P5-map, qwen3.5:9b)

```markdown
## Tarea
Redacta UN capítulo del informe de investigación de red societaria. Recibes: el nombre del
capítulo, el subconjunto del corpus que le corresponde (vínculos confirmados con su
confianza, actos registrales, adjudicaciones con su confianza de identidad, métricas
computadas) y los identificadores de evidencia autorizados (allowed_evidence_ids).

## Reglas
- Todo párrafo "fact" cita al menos un evidence_id autorizado; conteos e importes solo de
  computed_metrics, nunca calculados por ti.
- Los vínculos con confianza media o los importes de adjudicaciones sin coincidencia exacta
  de nombre se redactan siempre como "inference" con confianza explícita, nunca como hechos.
- Personas físicas: solo hechos registrales (cargo, sociedad, fechas, fuente). Prohibido
  cualquier adjetivo, valoración, conjetura o inferencia sobre una persona física.
- Vocabulario de red obligatorio: "consta como", "coincide con", "figura en". Prohibido:
  "controla", "opera a través de", "entramado", "testaferro" o cualquier término que
  implique coordinación, ocultación o irregularidad.
- No abras ni cierres el informe: escribes un capítulo interior, sin resumen ni conclusión
  general. Los caveats van al campo de límites, no intercalados.
- 250-450 palabras por capítulo; párrafos de 60-150 palabras.

## Contrato de salida
Mismo contrato ReportOutput del sistema: paragraphs[] con kind (fact | inference), texto,
evidence_ids y confidence en las inferencias; sin source_index propio (se consolida en la
síntesis); sin UUIDs en prosa.
```

### 7.3 `investigation_synthesis/v1.md` (P5-reduce, qwen3.6:27b)

```markdown
## Tarea
Recibes los capítulos ya redactados y validados de una investigación de red societaria
(núcleo, red por niveles, contratación pública de la red, señales externas) junto con las
métricas globales computadas y los límites de cobertura declarados. Redacta las tres piezas
que faltan: Resumen ejecutivo, Lectura estratégica y Cobertura y límites.

## Reglas
- No introduces hechos nuevos: trabajas exclusivamente sobre lo que los capítulos ya
  afirman con sus citas. Puedes referenciar evidence_ids que aparezcan en los capítulos.
- La Lectura estratégica es la sección más larga y la única con opinión. La opinión versa
  sobre sociedades y sobre la ESTRUCTURA de la red: patrones de concentración, dependencia
  del sector público, compradores compartidos, densidad competitiva, vacíos de información.
  Toda tesis es "inference" con confianza explícita y con los hechos capitulares que la
  sostienen nombrados en el propio párrafo.
- Prohibido: valorar personas físicas; afirmar o insinuar coordinación, ocultación, fraude
  o irregularidad; convertir recomendaciones en decisiones; presentar una hipótesis como
  hecho. La coincidencia registral de cargos no acredita unidad de decisión: si formulas
  una hipótesis de grupo, dilo con esas palabras y confianza.
- Cobertura y límites concentra TODOS los caveats al final (fuentes recortadas, homonimia
  residual, ausencia de licitadores no adjudicatarios, fechas de publicación BORME), sin
  abrir el informe pidiendo disculpas.
- Resumen ejecutivo 150-250 palabras; Lectura estratégica 500-800; total 800-1.300.

## Contrato de salida
ReportOutput completo: executive_summary, paragraphs[] (fact | inference | recommendation),
top_opportunities/top_risks/recommended_actions (3-5), source_index solo con evidencias
realmente citadas.
```

### 7.4 `tender_bidder_extraction/v1.md` (P3b, fase avanzada — borrador anticipado)

```markdown
## Tarea
Recibes el texto extraído de un documento oficial de una licitación pública española (acta
de mesa de contratación, informe de valoración o resolución de adjudicación). Extrae la
lista de licitadores presentados que el documento identifique.

## Reglas
- Extrae solo denominaciones que el documento presente explícitamente como licitadores,
  ofertas presentadas o admitidos/excluidos. No infieras participantes de menciones de otro
  tipo (avales, subcontratistas, medios adscritos).
- Conserva la denominación literal del documento; no normalices ni completes razones
  sociales.
- Registra si el documento distingue admitidos y excluidos, y el adjudicatario si consta.
- Si el documento no contiene lista de licitadores, devuelve la lista vacía con
  has_bidder_list=false. No deduzcas el número de ofertas de otros pasajes.

## Contrato de salida
JSON con: has_bidder_list (bool), bidders[] (name literal, status: admitido | excluido |
adjudicatario | sin_especificar), document_kind (acta | informe_valoracion | resolucion |
otro), extraction_notes (frase única si hay ambigüedad material, si no null).
```

---

## 8. Plan de fases

**F0 — Spike de validación (2-4 días).** Sin esto, todo lo demás es humo:
1. ¿Signal soporta consulta inversa persona→sociedades a escala y con qué profundidad y
   cuota? (El grafo actual está centrado y truncado a profundidad 2/300 nodos.)
2. ¿Expone `ReceivedTenderQuantity` y `counterpart_kind`? Si no: petición formal a Signal.
3. Medir tokens/s reales de qwen3.5:9b y qwen3.6:27b y estabilidad de salida estructurada
   en llamadas de 30-60 min (timeout, memoria).
4. Prueba de fuego de homonimia: 20 personas reales del corpus (10 nombres raros, 10
   comunes) por el triaje de tres capas; medir precisión contra verificación manual.
   → Resultado en `docs/implementation/spikes/`, y decisión go/no-go de D1-D3.

**F1 — MVP listados (~2 semanas).** `Investigation` + P0-P3 + cola de revisión de identidad
en UI (reutilizando el patrón de candidatos) + export de listados deterministas (sin
narrativa). Ya vendible: es exactamente la "due diligence ligera que hoy se hace a mano"
del posicionamiento comercial.

**F2 — Informe narrativo (~1-2 semanas).** Prompts 7.1-7.3 + esquemas + plantilla
`investigation_network.v1.json` + P4-P5 + revisor con `reject_output` + disclaimer +
entradas en DECISIONS.md (LIA y política de retención).

**F3 — Avanzado (a demanda).** P3b (minería de actas: prompt 7.4), TED, BDNS/subvenciones
(el cruce con dinero público no licitado), enriquecimiento NIF de pago para nodos críticos,
RECTIR con interés legítimo para titularidad real.

---

## 9. Decisiones que necesito de ti antes de empezar

- **D1 · Desambiguación.** ¿Arrancamos solo con triaje gratuito (heurística + Ollama +
  revisión humana; precisión media, coste 0) o presupuestamos verificación externa para
  nodos críticos (nota mercantil ~9-18 €/nodo, LibreBOR ~0,21 €/consulta con mínimo
  2.000/mes, eInforma por contrato)? *Mi recomendación: F1 gratuito; presupuesto de notas
  puntuales solo para los 5-10 nodos que sostengan las tesis del informe.*
- **D2 · Alcance del MVP.** ¿Confirmas adjudicaciones-solo en F1 y "presentadas" (minería
  de PDFs) a F3? *Recomendación: sí; el nº de ofertas recibidas ya da señal competitiva sin
  minar PDFs.*
- **D3 · Parámetros por defecto.** ¿Profundidad 2, familias gobierno+propiedad, corte 4
  años, techo 150 sociedades? (Cada investigación puede sobreescribirlos.)
- **D4 · Política de opinión.** ¿Confirmas opinión limitada a sociedades/estructura y
  personas físicas solo con hechos registrales? ¿Apruebas el disclaimer de §6?
- **D5 · Verificación.** ¿`reject_output` para capítulos y síntesis (más lento, cero citas
  rotas) y revisor en Ollama local? Contexto: existe la pregunta abierta de si el revisor
  local (0% rechazo vs 69% del cloud) es demasiado laxo — esta feature es el mejor banco de
  pruebas para responderla con datos.

---

## 10. Riesgos y límites que el producto debe declarar siempre

- **Homonimia residual**: sin NIF de personas, ningún vínculo persona-sociedad es certeza
  absoluta; el informe muestra la confianza de cada vínculo y el método que lo validó.
- **Accionariado invisible**: BORME no publica socios (salvo socio único). Una filial
  participada sin administradores compartidos es invisible para esta metodología sin fuentes
  de pago. Se declara en Cobertura y límites.
- **Presentadas no ganadoras**: fuera del dato estructurado; cobertura irregular incluso
  minando PDFs.
- **Redes ≠ grupos**: la coincidencia de administradores no acredita grupo ni coordinación;
  el informe lo dice y el lenguaje lo respeta.
- **Explosión combinatoria**: un administrador profesional (secretarios de consejo,
  despachos) puede conectar cientos de sociedades irrelevantes; el corte por familias de
  rol + techos + revisión humana en frontera existe exactamente para esto. Candidato a
  heurística F2: marcar "conectores de alta cardinalidad" y no expandirlos por defecto.
