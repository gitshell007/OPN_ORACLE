#!/usr/bin/env bash
# Activate an immutable release: symlink + env identity together, migrate once,
# restart services. Fail loud if identity sources diverge.
# Usage: activate-release.sh <release-id>
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "must run as root" >&2
  exit 1
fi

RELEASE_ID="${1:?release-id required}"
RELEASE_DIR="/opt/opn-oracle/releases/${RELEASE_ID}"
CURRENT="/opt/opn-oracle/current"
ENV_FILE="/etc/opn-oracle-dev/oracle.env"
SECRETS="/etc/opn-oracle-dev/secrets"

[[ -d "$RELEASE_DIR" ]] || { echo "missing $RELEASE_DIR" >&2; exit 1; }
[[ -f "$ENV_FILE" ]] || { echo "missing $ENV_FILE" >&2; exit 1; }

# Prefer tree identity when the release was built with RELEASE_ID metadata.
if [[ -f "${RELEASE_DIR}/RELEASE_ID" ]]; then
  TREE_ID="$(tr -d '[:space:]' <"${RELEASE_DIR}/RELEASE_ID")"
  if [[ -n "$TREE_ID" && "$TREE_ID" != "$RELEASE_ID" ]]; then
    echo "FATAL: activate arg RELEASE_ID=${RELEASE_ID} != tree RELEASE_ID=${TREE_ID}" >&2
    exit 1
  fi
fi

PREV=""
if [[ -L "$CURRENT" ]]; then
  PREV="$(readlink -f "$CURRENT" || true)"
fi

# --- Update env + symlink as one activation unit (SV2-SANEO-ANIDADO) ---
# Never update only the symlink (build-release used to hint ln -sfn alone;
# that left ORACLE_RELEASE/RELEASE lagging and /api/v1/meta lied).
_set_env_key() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    echo "${key}=${value}" >>"$ENV_FILE"
  fi
}

_set_env_key "ORACLE_RELEASE" "$RELEASE_ID"
_set_env_key "RELEASE" "$RELEASE_ID"
if ! grep -q '^APP_VERSION=' "$ENV_FILE"; then
  echo "APP_VERSION=0.1.0" >>"$ENV_FILE"
fi

# Atomic symlink swap
ln -sfn "$RELEASE_DIR" "${CURRENT}.new"
mv -Tf "${CURRENT}.new" "$CURRENT"
echo "current -> $(readlink -f "$CURRENT")"
printf '%s\n' "$RELEASE_ID" >/opt/opn-oracle/CURRENT_RELEASE
if [[ -n "$PREV" ]]; then
  printf '%s\n' "$(basename "$PREV")" >/opt/opn-oracle/PREVIOUS_RELEASE || true
fi

# --- Fail-loud identity coherence (symlink ≡ env ≡ CURRENT_RELEASE ≡ tree) ---
ACTIVE="$(basename "$(readlink -f "$CURRENT")")"
ENV_ORACLE_RELEASE="$(sed -n 's/^ORACLE_RELEASE=//p' "$ENV_FILE" | tail -n 1)"
ENV_RELEASE="$(sed -n 's/^RELEASE=//p' "$ENV_FILE" | tail -n 1)"
CURRENT_FILE="$(tr -d '[:space:]' </opt/opn-oracle/CURRENT_RELEASE 2>/dev/null || true)"
TREE_ID="$(tr -d '[:space:]' <"${RELEASE_DIR}/RELEASE_ID" 2>/dev/null || true)"

_fail_identity() {
  echo "FATAL: release identity divergence after activate: $*" >&2
  echo "  symlink_basename=${ACTIVE}" >&2
  echo "  ORACLE_RELEASE=${ENV_ORACLE_RELEASE}" >&2
  echo "  RELEASE=${ENV_RELEASE}" >&2
  echo "  CURRENT_RELEASE=${CURRENT_FILE}" >&2
  echo "  tree_RELEASE_ID=${TREE_ID:-<missing>}" >&2
  echo "  expected=${RELEASE_ID}" >&2
  exit 1
}

