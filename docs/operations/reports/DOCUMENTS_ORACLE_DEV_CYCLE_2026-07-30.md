# Ciclo documental en oracle-dev · 2026-07-30

## Estado inicial

| Variable (proceso) | Valor |
|---|---|
| `DOCUMENTS_ENABLED` | `false` |
| `DOCUMENT_STORAGE_BACKEND` | `local` |
| `DOCUMENT_SCANNER_MODE` | `noop` |
| Respuesta listado documentos | **503** `documents_disabled` (request_id `dfa4dcac…`) |

Disco libre en `/var/lib/opn-oracle-dev`: **~236 GiB**.

## Cambios de configuración (oracle-dev)

```
DOCUMENTS_ENABLED=true
DOCUMENT_STORAGE_BACKEND=local
DOCUMENT_LOCAL_ROOT=/var/lib/opn-oracle-dev/document-storage
DOCUMENT_SCANNER_MODE=noop
DOCUMENT_ALLOW_LOCAL_BACKEND=true
DOCUMENT_ALLOW_OFFICIAL_UNSCANNED=true
DOCUMENT_MAX_BYTES=26214400
```

Código: `DOCUMENT_ALLOW_LOCAL_BACKEND` en `config.py` (escape explícito; producción sin flag sigue exigiendo S3).  
`security.py`: citabilidad/descarga con noop+local-backend.

Tras reinicio: health 200; listado sin sesión **401** (ya no 503).

## Ciclo demostrado

Expediente: `DEV-DOCS · Expediente de prueba documental`  
`c9749dc5-cef2-439d-91a8-44e572872e7f` · tenant OPN.

| # | Paso | Resultado | Evidencia |
|---|---|---|---|
| 1 | Subida PDF | **202** (no 201) + job | doc `132c8ec7-…` job; request_id `981c6a0d…` |
| 2 | Rechazo MIME | **422** `document_rejected` | request_id `fc8e78a6…` |
| 2b | Oversize | **413** `request_entity_too_large` | request_id `525292a6…` |
| 3 | Procesado | **ready** + texto | chunk «DEV-DOCS TEST PLIEGO ORACLE memoria» |
| 4 | Re-subida mismo PDF | **nuevo id** (no dedupe) | ids distintos |
| 5 | Cita/evidencia | **201** | evidence `772c6ca6-…` request_id `d137daef…` |
| 6 | Descarga | **200** byte-equal SHA-256 | `5b81eca3…` |
| 7 | Aislamiento tenant B | **404** get/dl/list | tenant `dev-docs-tenant-b` |
| 8 | Soft delete | **204**; fila `deleted`; fichero **conservado** | purge_after +30d |

### Límites observados

- MIME admitidos: pdf, docx, text/plain, markdown, csv, vtt, srt, transcript+json.
- `DOCUMENT_MAX_BYTES` default 25 MiB; rechazo oversize llega como 413 de capa HTTP.
- Upload API responde **202** Accepted (async job), no 201.

### Hallazgo (resuelto en dev)

Con `noop`, `scan_status=not_configured` y **sin** escape, la descarga devolvía **404** pese a `status=ready` (política `document_available_for_citation`). Corregido solo con `DOCUMENT_ALLOW_LOCAL_BACKEND`.

## Tests

`pytest tests/test_documents.py -m unit --no-cov`: **9 passed**.

## SHA / ficheros

- SHA `06ec3b0` + commit security: ver `oracle-dev` tip.
- `apps/api/src/opn_oracle/config.py`
- `apps/api/src/opn_oracle/documents/security.py`
- `apps/api/tests/test_documents.py`
- `docs/integrations/memory/DOCUMENTS_READ_CONTRACT.md`
- `infra/native-dev/oracle.env.example`
- `docs/operations/reports/DOCUMENTS_ORACLE_DEV_CYCLE_2026-07-30.md`

## Limitaciones

- Scanner **noop** es excepción de dev, no objetivo de prod.
- Contraseñas de prueba rotadas en usuarios de prueba; rotar de nuevo si se reutilizan cuentas reales.
- Tenant `uat-competencia-iturri` está **suspended** (no sirvió para aislamiento).
