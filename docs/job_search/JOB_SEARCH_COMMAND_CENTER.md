# Job Search Command Center

The job-search workflow is prepare/manual-first. It ranks local or discovered
jobs, selects traceable resume evidence, drafts materials, creates application
memory, and generates follow-up packs. It does not submit applications in the
MVP.

Primary cockpit path: `job_search_pipeline_internal` in the first-party
`agent_kanban_ui` Domains view. AppFlowy `job_search_pipeline` remains a
useful external/mobile projection, but it is not required for the local
validation loop.

Run the safe local path:

```powershell
uv run cc job-search ingest-profile
uv run cc job-search suggest --from-file docs/job_search/examples/sportsbook_analytics_engineer.md --write
uv run cc job-search generate-materials <job_key> --selected-by-geoff
# after real submission: drag the cockpit job card to Completed
uv run cc job-search followup <application_id>
uv run cc job-search retention --dry-run
```

Validate the fixture postings:

```powershell
uv run cc job-search validate-examples
```

`data/job_search/` is gitignored and local-only. It can contain personal resume
source files, generated materials, job descriptions, salary notes, recruiter
communications, and interview notes.

## Safety Boundary

- No mass apply.
- No MVP submit path.
- No login, MFA, captcha, or bot-check bypass.
- No legal, EEO, self-ID, disability, veteran, sponsorship, work authorization,
  salary expectation, relocation, background-check, non-compete, clearance, or
  start-date answers without Geoff.
- No recruiter, hiring-manager, LinkedIn, or email messages without Geoff review.
- No resume claim without an achievement ID and evidence file.

## Board Columns

```text
Suggested Jobs -> Selected by Geoff -> In Progress -> Needs Geoff -> Completed
-> Interviewing -> Rejected / Skip -> Closed / Archived
```

The board commands are under the same safe namespace:

```powershell
uv run cc job-search board-setup --dry-run
uv run cc job-search board-doctor
uv run cc job-search board-snapshot
uv run cc job-search publish-suggestions --dry-run
uv run cc job-search process-selected --dry-run
```

Preferred local cockpit path:

```powershell
uv run cc job-search board-setup --apply --backend internal
uv run cc job-search publish-suggestions --apply --backend internal
uv run cc job-search board-snapshot --backend internal
uv run cc job-search process-selected --apply --backend internal
```

Daily discovery targets 50 surfaced jobs: up to 25 `bot_possible` jobs and up
to 25 `manual_required` jobs, with score-ranked filler only when one queue has
too few eligible jobs. This is a queue-balancing target, not a submit promise:
`bot_possible` means no configured blocker was detected, while the MVP still
prepares materials and waits for Geoff to review/submit.

Useful live discovery commands:

```powershell
uv run cc job-search discover-live --source jobicy --tag python --tag sql --tag analytics --tag machine-learning --industry data-science --industry engineering --industry dev --industry management --industry accounting-finance --industry marketing --industry business --count 100 --write
uv run cc job-search discover-live --source jobicy --tag dbt --tag snowflake --tag airflow --tag experimentation --count 100 --write
uv run cc job-search discover-live --source remotive --tag data --tag analytics --tag "machine learning" --tag "ai engineer" --tag "data engineer" --tag python --tag sql --tag dbt --tag snowflake --tag airflow --count 100 --write
uv run cc job-search publish-suggestions --apply --backend internal
```

The daily Airflow DAG uses the same broader Jobicy/Remotive/RemoteOK discovery,
publishes the balanced board, and runs `process-selected` only for cards Geoff
has already moved to `Selected by Geoff` or unprepared `In Progress`.

The first-party cockpit reads this same internal board store through
`configs/domain_surfaces.yaml -> job_application`. The SPA has a top-level
`Sections` view plus sidebar shortcuts for Jobs, Posts, Books, Papers, Repos,
DAGs, Upkeep, and Tasks. Jobs render as lane-backed job cards across all 8
pipeline stages, Posts render as LinkedIn-style previews, and other domain
types use their own card grammar. Fixture-backed domains always show a
`demo data` badge; the Jobs domain reports `board_store`.

