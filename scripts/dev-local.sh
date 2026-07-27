#!/usr/bin/env bash
# Entorno de desarrollo local sin Docker.
#
# Usa PostgreSQL y Redis instalados con brew en lugar de contenedores: menos
# capas entre el código y el proceso, arranque en segundos y recarga en
# caliente tanto de la API como del frontend. Producción sigue siendo Docker
# (compose.prod.yml); esto es solo para desarrollar.
#
#   scripts/dev-local.sh setup   crea la base, migra y siembra datos de demo
#   scripts/dev-local.sh up      arranca API, worker, beat y frontend
#   scripts/dev-local.sh down    para todo lo que arrancó up
#   scripts/dev-local.sh status  qué está vivo y en qué puerto
#   scripts/dev-local.sh logs [api|worker|beat|web]
#   scripts/dev-local.sh psql    abre una consola SQL sobre la base de dev
#
# Las credenciales de aquí son locales y sin valor: la base solo escucha en
# 127.0.0.1. Nunca reutilices estos valores fuera de tu máquina.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME="$ROOT/.dev-local"
LOGS="$RUNTIME/logs"
PIDS="$RUNTIME/pids"

PG_BIN="${ORACLE_DEV_PG_BIN:-/opt/homebrew/opt/postgresql@17/bin}"
DB_NAME="${ORACLE_DEV_DB:-oracle_dev}"
DB_HOST="${ORACLE_DEV_DB_HOST:-127.0.0.1}"
DB_PORT="${ORACLE_DEV_DB_PORT:-5432}"
REDIS_HOST="${ORACLE_DEV_REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${ORACLE_DEV_REDIS_PORT:-6379}"
# 8010 y no 8000 a propósito: en esta máquina hay otros proyectos sirviendo en
# el 8000. macOS deja convivir un bind en 127.0.0.1 con otro en 0.0.0.0 del
# mismo puerto, así que la colisión no da error: da respuestas del proyecto
# equivocado, que es mucho peor de diagnosticar.
API_PORT="${ORACLE_DEV_API_PORT:-8010}"
WEB_PORT="${ORACLE_DEV_WEB_PORT:-3000}"

# Los roles son del clúster, no de la base: si cambias estas contraseñas
# rompes también el entorno de tests de integración, que usa los mismos roles.
MIGRATOR_PASSWORD="${ORACLE_MIGRATOR_PASSWORD:-ci-migrator-only}"
APP_PASSWORD="${ORACLE_APP_PASSWORD:-ci-app-only}"

DEV_TENANT_SLUG="${ORACLE_DEV_TENANT_SLUG:-desarrollo}"
DEV_TENANT_NAME="${ORACLE_DEV_TENANT_NAME:-Entorno de desarrollo}"
DEV_USER_EMAIL="${ORACLE_DEV_USER_EMAIL:-dev@opnconsultoria.com}"
DEV_USER_NAME="${ORACLE_DEV_USER_NAME:-Desarrollo Local}"

BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; RED=$'\033[31m'
YELLOW=$'\033[33m'; RESET=$'\033[0m'

