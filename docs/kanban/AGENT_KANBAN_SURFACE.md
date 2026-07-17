# Agent Kanban Surface — project tracker

**Status**: in progress (2026-06-13) · **Owner**: agent-kanban-surface · **Risk**: L1–L2 (harness/agent-loop
changes + an observer-only observability lane + an optional read-mostly Phase-4 web UI; AppFlowy/Ledger stay the
write-authority, Approved stays human-only).

The operator tracker for giving our agents a kanban surface they actually use well — and us the observability to
tune it. Built by combining **AppFlowy + Ledger** (kept as the data/authority layer), **Cline's harness-owned-state
+ intent-verb patterns** (adopted in our agent loops), and a **first-party Cline-styled web app** (the styling +
observability surface, repurposing the already-budgeted WebUI slot).

> **Scope decision (2026-06-13).** llm_station is the LLM control plane, not the basketball forecasting stack.
> We apply the **transferable principles** of `docs/reference/betts-basketball-standards/` (data-derived decisions, no defensive coding, no
> leakage/temporal safety, module-tree + stage header, blocking validation gate, multi-session git hygiene) and
> NOT the infrastructure (R2, Railway, fleet, medallion). Infra-coupled items are marked **N/A (no infra)**.

> **Why this is not the §13 "another abstraction layer" anti-pattern.** It fixes a failure actually hit (agents
> mis-drive the board; no way to observe/tune it), keeps AppFlowy as the sole write-authority (no competing
> boundary), and the UI fills the **already-budgeted** Phase-4 WebUI slot (`configs/ui.yaml` / `WebUIConfig`),
> repurposed from the now-deferred Hermes WebUI/Kanban (see MASTER.md change log 2026-06-13 Cline DEFER).

---

## 1. The root problem (diagnosed, confirmed in code)

Our agent loops make the **model** the board manager: it must pick the right database of 7, type exact per-board
enum strings, re-derive row keys, and hold the board's current contents in its head — because **nothing re-injects
board state between turns**. The scar tissue proves it: the `seen` loop-breaker + "you already called this with
identical arguments" + forced-final-answer + "validate enums LOUDLY"
([assistant.py](../../../appflowy_kanban/growth-os/growthos/assistant.py),
[channels/core.py](../../../src/command_center/channels/core.py)).

Cline (verified from its source) inverts this: the model emits **intent**; the **harness** owns the canonical state
and **re-injects the single source of truth on a fixed cadence**; transitions/completion are constrained signals.
We adopt that inversion.

## 2. Module tree (target)

```
src/command_center/channels/
  board_state.py        (NEW) STAGE 1  render_board_state() — canonical state → compact block; fail-loud
  core.py                     STAGE 1  GatewayCore._run_turn — re-inject board_state each turn
appflowy_kanban/growth-os/growthos/
  assistant.py                STAGE 1  run_turn — re-inject board_state each turn
  actions.py                  STAGE 2  intent verbs (start/stage/block/finish/reject_card, *_todo) + _resolve()
src/command_center/kanban/    (NEW)            the observability lane
  __init__.py
  events.py             (NEW) STAGE 3  emit board events → Ledger POST /event (GlobalEventIn); decision-time only
  features.py           (NEW) STAGE 3  features_of() — pre-decision signals only (no leakage)
  tuning.py             (NEW) STAGE 3  cadence learner (champion/challenger vs config; abstain < min_decisions)
  digest.py             (NEW) STAGE 3  read event spine → Markdown metrics digest (real data; fail-loud)
  validate.py           (NEW) STAGE 3  blocking N/N PASS gate (run_gate)
src/command_center/cli/
  kanban_surface.py     (NEW)          `digest` + `validate` subcommands (make kanban-digest / kanban-validate)
configs/agent_surface.yaml (NEW)       AgentSurfaceConfig: cadence/size/fuzzy knobs + tuning sub-block
services/agent_kanban_ui/  (NEW)       Phase-4 FastAPI + static SPA; read-mostly; governed writes only
```

## 3. Stages (linear; each reads only prior-stage state)

