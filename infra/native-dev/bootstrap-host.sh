#!/usr/bin/env bash
# Fase 1–2: base nativa del host de desarrollo OPN (Debian 13).
# Idempotente. No imprime secretos. Ejecutar como root.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "must run as root" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
TS="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="/var/backups/opn-oracle-dev/host-audit"
mkdir -p "$EVIDENCE_DIR"
EVIDENCE="$EVIDENCE_DIR/bootstrap-${TS}.txt"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$EVIDENCE"; }

log "=== bootstrap-host start ==="

log "Installing packages"
apt-get update -qq
apt-get install -y --no-install-recommends \
  ca-certificates curl gnupg git rsync jq tar gzip coreutils findutils \
  postgresql-17 postgresql-client-17 \
  redis-server \
  nginx certbot python3-certbot-nginx \
  python3 python3-venv python3-pip python3-dev \
  build-essential pkg-config \
  libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 \
  libcairo2 libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info \
  fonts-dejavu-core \
  nodejs npm \
  ufw \
  acl

# uv
if ! command -v uv >/dev/null 2>&1; then
  log "Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  install -m 0755 /root/.local/bin/uv /usr/local/bin/uv
fi

log "Versions"
{
  python3 --version
  uv --version
  node --version || true
  npm --version || true
  nginx -v 2>&1 || true
  psql --version
  redis-server --version
  certbot --version 2>&1 || true
} | tee -a "$EVIDENCE"

log "System users"
id opn-oracle >/dev/null 2>&1 || useradd --system --home /var/lib/opn-oracle-dev --shell /usr/sbin/nologin --user-group opn-oracle
id opn-risk >/dev/null 2>&1 || useradd --system --home /var/lib/opn-risk-dev --shell /usr/sbin/nologin --user-group opn-risk

log "Directory layout"
install -d -m 0750 -o root -g opn-oracle /opt/opn-oracle
install -d -m 0750 -o root -g opn-oracle /opt/opn-oracle/releases
install -d -m 0750 -o root -g opn-oracle /etc/opn-oracle-dev
install -d -m 0750 -o root -g opn-oracle /etc/opn-oracle-dev/secrets
install -d -m 0750 -o opn-oracle -g opn-oracle /var/lib/opn-oracle-dev
install -d -m 0750 -o opn-oracle -g opn-oracle /var/lib/opn-oracle-dev/document-storage
install -d -m 0750 -o opn-oracle -g opn-oracle /var/log/opn-oracle-dev
install -d -m 0750 -o root -g root /var/backups/opn-oracle-dev
install -d -m 0750 -o root -g opn-risk /var/lib/opn-risk-dev
install -d -m 0755 -o root -g root /var/www/certbot
install -d -m 0755 -o root -g root /opt/src
install -d -m 0700 -o root -g root /opt/src/oracle-build

# PostgreSQL: loopback only
PG_CONF="$(ls /etc/postgresql/17/main/postgresql.conf 2>/dev/null || true)"
PG_HBA="$(ls /etc/postgresql/17/main/pg_hba.conf 2>/dev/null || true)"
if [[ -n "$PG_CONF" ]]; then
  if [[ ! -f "${PG_CONF}.bak-pre-opn-native" ]]; then
    cp -a "$PG_CONF" "${PG_CONF}.bak-pre-opn-native"
  fi
  # ensure listen_addresses = 'localhost'
  if grep -qE "^\s*listen_addresses\s*=" "$PG_CONF"; then
    sed -i "s/^\s*listen_addresses\s*=.*/listen_addresses = 'localhost'/" "$PG_CONF"
  else
    echo "listen_addresses = 'localhost'" >>"$PG_CONF"
  fi
fi
if [[ -n "$PG_HBA" && ! -f "${PG_HBA}.bak-pre-opn-native" ]]; then
  cp -a "$PG_HBA" "${PG_HBA}.bak-pre-opn-native"
fi

systemctl enable --now postgresql
systemctl restart postgresql

log "PostgreSQL roles and databases"
# Generate passwords if missing (do not print)
SECRETS=/etc/opn-oracle-dev/secrets
gen_secret_file() {
  local f="$1" mode="${2:-0440}" owner="${3:-root:opn-oracle}"
  if [[ ! -f "$f" ]]; then
    umask 077
    # 43 url-safe chars
    openssl rand -base64 48 | tr -d '\n/+=' | head -c 48 >"$f"
    chown "$owner" "$f"
    chmod "$mode" "$f"
  fi
}

gen_secret_file "$SECRETS/postgres_admin_password" 0400 root:root
gen_secret_file "$SECRETS/postgres_migrator_password" 0440 root:opn-oracle
gen_secret_file "$SECRETS/postgres_app_password" 0440 root:opn-oracle
gen_secret_file "$SECRETS/redis_password" 0440 root:opn-oracle
gen_secret_file "$SECRETS/oracle_secret_key" 0440 root:opn-oracle
gen_secret_file "$SECRETS/oracle_integration_encryption_keys" 0440 root:opn-oracle

# integration keyring format 1:<base64 of 32 bytes>
if ! grep -q '^1:' "$SECRETS/oracle_integration_encryption_keys" 2>/dev/null; then
  KEY_B64="$(openssl rand 32 | base64 -w0 2>/dev/null || openssl rand 32 | base64)"
  printf '1:%s\n' "$KEY_B64" >"$SECRETS/oracle_integration_encryption_keys"
  chown root:opn-oracle "$SECRETS/oracle_integration_encryption_keys"
  chmod 0440 "$SECRETS/oracle_integration_encryption_keys"
