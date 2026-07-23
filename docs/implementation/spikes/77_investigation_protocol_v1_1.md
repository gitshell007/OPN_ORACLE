# ORACLE-EXP-INV-02 · protocolo de medición v1.1

**Estado:** protocolo de spike; sustituye v1 solo para el muestreo posterior a INV-01

**Fecha de corte del diseño:** 2026-07-23

## 1. Cuatro poblaciones, no una cifra nacional

Los resultados se publican por separado para:

1. PLACSP alojada (`sindicacion_643`);
2. PLACSP agregada (`sindicacion_1044`);
3. artículos de la Sección Primera del BORME;
4. challenge sets dirigidos de casos raros.

No se suman las dos familias PLACSP como una tasa de España. Sin tamaños poblacionales y pesos de
inclusión, el resumen entre familias será solo una macro-media descriptiva. Un challenge set mide
capacidad ante casos conocidos; no estima prevalencia ni recall poblacional.

## 2. Marco PLACSP congelado

Cada adquisición registra URL oficial, bytes, SHA-256, fecha y hora UTC, nombre del miembro ZIP,
`feed/id`, `feed/updated` y enlaces de paginación. El algoritmo:

1. recorre todas las páginas incluidas en los paquetes fijados;
2. identifica la colección y usa `atom:entry/atom:id` como identidad primaria;
3. conserva la entrada con `atom:updated` más reciente al corte;
4. registra tombstones y no los convierte en expedientes activos;
5. agrupa resultados repetidos por lote antes de interpretar `ReceivedTenderQuantity`.

La unidad transversal es:

```text
source_family + collection_or_producer + atom_entry_id
+ folder_id + canonical_lot_id + selected_entry_updated
```

El core selecciona una única revisión por entrada y como máximo un lote por expediente. Los lotes
restantes se conservan para diagnóstico de clúster, pero no aumentan el denominador principal.
`folder_id` solo no es globalmente único.

La fecha ancla del periodo es `selected_entry_updated`. Los cortes cerrados de INV-02 son:

- reciente: paquete mensual de enero de 2025;
- histórico: paquete mensual de enero de 2022.

Ambos caen dentro de las ventanas originales de 0–18 y 19–60 meses respecto del corte de diseño.
El estudio no infiere la fecha inicial del expediente desde esa ancla. Los ZIP mensuales históricos
responden hoy, pero el catálogo solo garantiza expresamente el patrón mensual del año en curso; por
eso cada byte y hash se congela y el fallback futuro es el paquete anual oficial.

## 3. Challenge set PLACSP de 96

Se seleccionan 12 unidades por celda:

```text
familia {alojada, agregada}
× periodo {2025-01, 2022-01}
× estructura {simple, compleja}
```

`simple` significa un único lote/result scope, un único adjudicatario estructurado y sin flag UTE.
`complex` significa multilote, multiganador o UTE; estos tres flags se conservan además por
separado. La elegibilidad exige un `TenderResult`; ganador y recuento admiten `missing` como
resultado observable, nunca como exclusión silenciosa.

El sorteo usa una semilla versionada y un ranking SHA-256 sobre el identificador estable. Antes de
seleccionar se publica inventario por celda. Si una celda no alcanza 12, se declara `infeasible`;
no se rellena a mano desde otra celda.

Los mínimos por tipo de contrato y nivel de comprador son diagnósticos de cobertura, no cuotas que
puedan alterar el sorteo después de ver resultados. El mapping de tipo de contrato queda
versionado. `buyer_level=unknown` es válido; no se deduce por el nombre del organismo.

Se crean top-ups independientes, con manifest y denominadores propios, para al menos ocho casos de
cada flag disponible:

- UTE;
- multiganador;
- desierto/anulado;
- `ReceivedTenderQuantity >= 5`;
- documento PDF escaneado o tabular, solo después de comprobar bytes y formato.

## 4. Gold documental PLACSP

El ledger separa:

1. referencia documental publicada;
2. descarga HTTP válida y hash;
3. documento relevante para participación;
4. contenido nominal;
5. rol por lote;
6. lista completa o reconciliable.

Una URL no cuenta como documento descargado. `lost` exige oferta en el mismo lote y otro
adjudicatario. `source_missing`, `document_missing`, `parser_miss`, `identity_ambiguous` y
`contract_field_missing` siguen siendo categorías distintas.

El 25 % se etiqueta a doble ciego, estratificado. Todos los ambiguos, desacuerdos y posibles datos
personales pasan a adjudicación humana. Los resultados antes de adjudicación y el acuerdo se
conservan por separado.

