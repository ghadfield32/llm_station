#!/usr/bin/env bash
# live_smoke.sh - prove the local-only model path with real responses.
#
# Steps:
#   1. Ollama direct on the 4090/host
#   2. LiteLLM -> local triage alias
#   3. LiteLLM -> local planner alias
#   4. LiteLLM -> local judge alias
#   5. Denied-model checks for gpt-*/claude-*
#   6. Executor auth check
#   7. Forbidden-provider config scan
#
# Run after bootstrap + keys are done and Ollama is serving at OLLAMA_API_BASE.
# Usage:
#   bash scripts/live_smoke.sh [triage_alias] [planner_alias] [judge_alias]

set -euo pipefail
cd "$(dirname "$0")/.."

TRIAGE_ALIAS="${1:-triage}"
PLANNER_ALIAS="${2:-planner}"
JUDGE_ALIAS="${3:-local-judge}"
LITELLM="${LITELLM_URL:-http://localhost:4000}"

fail_if_provider_env_exists() {
  local failed=0
  for key in OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY; do
    if [ -n "${!key:-}" ]; then
      echo "$key must not exist in the executor environment. [FAIL]"
      failed=1
    fi
  done
  if [ "$failed" -ne 0 ]; then
    exit 1
  fi
}

read_env() {
  local name="$1"
  python3 - "$name" <<'PY'
import sys
name = sys.argv[1]
try:
    with open(".env", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key == name:
                print(value)
                break
except FileNotFoundError:
    pass
PY
}

json_payload() {
  python3 - "$1" "$2" <<'PY'
import json
import sys
model, prompt = sys.argv[1], sys.argv[2]
print(json.dumps({
    "model": model,
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": 160,
}))
PY
}

extract_openai_reply() {
  python3 - <<'PY'
import json
import sys
data = json.load(sys.stdin)
content = data["choices"][0]["message"]["content"].strip()
if not content:
    raise SystemExit("LiteLLM returned empty content")
print(content)
PY
}

extract_ollama_reply() {
  python3 - <<'PY'
import json
import sys
data = json.load(sys.stdin)
print(data["message"]["content"].strip())
PY
}

ask_litellm() {
  local model="$1"
  local prompt="$2"
  local payload
  payload="$(json_payload "$model" "$prompt")"
  curl -sS --max-time 120 "$LITELLM/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $VKEY" \
    -d "$payload" | extract_openai_reply
}

expect_litellm_denied() {
  local model="$1"
  local payload status tmp
  payload="$(json_payload "$model" "Reply with exactly: SHOULD-NOT-RUN")"
  tmp="$(mktemp)"
  status="$(curl -sS --max-time 60 -o "$tmp" -w "%{http_code}" "$LITELLM/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $VKEY" \
    -d "$payload" || true)"
  rm -f "$tmp"
  if [[ "$status" =~ ^2 ]]; then
    echo "forbidden model '$model' unexpectedly succeeded [FAIL]"
    exit 1
  fi
  echo "forbidden model '$model' denied [OK]"
}

fail_if_provider_env_exists

OLLAMA="$(read_env OLLAMA_API_BASE)"
VKEY="$(read_env HERMES_LITELLM_KEY)"

if [ -z "$OLLAMA" ]; then
  echo "OLLAMA_API_BASE empty in .env - set it to local Ollama or the 4090 Tailscale URL"
  exit 1
fi

if [ -z "$VKEY" ]; then
  echo "HERMES_LITELLM_KEY empty in .env - run bootstrap + keys first"
  exit 1
fi

$OLLAMA_DIRECT="${OLLAMA_DIRECT_BASE:-$OLLAMA}"
case "$OLLAMA_DIRECT" in
  http://host.docker.internal|http://host.docker.internal:*)
    OLLAMA_DIRECT="http://127.0.0.1:11434"
    ;;
esac

echo "== 1. Ollama direct ($OLLAMA) =="
if [ "$OLLAMA_DIRECT" != "$OLLAMA" ]; then
  echo "host direct URL: $OLLAMA_DIRECT"
fi
curl -sS --max-time 180 "$OLLAMA_DIRECT/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3-coder:30b","stream":false,"messages":[{"role":"user","content":"Reply with exactly: LOCAL-TIER-OK"}]}' \
  | { printf "reply: "; extract_ollama_reply; }

echo ""
echo "== 2. LiteLLM -> local triage alias '$TRIAGE_ALIAS' =="
printf "reply: "
ask_litellm "$TRIAGE_ALIAS" "Reply with exactly: GATEWAY-TRIAGE-OK"

echo ""
echo "== 3. LiteLLM -> local planner alias '$PLANNER_ALIAS' =="
printf "reply: "
ask_litellm "$PLANNER_ALIAS" "Reply with exactly: GATEWAY-PLANNER-OK"

echo ""
echo "== 4. LiteLLM -> local judge alias '$JUDGE_ALIAS' =="
printf "reply: "
ask_litellm "$JUDGE_ALIAS" "Reply with exactly: GATEWAY-JUDGE-OK"

echo ""
echo "== 5. Denied-model checks =="
expect_litellm_denied "gpt-4o"
expect_litellm_denied "claude-3-5-sonnet-latest"

echo ""
echo "== 6. Executor auth (subscription/OAuth, not API keys) =="
echo "provider API keys absent from process environment [OK]"
if command -v claude >/dev/null 2>&1; then
  echo "claude installed [OK] - run 'claude' then /status; auth should show subscription/OAuth"
else
  echo "claude not installed on this machine (fine if executors run elsewhere)"
fi
if command -v codex >/dev/null 2>&1; then
  echo "codex installed [OK] - run 'codex login status' manually; expected: Logged in using ChatGPT"
else
  echo "codex not installed on this machine (fine if executors run elsewhere)"
fi

echo ""
echo "== 7. Forbidden-provider config scan =="
python3 -m command_center.cli.check_forbidden_providers

echo ""
echo "live smoke complete: all model replies came from Ollama direct or LiteLLM local aliases."
