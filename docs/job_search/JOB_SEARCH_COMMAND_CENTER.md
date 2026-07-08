# Job Search Command Center

The job-search workflow is prepare/manual-first. It ranks local or discovered
jobs, selects traceable resume evidence, drafts materials, creates application
memory, and generates follow-up packs. It does not submit applications in the
MVP.

Run the safe local path:

```powershell
uv run cc job-search ingest-profile
uv run cc job-search suggest --from-file docs/job_search/examples/sportsbook_analytics_engineer.md --write
uv run cc job-search generate-materials <job_key> --selected-by-geoff
uv run cc job-search mark-submitted <application_id>
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

`process-selected` only processes cards in `Selected by Geoff`. It moves them
through `In Progress`, generates materials with the existing claim validation
path, and routes them to `Needs Geoff` in the MVP. `Completed` still requires
`uv run cc job-search mark-submitted <application_id>`.

The AppFlowy schema for `job_search_pipeline` is registered in
`appflowy_kanban/growth-os/config/schema.yaml`, and the board is registered in
`configs/kanban_boards.yaml`.

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
rtk git diff --check
uv --cache-dir data/job_search/uv-cache run cc kanban-verify --board-id job_search_pipeline
```

## Executor Fallback

Material generation accepts `--executor auto|claude|codex`. The MVP generation
path is deterministic and uses the same structured inputs either way; the flag
records intent and proves Codex can run the same workflow if Claude Code is not
available.

```powershell
uv run cc job-search generate-materials <job_key> --selected-by-geoff --executor codex
```
