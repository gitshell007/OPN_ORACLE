# OPN Oracle API

Backend autoritativo Flask de OPN Oracle con identidad multi-tenant, sesiones Redis revocables,
CSRF para SPA JSON, Argon2id, RBAC, auditoría y administración de plataforma/tenant.

## Requisitos

- Python 3.11+
- `uv` 0.11+
- PostgreSQL 16+ y Redis 7+ para ejecución integrada

## Instalación y calidad

```bash
uv sync --frozen
make lint
make typecheck
make test
```

`make test` ejecuta la batería aislada sin cobertura agregada porque los flujos de sesión/RLS
solo son ejercitables con PostgreSQL y Redis reales. Con las variables de integración definidas,
`make test-coverage` ejecuta la suite completa y exige el umbral configurado del 85 %.

`uv.lock` es vinculante. Para actualizar dependencias de forma deliberada:

```bash
uv lock --upgrade
uv sync --frozen
```

## Configuración

```bash
cp .env.example .env
```

Sustituye todos los placeholders locales. La aplicación carga `.env` solo fuera de producción.
Producción exige un `SECRET_KEY` de al menos 32 caracteres, PostgreSQL, Redis y un
`FRONTEND_ORIGIN` HTTPS; si faltan, el proceso falla antes de servir tráfico.

Las credenciales pueden suministrarse mediante archivos montados fuera de la imagen usando la
variante `NOMBRE_FILE` con ruta absoluta. Se admite para `SECRET_KEY`, las URLs de PostgreSQL y
Redis/Celery, `METRICS_TOKEN`, `SMTP_PASSWORD`, `GRAPH_CLIENT_SECRET`, el keyring de integraciones
y las credenciales S3.
No configures simultáneamente `NOMBRE` y `NOMBRE_FILE`: la aplicación falla cerrada. Los archivos
no deben incluirse en Git y el usuario del contenedor API (UID/GID `10001`) necesita lectura; en el
host productivo se usarán ownership `10001:10001` y modo `0400`.

| Variable | Desarrollo | Producción |
|---|---|---|
| `APP_ENV` | `development` | `production` |
| `FLASK_DEBUG` | opcional | `false` |
| `SECRET_KEY` / `SECRET_KEY_FILE` | placeholder local | archivo secreto externo, 32+ caracteres |
| `DATABASE_URL` | PostgreSQL local | PostgreSQL privado |
| `DATABASE_MIGRATION_URL` | rol migrador separado | solo proceso de release/migración |
| `RLS_ENABLED` | `true` | obligatorio, `true` |
| `REDIS_URL` | Redis local | Redis privado/ACL |
| `SESSION_REDIS_URL` | DB lógica separada | obligatoria en fase de auth |
| `RATELIMIT_STORAGE_URL` | DB lógica separada | obligatoria en fase de auth |
| `SESSION_IDLE_MINUTES` / `SESSION_ABSOLUTE_HOURS` | `30` / `12` | política revisada |
| `SENSITIVE_REAUTH_MINUTES` | `10` | ventana de confirmación de contraseña |
| `MAIL_BACKEND` | `capture` | `smtp` o `graph` completamente configurado |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `MAIL_FROM` | local/capture | credenciales externas si se usa SMTP |
| `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`, `GRAPH_SENDER_MAILBOX` | vacío | registro Azure y buzón emisor si se usa Graph |
| `LOG_FORMAT` | `console` | `json` |
| `METRICS_ENABLED` / `METRICS_TOKEN` | `false` / vacío | red privada y token externo 32+ si se habilita |
| `HSTS_ENABLED` | `false` | solo `true` después de validar HTTPS/TLS exterior |
| `TRUSTED_PROXY_COUNT` | `0` | número exacto de proxies confiables |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | origen HTTPS canónico |
| `OPENAPI_ENABLED` | `true` | `false` salvo acceso protegido |
| `SQLALCHEMY_POOL_TIMEOUT_SECONDS` | `1.0` | deadline corto revisado |
| `DEPENDENCY_TIMEOUT_SECONDS` | `1.0` | connect/query/Redis timeout corto |
| `DOCUMENTS_ENABLED` | `true` | `false` hasta configurar storage y scanner |
| `DOCUMENT_STORAGE_BACKEND` / `DOCUMENT_LOCAL_ROOT` | `local` / `.oracle-storage` | `s3`; local no permitido con módulo activo |
| `DOCUMENT_MAX_BYTES` / `DOCUMENT_TENANT_QUOTA_BYTES` | 25 MiB / 1 GiB | límites revisados por tenant |
| `DOCUMENT_SCANNER_MODE` / `DOCUMENT_CLAMAV_*` | `noop` | `clamav` y endpoint privado obligatorio |
| `DOCUMENT_S3_*` / `DOCUMENT_S3_ALLOWED_HOSTS` | vacío | secreto externo y endpoint IP global fijado |
| `BACKUP_STORAGE_PATH` / `BACKUP_RETENTION_DAYS` | `/var/backups/opn-oracle` / `30` | catálogo superadmin; ejecución y filesystem pertenecen al agente root del host |

Las URLs se tratan como sensibles y no se imprimen. `TRUSTED_PROXY_COUNT=1` solo será válido
cuando Gunicorn esté directamente detrás del Nginx controlado; nunca se confían proxies de forma
automática.