| # | Stage | Module | Standard / gate |
|--:|-------|--------|-----------------|
| 1 | re-inject canonical board state every turn | `board_state.py` + both loops | fail-loud on fetch error; never inject empty/stale state |
| 2 | model emits intent verbs; harness owns enum+key resolution | `actions.py` | Approved structurally refused; fuzzy miss → candidates, no silent guess |
| 3 | log every action as a Ledger event; tune cadence from data | `kanban/*` | knobs in config (no literals); decision-time features only (no leakage); N/N gate |
| 4 | first-party styled board + observability panel | `services/agent_kanban_ui/` | read-mostly; writes governed by Ledger; UI cannot set Approved |

## 4. Standards-conformance matrix

| Standard | How met | Status |
|---|---|---|
| No hardcoded thresholds | cadence/size/fuzzy/tuning all in `configs/agent_surface.yaml` (`AgentSurfaceConfig`, in `make validate`) | Phase 1/3 |
| Data-derived decisions | cadence learner mirrors `acceptance.py` (temporal split, champion/challenger, **abstain < min_decisions**) | Phase 3 |
| No data leakage | `features_of()` uses pre-decision signals only; gate asserts no leakage tokens | Phase 3 |
| No defensive coding / no fallbacks | board-state fetch fails loud (like `network_health()`); no stale/empty injection | Phase 1 |
| Linear, single-source-of-truth | harness owns state; model contributes content only | Phase 1/2 |
| Blocking validation gate | `make kanban-validate` N/N PASS (mirrors `discovery/validate.py`) | Phase 3 |
| Authority unchanged | AppFlowy/Ledger keep write-authority; Approved human-only; UI read-mostly | all |
| Multi-session git | branch `feat/agent-kanban-surface`; exact-path staging; no `-A` | all |
| R2 / fleet / medallion / Railway | **N/A (no infra)** | — |

## 5. Done / left (kept live)

- [x] **Phase 0** — this tracker; reconcile stale Hermes-WebUI refs (ui.yaml/ui-options.md/ecosystem.md); MASTER.md changelog
- [x] **Phase 1** — `agent_surface.yaml` + `AgentSurfaceConfig`; `board_state.py`; re-inject in both loops; `test_board_state.py` (7/7). validate PASS · ruff clean · mypy baseline-consistent (yaml/growthos env-imports only) · no import cycle.
- [x] **Phase 2** — intent verbs (`stage/block/reject_card`, `start/finish/block_todo`) + `_resolve()` fuzzy addressing (data-derived `fuzzy_min_ratio`, candidates-on-miss); `set_status` dropped from both agent surfaces (assistant `TOOL_FNS` + MCP); `test_actions_intent.py` (7/7). ruff clean.
- [x] **Phase 3** — reused the existing agent-call log as the event spine (no parallel store); `kanban/` = metrics + features + tuning (abstaining champion/challenger) + digest + N/N gate; `make kanban-digest` + `make kanban-surface-validate` (6/6 PASS); `test_kanban_surface.py` (9/9). The gate caught a real verb→terminal-column bug pre-merge. ruff clean.
- [x] **Phase 4** — `services/agent_kanban_ui/`: read-only FastAPI (Ledger missions + agent-call metrics) + React/Vite/TS Cline-styled SPA, single-container multi-stage Dockerfile, compose `profiles: ["ui"]`. `configs/ui.yaml`/`WebUIConfig` field repointed `hermes_webui`→`agent_kanban_ui`. `test_agent_kanban_ui.py` 5/5. Read-only by construction (no write path; approve/kill stay in signed Ledger). **Scope note:** built as the read-only observability board (the highest-value, container-clean shape); live drag→transition was intentionally NOT added because mission transitions are gated/signed in the Ledger — the UI links out rather than duplicate the HMAC auth. **SPA authored but not npm-built in-session** (builds in the Docker node stage).
- [x] **Final** — MASTER.md §4 service table + §11 module tree + change log updated each phase; full validate/kanban-surface-validate/pytest/ruff sweep green.

## Decisions & honest deviations from the original plan

