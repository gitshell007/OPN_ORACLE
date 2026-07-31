#!/usr/bin/env bash
set -Eeuo pipefail

umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[[ ${1:-} == "--install" && $# -eq 1 ]] || {
  echo "Uso: $0 --install" >&2
  exit 2
}
[[ $EUID -eq 0 ]] || {
  echo "Debe ejecutarse como root." >&2
  exit 2
}

release_dir="$(readlink -f "${OPN_SERVER_MONITOR_RELEASE_DIR:-/opt/opn-server-monitor/current}")"
config_dir="${OPN_SERVER_MONITOR_CONFIG_DIR:-/etc/opn-server-monitor}"
state_dir="${OPN_SERVER_MONITOR_STATE_DIR:-/var/lib/opn-server-monitor}"
config_file="$config_dir/server-health-monitor.toml"
key_file="$config_dir/secrets/id_ed25519"
known_hosts_file="$config_dir/known_hosts"
graph_secret_file="${OPN_SERVER_MONITOR_GRAPH_SECRET_FILE:-/etc/opn-oracle/secrets/oracle_graph_client_secret}"

[[ "$release_dir" == /opt/opn-server-monitor/releases/* && -d "$release_dir" ]] || {
  echo "Release del monitor inseguro o ausente: $release_dir" >&2
  exit 2
}
[[ -r "$release_dir/scripts/server_health_report.py" && ! -L "$release_dir/scripts/server_health_report.py" ]] || {
  echo "Falta el recolector en el release." >&2
  exit 2
}
[[ -f "$config_file" && ! -L "$config_file" ]] || {
  echo "Falta la configuración: $config_file" >&2
  exit 2
}
[[ -f "$key_file" && ! -L "$key_file" && $(stat -c '%a' "$key_file") == 600 ]] || {
  echo "La clave SSH debe existir como fichero regular con modo 0600." >&2
  exit 2
}
[[ -f "$known_hosts_file" && ! -L "$known_hosts_file" ]] || {
  echo "Falta el known_hosts fijado: $known_hosts_file" >&2
  exit 2
}
[[ -s "$graph_secret_file" && ! -L "$graph_secret_file" && $(stat -c '%a' "$graph_secret_file") == 400 ]] || {
  echo "Falta el secreto Graph con modo 0400: $graph_secret_file" >&2
  exit 2
}

install -d -o root -g root -m 0700 "$state_dir"
install -o root -g root -m 0644 "$release_dir/infra/systemd/opn-server-health-report.service" /etc/systemd/system/opn-server-health-report.service
install -o root -g root -m 0644 "$release_dir/infra/systemd/opn-server-health-report.timer" /etc/systemd/system/opn-server-health-report.timer
systemd-analyze verify /etc/systemd/system/opn-server-health-report.service /etc/systemd/system/opn-server-health-report.timer
systemctl daemon-reload
systemctl enable --now opn-server-health-report.timer
systemctl list-timers --all opn-server-health-report.timer
echo "Monitor diario instalado; se ejecutará a las 08:00 Europe/Madrid con hasta 10 minutos de dispersión."
