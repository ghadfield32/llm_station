# Cockpit Quickstart (agent_kanban_ui)

The first-party cockpit is the primary operator surface (decision:
`docs/reviews/2026-07-08-cockpit-decision.md`). One FastAPI + React container:
Missions (Ledger kanban), Boards (snapshot/live), Router (model lanes),
Observability, Activity, and — when enabled — SSE Chat through the same
GatewayCore every channel uses. It can never approve, merge, or deploy;
external writes stay `governed_by_ledger` (`configs/ui.yaml`).

## Start it

```powershell
# one button (starts the control plane too, then opens the UIs):
uv run cc start

# or just the cockpit container, if the stack is already up:
docker compose --profile ui up -d --build agent-kanban-ui

# open it (also prints the URLs):
uv run cc open cockpit
```

Local URL: http://127.0.0.1:8787 (loopback-bound; `KANBAN_UI_PORT` overrides).

## Two modes

- **Read-only board** (no creds in the container): remove
  `KANBAN_UI_CHAT_ENABLED=1` and the growth-os/.env mounts in
  `docker-compose.yml`. The UI reads the Ledger, the agent-call log, the board
  snapshot, and the kanban event log. No write path exists.
- **Full console** (default compose config): chat + the governed action verbs.
  Every write goes through the action layer (Approved is structurally refused;
  L3/L4 approve/kill stay in the signed Ledger UI).

## Phone access (Tailscale — never `tailscale funnel`)

Per `docs/operations/remote-access.md`, everything binds loopback and is
exposed tailnet-only:

```powershell
tailscale serve --bg --https=8787 http://127.0.0.1:8787
```

Then on the phone (on the tailnet): `https://vengeance.taile6a055.ts.net:8787`.
AppFlowy's native mobile app remains the fallback for board approvals on the
go (`docs/job_search/READINESS_FAQ.md` has its one-time board setup).

## Honest failure states (what "broken" actually means)

- `/api/missions` → 502: the Ledger is unreachable — never rendered as an
  empty "no work" board. Start the stack: `uv run cc up`.
- `/api/boards` → 503 with a path: the AppFlowy board snapshot is missing —
  run `make kanban-board-snapshot` on the worker, or ignore if you don't use
  the AppFlowy projection.
- `/api/boards/live` or chat → 503: this deployment is read-only
  (`KANBAN_UI_CHAT_ENABLED` unset) — that is a mode, not a bug.
- Board looks wrong in AppFlowy itself: `uv run cc job-search board-doctor`
  prints the one-time Group-by-Status fix.

## Validate

```powershell
uv run cc doctor          # internal_ui_config check covers this service
uv run pytest tests/test_agent_kanban_ui.py tests/test_kanban_ui_events.py -q
curl http://127.0.0.1:8787/api/health
```
