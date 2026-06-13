# Kanban Integration

AppFlowy/GrowthOS and Command Center should be joined by a bridge, not merged into
one authority boundary.

## Current Roles

| Layer | Job | Write Authority |
| --- | --- | --- |
| AppFlowy / GrowthOS | Human Kanban, learning notes, papers/repos/signals, review queue | AppFlowy rows only |
| LiteLLM / Ollama | Local model gateway for both systems | model calls only |
| Ledger | Mission state, approvals, leases, audit trail | mission records |
| Judge Gate | Review plans/diffs against standards | verdicts only |
| Claude Code / Codex | Repo execution in leased worktrees | local repo edits after gates |

The Kanban board should never edit repos, push branches, approve itself, or bypass
the Ledger. A card becomes work only after the bridge opens a Ledger mission.

## AppFlowy Sections

`appflowy_kanban/growth-os/config/schema.yaml` now includes `mission_intake` with
these intended sections:

| Section | Target | Typical Risk | Meaning |
| --- | --- | --- | --- |
| `DAGs` | `odds_ingest_daily` / Airflow work | L2 | pipeline checks, freshness fixes, data QA follow-up |
| `Learning` | GrowthOS learning/research | L1 | syntheses, study plans, notes, lesson capture |
| `Betts Basketball` | `betts_basketball` repo | L2 | tests, small fixes, DAG/code improvements |
| `Command Center` | future control-plane cards | L1/L2 | setup improvements, docs, local tooling |

Cards move through:

```text
Backlog -> Ready (staging) -> Approved -> Ledger mission -> In Progress -> Done/Rejected
```

The bridge applies **Approved cards only** (`ready_statuses: [Approved]` in
configs/kanban.yaml) — `Ready` is human staging and never dispatches. Imported
card hashes land in `generated/kanban-imported.json` so repeated runs do not
reopen the same card.

**Writeback:** cards created through the agent action layer
(`growthos/actions.py::add_mission_card`) carry a `CardKey`; on apply the
bridge stamps `MissionID`, `Status=In Progress`, and `LastSync` back onto the
card. UI-created cards have no CardKey (AppFlowy's REST can only address rows
by pre_hash), so they are deduped by the imported-state file and visible via
the brief's **Mission worklog** section instead, which lists every bridged
mission with its current Ledger status each morning.

The mission board intentionally mirrors the useful parts of the `todos` board:
`Title`, `Status`, `Section`, `Priority`, `Risk`, `Due`, `Action`,
`Acceptance`, `Notes`, `Repo`, `Branch`, `MissionID`, `CardKey`, `LastSync`,
and `Created`. The board view groups by `Status`; the calendar view uses `Due`.

**Scheduling (run yourself — agent-created persistence is deliberately
blocked):**

```powershell
schtasks /create /tn "CC kanban bridge" /sc minute /mo 15 /tr "cmd /c cd /d C:\Users\ghadf\vscode_projects\docker_projects\llm_station && .venv\Scripts\python.exe scripts\kanban_bridge.py --apply"
```

## Commands

Validate the contract:

```powershell
.\scripts\cc.ps1 kanban-validate
```

Preview mission drafts without writing:

```powershell
.\scripts\cc.ps1 kanban-bridge
```

Open Ledger missions:

```powershell
.\scripts\cc.ps1 kanban-bridge -Apply
```

Audit AppFlowy formatting and starter rows:

```powershell
.\scripts\cc.ps1 appflowy-audit
.\scripts\cc.ps1 appflowy-audit -Details
```

Make equivalents:

```bash
make kanban-validate
make kanban-bridge
make kanban-bridge APPLY=1
```

## Ollama Sharing

Use one model gateway:

```text
AppFlowy/GrowthOS optional LLM calls -> LiteLLM -> Ollama
Command Center judges/planners       -> LiteLLM -> Ollama
Claude Code/Codex executors          -> their own subscription/OAuth lanes
```

For GrowthOS, keep direct scraping/curation deterministic where possible. If you add
LLM summarization, point it to the same OpenAI-compatible LiteLLM endpoint:

```dotenv
OPENAI_BASE_URL=http://host.docker.internal:4000/v1
OPENAI_API_KEY=<local LiteLLM virtual key>
```

Do not add OpenAI/Anthropic/OpenRouter provider keys.

## Safety Rules

- Kanban cards are requests, not commands.
- `Learning` defaults to L1 and should not produce repo edits.
- `DAGs` and `Betts Basketball` default to L2 local edits.
- L3/L4 work still requires Ledger approval.
- Repo execution still needs one branch, one worktree, one devcontainer, one lease.
- GitHub push/PR remains behind the existing GitHub wall.

## Next Practical Step

Rerun the GrowthOS workspace setup from `appflowy_kanban/growth-os` so AppFlowy
creates or reconciles the `mission_intake` database, then create the board and
calendar views:

```powershell
Set-Location appflowy_kanban\growth-os
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe scripts\setup_workspace.py
.\.venv\Scripts\python.exe scripts\create_views.py
```

Then create a test card:

```text
Title: Add freshness check for odds ingest
Section: DAGs
Target: odds_ingest_daily
Status: Ready
Risk: L2
Action: Add or verify a freshness check for the odds ingest output.
Acceptance: A failing stale partition is detected before downstream modeling.
Repo: betts_basketball
```

Back at the Command Center root, run:

```powershell
.\scripts\cc.ps1 kanban-bridge
```

## Blank Starter Rows

The top three blank rows are created by AppFlowy itself for every REST-created
grid. In `AppFlowy-Cloud/src/biz/workspace/page_view.rs`,
`prepare_default_grid_encoded_database` creates `Type`, `Done`, and
`rows = (0..3)`. They are not import failures and not duplicates from the
curator.

The unusable blank dropdown is AppFlowy's default `Type` select column. It has
zero options, so it opens a chooser with nothing to choose. Our real select
columns (`Status`, `Section`, `Priority`, `Risk`, etc.) are created with fixed
options and are validated by `appflowy-audit`.

Current AppFlowy Cloud REST exposes endpoints to list, insert, and upsert rows,
and to add fields. It does not expose row delete, field hide/delete/update, or
view filter/sort settings. Delete the blank rows and hide/remove `Type` and
`Done` from the desktop/web UI when you want a clean visual grid. All agent code
and the Kanban bridge skip rows whose primary `Name` cell is empty, and the
board views hide ungrouped starter rows when grouped by a real status field.
