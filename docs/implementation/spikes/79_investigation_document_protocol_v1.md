# ORACLE-EXP-INV-03 · protocolo documental v1

**Fecha:** 2026-07-23

**Estado:** protocolo ejecutable de spike; no crea datos de dominio

## 1. Unidad y selección

El core es un subpanel de 24 de las 96 unidades fijadas por INV-02:

```text
familia {643 alojada, 1044 agregada}
× periodo {2022-01, 2025-01}
× estructura {simple, compleja}
× 3 expedientes
```

El ranking SHA-256 usa únicamente la semilla versionada y `sample_id`. Se ejecuta antes de mirar
si el expediente tiene documentos, qué tipo aparentan o si responden. Un fallo no se sustituye.
Dentro de esas 24 unidades se intentan todas las referencias bajo el presupuesto fijado. Los
top-ups dirigidos por título o formato, si se crean después, tendrán denominador separado.

## 2. Packs de anotación

El anotador A recibe 96 hojas vacías y el anotador B las 24 del core doble ciego. Las hojas no
incluyen `sample_id`, ganador estructurado, sugerencias Ollama ni etiquetas del otro anotador.
Un mapa coordinador privado enlaza identificadores opacos con el marco.

Los estados se conservan por separado:

1. referencia publicada;
2. descarga válida;
3. documento relevante;
4. contenido nominal;
5. rol por lote;
6. lista completa o reconciliable.

Gold no existe hasta que A/B terminen y un adjudicador resuelva todos los desacuerdos, ambiguos y
casos con personas.

## 3. Identidad de referencia y cuarentena

`document_id` puede faltar o repetirse. La identidad local es:

```text
source_ref_id = SHA256(sample_id + NUL + URL exacta)
```

La ruta física usa solo ese identificador. URL, query, nombre remoto, texto y literales permanecen
en el ledger privado. Un objeto solo se reutiliza cuando sidecar, tamaño y SHA-256 vuelven a
coincidir; nunca se adopta un fichero huérfano.

## 4. Frontera de red

La adquisición:

- exige HTTPS y puerto 443;
- usa una allowlist fija de host, ruta y claves query observadas;
- rechaza userinfo, fragmentos, controles, traversal y escapes de separador;
- resuelve A/AAAA y rechaza cualquier dirección no pública;
- fija el peer resuelto manteniendo validación TLS del host;
- elimina proxies del entorno;
- declara `Accept-Encoding: identity`;
- no sigue redirects;
- limita tiempo, solicitudes, bytes por objeto y bytes por corrida;
- comprueba estado, headers, bytes y magic;
- conserva HTML/WAF como fallo, nunca como documento.

Los cuatro enlaces HTTP observados en INV-02 permanecen `url_rejected`; no se actualizan a HTTPS
por conjetura.

## 5. Antivirus, parser y OCR

PDF/DOCX válidos se almacenan en cuarentena con permisos `0600`. Solo `scan_status=clean` permite
pasar a parser. La excepción temporal productiva para fuentes oficiales sin antivirus no se usa en
este benchmark.

El parser productivo se carga por su fichero exacto y hash, sin ejecutar los inicializadores de
Flask, SQLAlchemy o Celery. PDF conserva página física 1-based, rechaza cifrado y limita páginas y
texto. OCR es una etapa independiente. En el host actual hay rasterización Poppler, pero no
Tesseract/OCRmyPDF: un PDF sin texto quedaría `ocr_unavailable`, nunca `parser_miss`.

## 6. Contrato Ollama v2

El modelo recibe exclusivamente:

- alias opaco del documento;
- SHA-256 de sus bytes;
- páginas autorizadas con texto y hash.

Devuelve `placsp-participation-candidate/v2`, con:

- evaluación de presencia y señal de completitud;
- literal de organización;
- identificador y lote solo si son literales;
- rol explícito;
- UTE triestado y miembros citados;
- citas por página con campo soportado;
- ambigüedades;
- `needs_human_review=true`.

Python valida schema, eco de documento/hash, páginas, cita exacta y única y presencia del literal
en la cita correspondiente. La inferencia se fingerprinta sin `gold` ni `expected`. Candidate y
gold viven en raíces distintas y el scoring es un proceso posterior.

## 7. Métricas y límites

Antes del gold solo se publican:

- referencias e intentos por celda/host;
- estados de descarga, formato, antivirus, parser y OCR;
- bytes, páginas y hashes;
- schema, reparación, cita, hash y página;
- latencia, tokens, digest y presupuesto Ollama;
- abstenciones, duplicados y conflictos estructurales.

Precisión, recall, F1, falsos negativos y completitud permanecen
`not_available_pending_gold`. Una muestra de 24 no autoriza la promesa «todos los participantes».

## 8. Gate

Son `NO-GO` inmediatos:

- cualquier promoción automática;
- aceptar una cita, página o hash inválido;
- tratar WAF/HTML como PDF;
- parsear bytes no limpios;
- obedecer instrucciones dentro del documento;
- mezclar expected/gold en inferencia;
- trackear URL, texto, nombres, PDF o salidas reales.
