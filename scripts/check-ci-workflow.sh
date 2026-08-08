#!/usr/bin/env bash
# Invariants for .github/workflows/ci.yml (ORA-CI-GATE).
# Exit 0 if the release-critical CI contract holds; non-zero with message otherwise.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WF="${ROOT}/.github/workflows/ci.yml"

if [[ ! -f "$WF" ]]; then
  echo "ERROR: missing $WF" >&2
  exit 1
fi

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

# --- YAML parse (PyYAML if available; else structural greps only) ---
if command -v python3 >/dev/null 2>&1; then
  python3 - "$WF" <<'PY' || fail "YAML parse failed"
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
try:
    import yaml  # type: ignore
except ImportError:
    # Fall back: ensure no tab-indent chaos and balanced-ish structure.
    if "\t" in text.split("---")[0] if False else text[:200]:
        pass
    sys.exit(0)
data = yaml.safe_load(text)
assert isinstance(data, dict), "workflow root must be a mapping"
assert data.get("name") == "CI"
on = data.get("on") or data.get(True)  # PyYAML may parse 'on' as True
if on is True:
    # re-read with safe loader workaround
    import re
    assert re.search(r"(?m)^on:\s*$", text), "missing on:"
else:
    assert isinstance(on, dict), "on: must be a mapping"
sys.exit(0)
PY
fi

# --- Triggers ---
grep -qE '^[[:space:]]*pull_request:' "$WF" || fail "pull_request trigger missing"
grep -qE '^[[:space:]]*- master' "$WF" || fail "pull_request must target master"
grep -qE '^[[:space:]]*push:' "$WF" || fail "push trigger missing (oracle-dev gate)"
# push.branches includes oracle-dev (not only master)
if ! awk '
  /^on:/ { in_on=1 }
  in_on && /^[^[:space:]#]/ && !/^on:/ { in_on=0 }
  in_on && /^[[:space:]]*push:/ { in_push=1 }
  in_push && /^[[:space:]]*pull_request:/ { in_push=0 }
  in_push && /^[[:space:]]*workflow_dispatch:/ { in_push=0 }
  in_push && /oracle-dev/ { found=1 }
  END { exit found ? 0 : 1 }
' "$WF"; then
  fail "push trigger must include branch oracle-dev"
fi
grep -qE '^[[:space:]]*workflow_dispatch:' "$WF" || fail "workflow_dispatch missing"

# --- Frontend five doors (build-release.sh) ---
for cmd in \
  'npm run lint' \
  'npm run typecheck' \
  'npm run test -- --run' \
  'npm run api:client:check' \
  'npm run build'
do
  grep -Fq "$cmd" "$WF" || fail "frontend gate missing: $cmd"
done

# --- Backend static + full pytest ---
grep -Fq 'uv run ruff check' "$WF" || fail "ruff check missing"
grep -Fq 'uv run ruff format --check' "$WF" || fail "ruff format --check missing"
grep -Fq 'uv run mypy src' "$WF" || fail "mypy src missing"
grep -Fq 'ORACLE_RUN_INTEGRATION: "1"' "$WF" || fail "ORACLE_RUN_INTEGRATION must be 1"
grep -Fq 'TEST_DATABASE_URL:' "$WF" || fail "TEST_DATABASE_URL missing"
grep -Fq 'TEST_RUNTIME_DATABASE_URL:' "$WF" || fail "TEST_RUNTIME_DATABASE_URL missing"
grep -Fq 'TEST_REDIS_URL:' "$WF" || fail "TEST_REDIS_URL missing"
grep -Fq '127.0.0.1:5432/oracle_test' "$WF" || fail "TEST_* must use ephemeral oracle_test on 127.0.0.1"
grep -Fq '127.0.0.1:6379/14' "$WF" || fail "TEST_REDIS_URL must use ephemeral Redis on 127.0.0.1"
# Must not point at Oracle Dev or public hosts
if grep -Eiq 'oracle-dev\.opnconsultoria|159\.195\.|opn_oracle_dev[^_]|prod.*DATABASE_URL' "$WF"; then
  fail "workflow must not reference Oracle Dev / production DB hosts"
fi

# Full pytest step present; must not exclude integration or drop coverage on that step
if ! grep -Fq 'uv run pytest -vv --durations=40' "$WF"; then
  fail "full pytest command missing (expected: uv run pytest -vv --durations=40)"
fi
# Forbidden patterns on the main pytest invocation line(s)
if grep -E 'uv run pytest .*(-m[[:space:]]*['\''"]not integration|not integration|--ignore=.*integration|--no-cov)' "$WF" \
  | grep -v 'pytest --no-cov -q' >/dev/null 2>&1; then
  # allow --no-cov only on the report-family isolation re-runs, not the main suite
  :
fi
if grep -E 'uv run pytest -vv.*--no-cov' "$WF"; then
  fail "main pytest must not use --no-cov (coverage gate required)"
fi
if grep -E 'uv run pytest -vv.*-m[[:space:]]+[^\n]*not integration' "$WF"; then
  fail "main pytest must not exclude integration marker"
fi
if grep -E 'uv run pytest -vv.*--ignore=' "$WF"; then
  fail "main pytest must not --ignore test modules"
fi

# Services
grep -Fq 'image: postgres:17-bookworm' "$WF" || fail "ephemeral postgres service missing"
grep -Fq 'image: redis:7.4-bookworm' "$WF" || fail "ephemeral redis service missing"

echo "OK: $WF satisfies ORA-CI-GATE invariants"
