# Decision: first-party agent_kanban_ui is the primary cockpit

Date: 2026-07-08
Status: decided
Related: `docs/cockpit-mission-prompt.md` (execution plan),
`docs/kanban/AGENT_KANBAN_SURFACE.md` (UI tracker),
`docs/architecture/ui-options.md`, `docs/job_search/READINESS_FAQ.md`
(AppFlowy one-time board fix).

## Decision

```text
Primary cockpit:        services/agent_kanban_ui (first-party FastAPI + React/Vite)
Board source of truth:  kanban event log + Ledger + provider registry
Optional projection:    AppFlowy (mobile approvals, knowledge boards)
External board tools:   watch-list only; none adopted
```

AppFlowy is NOT abandoned and NOT the cockpit. It keeps the two jobs it is
uniquely good at — free native mobile apps that officially connect to a
self-hosted server (our Tailscale phone flow), and lightweight knowledge
boards — and loses the job it cannot do: a typed, visually rich operator
cockpit.

## Why (verified 2026-07-08)

**AppFlowy's ceiling is structural, not cosmetic.** The self-hosted REST API
is insert/read-oriented: it cannot delete rows, set a board view's group-by
field, or create select options, and upstream bug #8665 (PUT row returns
200 but SingleSelect cells silently stay empty) is open. The blank
"Untitled" cards were its default starter rows plus default "Type" grouping
— data was always correct (board-doctor: Status field with all 8 stages,
every real card tagged). Custom per-type card rendering (posts as LinkedIn
previews, jobs with fit/salary/blockers) is impossible in AppFlowy at any
effort level.

**Plane was rejected on fact-check.** The attractive claims did not survive:
its mobile apps only connect to the self-hosted *Commercial* Edition
(v1.12+), not the AGPL Community Edition; Workflows are the paid Business
tier and approval gates are Enterprise. Its MCP server is real, but not
worth adopting a third surface plus a second authority boundary for.

**AFFiNE / Vikunja / Focalboard / Huly rejected.** AFFiNE: open self-host
mobile connection bugs (June 2026), EE-licensed backend. Vikunja: mobile app
is alpha. Focalboard: unmaintained (open call for maintainers). Huly: no
mobile apps, heavy self-host stack. No open-source option combines free
self-hosted mobile + a rich API + custom card rendering.

**The first-party path is mostly built.** `configs/kanban_boards.yaml` is
already a provider-agnostic registry (`provider: appflowy |
command_center_ui`; `betts_basketball` already runs on the internal
provider); the kanban event log is already the source of truth with
AppFlowy as one projection; and `services/agent_kanban_ui/` already has
Missions, Boards (drag-to-move), Router, Observability, Activity, and SSE
Chat through GatewayCore, governed by `configs/ui.yaml` with wall verbs
forbidden.

## Consequences

1. Engineering investment goes to the first-party UI: BoardProvider
   abstraction with explicit capability flags, typed domain cards
   (jobs/posts/books/papers/repos/DAGs/upkeep/missions), PWA over Tailscale.
2. AppFlowy write paths must fail loud on its unsupported operations, never
   silently no-op.
3. Boards migrate per-board via the registry `provider:` flag; AppFlowy
   entries may remain as optional projections.
4. AppFlowy AI, Plane, or any external tool never becomes a second brain:
   one action layer, one approval wall, one gateway, one merge wall.
5. External tools stay on the watch-list through the research-digest intake
   (`docs/watch-list/`, `cc research-digest`).
