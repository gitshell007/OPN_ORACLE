#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Uso:" >&2
  echo "  $0 --verify-isolated /ruta/MANIFEST.txt" >&2
  echo "  $0 --check-evidence /ruta/MANIFEST.txt /ruta/RESTORE_EVIDENCE.txt" >&2
}

if [[ "${1:-}" != "--verify-isolated" && "${1:-}" != "--check-evidence" ]]; then
  usage
  exit 2
fi

mode="$1"
manifest="${2:-}"
evidence="${3:-}"
if [[ -z "$manifest" || ( "$mode" == "--verify-isolated" && $# -ne 2 ) || \
      ( "$mode" == "--check-evidence" && $# -ne 3 ) ]]; then
  usage
  exit 2
fi

for command_name in sha256sum date awk grep mkdir mv chmod dirname basename wc; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Falta el comando requerido: $command_name" >&2
    exit 2
  }
done

if [[ ! -f "$manifest" || ! -r "$manifest" || -L "$manifest" ]]; then
  echo "El manifiesto debe ser un fichero regular legible, no un enlace." >&2
  exit 2
fi
manifest_dir="$(cd "$(dirname "$manifest")" && pwd)"
manifest="${manifest_dir}/$(basename "$manifest")"

format_version=""
backup_id=""
created_at_utc=""
release=""
postgres_image=""
database_name=""
dump_file_name=""
dump_format=""
dump_compression=""
dump_acl=""
dump_sha256=""
dump_bytes=""
config_checksum_file=""
restore_test_required=""
offsite_copy_required=""

while IFS='=' read -r key value || [[ -n "$key" ]]; do
  [[ -z "$key" ]] && continue
  case "$key" in
    format_version) format_version="$value" ;;
    backup_id) backup_id="$value" ;;
    created_at_utc) created_at_utc="$value" ;;
    release) release="$value" ;;
    postgres_image) postgres_image="$value" ;;
    database_name) database_name="$value" ;;
    dump_file) dump_file_name="$value" ;;
    dump_format) dump_format="$value" ;;
    dump_compression) dump_compression="$value" ;;
    dump_acl) dump_acl="$value" ;;
    dump_sha256) dump_sha256="$value" ;;
    dump_bytes) dump_bytes="$value" ;;
    config_checksum_file) config_checksum_file="$value" ;;
    restore_test_required) restore_test_required="$value" ;;
    offsite_copy_required) offsite_copy_required="$value" ;;
    *) echo "Clave desconocida en el manifiesto: $key" >&2; exit 2 ;;
  esac
done < "$manifest"

if [[ "$format_version" != "1" || "$dump_format" != "postgresql_custom" || \
      "$dump_compression" != "gzip_level_6" || \
      ( -n "$dump_acl" && "$dump_acl" != "preserved" ) || \
      "$restore_test_required" != "true" || \
      ( "$offsite_copy_required" != "true" && "$offsite_copy_required" != "false" && \
        "$offsite_copy_required" != "0" && "$offsite_copy_required" != "1" ) ]]; then
  echo "El manifiesto no cumple el contrato de backup productivo." >&2
  exit 2
