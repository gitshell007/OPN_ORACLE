#!/usr/bin/env bash
set -euo pipefail

DB_NAME="${E2E_DB_NAME:-opn_oracle_frontend_e2e_test}"
REDIS_DB="${E2E_REDIS_DB:-14}"
POSTGRES_HOST="${E2E_POSTGRES_HOST:-}"
POSTGRES_PORT="${E2E_POSTGRES_PORT:-5432}"
POSTGRES_USER="${E2E_POSTGRES_USER:-postgres}"
MIGRATOR_PASSWORD="${E2E_ORACLE_MIGRATOR_PASSWORD:-}"
APP_PASSWORD="${E2E_ORACLE_APP_PASSWORD:-}"
if [ -n "$POSTGRES_HOST" ]; then
  MIGRATION_URL="postgresql+psycopg://oracle_migrator:${MIGRATOR_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${DB_NAME}"
  RUNTIME_URL="postgresql+psycopg://oracle_app:${APP_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${DB_NAME}"
  PSQL_ADMIN=(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER")
  DROPDB_ADMIN=(dropdb -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER")
  CREATEDB_ADMIN=(createdb -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER")
else
  MIGRATION_URL="postgresql+psycopg://oracle_migrator@/${DB_NAME}?host=/tmp"
  RUNTIME_URL="postgresql+psycopg://oracle_app@/${DB_NAME}?host=/tmp"
  PSQL_ADMIN=(psql)
  DROPDB_ADMIN=(dropdb)
  CREATEDB_ADMIN=(createdb)
fi
CREATED_MIGRATOR=0
CREATED_APP=0
SERVER_PID=""

cleanup() {
  if [ -n "$SERVER_PID" ]; then kill "$SERVER_PID" >/dev/null 2>&1 || true; wait "$SERVER_PID" >/dev/null 2>&1 || true; SERVER_PID=""; fi
  redis-cli -n "$REDIS_DB" flushdb >/dev/null 2>&1 || true
  "${PSQL_ADMIN[@]}" -d postgres -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DB_NAME}' AND pid <> pg_backend_pid()" >/dev/null 2>&1 || true
  "${DROPDB_ADMIN[@]}" --if-exists "$DB_NAME" >/dev/null 2>&1 || true
  if [ "$CREATED_APP" = "1" ]; then "${PSQL_ADMIN[@]}" -d postgres -v ON_ERROR_STOP=1 -c "DROP ROLE IF EXISTS oracle_app" >/dev/null 2>&1 || true; fi
  if [ "$CREATED_MIGRATOR" = "1" ]; then "${PSQL_ADMIN[@]}" -d postgres -v ON_ERROR_STOP=1 -c "DROP ROLE IF EXISTS oracle_migrator" >/dev/null 2>&1 || true; fi
}
on_signal() { cleanup; exit 0; }
trap cleanup EXIT
trap on_signal INT TERM
if [ -n "$POSTGRES_HOST" ] && { [ -z "$MIGRATOR_PASSWORD" ] || [ -z "$APP_PASSWORD" ]; }; then
  echo "E2E_ORACLE_MIGRATOR_PASSWORD y E2E_ORACLE_APP_PASSWORD son obligatorias con E2E_POSTGRES_HOST." >&2
  exit 1
fi
"${DROPDB_ADMIN[@]}" --if-exists "$DB_NAME" >/dev/null 2>&1 || true
redis-cli -n "$REDIS_DB" flushdb >/dev/null 2>&1 || true
if ! "${PSQL_ADMIN[@]}" -d postgres -Atqc "SELECT 1 FROM pg_roles WHERE rolname='oracle_migrator'" | grep -q 1; then "${PSQL_ADMIN[@]}" -d postgres -v ON_ERROR_STOP=1 -c "CREATE ROLE oracle_migrator LOGIN NOSUPERUSER BYPASSRLS" >/dev/null; CREATED_MIGRATOR=1; fi
if ! "${PSQL_ADMIN[@]}" -d postgres -Atqc "SELECT 1 FROM pg_roles WHERE rolname='oracle_app'" | grep -q 1; then "${PSQL_ADMIN[@]}" -d postgres -v ON_ERROR_STOP=1 -c "CREATE ROLE oracle_app LOGIN NOSUPERUSER NOBYPASSRLS" >/dev/null; CREATED_APP=1; fi
if [ -n "$POSTGRES_HOST" ]; then
  "${PSQL_ADMIN[@]}" -d postgres -v ON_ERROR_STOP=1 -c "ALTER ROLE oracle_migrator PASSWORD '${MIGRATOR_PASSWORD}'" >/dev/null
  "${PSQL_ADMIN[@]}" -d postgres -v ON_ERROR_STOP=1 -c "ALTER ROLE oracle_app PASSWORD '${APP_PASSWORD}'" >/dev/null
fi
"${CREATEDB_ADMIN[@]}" --owner oracle_migrator "$DB_NAME"
redis-cli -n "$REDIS_DB" flushdb >/dev/null

export APP_ENV=test
export SECRET_KEY="frontend-e2e-only-secret-key-2026"
export DATABASE_MIGRATION_URL="$MIGRATION_URL"
export DATABASE_URL="$MIGRATION_URL"
export REDIS_URL="redis://127.0.0.1:6379/${REDIS_DB}"
export SESSION_REDIS_URL="$REDIS_URL"
export RATELIMIT_STORAGE_URL="$REDIS_URL"
export FRONTEND_ORIGIN="http://127.0.0.1:3000"
export RLS_ENABLED=1
export LOG_FORMAT=console
export TRUSTED_PROXY_COUNT=1

cd apps/api
uv run flask --app opn_oracle.wsgi:app db upgrade >/dev/null
uv run python tests/seed_frontend_e2e.py
if [ -n "$POSTGRES_HOST" ]; then
  TENANT_ID=$("${PSQL_ADMIN[@]}" -d "$DB_NAME" -Atqc "SELECT id FROM tenants WHERE slug = 'asterion-e2e'")
else
  TENANT_ID=$(psql "$DB_NAME" -Atqc "SELECT id FROM tenants WHERE slug = 'asterion-e2e'")
fi
uv run flask --app opn_oracle.wsgi:app seed-oracle-demo --tenant-id "$TENANT_ID" >/dev/null
export DATABASE_URL="$RUNTIME_URL"
uv run gunicorn --bind 127.0.0.1:5001 --workers 1 --access-logfile /dev/null opn_oracle.wsgi:app &
SERVER_PID=$!
wait "$SERVER_PID"
