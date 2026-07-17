#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV_BIN="${UV_BIN:-}"
PG_CONTAINER=""
REDIS_CONTAINER=""
UNIT_ONLY=0

usage() {
  cat <<'EOF'
Uso: scripts/api-test.sh [--unit]

  (sin flags)  Gate completo: lint, formato, tipos y pytest con cobertura, levantando
               PostgreSQL/Redis desechables. Es el único modo válido antes de un release.
               Falla cerrado si no hay entorno de integración: no da falso verde.

  --unit       Comprobación rápida sin Docker: lint, formato, tipos y solo los tests
               unitarios, sin umbral de cobertura. NO sustituye al gate completo, pero
               detecta la mayoría de las regresiones antes de entregar el trabajo.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --unit) UNIT_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; echo >&2; echo "Opción desconocida: $1" >&2; exit 64 ;;
  esac
done

cleanup() {
  if [[ -n "$PG_CONTAINER" ]]; then
    docker rm -f "$PG_CONTAINER" >/dev/null 2>&1 || true
  fi
  if [[ -n "$REDIS_CONTAINER" ]]; then
    docker rm -f "$REDIS_CONTAINER" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ -z "$UV_BIN" ]]; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then
    UV_BIN="$HOME/.local/bin/uv"
  elif command -v uv >/dev/null 2>&1; then
    UV_BIN="$(command -v uv)"
  fi
fi

if [[ -z "$UV_BIN" || ! -x "$UV_BIN" ]]; then
  cat >&2 <<'EOF'
uv no está disponible.

Instala uv o define UV_BIN con una ruta absoluta. En el entorno de agentes esperado:
  UV_BIN="$HOME/.local/bin/uv" scripts/api-test.sh
EOF
  exit 127
fi

cd "$ROOT_DIR/apps/api"
"$UV_BIN" sync --frozen
"$UV_BIN" lock --check
"$UV_BIN" run ruff check src tests migrations
"$UV_BIN" run ruff format --check src tests migrations
"$UV_BIN" run mypy src

if [[ "$UNIT_ONLY" == "1" ]]; then
  # Sin cobertura a propósito: el umbral de --cov-fail-under cuenta con los tests de
  # integración, así que exigirlo aquí haría fallar una tirada legítimamente parcial.
  UNIT_MIN_TESTS="${ORACLE_UNIT_MIN_TESTS:-284}"
  UNIT_OUTPUT="$(mktemp)"
  set +e
  "$UV_BIN" run pytest -m "not integration" --no-cov -rA | tee "$UNIT_OUTPUT"
  pytest_status=${PIPESTATUS[0]}
  set -e
  if [[ "$pytest_status" -ne 0 ]]; then
    rm -f "$UNIT_OUTPUT"
    exit "$pytest_status"
  fi
  "$UV_BIN" run python - "$UNIT_OUTPUT" "$UNIT_MIN_TESTS" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

output = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
minimum = int(sys.argv[2])
summary_lines = [
    line.strip()
    for line in output.splitlines()
    if " passed" in line or " skipped" in line or " failed" in line or " deselected" in line
]
summary = summary_lines[-1] if summary_lines else ""
passed_match = re.search(r"(\d+) passed", summary)
skipped_match = re.search(r"(\d+) skipped", summary)
passed = int(passed_match.group(1)) if passed_match else 0
skipped = int(skipped_match.group(1)) if skipped_match else 0
if skipped:
    print(
        f"ERROR: el modo unitario no puede ocultar tests: {skipped} skipped en {summary!r}.",
        file=sys.stderr,
    )
    sys.exit(1)
if passed < minimum:
    print(
        f"ERROR: el modo unitario ejecutó {passed} tests; mínimo protegido {minimum}.",
        file=sys.stderr,
    )
    sys.exit(1)
print(f"Guard unitario OK: {passed} tests ejecutados, 0 skipped.")
PY
  rm -f "$UNIT_OUTPUT"
  cat >&2 <<'EOF'

⚠  MODO PARCIAL: solo se han ejecutado los tests unitarios, sin cobertura.
   Los de integración (PostgreSQL, Redis, Celery, migraciones, RLS) NO se han ejecutado.
   Esto NO es el gate de release: antes de desplegar hace falta CI verde del SHA exacto.
EOF
  exit 0
fi

if [[ "${ORACLE_RUN_INTEGRATION:-}" != "1" ]]; then
  if ! command -v docker >/dev/null 2>&1; then
    cat >&2 <<'EOF'
