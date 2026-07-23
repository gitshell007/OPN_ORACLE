# Propuesta de investigaciones empresariales trazables

**Identificador:** `ORACLE-EXP-INVESTIGACIONES`

**Estado:** propuesta para decisión; no autoriza todavía implementación ni uso sobre personas reales

**Fecha:** 2026-07-23

**Ámbito:** metodología genérica; ninguna entidad concreta forma parte del diseño

## 1. Recomendación ejecutiva

La capacidad es viable y encaja de forma natural en OPN Oracle, pero no debe plantearse como
«pedirle a Ollama que busque durante horas». La solución correcta es un **banco de trabajo de
investigación** que:

1. parte de una entidad identificada de forma inequívoca;
2. captura y congela fuentes autorizadas;
3. expande un grafo de relaciones por rondas y con límites explícitos;
4. consulta contratación pública para cada sociedad verificada;
5. extrae de documentos oficiales las participaciones que no estén estructuradas;
6. guarda hechos atómicos, contradicciones, cobertura y evidencia;
7. usa Ollama para extraer, contrastar e interpretar, no como fuente de verdad;
8. redacta un informe amplio con hechos, inferencias, opinión y recomendaciones separados;
9. exige revisión humana antes de promover entidades, relaciones o publicar conclusiones.

La formulación que Oracle sí puede defender es:

> «Sociedades conectadas mediante vínculos registrales observados y actividad de contratación
> localizada en el corpus consultado».

La formulación que Oracle no debe producir sin evidencia adicional es:

> «Empresas que licitan indirectamente por cuenta de la entidad investigada».

Compartir administrador prueba un vínculo registral temporal. No prueba por sí solo control,
pertenencia a grupo, coordinación, influencia, connivencia ni actuación concertada.

## 2. Qué pregunta responde realmente

«Nexo empresarial» es demasiado ambiguo para ser un dato. La investigación debe empezar con una
pregunta falsable y un contrato de alcance:

> A una fecha de corte determinada, ¿qué personas y sociedades presentan vínculos registrales
> directos o de segundo grado con la entidad semilla, qué vigencia tiene cada vínculo y en qué
> procedimientos de contratación pública aparece cada sociedad con un rol demostrable durante el
> periodo estudiado?

Cada investigación congela:

- entidad semilla e identificadores aceptados;
- finalidad y preguntas;
- territorio y periodo;
- fecha de corte de las fuentes;
- relaciones que se pueden seguir;
- profundidad máxima;
- presupuestos de entidades, documentos, tiempo y llamadas IA;
- fuentes permitidas y fuentes excluidas;
- reglas de identidad, evidencia, publicación y parada;
- versión del protocolo, schemas, prompts y política IA.

Una búsqueda sin resultados solo permite afirmar «no localizado en el corpus consultado». Nunca
permite afirmar «no existe» o «no se presentó» si la cobertura de la fuente no es completa.

## 3. Taxonomía: relaciones precisas, no una arista «asociada»

Oracle debe guardar relaciones tipadas, dirigidas y temporales. Como mínimo:

| Familia | Relaciones posibles | Qué demuestra | Qué no demuestra |
|---|---|---|---|
| Gobierno | administrador, consejero, representante de administrador persona jurídica | cargo publicado, con su vigencia conocida | propiedad, control efectivo o coordinación |
| Representación | apoderado, representante | facultad o cargo registral publicado | dirección efectiva de toda la actividad |
| Propiedad/control | socio único, matriz declarada, titular real autorizado | únicamente lo que declara la fuente y su alcance | grupo completo si faltan porcentajes o filiales |
| Profesional | auditor, secretario, asesor | prestación o cargo concreto | asociación empresarial material |
| Operación | UTE, subcontratista, socio de proyecto | relación en un expediente o documento determinado | alianza estable fuera de ese contexto |
| Contratación | licitador confirmado, adjudicatario, excluido, retirado | rol en procedimiento y lote concretos | que actúe en nombre de otra entidad |
| Mención | nombrado en documento | presencia textual verificable | participación o relación si el documento no la define |

Toda arista conserva:

- sujeto y objeto;
- etiqueta original y tipo normalizado;
- dirección;
- `valid_from`, `valid_to` y calidad de la fecha;
- estado `candidate`, `verified`, `disputed`, `rejected`;
- fuente, página/fragmento o puntero estructurado;
- confianza de identidad y confianza de relación, por separado;
- contemporaneidad respecto del hecho analizado;
- decisión humana y motivo, cuando exista.

Ejemplo de un camino defendible:

```text
Entidad semilla
  ─[administrador; vigente 2022–2024; evidencia E17]→ Persona P
  ─[administrador; vigente desde 2021; evidencia E29]→ Sociedad S
  ─[licitador, lote 3; resolución oficial; evidencia E83]→ Expediente X
```

