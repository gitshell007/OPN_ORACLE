#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
TMP_REQUIREMENTS=$(mktemp)
trap 'rm -f "$TMP_REQUIREMENTS"' EXIT

cd "$ROOT"

echo "[1/5] npm audit (high/critical gate)"
npm audit --audit-level=high

echo "[2/5] Python dependency audit from the frozen lock"
(
  cd apps/api
  uv export --quiet --frozen --no-dev --no-hashes --no-emit-project \
    --output-file "$TMP_REQUIREMENTS"
)
uvx --from pip-audit==2.9.0 pip-audit --requirement "$TMP_REQUIREMENTS" --progress-spinner=off

echo "[3/5] Semgrep reviewed local rules"
semgrep scan --config docs/security/semgrep.yml --error --severity ERROR \
  apps/api/src src packages next.config.ts

echo "[4/5] High-confidence secret patterns"
if rg -n --hidden \
  --glob '!.git/**' --glob '!node_modules/**' --glob '!.next/**' \
  --glob '!*.lock' --glob '!docs/api/openapi.json' \
  --glob '!packages/api-client/src/generated/schema.ts' \
  --glob '!docs/security/semgrep.yml' --glob '!scripts/run-quality-scans.sh' \
  -e '-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----' \
  -e 'AKIA[0-9A-Z]{16}' \
  -e 'gh[pousr]_[A-Za-z0-9]{36,}' \
  -e 'sk-(live|proj)-[A-Za-z0-9_-]{20,}' .; then
  echo "Possible high-confidence secret found; triage before continuing." >&2
  exit 1
fi

echo "[5/5] Container scanner"
if command -v trivy >/dev/null 2>&1; then
  trivy fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --exit-code 1 apps/api
elif [ "${STRICT_CONTAINER_SCAN:-0}" = "1" ]; then
  echo "trivy is required when STRICT_CONTAINER_SCAN=1." >&2
  exit 2
else
  echo "SKIP: trivy is unavailable; container/image scan remains a phase 14-15 gate."
fi

echo "Quality scans completed."
