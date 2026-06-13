# Autonomy idea map — channels, brain, knowledge, and the wall

The complete picture of the system as built and where it grows. One sentence
version: **many channels, one brain gateway, one action layer, one approval
wall** — open-source local models do the routine work; Claude Code/Codex are
engaged through gated missions for the big things.

```
 CHANNELS (talk to it anywhere)              KNOWLEDGE (updates itself)
 ┌─────────────────────────────┐             ┌──────────────────────────────┐
 │ AppFlowy boards (phone/web) │             │ papers/repos/signals  hourly │
 │ chat.bat (terminal, Ollama) │             │ guidelines (standards+feeds) │
 │ Claude Code via MCP         │             │ packages (semver vs PyPI)    │
 │ Discord bot (anywhere)      │             │ dags (betts importer)        │
 │ [future: SMS/email/voice]   │             │ library/lessons/notes (you)  │
 └──────────────┬──────────────┘             └──────────────┬───────────────┘
                │  natural language                         │ rows
                ▼                                           ▼
 ┌─────────────────────────────┐  reads/writes  ┌──────────────────────────┐
 │ BRAIN GATEWAY: LiteLLM:4000 │◄──────────────►│ ACTION LAYER             │
 │  triage / planner / coder / │   tool calls   │ growthos/actions.py      │
 │  local-judge → Ollama       │                │ (15 tools, one source of │
 │  (qwen3/devstral, $0, local)│                │  truth for every agent)  │
 └─────────────────────────────┘                └────────────┬─────────────┘
                                                             │ add_mission_card
                                                             ▼  (Backlog only)
 ┌───────────────────────────────────────────────────────────────────────────┐
 │ THE WALL — human approval, enforced three ways:                           │
 │  1. agents cannot set Approved (actions.set_status refuses)               │
 │  2. the bridge applies ONLY Approved cards (configs/kanban.yaml)          │
 │  3. L3/L4 missions additionally hold at the Ledger awaiting approval      │
 │                 YOU drag the card → that is the entire UX                 │
 └─────────────────────────────────────┬─────────────────────────────────────┘
                                       ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ EXECUTION PLANE: bridge → Ledger:8091 → risk gates → judges (local      │
 │ models, judging against standards.yaml) → executors (Claude Code/Codex  │
 │ in leased worktrees) → PR behind the GitHub wall → morning-brief worklog │
 └─────────────────────────────────────────────────────────────────────────┘
```

## Where each piece lives

| Piece | Path | State |
|---|---|---|
| Action layer (15 tools) | `appflowy_kanban/growth-os/growthos/actions.py` | live |
| Local assistant | `growth-os/chat.bat` → `growthos/assistant.py` (Ollama) | live |
| Claude MCP server | `growth-os/agent/growthos_mcp.py` (stdio/`--http`) | live |
| Chat gateways (Discord/Slack/Telegram/WhatsApp) | `src/command_center/channels/` (LiteLLM `triage`; see [channels.md](channels.md)) | built; each needs its token |
| Knowledge watchers | `growthos/{curate,guidelines,packages}.py` | live (hourly/daily/host) |
| Bridge | `scripts/kanban_bridge.py` (Approved-only, CardKey writeback) | live; schedule = your one-liner |
| Ledger/gates/judges | `services/*`, `configs/{gates,judges,standards}.yaml` | live |
| Project stamper | `growth-os/scripts/new_project.py` | live (demo-proven) |

## The Magentic-One-style reading (inspiration, mapped honestly)

Multi-agent orchestrators (AutoGen/Magentic-One et al.) use an orchestrator
that decomposes tasks, delegates to specialist agents, and tracks a ledger of
progress. This system already has those organs — with one improvement: the
**orchestrator's commit step is a human drag**, not a model decision.

- Orchestrator = bridge + Ledger (task decomposition lives in mission Action/
  Acceptance fields, drafted by any channel's LLM)
- Specialists = LiteLLM roles (triage/planner/coder/judge on local models) and
  Claude Code/Codex as the heavyweight executors inside leased worktrees
- Progress ledger = the Ledger service + the brief's Mission worklog
- The standards (configs/standards.yaml) ride along three ways: rendered into
  each repo's CLAUDE.md/AGENTS.md, quoted by judges, mirrored in `guidelines`

## What "autonomous" means here, phase by phase

- **Phase 1 (now):** every knowledge stream self-updates; any channel can
  read/triage/draft; you approve by drag; bridge dispatches (after you run the
  schtasks one-liner in docs/kanban-integration.md); brief reports outcomes.
- **Phase 2 (next, small):** Discord token in `.env` → the same powers from
  any device with Discord, including proactive pushes (a `notify` action that
  DMs you the brief + cards awaiting approval — pull becomes push).
- **Phase 3 (when prod box returns):** stack migrates to the Linux host
  (runbook ready), systemd timers replace Task Scheduler, the workstation
  becomes a pure GPU node (Ollama only) — survives sleep, true always-on.
- **Phase 4 (judgement-heavy autonomy):** proactive_runner proposes cards
  from observations (failing DAGs via the dags board, major package bumps,
  stale guidelines) — still landing in Backlog. Autonomy grows by proposing
  more, never by approving itself.

## Deliberately not built (and why)

A second model gateway (LiteLLM is it) · a separate channel *service*
(channels are thin transports onto the action layer; Discord above is ~200
lines for exactly this reason) · agent-side approval or scheduled
self-dispatch installed by an agent (twice classifier-blocked today — the
wall catching its own builder is the system working) · public exposure
(tailnet only; Claude-mobile remote connectors can't reach it and that
trade is accepted) · Hermes (phantom image; LiteLLM+Ollama already serve
its role).
