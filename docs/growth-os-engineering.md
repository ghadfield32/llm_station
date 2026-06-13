# Growth OS — engineering reference (living doc)

Keep this current: it is the map a new session reads first. Update it when
behavior, interfaces, or module structure actually change — not for cosmetics.
Last full revision: 2026-06-12.

## Module tree (what runs, where, when)

```
appflowy_kanban/growth-os/
├─ growthos/
│  ├─ config.py        contracts: Settings(.env) · Config(sources.yaml) ·
│  │                   ProjectsConfig(projects.yaml) — pydantic, fail-fast
│  ├─ appflowy.py      the ONE AppFlowy client: GoTrue login, pre_hash
│  │                   upserts (idempotent), row reads; field-id wire format
│  ├─ actions.py       the ONE tool layer (20 tools) shared by assistant /
│  │                   MCP / Discord; approval structurally refused here;
│  │                   every list tool validates its enums LOUDLY (anti-loop)
│  ├─ curate.py        hourly: arxiv+github+rss → score → dedupe → enrich
│  │                   → upsert
│  ├─ score.py         embedding scorer (Ollama) w/ keyword fallback
│  ├─ enrich.py        curate stage 3.5: <=35-word "useful for <project>"
│  │                   annotation per NEWLY kept item -> Suggested column
│  ├─ airflow_sync.py  hourly: LIVE dag run state + failure summaries → board
│  ├─ packages.py      host/daily: lockfiles vs PyPI → packages board
│  ├─ guidelines.py    daily: standards.yaml mirror + release feeds
│  ├─ retention.py     daily: Inbox rows older than retention.days → Archived
│  ├─ brief.py         daily: morning brief + LLM overview + mission worklog
│  └─ assistant.py     chat.bat brain: Ollama tool-calling loop w/
│                      repeat-call breaker + forced final answer
├─ agent/growthos_mcp.py   MCP registration over actions (Claude)
├─ scripts/
│  ├─ setup_workspace.py   create/RECONCILE databases from schema.yaml
│  │                       (missing fields added in place on live boards)
│  ├─ create_views.py      Board/Calendar views (idempotent)
│  ├─ import_books.py      data/book-checklist.md → library (Section number
│  │                       from module prefix; never clobbers Status/Notes)
│  ├─ import_dags.py       dag files → dags board (static inventory)
│  ├─ new_project.py       stamp per-project board + kanban.yaml section
│  ├─ seed_workspace.py    sources mirror + starter todos
│  └─ selftest.py          22 live checks across the whole system; run
│                          after any structural change; goal is 100%
├─ config/
│  ├─ schema.yaml          database shapes (first select = board grouping)
│  ├─ sources.yaml         feeds, interest weights, scoring, retention
│  ├─ projects.yaml        ★ repo registry: what the watchers observe
│  └─ databases.json       generated id map (never hand-edit)
└─ docker-compose.curator.yml  the always-on loop (see cadence below)

llm_station/
├─ scripts/kanban_bridge.py  Approved cards → Ledger missions (+writeback)
├─ src/command_center/channels/  Discord/Slack/Telegram/WhatsApp ↔ LiteLLM ↔ actions
└─ configs/kanban.yaml       dispatch contract (sections, risk ceilings)
```

**Cadence:** hourly = curate(+enrich) + airflow_sync · daily after 06:00 =
brief, guidelines, retention · q15min (host task) = bridge · on demand/host =
packages, import_books/dags, selftest.

## The two registries (do not merge them)

| File | Owns | Consumed by |
|---|---|---|
| `growth-os/config/projects.yaml` | what we **observe**: repos for package watch, dags dirs, airflow endpoints | packages, import_dags, airflow_sync |
| `configs/kanban.yaml` | what work **dispatches**: sections, risk ceilings, ready statuses | kanban_bridge (KanbanConfig-validated) |

**Adding a repo (the standard, ~3 minutes):**
1. Block in `projects.yaml` (repo path; optional `dags_dir`, `airflow:`).
2. If it should receive mission cards: `scripts/new_project.py --name X
   --repo X --risk L2` (board + validated kanban.yaml section), and add the
   section label to mission_intake's Section options.
3. Secrets the watcher needs go in `growth-os/.env` under the env names the
   registry block declares. Run the relevant watcher once to verify.

## DAG failure → root cause (airflow_sync stages)

registry → `/dags` (paginated) → latest run per DAG → on `failed`: failed
taskInstances → log text → `extract_error()`: exception line + **deepest
non-site-packages frame** (the pointer lands in code you can edit) → board
row: `Status=Broken`, `Notes = FAILED <when>: <exc> | <file:line in fn> |
task=<id> try=<n> | logs: <direct UI url>` → newly-Broken DAGs get a Backlog
card drafted (dispatch still requires the human drag). Human-set `Retired`
rows are never touched. Everything deterministic — no LLM in the loop.

## Execution visibility (how "check on status" works)

