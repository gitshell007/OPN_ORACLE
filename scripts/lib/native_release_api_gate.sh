#!/usr/bin/env bash
# Fail-closed API gate shared by the native release builder and its behavioral test.
set -Eeuo pipefail

repo_dir="${1:?repository directory required}"
if [[ ! -d "$repo_dir/apps/api" || ! -f "$repo_dir/scripts/api-test.sh" ]]; then
  echo "ERROR: invalid Oracle repository for native API gate: $repo_dir" >&2
  exit 64
fi

cd "$repo_dir"
if ! bash scripts/api-test.sh --unit; then
  echo "ERROR: api-test.sh --unit failed; release build aborted before materialization." >&2
  exit 1
fi
