#!/usr/bin/env bash
set -Eeuo pipefail

umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[[ "${1:-}" == "--process-one" && $# -eq 1 ]] || { echo "Uso: $0 --process-one" >&2; exit 2; }
[[ $EUID -eq 0 ]] || { echo "Debe ejecutarse como root." >&2; exit 2; }

env_file="${ORACLE_ENV_FILE:-/etc/opn-oracle/oracle.env}"
release_dir="${ORACLE_RELEASE_DIR:-/opt/opn-oracle/current}"
backup_root="${ORACLE_BACKUP_ROOT:-/var/backups/opn-oracle}"
worker_id="${ORACLE_BACKUP_WORKER_ID:-$(hostname -s)-backup-agent}"
[[ "$worker_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{2,99}$ ]] || { echo "worker-id inseguro." >&2; exit 2; }
release_dir="$(readlink -f "$release_dir")"
[[ -f "$env_file" && ! -L "$env_file" && "$release_dir" == /opt/opn-oracle/releases/* && -d "$release_dir" ]] || {
  echo "Configuración/release inseguro o ausente." >&2; exit 2;
}
[[ "$backup_root" == /* && -d "$backup_root" && ! -L "$backup_root" ]] || {
  echo "Backup root inseguro o ausente." >&2; exit 2;
}
compose=(docker compose --env-file "$env_file" -f "$release_dir/compose.prod.yml")
export ORACLE_SECRETS_DIR="${ORACLE_SECRETS_DIR:-/etc/opn-oracle/secrets}"
"${compose[@]}" config --quiet
"${compose[@]}" ps --status running --services | grep -qx api || { echo "API no disponible." >&2; exit 75; }

agent_cli() { "${compose[@]}" exec -T api flask --app opn_oracle.wsgi:app backup-agent "$@"; }
expiration_dir="$backup_root/.pending-expirations"
mkdir -p "$expiration_dir"
chmod 0700 "$expiration_dir"
for pending_expirations in "$expiration_dir"/*.names; do
  [[ -e "$pending_expirations" ]] || break
  [[ -f "$pending_expirations" && ! -L "$pending_expirations" ]] || {
    echo "Ledger de expiración inseguro: $pending_expirations" >&2; exit 1;
  }
  while IFS= read -r expired_name; do
    [[ "$expired_name" =~ ^[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || {
      echo "Nombre inválido en ledger de expiración." >&2; exit 1;
    }
    agent_cli mark-expired --backup-name "$expired_name"
  done < "$pending_expirations"
  rm -f -- "$pending_expirations"
done
claim="$(agent_cli claim-next --worker-id "$worker_id")"
operation_id="$(printf '%s' "$claim" | sed -n 's/.*"operation_id":"\([0-9a-f-]*\)".*/\1/p')"
operation_type="$(printf '%s' "$claim" | sed -n 's/.*"operation_type":"\([a-z_]*\)".*/\1/p')"
[[ -n "$operation_id" ]] || { echo "No hay operaciones de backup pendientes."; exit 0; }
[[ "$operation_id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || {
  echo "Respuesta de claim inválida." >&2; exit 1;
}
case "$operation_type" in
  manual_backup) origin="manual" ;;
  scheduled_backup) origin="scheduled" ;;
  *) echo "El agente automático rechaza operation_type=$operation_type." >&2; exit 1 ;;
esac

output=""
metadata="$(mktemp "$backup_root/.artifact.XXXXXX.json")"
rm -f -- "$metadata"
expired_names="$expiration_dir/$operation_id.names"
[[ ! -e "$expired_names" ]] || { echo "Ya existe el ledger de esta operación." >&2; exit 1; }
trap 'rm -f -- "${metadata:-}"' EXIT INT TERM
if ! output="$(ORACLE_ENV_FILE="$env_file" ORACLE_RELEASE_DIR="$release_dir" \
  ORACLE_ARTIFACT_JSON_OUTPUT="$metadata" \
  ORACLE_EXPIRED_NAMES_OUTPUT="$expired_names" \
  "$release_dir/scripts/backup-maintenance.sh" --create --origin "$origin" 2>&1)"; then
  agent_cli complete --operation-id "$operation_id" --worker-id "$worker_id" --status failed \
    --error-code backup_failed --error-message "Backup o verificación aislada falló; consultar journal del host."
  printf '%s\n' "$output" >&2
  exit 1
fi
[[ "$metadata" == "$backup_root"/.artifact.*.json && -f "$metadata" && ! -L "$metadata" ]] || {
  agent_cli complete --operation-id "$operation_id" --worker-id "$worker_id" --status failed \
    --error-code artifact_metadata_missing --error-message "No se generó metadata segura del artefacto."
  exit 1
}
while IFS= read -r expired_name; do
  [[ "$expired_name" =~ ^[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || {
    agent_cli complete --operation-id "$operation_id" --worker-id "$worker_id" --status failed \
      --error-code retention_metadata_invalid --error-message "La rotación produjo metadata inválida."
    exit 1
  }
  agent_cli mark-expired --backup-name "$expired_name"
done < "$expired_names"
rm -f -- "$expired_names"
agent_cli complete --operation-id "$operation_id" --worker-id "$worker_id" --status succeeded \
  --artifact-json-stdin < "$metadata"
printf '%s\n' "$output"
