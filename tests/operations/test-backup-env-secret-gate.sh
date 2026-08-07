#!/usr/bin/env bash
# Focal: ORACLE_ENV_FILE gate accepts secure *_FILE references and rejects
# inline secrets / invalid file refs. Runs the real backup-production.sh with a
# docker stub so no Docker/backup production path is exercised.
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
script="$repo_root/scripts/backup-production.sh"
bash -n "$script"

work="$(mktemp -d "${TMPDIR:-/tmp}/test-backup-env-secret-gate.XXXXXX")"
cleanup() { rm -rf -- "$work"; }
trap cleanup EXIT

mkdir -p "$work/bin" "$work/secrets" "$work/backup" "$work/cases"
export PATH="$work/bin:$PATH"

# Docker stub: allow early `docker compose version`; anything else is past the
# env gate and must emit a stable marker without real compose/exec/dump.
cat >"$work/bin/docker" <<'STUB'
#!/usr/bin/env bash
if [[ "${1:-}" == "compose" && "${2:-}" == "version" ]]; then
  echo "Docker Compose version v2.29.0-stub"
  exit 0
fi
echo "SV2_GATE_SECRET_FILE_POST_ENV_MARKER" >&2
exit 99
STUB
chmod +x "$work/bin/docker"

secret_file="$work/secrets/graph_client_secret"
printf 'placeholder-not-a-real-secret\n' >"$secret_file"
chmod 0400 "$secret_file"

# Non-secret content that must never appear in script I/O.
SECRET_CONTENT='placeholder-not-a-real-secret'
INLINE_VALUE='dummy-inline-secret-value'

run_case() {
  local name="$1"
  local env_body="$2"
  local env_path="$work/cases/${name}.env"
  local out_stdout="$work/cases/${name}.stdout"
  local out_stderr="$work/cases/${name}.stderr"
  printf '%s\n' "$env_body" >"$env_path"
  set +e
  ORACLE_ENV_FILE="$env_path" ORACLE_BACKUP_ROOT="$work/backup" \
    bash "$script" --create >"$out_stdout" 2>"$out_stderr"
  local ec=$?
  set -e
  printf '%s\n' "$ec" >"$work/cases/${name}.exit"
  # Never allow secret material to leak into I/O.
  if grep -Fq -- "$SECRET_CONTENT" "$out_stdout" "$out_stderr" 2>/dev/null; then
    echo "FAIL $name: contenido del secret file filtrado en salida" >&2
    exit 1
  fi
  if grep -Fq -- "$INLINE_VALUE" "$out_stdout" "$out_stderr" 2>/dev/null; then
    echo "FAIL $name: valor inline filtrado en salida" >&2
    exit 1
  fi
  # Snapshot path is only created after docker dump; ensure none was written.
  if find "$work/backup" -mindepth 1 -print -quit 2>/dev/null | grep -q .; then
    echo "FAIL $name: se escribió bajo ORACLE_BACKUP_ROOT (producción/backup no permitido en test)" >&2
    exit 1
  fi
  return 0
}

expect_exit() {
  local name="$1"
  local want="$2"
  local got
  got="$(cat "$work/cases/${name}.exit")"
  if [[ "$got" != "$want" ]]; then
    echo "FAIL $name: exit esperado $want, obtenido $got" >&2
    echo "--- stderr ---" >&2
    cat "$work/cases/${name}.stderr" >&2
    exit 1
  fi
}

expect_stderr_match() {
  local name="$1"
  local pattern="$2"
  if ! grep -Eq -- "$pattern" "$work/cases/${name}.stderr"; then
    echo "FAIL $name: stderr no coincide /$pattern/" >&2
    cat "$work/cases/${name}.stderr" >&2
    exit 1
  fi
}

expect_no_marker() {
  local name="$1"
  if grep -Fq 'SV2_GATE_SECRET_FILE_POST_ENV_MARKER' "$work/cases/${name}.stderr" \
    "$work/cases/${name}.stdout" 2>/dev/null; then
    echo "FAIL $name: llegó al marcador post-env (no debió superar el gate)" >&2
    exit 1
  fi
}

expect_marker() {
  local name="$1"
  if ! grep -Fq 'SV2_GATE_SECRET_FILE_POST_ENV_MARKER' "$work/cases/${name}.stderr"; then
    echo "FAIL $name: no llegó al marcador post-env tras el gate" >&2
    cat "$work/cases/${name}.stderr" >&2
    exit 1
  fi
}

base_env() {
  printf 'ORACLE_RELEASE=test-release-gate\n'
  printf 'ORACLE_SECRETS_DIR=%s\n' "$work/secrets"
}

# --- Positive: valid sensitive *_FILE reference passes env gate ---
run_case "good_file_ref" "$(
  base_env
  printf 'GRAPH_CLIENT_SECRET_FILE=%s\n' "$secret_file"
)"
expect_exit "good_file_ref" 99
expect_marker "good_file_ref"
expect_stderr_match "good_file_ref" 'SV2_GATE_SECRET_FILE_POST_ENV_MARKER'

# --- Inline secret still fails before docker/dump ---
run_case "inline_secret" "$(
  base_env
  printf 'GRAPH_CLIENT_SECRET=%s\n' "$INLINE_VALUE"
)"
expect_exit "inline_secret" 2
expect_no_marker "inline_secret"
expect_stderr_match "inline_secret" 'posible secreto inline: GRAPH_CLIENT_SECRET'

