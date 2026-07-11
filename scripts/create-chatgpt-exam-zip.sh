#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${1:-${ROOT_DIR}/dist}"
OUTPUT_FILE="${OUTPUT_DIR}/opn-oracle-chatgpt-exam.zip"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/opn-oracle-exam.XXXXXX")"

cleanup() {
  rm -rf "${STAGING_DIR}"
}
trap cleanup EXIT

if ! command -v zip >/dev/null 2>&1; then
  echo "Error: se necesita el comando 'zip'." >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIR}" "${STAGING_DIR}/OPN_ORACLE"

FILES=(
  .dockerignore
  AGENTS.md
  Dockerfile.web
  README.md
  README_UI_PROTOTYPES.md
  01_IMPLEMENTATION_PLAN.md
  compose.dev.yml
  compose.prod.yml
  package.json
  package-lock.json
  tsconfig.json
  next-env.d.ts
  next.config.ts
  eslint.config.mjs
  playwright.config.ts
  vitest.config.ts
  vitest.setup.ts
)

DIRECTORIES=(
  src
  tests
  packages
  docs
  infra
)

for file in "${FILES[@]}"; do
  if [[ ! -f "${ROOT_DIR}/${file}" ]]; then
    echo "Error: falta el archivo necesario ${file}." >&2
    exit 1
  fi
  cp "${ROOT_DIR}/${file}" "${STAGING_DIR}/OPN_ORACLE/${file}"
done

for directory in "${DIRECTORIES[@]}"; do
  cp -R "${ROOT_DIR}/${directory}" "${STAGING_DIR}/OPN_ORACLE/${directory}"
done

mkdir -p "${STAGING_DIR}/OPN_ORACLE/apps/api" "${STAGING_DIR}/OPN_ORACLE/scripts"

API_FILES=(
  .dockerignore
  Dockerfile
  Makefile
  README.md
  gunicorn.conf.py
  pyproject.toml
  uv.lock
)
for file in "${API_FILES[@]}"; do
  cp "${ROOT_DIR}/apps/api/${file}" "${STAGING_DIR}/OPN_ORACLE/apps/api/${file}"
done
cp -R "${ROOT_DIR}/apps/api/src" "${STAGING_DIR}/OPN_ORACLE/apps/api/src"
cp -R "${ROOT_DIR}/apps/api/tests" "${STAGING_DIR}/OPN_ORACLE/apps/api/tests"
cp -R "${ROOT_DIR}/apps/api/migrations" "${STAGING_DIR}/OPN_ORACLE/apps/api/migrations"

SCRIPT_FILES=(
  backup-host-agent.sh
  backup-maintenance.sh
  backup-production.sh
  capture-ui.mjs
  create-chatgpt-exam-zip.sh
  deploy-production.sh
  enqueue-scheduled-backup.sh
  install-backup-systemd.sh
  oracle-control.sh
  restore-production.sh
  restore-test-production.sh
  run-auth-e2e-api.sh
  run-quality-scans.sh
  smoke-production.sh
)
for file in "${SCRIPT_FILES[@]}"; do
  cp "${ROOT_DIR}/scripts/${file}" "${STAGING_DIR}/OPN_ORACLE/scripts/${file}"
done

find "${STAGING_DIR}" \( -path '*/docs/ui-prototypes' -o -name '._*' -o -name '.DS_Store' -o -name '.env' -o -name '.env.*' -o -name '.venv' -o -name 'node_modules' -o -name '.next' -o -name '.git' -o -name '.idea' -o -name '__pycache__' -o -name '.pytest_cache' -o -name '.mypy_cache' -o -name '.ruff_cache' -o -name '.coverage' -o -name 'test-results' \) -prune -exec rm -rf {} +
rm -f "${OUTPUT_FILE}"

(
  cd "${STAGING_DIR}"
  COPYFILE_DISABLE=1 zip -q -r "${OUTPUT_FILE}" OPN_ORACLE
)

echo "ZIP creado: ${OUTPUT_FILE}"
echo "Contenido: código fuente, configuración, documentación y tests; sin dependencias, cachés, capturas ni archivos del IDE."