- **Event spine reused, not rebuilt.** The plan said "log board actions as Ledger global events"; the existing `growthos.observability` agent-call log already records every tool call on every surface, so Phase 3 reads *that* single source instead of adding a parallel store. Strictly better (no duplication).
- **UI is read-only, not read-mostly-with-writes.** Mission transitions/approvals are gated and HMAC-signed in the Ledger; giving a browser UI that secret would weaken the wall. So the UI observes and links out — `external_write_policy: governed_by_ledger` holds by construction. AppFlowy remains the human staging surface (drag-to-Approve there, as designed).
- **Cadence auto-tuning is honestly deferred.** `refresh_every_rounds` is config-externalized and its outcome metric (redundant-call rate) is measured, but auto-tuning it needs a controlled cadence experiment — not fabricated. The one knob with a genuine data-derived tuner is `fuzzy_min_ratio` (abstains until labelled resolution outcomes exist). No fake values.

## 6. Parity review — vs AppFlowy (availability + databases) and Cline (look & feel)

Where we stand against the two yardsticks, and what's left (Phase 5).

### What we already match
- **Cline — agent ergonomics:** harness owns board state + re-injects it (Phase 1); model emits intent verbs, not CRUD (Phase 2). This is the core of why Cline's agent stays on-rails.
- **Cline — look & feel:** dark column board, status dots, risk-colored cards, observability panel (Phase 4).
- **AppFlowy — authority/availability:** AppFlowy/Ledger keep write-authority; the UI is always-on capable (compose, loopback+Tailscale).

### Gaps to close (Phase 5)
| # | Gap | Against | Severity |
|--:|-----|---------|----------|
| 5.1 | **Agent lost triage on papers/repos/signals/library/lessons** when `set_status` was dropped — only cards/todos/dags have verbs | AppFlowy databases (agent use) | **regression — must fix** |
| 5.2 | UI shows only the Ledger missions lane — none of the AppFlowy boards (mission_intake cards, todos, dags, research inboxes) | AppFlowy databases (breadth) | high |
| 5.3 | No card/mission **detail** (events, diffs, approvals, leases) and no **agent activity feed** — Cline shows the agent's latest message/diff per card | Cline look & feel (agent use) | high |
| 5.4 | Docs + full sweep for the above | — | med |
| 5.5 | Detailed end-to-end review across every use case + look/feel | — | med |

### Phase 5 — Done / left
- [x] **5.1** — title-addressed `move_item(database, title, status)` restores agent action on every board with statuses (papers/repos/signals/library/lessons), loud validation, Approved still refused, harness owns the key. Dedicated verbs remain the ergonomic path. Added to assistant `TOOL_FNS` + MCP. `test_actions_intent.py` (13/13).
- [x] **5.2** — `actions.board_view()` (whole-board grouped read) + `board_state.all_boards_json()` (per-board fail-loud) + `kanban_surface board-snapshot` CLI / `make kanban-board-snapshot` writing `generated/board-snapshot.json` + UI `/api/boards` (reads the snapshot, 503-on-missing) + frontend board tabs (mission_intake/todos/dags/papers/repos/signals). Tests across `test_actions_intent.py` + `test_agent_kanban_ui.py`.
- [x] **5.3** — `/api/activity` (recent agent-call log, newest-first) + clickable mission **detail drawer** (`/api/mission/{id}` events/status/risk) + `metrics.recent_calls()`. Frontend: activity feed panel + drawer with event tags. `test_agent_kanban_ui.py` (10/10).
- [x] **5.4** — MASTER + tracker updated; `make validate` + `kanban-surface-validate` + full pytest + ruff green.
- [x] **5.5** — detailed review; per-use-case verdicts recorded below.

> **Resolved tradeoff (was: AppFlowy creds in the UI container).** Instead of the UI reading AppFlowy directly, the board read runs on the **worker** (`make kanban-board-snapshot`, where growthos + creds already live) and writes `generated/board-snapshot.json`; the UI mounts that file **read-only**. So the UI container holds **no AppFlowy credentials** — same pattern as the agent-call log. Snapshot freshness is shown in the UI (`generated_at`); a missing snapshot is a loud 503, never an empty board set.

## 7. Detailed review (5.5) — per use-case verdicts

