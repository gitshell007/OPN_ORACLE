#!/usr/bin/env bash
set -Eeuo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
[[ $EUID -eq 0 ]] || { echo "Debe ejecutarse como root." >&2; exit 2; }
env_file="${ORACLE_ENV_FILE:-/etc/opn-oracle/oracle.env}"
release_dir="$(readlink -f "${ORACLE_RELEASE_DIR:-/opt/opn-oracle/current}")"
[[ -f "$env_file" && ! -L "$env_file" && "$release_dir" == /opt/opn-oracle/releases/* && -d "$release_dir" ]] || exit 2
export ORACLE_SECRETS_DIR="${ORACLE_SECRETS_DIR:-/etc/opn-oracle/secrets}"
compose=(docker compose --env-file "$env_file" -f "$release_dir/compose.prod.yml")
"${compose[@]}" config --quiet
key="scheduled-$(date -u +%Y-%m-%d)"
"${compose[@]}" exec -T api flask --app opn_oracle.wsgi:app backup-agent \
  enqueue-scheduled --idempotency-key "$key"
