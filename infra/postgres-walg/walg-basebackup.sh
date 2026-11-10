#!/bin/sh
# Base-backup loop for the `walg-backup` sidecar in infra/docker-compose.pitr.yml: one full WAL-G base backup at start
# and then every WALG_BACKUP_INTERVAL_SECONDS (default 1 day), keeping the last WALG_RETAIN_FULL (default 7) base
# backups and the WAL needed to replay from them. /tmp/walg-last-ok is touched after each success; the container
# healthcheck turns unhealthy when it gets older than a day and a bit, so a stuck backup is visible in `docker ps`.
set -eu
INTERVAL=${WALG_BACKUP_INTERVAL_SECONDS:-86400}
KEEP=${WALG_RETAIN_FULL:-7}

until pg_isready -q; do sleep 5; done
while true; do
  if wal-g backup-push "$PGDATA"; then
    touch /tmp/walg-last-ok
    wal-g delete retain FULL "$KEEP" --confirm || echo "walg: retention cleanup failed" >&2
  else
    echo "walg: backup-push FAILED" >&2
  fi
  sleep "$INTERVAL"
done
