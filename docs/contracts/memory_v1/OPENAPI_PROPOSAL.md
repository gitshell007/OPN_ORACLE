# OpenAPI propuesta · Memory API v1 (Signal) y BFF Oracle (MDEV-01)

No se publica aún en el openapi.json productivo de Oracle salvo fragmentos de settings/mode.
Implementación runtime de rutas productivas: MDEV-02+.

## Headers comunes (Signal)

- `Authorization: Bearer <api_key>` o `X-API-Key`
- `X-OPN-External-Tenant-ID` (obligatorio productivo)
- `X-OPN-Dossier-ID` (UUID; o `dossier_id` en body)
- `Idempotency-Key` en mutaciones
- `If-Match` en updates de settings/profile (ETag)

Scopes de capability (política consumer): `memory:read`, `memory:write`.

## Signal `/api/v1/memory/v1`

| Método | Path | Scope | Descripción |
|---|---|---|---|
| GET | `/health` | none/read | status + capabilities efectivas |
| GET | `/effective-config` | read | ConsumerMemorySettings sanitizado |
| POST | `/scopes/ensure` | write | alta/estado scope dossier |
| GET | `/scopes/{dossier_id}` | read | estado scope |
| POST | `/ingest` | write | batch idempotente |
| POST | `/sources/{source_id}/versions` | write | nueva versión |
| POST | `/sources/{source_id}/tombstone` | write | tombstone |
| POST | `/retrieve` | read | retrieval con budget/filtros |
| GET | `/dossiers/{dossier_id}/stats` | read | counts/coverage/watermark |
| POST | `/analysis-requests` | write | create durable |
| GET | `/analysis-requests/{id}` | read | status |
| POST | `/analysis-requests/{id}/cancel` | write | cancel |
| POST | `/analysis-requests/{id}/retry` | write | retry |

Errores: ver `error_catalog.json` (401/403/404/409/413/422/429/502/503/504).

## Oracle BFF (tenant session)

| Método | Path | Descripción |
|---|---|---|
| GET | `/api/v1/tenants/current/memory/settings` | modo efectivo + procedencia |
| PATCH | `/api/v1/tenants/current/memory/settings` | mode disabled\|shadow\|augment |
| POST | `/api/v1/tenants/current/memory/test-connection` | sonda health Signal |
| GET | `/api/v1/dossiers/{id}/memory/profile` | DossierMemoryProfile |
| PATCH | `/api/v1/dossiers/{id}/memory/profile` | override expediente + ETag |
| GET | `/api/v1/dossiers/{id}/memory/status` | sync/coverage/watermark |

Oracle **nunca** expone API keys tras guardar. Sin selectores de proveedor/modelo.
