#!/usr/bin/env bash
set -Eeuo pipefail

umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

usage() {
  cat >&2 <<'EOF'
Uso:
  backup-maintenance.sh --create --origin scheduled|manual
  backup-maintenance.sh --prune

Variables: ORACLE_ENV_FILE, ORACLE_BACKUP_ROOT, ORACLE_RETENTION_DAYS,
ORACLE_RELEASE_DIR, ORACLE_RESTORE_EVIDENCE_ROOT.
EOF
}

mode="${1:-}"
origin=""
if [[ "$mode" == "--create" && "${2:-}" == "--origin" && $# -eq 3 ]]; then
  origin="$3"
  [[ "$origin" == "scheduled" || "$origin" == "manual" ]] || { usage; exit 2; }
elif [[ "$mode" == "--prune" && $# -eq 1 ]]; then
  :
else
  usage
  exit 2
fi

[[ $EUID -eq 0 ]] || { echo "Debe ejecutarse como root." >&2; exit 2; }

env_file="${ORACLE_ENV_FILE:-/etc/opn-oracle/oracle.env}"
backup_root="${ORACLE_BACKUP_ROOT:-/var/backups/opn-oracle}"
release_dir="${ORACLE_RELEASE_DIR:-/opt/opn-oracle/current}"
evidence_root="${ORACLE_RESTORE_EVIDENCE_ROOT:-$backup_root/restore-evidence}"
expired_names_output="${ORACLE_EXPIRED_NAMES_OUTPUT:-}"
retention_days="${ORACLE_RETENTION_DAYS:-30}"
skip_prune="${ORACLE_SKIP_PRUNE:-0}"
lock_file="${ORACLE_BACKUP_LOCK_FILE:-/run/lock/opn-oracle-backup.lock}"

if [[ ! "$retention_days" =~ ^[0-9]+$ ]] || \
   ((retention_days < 1 || retention_days > 3650)); then
  echo "ORACLE_RETENTION_DAYS debe estar entre 1 y 3650." >&2
  exit 2
fi
[[ "$skip_prune" == 0 || "$skip_prune" == 1 ]] || {
  echo "ORACLE_SKIP_PRUNE solo admite 0 o 1." >&2; exit 2;
}
for path in "$backup_root" "$evidence_root"; do
  [[ "$path" == /* && ! -L "$path" ]] || { echo "Ruta insegura: $path" >&2; exit 2; }
done
release_dir="$(readlink -f "$release_dir")"
[[ "$release_dir" == /opt/opn-oracle/releases/* && -d "$release_dir" ]] || {
  echo "El release debe resolver dentro de /opt/opn-oracle/releases." >&2; exit 2;
}
[[ -x "$release_dir/scripts/backup-production.sh" && -x "$release_dir/scripts/restore-test-production.sh" ]] || {
  echo "El release activo no contiene los scripts de backup/restore ejecutables." >&2; exit 2;
}
for command_name in flock find date stat awk sha256sum du mktemp sort readlink chmod mkdir rm basename dirname; do
  command -v "$command_name" >/dev/null || { echo "Falta $command_name." >&2; exit 2; }
done

mkdir -p "$backup_root" "$evidence_root" "$(dirname "$lock_file")"
chmod 0700 "$backup_root" "$evidence_root"
if [[ -n "$expired_names_output" ]]; then
  [[ "$expired_names_output" == "$backup_root"/.pending-expirations/*.names && \
     ! -e "$expired_names_output" ]] || {
    echo "ORACLE_EXPIRED_NAMES_OUTPUT debe ser un destino nuevo en .pending-expirations." >&2; exit 2;
  }
  mkdir -p "$backup_root/.pending-expirations"
  chmod 0700 "$backup_root/.pending-expirations"
  : > "$expired_names_output"
  chmod 0400 "$expired_names_output"
fi
exec 9>"$lock_file"
flock -n 9 || { echo "Ya existe una operación de backup/restore en curso." >&2; exit 75; }

manifest_value() {
  local manifest="$1" key="$2"
  awk -F= -v wanted="$key" '$1 == wanted { if (++seen > 1) exit 3; print substr($0,index($0,"=")+1) } END { if (seen != 1) exit 4 }' "$manifest"
}

validate_backup_dir() {
  local directory="$1" name manifest declared
  [[ -d "$directory" && ! -L "$directory" ]] || return 1
  name="$(basename "$directory")"
  [[ "$name" =~ ^[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || return 1
  manifest="$directory/MANIFEST.txt"
  [[ -f "$manifest" && ! -L "$manifest" ]] || return 1
  declared="$(manifest_value "$manifest" backup_id)" || return 1
  [[ "$declared" == "$name" ]] || return 1
  (cd "$directory" && sha256sum --check --strict ARTIFACT_CHECKSUMS.sha256 >/dev/null) || return 1
}

prune_expired() {
  local now cutoff directory name timestamp epoch newest="" deleted=0
  now="$(date -u +%s)"
  cutoff=$((now - retention_days * 86400))
  mapfile -d '' directories < <(find -P "$backup_root" -mindepth 1 -maxdepth 1 -type d \
    -name '[0-9]*T[0-9]*Z-*' -print0 | sort -z)
  ((${#directories[@]} > 0)) || { echo "No hay backups que rotar."; return 0; }
  newest="${directories[${#directories[@]}-1]}"
  for directory in "${directories[@]}"; do
    [[ "$directory" != "$newest" ]] || continue
    validate_backup_dir "$directory" || { echo "Se conserva artefacto inválido/no reconocido: $directory" >&2; continue; }
    [[ ! -e "$directory/.RETAIN" ]] || { echo "Retención legal/manual activa: $directory"; continue; }
    name="$(basename "$directory")"
    timestamp="${name%%-*}"
    timestamp_iso="${timestamp:0:4}-${timestamp:4:2}-${timestamp:6:2}T${timestamp:9:2}:${timestamp:11:2}:${timestamp:13:2}Z"
    epoch="$(date -u -d "$timestamp_iso" +%s 2>/dev/null)" || {
      echo "Se conserva backup con timestamp no interpretable: $directory" >&2; continue;
    }
    ((epoch < cutoff)) || continue
    find -P "$directory" -xdev -depth -delete
    ((deleted += 1))
    if [[ -n "$expired_names_output" ]]; then
      printf '%s\n' "$name" >> "$expired_names_output"
    fi
    echo "Backup local vencido eliminado: $name"
  done
  echo "Rotación finalizada: $deleted backup(s) eliminado(s), retención=$retention_days días."
}

if [[ "$mode" == "--prune" ]]; then
  [[ "$skip_prune" == 0 ]] || { echo "ORACLE_SKIP_PRUNE no es compatible con --prune." >&2; exit 2; }
  [[ -n "$expired_names_output" ]] || {
    echo "--prune exige ORACLE_EXPIRED_NAMES_OUTPUT para reconciliar el catálogo." >&2; exit 2;
  }
  prune_expired
  exit 0
fi

started_epoch="$(date -u +%s)"
ORACLE_ENV_FILE="$env_file" ORACLE_BACKUP_ROOT="$backup_root" \
  "$release_dir/scripts/backup-production.sh" --create

manifest=""
while IFS= read -r -d '' candidate; do
  candidate_epoch="$(stat -c %Y "$candidate")"
  ((candidate_epoch >= started_epoch)) || continue
  [[ -z "$manifest" ]] || { echo "Más de un backup nuevo; se rechaza la ambigüedad." >&2; exit 1; }
  manifest="$candidate"
done < <(find -P "$backup_root" -mindepth 2 -maxdepth 2 -type f -name MANIFEST.txt -print0)
[[ -n "$manifest" ]] || { echo "No se encontró el manifiesto recién creado." >&2; exit 1; }
validate_backup_dir "$(dirname "$manifest")" || { echo "El backup nuevo no supera checksums." >&2; exit 1; }

backup_id="$(manifest_value "$manifest" backup_id)"
evidence="$evidence_root/${backup_id}.RESTORE_EVIDENCE.txt"
if [[ -f "$evidence" ]]; then
  "$release_dir/scripts/restore-test-production.sh" --check-evidence "$manifest" "$evidence"
else
  ORACLE_RESTORE_EVIDENCE_ROOT="$evidence_root" \
    "$release_dir/scripts/restore-test-production.sh" --verify-isolated "$manifest"
fi

dump_sha="$(manifest_value "$manifest" dump_sha256)"
created="$(manifest_value "$manifest" created_at_utc)"
created_date="${created:0:8} ${created:9:2}:${created:11:2}:${created:13:2} UTC"
size="$(du -sb "$(dirname "$manifest")" | awk '{print $1}')"
expires="$(date -u -d "$created_date + $retention_days days" --iso-8601=seconds)"
verified="$(date -u --iso-8601=seconds)"
metadata_file="${ORACLE_ARTIFACT_JSON_OUTPUT:-}"
[[ "$metadata_file" == "$backup_root"/.artifact.*.json && ! -e "$metadata_file" ]] || {
  echo "ORACLE_ARTIFACT_JSON_OUTPUT debe ser un destino nuevo y seguro en backup_root." >&2; exit 2;
}
cat >"$metadata_file" <<EOF
{"backup_name":"$backup_id","relative_path":"$backup_id/MANIFEST.txt","size_bytes":$size,"sha256":"$dump_sha","backup_created_at":"$(date -u -d "$created_date" --iso-8601=seconds)","verified_at":"$verified","expires_at":"$expires","origin":"$origin"}
EOF
chmod 0400 "$metadata_file"
echo "ORACLE_BACKUP_MANIFEST=$manifest"
if [[ "$skip_prune" == 1 ]]; then
  echo "Rotación omitida explícitamente durante la copia previa al restore."
elif [[ -n "$expired_names_output" ]]; then
  prune_expired
else
  echo "La creación normal exige ORACLE_EXPIRED_NAMES_OUTPUT para reconciliar catálogo." >&2
  exit 2
fi