| Use case | Path | Verdict |
|---|---|---|
| Agent triages research inboxes (papers/repos/signals) | `move_item` | ✅ restored |
| Agent updates library/lessons status | `move_item` | ✅ restored |
| Agent moves mission cards (stage/block/reject) | dedicated verbs | ✅ |
| Agent moves todos (start/finish/block) | dedicated verbs | ✅ |
| Agent updates DAG board | `update_dag` (+ `move_item`) | ✅ |
| Agent never has to recall board state | board-state re-injection (Phase 1) | ✅ |
| Agent can't fumble enums/keys | title addressing + loud validation + board-state vocab | ✅ |
| Human views EVERY AppFlowy board in the new UI | `/api/boards` ← worker snapshot, tabbed | ✅ read-only |
| Human views the execution lane (missions) | `/api/missions`, Cline columns | ✅ |
| Human drills into a mission (events/status/risk) | clickable card → drawer | ✅ |
| Human watches what agents are doing live | `/api/activity` feed | ✅ |
| Operator tunes the surface from real data | `make kanban-digest` + UI obs panel | ✅ (data-derived; cadence learner abstains until labelled) |
| Approve / kill a mission | links out to the signed Ledger UI | ✅ by design (UI never holds the HMAC secret) |
| Availability of board data | worker snapshot file, mounted RO | ✅ snapshot self-bootstraps growth-os + verified live (6 boards, real data); fresh via user-run schtasks/cron (below) |
| Look & feel (Cline) | dark board, status dots, risk colors, tabs, drawer, activity | ✅ SPA **compiles** (tsc+vite) and serves live; pixel pass = open the URL below |

### Snapshot scheduling (the freshness wiring)
The snapshot self-bootstraps growth-os (sys.path + CWD at the growth-os root, like the gateway), so it
produces **real** board data when run from the repo root with AppFlowy up. Verified live 2026-06-13: 6
boards, 0 errors (mission_intake 12 · todos 8 · dags 87 · papers 68 · repos 55 · signals 56). It runs on a
cadence via a **user-run** schtasks one-liner — agents do **not** self-install schedules (§13). Windows
(mirrors the kanban-bridge task, see [kanban-integration.md](kanban-integration.md)):

```
schtasks /create /tn "CC kanban snapshot" /sc minute /mo 15 /tr "cmd /c cd /d C:\Users\ghadf\vscode_projects\docker_projects\llm_station && .venv\Scripts\python.exe -m command_center.cli.kanban_surface board-snapshot --output generated/board-snapshot.json"
```

Linux/worker cron: `*/15 * * * * cd <repo> && .venv/bin/python -m command_center.cli.kanban_surface board-snapshot --output generated/board-snapshot.json`. The UI shows `generated_at`, so staleness is visible, never silent; a missing snapshot is a loud 503.

