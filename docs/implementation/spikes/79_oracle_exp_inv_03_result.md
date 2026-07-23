# ORACLE-EXP-INV-03 · adquisición documental y contrato candidato

**Fecha:** 2026-07-23

**Veredicto:** `GO` para parsing interno y organización del doble etiquetado; `NO-GO` para usar
`qwen3.5:9b` como extractor autónomo, medir precision/recall o promover datos al dominio.

## 1. Core congelado antes de mirar documentos

Se sortearon tres unidades por cada una de las ocho celdas INV-02. El core contiene 24/96
expedientes y su hash es:

`56efc30ad89edea7384149fdaa22d7ece8b7f15dc6adf5fb93c436fad4246d80`.

La selección usa exclusivamente semilla+`sample_id`; cambiar presencia o número de documentos no
cambia la muestra. No se repuso ninguno de los siete expedientes sin referencias.

Se generaron en el área privada:

- 96 hojas vacías para anotador A;
- 24 hojas vacías para anotador B;
- un mapa coordinador separado;
- cero etiquetas completadas y cero adjudicadas.

Los packs de anotador no contienen `sample_id`, ganador estructurado ni propuestas Ollama.

## 2. Adquisición real

Las 24 unidades contenían 145 referencias y 17 tenían al menos una. El primer recorrido obtuvo:

| Resultado | Referencias |
|---|---:|
| PDF válido en cuarentena | 10 |
| HTML 200 con bloqueo WAF de PLACSP | 133 |
| URL HTTP rechazada | 2 |
| Total | 145 |

Por host:

| Host | Resultado |
|---|---:|
| `contrataciondelestado.es` | 133 WAF |
| `contractaciopublica.cat` | 6 PDF |
| `contratos-publicos.comunidad.madrid` | 2 PDF |
| `www.contratacion.euskadi.eus` | 2 PDF |
| `www.madrid.org` | 2 HTTP rechazadas |

Los diez PDF suman 17.737.928 bytes. Están nombrados por hash, con sidecar, SHA-256, permisos
`0600` y dentro de `.work/79`. La repetición verificó y reutilizó los diez objetos; no volvió a
adoptarlos por mera existencia.

La adquisición fija peer tras DNS público, conserva TLS por hostname, elimina proxies, no sigue
redirects, exige `Accept-Encoding: identity`, limita bytes/tiempo y comprueba magic. PLACSP también
bloqueó la navegación controlada después de entrar en el portal, por lo que no se atribuye el
resultado a una peculiaridad de `curl`.

Una repetición posterior ya autorizada recuperó 120 de las referencias PLACSP antes bloqueadas. El
estado final reproducido sobre las mismas 145 referencias fue:

| Resultado final | Referencias |
|---|---:|
| PDF/DOCX válido en cuarentena | 130 |
| Error HTTP | 4 |
| Respuesta no clasificable | 6 |
| ZIP no admitido en esta fase | 3 |
| URL HTTP rechazada | 2 |
| Total | 145 |

Los 130 objetos suman 191.795.034 bytes. El cambio de 10 a 130 demuestra que el WAF observado no
era una característica estable del corpus: cada corrida conserva su resultado y no convierte el
fallo temporal inicial en ausencia documental.

## 3. Autorización interna, parser y OCR

Por instrucción explícita del propietario, ClamAV no bloquea esta investigación interna. La corrida
usó `--allow-unscanned-internal`; cada objeto conservó `scan_status=not_scanned`, registró
`internal_unscanned_authorized` y fue revalidado por tipo de fichero, no-symlink, tamaño y SHA-256
antes de abrirse. La política productiva no cambió.

El parser productivo se cargó por fichero y hash sin inicializar Flask, SQLAlchemy o Celery:

| Estado parser | Documentos |
|---|---:|
| Texto nativo | 125 |
| OCR requerido | 5 |
| Total considerado | 130 |

Los 125 documentos nativos produjeron 3.631 bloques. Hay Poppler, pero no Tesseract/OCRmyPDF; esos
cinco casos quedan como `ocr_required`, sin frenar los demás.

## 4. Contrato candidato Ollama v2

Se añadió `placsp-participation-candidate/v2`:

- roles inequívocos, incluido `non_awarded_bidder`;
- UTE triestado;
- nombre, identificador, lote, rol y miembros ligados a citas;
- página física PDF 1-based;
- eco obligatorio de documento y SHA-256;
- citas exactas y únicas validadas en Python;
- `needs_human_review=true` constante;
- fingerprint de inferencia sin `gold` ni `expected`.

