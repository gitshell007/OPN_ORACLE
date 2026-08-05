#!/usr/bin/env bash
# Build immutable native release on the host from a verified git SHA.
# Deploy channel for https://oracle-dev.opnconsultoria.com is branch oracle-dev.
# Usage: build-release.sh <git-sha>
# Optional: ORACLE_DEPLOY_BRANCH=oracle-dev (default) — fetched before checkout.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "must run as root" >&2
  exit 1
fi

SHA="${1:?git sha required}"
DEPLOY_BRANCH="${ORACLE_DEPLOY_BRANCH:-oracle-dev}"
SHORT="$(printf '%s' "$SHA" | cut -c1-7)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
RELEASE_ID="${TS}-native-${SHORT}"
BUILD_ROOT="/opt/src/oracle-build"
REPO_DIR="${BUILD_ROOT}/repo"
RELEASE_DIR="/opt/opn-oracle/releases/${RELEASE_ID}"
KEY="${ORACLE_DEPLOY_SSH_KEY:-/root/.ssh/id_ed25519_signal_dev_github}"
KNOWN_HOSTS="${BUILD_ROOT}/github_known_hosts"

mkdir -p "$BUILD_ROOT" "$(dirname "$KNOWN_HOSTS")"
ssh-keyscan -t ed25519,rsa github.com 2>/dev/null >"$KNOWN_HOSTS"
export GIT_SSH_COMMAND="ssh -i ${KEY} -o IdentitiesOnly=yes -o BatchMode=yes -o UserKnownHostsFile=${KNOWN_HOSTS} -o StrictHostKeyChecking=yes"

if [[ ! -d "$REPO_DIR/.git" ]]; then
  git clone --filter=blob:none git@github.com:gitshell007/OPN_ORACLE.git "$REPO_DIR"
fi
git -C "$REPO_DIR" fetch --all --tags --prune
# Prefer the deploy branch tip history; still pin the exact SHA for immutability.
git -C "$REPO_DIR" fetch origin "+refs/heads/${DEPLOY_BRANCH}:refs/remotes/origin/${DEPLOY_BRANCH}" 2>/dev/null || true
git -C "$REPO_DIR" checkout --force "$SHA"
git -C "$REPO_DIR" reset --hard "$SHA"
ACTUAL="$(git -C "$REPO_DIR" rev-parse HEAD)"
if [[ "$ACTUAL" != "$SHA" && "$ACTUAL" != "$(git -C "$REPO_DIR" rev-parse "$SHA")" ]]; then
  echo "SHA mismatch: expected $SHA got $ACTUAL" >&2
  exit 1
fi
ACTUAL="$(git -C "$REPO_DIR" rev-parse HEAD)"
# Soft guard: warn if SHA is not an ancestor of origin/oracle-dev (still allow explicit override).
if git -C "$REPO_DIR" rev-parse --verify "origin/${DEPLOY_BRANCH}" >/dev/null 2>&1; then
  if ! git -C "$REPO_DIR" merge-base --is-ancestor "$ACTUAL" "origin/${DEPLOY_BRANCH}"; then
    if [[ "${ORACLE_ALLOW_OFF_BRANCH_SHA:-0}" != "1" ]]; then
      echo "ERROR: SHA $ACTUAL is not on origin/${DEPLOY_BRANCH}. Set ORACLE_ALLOW_OFF_BRANCH_SHA=1 to override." >&2
      exit 1
    fi
    echo "WARNING: SHA $ACTUAL is not on origin/${DEPLOY_BRANCH} (override enabled)" >&2
  fi
fi
echo "Building release $RELEASE_ID from $ACTUAL (branch channel: ${DEPLOY_BRANCH})"

# Clean worktree artifacts that must not enter release
rm -rf "$REPO_DIR/node_modules" "$REPO_DIR/apps/api/.venv" "$REPO_DIR/.next" \
  "$REPO_DIR/apps/api/.env" "$REPO_DIR/.env" 2>/dev/null || true

cd "$REPO_DIR"

echo "== frontend install =="
npm ci
echo "== frontend lint =="
npm run lint
echo "== frontend typecheck =="
npm run typecheck
echo "== frontend unit tests =="
npm run test -- --run
echo "== api client check =="
npm run api:client:check
echo "== frontend build =="
NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 npm run build

