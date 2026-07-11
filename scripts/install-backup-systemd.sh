#!/usr/bin/env bash
set -Eeuo pipefail

umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[[ "${1:-}" == "--install" && $# -eq 1 ]] || { echo "Uso: $0 --install" >&2; exit 2; }
[[ $EUID -eq 0 ]] || { echo "Debe ejecutarse como root." >&2; exit 2; }
release_dir="$(readlink -f "${ORACLE_RELEASE_DIR:-/opt/opn-oracle/current}")"
[[ "$release_dir" == /opt/opn-oracle/releases/* && -d "$release_dir" ]] || {
  echo "Release activo inseguro o ausente." >&2; exit 2;
}
for unit in opn-oracle-backup-agent.service opn-oracle-backup-agent.timer \
  opn-oracle-backup-schedule.service opn-oracle-backup-schedule.timer; do
  [[ -f "$release_dir/infra/systemd/$unit" && ! -L "$release_dir/infra/systemd/$unit" ]] || exit 2
done
for script in backup-production.sh restore-test-production.sh backup-maintenance.sh \
  backup-host-agent.sh enqueue-scheduled-backup.sh restore-production.sh; do
  [[ -x "$release_dir/scripts/$script" && ! -L "$release_dir/scripts/$script" ]] || exit 2
  bash -n "$release_dir/scripts/$script"
done

if [[ ! -e /etc/opn-oracle/backup.conf ]]; then
  install -o root -g root -m 0600 "$release_dir/infra/production/backup.conf.example" \
    /etc/opn-oracle/backup.conf
else
  [[ -f /etc/opn-oracle/backup.conf && ! -L /etc/opn-oracle/backup.conf ]] || exit 2
  chown root:root /etc/opn-oracle/backup.conf
  chmod 0600 /etc/opn-oracle/backup.conf
fi
install -d -o root -g root -m 0700 /var/backups/opn-oracle \
  /var/backups/opn-oracle/restore-evidence
for unit in opn-oracle-backup-agent.service opn-oracle-backup-agent.timer \
  opn-oracle-backup-schedule.service opn-oracle-backup-schedule.timer; do
  install -o root -g root -m 0644 "$release_dir/infra/systemd/$unit" "/etc/systemd/system/$unit"
done
systemd-analyze verify /etc/systemd/system/opn-oracle-backup-*.service \
  /etc/systemd/system/opn-oracle-backup-*.timer
systemctl daemon-reload
systemctl enable --now opn-oracle-backup-agent.timer opn-oracle-backup-schedule.timer
systemctl list-timers --all opn-oracle-backup-agent.timer opn-oracle-backup-schedule.timer
echo "Timers instalados. Los backups se guardan en /var/backups/opn-oracle."
