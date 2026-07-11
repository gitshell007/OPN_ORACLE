#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
scripts=(
  backup-production.sh
  restore-test-production.sh
  backup-maintenance.sh
  backup-host-agent.sh
  enqueue-scheduled-backup.sh
  restore-production.sh
  install-backup-systemd.sh
)
for script in "${scripts[@]}"; do
  bash -n "$repo_root/scripts/$script"
done

grep -q '^ORACLE_RETENTION_DAYS=30$' "$repo_root/infra/production/backup.conf.example"
grep -q '^OnCalendar=.*Europe/Madrid$' \
  "$repo_root/infra/systemd/opn-oracle-backup-schedule.timer"
grep -q '^Persistent=true$' "$repo_root/infra/systemd/opn-oracle-backup-schedule.timer"
grep -q -- '--artifact-json-stdin' "$repo_root/scripts/backup-host-agent.sh"
grep -q -- '--app opn_oracle.wsgi:app backup-agent' "$repo_root/scripts/backup-host-agent.sh"
grep -q 'ORACLE_EXPIRED_NAMES_OUTPUT' "$repo_root/scripts/backup-maintenance.sh"
grep -q 'mark-expired' "$repo_root/scripts/backup-host-agent.sh"
grep -q 'ORACLE_SKIP_PRUNE=1' "$repo_root/scripts/restore-production.sh"
grep -q 'dump_acl=preserved' "$repo_root/scripts/backup-production.sh"
grep -q 'RECUPERAR \$operation_id \$backup_id' "$repo_root/scripts/restore-production.sh"
grep -q 'opn_oracle_before_' "$repo_root/scripts/restore-production.sh"
grep -q 'rollback_swap' "$repo_root/scripts/restore-production.sh"

if grep -Eq 'docker compose .*down|down -v|DROP DATABASE|rm -rf.*/var/backups' \
  "$repo_root/scripts/backup-maintenance.sh" "$repo_root/scripts/backup-host-agent.sh" \
  "$repo_root/scripts/restore-production.sh"; then
  echo "Se detectó una primitiva destructiva prohibida." >&2
  exit 1
fi

echo "Infraestructura de backup: checks estáticos correctos."
