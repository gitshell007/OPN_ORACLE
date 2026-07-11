# Aislamiento multi-tenant

**Estado:** implementado en la fase 03  
**Backend:** Flask + SQLAlchemy + PostgreSQL  
**Defensa:** scoping de repositorio y PostgreSQL RLS

## Regla de seguridad

Los recursos tenant-scoped no confían en `tenant_id` de body, query o cabecera. El backend lo
deriva de identidad y membership validadas y establece un `TenantContext`. Sin contexto, los
repositorios fallan antes de consultar y PostgreSQL devuelve cero filas o rechaza la escritura.

`Tenant`, `User`, `Permission`, `UserSettings`, `UserSession`, `PasswordResetToken` y
`SystemMetadata` son recursos globales de identidad/plataforma. Su acceso se limita mediante
servicios y privilegios. Las tablas de negocio y administración tenant-scoped usan RLS.

## Flujo por petición o job

```text
identidad autenticada
  -> app.actor_id (contexto pre-tenant)
  -> resolver memberships activas mediante función limitada
  -> validar tenant seleccionado y membership
  -> TenantContext(tenant_id, actor_id)
  -> comienza transacción SQLAlchemy
  -> set_config('app.tenant_id', ..., true)
  -> set_config('app.actor_id', ..., true)
  -> repositorio aplica filtro tenant_id
  -> RLS aplica USING y WITH CHECK
  -> commit/rollback limpia SET LOCAL
```

El tercer argumento `true` de `set_config` limita el valor a la transacción. No se usa
`SET SESSION`, por lo que devolver una conexión al pool no conserva el tenant. Los jobs Celery
deberán reconstruir el contexto a partir de IDs validados; nunca recibirán un objeto ORM ni una
cookie.

La `Session` guarda el fingerprint `(tenant_id, actor_id)` al comenzar la transacción. Los hooks
`do_orm_execute`, `before_flush` y `after_begin` —incluidos savepoints— rechazan cualquier cambio
de contexto hasta que termina la transacción raíz. El resolver trabaja primero bajo identidad
pre-tenant, exige una Session sin cambios pendientes y ejecuta `rollback()` tras el lookup antes
de devolver el contexto validado; nunca confirma trabajo ajeno.

## Roles de base de datos

| Rol | Uso | RLS | DDL |
|---|---|---|---|
| `oracle_migrator` | Alembic y ownership | `BYPASSRLS` | sí |
| `oracle_app` | API, workers y CLI ordinaria | `NOBYPASSRLS` | no |

`DATABASE_MIGRATION_URL` y `DATABASE_URL` deben ser credenciales distintas. Alembic crea una
conexión `NullPool` usando exclusivamente la primera. Gunicorn usa exclusivamente la segunda.
El migrador no debe servir tráfico.

El schema `public` mantiene las tablas para no mover la migración técnica existente, pero
`CREATE` está revocado a `PUBLIC` y a runtime. PostgreSQL y Redis permanecen en red privada.

## Tablas con RLS

- `workspaces`;
- `tenant_memberships`;
- `roles`, `role_permissions`, `membership_roles`;
- `invitations`;
- `audit_events`;
- `integration_connections`, `api_credentials`.

Cada una tiene `ENABLE ROW LEVEL SECURITY`, `FORCE ROW LEVEL SECURITY`, `USING` para lectura y
`WITH CHECK` para escritura. La función común convierte un GUC ausente o vacío en `NULL`; por
tanto la comparación nunca autoriza una fila.

`oracle_actor_memberships(uuid)` es una excepción estrecha para seleccionar tenant después de
autenticar: es `SECURITY DEFINER`, tiene `search_path` fijo, exige que el argumento coincida con
`app.actor_id` y devuelve solo ID, slug, nombre y estado. Su owner migrador debe conservar
`BYPASSRLS`; runtime no lo tiene.

## Superadmin