echo "== api uv sync =="
cd "$REPO_DIR/apps/api"
uv sync --frozen
echo "== api unit tests =="
cd "$REPO_DIR"
if [[ -x scripts/api-test.sh ]]; then
  bash scripts/api-test.sh --unit || {
    echo "api-test.sh --unit failed; continuing only if env lacks DB (dev host will re-run post-import)" >&2
    # On a host without test DB this may fail; require success when ORACLE_REQUIRE_API_UNIT=1
    if [[ "${ORACLE_REQUIRE_API_UNIT:-0}" == "1" ]]; then
      exit 1
    fi
  }
fi

echo "== materialize release tree =="
install -d -m 0750 -o root -g opn-oracle "$RELEASE_DIR"
# Export clean tree without .git, node_modules, venv, caches
rsync -a \
  --exclude '.git/' \
  --exclude 'node_modules/' \
  --exclude 'apps/api/.venv/' \
  --exclude '.next/' \
  --exclude '.env' \
  --exclude '**/.env' \
  --exclude '**/.pytest_cache/' \
  --exclude '**/__pycache__/' \
  --exclude '.mypy_cache/' \
  --exclude 'coverage/' \
  --exclude 'htmlcov/' \
  --exclude 'playwright-report/' \
  --exclude 'test-results/' \
  "$REPO_DIR/" "$RELEASE_DIR/"

# Copy built Next standalone runtime
install -d -m 0750 -o root -g opn-oracle "$RELEASE_DIR/.next/standalone"
rsync -a "$REPO_DIR/.next/standalone/" "$RELEASE_DIR/.next/standalone/"
install -d -m 0750 -o root -g opn-oracle "$RELEASE_DIR/.next/standalone/.next/static"
rsync -a "$REPO_DIR/.next/static/" "$RELEASE_DIR/.next/standalone/.next/static/"
if [[ -d "$REPO_DIR/public" ]]; then
  rsync -a "$REPO_DIR/public/" "$RELEASE_DIR/.next/standalone/public/"
fi
# Keep non-standalone .next/static for reference if needed
rsync -a "$REPO_DIR/.next/static/" "$RELEASE_DIR/.next/static/"

# Recreate API venv inside the release tree so shebangs point at release paths
# (copying .venv from the build checkout leaves absolute paths under /opt/src/...).
(
  cd "$RELEASE_DIR/apps/api"
  rm -rf .venv
  # Interpreters managed under /opt/uv-python (readable by service user), never under /root.
  export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-/opt/uv-python}"
  uv python install 3.12 >/dev/null
  uv sync --frozen --python 3.12
)

# Metadata
printf '%s\n' "$ACTUAL" >"$RELEASE_DIR/RELEASE_GIT_SHA"
printf '%s\n' "$RELEASE_ID" >"$RELEASE_DIR/RELEASE_ID"
printf '%s\n' "$TS" >"$RELEASE_DIR/RELEASE_BUILT_AT"
chown -R root:opn-oracle "$RELEASE_DIR"
find "$RELEASE_DIR" -type d -exec chmod 0750 {} +
# Keep venv executables runnable
find "$RELEASE_DIR/apps/api/.venv/bin" -type f -exec chmod 0750 {} + 2>/dev/null || true

(
  cd "$RELEASE_DIR"
  find . -type f ! -name 'RELEASE_SHA256SUMS' -print0 | sort -z | xargs -0 sha256sum >RELEASE_SHA256SUMS
)
chown root:opn-oracle "$RELEASE_DIR/RELEASE_SHA256SUMS"
chmod 0640 "$RELEASE_DIR/RELEASE_SHA256SUMS"

echo "Release ready: $RELEASE_DIR"
# NEVER activate with bare `ln -sfn` alone: that diverges oracle.env (ORACLE_RELEASE/
# RELEASE) from the code symlink and makes /api/v1/meta lie (SV2-SANEO-ANIDADO).
echo "Activate with: bash ${RELEASE_DIR}/infra/native-dev/activate-release.sh ${RELEASE_ID}"
echo "  (symlink + env + CURRENT_RELEASE updated together; fails loud on divergence)"