Dragging a Jobs card between pipeline lanes is available only in the write-enabled
cockpit (`KANBAN_UI_CHAT_ENABLED=1`). The drop emits a governed kanban event
against `job_search_pipeline_internal`; it does not write status into the card
JSON and still cannot set approval/merge/deploy/delete states. The Jobs header
also exposes a `Job presets` drawer that reads
`data/job_search/profile/application_question_policy.yml` plus the configured
resume variants/categories so application-question defaults are visible before
Geoff starts an application.

Desktop flow: open `Sections -> Jobs`, use the queue chips or `any automation`
filter to switch between `Bot Possible`, `Manual Required`, and `Prepare Only`,
then drag cards between lanes. Mobile flow: open the same Jobs board and use the
card's `Move to...` menu instead of dragging. After a real manual submission,
drag the prepared card to `Completed`; no `application_id` command is needed.

Opening a Jobs card shows a compact progress checklist, the governed kanban
events recorded for that card, and an `open in chat` handoff. The chat handoff
prefills the existing cockpit chat with the card, current lane, and next action;
it uses the configured GatewayCore/LiteLLM runtime rather than Orca or Omnigent.

### Required one-time step: Group by Status

AppFlowy's self-hosted REST API cannot set a board view's group field, edit
select options, delete/reorder fields, or delete rows. A REST-created board
therefore opens grouped by AppFlowy's default empty `Type` field, showing one
`No Type` column with nothing to drag. The database is correct - `Status`
carries all 8 stages and cards are tagged - only the board *view* needs
pointing at it. In the AppFlowy client: open the **Board** tab -> view
settings (`...`) -> **Group by** -> **Status**. All 8 columns appear.
`board-doctor` verifies the database and reprints these steps. Full detail
(plus optional cleanup of the blank starter rows and `Type`/`Done` default
fields) is in `docs/job_search/READINESS_FAQ.md`.

Default board mode targets real AppFlowy and fails closed if the
`job_search_pipeline` database mapping or credentials are missing. For local
validation without touching AppFlowy, use the explicit local backend:

```powershell
uv run cc job-search board-setup --apply --backend local
uv run cc job-search publish-suggestions --apply --backend local
uv run cc job-search board-snapshot --backend local
```

Use `--backend internal` for the cockpit-native board. Use `--backend local`
only for the older JSON-file harness tests.

`process-selected` processes cards in `Selected by Geoff`. It also catches
cards already dragged to `In Progress` when they do not yet have an
`application_id` or `materials_path`, because that drag is a human selection
signal in the cockpit. It moves them through material generation with the
existing claim validation path, then routes them to `Needs Geoff` in the MVP.
Already prepared cards are ignored on rerun, so it is safe to run the command
again. `Completed` is now the no-ID cockpit action: after Geoff confirms a real
submission, drag the card to `Completed` and the application record/follow-up
memory are updated from the card's `application_id`.

The AppFlowy schema for `job_search_pipeline` is registered in
`appflowy_kanban/growth-os/config/schema.yaml`, and the board is registered in
`configs/kanban_boards.yaml`.

## Search Filters (Location + Language), Feedback, and Background Prep

Three operator-facing controls layer on top of the pipeline above. All three
are editable in the cockpit `Job presets` drawer and via the CLI; the filters
also live in `configs/job_search.yaml` (`locations`, `languages`) and can be
overridden per-operator in `data/job_search/profile/search_settings.yml`.

### Location + language filter (hybrid enforcement)

`locations` gates jobs by geography and work arrangement; `languages` gates by
required language. Enforcement is **hybrid**:

- A **clear mismatch** is hard-excluded from Suggested Jobs (score forced below
  the show bar, fit action `SKIP`): an onsite/hybrid role in a US state that is
  not on your list, a foreign onsite role, an excluded work arrangement, or a
  posting that *requires* a language you do not speak.
- An **ambiguous** posting stays visible but ranked lower (soft penalty): an
  unknown or national-only location, a merely *preferred* language, or a noisy
  employment-type signal (e.g. "contract" when you filter for full-time).
- Remote roles pass the geography check whenever `locations.remote_ok` is true.

