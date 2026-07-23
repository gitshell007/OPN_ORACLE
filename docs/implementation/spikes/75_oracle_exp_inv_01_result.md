# ORACLE-EXP-INV-01 · primer bloque medido

**Fecha:** 2026-07-23

**Veredicto:** `GO` condicionado para continuar la Fase 0 y diseñar un MVP de **adjudicaciones
trazables**; `NO-GO` actual para participantes nominales, auto-merge de personas, expansión por tipo
de contraparte y reviewer como bloqueo automático.

Este resultado no aprueba todavía la feature ni completa las muestras de 96 unidades PLACSP y 72
aserciones BORME. Sí sustituye varias hipótesis por mediciones reproducibles.

## 1. Qué se ejecutó

- arnés instrumental fuera de Flask/Celery y sin migraciones;
- fixture oro inequívocamente sintético;
- auditoría de los allowlists/contratos actuales de Oracle;
- lectura de una página Atom oficial viva de PLACSP, sin persistir el XML bruto;
- 17 casos estructurados con Ollama local:
  - 2 de triaje de identidad;
  - 4 de extracción de participación;
  - 9 de reviewer y 2 repeticiones de estabilidad;
- primera pasada con el comportamiento por defecto observado y segunda con `think=false`;
- repetición desde checkpoints por caso;
- diseño ERD y OpenAPI separado del contrato productivo.

No se consultó una empresa real, no se usaron datos de negocio, no se llamó a Registro Mercantil de
pago y no se escribió en `Actor`, `Relationship`, `Evidence`, `Document`, `Report` ni contratación
fijada.

## 2. PLACSP: el recuento existe; las identidades no están en el feed

Fuente medida:

- sindicación oficial 643;
- feed actualizado `2026-07-22T20:18:21.725+02:00`;
- SHA-256
  `33a8024a2a539c79159d8699fe93dca5f7a7fe53e198e8a49b2a1267d7ce50f2`;
- 5.631.555 bytes;
- una única página viva y no aleatoria: sirve como diagnóstico contractual, no como estimación
  histórica ni nacional.

| Métrica | Resultado |
|---|---:|
| Entradas Atom | 179 |
| Entradas con `TenderResult` | 68 |
| Resultados/lotes observados | 124 |
| Resultados con `ReceivedTenderQuantity` | 124/124 · 100 % · Wilson 95 % [97,0 %, 100 %] |
| Ámbitos únicos expediente+lote+revisión | 118 |
| Filas repetidas del recuento | 6 |
| Suma ingenua de recuentos | 264 |
| Suma deduplicada | 250 |
| Doble conteo evitado | 14 |
| Resultados con `WinningParty` | 112/124 · 90,32 % |
| Resultados con algún `WinningParty` identificado | 112/112 · 100 % |
| Entradas con referencias documentales | 179/179 |
| Nodos estructurados de participantes no ganadores | 0 |

La medición confirma tres reglas:

1. `ReceivedTenderQuantity` debe conservarse por **expediente+lote+revisión** y no sumarse por fila
   de adjudicatario.
2. El recuento no aporta identidades. Las referencias documentales permiten una fase posterior,
   pero su mera existencia no demuestra que contengan una lista nominal completa o descargable.
3. La sindicación 643 no representa por sí sola la familia agregada autonómica. «España completa»
   sigue siendo una promesa no defendible.