fi

MIGRATOR_PW="$(tr -d '\n' <"$SECRETS/postgres_migrator_password")"
APP_PW="$(tr -d '\n' <"$SECRETS/postgres_app_password")"
REDIS_PW="$(tr -d '\n' <"$SECRETS/redis_password")"

# SQL with password vars via env (psql -v)
sudo -u postgres psql -v ON_ERROR_STOP=1 \
  -v migrator_password="$MIGRATOR_PW" \
  -v app_password="$APP_PW" <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'oracle_migrator') THEN
    CREATE ROLE oracle_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOREPLICATION BYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'oracle_app') THEN
    CREATE ROLE oracle_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOREPLICATION NOBYPASSRLS;
  END IF;
END
$$;

ALTER ROLE oracle_migrator WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION BYPASSRLS PASSWORD :'migrator_password';
ALTER ROLE oracle_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD :'app_password';

SELECT format('CREATE DATABASE %I OWNER oracle_migrator ENCODING %L LOCALE %L TEMPLATE template0',
              'opn_oracle_dev', 'UTF8', 'C.UTF-8')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'opn_oracle_dev')\gexec

ALTER DATABASE opn_oracle_dev OWNER TO oracle_migrator;
SQL

sudo -u postgres psql -v ON_ERROR_STOP=1 -d opn_oracle_dev <<'SQL'
ALTER SCHEMA public OWNER TO oracle_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE opn_oracle_dev TO oracle_app;
SQL

# Risk DB (empty shell for later)
sudo -u postgres psql -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'risk_migrator') THEN
    CREATE ROLE risk_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION BYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'risk_app') THEN
    CREATE ROLE risk_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
  END IF;
END
$$;
SELECT format('CREATE DATABASE %I OWNER risk_migrator ENCODING %L LOCALE %L TEMPLATE template0',
              'opn_risk_advisor_dev', 'UTF8', 'C.UTF-8')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'opn_risk_advisor_dev')\gexec
SQL

# URL-encode helper for passwords in redis/pg URLs
python3 - <<'PY' "$SECRETS" "$MIGRATOR_PW" "$APP_PW" "$REDIS_PW"
import sys, urllib.parse, pathlib, os, grp
secrets = pathlib.Path(sys.argv[1])
migrator_pw, app_pw, redis_pw = sys.argv[2], sys.argv[3], sys.argv[4]
m = urllib.parse.quote(migrator_pw, safe="")
a = urllib.parse.quote(app_pw, safe="")
r = urllib.parse.quote(redis_pw, safe="")
files = {
  "oracle_database_url": f"postgresql+psycopg://oracle_app:{a}@127.0.0.1:5432/opn_oracle_dev",
  "oracle_database_migration_url": f"postgresql+psycopg://oracle_migrator:{m}@127.0.0.1:5432/opn_oracle_dev",
  "oracle_redis_url": f"redis://:{r}@127.0.0.1:6379/0",
  "oracle_session_redis_url": f"redis://:{r}@127.0.0.1:6379/1",
  "oracle_ratelimit_redis_url": f"redis://:{r}@127.0.0.1:6379/2",
  "oracle_celery_broker_url": f"redis://:{r}@127.0.0.1:6379/3",
  "oracle_celery_result_url": f"redis://:{r}@127.0.0.1:6379/4",
}
gid = grp.getgrnam("opn-oracle").gr_gid
for name, value in files.items():
    path = secrets / name
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(0o440)
    os.chown(path, 0, gid)
print("secret URL files written (contents not printed)")
PY

# Clear password vars
unset MIGRATOR_PW APP_PW REDIS_PW

log "Redis bind localhost + requirepass"
REDIS_CONF=/etc/redis/redis.conf
if [[ -f "$REDIS_CONF" ]]; then
  if [[ ! -f "${REDIS_CONF}.bak-pre-opn-native" ]]; then
    cp -a "$REDIS_CONF" "${REDIS_CONF}.bak-pre-opn-native"
  fi
  # bind loopback only
  if grep -qE '^\s*bind\s+' "$REDIS_CONF"; then
    sed -i 's/^\s*bind\s\+.*/bind 127.0.0.1 -::1/' "$REDIS_CONF"
  else
    echo 'bind 127.0.0.1 -::1' >>"$REDIS_CONF"
  fi
  sed -i 's/^\s*protected-mode\s\+.*/protected-mode yes/' "$REDIS_CONF" || true
  # requirepass
  RPW="$(tr -d '\n' <"$SECRETS/redis_password")"
  if grep -qE '^\s*requirepass\s+' "$REDIS_CONF"; then
    sed -i "s|^\s*requirepass\s\+.*|requirepass ${RPW}|" "$REDIS_CONF"
  else
    echo "requirepass ${RPW}" >>"$REDIS_CONF"
  fi
  unset RPW
  # supervised systemd
  sed -i 's/^\s*supervised\s\+.*/supervised systemd/' "$REDIS_CONF" || true
fi
systemctl enable --now redis-server
systemctl restart redis-server

log "Verify listeners not public"
ss -lntp | tee -a "$EVIDENCE"
if ss -lntp | grep -E ':(5432|6379)\s' | grep -vE '127\.0\.0\.1|::1|\[::1\]'; then
  log "ERROR: PostgreSQL/Redis appear bound beyond loopback"
  exit 1
fi

log "Nginx enable"
systemctl enable nginx
systemctl start nginx || true

log "=== bootstrap-host complete ==="
log "Evidence: $EVIDENCE"