Si el primer cargo había cesado antes de la licitación, el camino se presenta como histórico y no
como vínculo contemporáneo.

## 4. Lo que Oracle ya tiene

La propuesta amplía piezas existentes; no crea un producto paralelo:

- `StrategicDossier` como unidad central, objetivos e hipótesis;
- `Actor`, `DossierActor`, `Relationship` y enlaces a evidencia;
- grafo BORME de profundidad 1–2, ficha registral y revisión humana antes de crear un actor;
- clientes Flask server-side para entidad y contratación servidos por Signal Avanza;
- adjudicaciones y licitaciones PLACSP, snapshots fijados y agregados calculados en Python;
- descarga y parsing de documentos oficiales PLACSP;
- `Document`, `DocumentVersion`, `DocumentChunk` y `Evidence`;
- `Insight` con hechos, inferencias, recomendación y confianza;
- informes versionados con snapshots de evidencia;
- área de espera para un informe de entidad antes de incorporarlo al expediente;
- `BackgroundJob`, Celery, auditoría IA, intentos y feedback humano;
- Cytoscape para explorar grafos densos en Vector.

Los huecos reales son:

1. una ejecución de investigación con frontera, rondas, presupuestos y reanudación;
2. identidad de personas y sociedades candidata, sin contaminar el grafo canónico;
3. consulta de contratación para **cada sociedad verificada**, no solo para la semilla;
4. índice de participantes por expediente y lote, también cuando no ganaron;
5. ledger de claims y contradicciones previo al informe;
6. revisión simétrica con el mismo corpus que recibió el redactor;
7. cobertura y motivos de poda como datos de primera clase.

## 5. Fuentes y jerarquía probatoria

### 5.1 Fuentes núcleo

