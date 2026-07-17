#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

APP_ROOT="${ORACLE_APP_ROOT:-/opt/opn-oracle}"
RELEASES_DIR="$APP_ROOT/releases"
CURRENT_LINK="$APP_ROOT/current"
ENV_FILE="${ORACLE_ENV_FILE:-/etc/opn-oracle/oracle.env}"
SECRETS_DIR="${ORACLE_SECRETS_DIR:-/etc/opn-oracle/secrets}"
BACKUP_ROOT="${ORACLE_BACKUP_ROOT:-/var/backups/opn-oracle}"
DOMAIN="${ORACLE_DOMAIN:-oracle.opnconsultoria.com}"
AUDIT_LOG="${ORACLE_CONTROL_AUDIT_LOG:-/var/log/opn-oracle-control.log}"
LOCK_FILE="${ORACLE_CONTROL_LOCK:-/run/lock/opn-oracle-control.lock}"
REQUIRE_OFFSITE_RECEIPT="${ORACLE_REQUIRE_OFFSITE_RECEIPT:-0}"
AUTO_APPROVE=0

APP_SERVICES=(api web worker-core beat)
ALL_SERVICES=(api web worker-core beat postgres redis)

if [[ -t 1 && -z "${NO_COLOR:-}" && "${TERM:-}" != "dumb" ]]; then
  RESET=$'\033[0m'; BOLD=$'\033[1m'; DIM=$'\033[2m'
  RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
  BLUE=$'\033[34m'; MAGENTA=$'\033[35m'; CYAN=$'\033[36m'
else
  RESET=''; BOLD=''; DIM=''; RED=''; GREEN=''; YELLOW=''
  BLUE=''; MAGENTA=''; CYAN=''
fi
trap 'printf "%s" "$RESET"' EXIT INT TERM

