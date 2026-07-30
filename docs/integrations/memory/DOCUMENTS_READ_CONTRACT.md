# Contrato de lectura · documentos Oracle → motor de memoria

**Ámbito:** cómo un lector externo en el mismo host/BD (p. ej. `opn-memory`)
resuelve un documento Oracle como **fuente de texto libre**.  
**No** es la API de escritura ni el diseño del motor de memoria.

Fecha: 2026-07-30 · Fuente de verdad: modelos en
`apps/api/src/opn_oracle/documents/models.py` y pipeline en `service.py`.

---

## 1. Tablas y campos estables (contrato)

### `documents` (metadatos del artefacto)

| Campo | Tipo lógico | Contrato |
|---|---|---|
| `id` | UUID | estable, PK lógica del documento |
| `tenant_id` | UUID | aislamiento multi-tenant **obligatorio** |
| `dossier_id` | UUID | expediente propietario |
| `original_filename` | text ≤255 | nombre de subida sanitizado |
| `media_type` | text | MIME admitido en subida |
| `byte_size` | int ≥0 | tamaño del blob almacenado |
| `checksum` | bytea(32) | **SHA-256** del contenido almacenado |
| `storage_key` | text ≤600 | clave de objeto en storage (no URL pública) |
| `status` | enum string | ver estados abajo |
| `classification` | `public` \| `internal` | |
| `current_version_id` | UUID nullable | versión de procesado actual |
| `version` | int ≥1 | contador de mutaciones lógicas del registro |
| `scan_status` | string | pending/clean/infected/error/not_configured |
| `scan_result` | JSON object | detalle de escaneo (no texto del documento) |
| `created_at` / `updated_at` | timestamptz | |
| `deleted_at` | timestamptz nullable | soft-delete |
| `purge_after` | timestamptz nullable | purga física diferida (~30 días) |
| `legal_hold` | bool | bloquea borrado |

**Estados de `documents.status`:**  
`uploaded`, `queued`, `processing`, `ready`, `failed`, `quarantined`, `deleted`.

Para ingestión de memoria, consumir preferentemente filas con
`status = 'ready'` y `deleted_at IS NULL`.

### `document_versions` (procesado inmutable por versión)

| Campo | Contrato |
|---|---|
| `id`, `tenant_id`, `document_id`, `dossier_id` | contexto |
| `version_number` | entero monótono por documento |
| `status` | queued / scanning / parsing / chunking / ready / failed / quarantined / abandoned |
| `source_checksum` | SHA-256 del blob fuente (igual al del documento en v1) |
| `parser_name` / `parser_version` / `chunker_version` | trazabilidad del pipeline |
| `provenance` | JSON object |
| `processing_started_at` / `processing_completed_at` | |

### `document_chunks` (texto extraído fragmentado)

| Campo | Contrato |
|---|---|
| `id`, `tenant_id`, `document_id`, `document_version_id` | |
| `ordinal` | orden estable del fragmento |
| `text` | texto extraído del chunk |
| `locator` | JSON (página, párrafo, char_start, etc.) |
| `checksum` | hash del chunk |
| `tsv` / FTS | índice de búsqueda (implementación; no API externa) |

---

## 2. Dónde vive el texto extraído

- El **blob original** está en el backend de storage (`local` o `s3`) bajo `storage_key`.
- El **texto libre** para lectura/FTS está en **`document_chunks.text`**, no en el fichero.
- Se genera en el job `oracle.document.process` (scan → parse → chunk).
- **Garantías:**
  - Con `status=ready` y versión actual, los chunks de `current_version_id` son la vista canónica.
  - Si cambia el parser, **no se reescribe** la versión anterior: `reprocess` crea
    `document_versions` con `version_number` nuevo y nuevos chunks.
  - Tras soft-delete, el registro metadatos permanece; la purga posterior puede
    borrar el blob y vaciar/redactar extractos de evidencia ligados a chunks.

---

## 3. Inmutabilidad del artefacto

- Un documento subido **no se edita en sitio**: el contenido en storage se escribe una vez
  en la clave `storage_key`.
- Correcciones de procesado = **versión nueva** (`new_reprocess_version`), no overwrite del blob.
- Re-subir el **mismo PDF** por la API de upload crea un **documento nuevo** (nuevo `id` y
  `storage_key`), no un dedupe automático por checksum. El checksum se registra para
  integridad y descarga, no como clave de unicidad de negocio.

---

## 4. Resolución documento → fichero (lector mismo host)

1. Leer fila `documents` filtrando **siempre** por `tenant_id` (+ `id`).
2. Verificar `status` y `deleted_at`.
3. Resolver blob:
   - **local:** `{DOCUMENT_LOCAL_ROOT}/{storage_key}` (ruta relativa segura bajo el root);
   - **s3:** `GetObject` con la clave `storage_key` en el bucket configurado.
4. Calcular SHA-256 del stream y comparar con `documents.checksum` (32 bytes raw) o su hex
   en API (`checksum` serializado en hex).
5. Para texto libre, unir `document_chunks` de `document_version_id = current_version_id`
   ordenados por `ordinal`.

**No** confiar en un `tenant_id` aportado por un cliente externo sin contexto de sesión:
el motor de memoria debe usar credenciales de servicio y scoping explícito por tenant.

---

## 5. Qué es estable vs qué puede cambiar

### Estable (contrato)

- Nombres de tablas `documents`, `document_versions`, `document_chunks`.
- Significado de `id`, `tenant_id`, `dossier_id`, `checksum` (SHA-256), `storage_key`,
  `byte_size`, `media_type`, soft-delete vía `status='deleted'` + `deleted_at`.
- Que el texto citables/indexable vive en chunks de la versión actual ready.

### Puede cambiar sin aviso (no acoplar)

- Forma exacta de `locator` / `provenance` / `metadata` / `scan_result`.
- Versiones de parser/chunker y política de solape de chunks.
- Prefijos internos de `storage_key`.
- Columnas FTS, índices, y jobs de recuperación de leases.
- Endpoints HTTP y códigos problem+json (salvo los ya documentados en OpenAPI).

---

## 6. Excepciones de entorno (oracle-dev)

| Variable | Valor dev | Nota |
|---|---|---|
| `DOCUMENTS_ENABLED` | `true` | |
| `DOCUMENT_STORAGE_BACKEND` | `local` | |
| `DOCUMENT_ALLOW_LOCAL_BACKEND` | `true` | **solo dev**; prod real no lo define |
| `DOCUMENT_SCANNER_MODE` | `noop` | excepción dev |
| `DOCUMENT_ALLOW_OFFICIAL_UNSCANNED` | `true` | permite noop con `APP_ENV=production` |

Producción real sigue exigiendo **S3 + ClamAV** (o S3 + `DOCUMENT_ALLOW_OFFICIAL_UNSCANNED`
solo para el scanner) cuando `DOCUMENTS_ENABLED=true`.