info()  { printf '%s→%s %s\n' "$DIM" "$RESET" "$*"; }
ok()    { printf '%s✔%s %s\n' "$GREEN" "$RESET" "$*"; }
warn()  { printf '%s!%s %s\n' "$YELLOW" "$RESET" "$*"; }
fail()  { printf '%s✖%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

export_env() {
  export PATH="$PG_BIN:$PATH"
  export APP_ENV=development
  export FLASK_DEBUG=true
  export SECRET_KEY="${SECRET_KEY:-local-development-only-change-me-please}"
  export DATABASE_URL="postgresql+psycopg://oracle_app:${APP_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
  export DATABASE_MIGRATION_URL="postgresql+psycopg://oracle_migrator:${MIGRATOR_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
  # Bases de Redis 10-15: no pisan las que usan los tests (14) ni producción.
  export REDIS_URL="redis://${REDIS_HOST}:${REDIS_PORT}/10"
  export SESSION_REDIS_URL="redis://${REDIS_HOST}:${REDIS_PORT}/11"
  export RATELIMIT_STORAGE_URL="redis://${REDIS_HOST}:${REDIS_PORT}/12"
  export CELERY_BROKER_URL="redis://${REDIS_HOST}:${REDIS_PORT}/13"
  export CELERY_RESULT_BACKEND="redis://${REDIS_HOST}:${REDIS_PORT}/15"
  export DOCUMENT_LOCAL_ROOT="$RUNTIME/storage"
  export BACKUP_STORAGE_PATH="$RUNTIME/backups"
  export LOG_LEVEL="${LOG_LEVEL:-INFO}"
  export LOG_FORMAT=console
  export FRONTEND_ORIGIN="http://localhost:${WEB_PORT}"
  export OPENAPI_ENABLED=true
  export RLS_ENABLED=true
  export TRUSTED_PROXY_COUNT=0
  # Por defecto la IA va en mock: desarrollar no debe depender de las GPUs ni
  # gastar cuota. Exporta AI_MODE=signal antes de llamar al script para usar
  # la gobernanza real de Signal.
  export AI_MODE="${AI_MODE:-mock}"
  export AI_ENABLED="${AI_ENABLED:-true}"
  export SIGNAL_AVANZA_MODE="${SIGNAL_AVANZA_MODE:-mock}"
}

require_services() {
  command -v "$PG_BIN/psql" >/dev/null 2>&1 \
    || fail "No encuentro psql en $PG_BIN. Instala con: brew install postgresql@17"
  command -v redis-cli >/dev/null 2>&1 \
    || fail "No encuentro redis-cli. Instala con: brew install redis"
  "$PG_BIN/pg_isready" -h "$DB_HOST" -p "$DB_PORT" -q \
    || fail "PostgreSQL no responde en ${DB_HOST}:${DB_PORT}. Arranca con: brew services start postgresql@17"
  redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping >/dev/null 2>&1 \
    || fail "Redis no responde en ${REDIS_HOST}:${REDIS_PORT}. Arranca con: brew services start redis"
  ok "PostgreSQL y Redis responden."
}

flask_cli() { (cd "$ROOT/apps/api" && uv run flask --app opn_oracle.wsgi:app "$@"); }

cmd_setup() {
  export_env
  require_services
  mkdir -p "$LOGS" "$PIDS" "$RUNTIME/storage" "$RUNTIME/backups"

  if "$PG_BIN/psql" -d postgres -tAc \
      "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
    info "La base ${DB_NAME} ya existe."
  else
    "$PG_BIN/createdb" -O oracle_migrator "$DB_NAME"
    ok "Base ${DB_NAME} creada."
  fi

  # Solo permisos de esta base: no tocamos las contraseñas de los roles porque
  # son del clúster y las comparte el entorno de tests.
  "$PG_BIN/psql" -d "$DB_NAME" -v ON_ERROR_STOP=1 -q <<SQL
ALTER DATABASE "${DB_NAME}" OWNER TO oracle_migrator;
ALTER SCHEMA public OWNER TO oracle_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE "${DB_NAME}" TO oracle_app;
SQL
  ok "Propiedad y permisos ajustados."

  info "Aplicando migraciones…"
  flask_cli db upgrade >"$LOGS/setup-migrate.log" 2>&1 \
    || { tail -20 "$LOGS/setup-migrate.log"; fail "Fallaron las migraciones (log completo en $LOGS/setup-migrate.log)."; }
  ok "Esquema al día."

  local tenant_id
  tenant_id="$("$PG_BIN/psql" -d "$DB_NAME" -tAc \
    "SELECT id FROM tenants WHERE slug='${DEV_TENANT_SLUG}' LIMIT 1" 2>/dev/null || true)"
  if [ -z "$tenant_id" ]; then
    info "Creando tenant de desarrollo…"
    flask_cli create-dev-tenant \
      --slug "$DEV_TENANT_SLUG" --name "$DEV_TENANT_NAME" \
      --email "$DEV_USER_EMAIL" --display-name "$DEV_USER_NAME" \
      >"$LOGS/setup-tenant.log" 2>&1 \
      || { tail -20 "$LOGS/setup-tenant.log"; fail "No se pudo crear el tenant."; }
    tenant_id="$("$PG_BIN/psql" -d "$DB_NAME" -tAc \
      "SELECT id FROM tenants WHERE slug='${DEV_TENANT_SLUG}' LIMIT 1")"
    ok "Tenant ${DEV_TENANT_SLUG} creado: $tenant_id"
    printf '%s\n' "$DIM$(cat "$LOGS/setup-tenant.log")$RESET"
  else
    info "Tenant ${DEV_TENANT_SLUG} ya existe: $tenant_id"
  fi

  flask_cli seed-rbac --tenant-id "$tenant_id" >"$LOGS/setup-rbac.log" 2>&1 \
    || { tail -20 "$LOGS/setup-rbac.log"; fail "No se pudieron sembrar los roles."; }
  ok "Roles del sistema sembrados."

  if flask_cli seed-oracle-demo --tenant-id "$tenant_id" >"$LOGS/setup-demo.log" 2>&1; then
    ok "Expedientes de demostración sembrados."
  else
    warn "El seed de demo no se aplicó (log en $LOGS/setup-demo.log). El entorno sigue siendo usable."
  fi

  printf '\n%sListo.%s Arranca con: %sscripts/dev-local.sh up%s\n' \
    "$BOLD" "$RESET" "$BOLD" "$RESET"
  printf '%sTenant:%s %s\n' "$DIM" "$RESET" "$tenant_id"
  printf '%sUsuario invitado:%s %s (define su contraseña desde la invitación)\n' \
    "$DIM" "$RESET" "$DEV_USER_EMAIL"
}

pid_alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

port_free() {
  local port="$1"
  ! lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

require_free_port() {
  local port="$1" role="$2"
  port_free "$port" && return 0
  printf '%s✖%s El puerto %s (%s) ya está ocupado por:\n' "$RED" "$RESET" "$port" "$role" >&2
  lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print "   pid " $2 " " $1}' | sort -u >&2
  printf '   Cambia el puerto con ORACLE_DEV_%s_PORT=… o para ese proceso.\n' \
    "$(printf '%s' "$role" | tr '[:lower:]' '[:upper:]')" >&2
  exit 1
}

# Mata el proceso y su descendencia por parentesco. Deliberadamente NO se usa
# `kill -- -PGID`: en un shell sin control de trabajos los hijos heredan el
# grupo del script que los lanzó, así que señalar al grupo entero puede
# alcanzar procesos ajenos al entorno de desarrollo.
kill_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child"
  done
  kill -TERM "$pid" 2>/dev/null || true
}