La [especificación oficial de sindicación](https://contrataciondelsectorpublico.gob.es/datosabiertos/especificacion-sindicacion.pdf)
y el [portal de datos abiertos PLACSP](https://contrataciondelestado.es/wps/portal/DatosAbiertos)
son la autoridad de fuente. El runtime futuro seguirá entrando por Signal conforme a D-028; la
lectura directa solo pertenece a este spike.

## 3. Hueco Signal/Oracle observado

No hay credenciales ni consumer Signal aislado en el workspace, por lo que no se midió el servicio
vivo. El inventario de código sí demuestra:

- `AWARD_SNAPSHOT_KEYS` no conserva `ReceivedTenderQuantity`, revisión ni identificador del ganador;
- no existe endpoint/contrato de participantes nominales por expediente y lote;
- la consulta BORME de empresa deja `counterpart_kind` sin verificar cuando Signal no lo aporta;
- el grafo admite profundidad máxima 2 y puede declarar truncación;
- no existen task keys, handlers, `TASK_QUEUES` ni `TASK_ROUTES` de investigación;
- `BackgroundJob` ya aporta la autoridad de ejecución que deberá reutilizar el futuro DAG.

En el fixture contractual, sumar el recuento repetido daba 10 y el agregado correcto 6. El test
protege esa semántica. El MVP no debe añadir aún el campo a snapshots: antes hay que contrastar la
muestra oficial de 96 unidades con un consumer Signal read-only y acordar nombre, ámbito,
versionado y cobertura.

## 4. Ollama: schema resuelto, calidad todavía insuficiente

Host medido: Mac mini M2 Pro, 32 GB de memoria unificada. Durante la primera pasada coexistió una
suite `pytest` ajena con carga alta; la segunda se ejecutó sin esa contención. Modelo:

- `qwen3.5:9b`;
- Ollama `0.32.1`;
- digest completo
  `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`;
- 9,7B, `Q4_K_M`, GGUF;
- 6,59 GB en disco y 5,90 GB residentes declarados por Ollama;
- contexto del benchmark: 8.192;
- `qwen3.6:27b` no está instalado y no se fingió su resultado.

### 4.1 Primera pasada: pensamiento no desactivado

El payload equivalente al adapter local actual no fijaba `think=false`.

| Métrica | Resultado |
|---|---:|
| Casos lógicos | 17 |
| Llamadas físicas con reparación | 34 |
| Schema inicial/final | 0/17 · 0/17 |
| Reparaciones | 17 |
| Tokens de salida | 29.000, exactamente los topes acumulados |
| p50 / p95 / máximo | 40,0 s / 52,8 s / 55,7 s |
| Suma de wall time | 1.346,4 s · 22 min 26 s |

Todas las salidas agotaron `num_predict` y quedaron inválidas. La segunda pasada aisló la causa
operativa: al declarar `think=false`, el mismo modelo y schemas dejaron de truncar. Esto revela un
gap en `OllamaLLMProvider`, que hoy tampoco envía ese control. No se modifica el provider desde el
spike; debe tratarse en un prompt independiente con regresión sobre modelos que no usen thinking.

### 4.2 Segunda pasada: `think=false`

| Métrica | Resultado |
|---|---:|
| Schema inicial/final | 17/17 · 17/17 |
| Reparaciones / topes de salida | 0 / 0 |
| Tokens entrada / salida | 5.386 / 5.259 |
| Throughput mediano / mínimo | 27,14 / 26,34 tokens/s |
| p50 / p95 / máximo | 13,5 s / 21,9 s / 21,9 s |
| Suma de wall time | 226,6 s · 3 min 47 s |
| Margen frente a lease IA 600 s | amplio por llamada |

El modelo es operacionalmente viable para jobs cortos, pero schema pass no equivale a exactitud.

#### Identidad

- `uncertain`: 2/2 correcto;
- `pair_id`: 2/2 coincide con el contexto;
- cero acciones de merge posibles por schema;
- acción recomendada exacta: 1/2;
- el caso con conflictos fuertes siguió pidiendo revisión en vez de recomendar `do_not_merge`.

Conclusión: puede producir un triaje estructurado y una explicación auxiliar; este microcorpus no
midió calidad de ranking. No puede promover ni abrir frontera.

#### Participación documental

- 4 casos oro;
- 4 extracciones producidas;
- `document_id`: 4/4 coincide con el contexto;
- localizadores literales válidos: 4/4;
- matches exactos de entidad+lote+rol+identificador+UTE: 0/4;
- precisión y recall exactos: 0 %.

Fallos materiales:

- interpretó la denominación como identificador;
- omitió lotes explícitos;
- rebajó admitido, excluido y perdido a `mentioned_unknown`;
- añadió el adjudicatario como segunda extracción en el caso UTE;
- omitió una mera mención que el ledger debía conservar como `mentioned_unknown`.

Conclusión: `NO-GO` para crear `ProcurementParticipation`. Puede servir para proponer fragmentos a
revisión después de simplificar schema/prompt, pero no para asignar rol.

#### Reviewer

- 11/11 schemas y hashes simétricos válidos;
- veredicto exacto: 10/11 · 90,91 %;
- falsos `pass` adversariales: 0;
- precisión de categoría: 36,36 %;
- recall de categoría: 50 %;
- conjunto exacto de categorías: 5/11;
- estabilidad: los dos casos repetidos devolvieron el mismo veredicto y categoría;
- falso rechazo: marcó como fallo una inferencia prudente que explícitamente negaba identidad.

También confundió `unsupported`, `misattributed` y `broken_citation` con otras categorías y añadió
incidencias espurias. `reject_output` queda en `NO-GO`: un modelo que bloquea texto seguro y no
ancla bien la causa no debe decidir publicación. Los validadores deterministas de citas, hashes,
IDs y clasificación se ejecutan antes; el reviewer local queda como señal auxiliar hasta ampliar y
superar el corpus.

## 5. Reanudación e idempotencia

El arnés usa dos niveles:

- macropasos `contracts → placsp → ollama → decision`, con fingerprint de protocolo, input,
  implementación, límites, endpoint local, digest de modelo y dependencias;
- checkpoint por caso IA con hash de fixture, expected, prompt, schema, modelo/digest y contexto.

Al reutilizar, ambos niveles recalculan el hash del resultado persistido; una alteración o
truncación invalida el checkpoint. El score se recalcula desde la salida estructurada cacheada, por
lo que cambiar un evaluador no obliga a repetir inferencia ni conserva métricas obsoletas.

La repetición final:

- reutilizó 17/17 casos;
- ejecutó 0 inferencias;
- consumió 0/40 llamadas;
- resolvió el macropaso Ollama desde checkpoints en menos de 100 ms y el run completo en menos de
  un segundo.

Los checkpoints y outputs permanecen bajo `docs/implementation/spikes/.work/75`, ignorado por Git.
El resultado versionado no incluye XML PLACSP, nombres reales ni secretos.

## 6. Decisión por capacidad

| Capacidad | Decisión | Motivo |
|---|---|---|
| Adjudicaciones de sociedades verificadas | `GO condicionado` | encaja con el contrato actual; falta concordancia Signal en 96 unidades y cobertura agregada |
| `ReceivedTenderQuantity` | `NO-GO de contrato` | existe en fuente, Oracle lo descarta y falta semántica/versionado upstream |
| No adjudicatarios nominales | `NO-GO` | no hay contrato Signal ni precisión de extractor |
| BORME como cola de candidatos | `GO condicionado` | hechos registrales/localizadores sí; identidad humana |
| Expansión por `counterpart_kind` | `NO-GO` | tipo upstream incompleto |
| Auto-merge de personas | `NO-GO permanente por metodología` | un nombre/LLM nunca es prueba |
| Reviewer con `reject_output` | `NO-GO` | recall de categoría 50 % y falso rechazo |
| «Todos los participantes» | `NO-GO` | feed alojado no basta, agregada no medida y listas completas no demostradas |
| DAG de jobs cortos | `GO de diseño` | p95 por llamada 21,9 s y reanudación por fingerprint demostrada |

## 7. ERD y OpenAPI

- [ERD propuesto](75_investigation_erd_draft.md): `InvestigationStep` describe el DAG, pero
  `BackgroundJob` conserva lease/fencing/retry; los candidatos permanecen aislados del grafo
  canónico. Los identificadores son tipados y evidenciados, y el recuento vive una sola vez en la
  observación expediente+lote+revisión, no en cada participante.
- [OpenAPI propuesto](75_investigation_openapi_draft.yaml): cookie de sesión, CSRF,
  `Idempotency-Key`, `If-Match`, tenant derivado y páginas por cursor. Es `design-only`; no se
  incorporó a `docs/api/openapi.json` ni al cliente TypeScript.

No se aplicó migración y el recuento de filas afectadas es cero.

## 8. Siguiente bloque de Fase 0

1. Etiquetar las 96 unidades PLACSP y 72 aserciones BORME descritas en el
   [protocolo v1](75_investigation_protocol_v1.md).
2. Crear un consumer Signal efímero, read-only, y comparar por `folder_id+lot_id+revision`.
3. Proponer en Signal un contrato aditivo de:
   - `ReceivedTenderQuantity` con ámbito y `coverage_status`;
   - ganador con identificador;
   - `counterpart_kind` con procedencia;
   - participantes por lote con documento y localizador.
4. Simplificar el extractor en dos etapas: localizar candidato/fragmento y clasificar rol de forma
   separada; evaluar cada una antes de combinarlas.
5. Mantener el reviewer fuera de `reject_output`; ampliar casos y exigir 100 % de veredicto, hash y
   categoría en el microcorpus antes de pasar al corpus estadístico.
6. Abrir un cambio independiente del adapter Ollama para `think=false`, con compatibilidad por
   modelo y test observable.
7. Ejecutar un micro-DAG real sobre `BackgroundJob` solo cuando los contratos de datos hayan
   superado el gate; no registrar tareas productivas durante este bloque.

La estimación de 2,5–5 horas para una red mediana sigue sin validarse: este bloque solo mide llamadas
individuales y una página fuente. Se mantendrá como hipótesis hasta cronometrar las seis
macropasadas sobre la muestra estratificada.

## 9. Reproducción

```bash
cd apps/api
~/.local/bin/uv run python ../../scripts/spikes/oracle_exp_inv_01.py \
  --official-placsp \
  --ollama \
  --work-dir ../../docs/implementation/spikes/.work/75/think-disabled \
  --ollama-timeout 180 \
  --max-calls 40 \
  --reviewer-repeat 1
```

La segunda ejecución con idénticos hashes debe informar `case_cache.reused=17`,
`case_cache.executed=0` y `call_budget.used=0`.
