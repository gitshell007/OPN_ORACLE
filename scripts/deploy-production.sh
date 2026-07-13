#!/usr/bin/env bash
set -euo pipefail

mode="${1:-}"
if [[ "$mode" != "--apply-authorized-stage-b" && \
      "$mode" != "--bootstrap-authorized-empty" ]]; then
  echo "Modo seguro: no se ha aplicado nada." >&2
  echo "Bootstrap vacío: $0 --bootstrap-authorized-empty" >&2
  echo "Upgrade rápido: ORACLE_BACKUP_MANIFEST=... ORACLE_BACKUP_RESTORE_EVIDENCE=... $0 --apply-authorized-stage-b" >&2
  echo "Upgrade estricto: ORACLE_REQUIRE_OFFSITE_RECEIPT=1 ORACLE_BACKUP_OFFSITE_RECEIPT=... ..." >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${ORACLE_ENV_FILE:-/etc/opn-oracle/oracle.env}"
secrets_dir="${ORACLE_SECRETS_DIR:-/etc/opn-oracle/secrets}"
backup_manifest="${ORACLE_BACKUP_MANIFEST:-}"
backup_evidence="${ORACLE_BACKUP_RESTORE_EVIDENCE:-}"
offsite_receipt="${ORACLE_BACKUP_OFFSITE_RECEIPT:-}"
require_offsite_receipt="${ORACLE_REQUIRE_OFFSITE_RECEIPT:-0}"

if [[ "$require_offsite_receipt" != "0" && "$require_offsite_receipt" != "1" ]]; then
  echo "ORACLE_REQUIRE_OFFSITE_RECEIPT solo admite 0 o 1." >&2
  exit 2
fi

for command_name in docker curl; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Falta el comando requerido: $command_name" >&2
    exit 2
  }
done
docker compose version >/dev/null

if [[ ! -r "$env_file" ]]; then
  echo "No se puede leer ORACLE_ENV_FILE." >&2
  exit 2
fi
required_secrets=(
  postgres_admin_password postgres_migrator_password postgres_app_password redis_password
  oracle_secret_key oracle_database_url oracle_database_migration_url oracle_redis_url
  oracle_session_redis_url oracle_ratelimit_redis_url oracle_celery_broker_url
  oracle_celery_result_url oracle_graph_client_secret
  oracle_signal_ai_api_key
)
for secret_name in "${required_secrets[@]}"; do
  if [[ ! -s "$secrets_dir/$secret_name" ]]; then
    echo "Falta un secret file requerido: $secret_name" >&2
    exit 2
  fi
done

compose=(docker compose --env-file "$env_file" -f "$repo_root/compose.prod.yml")
export ORACLE_SECRETS_DIR="$secrets_dir"

"${compose[@]}" config --quiet

postgres_volume="opn-oracle-prod_oracle_postgres_data"
if [[ "$mode" == "--bootstrap-authorized-empty" ]]; then
  if docker volume inspect "$postgres_volume" >/dev/null 2>&1; then
    if ! "${compose[@]}" ps --status running --services | grep -qx postgres; then
      echo "Bootstrap rechazado: existe volumen PostgreSQL sin servicio sano verificable." >&2
      exit 2
    fi
    table_count="$("${compose[@]}" exec -T -u postgres postgres psql \
      -U postgres -d opn_oracle -Atqc \
      "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p') AND n.nspname NOT IN ('pg_catalog','information_schema');")"
    if [[ "$table_count" != "0" ]]; then
      echo "Bootstrap rechazado: el volumen PostgreSQL ya contiene esquema de aplicación." >&2
      exit 2
    fi
  fi
else
  for gate_file in "$backup_manifest" "$backup_evidence"; do
    if [[ -z "$gate_file" || ! -f "$gate_file" || ! -r "$gate_file" || -L "$gate_file" ]]; then
      echo "Upgrade rechazado: falta backup local o evidencia de restore válida." >&2
      exit 2
    fi
  done
  if [[ "$require_offsite_receipt" == "1" || -n "$offsite_receipt" ]]; then
    if [[ -z "$offsite_receipt" || ! -f "$offsite_receipt" || ! -r "$offsite_receipt" || -L "$offsite_receipt" ]]; then
      echo "Upgrade rechazado: falta receipt off-host válido en modo estricto." >&2
      exit 2
    fi
  fi
  "$repo_root/scripts/restore-test-production.sh" \
    --check-evidence "$backup_manifest" "$backup_evidence"
fi

"${compose[@]}" build --pull
"${compose[@]}" pull postgres redis

postgres_uid="$(docker run --rm --entrypoint id postgres:17-bookworm -u postgres)"
postgres_gid="$(docker run --rm --entrypoint id postgres:17-bookworm -g postgres)"

check_secret_metadata() {
  secret_name="$1"
  expected_uid="$2"
  expected_gid="$3"
  actual_uid="$(stat -c '%u' "$secrets_dir/$secret_name")"
  actual_gid="$(stat -c '%g' "$secrets_dir/$secret_name")"
  actual_mode="$(stat -c '%a' "$secrets_dir/$secret_name")"
  if [[ "$actual_uid" != "$expected_uid" || "$actual_gid" != "$expected_gid" || \
        "$actual_mode" != "400" ]]; then
    echo "Ownership/modo inseguro o ilegible en secret file: $secret_name" >&2
    exit 2
  fi
}

check_secret_metadata postgres_admin_password 0 0
check_secret_metadata redis_password 0 0
check_secret_metadata postgres_migrator_password "$postgres_uid" "$postgres_gid"
check_secret_metadata postgres_app_password "$postgres_uid" "$postgres_gid"
for secret_name in oracle_secret_key oracle_database_url oracle_database_migration_url \
  oracle_redis_url oracle_session_redis_url oracle_ratelimit_redis_url \
  oracle_celery_broker_url oracle_celery_result_url oracle_graph_client_secret; do
  check_secret_metadata "$secret_name" 10001 10001
done
check_secret_metadata oracle_signal_ai_api_key 10001 10001

"${compose[@]}" up -d --wait --wait-timeout 120 postgres redis
"${compose[@]}" --profile release run --rm migrate
"${compose[@]}" up -d beat
"${compose[@]}" up -d --wait --wait-timeout 180 api worker-core web
beat_count="$("${compose[@]}" ps --status running --services | grep -xc beat || true)"
if [[ "$beat_count" != "1" ]]; then
  echo "Se esperaba un único servicio beat activo; encontrados: $beat_count" >&2
  exit 1
fi
if ! "${compose[@]}" exec -T worker-core \
  celery -A opn_oracle.celery_entry:celery inspect ping --timeout 10 | grep pong >/dev/null; then
  echo "El worker Celery no responde al ping después del arranque." >&2
  exit 1
fi
"${compose[@]}" ps

ALLOW_HTTP_SMOKE=1 ORACLE_API_BASE_URL=http://127.0.0.1:8000 \
  "$repo_root/scripts/smoke-production.sh" http://127.0.0.1:3000

echo "Stack de aplicación listo en loopback. Nginx/TLS y el smoke HTTPS son pasos separados."