## 5. BORME: marco independiente y challenge set

La API del BOE devuelve sumarios diarios y documentos provinciales. La unidad inicial es un
artículo, no una relación:

```text
publication_date + borme_document_id + article_number
+ registry_sheet_if_present + source_content_hash
```

El marco probabilístico selecciona artículos sin consultar el output del detector. Dos personas
etiquetan exhaustivamente todos los actos y contrapartes del artículo. Solo así se pueden contar
falsos negativos. Las aserciones resultantes añaden `assertion_ordinal` y `act_family`; los
intervalos deben reconocer el clúster por artículo.

En paralelo se crea un challenge set de 72 aserciones, seis recientes y seis históricas para cada
familia diagnóstica:

1. gobierno con contraparte demostrada como persona;
2. gobierno con contraparte demostrada como sociedad;
3. representante expresamente vinculado a administrador jurídico;
4. socio único demostrado como persona;
5. socio único demostrado como sociedad;
6. corrección, sociedad profesional u otro caso difícil, etiquetado además con subtipo.

El detector solo propone candidatos. El tipo final admite `person | company | unknown` y solo se
marca `person` o `company` cuando el acto o una fuente autorizada lo demuestra. Los sufijos y las
mayúsculas pueden servir para priorizar revisión, nunca para promover una relación.

Cada documento fija bytes, SHA-256, `fecha_actualizacion`, fecha de publicación, URL y localizador.
Una fe de erratas se enlaza a la publicación original cuando esta pueda localizarse; no la
sobrescribe.

## 6. Comparador Signal aislado

Signal se consulta después de congelar la muestra. El consumer:

- recibe el secreto solo mediante archivo absoluto, regular, no symlink, propietario del proceso,
  permisos `0600` o más restrictivos, una sola línea y tamaño acotado;
- no hereda claves productivas;
- usa HTTPS y un host exacto allowlisted;
- no sigue redirects;
- expone únicamente `GET /api/v1/consumers/me` y
  `GET /api/v1/registry/awards/{folder_id}`;
- agrupa las consultas por `folder_id`, sin una llamada por lote/revisión;
- invalida la corrida ante 401, 403, 429, 5xx, redirect o deriva de schema.

El preflight exige slug efímero esperado y consumer activo. Signal v1 no aplica scopes de lectura
a `/registry`; por ello GET-only es una protección del cliente, no una garantía server-side. Un
consumer realmente read-only requiere un cambio previo en Signal. La pausa/revocación posterior es
un gate administrativo externo y debe verificarse antes de declarar limpieza completa.

La comparación distingue:

- `folder_missing`;
- `lot_missing`;
- `revision_contract_missing`;
- concordancia secundaria de ganador, importe, fecha y URL.

Signal v1 no transporta revisión, recuento, identificador oficial del ganador ni no adjudicatarios.
Además, solo indexa 643. Las 48 unidades agregadas se informan como
`source_not_indexed_v1`, fuera del recall 643. Falta de credencial produce
`not_run_missing_ephemeral_credential`, no `0/96`.

## 7. Estadística y gates

Se publican numerador, denominador y Wilson 95 % por familia, periodo y fase del pipeline. Los
umbrales altos son gates de ingeniería de cero error crítico observado, no garantías
poblacionales:

- 12/12 tiene límite inferior Wilson aproximado 75,8 %;
- 96/96, 96,2 %;
- 72/72, 94,9 %.

La precisión requiere predicciones positivas y una base negativa; el recall exige enumeración
manual exhaustiva. Los challenge sets no sirven para ambas cosas. Los lotes del mismo expediente y
aserciones del mismo artículo se tratan como clústeres, no como observaciones independientes.

Los gates se separan en:

1. disponibilidad y congelación de fuente;
2. adquisición de documento;
3. extracción/normalización;
4. fidelidad del contrato Signal/Oracle.

## 8. Persistencia del spike

Se versionan protocolo, codebook, semilla, algoritmo, mappings, manifest redactado, recuentos,
hashes, métricas y decisiones. Quedan exclusivamente en `.work/77`:

- Atom, XML, HTML, PDF, OCR y texto;
- nombres, identificadores y hojas de anotación;
- respuestas Signal y mapa de `sample_id` a literal;
- prompts/respuestas locales sobre datos reales;
- secretos o material de revocación.

El directorio local debe tener permisos restrictivos y una política explícita de borrado. Antes de
commitear se comprueba que ningún bruto o identificador personal esté trackeado.
