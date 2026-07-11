# Documentos, evidencias y búsqueda

La fase documental ingiere fuentes como datos no confiables y nunca como instrucciones. El
original vive fuera de PostgreSQL; la base conserva lifecycle, checksum, provenance, fragmentos y
citas inmutables.

## Formatos y límites

- PDF (`pypdf`), máximo 500 páginas y 5 millones de caracteres extraídos; no OCR.
- DOCX OpenXML sin macros, máximo 2.000 entradas, 50 MiB descomprimidos, 20 MiB por entrada y
  ratio de compresión 100:1.
- TXT/Markdown UTF-8, CSV (20.000 filas, 200 columnas), VTT/SRT y transcript JSON estructurado.
- 25 MiB por archivo y 1 GiB por tenant por defecto; ambos límites son configurables.

El worker Celery aporta soft/hard timeout, pero no sustituye un sandbox de parser. Antes de
producción los workers `documents` deben ejecutarse sin red saliente, filesystem de solo lectura
salvo storage temporal y límites de CPU/memoria del runtime de contenedores.

## Storage y scan

`LocalObjectStorage` es solo desarrollo/test: root privado fuera del webroot, keys UUID por
tenant/dossier/documento, permisos `0700/0600`, escritura temporal atómica, límite streaming y
SHA-256. `S3ObjectStorage` exige HTTPS, cifrado AES-256, allowlist y endpoint IP global fijado; los
hostnames se rechazan para no aceptar DNS rebinding mediante el SDK.

`NoopScanner` queda marcado como `not_configured` y sus archivos no son descargables. Producción
con `DOCUMENTS_ENABLED=true` exige S3 y `DOCUMENT_SCANNER_MODE=clamav`; el adapter usa `INSTREAM`
acotado y falla cerrado ante timeout o respuesta ambigua.

## Durabilidad y trazabilidad

Upload, `BackgroundJob` y versión se confirman en una transacción; la publicación posterior es
reconciliable. La cuota se serializa por tenant con advisory transaction lock. El worker procesa el
`version_id` exacto y usa `DocumentProcessingAttempt`, lease y execution token: un retry obsoleto
no puede borrar chunks ni marcar fallida una versión nueva.

El chunking estructural conserva página, párrafo, speaker/timestamp, offsets exactos y checksum.
Reprocesar crea otra `DocumentVersion`; `Evidence` sigue apuntando a la versión/chunk histórico.
FTS usa `plainto_tsquery`, `tsvector` generado y GIN bajo RLS; pgvector queda deshabilitado porque
no hay proveedor/política de embeddings aprobados.

## Retención

El borrado lógico es inmediato. El mantenimiento purga el objeto y sustituye texto de chunks y
extractos por un marcador, conservando IDs, locator, metadata y hashes. `legal_hold` bloquea purge.
La reconciliación de objetos huérfanos y el sandbox de parser productivo siguen siendo controles
operativos requeridos antes del despliegue.