El smoke sintético adversarial usó `qwen3.5:9b`, digest
`6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
`think=false`, temperatura cero y contexto 8192.

| Medida | Resultado |
|---|---:|
| Casos | 4 |
| Llamadas físicas | 6 |
| Reparaciones | 2 |
| Schema final válido | 2/4 |
| Validación estructural final | 2/4 |
| Match exacto | 1/4 |
| Falsos positivos nominales | 0 |
| Falsos negativos | 3 |
| Intentos que agotaron salida | 3/6 |
| Mediana de llamada física | 55,1 s |
| Máximo | 83,2 s |
| Tokens de salida/s mediana | 23,0 |

El caso de exclusión devolvió abstención y omitió la entidad. El caso con dos participantes y el
caso de inyección no validaron ni después de reparación. La ausencia de falsos positivos en cuatro
casos no compensa las omisiones ni el 50 % de schema.

Una segunda ejecución reutilizó 4/4 fingerprints, hizo cero llamadas y mantuvo resultados. El
extractor sintético permanece `NO-GO`.

## 5. Pasada real sobre documentos

De los 125 documentos con texto, 111 contenían al menos una página seleccionable por señales
deterministas. Se eligieron diez por ranking opaco reproducible, sin mirar nombres ni gold.

| Medida | Resultado |
|---|---:|
| Documentos seleccionados | 10 |
| Llamadas físicas | 17/24 |
| Reparaciones | 7 |
| Schema final válido | 6/10 |
| Validación determinista final | 5/10 |
| Intentos agotados por longitud | 8/17 |
| Aserciones validadas | 0 |
| Mediana de llamada física | 55,1 s |
| Máximo | 102,6 s |

La abstención agregada no equivale a ausencia de participantes. Un diagnóstico manual posterior,
fuera del gold, encontró al menos dos documentos seleccionados con listas o tablas nominales de
licitadores. En ambos la salida agotó 1.600 tokens y quedó inválida. Es una señal material de falso
negativo, pero no se publica como recall porque A/B y adjudicación siguen vacíos.

Conclusión técnica: el parser y la selección de páginas ya permiten iterar con datos reales;
`qwen3.5:9b` necesita extracción por página/chunk, salida más compacta y merge determinista antes
de ampliar la corrida. Toda salida continúa siendo candidata y de revisión humana obligatoria.

## 6. Qué puede y qué no puede afirmarse

Sí puede afirmarse:

- que la muestra doble ciego quedó congelada sin sesgo documental posterior;
- que 130/145 referencias del core produjeron un PDF/DOCX válido en la corrida final;
- que el primer intento sufrió 133 bloqueos WAF y una repetición recuperó después 120;
- que los bytes recuperados están en cuarentena;
- que 125/130 documentos tienen texto nativo y cinco requieren OCR;
- que la pasada real validó estructuralmente 5/10 salidas y ninguna aserción;
- que el schema v2 rechaza promociones, citas y referencias inválidas.

No puede afirmarse:

- cobertura nacional de documentos;
- presencia o ausencia de licitadores;
- precisión, recall, F1 o completitud;
- que los documentos estén limpios por antivirus;
- que Ollama extraiga participantes con calidad suficiente;
- que un no localizado no se presentase.

## 7. Verificación

- 33 pruebas específicas correctas;
- mutaciones restauradas hicieron fallar selección condicionada por documentos, HTTPS, redirects,
  confianza en MIME, revisión humana constante, cita literal, cegado del pack, autorización
  interna, integridad SHA-256 y prioridad de páginas;
- repetición de adquisición: 130 objetos reutilizados por sidecar+tamaño+hash;
- repetición Ollama: 4/4 caches, cero llamadas;
- repetición Ollama real: 10/10 caches, cero llamadas y métricas idénticas;
- cero ficheros `.work` trackeados.
- Ruff check y format-check correctos en los tres ficheros Python de INV-03;
- mypy correcto sobre 118 módulos productivos;
- suite completa con PostgreSQL/Redis/Celery reales: 661 pruebas y 84,70 % de cobertura.

## 8. Siguiente gate

1. Dividir inferencia por página/chunk, compactar el contrato y fusionar candidatos en Python.
2. Repetir primero sobre los documentos con listas nominales diagnósticas y comprobar citas.
3. Añadir OCR local para los cinco documentos sin texto.
4. Completar A/B y adjudicación humana.
5. Solo después congelar candidate+gold y calcular precisión/recall por celda.

## 9. Seguimiento INV-04: chunking y merge candidato

Se implementó `placsp-participation-chunk/v1` como unidad compacta por trozo de página y un merge
determinista hacia `placsp-participation-candidate/v2`. Cada trozo valida `document_id`, SHA-256,
`chunk_id`, página, cita literal única y presencia del nombre en la cita; el merge final se vuelve
a validar contra páginas físicas. La caché incluye parámetros de inferencia.

Smoke real acotado con qwen3.5:9b:

| Medida | Resultado |
|---|---:|
| Objetos reutilizados | 130 |
| Documentos parseados nativos | 125 |
| Documentos con OCR pendiente | 5 |
| Documentos elegibles | 111 |
| Documentos ejecutados | 2 |
| Trozos ejecutados | 12 |
| Llamadas físicas | 13 |
| Schema por trozo | 12/12 |
| Validación estructural por trozo | 5/12 |
| Merge final válido | 2/2 |
| Candidatos fusionados citables | 13 |
| Agotamientos de salida | 1 |
| Mediana de llamada física | 21,9 s |

El cambio es un `GO` metodológico para continuar con extracción candidata por chunks. Sigue siendo
`NO-GO` para promoción, precisión/recall o afirmaciones sobre participantes hasta completar gold
A/B y adjudicación humana.

## 10. Seguimiento INV-05: comparación de schema y expansión acotada

Se probó un `chunk/v2` privado con varias citas por aserción para separar encabezados de tabla y
filas nominales. No mejoró: en 8 chunks reales obtuvo 6/8 schemas, 1/8 chunks estructurales y dos
candidatos fusionados. Errores agregados: cinco `name_not_in_quote`, tres `quote_missing` y dos
`schema_invalid`. Se descarta como extractor activo.

Con `chunk/v1` restaurado, una expansión acotada sobre cuatro documentos produjo:

| Medida | Resultado |
|---|---:|
| Documentos ejecutados | 4 |
| Chunks ejecutados | 18 |
| Llamadas físicas | 15 |
| Chunks reutilizados | 4 |
| Schema por chunk | 18/18 |
| Validación estructural por chunk | 11/18 |
| Merge final válido | 4/4 |
| Candidatos fusionados citables | 15 |
| Agotamientos de salida | 1 |
| Mediana de llamada física | 18,0 s |

Conclusión: `chunk/v1` permanece como mejor contrato local medido. La siguiente mejora debe
centrarse en selección/normalización determinista de fragmentos y gold humano, no en enriquecer el
schema del modelo.