### Other honest remaining items (not blockers)
- **SPA is authored, not built here.** It compiles + serves in the Docker `ui` profile (`tsc && vite build`); the look&feel is designed but not visually verified in this session. First `--profile ui` bring-up is the visual check.
- **Mission diffs are raw event payloads** in the drawer (kind=`diff` shown as JSON), not a syntax-highlighted diff view. Adequate for review; a nicer diff renderer is a later polish.
- **AppFlowy-board cards show title+meta only** (no per-card agent status) — only Ledger missions carry an event timeline. By design (AppFlowy cards aren't agent tasks).
- **Drag-to-move was deliberately NOT built** — the UI is read-only; agents move via verbs, humans via AppFlowy/the Ledger. Adding drag would mean a write path (and, for missions, the HMAC secret) in the browser. Out of scope on purpose.

**Overall:** agent-side parity with AppFlowy's databases is **complete**; human-side viewing parity is **complete** (read-only, snapshot-fed); Cline look&feel + agent-use depth is **complete** and now **live-verified**.

### Live bring-up (2026-06-13)
`docker compose --profile ui up -d agent-kanban-ui` against the running stack: image **built** (multi-stage
node→python, SPA compiled clean), container **healthy** on `127.0.0.1:8787`. All endpoints returned real data:
`/api/missions` (2 live Ledger missions), `/api/metrics` (50 calls from the mounted agent-call log),
`/api/boards` (the real snapshot — dags 87, papers 68, repos 55, signals 56, cards 12, todos 8),
`/api/activity` (recent agent calls), and `/` serves the built SPA. Remaining: a human eyeball at the URL to
tune spacing/colors (the only thing code can't self-check).

## 8. Phase 6 — "the best choice": full operator console (ordered)

Goal: from a read-only board to a smooth, mobile, write-capable operator console — filter/click into any item,
see the router/agent-chain, watch the LLM live, assign tasks + pick the model, and chat with the agent from
the app and every channel. Ordered so each lands independently; **the write/chat path is the architecture fork**.

**Architecture decision (the write/chat fork).** The UI gains a **governed** write path by becoming a first-class
*channel*, not by holding the approval secret. Writes go through the **growthos action layer** (move/assign/
`move_item`/stage) — which already refuses Approved structurally and needs no HMAC — and chat goes through the
**same `GatewayCore`** Discord/Slack use. So the UI service grows into "web channel + console": it gains growthos
+ LiteLLM access (creds via env, like the gateway). **L3/L4 approve/kill stay signed and out of the browser** —
the console links out. Board *reads* stay snapshot-based (no creds needed); *writes/chat* use the action layer.

| # | Sub-phase | What | Depth |
|--:|-----------|------|-------|
| 6.1 | **Redesign + filter + mobile** | Left-nav multi-view app (Missions · Boards · Router · Activity · Chat), responsive for phone, board filtering (column/risk/free-text) | frontend |
| 6.2 | **Deep detail** | Click ANY item (mission + AppFlowy card) → rich drawer: all fields, status, where it is; snapshot enriched to carry full card fields | frontend + snapshot |
| 6.3 | **Router / agent-chain** | Per-mission routing chain from Ledger `model_call`/`judge_verdict` events (role→model→verdict→escalation) + a Model-lanes reference from `models.yaml`/`judges.yaml` (configs mounted RO) | read-only |
| 6.4 | **In-app chat + governed writes + model pick** | UI = a channel: embed `GatewayCore` → `/api/chat`; assign/move via the action layer; choose the model alias per turn | **fork — creds in service** |
| 6.5 | **Live LLM streaming** | "what the LLM is doing now, continue live" — stream tokens + tool calls (SSE) from a streaming `GatewayCore` | deep |
| 6.6 | **Multi-channel + SMS + phone** | Agents reachable from every channel incl. **in-app** + new **SMS** adapter (Twilio); phone access = Tailscale + the 6.1 responsive UI | new adapter |

**Standards for Phase 6:** writes are governed (action layer; Approved/L3/L4 never in the browser); no creds in
the *read* path (snapshot stays); router/lanes are **data-derived** from real config + real events (no invented
routing); model list comes from `models.yaml` (no hardcoded model names); fail-loud everywhere; no leakage
(the console shows only what the Ledger/log/snapshot already hold).

### Phase 6 — usability round 4 (inline field editing)
- **Edit any field from the card drawer.** Each field has an inline `edit` (→ `set_item_field`) and there's an
  "+ Note" box (→ `annotate_item`, clobber-safe) — built on the governed verbs a concurrent session added
  (`set_item_field`/`annotate_item`/`remove_item_field_value`, now in the UI's `ACTION_VERBS`). So you can adjust
  Priority/Area/Risk/Due/Tags/etc. on any board at any time. Verified live: `Priority=P3` set, **Status edit
  refused** ("use move_item"), **invalid `P9` rejected** with the data-derived allowed set
  (`['P0','P1','P2','P3']`), note added, reverted. Status/keys are not offered as editable (the move control owns
  Status; protected fields are server-refused regardless).

### Phase 6 — usability round 3 (drag-and-drop)
- **Drag-and-drop on the Boards kanban.** Cards are draggable; columns are drop targets (all legal columns
  render, so you can drop into an empty one); dropping calls the governed `move_item` and the live board
  refreshes. The dropdown in the card details does the same thing — both verified (`Ready -> In Progress` works;
  the earlier "won't let me" was simply the absence of drag, not a backend bug). **The wall holds through drag**:
  dropping onto `Approved` is refused with a clear message (it's human-only), shown as a toast.
- **Live vs snapshot label** on the board (console reads live; read-only uses the worker snapshot).
- **Gated-vs-movable made obvious** — the Missions view is labeled the gated execution lane (open → Ledger to
  approve/kill); the Boards → mission_intake cards are where you move work freely. Verified live: drag→In Progress
  reflected on the live board; Approved drop refused; reverted.

### Phase 6 — usability round 2 (formatting + detail)
- **Stack-health topbar** — new `/api/status` runs REAL liveness probes (Ledger always; LiteLLM + AppFlowy
  when the console is on) and the topbar shows a green/red dot per hop + "updated HH:MM:SS" + a manual refresh
  button. No fabrication — a hop is "ok" only if it answered.
- **Nav counts** — Missions/Boards/Router/Activity show live counts for quick orientation.
- **Persistent chat** — the Chat view stays mounted across view switches, so the conversation no longer resets
  when you click Missions/Boards/etc.
- **Richer mission drawer** — colored event timeline with timestamps, an Approvals section, risk-colored chip,
  and an **"Open in Ledger to approve / kill"** link for L3/L4 / awaiting-approval missions (the signed path
  stays in the Ledger UI; the console links out, never holds the HMAC secret).
- **Keyboard** — Escape closes any open drawer; the card drawer surfaces the current status prominently.

### Phase 6 — fix + polish round (from the visual pass)
Found during the live visual pass and fixed (all live-verified):
- **Governed writes were failing** with `Read-only file system: /logs/agent_calls.jsonl` — the in-app channel
  logs every tool call (like Discord), but the agent-call log was mounted `:ro`. Now `:rw` (it's a channel that
  writes its own calls). Writes verified: `stage_card -> Ready`, `move_item -> Backlog`, HTTP 200.
- **AppFlowy unreachable from the container** (`Connection refused`) — growth-os/.env's `APPFLOWY_BASE_URL=localhost:8081`
  points at the container, not the host. Overridden to `host.docker.internal:8081` (the Ollama pattern; growthos
  Settings: env > .env). Live AppFlowy reads/writes now work from the console.
- **Per-surface logging** — `load_tool_layer(surface)` so each channel's calls are recorded under its own surface;
  in-app calls now show as `app` (verified `03:34 app stage_card`), so the agent chain is observable per surface.
- **Adjust ANY board at any time** — `board_view` carries each board's full legal `statuses`; the card drawer
  has a "Move to…" dropdown (→ `move_item`) for every board, plus quick verb buttons for cards/todos.
- **Row-level Kanban powers are explicit and schema-derived** — the shared action layer now exposes
  `annotate_item` (append dated Notes without clobbering), `set_item_field` (change real schema fields such as
  Section/Area/Priority/Risk/Due/Tags/Pillar/Format/Module/Action/Acceptance/Owners), and
  `remove_item_field_value` (remove one exact value from grouped text fields such as Tags/Topics/Owners/Media).
  Field names/types/select options come from `config/schema.yaml` including project/content templates. The tools
  refuse generated/writeback/key fields and Status stays on `move_item`/lifecycle verbs. AppFlowy view
  layout/group-by/visual formatting is **not claimed** through the row-write REST client; blank field clearing is
  also not claimed until REST clear semantics are verified.
- **See writes immediately** — `/api/boards/live` (console-only; reads AppFlowy live, full statuses) + the card
  drawer refreshes the boards after each action. Read-only deployments still use the worker snapshot.
- **`/api/action` routed through the logged dispatch** (was calling the raw action, bypassing the log).
- **Chat polish** — cleaner tool-call rendering (verb + arg, not raw JSON) + a clear button.

### Phase 6 — Done / left
- [x] **6.1** redesign + filter + mobile — left-nav console (Missions · Boards · Router · Observability · Activity), responsive `@media` for phone, per-view filtering (text + risk). SPA rebuilt + live.
- [x] **6.2** deep detail — `board_view` enriched to carry all scalar card fields; click any item → drawer: missions show status/risk + events, AppFlowy cards show **all fields**. Snapshot regenerated (verified: cards carry CardKey/Section/Risk/Acceptance/Action/…).
- [x] **6.3** router/agent-chain — `/api/models` (configs mounted RO; live: 7 roles, 2 executors, 9 judge stages from `models.yaml`/`judges.yaml`, no hardcoding) + per-mission routing chain (`model_call`/`judge_verdict` events) in the mission drawer. `test_agent_kanban_ui` 12/12.
- [x] **6.4** in-app chat + governed writes + model pick — the UI is now a **channel**: `/api/chat` embeds `GatewayCore`; `/api/action` drives the governed verbs (Approved refused; L3/L4 stay signed); model picked per turn (validated vs models.yaml). Gated by `KANBAN_UI_CHAT_ENABLED` (off ⇒ creds-free read-only). **Live-verified**: agent answered "1 mission awaiting approval" correctly from the injected board; `approve_card` → 400. `test_agent_kanban_ui` 19/19.
- [x] **6.5** live streaming — `GatewayCore.run_turn_events` async-generator + `/api/chat/stream` (SSE) + a streaming chat log (round/tool/tool_result/final). **Live-verified**: events stream as they happen.
- [x] **6.6** SMS adapter — `channels/sms.py` (Twilio webhook → `GatewayCore` → REST reply), `transport: sms` in `ChannelSpec` (runner auto-dispatches), disabled `sms-main` in `channels.yaml`. Authored + registered + `make validate` green (needs Twilio creds + a public webhook to run, like WhatsApp). **Phone access**: the responsive UI over Tailscale (done in 6.1).

## 9. Phase 7 — typed domain cockpit surfaces

Goal: move beyond generic kanban cards so each operating domain has a visual
grammar that matches the work: jobs look like applications, posts look like
LinkedIn previews, books show bibliographic details and ordered notes, papers show research context,
repos/DAGs show health, and upkeep/tasks stay compact.

- [x] **7.1** domain registry — `configs/domain_surfaces.yaml` defines nine
  domains (`job_application`, `linkedin_post`, `book`, `paper`, `repo`, `dag`,
  `machine_upkeep`, `mission`, `generic_task`), their card components, source
  bindings, drawer fields, allowed governed verbs, and designed empty states.
- [x] **7.2** backend API — `services/agent_kanban_ui/app.py` serves
  `/api/domains`, `/api/domain/{id}/cards`, `/api/domain/{id}/card/{card_id}`,
  and `/api/domain/{id}/actions`. Origins are explicit: `board_store`,
  `ledger`, or `fixtures`; fixture data cannot masquerade as live data.
- [x] **7.3** Jobs on the internal board — `job_search_pipeline_internal`
  is a `command_center_ui` board in `configs/kanban_boards.yaml`; the Jobs
  domain reads the same provider/event-fold that the job-search internal
  backend writes.
- [x] **7.3a** Posts on an internal board —
  `linkedin_content_pipeline_internal` is a `command_center_ui` draft/review
  board. The Posts view has a LinkedIn-style entry composer with configured
  accounts, live desktop/mobile preview, canonical length/lint checks, and a
  governed Draft event; publishing remains outside this surface.
- [x] **7.4** typed SPA view — the React app has a top-level `Domains` view
  with domain switching, per-domain filters, status filtering, typed cards,
  detail drawer, LinkedIn desktop/mobile preview toggle and post entry, honest demo badges,
  designed empty states, and read-only disabled governed verbs unless
  `KANBAN_UI_CHAT_ENABLED=1`.
- [x] **7.5** validation — `tests/test_domain_surfaces.py`,
  `tests/test_agent_kanban_ui.py`, `tests/test_kanban_ui_events.py`,
  TypeScript `--noEmit`, `npm run build`, and live FastAPI endpoint curls
  validated the domain registry, card payloads, and built SPA serving.

Plan of record: `C:\Users\ghadf\.claude\plans\dapper-crunching-sketch.md`.

## 10. Phase 8 — PWA / mobile polish

- [x] **PWA shell** — Vite public assets now include
  `manifest.webmanifest`, SVG app icons, and a service worker. The service
  worker caches the static app shell/assets only and explicitly bypasses
  `/api/*` plus non-GET requests.
- [x] **Phone layout** — mobile width uses a fixed bottom nav, full-screen
  drawers, larger touch targets, horizontal board snapping, and hidden
  secondary/sidebar domain nav to keep the primary actions reachable.
- [x] **Tap move path** — generic boards and typed domain cards expose
  `Move to...` controls for touch devices while desktop drag/drop remains.
  Moves still go through the existing governed endpoints.
- [x] **Docs/tests** — quickstart documents install-to-home-screen over
  Tailscale; `test_agent_kanban_ui.py` asserts the static-only caching policy.
