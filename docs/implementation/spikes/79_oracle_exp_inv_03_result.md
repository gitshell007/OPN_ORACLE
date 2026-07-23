# ORACLE-EXP-INV-03 · adquisición documental y contrato candidato

**Fecha:** 2026-07-23

**Veredicto:** `GO` para organizar el doble etiquetado; `NO-GO` para parsing/Ollama real,
participantes nominales, precision/recall y promoción al dominio.

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

## 3. Gate antivirus y OCR

El host no dispone de ClamAV. Los diez PDF permanecen:

```text
downloaded → quarantined → not_scanned
```

No llegaron al parser ni a Ollama. INV-03 no usa la excepción productiva
`official_source_without_clamav_v1`, y esa excepción tampoco cubriría los hosts autonómicos.

El parser productivo puede cargarse por fichero y hash sin inicializar Flask, SQLAlchemy o Celery,
pero no se ejecutó sobre bytes reales. Hay Poppler, pero no Tesseract/OCRmyPDF; OCR queda
`unavailable`, no `parser_miss`.

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
extractor real permanece `NO-GO`.

## 5. Qué puede y qué no puede afirmarse

Sí puede afirmarse:

- que la muestra doble ciego quedó congelada sin sesgo documental posterior;
- que 10/145 referencias del core produjeron PDF descargable por el canal automatizado fijado;
- que PLACSP devolvió WAF para 133/145;
- que los bytes recuperados están en cuarentena;
- que el schema v2 rechaza promociones, citas y referencias inválidas.

No puede afirmarse:

- cobertura nacional de documentos;
- presencia o ausencia de licitadores;
- precisión, recall, F1 o completitud;
- que los PDF estén limpios;
- que Ollama extraiga participantes con calidad suficiente;
- que un no localizado no se presentase.

## 6. Verificación

- 30 pruebas específicas correctas;
- mutaciones restauradas hicieron fallar selección condicionada por documentos, HTTPS, redirects,
  confianza en MIME, revisión humana constante, cita literal y cegado del pack;
- repetición de adquisición: diez objetos reutilizados por sidecar+tamaño+hash;
- repetición Ollama: 4/4 caches, cero llamadas;
- cero ficheros `.work` trackeados.
- Ruff check y format-check correctos en los tres ficheros Python de INV-03;
- mypy correcto sobre 118 módulos productivos;
- suite completa con PostgreSQL/Redis reales: 658 pruebas y 84,70 % de cobertura.

## 7. Siguiente gate

1. Desplegar ClamAV local o un scanner autorizado y repetir scan sobre los diez PDF.
2. Ejecutar parser aislado solo sobre `clean`; clasificar texto nativo frente a OCR requerido.
3. Resolver acceso documental PLACSP sin sortear WAF, CAPTCHA ni controles de fuente.
4. Completar A/B y adjudicación humana.
5. Solo después congelar candidate+gold y calcular precisión/recall por celda.
