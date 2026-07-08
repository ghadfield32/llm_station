# Job Search Implementation Prompt

Implement and maintain the Job Search Command Center inside `llm_station`.

Use the prepare/manual-first MVP:

```text
Daily DAG finds/ranks jobs
-> Geoff reviews Suggested Jobs
-> Geoff selects jobs
-> system prepares materials and routes blockers
-> Geoff submits manually or confirms submission
-> active applications keep 30-day rich memory
-> follow-up packs refresh from notes and recruiter activity
```

Hard rules:

- Do not mass apply.
- Do not submit applications in the MVP.
- Do not bypass login, MFA, captcha, bot checks, or session challenges.
- Do not answer EEO, voluntary self-ID, disability, veteran status, legal,
  work authorization, sponsorship, salary, relocation, clearance, background
  check, non-compete, or start-date questions without Geoff.
- Do not send recruiter, hiring-manager, LinkedIn, or email messages without
  Geoff approval.
- Do not invent resume claims, metrics, dates, titles, tools, or experience.
- Every resume bullet must trace to `achievement_bank.yml` and evidence files.
- Keep `data/job_search/` local-only and gitignored.

Required validation before finishing changes:

```powershell
uv --cache-dir data/job_search/uv-cache run cc validate
uv --cache-dir data/job_search/uv-cache run pytest tests/job_search -q --basetemp data/job_search/pt2
uv --cache-dir data/job_search/uv-cache run ruff check src/command_center/job_search tests/job_search dags/job_search_daily.py
uv --cache-dir data/job_search/uv-cache run cc kanban-verify --board-id job_search_pipeline
git diff --check
```

Board workflow validation:

```powershell
uv --cache-dir data/job_search/uv-cache run cc job-search board-setup --dry-run
uv --cache-dir data/job_search/uv-cache run cc job-search board-snapshot
uv --cache-dir data/job_search/uv-cache run cc job-search board-setup --apply --backend local
uv --cache-dir data/job_search/uv-cache run cc job-search publish-suggestions --apply --backend local
uv --cache-dir data/job_search/uv-cache run cc job-search board-snapshot --backend local
uv --cache-dir data/job_search/uv-cache run cc job-search process-selected --dry-run --backend local
```

Real AppFlowy mode must fail closed when `job_search_pipeline` is not present
in `appflowy_kanban/growth-os/config/databases.json`. The explicit `--backend
local` path is only for local validation and tests.

If Claude Code is unavailable, run the same workflow with Codex. The executor
fallback must not weaken safety gates.

Codex fallback command shape:

```powershell
uv run cc job-search suggest --from-file <posting.md> --write
uv run cc job-search generate-materials <job_key> --selected-by-geoff --executor codex
```
