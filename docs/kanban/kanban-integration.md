# Kanban Integration — AppFlowy quirks, commands, one-time setup

AppFlowy/GrowthOS and Command Center are joined by a bridge, not merged into
one authority boundary. For the full card → mission pipeline (roles, stages,
gates, writeback), see [MASTER.md §6.3](../MASTER.md#63-the-kanban-intake-pipeline-cards--missions).
For the current event-driven sync design (the default path since 2026-06-20),
see [LIVE_KANBAN_SYNC.md](LIVE_KANBAN_SYNC.md). This file covers what's
specific to AppFlowy itself: its REST-API quirks, the commands, and one-time
board setup.

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

**Scheduling (run yourself — agent-created persistence is deliberately
blocked):**

```powershell
schtasks /create /tn "CC kanban bridge" /sc minute /mo 15 /tr "cmd /c cd /d C:\Users\ghadf\vscode_projects\docker_projects\llm_station && .venv\Scripts\python.exe -m command_center.cli.kanban_bridge --apply"
```

## Ollama sharing

Use one model gateway:

```text
AppFlowy/GrowthOS optional LLM calls -> LiteLLM -> Ollama
Command Center judges/planners       -> LiteLLM -> Ollama
Claude Code/Codex executors          -> their own subscription/OAuth lanes
```

For GrowthOS, keep direct scraping/curation deterministic where possible. If
you add LLM summarization, point it to the same OpenAI-compatible LiteLLM
endpoint:

```dotenv
OPENAI_BASE_URL=http://host.docker.internal:4000/v1
OPENAI_API_KEY=<local LiteLLM virtual key>
```

Do not add OpenAI/Anthropic/OpenRouter provider keys.

## One-time board setup

Rerun the GrowthOS workspace setup from `appflowy_kanban/growth-os` so
AppFlowy creates or reconciles the `mission_intake` database, then create the
board and calendar views:

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

## AppFlowy REST quirks

**Blank starter rows.** The top three blank rows are created by AppFlowy
itself for every REST-created grid. In `AppFlowy-Cloud/src/biz/workspace/page_view.rs`,
`prepare_default_grid_encoded_database` creates `Type`, `Done`, and
`rows = (0..3)`. They are not import failures and not duplicates from the
curator.

**Unusable `Type` dropdown.** AppFlowy's default `Type` select column has zero
options, so it opens a chooser with nothing to choose. Our real select columns
(`Status`, `Section`, `Priority`, `Risk`, etc.) are created with fixed options
and are validated by `appflowy-audit`.

**REST API limits.** Current AppFlowy Cloud REST exposes endpoints to list,
insert, and upsert rows, and to add fields. It does not expose row delete,
field hide/delete/update, or view filter/sort settings. Delete the blank rows
and hide/remove `Type` and `Done` from the desktop/web UI when you want a
clean visual grid. All agent code and the Kanban bridge skip rows whose
primary `Name` cell is empty, and the board views hide ungrouped starter rows
when grouped by a real status field.