`locations.mode` is `worldwide | countries | regions`. `remote_types_allowed`
is the remote/hybrid/onsite allowlist; `employment_types_allowed` (e.g.
`[full_time]`) is a soft-only signal. Edit from the drawer's states/DC checklist
plus the remote/hybrid/onsite + full-time toggles, or:

```powershell
# PUT /api/job-search/profile-controls/locations  and  .../languages
```

Scoring lives in `src/command_center/job_search/geo_language.py`; the score
breakdown on each card names the exact filter effect.

### Rejection feedback loop

Moving a Jobs card to `Rejected / Skip` prompts for a reason (the cockpit picker
mirrors `rejections.REASON_CODES`); it is recorded to
`data/job_search/rejections/rejections.jsonl`. The report aggregates reasons and
proposes concrete changes, distinguishing a *filter gap* (a job the filter
should have caught) from a filter that is already working:

```powershell
uv run cc job-search reject <job_key> --reason location --note "too far"
uv run cc job-search rejections-report
# GET /api/job-search/rejections-report ; cockpit: Job Search -> Rejections & weaknesses
```

### Background packet prep (fast selection)

Moving a card to `Selected by Geoff` (or the `Add all` bulk button) no longer
blocks on packet generation. The move returns immediately and queues prep on a
single background worker, so you can move through many cards fast; each card
shows `preparing packet…` until the worker advances it to `Needs Geoff`. Queue
health (including a failed run) is at `GET /api/job-search/prep-status`. The
Geoff-selection wall is unchanged: prep still runs only for cards Geoff selected,
and nothing is submitted automatically.

## Validation Commands

Use a short pytest temp path on Windows to avoid path-length and sandbox temp
directory issues:

```powershell
New-Item -ItemType Directory -Force data\job_search\tmp_env | Out-Null
$env:TMP = (Resolve-Path data\job_search\tmp_env).Path
$env:TEMP = $env:TMP

uv --cache-dir data/job_search/uv-cache run cc validate
uv --cache-dir data/job_search/uv-cache run pytest tests/job_search -q --basetemp data/job_search/pt2
uv --cache-dir data/job_search/uv-cache run ruff check src/command_center/job_search tests/job_search dags/job_search_daily.py
uv --cache-dir data/job_search/uv-cache run pytest tests/test_domain_surfaces.py tests/test_agent_kanban_ui.py tests/test_kanban_ui_events.py -q --basetemp data/job_search/pt-ui
uv --cache-dir data/job_search/uv-cache run ruff check services/agent_kanban_ui/app.py tests/test_domain_surfaces.py
rtk git diff --check
uv --cache-dir data/job_search/uv-cache run cc kanban-verify --board-id job_search_pipeline
```

Frontend/cockpit validation:

```powershell
cd services/agent_kanban_ui/web
npm install
.\node_modules\.bin\tsc.cmd --noEmit
npm run build
cd ..\..\..

$env:KANBAN_UI_CONFIGS='configs'
$env:LEDGER_BASE_URL='http://127.0.0.1:8091'
$env:KANBAN_EVENT_LOG='generated/kanban-events.jsonl'
$env:KANBAN_BOARD_STORE='generated/boards'
$env:KANBAN_BOARD_SNAPSHOT='generated/board-snapshot.json'
$env:KANBAN_UI_STATIC='services/agent_kanban_ui/web/dist'
uv --cache-dir data/job_search/uv-cache run uvicorn app:app --app-dir services/agent_kanban_ui --port 8789
```

If `/api/missions` reports `getaddrinfo failed`, the local server was started
with Docker's service URL (`http://ledger:8090`) instead of the host URL above.
Open the cockpit's Diagnostics view or call `/api/debug/runtime` to see the
exact URL/path probes the server is using.

## Executor Fallback

Material generation accepts `--executor auto|claude|codex`. The MVP generation
path is deterministic and uses the same structured inputs either way; the flag
records intent and proves Codex can run the same workflow if Claude Code is not
available.

```powershell
uv run cc job-search generate-materials <job_key> --selected-by-geoff --executor codex
```
