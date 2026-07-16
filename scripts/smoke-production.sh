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
curl_status=(--silent --show-error --output /dev/null --write-out '%{http_code}' \
  --connect-timeout 5 --max-time 15)

require_status() {
  local label="$1"
  local url="$2"
  local expected="$3"
  local code
  code="$(curl "${curl_status[@]}" "$url")"
  if [[ "$code" != "$expected" ]]; then
    echo "${label} devolvió ${code}; se esperaba ${expected}." >&2
    exit 1
  fi
}

require_protected_api() {
  local label="$1"
  local url="$2"
  local expected="$3"
  local code
  code="$(curl "${curl_status[@]}" "$url")"
  case "$code" in
    301|302|303|307|308)
      echo "${label} redirige (${code}); una API JSON debe devolver 401/403, no login HTML." >&2
      exit 1
      ;;
    404)
      echo "${label} devolvió 404; el blueprint no parece registrado." >&2
      exit 1
      ;;
    5*)
      echo "${label} devolvió ${code}; la aplicación no está sana." >&2
      exit 1
      ;;
  esac
  if [[ "$code" != "$expected" ]]; then
    echo "${label} devolvió ${code}; se esperaba ${expected} para anónimo." >&2
    exit 1
  fi
}

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
if ! grep -Eiq '^cache-control:.*no-store' "$tmp_dir/login.headers"; then
  if [[ "${ALLOW_HTTP_SMOKE:-0}" == "1" ]] \
    && grep -Eiq '^cache-control:.*no-cache' "$tmp_dir/login.headers"; then
    :
  else
    echo "La página de login no declara no-store." >&2
    exit 1
  fi
fi

require_protected_api \
  "Entity-intel suggest anónimo" \
  "$api_base_url/api/v1/entity-intel/suggest?q=ib&kind=company" \
  "401"
require_protected_api \
  "Procurement tenders anónimo" \
  "$api_base_url/api/v1/procurement/tenders" \
  "401"
require_protected_api \
  "Procurement awards anónimo" \
  "$api_base_url/api/v1/procurement/awards?company=x" \
  "401"

actors_headers="$tmp_dir/app-actors.headers"
actors_code="$(curl --silent --show-error --dump-header "$actors_headers" --output /dev/null \
  --write-out '%{http_code}' --connect-timeout 5 --max-time 15 "$base_url/app/actors")"
case "$actors_code" in
  200) ;;
  404)
    echo "/app/actors devolvió 404; la ruta del grafo no parece servida por la SPA." >&2
    exit 1
    ;;
  5*)
    echo "/app/actors devolvió ${actors_code}; la capa web no está sana." >&2
    exit 1
    ;;
  *)
    echo "/app/actors devolvió ${actors_code}; se esperaba 200 para el shell SPA anónimo." >&2
    exit 1
    ;;
esac

if [[ "$api_base_url" == "$base_url" ]]; then
  metrics_code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --connect-timeout 5 --max-time 15 "$base_url/internal/metrics")"
  if [[ "$metrics_code" != "404" ]]; then
    echo "La ruta pública de métricas devolvió ${metrics_code}; se esperaba 404." >&2
    exit 1
  fi
  echo "Smoke público correcto: liveness, meta, headers de login, auth gates, grafo y métricas ocultas."
else
  echo "Smoke loopback correcto: liveness/meta de API, headers de login web, auth gates y grafo."
fi