| Fuente | Uso propuesto | Acceso | Valor probatorio y límite |
|---|---|---|---|
| [BORME / AEBOE](https://www.boe.es/datosabiertos/api/api.php) | actos, nombramientos, ceses, poderes, fusiones y otros eventos | sumario diario JSON/XML y documentos PDF/HTML/XML; disponible desde enero de 2009 según la [FAQ oficial](https://www.boe.es/datosabiertos/faq/borme.php) | fuente oficial de publicaciones históricas; no es por sí sola una foto completa del estado vigente y el PDF firmado es el documento auténtico |
| [Registro Mercantil](https://sede.registradores.org/site/mercantil?lang=es_ES) | confirmar identidad, NIF, representación vigente, capital, actos y cuentas | nota/certificación de pago; búsqueda por denominación, NIF o representación | cierre probatorio para afirmaciones vigentes; no debe vaciarse masivamente ni tratarse como una API abierta |
| [PLACSP](https://contrataciondelestado.es/wps/portal/DatosAbiertos) | procedimientos, lotes, CPV, presupuesto, órganos, resultados, adjudicatarios y documentos | feeds/datasets abiertos CODICE y adjuntos del perfil | fuente principal española; calidad y completitud dependen de publicación y agregación |
| Documentos PLACSP | identidad de licitadores, admitidos, excluidos, retirados y valoraciones | actas de mesa/apertura, informes y resoluciones enlazados desde el expediente | evidencia necesaria para no adjudicatarios; disponibilidad, formato y estructura varían |
| [TED Search API](https://docs.ted.europa.eu/api/latest/intro.html) | procedimientos sujetos a publicidad europea y contraste transfronterizo | búsqueda y descarga de anuncios publicados | no cubre toda la contratación española ni garantiza la identidad de todos los perdedores |

### 5.2 Fuentes de enriquecimiento, no obligatorias para el MVP

- BDNS/SNPSAP para subvenciones y beneficiarios, sin confundir subvención con contrato.
- CNMV para emisores y entidades de su ámbito.
- CNMC para operadores, resoluciones y contexto regulatorio.
- Portal de Transparencia para documentos o huecos de la AGE.
- GLEIF para LEI y relaciones de consolidación declaradas.
- fuentes corporativas y prensa solo como evidencia secundaria y desambiguada.

Las menciones web actuales de Oracle no son una hemeroteca fechada. No deben alimentar conclusiones
de investigación hasta disponer de una fuente con URL canónica, fecha, medio y contrato de
identidad verificable.

### 5.3 El límite decisivo de los no adjudicatarios

La documentación abierta de PLACSP muestra de forma estructurada el adjudicatario, su identificador
y el número de ofertas, pero no una colección fiable de las identidades de todos los licitadores.
Sí expone la existencia de actas y otros documentos publicados en el
[resumen oficial de datos abiertos](https://contrataciondelestado.es/datosabiertos/DGPE_PLACSP_ResumenDatosAbiertos.pdf).
El [artículo 63.3.e de la LCSP](https://www.boe.es/eli/es/l/2017/11/08/9/con) exige publicar en el
perfil el número e identidad de los participantes, las actas, los informes de valoración y la
resolución; que deban publicarse no significa que las identidades estén normalizadas en el feed.

Por tanto, el flujo correcto es:

```text
feed PLACSP/TED
  → descubrir expediente, lotes y adjudicatario
  → obtener documentos oficiales
  → extraer texto/OCR y tablas
  → localizar razón social o identificador
  → clasificar el rol por lote
  → validar página, fragmento y documento
  → revisión humana si hay ambigüedad
```

Estados mínimos de participación:

| Estado | Regla de aceptación |
|---|---|
| `awardee` | adjudicatario estructurado o resolución oficial inequívoca |
| `bidder_confirmed` | documento oficial identifica a la entidad como licitadora/admitida en el lote |
| `lost` | consta como licitadora y consta otro adjudicatario en el mismo lote |
| `excluded` | resolución o acta declara la exclusión y su lote |
| `withdrawn` | documento declara retirada/desistimiento de la oferta |
| `mentioned_unknown` | aparece el nombre, pero el documento no permite asignar rol |
| `unknown` | no se localizó evidencia suficiente; no equivale a no participación |

No se calcula tasa de éxito con procedimientos donde solo se conoce el ganador. No se incorpora una
UTE a cada miembro si el documento no enumera esos miembros.

Para descubrir a escala nacional quién perdió no basta con consultar adjudicaciones por nombre.
Signal debe construir un índice incremental de participantes a partir de documentos PLACSP/CODICE,
o declarar de forma visible que el análisis es dirigido y parcial. Oracle no debe replicar ese
índice nacional dentro de Flask.

## 6. Resolución de identidad

### 6.1 Sociedades

Orden de autoridad:

1. NIF/CIF u otro identificador oficial;
2. LEI cuando proceda;
3. denominación registral exacta + registro/provincia;
4. alias histórico respaldado por un acto;
5. nombre normalizado como generador de candidatos, nunca como prueba final.

Se pueden normalizar de forma determinista puntuación, mayúsculas y formas jurídicas para buscar
candidatos. Un nombre comercial, una abreviatura o una semejanza semántica requieren evidencia.

### 6.2 Personas físicas

Un nombre idéntico no basta para unir dos trayectorias. La coincidencia se queda como candidata
hasta disponer de:

- segundo identificador permitido;
- continuidad registral verificable;
- combinación de nombre, cargo, sociedad, provincia y fechas suficientemente discriminante; o
- revisión humana documentada.

Signal todavía puede entregar en el campo de contraparte tanto personas físicas como firmas. Oracle
no debe inferir el tipo por sufijos como `SL`, por apariencia del nombre ni mediante Ollama. El
contrato upstream debe aportar `counterpart_kind`; mientras no exista, el candidato queda
`unresolved`.

### 6.3 Promoción

El área de investigación conserva candidatos. Solo una acción humana promueve:

- entidad → `Actor` y `DossierActor`;
- vínculo → `Relationship`;
- fuente elegida → `Evidence`;
- procedimiento → `DossierProcurementItem` o futura participación;
- hallazgo → `Insight`, `Hypothesis`, `Opportunity`, `RiskItem` o `Task`;
- resultado final → `Report`.

Así se evita que homónimos, relaciones históricas o menciones débiles contaminen el directorio
compartido del tenant.

## 7. Metodología por rondas

### R0 — Encargo y congelación

- formular pregunta, finalidad y audiencia;
- fijar semilla e identificadores;
- elegir periodo, territorio, relaciones, fuentes y presupuesto;
- registrar base legal/política de tratamiento;
- congelar `protocol_version`, `source_policy_version` y fecha de corte.

### R1 — Identidad de la semilla

- consultar sugerencias y fuentes registrales;
- exigir identificador o aprobación humana;
- parar si no existe una identidad raíz defendible.

### R2 — Captura inicial

- BORME/Registro según disponibilidad y autorización;
- grafo actual e histórico;
- contratación estructurada de la semilla;
- snapshot inmutable con URL, fecha, hash, parser y cobertura.

### R3 — Normalización determinista

- desduplicar actos y versiones;
- calcular vigencias;
- crear candidatos y relaciones tipadas;
- detectar ciclos y supernodos;
- no usar un LLM para aritmética, fechas, caminos o merge por identificador.

### R4 — Revisión de identidad

- autoaceptar solo identificadores oficiales inequívocos;
- enviar homónimos y tipos dudosos a bandeja humana;
- Ollama puede explicar por qué dos registros parecen coincidir, pero no ejecutar el merge.

### R5 — Expansión de frontera

- recorrer por anchura una oleada cada vez;
- profundidad automática recomendada: dos saltos societarios;
- conservar la relación pero no expandir por defecto auditores, secretarios, asesores o
  profesionales ubicuos;
- priorizar gobierno, propiedad demostrada, UTE y representación material;
- registrar cada rama podada y su motivo.

### R6 — Contratación por sociedad verificada

- consultar adjudicaciones y procedimientos por identificador cuando sea posible;
- en su defecto, denominación exacta y aliases aprobados;
- congelar todas las versiones del procedimiento;
- calcular en Python importes, órganos, CPV, lotes y periodos;
- no interpretar adjudicaciones ganadas como participación total.

### R7 — Documentos y participantes

- descargar solo desde hosts y referencias permitidos;
- conservar checksum, versión y procedencia;
- antivirus y cuarentena según la política documental;
- parsing/OCR y chunking por unidad jurídica: acta, lote, apartado, fila o página;
- extracción estructurada de participantes con localizador exacto;
- revisión de casos ambiguos.

### R8 — Claims y contradicciones

Cada hecho material se convierte en un claim atómico:

```text
sujeto + predicado + objeto + periodo + alcance + evidence_ids
```

Estados: `candidate`, `verified`, `disputed`, `rejected`, `superseded`.

Las contradicciones son registros, no notas dentro de un prompt. Una fecha distinta puede significar
evolución y no conflicto; un cese posterior no contradice un nombramiento anterior.

### R9 — Segunda pasada y huecos

Ollama recibe únicamente:

- pregunta;
- claims verificados;
- candidatos no resueltos;
- contradicciones;
- cobertura y presupuestos restantes;
- catálogo cerrado de consultas posibles.

Puede proponer la siguiente consulta. El orquestador valida la propuesta y ejecuta un conector
allowlisted; el modelo no navega libremente ni decide nuevas fuentes.

### R10 — Métricas y caminos

Python calcula:

- caminos desde la semilla;
- distancia, vigencia y contemporaneidad;
- grados y supernodos;
- concentración por órganos, CPV y periodo;
- importes y denominadores;
- cobertura por fuente, entidad y procedimiento;
- cambios desde una revisión previa.

Ollama interpreta esos cálculos; no los rehace.

### R11 — Redacción, crítica y publicación

- redactar por secciones desde paquetes de claims congelados;
- revisar cada sección con exactamente el mismo paquete;
- comprobar citas, localizadores y hashes de forma determinista;
- ensamblar tablas, anexos y numeración en Python;
- bloquear hechos sin evidencia o contradicciones materiales no revisadas;
- publicar solo después de revisión humana.

## 8. Arquitectura de ejecución con Ollama

### 8.1 No una llamada de horas

Producción tiene límites Celery de 690 segundos soft y 720 segundos hard; las leases IA se acotan a
600 segundos. Una investigación de seis horas debe ser un DAG de muchos jobs de minutos, no una
tarea o contexto gigante.

```text
InvestigationRun
  → resolver semilla
  → capturar fuentes
  → normalizar
  → resolver candidatos
  → expandir oleada N
      ├─ consultar contratación por lotes
      └─ descargar/parsear documentos
  → extraer participaciones
  → validar claims
  → decidir si existe otra oleada
  → sintetizar por temas
  → redactar secciones
  → revisar secciones
  → ensamblar
  → revisión humana
```

Un dispatcher consulta PostgreSQL y solo encola pasos cuyas dependencias estén completadas. Redis
no es historial ni fuente de verdad. No se usa un chord de Celery como estado autoritativo.

Distribución en colas existentes:

- `signals`: adquisición de entidad y contratación;
- `documents`: descarga, parsing, OCR y chunks;
- `ai`: extracción, contradicciones, síntesis, redacción y crítica;
- `notifications`: gates humanos y finalización;
- `maintenance`: reconciliación de pasos huérfanos.

No se añade una cola nueva hasta medir contención y registrar la decisión arquitectónica.

### 8.2 Ollama detrás de Signal

Oracle no debe llamar Ollama directamente ni hardcodear modelos. Debe solicitar `task_key` a Signal
Avanza, que gobierna proveedor, modelo, digest, límites y fallback.

Task keys propuestas:

- `investigation_identity_resolution`;
- `investigation_relationship_extraction`;
- `investigation_procurement_participation_extraction`;
- `investigation_contradiction_analysis`;
- `investigation_report_section`;
- `investigation_report_evidence_review`;
- `investigation_opinion`.

Si se exige procesamiento local, la política del consumer en Signal fija Ollama y desactiva cloud
para estas tasks. `AIAuditLog` conserva proveedor/modelo efectivos, versión y hash de política.

Antes de elegir modelos se ejecuta un benchmark sobre el hardware real y un corpus etiquetado.
Oracle no promete una familia concreta desde código. La configuración inicial debe priorizar:

- contexto acotado por chunk o sección;
- una petición LLM concurrente en hardware compartido;
- salida estructurada y temperatura baja para extracción;
- digest de modelo registrado;
- métricas de tokens, duración y throughput;
- backpressure y kill switch.

Ollama admite JSON Schema en `format` y la validación con Pydantic, según su
[documentación de structured outputs](https://docs.ollama.com/capabilities/structured-outputs).
También expone métricas de generación y controles de cola/concurrencia documentados en su
[FAQ](https://docs.ollama.com/faq).

### 8.3 Reparto determinista/IA

| Código determinista | Ollama |
|---|---|
| conectores, paginación, rate limit y reintentos | extraer estructura de texto no normalizado |
| identificadores, hashes y deduplicación | proponer candidatos para homónimos |
| vigencia, BFS, ciclos y poda | comparar contradicciones semánticas |
| importes, porcentajes, denominadores y centralidad | explicar materialidad de caminos verificados |
| estados declarados de contratación | redactar secciones y valoración |
| allowlist de fuentes y validación de citas | criticar saltos lógicos con el mismo corpus |
| ensamblado de tablas, anexos e índice | proponer consultas desde un catálogo cerrado |

Ollama nunca:

- inventa una arista;
- decide que dos personas son la misma;
- deduce participación por asociación;
- transforma administrador común en control;
- completa un importe ausente;
- convierte falta de resultados en un hecho negativo;
- publica directamente.

### 8.4 Contexto y RAG

Identidad, fechas, expedientes y relaciones se consultan con SQL y claves exactas, no embeddings.
RAG se reserva para documentos largos:

1. filtro obligatorio por tenant, run, entidad, fuente, fecha y tipo;
2. búsqueda exacta por NIF, razón social, expediente, lote y CPV;
3. búsqueda lexical;
4. búsqueda vectorial opcional;
5. diversidad por documento, fecha y tipo;
6. congelación de los fragmentos elegidos.

La API de embeddings de Ollama trunca por defecto si la entrada supera el contexto; la
[documentación](https://docs.ollama.com/api/embed) permite `truncate=false`. La investigación debe
prefragmentar y fallar de forma visible, nunca perder el final de un acta en silencio.

### 8.5 Writer y reviewer simétricos

El redactor recibe un `source_pack` congelado con:

- manifest del run;
- claims verificados y contraevidencia;
- métricas calculadas;
- contradicciones abiertas;
- cobertura;
- `allowed_claim_ids` y `allowed_evidence_ids`.

Cada sección guarda `writer_source_pack_hash`. El revisor recibe la sección candidata y el mismo
paquete completo, y debe devolver ese hash. Las incidencias se anclan a `paragraph_id`, `claim_id` y
`evidence_id`.

Esta simetría evita repetir el fallo ya documentado en Oracle donde un reviewer juzgaba un informe
con menos contexto que el escritor. Un comentario global sin anclaje no elimina automáticamente un
hecho.

## 9. Modelo de datos propuesto

Todo es tenant-scoped y depende de `StrategicDossier`.

### `InvestigationRun`

- alcance, semilla, fecha de corte y periodo;
- versión del protocolo y política de fuentes;
- límites de profundidad, entidades, documentos, bytes, tiempo y tokens;
- estado, etapa, progreso, motivo de parada y corpus hash;
- solicitante, cancelación y timestamps.

### `InvestigationStep` y dependencias

- etapa, sujeto, estado, intentos y lease;
- input/result refs pequeños;
- hashes de fuente, prompt, schema y política;
- dependencia entre pasos;
- vínculo a `BackgroundJob`.

### `ResearchEntity` y `ResearchAlias`

- tipo demostrado o `unknown`;
- nombre exacto/normalizado, aliases e identificadores;
- profundidad, camino de descubrimiento y prioridad;
- estado de resolución y confianza;
- motivo de gate, rechazo o poda.

### `ResearchRelation`

- origen, destino, tipo, etiqueta original y dirección;
- vigencia y contemporaneidad;
- estado, confianza y revisión;
- evidencias y contraevidencias.

### `ProcurementParticipation`

- procedimiento, lote y sociedad;
- rol y resultado;
- nombre/identificador exactos recibidos;
- estado estructurado/documental;
- evidencia, confianza y revisión.

### `ResearchSourceSnapshot`

- proveedor, clase, identificador externo y URL;
- publicación, captura y validez;
- checksum, payload/blob, parser y versión;
- licencia/política aplicada;
- cobertura, cursor, truncamiento y errores.

### `ResearchClaim` y `ResearchContradiction`

- `fact`, `inference`, `opinion`, `recommendation` o `limitation`;
- sujeto, predicado, objeto y tiempo;
- evidencia y contraevidencia;
- confianza, estado y revisión;
- claims incompatibles y resolución.

Los documentos exploratorios no deben forzarse al esquema canónico `Document` si todavía no hay una
decisión de incorporación. Se mantienen como snapshots del run; al aceptarlos se materializan en
`Document`/`Evidence` dentro del expediente.

PostgreSQL es suficiente para esta primera versión. No se introduce Neo4j: los grafos son acotados,
las relaciones ya viven en SQL y Cytoscape cubre la visualización. Una base de grafos solo se
reconsidera después de medir volumen y latencia.

## 10. API y experiencia Vector

API Flask orientativa:

```text
POST /api/v1/dossiers/{dossier_id}/investigations
GET  /api/v1/dossiers/{dossier_id}/investigations
GET  /api/v1/investigations/{run_id}
POST /api/v1/investigations/{run_id}/pause
POST /api/v1/investigations/{run_id}/resume
POST /api/v1/investigations/{run_id}/cancel
GET  /api/v1/investigations/{run_id}/entities
GET  /api/v1/investigations/{run_id}/relations
GET  /api/v1/investigations/{run_id}/participations
GET  /api/v1/investigations/{run_id}/claims
GET  /api/v1/investigations/{run_id}/sources
POST /api/v1/investigations/{run_id}/reviews
POST /api/v1/investigations/{run_id}/promotions
POST /api/v1/investigations/{run_id}/reports
```

Cada mutación usa permiso, CSRF, tenant derivado de sesión, `Idempotency-Key`, auditoría y control de
versión. Ningún endpoint confía en un tenant enviado por el navegador.

La investigación vive dentro del expediente, con estas vistas:

1. **Alcance:** pregunta, semilla, fuentes, periodo y presupuestos.
2. **Ejecución:** rondas, pasos, ETA, pausa/reanudación y bloqueos.
3. **Identidad:** candidatos, aliases, conflictos y decisiones humanas.
4. **Grafo:** caminos con alternativa tabular accesible, vigencia y cobertura.
5. **Contratación:** sociedad, procedimiento, lote, rol, resultado y evidencia.
6. **Hallazgos:** claims, contradicciones, huecos y revisiones.
7. **Fuentes:** ledger, fallos, recortes, hashes y licencias.
8. **Informe:** borrador, crítica, revisión, publicación y revisiones.

La UI no muestra un porcentaje genérico de «vinculación». Presenta caminos y tipos de vínculo. Los
colores nunca sustituyen estado textual, evidencia o vigencia.

## 11. Contrato del informe final

El informe amplio debe contener:

1. resumen ejecutivo;
2. pregunta, alcance, fecha de corte y corpus;
3. identidad de la semilla;
4. vínculos directos;
5. caminos indirectos y vigencia;
6. actividad de contratación por sociedad;
7. participaciones no adjudicadas confirmadas por documento;
8. patrones y métricas calculadas;
9. contradicciones y explicaciones alternativas;
10. valoración analítica/opinión;
11. oportunidades, riesgos y comprobaciones recomendadas;
12. cobertura, límites y ramas podadas;
13. anexos de entidades, caminos, procedimientos y fuentes.

La opinión no es una conclusión libre. Cada valoración incluye:

- premisas mediante `claim_ids`;
- evidencias y contraevidencias;
- nivel de confianza;
- explicaciones alternativas;
- qué dato podría cambiar la valoración;
- recomendación de verificación humana.

Reglas editoriales:

- un hecho necesita evidencia y localizador válido;
- una inferencia se etiqueta y explica;
- una opinión se apoya en claims verificados;
- no se publican UUID dentro de la prosa;
- no se usa lenguaje acusatorio por mera asociación;
- no se presenta un dato histórico como vigente;
- no se ocultan fuentes fallidas, recortes ni identidades dudosas.

## 12. Seguridad, privacidad y legalidad

Ollama local reduce transferencias a terceros, pero no resuelve por sí solo protección de datos,
licencias, exactitud ni riesgo reputacional.

Antes de producción:

1. definir responsable, finalidad y base jurídica por tipo de investigación;
2. documentar interés legítimo y ponderación si se usa esa base;
3. mantener registro de actividad, información del artículo 14 y canal de derechos;
4. evaluar con DPO si procede EIPD; la AEPD señala perfilado, combinación de bases y uso innovador
   como factores relevantes en su [lista y guía de EIPD](https://www.aepd.es/documento/listas-dpia-es-35-4.pdf);
5. revisar condiciones, licencia, atribución, robots y límites de cada fuente;
6. prohibir elusión de CAPTCHA, autenticación o controles del Registro; la publicidad registral
   está sujeta a tratamiento profesional y límites frente a solicitudes masivas en el
   [artículo 12 del Reglamento del Registro Mercantil](https://boe.es/buscar/act.php?id=BOE-A-1996-17533);
7. limitar personas físicas a identidad profesional, cargo, sociedad, vigencia y evidencia;
8. no almacenar domicilio particular, DNI visible, vida privada, categorías especiales ni datos
   penales por defecto;
9. cifrar y restringir un identificador personal si fuese imprescindible para desambiguar;
10. fijar retención, rectificación/réplica y borrado;
11. exigir revisión humana antes de una conclusión adversa o exportación.

El RGPD exige licitud, finalidad, minimización, exactitud, retención limitada y seguridad, además de
una base de tratamiento, como recogen sus [artículos 5 y 6](https://eur-lex.europa.eu/eli/reg/2016/679/oj?locale=es).
Que un nombre aparezca en una publicación oficial no convierte cualquier perfilado posterior en
automáticamente lícito.

Controles técnicos:

- aislamiento tenant y tests negativos IDOR;
- permiso específico de investigador y acceso con motivo;
- auditoría de lectura, resolución, promoción y publicación;
- fuentes/documentos como datos no confiables, nunca instrucciones;
- SSRF allowlist, tamaños máximos, antivirus y redirecciones cerradas;
- Ollama/Signal en red privada; puerto de inferencia no expuesto;
- secretos fuera de prompts, args Celery y logs;
- kill switch y presupuestos por tenant/run;
- exportaciones marcadas con fecha de corte y clasificación.

## 13. Presupuestos y condiciones de parada

Perfiles iniciales para medir, no promesas de exhaustividad:

| Perfil | Tiempo máximo | Profundidad | Sociedades | Documentos | Llamadas IA |
|---|---:|---:|---:|---:|---:|
| Piloto | 90 min | 1 | 30 | 300 | 40 |
| Estándar | 6 h | 2 | 150 | 2.000 | 250 |
| Profundo | aprobación nueva | configurable | configurable | configurable | configurable |

Paradas duras:

- identidad raíz no resuelta;
- deadline o presupuesto agotado;
- cancelación o kill switch;
- tres fallos consecutivos del mismo paso;
- tres salidas estructuradas inválidas;
- fuente bloqueada más allá del deadline;
- espacio o memoria por debajo del umbral operativo;
- frontera vacía.

Podas blandas registradas:

- supernodo: persona con más de 50 sociedades o firma con más de 100 vínculos;
- rol profesional no material;
- identidad por debajo del umbral de autopromoción;
- relación fuera de la ventana temporal;
- dos oleadas con rendimiento marginal mínimo;
- ETA superior al tiempo restante;
- duplicado por contenido;
- fuente de baja autoridad cuando ya existe fuente oficial equivalente.

Una contradicción material abierta o una sección con hechos sin cobertura completa bloquea
publicación, no la investigación completa.

## 14. Reanudación e idempotencia

Clave conceptual de un paso:

```text
research:{run_id}:{stage}:{subject_key}:{source_revision}:
{prompt_version}:{schema_version}:{task_policy_hash}
```

Reglas:

- payloads Celery basados en IDs, nunca objetos ORM ni corpus;
- resultado durable antes de publicar dependencias;
- lease y fencing por paso;
- comprobación de cancelación entre lotes;
- retry técnico sobre el mismo snapshot;
- pausa/reanudación conserva fecha de corte y corpus;
- refrescar fuentes crea una revisión nueva;
- un informe de cambio compara dos runs congelados;
- blobs y respuestas direccionados por contenido;
- ninguna reejecución duplica claims, fuentes o promociones.

## 15. Plan de entrega

### Fase 0 — Spike de verdad y cobertura · 1–2 semanas

Sin nueva UI productiva:

- definir protocolo, fuentes, taxonomía y gate jurídico;
- medir resolución de identidad BORME/Registro;
- medir en una muestra PLACSP cuántos expedientes ofrecen identidad completa de participantes en
  datos estructurados o documentos;
- medir descarga, OCR, tablas y localizadores;
- benchmark de Ollama por task y tamaño de contexto;
- preparar corpus oro con homónimos, persona jurídica administradora, cese, UTE, multilote,
  adjudicatario, perdedor, excluido, fuente caída y prompt injection.

**Gate:** decisión informada sobre si el producto se vende como adjudicaciones, participación
documentada o cobertura exhaustiva. La tercera opción no se acepta sin evidencia.

### Fase 1 — MVP determinista · 2–3 semanas

- `InvestigationRun`, pasos, candidatos, relaciones y fuentes;
- semilla y grafo de profundidad 1–2;
- contratación ganada de todas las sociedades verificadas;
- caminos, cobertura, pause/resume/cancel;
- informe factual sin pretender cubrir perdedores.

**Gate:** reanudación tras matar worker, identidad raíz confirmada, cero contaminación del grafo
canónico y 100 % de hechos citados.

### Fase 2 — Participación documental · 3–5 semanas

- contrato Signal de participantes por lote;
- ingesta incremental de actas, valoraciones y resoluciones;
- OCR/chunking jurídico;
- extracción estructurada con Ollama;
- revisión de identidad y rol;
- estados `bidder/lost/excluded/withdrawn/unknown`.

**Gate:** precisión de rol/resultado al menos 98 % en corpus etiquetado y cobertura siempre
declarada. Sin alcanzar el gate, solo se publica como mención documental.

### Fase 3 — Claims, contradicciones e informe · 2–3 semanas

- claims atómicos y contraevidencias;
- segunda pasada de huecos;
- agregados deterministas;
- redacción por secciones;
- reviewer simétrico;
- opinión separada y revisión humana;
- snapshot de informe y anexos.

**Gate:** cero citas inventadas, cero hechos sin evidencia, ninguna afirmación de ausencia fuera de
su cobertura y 100 % de contradicciones materiales visibles.

### Fase 4 — Operación continua · 1–2 semanas

- watchlists/monitores para entidades aprobadas;
- revisión incremental BORME/PLACSP;
- informe de diferencias;
- métricas, alertas, retención y runbooks;
- pruebas de carga, recuperación y seguridad.

Estimación total: **9–15 semanas de ingeniería** según el contrato que deba construirse en Signal y
el acceso a fuentes registrales. Con Signal, backend, frontend y QA en paralelo puede reducirse el
calendario; las licencias y la cobertura documental pueden ampliarlo.

## 16. Métricas y gates de release

- 100 % de identidad raíz confirmada;
- precisión de merges automáticos ≥ 99 % sobre corpus oro; el resto, revisión;
- 100 % de citas existentes, permitidas y con localizador válido;
- 0 claims factuales sin evidencia;
- precisión ≥ 98 % en rol/resultado de participación documentada;
- toda cifra con denominador y cobertura;
- toda ausencia condicionada al corpus;
- cancelación y reanudación sin duplicados;
- recuperación tras caída del worker;
- 0 accesos cross-tenant;
- schema pass inicial y tras una reparación;
- medición de tokens, throughput, memoria, latencia y reintentos por task/model digest;
- revisión humana y tasa de correcciones;
- corpus de prompt injection y documentos maliciosos;
- despacho HTTP real, OpenAPI/cliente TS, integración PostgreSQL/Redis/Celery y smoke visual.

Cada comportamiento nuevo debe tener una mutación demostrada: romper resolución de identidad,
allowlist de citas, aislamiento, vigencia o idempotencia debe hacer caer el test correspondiente.

## 17. Riesgos principales

| Riesgo | Mitigación |
|---|---|
| explosión combinatoria | profundidad, presupuestos, supernodos, prioridad y rendimiento marginal |
| homónimos | identificadores, candidatos separados y revisión humana |
| falsa exhaustividad de licitadores | estados de cobertura, documentos oficiales y `unknown` |
| falacia de asociación | relaciones tipadas, vigencia, caminos y lenguaje neutral |
| alucinación del modelo | schemas, claims, allowlists, localizadores y ensamblado determinista |
| reviewer con menos contexto | paquete simétrico y hash de corpus |
| fuente cambiante | snapshots, parser versionado y contract tests |
| horas de ejecución | DAG reanudable, jobs cortos, backpressure y ETA |
| privacidad/reputación | finalidad, DPO/EIPD, minimización, derechos y publicación humana |
| licencia o coste registral | registro de fuentes, conector autorizado y presupuesto por run |
| datos antiguos | fecha de corte, vigencia y revisiones incrementales |

## 18. Decisiones que debe tomar producto

Recomendación por defecto:

1. **Sí:** tratar Investigación como plantilla/workflow de `StrategicDossier`.
2. **Sí:** profundidad automática máxima 2; una tercera capa requiere acción humana.
3. **Sí:** usar solo roles profesionales y societarios de personas físicas.
4. **Sí:** denominar «participación confirmada» únicamente la demostrada por expediente/lote.
5. **Sí:** configurar las task keys de investigación como Ollama local, cloud desactivado.
6. **Sí:** ejecutar primero la Fase 0 y decidir el producto después de medir.
7. **No:** afirmar control, grupo o coordinación por administrador común.
8. **No:** prometer todos los licitadores hasta tener un índice documental medido.
9. **Pendiente:** acceso autorizado y presupuesto para Registro Mercantil.
10. **Pendiente:** EIPD/base jurídica, información y retención para grafos de personas.

## 19. Siguiente prompt recomendado

`ORACLE-EXP-INV-01 — Spike de cobertura e identidad`

Entregables:

- protocolo v1 y matriz de fuentes/licencias;
- muestra etiquetada de entidades, relaciones y expedientes;
- medición de cobertura de participantes PLACSP;
- benchmark real de Ollama con schemas;
- diseño OpenAPI/ERD sin aplicar migración;
- decisión go/no-go y alcance honesto del MVP;
- estimación revisada basada en mediciones.

No debe crear todavía un crawler masivo, afirmar nada sobre una empresa real ni materializar
personas/relaciones en el dominio canónico.
