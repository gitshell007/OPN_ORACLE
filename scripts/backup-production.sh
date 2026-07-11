#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Uso: $0 --create" >&2
  echo "Variables: ORACLE_ENV_FILE, ORACLE_BACKUP_ROOT, ORACLE_RELEASE" >&2
}

if [[ "${1:-}" != "--create" || $# -ne 1 ]]; then
  usage
  exit 2
fi

umask 077
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${ORACLE_ENV_FILE:-/etc/opn-oracle/oracle.env}"
backup_root="${ORACLE_BACKUP_ROOT:-/var/backups/opn-oracle}"
postgres_image="postgres:17-bookworm"
database_name="opn_oracle"

for command_name in docker sha256sum date awk grep cp mkdir mv chmod find sort xargs rm wc; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Falta el comando requerido: $command_name" >&2
    exit 2
  }
done
docker compose version >/dev/null

if [[ ! -r "$env_file" || -L "$env_file" ]]; then
  echo "ORACLE_ENV_FILE debe ser un fichero regular legible, no un enlace." >&2
  exit 2
fi
if [[ "$backup_root" != /* || -L "$backup_root" ]]; then
  echo "ORACLE_BACKUP_ROOT debe ser una ruta absoluta y no un enlace." >&2
  exit 2
fi

declare -A seen_env=()

release_from_file=""
while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
  line="${raw_line%$'\r'}"
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
  if [[ "$line" != *=* ]]; then
    echo "Línea inválida en ORACLE_ENV_FILE; no se genera el backup." >&2
    exit 2
  fi
  key="${line%%=*}"
  value="${line#*=}"
  if [[ ! "$key" =~ ^[A-Z][A-Z0-9_]*$ ]]; then
    echo "Clave inválida en ORACLE_ENV_FILE: $key" >&2
    exit 2
  fi
  if [[ -n "${seen_env[$key]:-}" ]]; then
    echo "Clave duplicada en ORACLE_ENV_FILE: $key" >&2
    exit 2
  fi
  if [[ "$value" == *$'\n'* || "$value" == *$'\r'* ]]; then
    echo "Valor multilínea no permitido en ORACLE_ENV_FILE: $key" >&2
    exit 2
  fi
  if [[ "$key" != "ORACLE_SECRETS_DIR" && \
        "$key" =~ (SECRET|PASSWORD|TOKEN|PRIVATE|CREDENTIAL) ]]; then
    echo "ORACLE_ENV_FILE contiene una clave de posible secreto inline: $key" >&2
    echo "Materialízala como secret file fuera de oracle.env." >&2
    exit 2
  fi
  seen_env[$key]=1
  [[ "$key" == "ORACLE_RELEASE" ]] && release_from_file="$value"
done < "$env_file"

release="${ORACLE_RELEASE:-$release_from_file}"
if [[ ! "$release" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]]; then
  echo "ORACLE_RELEASE ausente o no es un identificador seguro." >&2
  exit 2
fi

compose=(docker compose --env-file "$env_file" -f "$repo_root/compose.prod.yml")
export ORACLE_SECRETS_DIR="${ORACLE_SECRETS_DIR:-/etc/opn-oracle/secrets}"
"${compose[@]}" config --quiet
if ! "${compose[@]}" ps --status running --services | grep -qx postgres; then
  echo "El servicio postgres de producción no está en ejecución." >&2
  exit 2
fi
if ! "${compose[@]}" exec -T -u postgres postgres \
  pg_isready -U postgres -d "$database_name" >/dev/null; then
  echo "PostgreSQL no está preparado; no se genera un backup parcial." >&2
  exit 2
fi

mkdir -p -- "$backup_root"
chmod 0700 "$backup_root"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_id="${timestamp}-${release}"
final_dir="$backup_root/$backup_id"
staging_dir="$backup_root/.${backup_id}.partial.$$"

if [[ -e "$final_dir" || -e "$staging_dir" ]]; then
  echo "El destino del backup ya existe; se evita sobrescribirlo." >&2
  exit 2
fi

cleanup() {
  if [[ -n "${staging_dir:-}" && -d "$staging_dir" ]]; then
    rm -rf -- "$staging_dir"
  fi
}
trap cleanup EXIT INT TERM

mkdir -p "$staging_dir/config"
dump_file="$staging_dir/database.dump"

if find "$repo_root/infra/nginx" -type l -print -quit | grep -q .; then
  echo "infra/nginx contiene enlaces simbólicos; snapshot rechazado." >&2
  exit 2
fi

"${compose[@]}" exec -T -u postgres postgres \
  pg_dump \
  --dbname="$database_name" \
  --format=custom \
  --compress=6 \
  --no-owner \
  > "$dump_file"

if [[ ! -s "$dump_file" ]]; then
  echo "pg_dump produjo un fichero vacío." >&2
  exit 1
fi
"${compose[@]}" exec -T -u postgres postgres pg_restore --list < "$dump_file" >/dev/null
acl_sql="$staging_dir/.acl-check.sql"
"${compose[@]}" exec -T -u postgres postgres \
  pg_restore --schema-only --no-owner --file=- < "$dump_file" > "$acl_sql"
if ! grep -Eq 'GRANT .* TO oracle_app;' "$acl_sql"; then
  echo "El dump no conserva grants para oracle_app; backup rechazado." >&2
  exit 1
fi
rm -f -- "$acl_sql"

cp -- "$repo_root/compose.prod.yml" "$staging_dir/config/compose.prod.yml"
cp -- "$repo_root/infra/production/oracle.env.example" \
  "$staging_dir/config/oracle.env.example"
cp -- "$repo_root/infra/production/SECRETS.md" "$staging_dir/config/SECRETS.md"
cp -R -- "$repo_root/infra/nginx" "$staging_dir/config/nginx"

snapshot_env="$staging_dir/config/oracle.env.snapshot"
while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
  line="${raw_line%$'\r'}"
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
  key="${line%%=*}"
  value="${line#*=}"
  case "$key" in
    ORACLE_RELEASE|ORACLE_APP_VERSION) printf '%s=%s\n' "$key" "$value" >> "$snapshot_env" ;;
    *) printf '%s=<configured-redacted>\n' "$key" >> "$snapshot_env" ;;
  esac
done < "$env_file"

dump_sha256="$(sha256sum "$dump_file" | awk '{print $1}')"
dump_bytes="$(wc -c < "$dump_file" | awk '{print $1}')"
(
  cd "$staging_dir"
  find config -type f -print0 | sort -z | xargs -0 sha256sum
) > "$staging_dir/CONFIG_CHECKSUMS.sha256"

manifest="$staging_dir/MANIFEST.txt"
{
  printf 'format_version=1\n'
  printf 'backup_id=%s\n' "$backup_id"
  printf 'created_at_utc=%s\n' "$timestamp"
  printf 'release=%s\n' "$release"
  printf 'postgres_image=%s\n' "$postgres_image"
  printf 'database_name=%s\n' "$database_name"
  printf 'dump_file=database.dump\n'
  printf 'dump_format=postgresql_custom\n'
  printf 'dump_compression=gzip_level_6\n'
  printf 'dump_acl=preserved\n'
  printf 'dump_sha256=%s\n' "$dump_sha256"
  printf 'dump_bytes=%s\n' "$dump_bytes"
  printf 'config_checksum_file=CONFIG_CHECKSUMS.sha256\n'
  printf 'restore_test_required=true\n'
  printf 'offsite_copy_required=true\n'
} > "$manifest"

(
  cd "$staging_dir"
  sha256sum database.dump CONFIG_CHECKSUMS.sha256 MANIFEST.txt > ARTIFACT_CHECKSUMS.sha256
)

find "$staging_dir" -type f -exec chmod 0400 {} +
find "$staging_dir" -type d -exec chmod 0500 {} +
mv -- "$staging_dir" "$final_dir"
staging_dir=""
trap - EXIT INT TERM

echo "Backup lógico creado y verificado localmente."
echo "Manifiesto: $final_dir/MANIFEST.txt"
echo "Pendiente obligatorio: restore aislado y copia cifrada off-host."