[[ "$ACTIVE" == "$RELEASE_ID" ]] || _fail_identity "current basename != RELEASE_ID"
[[ "$ENV_ORACLE_RELEASE" == "$RELEASE_ID" ]] || _fail_identity "ORACLE_RELEASE != RELEASE_ID"
[[ "$ENV_RELEASE" == "$RELEASE_ID" ]] || _fail_identity "RELEASE != RELEASE_ID"
[[ "$CURRENT_FILE" == "$RELEASE_ID" ]] || _fail_identity "CURRENT_RELEASE file != RELEASE_ID"
if [[ -n "$TREE_ID" && "$TREE_ID" != "$RELEASE_ID" ]]; then
  _fail_identity "tree RELEASE_ID != activate arg"
fi
echo "identity OK: symlink=env=CURRENT_RELEASE=${RELEASE_ID}${TREE_ID:+ tree=${TREE_ID}}"

# Load env for migration (set -a)
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
export PATH="${RELEASE_DIR}/apps/api/.venv/bin:/usr/local/bin:${PATH}"
export PYTHONPATH="${RELEASE_DIR}/apps/api/src"

# The app resolves *_FILE at runtime; just ensure the secret files exist.
for f in oracle_secret_key oracle_database_url oracle_database_migration_url \
  oracle_redis_url oracle_session_redis_url oracle_ratelimit_redis_url \
  oracle_celery_broker_url oracle_celery_result_url oracle_integration_encryption_keys; do
  [[ -f "${SECRETS}/${f}" ]] || { echo "missing secret $f" >&2; exit 1; }
done

echo "=== alembic upgrade (migrator URL via env file) ==="
cd "${RELEASE_DIR}/apps/api"
# Flask-Migrate uses DATABASE_MIGRATION_URL / DATABASE_URL from env files
set +e
sudo -u opn-oracle env \
  HOME=/var/lib/opn-oracle-dev \
  PATH="${RELEASE_DIR}/apps/api/.venv/bin:/usr/bin" \
  PYTHONPATH="${RELEASE_DIR}/apps/api/src" \
  $(grep -E '^[A-Z0-9_]+=' "$ENV_FILE" | grep -v -E 'PASSWORD|SECRET|URL=' || true) \
  bash -c '
    set -a
    source /etc/opn-oracle-dev/oracle.env
    set +a
    # Do NOT materialize secrets from *_FILE here: config.py resolves them at
    # runtime and raises ConfigError if both X and X_FILE are set.
    cd /opt/opn-oracle/current/apps/api
    # Call the venv flask directly; uv lives in /usr/local/bin, outside this PATH.
    .venv/bin/flask --app opn_oracle.wsgi:app db upgrade
  '
migrate_rc=$?
set -e
if [[ $migrate_rc -ne 0 ]]; then
  echo "migration failed rc=$migrate_rc; leaving current at new release for diagnosis" >&2
  exit $migrate_rc
fi

systemctl daemon-reload
systemctl enable opn-oracle-api opn-oracle-web opn-oracle-worker opn-oracle-beat
systemctl restart opn-oracle-api
systemctl restart opn-oracle-web
systemctl restart opn-oracle-worker
systemctl restart opn-oracle-beat

sleep 3
systemctl --no-pager --full status opn-oracle-api opn-oracle-web opn-oracle-worker opn-oracle-beat || true

# Post-restart identity re-check (services read EnvironmentFile at start)
ENV_ORACLE_RELEASE="$(sed -n 's/^ORACLE_RELEASE=//p' "$ENV_FILE" | tail -n 1)"
ACTIVE="$(basename "$(readlink -f "$CURRENT")")"
META_RELEASE="$(curl -fsS http://127.0.0.1:8010/api/v1/meta 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin).get("release",""))' 2>/dev/null || true)"
if [[ "$ACTIVE" != "$RELEASE_ID" || "$ENV_ORACLE_RELEASE" != "$RELEASE_ID" ]]; then
  _fail_identity "post-restart env/symlink drift"
fi
if [[ -n "$META_RELEASE" && "$META_RELEASE" != "$RELEASE_ID" ]]; then
  # Prefer tree identity in app code; if meta still disagrees, surface it.
  echo "WARNING: /api/v1/meta release=${META_RELEASE} != ${RELEASE_ID} (check tree RELEASE_ID vs Settings)" >&2
fi
echo "activate complete: meta=${META_RELEASE:-<unavailable>} symlink=${ACTIVE} env=${ENV_ORACLE_RELEASE}"
