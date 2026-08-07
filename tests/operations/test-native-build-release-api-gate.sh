#!/usr/bin/env bash
# Behavioral regression: the exact helper used by the native release builder
# must stop continuation when the API unit gate fails.
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
gate_script="$repo_root/scripts/lib/native_release_api_gate.sh"
build_script="$repo_root/infra/native-dev/build-release.sh"
bash -n "$gate_script"
bash -n "$build_script"

work="$(mktemp -d "${TMPDIR:-/tmp}/test-native-build-release-api-gate.XXXXXX")"
cleanup() { rm -rf -- "$work"; }
trap cleanup EXIT
mkdir -p "$work/repo/apps/api" "$work/repo/scripts"

run_gate() {
  local api_exit="$1"
  local case_dir="$work/case-$api_exit"
  local invocation_file="$case_dir/invocation"
  local continued_file="$case_dir/materialization-reached"
  local runner="$case_dir/run.sh"
  mkdir -p "$case_dir"

  printf '%s\n' \
    '#!/usr/bin/env bash' \
    "printf '%s\\n' \"\$*\" >'$invocation_file'" \
    "exit $api_exit" \
    >"$work/repo/scripts/api-test.sh"
  chmod +x "$work/repo/scripts/api-test.sh"

  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'set -Eeuo pipefail' \
    "bash '$gate_script' '$work/repo'" \
    "touch '$continued_file'" \
    >"$runner"
  chmod +x "$runner"

  set +e
  bash "$runner" >"$case_dir/stdout" 2>"$case_dir/stderr"
  local runner_exit=$?
  set -e

  if [[ ! -f "$invocation_file" ]] || [[ "$(<"$invocation_file")" != "--unit" ]]; then
    echo "FAIL: api-test.sh no recibió exactamente --unit" >&2
    exit 1
  fi
  printf '%s\n' "$runner_exit"
}

failed_exit="$(run_gate 23)"
if [[ "$failed_exit" -eq 0 || -e "$work/case-23/materialization-reached" ]]; then
  echo "FAIL: la construcción continuó tras fallar el gate API" >&2
  exit 1
fi
if ! grep -Fq 'release build aborted before materialization' "$work/case-23/stderr"; then
  echo "FAIL: falta el diagnóstico explícito de aborto" >&2
  exit 1
fi

passed_exit="$(run_gate 0)"
if [[ "$passed_exit" -ne 0 || ! -e "$work/case-0/materialization-reached" ]]; then
  echo "FAIL: el gate bloqueó una suite API correcta" >&2
  exit 1
fi

echo "Gate API de build-release: fail-closed verificado por comportamiento."
