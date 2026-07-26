#!/usr/bin/env bash
# Copia cifrada off-host de un backup local ya validado.
# Fail-closed si está habilitado sin destino/clave; no-op si está deshabilitado.
set -euo pipefail

umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

usage() {
  cat >&2 <<'EOF'
Uso:
  backup-offsite.sh --push-latest
  backup-offsite.sh --push /ruta/MANIFEST.txt
  backup-offsite.sh --verify-receipt /ruta/RECEIPT.txt

Variables (backup.conf o entorno):
  ORACLE_OFFSITE_ENABLED=0|1          (default 0)
  ORACLE_OFFSITE_METHOD=local|rsync   (default local)
  ORACLE_OFFSITE_DEST=/ruta/absoluta o user@host:/ruta
  ORACLE_OFFSITE_KEY_FILE=/etc/opn-oracle/secrets/oracle_backup_offsite_key
  ORACLE_OFFSITE_RECEIPT_ROOT=/var/backups/opn-oracle/offsite-receipts
  ORACLE_BACKUP_ROOT=/var/backups/opn-oracle
  ORACLE_REQUIRE_OFFSITE_RECEIPT=0|1  (solo informativo aquí)
EOF
}

mode="${1:-}"
target="${2:-}"
case "$mode" in
  --push-latest)
    [[ $# -eq 1 ]] || { usage; exit 2; }
    ;;
  --push)
    [[ $# -eq 2 && "$target" == /* ]] || { usage; exit 2; }
    ;;
  --verify-receipt)
    [[ $# -eq 2 && "$target" == /* ]] || { usage; exit 2; }
    ;;
  *)
    usage
    exit 2
    ;;
esac

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Debe ejecutarse como root." >&2; exit 2; }

backup_root="${ORACLE_BACKUP_ROOT:-/var/backups/opn-oracle}"
receipt_root="${ORACLE_OFFSITE_RECEIPT_ROOT:-$backup_root/offsite-receipts}"
enabled="${ORACLE_OFFSITE_ENABLED:-0}"
method="${ORACLE_OFFSITE_METHOD:-local}"
dest="${ORACLE_OFFSITE_DEST:-}"
key_file="${ORACLE_OFFSITE_KEY_FILE:-/etc/opn-oracle/secrets/oracle_backup_offsite_key}"

if [[ "$enabled" != "0" && "$enabled" != "1" ]]; then
  echo "ORACLE_OFFSITE_ENABLED solo admite 0 o 1." >&2
  exit 2
fi

receipt_value() {
  local file="$1" key="$2"
  awk -F= -v wanted="$key" '
    $1 == wanted {
      if (++seen > 1) exit 3
      print substr($0, index($0, "=") + 1)
    }
    END { if (seen != 1) exit 4 }
  ' "$file"
}

if [[ "$mode" == "--verify-receipt" ]]; then
  [[ -f "$target" && ! -L "$target" ]] || { echo "Receipt ausente o inseguro." >&2; exit 2; }
  backup_id="$(receipt_value "$target" backup_id)"
  artifact_sha="$(receipt_value "$target" artifact_sha256)"
  artifact_name="$(receipt_value "$target" artifact_name)"
  stored="$(receipt_value "$target" destination_artifact)"
  [[ "$backup_id" =~ ^[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || {
    echo "backup_id del receipt no es seguro." >&2; exit 2;
  }
  [[ "$artifact_sha" =~ ^[a-f0-9]{64}$ ]] || { echo "artifact_sha256 inválido." >&2; exit 2; }
  [[ -f "$stored" && ! -L "$stored" ]] || {
    echo "Artefacto offsite no accesible en esta máquina: $stored" >&2
    echo "Si el destino es remoto, verifícalo en el host receptor." >&2
    exit 1
  }
  actual="$(sha256sum -- "$stored" | awk '{print $1}')"
  [[ "$actual" == "$artifact_sha" ]] || {
    echo "Checksum del artefacto no coincide con el receipt." >&2
    exit 1
  }
  echo "Receipt válido: backup_id=$backup_id artifact=$artifact_name sha256 ok."
  exit 0
fi

if [[ "$enabled" != "1" ]]; then
  echo "Copia offsite deshabilitada (ORACLE_OFFSITE_ENABLED=0). No se genera receipt."
  exit 0
fi

for command_name in tar openssl sha256sum date mkdir chmod mktemp find awk basename dirname; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Falta el comando requerido: $command_name" >&2
    exit 2
  }
done
if [[ "$method" == "rsync" ]]; then
  command -v rsync >/dev/null 2>&1 || { echo "Falta rsync para method=rsync." >&2; exit 2; }
elif [[ "$method" != "local" ]]; then
  echo "ORACLE_OFFSITE_METHOD debe ser local o rsync." >&2
  exit 2
fi

[[ "$backup_root" == /* && -d "$backup_root" && ! -L "$backup_root" ]] || {
  echo "ORACLE_BACKUP_ROOT inseguro o ausente." >&2; exit 2;
}
[[ "$receipt_root" == /* && ! -L "$receipt_root" ]] || {
  echo "ORACLE_OFFSITE_RECEIPT_ROOT inseguro." >&2; exit 2;
}
[[ -n "$dest" && "$dest" != */ ]] || {
  echo "ORACLE_OFFSITE_DEST es obligatorio cuando offsite está habilitado." >&2
  exit 2
}
if [[ "$method" == "local" ]]; then
  [[ "$dest" == /* && ! -L "$dest" ]] || {
    echo "Con method=local, ORACLE_OFFSITE_DEST debe ser ruta absoluta no enlace." >&2
    exit 2
  }
  # Evitar copiar al mismo árbol de backup local.
  if [[ "$dest" == "$backup_root" || "$dest" == "$backup_root"/* ]]; then
    echo "ORACLE_OFFSITE_DEST no puede estar dentro de ORACLE_BACKUP_ROOT." >&2
    exit 2
  fi
fi
[[ -f "$key_file" && ! -L "$key_file" && -r "$key_file" ]] || {
  echo "ORACLE_OFFSITE_KEY_FILE ausente o no legible: $key_file" >&2
  echo "Genera una clave fuerte, p. ej.:" >&2
  echo "  openssl rand -out $key_file 32 && chmod 0400 $key_file" >&2
  exit 2
}
key_bytes="$(wc -c <"$key_file" | tr -d ' ')"
((key_bytes >= 32)) || {
  echo "La clave offsite debe tener al menos 32 bytes." >&2
  exit 2
}

resolve_manifest() {
  if [[ "$mode" == "--push" ]]; then
    [[ -f "$target" && ! -L "$target" && "$(basename "$target")" == "MANIFEST.txt" ]] || {
      echo "Se espera un MANIFEST.txt regular." >&2; exit 2;
    }
    printf '%s\n' "$target"
    return
  fi
  local newest="" candidate
  while IFS= read -r -d '' candidate; do
    newest="$candidate"
  done < <(find -P "$backup_root" -mindepth 2 -maxdepth 2 -type f -name MANIFEST.txt -print0 | sort -z)
  [[ -n "$newest" ]] || { echo "No hay MANIFEST local que copiar." >&2; exit 1; }
  printf '%s\n' "$newest"
}

manifest="$(resolve_manifest)"
backup_dir="$(dirname "$manifest")"
backup_id="$(basename "$backup_dir")"
[[ "$backup_id" =~ ^[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || {
  echo "backup_id no es seguro: $backup_id" >&2; exit 2;
}
(cd "$backup_dir" && sha256sum --check --strict ARTIFACT_CHECKSUMS.sha256 >/dev/null) || {
  echo "Checksums del backup local inválidos; no se copia offsite." >&2
  exit 1
}

mkdir -p -- "$receipt_root"
chmod 0700 "$receipt_root"
if [[ "$method" == "local" ]]; then
  mkdir -p -- "$dest"
  chmod 0700 "$dest"
fi

work="$(mktemp -d "$backup_root/.offsite-pack.XXXXXX")"
trap 'rm -rf -- "${work:-}"' EXIT INT TERM
chmod 0700 "$work"

artifact_name="${backup_id}.tar.enc"
plain_tar="$work/${backup_id}.tar"
enc_file="$work/$artifact_name"

# Solo artefactos del backup, sin secretos del host.
tar -C "$(dirname "$backup_dir")" -cf "$plain_tar" "$backup_id"
openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
  -pass "file:$key_file" \
  -in "$plain_tar" \
  -out "$enc_file"
rm -f -- "$plain_tar"
chmod 0400 "$enc_file"
artifact_sha="$(sha256sum -- "$enc_file" | awk '{print $1}')"
manifest_sha="$(sha256sum -- "$manifest" | awk '{print $1}')"
created_at="$(date -u +%Y%m%dT%H%M%SZ)"

destination_artifact=""
case "$method" in
  local)
    destination_artifact="$dest/$artifact_name"
    if [[ -e "$destination_artifact" ]]; then
      echo "El destino offsite ya tiene $artifact_name; se evita sobrescribir." >&2
      exit 2
    fi
    cp -p -- "$enc_file" "$destination_artifact"
    chmod 0400 "$destination_artifact"
    ;;
  rsync)
    # Destino remoto o local vía rsync. No se imprimen credenciales SSH.
    destination_artifact="${dest%/}/$artifact_name"
    rsync -a --chmod=F0400 -- "$enc_file" "${dest%/}/"
    ;;
esac

receipt="$receipt_root/${backup_id}.OFFSITE_RECEIPT.txt"
if [[ -e "$receipt" ]]; then
  echo "Ya existe un receipt para $backup_id." >&2
  exit 2
fi
cat >"$receipt" <<EOF
backup_id=$backup_id
created_at_utc=$created_at
method=$method
destination=${dest%/}
destination_artifact=$destination_artifact
artifact_name=$artifact_name
artifact_sha256=$artifact_sha
manifest_path=$manifest
manifest_sha256=$manifest_sha
encrypted=true
cipher=aes-256-cbc-pbkdf2-iter200000
key_file=$key_file
EOF
chmod 0400 "$receipt"

echo "Copia offsite cifrada publicada."
echo "ORACLE_BACKUP_OFFSITE_RECEIPT=$receipt"
echo "artifact_sha256=$artifact_sha"