info()    { printf '%sℹ%s %s\n' "$BLUE" "$RESET" "$*"; }
success() { printf '%s✔%s %s\n' "$GREEN" "$RESET" "$*"; }
warn()    { printf '%s⚠%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
error()   { printf '%s✖%s %s\n' "$RED" "$RESET" "$*" >&2; }
heading() { printf '\n%s%s%s\n' "$BOLD$CYAN" "$*" "$RESET"; }
rule()    { printf '%s\n' "${DIM}────────────────────────────────────────────────────────────${RESET}"; }

die() {
  error "$*"
  exit 1
}

usage() {
  cat <<'EOF'
Uso: oracle-control.sh [--yes|--non-interactive] [comando]

Sin comando abre el menú interactivo.

Comandos de consulta:
  status                    Resumen de host, servicios y contenedores
  health                    Health local, workers y HTTPS público
  validate                  Config, release, permisos, Nginx y exposición
  resources                 CPU, RAM/zram, disco y docker stats
  logs <servicio>           Logs acotados del servicio permitido
  tls                       Certificado y timer de renovación

Comandos operativos interactivos:
  start                     Iniciar la capa de aplicación
  stop                      Detener solo aplicación; conserva DB/Redis
  restart                   Recrear y esperar la capa de aplicación
  restart-service <nombre>  Reiniciar un servicio permitido
  backup                    Crear backup y ofrecer restore aislado
  restore-test              Probar un backup en contenedor efímero
  update                    Activar un release con backup local y restore
  rollback                  Rollback solo de aplicación, nunca de esquema
  nginx-reload              nginx -t y reload seguro
  tls-dry-run               Ensayo de renovación Certbot
  menu                      Abrir menú

Servicios permitidos: api web worker-core beat postgres redis

Opciones:
  --yes, --non-interactive  Autoacepta confirmaciones simples y desactiva pausas.
                            Las frases reforzadas siguen exigiendo
                            ORACLE_CONTROL_CONFIRM_PHRASE exacta.

No muta un release activo in-place. Nunca ejecuta docker compose down,
down -v, DROP DATABASE, pg_restore sobre producción ni Alembic downgrade.
EOF
}

banner() {
  printf '\n%s%s' "$BOLD$MAGENTA" '╔════════════════════════════════════════════════════════════╗'
  printf '\n║             OPN ORACLE · CONTROL CENTER                   ║'
  printf '\n╚════════════════════════════════════════════════════════════╝%s\n' "$RESET"
  printf '%sDominio:%s %s   %sHost:%s %s\n' "$DIM" "$RESET" "$DOMAIN" "$DIM" "$RESET" "$(hostname)"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Falta el comando requerido: $1"
}

ensure_root() {
  if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    if [[ -t 0 ]] && command -v sudo >/dev/null 2>&1; then
      info "Se requieren privilegios; solicitando sudo sin conservar el entorno."
      exec sudo -- "$0" "$@"
    fi
    die "Esta operación debe ejecutarse como root."
  fi
}

ensure_layout() {
  [[ "$REQUIRE_OFFSITE_RECEIPT" == "0" || "$REQUIRE_OFFSITE_RECEIPT" == "1" ]] || \
    die "ORACLE_REQUIRE_OFFSITE_RECEIPT solo admite 0 o 1."
  [[ -d "$RELEASES_DIR" ]] || die "No existe el directorio de releases: $RELEASES_DIR"
  [[ -L "$CURRENT_LINK" ]] || die "No existe el symlink current: $CURRENT_LINK"
  [[ -r "$ENV_FILE" && ! -L "$ENV_FILE" ]] || die "oracle.env no es regular/legible."
  [[ -d "$SECRETS_DIR" && ! -L "$SECRETS_DIR" ]] || die "Directorio de secretos inválido."
  CURRENT_DIR="$(readlink -f "$CURRENT_LINK")"
  case "$CURRENT_DIR" in "$RELEASES_DIR"/*) ;; *) die "current apunta fuera de releases.";; esac
  COMPOSE_FILE="$CURRENT_DIR/compose.prod.yml"
  [[ -r "$COMPOSE_FILE" ]] || die "Falta compose.prod.yml en el release activo."
  export ORACLE_SECRETS_DIR="$SECRETS_DIR"
}

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

current_release() {
  basename "$(readlink -f "$CURRENT_LINK")"
}

release_marker_value() {
  local marker="$APP_ROOT/CURRENT_RELEASE"
  [[ -r "$marker" && ! -L "$marker" ]] || return 0
  sed -n '1p' "$marker"
}

env_release_value() {
  sed -n 's/^ORACLE_RELEASE=//p' "$ENV_FILE" | tail -n 1
}

expected_app_image() {
  local service="$1" release="$2"
  case "$service" in
    web) printf 'opn-oracle-web:%s\n' "$release" ;;
    api|worker-core|beat) printf 'opn-oracle-api:%s\n' "$release" ;;
    *) return 1 ;;
  esac
}

running_service_image() {
  local service="$1" container_id
  container_id="$(compose ps -q "$service" 2>/dev/null | head -n 1 || true)"
  [[ -n "$container_id" ]] || return 1
  docker inspect --format '{{.Config.Image}}' "$container_id" 2>/dev/null
}

check_release_coherence() {
  local release marker env_release service expected image failed=0
  release="$(current_release)"
  marker="$(release_marker_value || true)"
  env_release="$(env_release_value || true)"

  if [[ "$marker" == "$release" ]]; then
    success "CURRENT_RELEASE coincide con current: $release."
  else
    error "CURRENT_RELEASE='$marker' no coincide con current='$release'."
    failed=1
  fi

  if [[ "$env_release" == "$release" ]]; then
    success "oracle.env ORACLE_RELEASE coincide con current: $release."
  else
    error "oracle.env ORACLE_RELEASE='$env_release' no coincide con current='$release'."
    failed=1
  fi

  for service in "${APP_SERVICES[@]}"; do
    expected="$(expected_app_image "$service" "$release")"
    image="$(running_service_image "$service" || true)"
    if [[ -z "$image" ]]; then
      error "Servicio $service sin contenedor en ejecución; esperado $expected."
      failed=1
      continue
    fi
    if [[ "$image" == "$expected" ]]; then
      success "$service ejecuta $image."
    else
      error "$service ejecuta '$image'; esperado '$expected'."
      failed=1
    fi
  done

  [[ "$failed" == "0" ]]
}

deploy_stage_requires_forward_fix() {
  local stage="$1"
  case "$stage" in
    mutation_started|migration_started|app_swap_started|app_swap_completed|smoke_started|completed)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

update_release_marker() {
  local release="$1" marker="$APP_ROOT/CURRENT_RELEASE" tmp owner=0 group=0 mode=640
  tmp="$(mktemp "$APP_ROOT/.CURRENT_RELEASE.XXXXXX")"
  if [[ -e "$marker" && ! -L "$marker" ]]; then
    owner="$(stat -c %u "$marker")"
    group="$(stat -c %g "$marker")"
    mode="$(stat -c %a "$marker")"
  fi
  printf '%s\n' "$release" >"$tmp"
  chown "$owner:$group" "$tmp"
  chmod "$mode" "$tmp"
  mv -f "$tmp" "$marker"
}

array_contains() {
  local needle="$1" item
  shift || true
  for item in "$@"; do
    [[ "$item" == "$needle" ]] && return 0
  done
  return 1
}

add_unique_release() {
  local candidate="$1"
  [[ -n "$candidate" ]] || return 0
  array_contains "$candidate" "${keep_releases[@]}" && return 0
  keep_releases+=("$candidate")
}

service_allowed() {
  local candidate="$1" allowed
  for allowed in "${ALL_SERVICES[@]}"; do
    [[ "$candidate" == "$allowed" ]] && return 0
  done
  return 1
}

confirm() {
  local prompt="$1" reply
  if [[ "$AUTO_APPROVE" == "1" ]]; then
    warn "Autoaceptado por --yes: $prompt"
    return 0
  fi
  [[ -t 0 ]] || { warn "La confirmación necesita una terminal interactiva."; return 1; }
  printf '%s%s [s/N]: %s' "$YELLOW" "$prompt" "$RESET" >&2
  IFS= read -r reply
  [[ "$reply" == "s" || "$reply" == "S" || "$reply" == "si" || "$reply" == "sí" || "$reply" == "SI" ]]
}

confirm_phrase() {
  local prompt="$1" expected="$2" reply configured="${ORACLE_CONTROL_CONFIRM_PHRASE:-}"
  if [[ -n "$configured" ]]; then
    [[ "$configured" == "$expected" ]] || die "ORACLE_CONTROL_CONFIRM_PHRASE no coincide con '$expected'."
    warn "Confirmación reforzada validada por ORACLE_CONTROL_CONFIRM_PHRASE."
    return 0
  fi
  if [[ "$AUTO_APPROVE" == "1" ]]; then
    die "La confirmación reforzada exige ORACLE_CONTROL_CONFIRM_PHRASE='$expected'."
  fi
  [[ -t 0 ]] || { warn "La confirmación reforzada necesita una terminal."; return 1; }
  warn "$prompt"
  printf 'Escribe exactamente %s%s%s: ' "$BOLD" "$expected" "$RESET" >&2
  IFS= read -r reply
  [[ "$reply" == "$expected" ]]
}

pause() {
  [[ "$AUTO_APPROVE" == "1" ]] && return 0
  [[ -t 0 ]] || return 0
  printf '\n%sPulsa Intro para continuar…%s' "$DIM" "$RESET"
  IFS= read -r _
}

gate_path() {
  # La expansión indirecta va en su propia sentencia: `local` expande todos sus
  # argumentos antes de asignar ninguno, así que ${!env_name} dentro del mismo
  # `local` se evalúa con env_name aún vacío y bash aborta con
  # "invalid indirect expansion".
  local __target="$1" label="$2" env_name="$3"
  local value="${!env_name:-}"
  if [[ -n "$value" ]]; then
    printf -v "$__target" '%s' "$value"
    return 0
  fi
  if [[ -t 0 && "$AUTO_APPROVE" != "1" ]]; then
    printf '%s: ' "$label"
    IFS= read -r value
    printf -v "$__target" '%s' "$value"
    return 0
  fi
  die "$env_name es obligatorio en modo no interactivo."
}

acquire_lock() {
  ensure_root
  require_command flock
  if [[ -z "${LOCK_HELD:-}" ]]; then
    install -d -m 0755 "$(dirname "$LOCK_FILE")"
    exec 9>"$LOCK_FILE"
    flock -n 9 || die "Otra operación de control está en curso: $LOCK_FILE"
    LOCK_HELD=1
  fi
}

audit_event() {
  local action="$1" result="$2" started="$3" now duration actor release
  ensure_root
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  duration=$(( $(date +%s) - started ))
  actor="${SUDO_USER:-$(id -un)}"
  release="$(current_release 2>/dev/null || printf unknown)"
  if [[ ! -e "$AUDIT_LOG" ]]; then
    install -o root -g root -m 0600 /dev/null "$AUDIT_LOG"
  else
    [[ -f "$AUDIT_LOG" && ! -L "$AUDIT_LOG" ]] || die "Audit log inseguro: $AUDIT_LOG"
    chown root:root "$AUDIT_LOG"
    chmod 0600 "$AUDIT_LOG"
  fi
  printf '%s actor=%s action=%s result=%s release=%s duration_seconds=%s\n' \
    "$now" "$actor" "$action" "$result" "$release" "$duration" >>"$AUDIT_LOG"
}

system_state() {
  local unit state color
  for unit in docker nginx ssh certbot.timer systemd-zram-setup@zram0.service; do
    state="$(systemctl is-active "$unit" 2>/dev/null || true)"
    [[ "$state" == "active" ]] && color="$GREEN" || color="$RED"
    printf '  %-34s %s%s%s\n' "$unit" "$color" "${state:-missing}" "$RESET"
  done
}

show_status() {
  ensure_layout
  heading "Resumen general"
  printf '  Release activo:     %s%s%s\n' "$BOLD" "$(current_release)" "$RESET"
  printf '  Ruta:               %s\n' "$CURRENT_DIR"
  printf '  Dominio:            https://%s\n' "$DOMAIN"
  printf '  Hora UTC:           %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  heading "Servicios systemd"
  system_state
  heading "Contenedores Compose"
  compose ps || true
  heading "Firewall y listeners relevantes"
  ufw status 2>/dev/null | sed -n '1,16p' || warn "UFW no disponible."
  ss -lnt | awk 'NR==1 || /:(22|80|443|3000|8000|5432|6379)[[:space:]]/'
}

probe_url() {
  local label="$1" url="$2" expected="${3:-200}" code
  code="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --connect-timeout 4 --max-time 12 "$url" 2>/dev/null || true)"
  code="${code:-000}"
  if [[ "$code" == "$expected" ]]; then
    printf '  %s✔%s %-24s HTTP %s\n' "$GREEN" "$RESET" "$label" "$code"
    return 0
  fi
  printf '  %s✖%s %-24s HTTP %s (esperado %s)\n' "$RED" "$RESET" "$label" "$code" "$expected"
  return 1
}

show_health() {
  ensure_layout
  local failed=0 beat_count
  heading "Coherencia de release"
  check_release_coherence || failed=1
  heading "Health interno"
  probe_url "API liveness"  "http://127.0.0.1:8000/health/live" 200 || failed=1
  probe_url "API readiness" "http://127.0.0.1:8000/health/ready" 200 || failed=1
  probe_url "Web login"     "http://127.0.0.1:3000/login" 200 || failed=1
  heading "Health público"
  probe_url "HTTPS login" "https://$DOMAIN/login" 200 || failed=1
  probe_url "HTTPS live"  "https://$DOMAIN/health/live" 200 || failed=1
  heading "Celery"
  if compose exec -T worker-core celery -A opn_oracle.celery_entry:celery inspect ping --timeout 5 2>/dev/null | grep pong >/dev/null; then
    success "Worker Celery responde ping."
  else
    error "Worker Celery no responde."
    failed=1
  fi
  beat_count="$(compose ps --status running --services 2>/dev/null | grep -xc beat || true)"
  if [[ "$beat_count" == "1" ]]; then
    success "Existe un único beat."
  else
    error "Beat activos: $beat_count"
    failed=1
  fi
  [[ "$failed" == "0" ]] || return 1
}

validate_security() {
  ensure_layout
  local failed=0 secret metadata owner group mode name expected_owner expected_group
  local postgres_uid postgres_gid
  heading "Validación de release y configuración"
  if [[ -r "$CURRENT_DIR/RELEASE_SHA256SUMS" ]] && (cd "$CURRENT_DIR" && sha256sum -c RELEASE_SHA256SUMS >/dev/null); then
    success "Manifest SHA-256 del release correcto."
  else
    error "Manifest SHA-256 ausente o inválido."
    failed=1
  fi
  if compose config --quiet; then
    success "Compose config correcto."
  else
    error "Compose config inválido."
    failed=1
  fi
  if nginx -t; then
    success "Nginx config correcto."
  else
    error "Nginx config inválido."
    failed=1
  fi

  heading "Secret files (solo metadata; nunca valores)"
  postgres_uid="$(compose exec -T postgres id -u postgres 2>/dev/null || true)"
  postgres_gid="$(compose exec -T postgres id -g postgres 2>/dev/null || true)"
  for name in postgres_admin_password postgres_migrator_password postgres_app_password redis_password \
    oracle_secret_key oracle_database_url oracle_database_migration_url oracle_redis_url \
    oracle_session_redis_url oracle_ratelimit_redis_url oracle_celery_broker_url \
    oracle_celery_result_url oracle_graph_client_secret; do
    secret="$SECRETS_DIR/$name"
    if [[ ! -s "$secret" || -L "$secret" ]]; then
      printf '  %s✖%s %-38s ausente/vacío/enlace\n' "$RED" "$RESET" "$name"
      failed=1
      continue
    fi
    metadata="$(stat -c '%u %g %a' "$secret")"
    read -r owner group mode <<<"$metadata"
    case "$name" in
      postgres_admin_password|redis_password)
        expected_owner=0; expected_group=0 ;;
      postgres_migrator_password|postgres_app_password)
        expected_owner="$postgres_uid"; expected_group="$postgres_gid" ;;
      *)
        expected_owner=10001; expected_group=10001 ;;
    esac
    if [[ -n "$expected_owner" && "$owner" == "$expected_owner" && \
          "$group" == "$expected_group" && "$mode" == "400" ]]; then
      printf '  %s✔%s %-38s uid=%s gid=%s mode=%s\n' \
        "$GREEN" "$RESET" "$name" "$owner" "$group" "$mode"
    else
      printf '  %s✖%s %-38s uid=%s gid=%s mode=%s; esperado %s:%s 400\n' \
        "$RED" "$RESET" "$name" "$owner" "$group" "$mode" \
        "${expected_owner:-desconocido}" "${expected_group:-desconocido}"
      failed=1
    fi
  done

  heading "Exposición"
  if ss -lnt | grep -E '(^|[[:space:]])[^[:space:]]*:(5432|6379)[[:space:]]' >/dev/null; then
    error "PostgreSQL o Redis escuchan en el host."
    failed=1
  else
    success "PostgreSQL/Redis sin listener host."
  fi
  if ss -lnt | awk '$4 ~ /:(3000|8000)$/ && $4 !~ /127\.0\.0\.1:/ {bad=1} END{exit bad?0:1}'; then
    error "Web/API tienen un bind no-loopback."
    failed=1
  else
    success "Web/API limitadas a loopback."
  fi
  if sshd -T | grep '^passwordauthentication no$' >/dev/null; then
    success "SSH password deshabilitado."
  else
    error "SSH password no está deshabilitado."
    failed=1
  fi
  if ufw status | grep '^Status: active$' >/dev/null; then
    success "UFW activo."
  else
    error "UFW inactivo."
    failed=1
  fi
  [[ "$failed" == "0" ]]
}

start_application() {
  acquire_lock
  ensure_layout
  local started; started=$(date +%s)
  if ! confirm "¿Iniciar API, web, worker y beat?"; then warn "Cancelado."; return 0; fi
  if compose up -d --wait --wait-timeout 180 "${APP_SERVICES[@]}"; then
    success "Capa de aplicación iniciada."
    audit_event start-application success "$started"
  else
    audit_event start-application failed "$started"
    die "No todos los servicios alcanzaron el estado esperado."
  fi
}

stop_application() {
  acquire_lock
  ensure_layout
  local started; started=$(date +%s)
  warn "PostgreSQL y Redis permanecerán activos."
  if ! confirm "¿Detener beat, web, API y worker?"; then warn "Cancelado."; return 0; fi
  if compose stop beat web api worker-core; then
    success "Capa de aplicación detenida; datos preservados."
    audit_event stop-application success "$started"
  else
    audit_event stop-application failed "$started"
    return 1
  fi
}

restart_application() {
  acquire_lock
  ensure_layout
  local started; started=$(date +%s)
  if ! confirm "¿Recrear y esperar API, web, worker y beat?"; then warn "Cancelado."; return 0; fi
  if compose up -d --force-recreate --wait --wait-timeout 180 "${APP_SERVICES[@]}"; then
    success "Capa de aplicación reiniciada."
    audit_event restart-application success "$started"
    show_health || warn "El restart terminó, pero el smoke detectó fallos."
  else
    audit_event restart-application failed "$started"
    return 1
  fi
}

restart_one() {
  local service="${1:-}"
  service_allowed "$service" || die "Servicio no permitido: ${service:-vacío}"
  acquire_lock
  ensure_layout
  local started phrase; started=$(date +%s)
  if [[ "$service" == "postgres" || "$service" == "redis" ]]; then
    phrase="REINICIAR $service"
    confirm_phrase "Reiniciar $service puede interrumpir sesiones/jobs." "$phrase" || { warn "Cancelado."; return 0; }
  else
    confirm "¿Reiniciar $service?" || { warn "Cancelado."; return 0; }
  fi
  if compose restart "$service" && compose up -d --wait --wait-timeout 120 "$service"; then
    success "$service reiniciado."
    audit_event "restart-$service" success "$started"
  else
    audit_event "restart-$service" failed "$started"
    return 1
  fi
}

choose_service() {
  local index
  heading "Selecciona servicio" >&2
  select index in "${ALL_SERVICES[@]}" "Cancelar"; do
    [[ "$index" == "Cancelar" ]] && return 1
    service_allowed "${index:-}" && { printf '%s' "$index"; return 0; }
    warn "Selección inválida."
  done
}

show_logs() {
  ensure_layout
  local service="${1:-}" lines since follow reply
  if [[ -z "$service" ]]; then service="$(choose_service)" || return 0; fi
  service_allowed "$service" || die "Servicio no permitido."
  lines=200; since=30m; follow=0
  if [[ -t 0 ]]; then
    printf 'Número de líneas [200, máximo 5000]: '; IFS= read -r reply
    [[ -n "$reply" ]] && lines="$reply"
    printf 'Desde cuándo [30m; formatos 10m, 2h, 1d]: '; IFS= read -r reply
    [[ -n "$reply" ]] && since="$reply"
    confirm "¿Seguir logs en vivo? Ctrl-C para salir" && follow=1 || true
  fi
  [[ "$lines" =~ ^[0-9]+$ && "$lines" -ge 1 && "$lines" -le 5000 ]] || die "Tail fuera de rango."
  [[ "$since" =~ ^[0-9]+[smhd]$ ]] || die "Formato --since inválido."
  warn "Los logs pueden contener datos operativos; revísalos antes de compartir."
  if [[ "$follow" == "1" ]]; then
    [[ -t 1 ]] || die "El seguimiento necesita TTY."
    compose logs --timestamps --tail "$lines" --since "$since" --follow "$service"
  else
    compose logs --timestamps --tail "$lines" --since "$since" "$service"
  fi
}

create_backup() {
  acquire_lock
  ensure_layout
  local started output manifest; started=$(date +%s)
  confirm "¿Crear backup lógico consistente de PostgreSQL?" || { warn "Cancelado."; return 0; }
  output="$("$CURRENT_DIR/scripts/backup-production.sh" --create)" || {
    audit_event backup failed "$started"; return 1;
  }
  printf '%s\n' "$output"
  manifest="$(printf '%s\n' "$output" | awk -F': ' '$1=="Manifiesto"{print $2}')"
  case "$manifest" in "$BACKUP_ROOT"/*/MANIFEST.txt) ;; *) die "El backup no devolvió un manifiesto permitido.";; esac
  [[ -f "$manifest" && ! -L "$manifest" ]] || die "Manifiesto inválido."
  audit_event backup success "$started"
  success "Backup creado: $manifest"
  warn "La copia cifrada off-host queda recomendada; solo bloquea con ORACLE_REQUIRE_OFFSITE_RECEIPT=1."
  if confirm "¿Probar ahora el restore aislado?"; then
    "$CURRENT_DIR/scripts/restore-test-production.sh" --verify-isolated "$manifest"
  fi
}

