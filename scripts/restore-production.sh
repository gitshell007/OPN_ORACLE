#!/usr/bin/env bash
set -Eeuo pipefail

umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

usage() {
  cat >&2 <<'EOF'
Uso: restore-production.sh --operation-id UUID --manifest /var/backups/opn-oracle/ID/MANIFEST.txt

Solo root interactivo. Crea y verifica un backup previo, restaura en una base nueva,
valida ACL/RLS/owners y hace swap conservando la base anterior. Nunca ejecuta DROP.
EOF
}

[[ "${1:-}" == "--operation-id" && "${3:-}" == "--manifest" && $# -eq 4 ]] || { usage; exit 2; }
operation_id="$2"
manifest="$4"
[[ $EUID -eq 0 && -t 0 && -t 1 ]] || { echo "Restore exige root y una TTY interactiva." >&2; exit 2; }
[[ "$operation_id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || exit 2

env_file="${ORACLE_ENV_FILE:-/etc/opn-oracle/oracle.env}"
backup_root="${ORACLE_BACKUP_ROOT:-/var/backups/opn-oracle}"
release_dir="$(readlink -f "${ORACLE_RELEASE_DIR:-/opt/opn-oracle/current}")"
evidence_root="${ORACLE_RESTORE_EVIDENCE_ROOT:-$backup_root/restore-evidence}"
[[ -f "$env_file" && ! -L "$env_file" && "$release_dir" == /opt/opn-oracle/releases/* && -d "$release_dir" ]] || exit 2
manifest="$(readlink -f "$manifest")"
[[ "$manifest" == "$backup_root"/*/MANIFEST.txt && -f "$manifest" && ! -L "$manifest" ]] || {
  echo "Manifest fuera del repositorio permitido." >&2; exit 2;
}
for command_name in docker flock sha256sum awk grep date readlink; do
  command -v "$command_name" >/dev/null || { echo "Falta $command_name." >&2; exit 2; }
done

export ORACLE_SECRETS_DIR="${ORACLE_SECRETS_DIR:-/etc/opn-oracle/secrets}"
compose=(docker compose --env-file "$env_file" -f "$release_dir/compose.prod.yml")
"${compose[@]}" config --quiet
worker_id="${ORACLE_BACKUP_WORKER_ID:-$(hostname -s)-backup-agent}"
[[ "$worker_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{2,99}$ ]] || exit 2
agent_cli() { "${compose[@]}" exec -T api flask --app opn_oracle.wsgi:app backup-agent "$@"; }
claimed=false
operation_done=false
swapped=false
metadata=""
acl_check=""

finalize_on_exit() {
  local status=$?
  trap - EXIT
  if ((status != 0)) && [[ "$swapped" == true ]] && declare -F rollback_swap >/dev/null; then
    rollback_swap
  fi
  if ((status != 0)) && [[ "$claimed" == true && "$operation_done" == false ]]; then
    agent_cli complete --operation-id "$operation_id" --worker-id "$worker_id" --status failed \
      --error-code restore_failed \
      --error-message "Restore productivo falló; consultar journal y evidencia del host." >/dev/null 2>&1 || true
  fi
  rm -f -- "${metadata:-}" "${acl_check:-}"
  exit "$status"
}
trap finalize_on_exit EXIT INT TERM
exec 9>/run/lock/opn-oracle-backup.lock
flock -n 9 || { echo "Ya existe una operación de backup/restore." >&2; exit 75; }

value() { awk -F= -v wanted="$2" '$1==wanted {if(++n>1) exit 3; print substr($0,index($0,"=")+1)} END{if(n!=1)exit 4}' "$1"; }
backup_id="$(value "$manifest" backup_id)"
dump_sha="$(value "$manifest" dump_sha256)"
dump_acl="$(value "$manifest" dump_acl)" || { echo "Este backup no preserva ACL; restore productivo rechazado." >&2; exit 2; }
[[ "$dump_acl" == preserved && "$(basename "$(dirname "$manifest")")" == "$backup_id" ]] || exit 2
dump="$(dirname "$manifest")/database.dump"
(cd "$(dirname "$manifest")" && sha256sum --check --strict ARTIFACT_CHECKSUMS.sha256 >/dev/null)
acl_check="$(mktemp "$backup_root/.acl-check.XXXXXX.sql")"
"${compose[@]}" exec -T -u postgres postgres pg_restore --schema-only --no-owner --file=- \
  < "$dump" > "$acl_check"
grep -Eq 'GRANT .* TO oracle_app;' "$acl_check" || {
  echo "El dump no contiene ACL para oracle_app." >&2; exit 1;
}
rm -f -- "$acl_check"
acl_check=""

evidence="$evidence_root/${backup_id}.RESTORE_EVIDENCE.txt"
if [[ -f "$evidence" ]]; then
  "$release_dir/scripts/restore-test-production.sh" --check-evidence "$manifest" "$evidence"
else
  ORACLE_RESTORE_EVIDENCE_ROOT="$evidence_root" "$release_dir/scripts/restore-test-production.sh" --verify-isolated "$manifest"
fi

phrase="RECUPERAR $operation_id $backup_id"
printf '\nATENCIÓN: se abrirá una ventana de mantenimiento y se intercambiará la base.\n'
printf 'La base anterior se conservará intacta para rollback.\nEscribe exactamente:\n%s\n> ' "$phrase"
IFS= read -r confirmation
[[ "$confirmation" == "$phrase" ]] || { echo "Confirmación incorrecta; cancelado." >&2; exit 2; }

claim="$(printf 'y\n' | "${compose[@]}" exec -T api flask --app opn_oracle.wsgi:app \
  backup-agent claim-restore \
  --operation-id "$operation_id" --worker-id "$worker_id" --confirm-production)"
claimed=true
claim_operation="$(printf '%s' "$claim" | sed -n 's/.*"operation_id":"\([0-9a-f-]*\)".*/\1/p')"
claim_name="$(printf '%s' "$claim" | sed -n 's/.*"backup_name":"\([A-Za-z0-9._-]*\)".*/\1/p')"
claim_sha="$(printf '%s' "$claim" | sed -n 's/.*"sha256":"\([0-9a-f]*\)".*/\1/p')"
[[ "$claim_operation" == "$operation_id" && "$claim_name" == "$backup_id" && "$claim_sha" == "$dump_sha" ]] || {
  echo "La operación aprobada no corresponde exactamente al manifest seleccionado." >&2; exit 1;
}
metadata="$(mktemp "$backup_root/.artifact.pre-restore.XXXXXX.json")"
rm -f "$metadata"
echo "Creando backup previo obligatorio..."
ORACLE_ARTIFACT_JSON_OUTPUT="$metadata" ORACLE_ENV_FILE="$env_file" ORACLE_RELEASE_DIR="$release_dir" \
  ORACLE_BACKUP_ROOT="$backup_root" ORACLE_SKIP_PRUNE=1 \
  "$release_dir/scripts/backup-maintenance.sh" --create --origin manual
rm -f "$metadata"

stamp="$(date -u +%Y%m%d%H%M%S)"
new_db="opn_oracle_restore_$stamp"
old_db="opn_oracle_before_$stamp"
failed_db="opn_oracle_failed_$stamp"
postgres() { "${compose[@]}" exec -T -u postgres postgres "$@"; }
psql_admin() { postgres psql -v ON_ERROR_STOP=1 -U postgres -d postgres "$@"; }

psql_admin -v new_db="$new_db" -v owner="oracle_migrator" <<'SQL'
SELECT format('CREATE DATABASE %I OWNER %I TEMPLATE template0 ENCODING ''UTF8''', :'new_db', :'owner') \gexec
SQL
postgres pg_restore -U oracle_migrator -d "$new_db" --exit-on-error --single-transaction --no-owner < "$dump"

current_head="$(postgres psql -U postgres -d opn_oracle -Atqc 'SELECT version_num FROM alembic_version')"
new_head="$(postgres psql -U postgres -d "$new_db" -Atqc 'SELECT version_num FROM alembic_version')"
[[ -n "$current_head" && "$new_head" == "$current_head" ]] || { echo "Alembic head incompatible." >&2; exit 1; }
checks="$(postgres psql -U postgres -d "$new_db" -AtF '|' <<'SQL'
SELECT
 (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p') AND n.nspname='public'),
 (SELECT count(*) FROM pg_index WHERE NOT indisvalid),
 (SELECT count(*) FROM pg_policy),
 (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_roles r ON r.oid=c.relowner WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m') AND r.rolname <> 'oracle_migrator'),
 has_schema_privilege('oracle_app','public','USAGE'),
 has_table_privilege('oracle_app','public.users','SELECT,INSERT,UPDATE'),
 has_table_privilege('oracle_app','public.workspaces','SELECT,INSERT,UPDATE,DELETE');
SQL
)"
IFS='|' read -r tables invalid rls wrong_owner schema_ok users_ok workspaces_ok <<<"$checks"
[[ "$tables" =~ ^[1-9][0-9]*$ && "$invalid" == 0 && "$rls" =~ ^[1-9][0-9]*$ && "$wrong_owner" == 0 && \
   "$schema_ok" == t && "$users_ok" == t && "$workspaces_ok" == t ]] || {
  echo "Validación estructural/ACL/RLS fallida: tables=$tables invalid=$invalid rls=$rls wrong_owner=$wrong_owner" >&2; exit 1;
}

rollback_swap() {
  [[ "$swapped" == true ]] || return 0
  "${compose[@]}" stop web api worker-core beat >/dev/null 2>&1 || true
  psql_admin -v current="opn_oracle" -v failed="$failed_db" -v previous="$old_db" <<'SQL' || true
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN (:'current', :'previous') AND pid <> pg_backend_pid();
SELECT format('ALTER DATABASE %I RENAME TO %I', :'current', :'failed') \gexec
SELECT format('ALTER DATABASE %I RENAME TO %I', :'previous', :'current') \gexec
SQL
  "${compose[@]}" up -d api worker-core beat web >/dev/null 2>&1 || true
  echo "Rollback automático ejecutado; la base fallida se conserva como $failed_db." >&2
}
"${compose[@]}" stop web api worker-core beat
psql_admin -v current="opn_oracle" -v previous="$old_db" -v replacement="$new_db" <<'SQL'
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN (:'current', :'replacement') AND pid <> pg_backend_pid();
SELECT format('ALTER DATABASE %I RENAME TO %I', :'current', :'previous') \gexec
SELECT format('ALTER DATABASE %I RENAME TO %I', :'replacement', :'current') \gexec
SQL
swapped=true
"${compose[@]}" up -d api worker-core beat web
"$release_dir/scripts/smoke-production.sh"
swapped=false
agent_cli complete --operation-id "$operation_id" --worker-id "$worker_id" --status succeeded
operation_done=true
trap - EXIT
rm -f -- "${metadata:-}"
echo "Restore completado. Rollback preservado en database=$old_db."
