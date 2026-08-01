# Credencial 1:1 consumer + external_tenant (MDEV-01)

## Modelo congelado: `ConsumerTenantCredential`

Tabla (expand, no aplicada en hosts en MDEV-01): `consumer_tenant_credentials`

| Campo | Tipo | Regla |
|---|---|---|
| id | PK | |
| consumer_id | FK consumers | |
| external_tenant_id | string | tenant Oracle externo |
| key_hash | sha256 hex | única con consumer+tenant |
| fingerprint | prefix | no secreto |
| scopes | JSON list | p.ej. memory:read, memory:write, ai:run |
| status | active\|revoked\|expired | |
| valid_from | datetime | |
| expires_at | datetime nullable | |
| revoked_at | datetime nullable | |
| last_used_at | datetime nullable | |
| created_at / updated_at | datetime | |

### Constraints e índices

- Unique `(consumer_id, external_tenant_id, key_hash)`
- Index `(key_hash)`
- Index `(consumer_id, external_tenant_id, status)`
- Invariante de negocio: como máximo **una credencial active** por `(consumer_id, external_tenant_id)` (enforce en servicio de rotación; índice parcial en Postgres en migración).

### Rotación y overlap

1. Emitir nueva key → insertar fila active con nuevo hash.
2. Periodo de overlap opcional: dos filas active temporalmente solo durante ventana de rotación documentada, luego revocar la anterior (`status=revoked`, `revoked_at=now`).
3. Revocación de tenant A no toca filas de tenant B.

### Compatibilidad legacy `consumers.api_key_hash`

- Legacy: una key por consumer sin bind de tenant.
- Memory v1 productiva para Oracle: **requiere** `ConsumerTenantCredential` tenant-bound.
- Path legacy en memory solo se usa si no hay credencial tenant-bound y se documenta como deprecado; allowlist `connector_policy.allowed_external_tenant_ids` sigue fail-closed.
- Retirada de `api_key_hash` como único secret: fase posterior (contract en matriz); no se borra en MDEV-01.

### Oracle

- Guarda el secreto **una sola vez**, cifrado, en `IntegrationConnection` del tenant.
- La misma credencial tenant-bound sirve memory + monitores/señales + `/ai/run` según scopes.
- No hay “y/o”: el binding es **exactamente** 1 credencial activa → 1 external_tenant_id.

### Recuentos a medir antes de aplicar migración (MDEV-02/10)

```sql
SELECT count(*) FROM consumers;
SELECT count(*) FROM consumer_tenant_credentials; -- 0 pre-migración
```
