# Prompt 75 · ORACLE-EXP-INV-01 — Spike de cobertura e identidad

## Objetivo

Convertir la propuesta `ORACLE-EXP-INVESTIGACIONES` en una primera medición reproducible antes de
crear el agregado productivo. El resultado debe distinguir capacidad de la fuente, fidelidad del
contrato Signal/Oracle y capacidad del modelo local.

## Alcance

1. Crear un arnés instrumental fuera del runtime, reanudable e idempotente por hash.
2. Auditar en lectura el feed oficial PLACSP y los contratos actuales de entidad/contratación.
3. Crear un corpus oro sintético para:
   - gate determinista de identidad;
   - extracción documental de participantes;
   - reviewer con errores sembrados.
4. Medir Ollama local con JSON Schema, modelo/digest, tokens, latencia, throughput, carga,
   reparaciones y exactitud por tarea.
5. Definir muestras estratificadas posteriores de PLACSP y BORME, con denominadores y gates.
6. Proponer ERD y OpenAPI sin migraciones ni cambios en el contrato productivo.
7. Emitir go/no-go separado para adjudicaciones, recuento de ofertas, participantes nominales,
   identidad y reviewer.

## Límites vinculantes

- No investigar una empresa ni una persona real.
- No escribir `Actor`, `Relationship`, `Evidence`, `Document`, `Report` ni snapshots PLACSP.
- No crear crawler masivo, tasks `investigation.*`, task keys Signal, endpoints o migraciones.
- PLACSP directo solo se usa como fuente oficial de diagnóstico; Signal sigue siendo el productor
  de runtime conforme a D-028.
- Los payloads brutos y checkpoints quedan bajo `.work/75`, ignorado por Git; el resultado
  versionado solo contiene métricas agregadas y fixtures inequívocamente sintéticos.
- Un nombre nunca autoriza un merge. Ollama no dispone de una acción de merge en su schema.
- `ReceivedTenderQuantity` se deduplica por expediente, lote y revisión; no representa identidades.
- Un falso `pass` del reviewer en un caso adversarial bloquea `reject_output`.
- Ninguna ausencia se expresa fuera del corpus y fecha de corte medidos.

## Gates mínimos

- Identidad: cero auto-merge por nombre, heurística o LLM.
- Citas/localizadores: 100 % existentes y dentro de allowlist.
- Participación documental: precisión de rol/resultado objetivo ≥98 % en el corpus ampliado.
- Reviewer: cero falsos `pass` adversariales antes de usarlo como bloqueo.
- Jobs futuros: cada llamada debe dejar margen bajo lease IA de 600 s y hard limit de 720 s.
- Producto «todos los participantes»: no-go hasta demostrar listas completas por estrato y cubrir
  PLACSP alojada y agregada.

## Entregables

- protocolo v1 y matriz de fuentes;
- fixture sintético etiquetado;
- arnés y pruebas de reanudación, presupuesto, identidad y deduplicación;
- medición PLACSP oficial y benchmark Ollama;
- borrador ERD/OpenAPI;
- informe del spike con decisión go/no-go y siguiente muestra de 96 unidades PLACSP y 72 aserciones
  BORME.

## Definición de terminado de este primer bloque

El bloque termina cuando los artefactos son reproducibles, sus pruebas fallan al mutar los
invariantes críticos, las limitaciones Signal quedan explícitas y se ha ejecutado al menos una
medición real del feed oficial y del modelo disponible. No implica que la Fase 0 completa ni el
producto estén aprobados.
