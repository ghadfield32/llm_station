#!/usr/bin/env bash
# Runs the pre-commit LLM judge array against the STAGED diff.
# TASK is taken from $JUDGE_TASK (export it, or Hermes sets it per mission),
# falling back to the branch name. Exit 2 from judgectl blocks the commit.
set -euo pipefail

JUDGE_HOST="${JUDGE_HOST:-http://judge-gate:8088}"   # reachable over Tailscale
TASK="${JUDGE_TASK:-$(git rev-parse --abbrev-ref HEAD)}"
DIFF="$(git diff --cached)"

if [ -z "${DIFF}" ]; then
  echo "No staged changes."; exit 0
fi

# judgectl is installed alongside the judge service; call it via the container
# or a local venv. Here we POST to a thin endpoint that wraps run_stage, OR run
# the module directly if available locally:
if command -v judgectl >/dev/null 2>&1; then
  printf '%s' "${DIFF}" | judgectl --stage pre-commit --task "${TASK}" --diff -
else
  printf '%s' "${DIFF}" | python3 -m judgectl --stage pre-commit --task "${TASK}" --diff -
fi