fi
if [[ ! "$backup_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$ || \
      ! "$release" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ || \
      ! "$created_at_utc" =~ ^[0-9]{8}T[0-9]{6}Z$ ]]; then
  echo "Metadatos inseguros o inválidos en el manifiesto." >&2
  exit 2
fi
if [[ "$postgres_image" != "postgres:17-bookworm" || "$database_name" != "opn_oracle" || \
      "$dump_file_name" != "database.dump" || \
      "$config_checksum_file" != "CONFIG_CHECKSUMS.sha256" || \
      ! "$dump_sha256" =~ ^[a-f0-9]{64}$ || ! "$dump_bytes" =~ ^[1-9][0-9]*$ ]]; then
  echo "Artefactos o imagen no permitidos por el contrato de restore." >&2
  exit 2
fi

dump_file="$manifest_dir/$dump_file_name"
config_checksums="$manifest_dir/$config_checksum_file"
artifact_checksums="$manifest_dir/ARTIFACT_CHECKSUMS.sha256"
for artifact in "$dump_file" "$config_checksums" "$artifact_checksums"; do
  if [[ ! -f "$artifact" || ! -r "$artifact" || -L "$artifact" ]]; then
    echo "Artefacto ausente, ilegible o enlazado: $(basename "$artifact")" >&2
    exit 2
  fi
done

actual_dump_sha256="$(sha256sum "$dump_file" | awk '{print $1}')"
actual_dump_bytes="$(wc -c < "$dump_file" | awk '{print $1}')"
if [[ "$actual_dump_sha256" != "$dump_sha256" || "$actual_dump_bytes" != "$dump_bytes" ]]; then
  echo "El dump no coincide con el manifiesto." >&2
  exit 1
fi
(
  cd "$manifest_dir"
  sha256sum --check --strict ARTIFACT_CHECKSUMS.sha256 >/dev/null
  sha256sum --check --strict CONFIG_CHECKSUMS.sha256 >/dev/null
)
manifest_sha256="$(sha256sum "$manifest" | awk '{print $1}')"

check_evidence() {
  local evidence_file="$1"
  local evidence_format="" evidence_status="" evidence_manifest_sha=""
  local evidence_dump_sha="" evidence_backup_id="" evidence_target=""
  local evidence_finished="" evidence_ports=""
  local evidence_tables="" evidence_invalid_indexes="" evidence_rls_policies=""

  if [[ ! -f "$evidence_file" || ! -r "$evidence_file" || -L "$evidence_file" ]]; then
    echo "La evidencia debe ser un fichero regular legible, no un enlace." >&2
    exit 2
  fi
  while IFS='=' read -r key value || [[ -n "$key" ]]; do
    [[ -z "$key" ]] && continue
    case "$key" in
      format_version) evidence_format="$value" ;;
      status) evidence_status="$value" ;;
      backup_id) evidence_backup_id="$value" ;;
      manifest_sha256) evidence_manifest_sha="$value" ;;
      dump_sha256) evidence_dump_sha="$value" ;;
      finished_at_utc) evidence_finished="$value" ;;
      target_database) evidence_target="$value" ;;
      published_ports) evidence_ports="$value" ;;
      restored_user_tables) evidence_tables="$value" ;;
      invalid_indexes) evidence_invalid_indexes="$value" ;;
      rls_policies) evidence_rls_policies="$value" ;;
      *) echo "Clave desconocida en la evidencia: $key" >&2; exit 2 ;;
    esac
  done < "$evidence_file"
  if [[ "$evidence_format" != "1" || "$evidence_status" != "success" || \
        "$evidence_backup_id" != "$backup_id" || \
        "$evidence_manifest_sha" != "$manifest_sha256" || \
        "$evidence_dump_sha" != "$dump_sha256" || \
        "$evidence_target" != "oracle_restore_test" || "$evidence_ports" != "none" || \
        ! "$evidence_finished" =~ ^[0-9]{8}T[0-9]{6}Z$ || \
        ! "$evidence_tables" =~ ^[1-9][0-9]*$ || "$evidence_invalid_indexes" != "0" || \
        ! "$evidence_rls_policies" =~ ^[0-9]+$ ]]; then
    echo "La evidencia no demuestra un restore aislado válido de este manifiesto." >&2
    exit 1
  fi
  echo "Evidencia de restore aislado válida para backup_id=$backup_id."
}

if [[ "$mode" == "--check-evidence" ]]; then
  check_evidence "$evidence"
  exit 0
fi

for command_name in docker seq sleep; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Falta el comando requerido: $command_name" >&2
    exit 2
  }
done
docker version >/dev/null
run_id="$(date -u +%Y%m%d%H%M%S)-$$"
network_name="oracle-restore-test-net-$run_id"
volume_name="oracle-restore-test-data-$run_id"
container_name="oracle-restore-test-db-$run_id"
restore_database="oracle_restore_test"
container_started="false"
network_created="false"
volume_created="false"

