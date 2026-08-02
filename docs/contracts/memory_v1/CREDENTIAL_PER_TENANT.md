# Credencial 1:1 consumer + external_tenant (MDEV-01 REWORK-2)

## Modelo congelado: `ConsumerTenantCredential`

Tabla (expand, **no** aplicada en hosts en MDEV-01): `consumer_tenant_credentials`

| Campo | Tipo | Regla |
|---|---|---|
| id | PK | |
| consumer_id | FK consumers | |
| external_tenant_id | string | tenant Oracle externo |
| key_hash | sha256 hex | **globalmente único** (auth busca solo por hash) |
| fingerprint | prefix | no secreto |
| scopes | JSON list | p.ej. memory:read, memory:write — **vacío deniega** (no hereda consumer) |
| status | active\|revoked\|expired | fail-closed; solo `active` autentica |
| valid_from | datetime | futuro → rechazada |
| expires_at | datetime nullable | pasado → rechazada |
| revoked_at | datetime nullable | no null → rechazada |
| last_used_at | datetime nullable | |
| created_at / updated_at | datetime | |

### Constraints e índices (política A — rotación atómica sin overlap)

- **Unique global** `key_hash` (`uq_ctc_key_hash_global`) — la autenticación resuelve solo por hash.
- Unique `(consumer_id, external_tenant_id, key_hash)`
- Index `(key_hash)`
- Index `(consumer_id, external_tenant_id, status)`
- PostgreSQL partial unique `uq_ctc_one_active_per_tenant` on `(consumer_id, external_tenant_id) WHERE status = 'active'`

**No hay overlap de keys activas.** El índice parcial lo impide; no documentar ventanas con dos `active`.

### Rotación (política A)

1. Revocar la credencial activa del tenant (`status=revoked`, `revoked_at=now`).
2. Insertar la nueva fila `active` con nuevo `key_hash`.
3. No existen dos filas `active` concurrentes para el mismo `(consumer_id, external_tenant_id)`.
4. Revocación de tenant A **no** toca filas de tenant B.

### Compatibilidad legacy `consumers.api_key_hash`

- Legacy: una key por consumer sin bind de tenant — **sigue válida** en endpoints Signal no-memory (jobs, signals, ai/run, etc.).
- Memory v1 productiva (`/api/v1/memory/v1/*`): **exige** `ConsumerTenantCredential`.
- Una key legacy en memory.v1 devuelve `tenant_bound_credential_required` (401, catálogo congelado).
- No se borra `api_key_hash` en MDEV-01.

### Oracle

- Guarda el secreto **una sola vez**, cifrado, en `IntegrationConnection` del tenant.
- La misma credencial tenant-bound sirve memory + monitores/señales + `/ai/run` según scopes.
- Binding exacto: 1 credencial activa → 1 `external_tenant_id`.

### Recuentos a medir antes de aplicar migración (MDEV-02/10)

```sql
SELECT count(*) FROM consumers;
SELECT count(*) FROM consumer_tenant_credentials; -- 0 pre-migración
```
