#!/usr/bin/env bash
# Nightly backup: AppFlowy Postgres dump + curator state. Keeps 14 days.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-$HOME/appflowy/backups}"
PG_CONTAINER="${PG_CONTAINER:-appflowy-cloud-postgres-1}"  # check: docker ps
STATE_DIR="${STATE_DIR:-$HOME/appflowy/growth-os/_state}"
KEEP_DAYS=14

mkdir -p "$BACKUP_DIR"
stamp=$(date +%F)

docker exec "$PG_CONTAINER" pg_dump -U postgres postgres \
  | gzip > "$BACKUP_DIR/appflowy_$stamp.sql.gz"
tar -czf "$BACKUP_DIR/growthos_state_$stamp.tar.gz" -C "$(dirname "$STATE_DIR")" \
  "$(basename "$STATE_DIR")"

find "$BACKUP_DIR" -name '*.gz' -mtime +"$KEEP_DAYS" -delete
echo "backup ok: $BACKUP_DIR ($stamp)"
