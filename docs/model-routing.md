# Model routing

LiteLLM is local-only in this repo. Every LiteLLM role renders to `ollama_chat/...`
and uses `OLLAMA_API_BASE`.

## Runtime Lanes

| Lane | Runs | Auth | API charge |
| --- | --- | --- | ---: |
| LiteLLM local gateway | `triage`, `planner`, `local-judge`, `architect-judge`, `security-judge`, `coder` aliases | `HERMES_LITELLM_KEY` / `JUDGE_GATE_LITELLM_KEY` | $0 provider API |
| Claude Code executor | primary coding missions in leased worktrees | Claude subscription/OAuth login | $0 provider API |
| Codex executor | fallback coding missions in leased worktrees | ChatGPT login | $0 provider API |

The executor CLIs are not generic APIs for Hermes or LiteLLM. They are controlled
subprocesses that work inside leased worktrees.

## Local Roles

- `triage`: first-pass risk sorting, small summaries, scope checks.
- `planner`: plans and validation plans through local Ollama.
- `local-judge`: continuous cheap judging, logs, data checks.
- `security-judge`: local security/scope skeptic.
- `architect-judge`: local high-effort planner/debugger role.
- `coder`: local model alias used for dry-runs and fallback summaries, not the Claude/Codex executor auth path.

## Gates

Risk tiers still control what can happen:

- L0/L1: read and plan.
- L2: local branch/worktree edits.
- L3: external writes such as push/PR require human approval.
- L4: merge, deploy, publish, secrets, delete are manual only.

Deterministic tools still run before LLM judges. The defensive-coding judge still blocks
swallowed exceptions, fake fallbacks, redundant guards, and out-of-scope rewrites.

## Failure Mode

No cloud fallback exists. If Ollama is unavailable or the LiteLLM virtual key is not allowed
to call an alias, the request fails closed.
