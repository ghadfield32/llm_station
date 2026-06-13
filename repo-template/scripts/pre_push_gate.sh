#!/usr/bin/env bash
# Pass before `git push`: local validation + cross-provider skeptic on the diff.
# Wire into Hermes' allowed-commands so "push" is only reachable after exit 0.
set -euo pipefail
JUDGE="${JUDGE_HOST:-http://judge-gate:8088}"
BASE="${1:-origin/main}"
TASK="${JUDGE_TASK:-$(git rev-parse --abbrev-ref HEAD)}"

echo "==> local validation"; ruff check .; mypy . || true; pytest -q
echo "==> secret scan"; command -v gitleaks >/dev/null && gitleaks detect --no-banner || echo "(CI enforces)"
echo "==> diff vs ${BASE}"; DIFF="$(git diff "${BASE}"...HEAD)"
[ -n "${DIFF}" ] || { echo "no diff"; exit 1; }
echo "==> cross-provider skeptic"
RESP="$(curl -sS -X POST "${JUDGE}/skeptic" -H 'Content-Type: application/json' \
  -d "$(jq -n --arg t "$TASK" --arg d "$DIFF" '{task:$t,diff:$d,test_output:"see CI"}')")"
echo "${RESP}" | jq .
[ "$(echo "${RESP}" | jq -r '.allow_push')" = "true" ] || { echo "BLOCKED by skeptic"; exit 2; }
echo "gate passed"
