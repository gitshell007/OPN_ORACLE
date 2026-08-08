# CI de OPN Oracle

Fuente del workflow: `.github/workflows/ci.yml`.  
Puertas frontend alineadas con `infra/native-dev/build-release.sh`.

## Qué valida cada trigger

| Trigger | Cuándo | Jobs | Qué acredita | Qué **no** acredita |
|---|---|---|---|---|
| `pull_request` → `master` | PR hacia tronco | frontend, backend (integración), frontend-e2e, security/images/SBOM | El SHA del PR es verde en runner efímero de GitHub | Despliegue, SHA activo en un host, Signal remoto, Oracle Dev |
| `push` → `oracle-dev` | Cada push a la rama de releases nativos | frontend (5 puertas), backend (Ruff, mypy, **pytest completo con integración**) | El commit de `oracle-dev` pasa las puertas de release-critical en runner efímero | Activación de release, smoke post-deploy, Signal, estado del host `oracle-dev` |
| `workflow_dispatch` | Manual | Matriz completa (como PR) | Validación completa a demanda | Idem: no es despliegue |

### Puertas frontend (las cinco de `build-release.sh`)

```text
npm run lint
npm run typecheck
npm run test -- --run
npm run api:client:check
npm run build
```

### Puertas backend (job `backend`)

- `uv lock --check`
- `uv run ruff check src tests migrations`
- `uv run ruff format --check src tests migrations`
- `uv run mypy src`
- `uv run pytest -vv --durations=40` con cobertura (`cov-fail-under=84` en `apps/api/pyproject.toml`)
- Familia de informes en dos órdenes (aislamiento)
- `flask db upgrade` + `flask db check` sobre la base efímera

`ORACLE_RUN_INTEGRATION=1` está activo. **No** se usa `-m "not integration"` ni se
excluyen módulos de integración. La suite de integración requiere PostgreSQL y
Redis **efímeros del runner**.

## Servicios efímeros (solo runner)

Declarados en el job `backend` (y E2E cuando corre):

| Variable | Valor CI (ejemplo) | Rol |
|---|---|---|
| `TEST_DATABASE_URL` | `postgresql+psycopg://oracle_migrator:ci-migrator-only@127.0.0.1:5432/oracle_test` | Migraciones / fixture |
| `TEST_RUNTIME_DATABASE_URL` | `postgresql+psycopg://oracle_app:ci-app-only@127.0.0.1:5432/oracle_test` | Runtime con RLS |
| `TEST_REDIS_URL` | `redis://127.0.0.1:6379/14` | Sesiones / rate limit / colas de test |
| `ORACLE_RUN_INTEGRATION` | `1` | Habilita tests `integration` |

- Imagen Postgres: `postgres:17-bookworm`, base `oracle_test`.
- Imagen Redis: `redis:7.4-bookworm`.
- Roles locales vía `infra/postgres/init/10-oracle-roles.sh`.

**Prohibido** apuntar estas variables a Oracle Dev, producción o cualquier host
compartido: el fixture puede hacer `downgrade base` + `upgrade` + `flushdb`.

## Concurrency

- Grupo: `ci-<workflow>-<ref>`.
- `cancel-in-progress: true` solo en `push` y `workflow_dispatch` (cancela
  ejecuciones obsoletas de la misma rama, p. ej. pushes sucesivos a `oracle-dev`).
- En `pull_request` a `master` **no** se cancela en progreso: un push intermedio
  al PR no aborta la corrida que ya estaba validando un SHA anterior del PR
  como si fuera un simple “latest only” agresivo sobre el tronco.

## Reparto de coste (oracle-dev push)

En **push a `oracle-dev`** se omiten deliberadamente:

- Playwright E2E (`frontend-e2e`)
- Trivy / Syft / scans de imágenes (`security-and-images`)

Motivo: la vía de release nativo necesita, en cada push, las cinco puertas
frontend + **integración real** del API; E2E y SBOM ya corren en PR→`master` y
en `workflow_dispatch`. Si se necesita la matriz completa sobre un SHA de
`oracle-dev`, usar **Run workflow** (dispatch).

## Invariantes del workflow

Script local: `scripts/check-ci-workflow.sh`.

Comprueba, entre otras:

- existe `push.branches: oracle-dev` y se conserva `pull_request` → `master`;
- las cinco puertas frontend aparecen en el job frontend;
- el job backend declara `ORACLE_RUN_INTEGRATION=1` y las tres URLs `TEST_*`;
- el `pytest` principal **no** excluye integración ni baja cobertura;
- no hay hosts remotos de Oracle Dev en las URLs de test.

## Smoke post-despliegue (otro gate)

Tras `build-release.sh` + `activate-release.sh` en el host, el smoke operativo
sigue el runbook `DEV_NATIVE_DEPLOY.md`. CI verde **no** sustituye readiness
HTTPS, workers ni comprobación de integración Oracle↔Signal en el entorno real.