start_process() {
  local name="$1"; shift
  local pid_file="$PIDS/$name.pid"
  if pid_alive "$pid_file"; then
    info "$name ya estaba corriendo (pid $(cat "$pid_file"))."
    return
  fi
  ( "$@" >"$LOGS/$name.log" 2>&1 & echo $! >"$pid_file" )
  sleep 1
  if pid_alive "$pid_file"; then
    ok "$name arrancado (pid $(cat "$pid_file"), log en .dev-local/logs/$name.log)."
  else
    tail -20 "$LOGS/$name.log" || true
    fail "$name no arrancó. Log completo en $LOGS/$name.log"
  fi
}

cmd_up() {
  export_env
  require_services
  mkdir -p "$LOGS" "$PIDS" "$RUNTIME/storage" "$RUNTIME/backups"

  "$PG_BIN/psql" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" \
    | grep -q 1 || fail "No existe la base ${DB_NAME}. Ejecuta primero: scripts/dev-local.sh setup"

  pid_alive "$PIDS/api.pid" || require_free_port "$API_PORT" api
  pid_alive "$PIDS/web.pid" || require_free_port "$WEB_PORT" web

  start_process api env FLASK_RUN_PORT="$API_PORT" \
    uv --directory "$ROOT/apps/api" run flask --app opn_oracle.wsgi:app \
    run --host 127.0.0.1 --port "$API_PORT" --reload

  # Un solo worker con todas las colas: en local no hace falta el aislamiento
  # por cola que sí tiene producción.
  start_process worker uv --directory "$ROOT/apps/api" run celery \
    -A opn_oracle.celery_entry:celery worker \
    -Q default,maintenance,signals,ai,documents,notifications \
    --loglevel=INFO --hostname=dev@%h --concurrency=2

  # --schedule fuera del árbol de fuentes: por defecto beat escribe
  # celerybeat-schedule.db en el directorio de trabajo y ensucia apps/api.
  start_process beat uv --directory "$ROOT/apps/api" run celery \
    -A opn_oracle.celery_entry:celery beat --loglevel=INFO \
    --schedule "$RUNTIME/celerybeat-schedule"

  start_process web env ORACLE_API_ORIGIN="http://127.0.0.1:${API_PORT}" \
    PORT="$WEB_PORT" npm --prefix "$ROOT" run dev

  printf '\n%sEntorno levantado.%s\n' "$BOLD" "$RESET"
  printf '  Frontend  http://localhost:%s\n' "$WEB_PORT"
  printf '  API       http://127.0.0.1:%s/health/live\n' "$API_PORT"
  printf '  OpenAPI   http://127.0.0.1:%s/docs\n' "$API_PORT"
  printf '\n%sLogs:%s scripts/dev-local.sh logs api    %sParar:%s scripts/dev-local.sh down\n' \
    "$DIM" "$RESET" "$DIM" "$RESET"
}

