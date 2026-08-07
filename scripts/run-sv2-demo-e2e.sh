#!/usr/bin/env bash
# SV2-E2E-CAMINO — un comando para el recorrido UI de la demo contra oracle-dev.
#
# Uso:
#   bash scripts/run-sv2-demo-e2e.sh
#   bash scripts/run-sv2-demo-e2e.sh --repeat 2
#
# Credenciales: se leen del host oracle-dev (nunca del repo):
#   /root/sv2_demo_owner_credentials.txt
#
# Variables opcionales:
#   ORACLE_SSH              default root@oracle-dev.opnconsultoria.com
#   ORACLE_CREDS_PATH       default /root/sv2_demo_owner_credentials.txt
#   PLAYWRIGHT_BASE_URL     default https://oracle-dev.opnconsultoria.com
#   ORACLE_E2E_EMAIL / ORACLE_E2E_PASSWORD  (si ya están exportadas, no usa SSH)
#   ORACLE_E2E_TENANT_LABEL default "SV2 Demo Tenant"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ORACLE_SSH="${ORACLE_SSH:-root@oracle-dev.opnconsultoria.com}"
ORACLE_CREDS_PATH="${ORACLE_CREDS_PATH:-/root/sv2_demo_owner_credentials.txt}"
export PLAYWRIGHT_BASE_URL="${PLAYWRIGHT_BASE_URL:-https://oracle-dev.opnconsultoria.com}"
export ORACLE_E2E_TENANT_LABEL="${ORACLE_E2E_TENANT_LABEL:-SV2 Demo Tenant}"

REPEAT=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repeat)
      REPEAT="${2:?}"
      shift 2
      ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *)
      echo "Argumento desconocido: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${ORACLE_E2E_EMAIL:-}" || -z "${ORACLE_E2E_PASSWORD:-}" ]]; then
  echo "[run-sv2-demo-e2e] leyendo credenciales demo via SSH ${ORACLE_SSH}:${ORACLE_CREDS_PATH}"
  CREDS="$(
    ssh -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new \
      "$ORACLE_SSH" "cat $(printf %q "$ORACLE_CREDS_PATH")"
  )"
  export ORACLE_E2E_EMAIL
  export ORACLE_E2E_PASSWORD
  ORACLE_E2E_EMAIL="$(printf '%s\n' "$CREDS" | awk -F= '/^email=/{print substr($0,7); exit}')"
  ORACLE_E2E_PASSWORD="$(printf '%s\n' "$CREDS" | awk -F= '/^password=/{print substr($0,10); exit}')"
  if [[ -z "$ORACLE_E2E_EMAIL" || -z "$ORACLE_E2E_PASSWORD" ]]; then
    echo "No se pudo parsear email/password de ${ORACLE_CREDS_PATH}" >&2
    exit 1
  fi
fi

echo "[run-sv2-demo-e2e] baseURL=${PLAYWRIGHT_BASE_URL}"
echo "[run-sv2-demo-e2e] credenciales=loaded"
echo "[run-sv2-demo-e2e] repeat=${REPEAT}"

# Resolver binario de Playwright (worktree local o monorepo padre).
PW_BIN=""
for cand in \
  "$ROOT/node_modules/.bin/playwright" \
  "$ROOT/../node_modules/.bin/playwright" \
  "$ROOT/../../node_modules/.bin/playwright"; do
  if [[ -x "$cand" ]]; then
    PW_BIN="$cand"
    break
  fi
done
if [[ -z "$PW_BIN" ]]; then
  echo "No se encontró @playwright/test. Ejecuta npm ci en el checkout Oracle." >&2
  exit 1
fi

# Asegura browsers Chromium de Playwright (idempotente).
"$PW_BIN" install chromium >/dev/null 2>&1 || true

FAILED=0
run_once() {
  local n="$1"
  echo ""
  echo "========== SV2-E2E-CAMINO run ${n}/${REPEAT} =========="
  if "$PW_BIN" test tests/e2e/sv2-demo-walkthrough.spec.ts \
    --project=sv2-demo \
    --reporter=list; then
    echo "[run-sv2-demo-e2e] run ${n}: PASS"
  else
    echo "[run-sv2-demo-e2e] run ${n}: FAIL"
    FAILED=1
  fi
}

for ((i = 1; i <= REPEAT; i++)); do
  run_once "$i"
done

echo ""
if [[ "$FAILED" -eq 0 ]]; then
  echo "[run-sv2-demo-e2e] OK (${REPEAT} corrida(s))"
  exit 0
fi
echo "[run-sv2-demo-e2e] FALLO en al menos una de ${REPEAT} corrida(s)"
exit 1
