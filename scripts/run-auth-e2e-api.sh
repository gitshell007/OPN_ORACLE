#!/usr/bin/env bash
set -euo pipefail

DB_NAME="opn_oracle_frontend_e2e_test"
REDIS_DB="14"
MIGRATION_URL="postgresql+psycopg://oracle_migrator@/${DB_NAME}?host=/tmp"
RUNTIME_URL="postgresql+psycopg://oracle_app@/${DB_NAME}?host=/tmp"
CREATED_MIGRATOR=0
CREATED_APP=0
SERVER_PID=""

cleanup() {
  if [ -n "$SERVER_PID" ]; then kill "$SERVER_PID" >/dev/null 2>&1 || true; wait "$SERVER_PID" >/dev/null 2>&1 || true; SERVER_PID=""; fi
  redis-cli -n "$REDIS_DB" flushdb >/dev/null 2>&1 || true
  psql -d postgres -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DB_NAME}' AND pid <> pg_backend_pid()" >/dev/null 2>&1 || true
  dropdb --if-exists "$DB_NAME" >/dev/null 2>&1 || true
  if [ "$CREATED_APP" = "1" ]; then psql -d postgres -v ON_ERROR_STOP=1 -c "DROP ROLE IF EXISTS oracle_app" >/dev/null 2>&1 || true; fi
  if [ "$CREATED_MIGRATOR" = "1" ]; then psql -d postgres -v ON_ERROR_STOP=1 -c "DROP ROLE IF EXISTS oracle_migrator" >/dev/null 2>&1 || true; fi
}
on_signal() { cleanup; exit 0; }
trap cleanup EXIT
trap on_signal INT TERM
dropdb --if-exists "$DB_NAME" >/dev/null 2>&1 || true
redis-cli -n "$REDIS_DB" flushdb >/dev/null 2>&1 || true
if ! psql -d postgres -Atqc "SELECT 1 FROM pg_roles WHERE rolname='oracle_migrator'" | grep -q 1; then psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE ROLE oracle_migrator LOGIN NOSUPERUSER BYPASSRLS" >/dev/null; CREATED_MIGRATOR=1; fi
if ! psql -d postgres -Atqc "SELECT 1 FROM pg_roles WHERE rolname='oracle_app'" | grep -q 1; then psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE ROLE oracle_app LOGIN NOSUPERUSER NOBYPASSRLS" >/dev/null; CREATED_APP=1; fi
createdb --owner oracle_migrator "$DB_NAME"
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
TENANT_ID=$(psql "$DB_NAME" -Atqc "SELECT id FROM tenants WHERE slug = 'asterion-e2e'")
uv run flask --app opn_oracle.wsgi:app seed-oracle-demo --tenant-id "$TENANT_ID" >/dev/null
export DATABASE_URL="$RUNTIME_URL"
uv run gunicorn --bind 127.0.0.1:5001 --workers 1 --access-logfile /dev/null opn_oracle.wsgi:app &
SERVER_PID=$!
wait "$SERVER_PID"
