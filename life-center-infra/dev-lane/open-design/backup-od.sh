#!/usr/bin/env bash
# Back up Open Design .od/ project files to the Life Center (Class B).
# The dev machine holds the authoritative copy; this is the durable backup.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OD_DIR="${OPEN_DESIGN_OD_DIR:-$DIR/open-design/.od}"
TARGET="${OPEN_DESIGN_BACKUP_TARGET:-/tank/models-archive/open-design}"

[ -d "$OD_DIR" ] || { echo "[open-design] no .od/ at $OD_DIR — run up.sh first"; exit 1; }
mkdir -p "$TARGET"
echo "[open-design] syncing $OD_DIR -> $TARGET"
rsync -a --delete "$OD_DIR/" "$TARGET/"
echo "[open-design] done. Ensure $TARGET is included in the restic 3-2-1 job."