cleanup() {
  if [[ "$container_started" == "true" ]]; then
    docker rm -f "$container_name" >/dev/null 2>&1 || true
  fi
  if [[ "$volume_created" == "true" ]]; then
    docker volume rm "$volume_name" >/dev/null 2>&1 || true
  fi
  if [[ "$network_created" == "true" ]]; then
    docker network rm "$network_name" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

docker network create --internal "$network_name" >/dev/null
network_created="true"
docker volume create "$volume_name" >/dev/null
volume_created="true"
docker run -d \
  --name "$container_name" \
  --network "$network_name" \
  --mount "type=volume,source=$volume_name,target=/var/lib/postgresql/data" \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
  --tmpfs /var/run/postgresql:rw,noexec,nosuid,nodev,size=16m \
  --read-only \
  --security-opt no-new-privileges:true \
  --env POSTGRES_HOST_AUTH_METHOD=trust \
  --env POSTGRES_DB="$restore_database" \
  "$postgres_image" >/dev/null
container_started="true"

ready="false"
for _ in $(seq 1 60); do
  if docker exec -u postgres "$container_name" \
    pg_isready -U postgres -d "$restore_database" >/dev/null 2>&1; then
    ready="true"
    break
  fi
  sleep 1
done
if [[ "$ready" != "true" ]]; then
  echo "El PostgreSQL efímero no alcanzó readiness." >&2
  exit 1
fi

docker exec -i -u postgres "$container_name" \
  pg_restore \
  --dbname="$restore_database" \
  --exit-on-error \
  --single-transaction \
  --no-owner \
  --no-privileges < "$dump_file"

table_count="$(docker exec -u postgres "$container_name" psql \
  -U postgres -d "$restore_database" -Atqc \
  "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p') AND n.nspname NOT IN ('pg_catalog','information_schema');")"
invalid_indexes="$(docker exec -u postgres "$container_name" psql \
  -U postgres -d "$restore_database" -Atqc \
  "SELECT count(*) FROM pg_index WHERE NOT indisvalid;")"
rls_policies="$(docker exec -u postgres "$container_name" psql \
  -U postgres -d "$restore_database" -Atqc \
  "SELECT count(*) FROM pg_policy;")"
alembic_present="$(docker exec -u postgres "$container_name" psql \
  -U postgres -d "$restore_database" -Atqc \
  "SELECT to_regclass('public.alembic_version') IS NOT NULL;")"

if [[ ! "$table_count" =~ ^[1-9][0-9]*$ || "$invalid_indexes" != "0" || \
      "$alembic_present" != "t" ]]; then
  echo "El restore terminó, pero fallaron las comprobaciones estructurales." >&2
  exit 1
fi

finished_at="$(date -u +%Y%m%dT%H%M%SZ)"
evidence_root="${ORACLE_RESTORE_EVIDENCE_ROOT:-$(dirname "$manifest_dir")/restore-evidence}"
if [[ "$evidence_root" != /* || -L "$evidence_root" ]]; then
  echo "ORACLE_RESTORE_EVIDENCE_ROOT debe ser absoluto y no un enlace." >&2
  exit 2
fi
mkdir -p "$evidence_root"
chmod 0700 "$evidence_root"
evidence_file="$evidence_root/${backup_id}.RESTORE_EVIDENCE.txt"
evidence_tmp="$evidence_root/.${backup_id}.RESTORE_EVIDENCE.txt.partial.$$"
if [[ -e "$evidence_file" || -e "$evidence_tmp" ]]; then
  echo "La evidencia ya existe; no se sobrescribe." >&2
  exit 2
fi
{
  printf 'format_version=1\n'
  printf 'status=success\n'
  printf 'backup_id=%s\n' "$backup_id"
  printf 'manifest_sha256=%s\n' "$manifest_sha256"
  printf 'dump_sha256=%s\n' "$dump_sha256"
  printf 'finished_at_utc=%s\n' "$finished_at"
  printf 'target_database=%s\n' "$restore_database"
  printf 'published_ports=none\n'
  printf 'restored_user_tables=%s\n' "$table_count"
  printf 'invalid_indexes=%s\n' "$invalid_indexes"
  printf 'rls_policies=%s\n' "$rls_policies"
} > "$evidence_tmp"
chmod 0400 "$evidence_tmp"
mv "$evidence_tmp" "$evidence_file"

check_evidence "$evidence_file"
echo "Restore completado en contenedor efímero sin puertos publicados."
echo "Evidencia: $evidence_file"
echo "La copia off-host cifrada solo bloquea si ORACLE_REQUIRE_OFFSITE_RECEIPT=1."