list_manifests() {
  find "$BACKUP_ROOT" -mindepth 2 -maxdepth 2 -type f -name MANIFEST.txt ! -path '*/.*.partial.*/*' -print0 2>/dev/null | sort -rz
}

choose_manifest() {
  local manifests=() selection
  while IFS= read -r -d '' selection; do manifests+=("$selection"); done < <(list_manifests)
  ((${#manifests[@]})) || die "No hay manifests de backup disponibles."
  heading "Backups disponibles" >&2
  select selection in "${manifests[@]}" "Cancelar"; do
    [[ "$selection" == "Cancelar" ]] && return 1
    [[ -n "$selection" ]] && { printf '%s' "$selection"; return 0; }
    warn "Selección inválida."
  done
}

restore_test() {
  acquire_lock
  ensure_layout
  local manifest="${1:-}" started; started=$(date +%s)
  [[ -n "$manifest" ]] || manifest="$(choose_manifest)" || return 0
  case "$(readlink -f "$manifest")" in "$BACKUP_ROOT"/*/MANIFEST.txt) ;; *) die "Manifest fuera del backup root.";; esac
  heading "Restore exclusivamente aislado"
  warn "Nunca se tocará la base de producción ni se publicarán puertos."
  confirm "¿Crear contenedor/volumen efímeros y verificar el restore?" || { warn "Cancelado."; return 0; }
  if "$CURRENT_DIR/scripts/restore-test-production.sh" --verify-isolated "$manifest"; then
    audit_event restore-test success "$started"
  else
    audit_event restore-test failed "$started"
    return 1
  fi
}

list_releases() {
  local dir
  for dir in "$RELEASES_DIR"/*; do
    [[ -d "$dir" && ! -L "$dir" ]] || continue
    basename "$dir"
  done | sort -r
}

prune_old_release_images() {
  require_command docker
  local previous release family repo tag ref count=0
  local -a keep_releases=() delete_refs=()

  add_unique_release "$(current_release 2>/dev/null || true)"
  if [[ -r "$APP_ROOT/PREVIOUS_RELEASE" && ! -L "$APP_ROOT/PREVIOUS_RELEASE" ]]; then
    previous="$(sed -n '1p' "$APP_ROOT/PREVIOUS_RELEASE" | tr -d '\r\n')"
    add_unique_release "$previous"
  fi
  while IFS= read -r release; do
    [[ -n "$release" ]] || continue
    add_unique_release "$release"
    count=$((count + 1))
    [[ "$count" -ge 3 ]] && break
  done < <(list_releases)

  info "Poda de imágenes Docker Oracle: se conservan releases ${keep_releases[*]}."
  for family in opn-oracle-api opn-oracle-web; do
    while IFS=' ' read -r repo tag; do
      [[ "$repo" == "$family" && -n "$tag" && "$tag" != "<none>" ]] || continue
      ref="$repo:$tag"
      if array_contains "$tag" "${keep_releases[@]}"; then
        info "Conservada imagen referenciada/reciente: $ref"
        continue
      fi
      delete_refs+=("$ref")
    done < <(docker image ls "$family" --format '{{.Repository}} {{.Tag}}' 2>/dev/null || true)
  done

  if ((${#delete_refs[@]} == 0)); then
    success "No hay imágenes antiguas de Oracle para podar."
    return 0
  fi
  for ref in "${delete_refs[@]}"; do
    if docker image rm "$ref"; then
      info "Eliminada imagen antigua: $ref"
    else
      warn "No se pudo eliminar $ref; puede estar en uso o compartida."
    fi
  done
}

choose_release() {
  local releases=() selection
  while IFS= read -r selection; do [[ -n "$selection" ]] && releases+=("$selection"); done < <(list_releases)
  ((${#releases[@]})) || die "No hay releases preparados."
  heading "Releases disponibles" >&2
  select selection in "${releases[@]}" "Cancelar"; do
    [[ "$selection" == "Cancelar" ]] && return 1
    [[ -n "$selection" ]] && { printf '%s' "$selection"; return 0; }
    warn "Selección inválida."
  done
}

validate_release_id() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]]
}

validate_release_dir() {
  local release="$1" target resolved
  target="$RELEASES_DIR/$release"
  validate_release_id "$release" || die "Release ID inválido."
  [[ -d "$target" && ! -L "$target" ]] || die "Release inexistente o enlazado."
  resolved="$(readlink -f "$target")"
  [[ "$resolved" == "$target" ]] || die "Release fuera del directorio permitido."
  [[ -r "$target/compose.prod.yml" && -x "$target/scripts/deploy-production.sh" ]] || die "Release incompleto."
  if [[ -n "$(find "$target" -type l -print -quit)" ]]; then
    die "El release contiene symlinks inesperados."
  fi
  [[ -r "$target/RELEASE_SHA256SUMS" ]] || die "Release sin manifest SHA-256."
  (cd "$target" && sha256sum -c RELEASE_SHA256SUMS >/dev/null) || die "Manifest del release inválido."
}

update_env_release() {
  local release="$1" tmp owner group mode
  tmp="$(mktemp "$(dirname "$ENV_FILE")/.oracle.env.XXXXXX")"
  owner="$(stat -c %u "$ENV_FILE")"; group="$(stat -c %g "$ENV_FILE")"; mode="$(stat -c %a "$ENV_FILE")"
  awk -v release="$release" '
    BEGIN{done=0}
    /^ORACLE_RELEASE=/{print "ORACLE_RELEASE=" release; done=1; next}
    {print}
    END{if(!done) print "ORACLE_RELEASE=" release}
  ' "$ENV_FILE" >"$tmp"
  chown "$owner:$group" "$tmp"; chmod "$mode" "$tmp"
  mv -f "$tmp" "$ENV_FILE"
}

set_release_pointers() {
  local release="$1" suffix="${2:-next}" target="$RELEASES_DIR/$release"
  rm -f "$APP_ROOT/current.$suffix"
  ln -s "$target" "$APP_ROOT/current.$suffix"
  mv -Tf "$APP_ROOT/current.$suffix" "$CURRENT_LINK"
  update_env_release "$release"
  update_release_marker "$release"
  ensure_layout
}

activate_release() {
  acquire_lock
  ensure_layout
  local release="${1:-}" old_release manifest evidence receipt started deploy_stage_file deploy_stage
  local -a deploy_env
  started=$(date +%s); old_release="$(current_release)"
  [[ -n "$release" ]] || release="$(choose_release)" || return 0
  [[ "$release" != "$old_release" ]] || die "Ese release ya está activo."
  validate_release_dir "$release"
  warn "Se activará un release preparado; no se modificará el release activo in-place."
  heading "Gates obligatorios de upgrade"
  gate_path manifest "Manifest de backup" ORACLE_BACKUP_MANIFEST
  gate_path evidence "Evidencia de restore" ORACLE_BACKUP_RESTORE_EVIDENCE
  if [[ "$REQUIRE_OFFSITE_RECEIPT" == "1" ]]; then
    gate_path receipt "Receipt de copia off-host" ORACLE_BACKUP_OFFSITE_RECEIPT
  else
    if [[ -n "${ORACLE_BACKUP_OFFSITE_RECEIPT:-}" ]]; then
      receipt="$ORACLE_BACKUP_OFFSITE_RECEIPT"
    elif [[ -t 0 && "$AUTO_APPROVE" != "1" ]]; then
      printf 'Receipt de copia off-host [opcional]: '; IFS= read -r receipt
    else
      receipt=""
    fi
  fi
  for path in "$manifest" "$evidence"; do
    [[ -f "$path" && -r "$path" && ! -L "$path" ]] || die "Gate ausente o inválido."
  done
  if [[ "$REQUIRE_OFFSITE_RECEIPT" == "1" || -n "$receipt" ]]; then
    [[ -f "$receipt" && -r "$receipt" && ! -L "$receipt" ]] || die "Receipt off-host ausente o inválido."
  fi
  "$CURRENT_DIR/scripts/restore-test-production.sh" --check-evidence "$manifest" "$evidence"
  confirm_phrase "Se migrará una sola vez y se activará $release." "ACTIVAR $release" || { warn "Cancelado."; return 0; }
  deploy_stage_file="$(mktemp "$APP_ROOT/.deploy-stage.XXXXXX")"
  printf '%s\n' "$old_release" >"$APP_ROOT/PREVIOUS_RELEASE"
  set_release_pointers "$release" next
  deploy_env=(
    "ORACLE_BACKUP_MANIFEST=$manifest"
    "ORACLE_BACKUP_RESTORE_EVIDENCE=$evidence"
    "ORACLE_REQUIRE_OFFSITE_RECEIPT=$REQUIRE_OFFSITE_RECEIPT"
    "ORACLE_DEPLOY_STAGE_FILE=$deploy_stage_file"
  )
  [[ -z "$receipt" ]] || deploy_env+=("ORACLE_BACKUP_OFFSITE_RECEIPT=$receipt")
  if env "${deploy_env[@]}" "$CURRENT_DIR/scripts/deploy-production.sh" --apply-authorized-stage-b; then
    rm -f "$deploy_stage_file"
    if ! check_release_coherence; then
      audit_event activate-release failed "$started"
      die "Release $release desplegado, pero la coherencia de punteros/containers no es verificable."
    fi
    audit_event activate-release success "$started"
    success "Release $release activado."
    prune_old_release_images
    show_health || warn "Revisa health antes de dar el cambio por cerrado."
  else
    deploy_stage="$(sed -n '1p' "$deploy_stage_file" 2>/dev/null || true)"
    rm -f "$deploy_stage_file"
    if deploy_stage_requires_forward_fix "$deploy_stage"; then
      warn "Deploy fallido tras iniciar mutaciones ($deploy_stage). No se restauran punteros ni esquema."
      warn "El release $release queda seleccionado para diagnóstico/forward-fix explícito."
      check_release_coherence || warn "Coherencia NO garantizada; revisa punteros, env e imágenes antes de operar."
    else
      warn "Deploy fallido antes de migración/arranque de aplicación ($deploy_stage). Se restauran punteros."
      set_release_pointers "$old_release" previous
      check_release_coherence || warn "Coherencia NO garantizada tras restaurar punteros; requiere revisión manual."
    fi
    audit_event activate-release failed "$started"
    die "Deploy de $release fallido; no se ha ejecutado despliegue público."
  fi
}

rollback_release() {
  acquire_lock
  ensure_layout
  local release="${1:-}" current started target
  started=$(date +%s); current="$(current_release)"
  [[ -n "$release" ]] || release="$(choose_release)" || return 0
  [[ "$release" != "$current" ]] || die "Ese release ya está activo."
  validate_release_dir "$release"; target="$RELEASES_DIR/$release"
  warn "Rollback solo de aplicación. No ejecuta Alembic downgrade ni restaura datos."
  warn "Continúa únicamente si el esquema actual es compatible con el release elegido."
  confirm_phrase "Cambiar current/env a $release." "ROLLBACK $release" || { warn "Cancelado."; return 0; }
  printf '%s\n' "$current" >"$APP_ROOT/PREVIOUS_RELEASE"
  rm -f "$APP_ROOT/current.rollback"
  ln -s "$target" "$APP_ROOT/current.rollback"
  mv -Tf "$APP_ROOT/current.rollback" "$CURRENT_LINK"
  update_env_release "$release"
  update_release_marker "$release"
  ensure_layout
  if compose up -d --wait --wait-timeout 180 "${APP_SERVICES[@]}" && show_health; then
    audit_event rollback-application success "$started"
    success "Rollback de aplicación completado."
  else
    warn "Smoke fallido. Se restauran pointers a $current; no se toca DB."
    rm -f "$APP_ROOT/current.failed-rollback"
    ln -s "$RELEASES_DIR/$current" "$APP_ROOT/current.failed-rollback"
    mv -Tf "$APP_ROOT/current.failed-rollback" "$CURRENT_LINK"
    update_env_release "$current"
    update_release_marker "$current"
    audit_event rollback-application failed "$started"
    return 1
  fi
}

nginx_reload() {
  acquire_lock
  local started; started=$(date +%s)
  confirm "¿Validar y recargar Nginx sin restart?" || { warn "Cancelado."; return 0; }
  if nginx -t && systemctl reload nginx && systemctl is-active --quiet nginx; then
    audit_event nginx-reload success "$started"
    success "Nginx recargado."
  else
    audit_event nginx-reload failed "$started"
    return 1
  fi
}

show_tls() {
  local cert="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
  heading "Certificado TLS"
  [[ -r "$cert" ]] || die "No existe certificado para $DOMAIN."
  openssl x509 -in "$cert" -noout -subject -issuer -dates -ext subjectAltName
  printf '\nTimer Certbot: %s\n' "$(systemctl is-active certbot.timer 2>/dev/null || true)"
}

tls_dry_run() {
  acquire_lock
  local started; started=$(date +%s)
  show_tls
  confirm_phrase "Se ensayará renovación ACME; no se revoca ni borra nada." "PROBAR RENOVACION" || { warn "Cancelado."; return 0; }
  if certbot renew --dry-run --cert-name "$DOMAIN" --no-random-sleep-on-renew; then
    nginx -t && systemctl reload nginx
    audit_event tls-dry-run success "$started"
  else
    audit_event tls-dry-run failed "$started"
    return 1
  fi
}

show_resources() {
  ensure_layout
  heading "Carga y memoria"
  uptime
  free -h
  swapon --show || true
  heading "Disco"
  df -h / /var/lib/docker "$BACKUP_ROOT" 2>/dev/null | awk 'NR==1 || !seen[$1]++'
  heading "Contenedores"
  docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.PIDs}}' || true
  heading "Docker disk usage"
  docker system df
}

menu() {
  local choice service
  ensure_root
  while true; do
    clear 2>/dev/null || true
    banner
    printf '\n%s 1%s  Estado general             %s10%s  Restore aislado\n' "$CYAN" "$RESET" "$CYAN" "$RESET"
    printf '%s 2%s  Health y smoke             %s11%s  Activar release\n' "$CYAN" "$RESET" "$CYAN" "$RESET"
    printf '%s 3%s  Validación de seguridad    %s12%s  Rollback aplicación\n' "$CYAN" "$RESET" "$CYAN" "$RESET"
    printf '%s 4%s  Iniciar aplicación         %s13%s  Nginx validate/reload\n' "$CYAN" "$RESET" "$CYAN" "$RESET"
    printf '%s 5%s  Detener aplicación         %s14%s  Estado TLS\n' "$CYAN" "$RESET" "$CYAN" "$RESET"
    printf '%s 6%s  Reiniciar aplicación       %s15%s  TLS renewal dry-run\n' "$CYAN" "$RESET" "$CYAN" "$RESET"
    printf '%s 7%s  Reiniciar un servicio      %s16%s  Recursos/containers\n' "$CYAN" "$RESET" "$CYAN" "$RESET"
    printf '%s 8%s  Logs                        %s 0%s  Salir\n' "$CYAN" "$RESET" "$CYAN" "$RESET"
    printf '%s 9%s  Crear backup\n\n' "$CYAN" "$RESET"
    printf '%sOpción:%s ' "$BOLD" "$RESET"
    IFS= read -r choice
    case "$choice" in
      1) show_status; pause ;;
      2) show_health || true; pause ;;
      3) validate_security || true; pause ;;
      4) start_application; pause ;;
      5) stop_application; pause ;;
      6) restart_application; pause ;;
      7) service="$(choose_service)" && restart_one "$service"; pause ;;
      8) show_logs; pause ;;
      9) create_backup; pause ;;
      10) restore_test; pause ;;
      11) activate_release; pause ;;
      12) rollback_release; pause ;;
      13) nginx_reload; pause ;;
      14) show_tls; pause ;;
      15) tls_dry_run; pause ;;
      16) show_resources; pause ;;
      0|q|Q) success "Saliendo sin cambios adicionales."; return 0 ;;
      *) warn "Opción inválida."; sleep 1 ;;
    esac
  done
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --yes|--non-interactive)
        AUTO_APPROVE=1
        shift
        ;;
      --)
        shift
        break
        ;;
      *)
        break
        ;;
    esac
  done
  local command="${1:-menu}"
  case "$command" in
    -h|--help|help) usage ;;
    menu) menu ;;
    status) ensure_root "$@"; banner; show_status ;;
    health) ensure_root "$@"; banner; show_health ;;
    validate) ensure_root "$@"; banner; validate_security ;;
    resources) ensure_root "$@"; banner; show_resources ;;
    logs) ensure_root "$@"; banner; show_logs "${2:-}" ;;
    tls) ensure_root "$@"; banner; show_tls ;;
    start) ensure_root "$@"; banner; start_application ;;
    stop) ensure_root "$@"; banner; stop_application ;;
    restart) ensure_root "$@"; banner; restart_application ;;
    restart-service) ensure_root "$@"; banner; restart_one "${2:-}" ;;
    backup) ensure_root "$@"; banner; create_backup ;;
    restore-test) ensure_root "$@"; banner; restore_test "${2:-}" ;;
    update) ensure_root "$@"; banner; activate_release "${2:-}" ;;
    rollback) ensure_root "$@"; banner; rollback_release "${2:-}" ;;
    nginx-reload) ensure_root "$@"; banner; nginx_reload ;;
    tls-dry-run) ensure_root "$@"; banner; tls_dry_run ;;
    *) usage; die "Comando desconocido: $command" ;;
  esac
}

main "$@"
