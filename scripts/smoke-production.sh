#!/usr/bin/env bash
set -euo pipefail

base_url="${1:-https://oracle.opnconsultoria.com}"
base_url="${base_url%/}"
api_base_url="${ORACLE_API_BASE_URL:-$base_url}"
api_base_url="${api_base_url%/}"

validate_target() {
  case "$1" in
    https://*) ;;
    http://127.0.0.1:*|http://localhost:*)
      if [[ "${ALLOW_HTTP_SMOKE:-0}" != "1" ]]; then
        echo "El smoke HTTP local exige ALLOW_HTTP_SMOKE=1." >&2
        exit 2
      fi
      ;;
    *)
      echo "El destino debe usar HTTPS o ser loopback HTTP autorizado explícitamente." >&2
      exit 2
      ;;
  esac
}

validate_target "$base_url"
validate_target "$api_base_url"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Falta el comando requerido: $1" >&2
    exit 2
  }
}

require_command curl

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

curl_common=(--fail --silent --show-error --connect-timeout 5 --max-time 15)

curl "${curl_common[@]}" "$api_base_url/health/live" >"$tmp_dir/live.json"
grep -Eq '"status"[[:space:]]*:[[:space:]]*"(ok|live)"' "$tmp_dir/live.json" || {
  echo "La respuesta de liveness no contiene un estado válido." >&2
  exit 1
}

curl "${curl_common[@]}" "$api_base_url/api/v1/meta" >"$tmp_dir/meta.json"
grep -q '"capabilities"' "$tmp_dir/meta.json" || {
  echo "La API meta no devolvió el contrato esperado." >&2
  exit 1
}

curl "${curl_common[@]}" --dump-header "$tmp_dir/login.headers" --output /dev/null \
  "$base_url/login"
for header in x-content-type-options referrer-policy permissions-policy; do
  grep -Eiq "^${header}:" "$tmp_dir/login.headers" || {
    echo "Falta la cabecera ${header} en /login." >&2
    exit 1
  }
done
grep -Eiq '^cache-control:.*no-store' "$tmp_dir/login.headers" || {
  echo "La página de login no declara no-store." >&2
  exit 1
}

if [[ "$api_base_url" == "$base_url" ]]; then
  metrics_code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --connect-timeout 5 --max-time 15 "$base_url/internal/metrics")"
  if [[ "$metrics_code" != "404" ]]; then
    echo "La ruta pública de métricas devolvió ${metrics_code}; se esperaba 404." >&2
    exit 1
  fi
  echo "Smoke público correcto: liveness, meta, headers de login y métricas ocultas."
else
  echo "Smoke loopback correcto: liveness/meta de API y headers de login web."
fi
