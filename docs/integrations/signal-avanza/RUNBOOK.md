# Runbook · integración Oracle ↔ Signal Avanza

Actualizado: 2026-07-14

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
GET /api/v1/procurement/tenders?keywords=energia&active=true&limit=5
GET /api/v1/procurement/stats
```

Para búsquedas guardadas, el tenant debe tener una conexión `signal-avanza` activa con
`external_tenant_id` o equivalente en `connection_metadata`.

### Errores esperados

- `503 procurement_not_configured`: falta configuración segura `SIGNAL_AI_*`.
- `409 signal_connection_missing`: la operación tenant-scoped no tiene conexión activa con Signal.
- `503` retryable: timeout, `429` o `5xx` del proveedor.
- `502`: redirect, payload no JSON, JSON inválido o respuesta demasiado grande.

### Follow-up 4b

Persistir licitaciones/adjudicaciones fijadas a un `dossier` u `opportunity` con RLS, auditoría y
trazabilidad para alimentar el informe `tender.v1`. Esta fase solo proxya consulta y búsquedas
guardadas en Signal.