Microsoft Graph usa OAuth 2.0 client credentials con el scope fijo
`https://graph.microsoft.com/.default` y `POST /v1.0/users/{buzón}/sendMail`. La aplicación Azure
necesita el permiso de aplicación `Mail.Send` con consentimiento de administrador y acceso al
buzón indicado en `GRAPH_SENDER_MAILBOX`. El secreto debe montarse mediante
`GRAPH_CLIENT_SECRET_FILE`; el identificador de objeto de la aplicación no es una variable de
runtime. Graph `sendMail` no garantiza deduplicación, por lo que Oracle conserva el control de
entrega ambigua y no reenvía automáticamente una solicitud cuyo resultado sea desconocido.
Invitaciones y restablecimientos se entregan exclusivamente mediante `BackgroundJob`/Celery. El
payload contiene solo IDs; el worker deriva el token de invitación mediante HMAC y nunca persiste
el token o la URL en los argumentos de cola. Si el broker falla tras el commit, el job queda en
`publish_pending` y `maintenance.dispatch_queued_jobs` lo reconcilia.

## Arranque local

Con PostgreSQL y Redis configurados en `.env`:

```bash
make migrate
make run
```

El servidor de Flask es solo para desarrollo. La forma equivalente a producción es:

```bash
make gunicorn
```

Rutas públicas de la fundación:

- `GET /health/live`: no llama a dependencias.
- `GET /health/ready`: prueba PostgreSQL y Redis con timeout corto.
- `GET /api/v1/meta`: metadatos públicos no sensibles.
- `GET /api/v1/openapi.json`: solo cuando OpenAPI está habilitado.
- `GET /api/v1/docs`: Swagger UI, solo cuando OpenAPI está habilitado.

Exporta el contrato reproducible con `make openapi`.

## Compose local

Desde la raíz del repositorio, define secretos locales fuera de Git:

```bash
export POSTGRES_ADMIN_PASSWORD='valor-admin-local'
export ORACLE_MIGRATOR_PASSWORD='valor-migrador-local'
export ORACLE_APP_PASSWORD='valor-runtime-local'
export SECRET_KEY='valor-local-de-32-caracteres-o-mas'
docker compose -f compose.dev.yml up --build
```

Los puertos 5432, 6379 y 8000 se enlazan exclusivamente a `127.0.0.1`. Compose aplica la
migración una sola vez al arrancar el servicio API. Esta configuración no es la topología de
producción.

Gunicorn no emite su access log porque la request line incluye query strings potencialmente
sensibles. Flask emite el evento de acceso autoritativo usando la plantilla de la ruta, nunca los
segmentos concretos, con request/correlation ID y redacción recursiva de campos estructurados.

`GET /internal/metrics` permanece oculto con 404 salvo que `METRICS_ENABLED=true` y se presente el
bearer `METRICS_TOKEN`. Expone etiquetas de ruta templada, clases de estado, latencia, fallos auth,
rate limit y pool; nunca IDs de tenant/usuario/recurso. En Gunicorn multi-worker debe agregarse cada
proceso o sustituirse este adapter por la plataforma elegida. HSTS no se activa automáticamente:
corresponde al edge tras verificar certificado, redirects y HTTPS estable.

## Identidad y sesiones

La web usa `opn_oracle_session`, una cookie opaca `HttpOnly`, `SameSite=Lax` y `Secure` en
producción. El contenido vive en Redis con msgpack; PostgreSQL conserva únicamente el registro
revocable y el hash del SID. Toda mutación exige el token obtenido en `GET /api/v1/auth/csrf`
mediante `X-CSRF-Token`. Login, reautenticación y cambios sensibles rotan el SID; la contraseña
se confirma de nuevo cuando vence `SENSITIVE_REAUTH_MINUTES`.

El primer superadmin se crea sin secretos en argumentos ni logs:

```bash
uv run flask --app opn_oracle.wsgi:app admin bootstrap-superadmin \
  --email admin@example.com --name "Administrador"
```

El comando solicita y confirma la contraseña sin eco. En producción requiere además
`--confirm-production` y confirmación interactiva.

## Migraciones

```bash
make migration  # genera una revisión tras modificar modelos
make migrate    # aplica revisiones pendientes
```

La revisión inicial crea `system_metadata`. La revisión de plataforma añade identidad, RBAC,
integraciones, auditoría y RLS. Alembic usa `DATABASE_MIGRATION_URL` con `NullPool`; la aplicación
usa `DATABASE_URL` y el rol runtime `NOBYPASSRLS`. Consulta
`docs/security/MULTITENANCY.md` para el flujo y troubleshooting.

## Integración local opt-in

La suite ordinaria no depende de servicios externos. Para probar migration round-trip y readiness
contra servicios reales, usa una base PostgreSQL desechable cuyo nombre contenga `test`:

```bash
export ORACLE_RUN_INTEGRATION=1
export TEST_DATABASE_URL='postgresql+psycopg://oracle_migrator:<migrator-password>@127.0.0.1:5432/opn_oracle_integration_test'
export TEST_RUNTIME_DATABASE_URL='postgresql+psycopg://oracle_app:<runtime-password>@127.0.0.1:5432/opn_oracle_integration_test'
export TEST_REDIS_URL='redis://127.0.0.1:6379/15'
uv run pytest -m integration --no-cov
```

El fixture aplica downgrade/upgrade y vuelve a `base` al finalizar. No apuntes este comando a una
base compartida o productiva.

## Runtime IA

La IA permanece deshabilitada por defecto y no incluye un proveedor externo. El mock determinista
solo se permite en desarrollo/CI. Configuración, guardrails, recuperación y evals se documentan en
[`docs/operations/AI_RUNTIME.md`](../../docs/operations/AI_RUNTIME.md).

## Documentos y búsqueda

La ingesta segura, formatos, provenance, búsqueda FTS, fencing de workers y retención se describen
en [`docs/operations/DOCUMENTS_EVIDENCE_SEARCH.md`](../../docs/operations/DOCUMENTS_EVIDENCE_SEARCH.md).
El noop local no afirma haber escaneado: un archivo solo se descarga con estado `ready` y scan
`clean`.