Executors post events to the Ledger (`POST /mission/{id}/event`) as they
work; `actions.mission_status(mission_id)` returns status + the last 5 event
summaries — ask from Discord/chat/Claude: *"status of T-b5f2e70f?"*. The
morning brief's **Mission worklog** lists every bridged mission with its
current Ledger state. Cards created by agents also get MissionID/Status
stamped back onto the board (CardKey writeback).

## Standards checklist (enforced shape of every module here)

- module-tree + stage docstring at the top; stages independently callable
- contracts validated at the boundary (pydantic / explicit checks); bad
  input returns a LOUD error the calling agent can self-correct on — the
  silent-empty-list bug (list_todos "open") is the canonical counterexample
- no hardcoded thresholds: policy knobs live in config (retention.days,
  scoring weights, lookbacks); derived values computed (semver severity)
- no silent fallbacks: degraded modes log warnings (embedding→keyword) or
  surface errors to the caller (LiteLLM/Airflow failures reply in-channel)
- idempotent writes only (pre_hash upserts); human triage never clobbered
- new deps: `uv add` (pyproject + lock + sync) at llm_station; pinned range
  in growth-os/requirements.txt for the container
- approval is human-only — in code (actions refuses), in config (bridge
  applies Approved only), at the Ledger (L3/L4 hold)

## Cross-session rules (multiple Claude/Codex sessions in this repo)

- `configs/*` changes must pass `KanbanConfig`/validate before write
- growth-os watchers and command-center services touch disjoint files; the
  bridge + this doc are the shared seams — update this doc when you move them
- `config/databases.json` is generated state: reconcile via
  setup_workspace.py, never hand-edit
- one logical change per session-turn on shared seams; check `git status`
  for the other session's in-flight edits before structural moves

## Context enrichment (added 2026-06-12, late)

- **DAG rows carry full context every sync**: Description, Owners, Tags,
  NextRun straight from the Airflow API (airflow_sync stage 5), alongside
  the run-state Notes. The board is now a self-describing inventory.
- **`Suggested` column on papers/repos/signals** (`growthos/enrich.py`,
  curate stage 3.5): one <=35-word "useful for <project>: <how>" line per
  NEWLY kept item, grounded in the projects registry, local model only.
  Honest by construction — items that fit neither project say so. Ollama
  down -> loud warning, items land unenriched; curation never blocks.
- **`book_note(title, note)`** appends dated reading notes to library rows
  from any channel.
- **In-app AppFlowy AI — VERDICT: blocked upstream.** Wiring to LiteLLM was
  verified correct (key, base URL, model seeding), but the `appflowy_ai`
  image license-walls every request ("commercial license... not yet
  available"). Container stopped; verdict documented in
  `AppFlowy-Cloud/docker-compose.override.yml`. The guidelines feed watches
  AppFlowy releases for when this changes. In-app AI's jobs are covered by
  the three live channels meanwhile.

## Agent loop hardening (added after the Discord tool-round stall)

Two defenses, both required, both channels (gateway + assistant):
1. **Boundary validation on every list tool** — an invalid enum returns a
   loud `invalid X; allowed: [...]` string the model self-corrects on. A
   silently-empty list is indistinguishable from "no data" and causes
   retry loops (the original `list_todos(status="open")` pathology).
2. **Deterministic loop-breakers in the chat loop** — an identical repeated
   tool call gets a "you already have this result, answer now" tool message;
   when the round budget exhausts, one final no-tools completion forces a
   text answer that states what couldn't be determined. The stub string
   "(stopped: too many tool rounds)" must never reach a human again.

`project_status(project)` is the one-call context pack (DAG counts + broken
summaries + pending package bumps + open cards/todos) an agent loads before
repo work; `network_health()` is the 5-hop liveness check (appflowy, ollama,
litellm, ledger, airflow) — both selftest-covered.

## Done / next (keep ordered)

Done: knowledge watchers (papers/repos/signals/guidelines/packages) ·
retention (7d) · 275-book library w/ Section sort key + clobber guard ·
live loop proven (T-b5f2e70f dispatched + writeback; T-c8e1d7d6 held at the
L4 wall) · bridge scheduled q15min · Discord live w/ loop hardening ·
projects.yaml registry · airflow_sync live (81 dags, root-cause summaries,
auto-drafted fix cards) · betts_basketball_board · project_status /
network_health / dag_health / mission_status / book_note tools ·
in-app AI verdict (upstream license wall) · **selftest.py 22/22 (100%)**.

Next, in order:
1. Executor-side: ensure Claude Code/Codex mission runs post progress events
   (the contract mission_status reads) — command-center session's lane.
2. GitHub PAT + nightly backup scheduling (open on the todos board).
3. "Discord gateway" onlogon task (one schtasks command, user-run) so the
   bot survives reboots — everything else already does.
4. One-time UI clicks that REST cannot do: per-view filters ("Title is not
   empty") and sorts (library by Section), delete blank starter rows.
5. Linux migration when the prod box revives (deploy/linux/MIGRATION.md).