# --- Parametrized negatives for sensitive *_FILE ---
run_case "empty_file_ref" "$(
  base_env
  printf 'GRAPH_CLIENT_SECRET_FILE=\n'
)"
expect_exit "empty_file_ref" 2
expect_no_marker "empty_file_ref"
expect_stderr_match "empty_file_ref" 'referencia de fichero vacía para GRAPH_CLIENT_SECRET_FILE'

run_case "relative_file_ref" "$(
  base_env
  printf 'GRAPH_CLIENT_SECRET_FILE=relative/not/absolute\n'
)"
expect_exit "relative_file_ref" 2
expect_no_marker "relative_file_ref"
expect_stderr_match "relative_file_ref" 'debe ser una ruta absoluta'

run_case "inline_as_file_ref" "$(
  base_env
  printf 'GRAPH_CLIENT_SECRET_FILE=%s\n' "$INLINE_VALUE"
)"
expect_exit "inline_as_file_ref" 2
expect_no_marker "inline_as_file_ref"
expect_stderr_match "inline_as_file_ref" 'debe ser una ruta absoluta'

missing_path="$work/secrets/does-not-exist"
run_case "missing_file_ref" "$(
  base_env
  printf 'GRAPH_CLIENT_SECRET_FILE=%s\n' "$missing_path"
)"
expect_exit "missing_file_ref" 2
expect_no_marker "missing_file_ref"
expect_stderr_match "missing_file_ref" 'debe apuntar a un fichero regular legible'

dir_path="$work/secrets"
run_case "directory_file_ref" "$(
  base_env
  printf 'GRAPH_CLIENT_SECRET_FILE=%s\n' "$dir_path"
)"
expect_exit "directory_file_ref" 2
expect_no_marker "directory_file_ref"
expect_stderr_match "directory_file_ref" 'debe apuntar a un fichero regular legible'

# Unreadable regular file (skip if running as root; chmod may not block).
unreadable="$work/secrets/unreadable_secret"
printf 'placeholder-not-a-real-secret\n' >"$unreadable"
chmod 0000 "$unreadable"
if [[ "$(id -u)" -ne 0 ]] && [[ ! -r "$unreadable" ]]; then
  run_case "unreadable_file_ref" "$(
    base_env
    printf 'GRAPH_CLIENT_SECRET_FILE=%s\n' "$unreadable"
  )"
  expect_exit "unreadable_file_ref" 2
  expect_no_marker "unreadable_file_ref"
  expect_stderr_match "unreadable_file_ref" 'debe apuntar a un fichero regular legible'
else
  echo "SKIP unreadable_file_ref (root or still readable)"
fi
chmod 0400 "$unreadable" 2>/dev/null || true

symlink_path="$work/secrets/graph_client_secret.link"
ln -s "$secret_file" "$symlink_path"
run_case "symlink_file_ref" "$(
  base_env
  printf 'GRAPH_CLIENT_SECRET_FILE=%s\n' "$symlink_path"
)"
expect_exit "symlink_file_ref" 2
expect_no_marker "symlink_file_ref"
expect_stderr_match "symlink_file_ref" 'no puede ser un enlace simbólico'

# False suffix: sensitive name contains FILE but does not end in _FILE.
run_case "false_suffix" "$(
  base_env
  printf 'GRAPH_CLIENT_SECRET_FILE_BACKUP=%s\n' "$secret_file"
)"
expect_exit "false_suffix" 2
expect_no_marker "false_suffix"
expect_stderr_match "false_suffix" 'posible secreto inline: GRAPH_CLIENT_SECRET_FILE_BACKUP'

# ORACLE_SECRETS_DIR remains allowed (existing contract).
run_case "secrets_dir_ok" "$(
  printf 'ORACLE_RELEASE=test-release-gate\n'
  printf 'ORACLE_SECRETS_DIR=%s\n' "$work/secrets"
)"
expect_exit "secrets_dir_ok" 99
expect_marker "secrets_dir_ok"

# Decision: non-sensitive *_FILE keys are NOT forced through the secret-file
# reference gate (only names matching SECRET|PASSWORD|TOKEN|PRIVATE|CREDENTIAL
# are). A non-sensitive path variable must still pass the env parser.
run_case "nonsensitive_file_key" "$(
  base_env
  printf 'ORACLE_CONFIG_FILE=/etc/opn-oracle/oracle.env\n'
)"
expect_exit "nonsensitive_file_key" 99
expect_marker "nonsensitive_file_key"

# Redacted snapshot path is not created in this stubbed run (post-env only).
# Extra leak check over the whole work tree artefacts we control:
if grep -RFq -- "$SECRET_CONTENT" "$work/cases" 2>/dev/null; then
  # env files intentionally contain only paths, not content; content must not appear
  if grep -RFl -- "$SECRET_CONTENT" "$work/cases" | grep -Ev '\.secret$|graph_client_secret' >/dev/null; then
    echo "FAIL: secret content found in case artefacts" >&2
    exit 1
  fi
fi
if grep -RFq -- "$INLINE_VALUE" "$work/cases"/*.stdout "$work/cases"/*.stderr 2>/dev/null; then
  echo "FAIL: inline secret value found in case I/O" >&2
  exit 1
fi

echo "Gate ORACLE_ENV_FILE *_FILE: todos los casos focales correctos."