No hay entorno de integración backend.

Para ejecutar el gate completo se necesita una de estas dos opciones:
  1) Docker disponible, para que scripts/api-test.sh levante PostgreSQL/Redis desechables.
  2) ORACLE_RUN_INTEGRATION=1 con TEST_DATABASE_URL, TEST_RUNTIME_DATABASE_URL y TEST_REDIS_URL.

No se ejecuta pytest sin integraciones porque eso saltaría tests y rompería el umbral de cobertura.

Si solo quieres comprobar tu trabajo antes de entregarlo, usa la comprobación rápida:
  scripts/api-test.sh --unit
Ejecuta los tests unitarios sin cobertura. No es el gate de release, pero es infinitamente
mejor que no ejecutar nada.
EOF
    exit 2
  fi

  PG_CONTAINER="opn-oracle-api-test-pg-$$"
  REDIS_CONTAINER="opn-oracle-api-test-redis-$$"
  POSTGRES_DB="${POSTGRES_DB:-oracle_test}"
  POSTGRES_USER="${POSTGRES_USER:-postgres}"
  PGPASSWORD="${PGPASSWORD:-ci-postgres-only}"
  ORACLE_MIGRATOR_PASSWORD="${ORACLE_MIGRATOR_PASSWORD:-ci-migrator-only}"
  ORACLE_APP_PASSWORD="${ORACLE_APP_PASSWORD:-ci-app-only}"
  export POSTGRES_DB POSTGRES_USER PGPASSWORD ORACLE_MIGRATOR_PASSWORD ORACLE_APP_PASSWORD

  docker run -d --rm \
    --name "$PG_CONTAINER" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$PGPASSWORD" \
    -p 127.0.0.1::5432 \
    postgres:17-bookworm >/dev/null
  docker run -d --rm \
    --name "$REDIS_CONTAINER" \
    -p 127.0.0.1::6379 \
    redis:7.4-bookworm >/dev/null

  for _ in {1..60}; do
    if docker exec "$PG_CONTAINER" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  docker exec "$PG_CONTAINER" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null

  for _ in {1..60}; do
    if docker exec "$REDIS_CONTAINER" redis-cli ping 2>/dev/null | grep -qx PONG; then
      break
    fi
    sleep 1
  done
  docker exec "$REDIS_CONTAINER" redis-cli ping | grep -qx PONG

  docker exec \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e ORACLE_MIGRATOR_PASSWORD="$ORACLE_MIGRATOR_PASSWORD" \
    -e ORACLE_APP_PASSWORD="$ORACLE_APP_PASSWORD" \
    "$PG_CONTAINER" sh -s <"$ROOT_DIR/infra/postgres/init/10-oracle-roles.sh"

  PGPORT="$(docker port "$PG_CONTAINER" 5432/tcp | sed -E 's/.*:([0-9]+)$/\1/')"
  REDISPORT="$(docker port "$REDIS_CONTAINER" 6379/tcp | sed -E 's/.*:([0-9]+)$/\1/')"
  export ORACLE_RUN_INTEGRATION=1
  TEST_DATABASE_URL="postgresql+psycopg://oracle_migrator:${ORACLE_MIGRATOR_PASSWORD}"
  TEST_DATABASE_URL="${TEST_DATABASE_URL}@127.0.0.1:${PGPORT}/${POSTGRES_DB}"
  TEST_RUNTIME_DATABASE_URL="postgresql+psycopg://oracle_app:${ORACLE_APP_PASSWORD}"
  TEST_RUNTIME_DATABASE_URL="${TEST_RUNTIME_DATABASE_URL}@127.0.0.1:${PGPORT}/${POSTGRES_DB}"
  export TEST_DATABASE_URL TEST_RUNTIME_DATABASE_URL
  export TEST_REDIS_URL="redis://127.0.0.1:${REDISPORT}/14"
elif [[ -z "${TEST_DATABASE_URL:-}" || -z "${TEST_RUNTIME_DATABASE_URL:-}" || -z "${TEST_REDIS_URL:-}" ]]; then
  cat >&2 <<'EOF'
ORACLE_RUN_INTEGRATION=1 exige TEST_DATABASE_URL, TEST_RUNTIME_DATABASE_URL y TEST_REDIS_URL.
EOF
  exit 2
fi

"$UV_BIN" run pytest
