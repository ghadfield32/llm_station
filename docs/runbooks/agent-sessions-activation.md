# Runbook — make Claude & Codex show as *available* in the cockpit

**Why they don't show today (verified root cause).** The adapters work — on this
host `registry.probes()` reports `codex_agent=available` and
`claude_code_local=available` (Claude Max subscription, **no API key**). But the
cockpit never *computes* availability itself: it **proxies** `/api/agent-harnesses`
to the host worker (`cc agent-worker`), and that proxy is gated by **three** env
vars. If any is unset, or no worker is running, or the deployed build predates the
real harnesses, the picker shows "Agent sessions unavailable". This is a
deployment/wiring gap, not an adapter bug.

Three things must all be true:

1. A `cc agent-worker` process is running **as the same OS user** that owns the
   `codex login` and `claude auth login` sessions.
2. The cockpit has `KANBAN_UI_AGENT_SESSIONS_ENABLED=1`, `AGENT_WORKER_URL`, and
   `AGENT_WORKER_TOKEN`.
3. The worker + cockpit are built from a branch that contains the real harnesses
   (this PR chain), not `main`.

## Steps

### 1. Start the host worker (as your user, with the CLI logins present)

```powershell
# same shell/user that ran `codex login` and `claude auth login`
$env:LEDGER_BASE_URL   = "http://127.0.0.1:8090"     # your running Ledger
$env:AGENT_WORKER_TOKEN = "<generate a strong secret>"
$env:AGENT_WORKER_USAGE = "1"    # worker records provider limits to the Ledger (durable, headless-safe)
# optional: install the agent SDK extras so the API lanes probe too
#   uv sync --extra agent-codex --extra agent-claude
uv run cc agent-worker        # binds localhost:8791 by default
```

Verify the worker sees the runtimes (no browser needed):

```powershell
$h = @{ Authorization = "Bearer $env:AGENT_WORKER_TOKEN" }
Invoke-RestMethod "http://127.0.0.1:8791/api/agent-harnesses" -Headers $h |
  Select harness_id, available, detail
# expect: codex_agent available=True, claude_code_local available=True,
#         claude_agent available=False (no ANTHROPIC_API_KEY — the optional lane)
```

Check a model catalog:

```powershell
Invoke-RestMethod "http://127.0.0.1:8791/api/agent-harnesses/claude_code_local/models" -Headers $h
Invoke-RestMethod "http://127.0.0.1:8791/api/agent-harnesses/codex_agent/models" -Headers $h
```

### 2. Point the cockpit at the worker + enable the surface

Set on the cockpit container/process (same value for the token):

```env
KANBAN_UI_AGENT_SESSIONS_ENABLED=1
AGENT_WORKER_URL=http://host.docker.internal:8791   # or 127.0.0.1:8791 if same host
AGENT_WORKER_TOKEN=<same secret as the worker>
KANBAN_UI_USAGE_ENABLED=1        # so the selector can show usage/limit badges
KANBAN_UI_USAGE_CODEX=1          # register the Codex rate-limit collector
KANBAN_UI_USAGE_CLAUDE=1         # tee live Claude rate_limit events into the usage store
KANBAN_UI_USAGE_LEDGER=1         # read the SAME durable Ledger the worker writes (restart-proof, one authoritative store)
```

Rebuild/restart the cockpit **from this branch** (it must contain
`claude_code_local`). Then in the UI: **Agent Sessions → pick a runtime** →
Claude Agent (local subscription) or Codex Agent → the **model** and **reasoning
effort** pickers populate from the live catalog → pick a registered repo → start
a read-only session.

### 3. If a runtime shows unavailable, read the reason

The cockpit surfaces the harness's concrete `detail` — never a generic
"unavailable". Common real reasons and fixes:

| detail says | fix |
|---|---|
| `claude CLI is not logged in` | run `claude auth login` as the worker's user |
| `codex authentication probe failed … run codex login` | run `codex login` |
| `ANTHROPIC_API_KEY is not set` (claude_agent) | expected — that's the optional API lane; use `claude_code_local` |
| `claude-agent-sdk is not installed` (claude_agent) | expected without `--extra agent-claude`; ignore for the local lane |
| worker 502 / "agent worker unreachable" | the `cc agent-worker` process isn't running or the URL/token is wrong |

## Safety

- **Never** run a deployment proof by hand — use
  `scripts/run_agent_deployment_proof.ps1` (it refuses unless it's an isolated
  proof project, so a proof can't touch the real `llm_station-*` containers).
- The worker binds localhost by default; the token is the only auth. Keep it in
  the host `.env`, never in the browser or a committed file.
- `claude_code_local` strips `ANTHROPIC_API_KEY` from its subprocess env so a
  stray key can never switch the subscription lane to metered API billing.