No existe una policy RLS que permita leer todos los tenants y no se usa
`app.is_platform_admin`. El acceso de plataforma debe validar el rol global, exigir tenant
objetivo y motivo, abrir un contexto limitado a ese tenant y registrar auditoría. La fase de
autenticación añadirá el flujo público y fresh-login; esta fase no expone rutas. La primitiva
actual solo admite un `User` activo con `platform_role=super_admin`, exige una Session limpia,
termina la lectura pre-tenant mediante rollback y confirma deliberadamente el `AuditEvent` antes
de devolver el contexto autorizado.

## RBAC y constraints

Los permisos son claves globales estables. Cada tenant recibe seis roles de sistema:
`owner`, `admin`, `editor`, `analyst`, `viewer` y `auditor`. El seed es idempotente. Roles y
memberships se vinculan con foreign keys compuestas que incluyen `tenant_id`; no se puede asignar
un rol ni una credencial de integración de otro tenant. Un trigger impide que runtime borre o
degrade roles de sistema.

`AuditEvent` es append-only para runtime. Invitaciones, resets y sesiones guardan únicamente
SHA-256 del valor opaco aleatorio. Las credenciales de integración guardan ciphertext, nonce y
versión de clave; la clave de cifrado debe residir fuera de PostgreSQL.

## Desarrollo y pruebas

Compose requiere valores locales separados:

```bash
export POSTGRES_ADMIN_PASSWORD='...'
export ORACLE_MIGRATOR_PASSWORD='...'
export ORACLE_APP_PASSWORD='...'
export SECRET_KEY='...'
docker compose -f compose.dev.yml up --build
```

La suite RLS real exige una base desechable y dos DSN:

```bash
ORACLE_RUN_INTEGRATION=1 \
TEST_DATABASE_URL='postgresql+psycopg://oracle_migrator:<migrator-password>@127.0.0.1:5432/opn_oracle_phase03_test' \
TEST_RUNTIME_DATABASE_URL='postgresql+psycopg://oracle_app:<runtime-password>@127.0.0.1:5432/opn_oracle_phase03_test' \
TEST_REDIS_URL='redis://127.0.0.1:6379/15' \
uv run pytest -m integration --no-cov
```

Los tests verifican aislamiento A/B, escritura cruzada, ausencia de contexto, reutilización de
pool, privilegios de roles, función pre-tenant, email CITEXT, audit append-only, seed RBAC y
constraints compuestas.

## Troubleshooting

- **Una consulta devuelve cero filas:** confirmar que la transacción comenzó dentro de
  `tenant_context` y consultar `current_setting('app.tenant_id', true)` en una sesión de prueba.
- **El valor aparece en otra petición:** buscar `SET SESSION`; está prohibido. Verificar que la
  transacción finaliza antes de devolver conexión al pool.
- **Alembic falla por permisos:** confirmar que usa `DATABASE_MIGRATION_URL`, no `DATABASE_URL`, y
  que el rol migrador posee schema/objetos.
- **La función de memberships devuelve cero:** confirmar `app.actor_id`, owner de la función,
  `SECURITY DEFINER`, `search_path` fijo y `rolbypassrls` del migrador.
- **Un modelo nuevo no queda aislado:** no desplegarlo hasta añadir `tenant_id`, policy, grants y
  tests negativos de IDOR/RLS en la misma migración.

## Limitaciones conscientes

- Las rutas de login, invitación, reset, selección de tenant y superadmin pertenecen a la fase 04.
- No hay roles custom públicos todavía; la estructura los permite, pero el flujo queda en P1.
- La política de retención/IP de sesiones y auditoría debe cerrarse antes de producción.
- Las credenciales se modelan cifradas, pero el servicio KMS/envelope encryption se implementará
  con las integraciones.
- Los grants runtime sobre tablas globales de identidad siguen siendo amplios para el bootstrap.
  La fase 04 debe revisarlos tabla por tabla y sustituir DML genérico por servicios de auth antes
  de exponer login o administración.
