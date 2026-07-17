#!/usr/bin/env bash
# Open Design dev-lane bring-up (macOS/Linux). Clones on first run, installs deps,
# detects a coding agent on PATH, and starts the local canvas. See README.md.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_URL="https://github.com/nexu-io/open-design.git"
CHECKOUT="${OPEN_DESIGN_DIR:-$DIR/open-design}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "[open-design] missing: $1"; exit 1; }; }
need git
need node
need pnpm

# Detect a coding agent on PATH (informational — Open Design auto-detects too).
AGENT=""
for a in claude codex cursor gemini opencode aider; do
  if command -v "$a" >/dev/null 2>&1; then AGENT="$a"; break; fi
done
[ -n "$AGENT" ] && echo "[open-design] coding agent detected: $AGENT" \
                 || echo "[open-design] WARN no coding agent found on PATH (BYOK API key/local model still works)"

if [ ! -d "$CHECKOUT/.git" ]; then
  echo "[open-design] cloning into $CHECKOUT"
  git clone "$REPO_URL" "$CHECKOUT"
else
  echo "[open-design] repo present; pulling latest"
  git -C "$CHECKOUT" pull --ff-only || echo "[open-design] pull skipped"
fi

cd "$CHECKOUT"
echo "[open-design] installing deps (pnpm install)"
pnpm install
echo "[open-design] starting local canvas (see upstream README if the command changed)"
pnpm tools-dev run web
