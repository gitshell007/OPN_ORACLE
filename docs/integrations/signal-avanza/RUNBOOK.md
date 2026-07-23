# Runbook · integración Oracle ↔ Signal Avanza

Actualizado: 2026-07-15

## Proxy de contratación pública PLACSP

Oracle publica la API interna `/api/v1/procurement` como proxy server-side a Signal. El navegador
no debe llamar a `signal.opnconsultoria.com` ni recibir claves.

### Configuración

No hay variables nuevas. El proxy reutiliza:

- `SIGNAL_AI_BASE_URL`
- `SIGNAL_AI_API_KEY`
- `SIGNAL_AI_ALLOWED_HOSTS`
- `SIGNAL_AI_TIMEOUT_SECONDS`
- `SIGNAL_CONNECT_TIMEOUT_SECONDS`

La URL debe ser HTTPS, estar en allowlist y no contener credenciales, query ni fragmento.

### Autenticación hacia Signal

- `/api/v1/registry/awards`, `/api/v1/registry/tenders`,
  `/api/v1/registry/tenders/{folder_id}/summary` y `/api/v1/registry/stats` usan solo
  `X-API-Key`.
- `/api/v1/oracle/tender-searches*` usa `X-API-Key` y `X-OPN-External-Tenant-ID`. Oracle obtiene
  ese tenant externo de la conexión `signal-avanza` activa del tenant actual.

Enviar `X-OPN-External-Tenant-ID` en los endpoints globales de registro es un bug: puede alterar
cuotas, auditoría o aislamiento del productor.

### Comprobaciones locales

```bash
cd apps/api
uv run pytest -q --no-cov tests/test_procurement.py tests/test_entity_intel.py
uv run ruff check src/opn_oracle/integrations/procurement.py \
  src/opn_oracle/integrations/procurement_routes.py \
  src/opn_oracle/app.py tests/test_procurement.py
```

### Smoke productivo sugerido

Con una sesión web válida en Oracle:

```http
GET /api/v1/procurement/awards?company=Genesis%20Consulting%20SLP&limit=5
GET /api/v1/procurement/tenders?keywords=energia&scope=active&limit=5
GET /api/v1/procurement/tenders?keywords=energia&scope=all&limit=5
GET /api/v1/procurement/stats
```

`scope=all` significa todo el índice disponible en Signal v1, no «solo inactivas» ni archivo
histórico completo. `active` continúa temporalmente como alias deprecado; `scope=historical`
responde `422` hasta que Signal demuestre y publique ese corpus.

Para búsquedas guardadas, el tenant debe tener una conexión `signal-avanza` activa con
`external_tenant_id` o equivalente en `connection_metadata`.

### Errores esperados

- `503 procurement_not_configured`: falta configuración segura `SIGNAL_AI_*`.
- `409 signal_connection_missing`: la operación tenant-scoped no tiene conexión activa con Signal.
- `503` retryable: timeout, `429` o `5xx` del proveedor.
- `502`: redirect, payload no JSON, JSON inválido o respuesta demasiado grande.

## Despliegue procurement

El despliegue coordinado de PLACSP debe respetar este orden para evitar que Oracle intente fijar
expedientes contra lookups que Signal todavía no publica.

### 1. Signal primero

Desplegar primero Signal con los endpoints:

- `GET /api/v1/registry/tenders/{folder_id}` → `{item}` o `404 tender_not_found`.
- `GET /api/v1/registry/awards/{folder_id}` → `{folder_id,total,items:[...]}`.

Nadie los llama antes de desplegar Oracle, así que añadirlos en Signal es compatible hacia atrás.

### 2. Backfill inicial en Signal

Ejecutar estos comandos en el servidor de Signal (`/opt/apps/opn_signal`). Los feeds PLACSP solo se
han verificado desde ese servidor por WAF/IP.

Histórico de adjudicaciones PLACSP (`docs/web-search-and-sources.md` §1.16.1):

```bash
cd /opt/apps/opn_signal
.venv/bin/python - <<'PY'
from app.db import get_session_factory
from app.services import placsp_awards

factory = get_session_factory()
print(placsp_awards.backfill_archives(factory, cache_dir="var/placsp/archives"))
PY
```

Licitaciones activas PLACSP (`docs/web-search-and-sources.md` §1.16.2):

```bash
cd /opt/apps/opn_signal
.venv/bin/python - <<'PY'
from app.db import get_session_factory
from app.services import placsp_open_tenders

factory = get_session_factory()
print(placsp_open_tenders.backfill_current_year(factory, cache_dir="var/placsp/archives"))
session = factory()
try:
    print(placsp_open_tenders.ingest_feed(
        session,
        cache_path="var/placsp/placsp_licitaciones.atom",
        source_key="live",
        max_age_seconds=0,
        force=True,
    ))
    session.commit()
finally:
    session.close()
PY
```

### 3. Oracle después

Cuando Signal y el backfill estén listos:

```bash
cd /opt/opn-oracle/current/apps/api
uv run flask --app opn_oracle.wsgi:app db upgrade
```

El head esperado tras Fase 4b es `20260714_0019`. Después de activar el release Oracle:

```bash
cd /opt/opn-oracle/current
./scripts/smoke-production.sh https://oracle.opnconsultoria.com
```

El smoke público comprueba liveness, meta, headers de login, métricas ocultas, presencia de
`entity-intel`, presencia de `procurement` y redirect anónimo de `/app/actors` a login.

### Rollback

- `db downgrade` de `20260714_0019` restaura el CHECK anterior de `evidence` y re-cuarentena las
  evidencias `source_kind='procurement'` como `legacy_unresolved`.
- `db downgrade` de `20260714_0018` elimina `dossier_procurement_items`; se pierden los pins PLACSP
  persistidos, no los datos originales de Signal.
