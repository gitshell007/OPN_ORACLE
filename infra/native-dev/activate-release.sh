#!/usr/bin/env bash
# Activate an immutable release: symlink, migrate once, restart services.
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

PREV=""
if [[ -L "$CURRENT" ]]; then
  PREV="$(readlink -f "$CURRENT" || true)"
fi

# Point env ORACLE_RELEASE / APP_VERSION / RELEASE
sed -i "s|^ORACLE_RELEASE=.*|ORACLE_RELEASE=${RELEASE_ID}|" "$ENV_FILE"
if ! grep -q '^RELEASE=' "$ENV_FILE"; then
  echo "RELEASE=${RELEASE_ID}" >>"$ENV_FILE"
else
  sed -i "s|^RELEASE=.*|RELEASE=${RELEASE_ID}|" "$ENV_FILE"
fi
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
echo "activate complete"
