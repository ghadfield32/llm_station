#!/usr/bin/env bash
# Cron/systemd entrypoint. Runs the curator, then builds the brief.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m growthos.curate
# brief generation hook (extend brief.py main() to pull from AppFlowy):
# python -m growthos.brief