cmd_down() {
  local stopped=0
  for pid_file in "$PIDS"/*.pid; do
    [ -e "$pid_file" ] || continue
    local name pid
    name="$(basename "$pid_file" .pid)"
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      # uv y npm dejan hijos que sobreviven al padre: hay que bajar el árbol.
      kill_tree "$pid"
      ok "$name detenido."
      stopped=1
    fi
    rm -f "$pid_file"
  done
  [ "$stopped" -eq 1 ] || info "No había nada corriendo."
}

cmd_status() {
  local any=0
  for name in api worker beat web; do
    local pid_file="$PIDS/$name.pid"
    if pid_alive "$pid_file"; then
      ok "$name activo (pid $(cat "$pid_file"))"
      any=1
    else
      printf '%s·%s %s parado\n' "$DIM" "$RESET" "$name"
    fi
  done
  [ "$any" -eq 1 ] || return 0
  printf '\n'
  curl -fsS "http://127.0.0.1:${API_PORT}/health/live" >/dev/null 2>&1 \
    && ok "API responde en http://127.0.0.1:${API_PORT}" \
    || warn "La API no responde todavía en el puerto ${API_PORT}."
}

cmd_logs() {
  local name="${1:-api}"
  [ -f "$LOGS/$name.log" ] || fail "No hay log para '$name'. Opciones: api, worker, beat, web."
  tail -f "$LOGS/$name.log"
}

cmd_psql() {
  export_env
  PGPASSWORD="$MIGRATOR_PASSWORD" "$PG_BIN/psql" \
    -h "$DB_HOST" -p "$DB_PORT" -U oracle_migrator -d "$DB_NAME" "$@"
}

case "${1:-}" in
  setup)  shift; cmd_setup "$@" ;;
  up)     shift; cmd_up "$@" ;;
  down)   shift; cmd_down "$@" ;;
  status) shift; cmd_status "$@" ;;
  logs)   shift; cmd_logs "$@" ;;
  psql)   shift; cmd_psql "$@" ;;
  *)
    sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
