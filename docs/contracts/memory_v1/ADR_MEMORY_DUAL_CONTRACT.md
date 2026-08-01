# ADR · Contrato bilateral memoria dual Oracle↔Signal (MDEV-01)

- Estado: aceptada
- Fecha: 2026-08-01
- IDs: Oracle `ORC-ADR-0011` / programa `MEMORIA_DEV_V2`

## Contexto

MDEV-00 fijó baseline Dev. Antes de implementar retrieve real e ingesta bilateral hay que
congelar contratos versionados, scopes, modos, errores, configuración y citabilidad.

## Decisiones

### Scope canónico productivo

```
consumer API autenticado
+ X-OPN-External-Tenant-ID ∈ allowed_external_tenant_ids
+ dossier_id UUID autorizado
= MemoryScope(
    tenant_key = "c:<consumer_id>|t:<external_tenant_id>",
    product_code = "oracle",
    scope_type = "dossier",
    scope_id = <dossier_id>
  )
```

No hay fallback `_global` ni pilot en rutas productivas. Los scopes pilot solo existen en scripts
de laboratorio y tests unitarios de laboratorio.

### Multi-dossier / misma fuente

Una misma fuente lógica (p. ej. PDF con `source_ref`+checksum) puede materializarse en **dos**
`memory_sources` con scopes distintos (dossier A y dossier B). Las consultas filtran por
`(tenant_key, product_code, scope_type, scope_id)` **antes** del retrieval. No existe JOIN
cross-scope ni post-filter de fugas.

### Modos Oracle

| mode | HTTP retrieve | inyección al LLM |
|---|---|---|
| disabled | no | no |
| shadow | sí + auditoría | no |
| augment | sí | sí, tras materializar Evidence Oracle |

Signal gobierna capacidad técnica del consumer; Oracle gobierna opt-in tenant/expediente.
El master switch del host Signal prevalece siempre.

### Credencial por tenant

Un consumer Signal de entorno (`opn-oracle-dev`) puede servir a varios tenants, pero **cada
tenant Oracle** guarda su propia API key en `IntegrationConnection` tenant-scoped. La key se
asocia server-side a un único `external_tenant_id` en la política de memoria del consumer.
Rotación/revocación de un tenant no invalida los demás. La misma key (scopes memory/monitors/ai)
sirve a todos los endpoints Signal que Oracle consume; no se exige un segundo secreto legacy.

### Citabilidad

Un item Signal no es citable por su ID opaco en Oracle. Antes del LLM, Oracle materializa o
resuelve un `Evidence` inmutable tenant+dossier con source_ref, checksum, extracto, locator,
clasificación, policy/watermark. Solo esos IDs Oracle entran en la allowlist del prompt.

### Degradación / retry

- disabled: no llama
- shadow: error se audita; respuesta Oracle sin items
- augment: timeout/5xx/engine disabled → degrada a memoria Oracle estructurada, coverage.failed,
  diagnóstico visible; auth/scope/tenant denied **no** se reintenta a ciegas

### Contract package

Schemas/fixtures viven copiados en ambos repos bajo `docs/contracts/memory_v1/` con
`CONTRACT_MANIFEST.json` e idéntico `content_set_sha256`. No hay imports cruzados entre repos.

## Consecuencias

- MDEV-02+ implementa retrieve/ingest real respetando estos schemas.
- Migraciones de settings/scopes se planifican en la matriz expand/contract; **no** se aplican en MDEV-01.
- Flags permanecen OFF.

## Riesgos abiertos heredados de MDEV-00

- NO_ROLLBACK Signal Dev
- beat disabled+active drift
