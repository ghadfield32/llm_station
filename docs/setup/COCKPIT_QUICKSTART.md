# Cockpit Quickstart (agent_kanban_ui)

The first-party cockpit is the primary operator surface (decision:
`docs/reviews/2026-07-08-cockpit-decision.md`). One FastAPI + React container:
All Boards (Jobs, Posts, Books, Papers, Repos, DAGs, Upkeep, Missions, Tasks),
Controls (board registry, job-search settings, profile defaults, runtime APIs),
Router (model lanes), Status, Metrics, Activity, and — when enabled — SSE Chat
through the same GatewayCore every channel uses. It can never approve, merge,
submit jobs, or deploy; external writes stay `governed_by_ledger`
(`configs/ui.yaml`).

Board-by-board usage is in `docs/setup/COCKPIT_BOARD_GUIDE.md`. Mobile,
open-source, and storage setup decisions are in
`docs/setup/COCKPIT_MOBILE_OPEN_SOURCE_SETUP.md`.

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

- **Read-only board**: remove `KANBAN_UI_CHAT_ENABLED=1` in
  `docker-compose.yml`. The UI reads the Ledger, the agent-call log, the local
  board snapshot, and the kanban event log. No write path exists.
- **Full console** (default compose config): chat + the governed action verbs.
  Every write goes through the action layer (Approved is structurally refused;
  L3/L4 approve/kill stay in the signed Ledger UI). Domain-board drag/drop and
  in-app job question preset edits require this mode. Controls -> All Boards
  can add/remove/update domain boards by writing `configs/domain_surfaces.yaml`
  only when `KANBAN_UI_DOMAIN_CONFIG_WRITES=1` and `./configs` is mounted
  writable; every save validates the full file with `DomainSurfacesConfig`.
  Job-search daily limits and role-focus keyword overrides write to
  `data/job_search/profile/search_settings.yml`, then the shared
  `load_config()` path reads them for CLI/DAG runs. The `./generated` mount must
  be writable because Jobs drag/drop appends governed events to
  `kanban-events.jsonl`.

## Phone access (Tailscale — never `tailscale funnel`)

Per `docs/operations/remote-access.md`, everything binds loopback and is
exposed tailnet-only:

```powershell
tailscale serve --bg --https=8787 http://127.0.0.1:8787
```

Then on the phone (on the tailnet): `https://<your-machine>.<your-tailnet>.ts.net:8787`
(find the hostname with `tailscale status`; on this deployment it is
`vengeance.taile6a055.ts.net`).
The cockpit PWA is the supported mobile board surface.

## Install on phone

Open the tailnet URL in the phone browser, then use the browser's install /
add-to-home-screen action. The cockpit ships a web app manifest and a service
worker that caches static app shell assets only. `/api/*` responses and
non-GET requests are always network-only so private job, chat, and board
payloads are not persisted for offline use.

On phone-width screens, the cockpit switches to a bottom nav, full-screen
drawers, larger touch targets, top horizontal scrollbars for board/tab lanes,
and per-card `Move to...` menus. Drag/drop still works on desktop, but phone
moves should use the menu; the same governed write endpoint is used either way.

The normal mobile route is **All Boards -> Jobs**. Missions are also available
inside All Boards; the old top-level Missions/Boards split is intentionally not
the primary phone navigation anymore.

## Chat specialists

The Chat page is still the cockpit channel, not a separate bot. It sends turns
to GatewayCore through the configured LiteLLM `chat` role and passes a stable
`conversation_id` so the backend can keep thread context. The app keeps recent
chat shortcuts in a shared server-side metadata file at `KANBAN_CHAT_THREADS`
(defaulting beside `KANBAN_EVENT_LOG`) and uses browser local storage only as a
fallback cache. This stores launcher metadata only, not full transcripts.

Optional specialist links can be added without changing the cockpit runtime:

```powershell
$env:ORCA_CHAT_URL="https://example-orca-chat"
$env:OMNIAGENT_CHAT_URL="https://example-omniagent-chat"
$env:OXYGENT_CHAT_URL="https://example-oxygent-dashboard"
docker compose --profile ui up -d --build agent-kanban-ui
```

Use ORCA first for document-heavy job materials such as resumes, PDFs,
screenshots, forms, and tables. Use OmniAgent/Omnigent later for long
video/audio or screen-recording evidence. Keep OxyGent as a framework spike for
planning graphs, visual debugging, and auditability. All three remain external
handoffs; governed board writes, approvals, submits, merges, and deploys stay
behind GatewayCore, the action layer, and the Ledger wall.

## Honest failure states (what "broken" actually means)

- `/api/missions` → 502: the Ledger is unreachable — never rendered as an
  empty "no work" board. Start the stack: `uv run cc up`. If you are running
  `uvicorn` directly on the Windows host, set
  `LEDGER_BASE_URL=http://127.0.0.1:8091`; `http://ledger:8090` only resolves
  inside Docker Compose.
- `/api/boards` → 503 with a path: the local board store or snapshot is missing —
  confirm `generated/boards/` is mounted at `/snapshot/boards` and writable in
  full-console mode.
- `/api/boards/live` or chat → 503: this deployment is read-only
  (`KANBAN_UI_CHAT_ENABLED` unset) — that is a mode, not a bug.
- Controls -> All Boards edits fail: confirm the full-console compose service
  has `KANBAN_UI_DOMAIN_CONFIG_WRITES=1` and `./configs:/app/configs` without
  `:ro`. The editor writes only `configs/domain_surfaces.yaml`; provider
  registry changes still belong in `configs/kanban_boards.yaml`.
- Jobs/Posts/etc. missing from the sidebar: rebuild the SPA and restart the
  cockpit process so it picks up the current `configs/domain_surfaces.yaml`.
- `router: models.yaml not at configs\models.yaml` with `Sections 0` means the
  running process is resolving a relative `KANBAN_UI_CONFIGS` from the wrong
  cwd. Current builds anchor relative paths at cockpit startup; restart uvicorn
  or the container and confirm `/api/debug/runtime` shows an absolute
  `configs_dir` under this repo.
- Jobs cards will not drag in read-only mode. Start the cockpit with
  `KANBAN_UI_CHAT_ENABLED=1` for governed drag/drop; the move writes a kanban
  event and still cannot set approval/merge/deploy/delete states. On a phone,
  use the card's `Move to...` menu instead of dragging.
- Jobs drag/drop returns `domain writes are not available`: open Diagnostics and
  check `kanban_event_log.writable` plus `board_store_dir.writable`. In Docker
  full-console mode, `./generated` must be mounted as `/snapshot` without `:ro`.
- Job-search limits or role-focus edits fail: open Controls and check the
  `search_settings` path. The cockpit writes only the profile override file,
  not `configs/job_search.yaml`.
- The Chat page's runtime panel should say `GatewayCore` + `LiteLLM`.
  ORCA, OmniAgent/Omnigent, and OxyGent should show as `not linked` unless the
  matching `*_CHAT_URL` env var is set. They are launch links, not active
  runtime dependencies.
- A board looks stale: inspect `/api/debug/runtime`, then verify the board store
  and governed kanban-event log paths shown there.
- `/api/debug/runtime`: non-secret runtime diagnostics for the exact Ledger
  URL, DNS/HTTP probe result, static dir, config dir, event log, board store,
  and board snapshot paths. Use this before changing code.

## Validate

```powershell
uv run cc doctor          # internal_ui_config check covers this service
uv run pytest tests/test_agent_kanban_ui.py tests/test_domain_surfaces.py tests/test_kanban_ui_events.py -q
curl http://127.0.0.1:8787/api/health
```
