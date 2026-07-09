# Cockpit Board Guide

The cockpit now treats **All Boards** as the primary operator surface.

- **All Boards** is the typed domain view. Use this for day-to-day work because
  each board has the right card shape, fields, progress drawer, and chat
  handoff.
- **Missions** lives inside All Boards as a Ledger-backed board. The old
  top-level Missions view remains URL-addressable for debugging, but it is not
  the primary mobile nav.
- **Raw AppFlowy boards** remain optional projection/fallback state. The old
  top-level Boards view remains URL-addressable for debugging and comparison,
  but AppFlowy is not the cockpit.

## Sections

| Section | Use it for | Source today | How to add/update |
| --- | --- | --- | --- |
| Jobs | Job search pipeline, resumes, application memory, manual checklist | `job_search_pipeline_internal` board store | `uv run cc job-search suggest --from-file <posting.md> --write`, then `uv run cc job-search publish-suggestions --apply --backend internal` |
| Posts | LinkedIn/content queue preview | demo fixtures until content pipeline is wired | Add cards to `services/agent_kanban_ui/domain_fixtures.json` or wire a real content board later |
| Books | Reading list and notes | demo fixtures | Add cards to `services/agent_kanban_ui/domain_fixtures.json` until the library board is wired |
| Papers | Research queue and useful paper notes | demo fixtures | Add cards to `services/agent_kanban_ui/domain_fixtures.json` until the paper intake is wired |
| Repos | Repo operations and blockers | demo fixtures | Add cards to `services/agent_kanban_ui/domain_fixtures.json` until repo telemetry is wired |
| DAGs | Scheduled jobs and automation health | demo fixtures | Add cards to `services/agent_kanban_ui/domain_fixtures.json` until DAG telemetry is wired |
| Upkeep | Machine and system maintenance | demo fixtures | Add cards to `services/agent_kanban_ui/domain_fixtures.json` until upkeep checks are wired |
| Tasks | Generic tracked tasks | demo fixtures | Add cards to `services/agent_kanban_ui/domain_fixtures.json` or promote a real task board later |
| Missions | Ledger mission execution | Ledger | Created by agent workflows; approve/kill stays in the signed Ledger UI |

The demo-backed sections are intentionally visible so the UI shape is testable
before each real pipeline is wired. The Docker image must copy
`domain_fixtures.json`; if Posts/Books/etc. show `0`, check
`/api/debug/runtime -> paths.fixtures_file`.

## Jobs Flow

Jobs are prepare/manual-first:

1. `Suggested Jobs`: ranked jobs from a daily DAG or pasted posting.
2. `Selected by Geoff`: Geoff has approved spending time on it.
3. `In Progress`: material generation can run.
4. `Needs Geoff`: resume, cover letter, answer bank, checklist, and follow-up
   memory are ready; Geoff must review and submit manually where required.
5. `Completed`: Geoff confirms a real submission by dragging the card here.
6. `Interviewing`: recruiter/hiring-manager process is active.
7. `Rejected / Skip`: not pursuing or rejected.
8. `Closed / Archived`: stale/final outcome after retention.

The processor accepts either `Selected by Geoff` cards or `In Progress` cards
that do not yet have `application_id`/`materials_path`. This lets a cockpit drag
to `In Progress` act as the approval signal without losing the material
generation step. Already prepared `In Progress` cards are ignored so reruns do
not duplicate applications.

The Jobs header shows queue chips for `Bot Possible`, `Manual Required`, and
`Prepare Only`. Click a chip, or use the `any automation` dropdown, to split
the board into the bot-preparable and Geoff/manual queues. The daily publish
target is 50 surfaced cards: up to 25 bot-possible and up to 25 manual-required,
with the remaining slots filled by score-ranked jobs only when one side has too
few eligible postings.

Daily limits and role focus can be adjusted from **Controls -> Job Search**.
Those edits write to `data/job_search/profile/search_settings.yml`; the shared
job-search config loader merges that override with `configs/job_search.yaml`, so
CLI and DAG runs see the same effective settings.

Desktop: drag cards between lanes. Mobile: use each card's `Move to...` menu;
it calls the same governed move endpoint as drag/drop.

### Packet review (Needs Geoff)

Open a prepared card's drawer and press **review packet**. The modal shows the
complete application across tabs — Resume, Cover Letter, Answers, Recruiter
Msg, Follow-ups, Checklist, Job Description — plus:

- **Agent Trace**: the exact prompts (full achievement bank + job description +
  your notes) and raw model outputs behind every generation, with timing and
  claim ids. Materials are agent-written via LiteLLM by default; if the model
  was unreachable the packet says `template_fallback` and the trace shows why.
- **Validation**: the submit gate. Errors (missing files, unresolved change
  requests, invalid claim ids, already submitted) block submission; warnings
  (template-mode materials) are shown but do not block.
- **Request changes & regenerate**: type what is wrong ("lead with the NBA
  work") — the note is recorded in `review_notes.md`, the agent rewrites the
  materials against ALL accumulated notes, and the revision counter bumps.
- **Approve & submit**: runs validation, marks the application applied, moves
  the card to `Completed` through the same governed event as a drag, writes
  `submission_record.json` evidence, and emails you the full record (resume,
  cover letter, answers, job description attached). Dragging to `Completed`
  runs the identical gate — an invalid packet is refused before any event is
  logged.

Email records always land on disk as `submission_email.html`. Real delivery
needs `DISCOVERY_SMTP_HOST/USER/PASSWORD/FROM` and `JOB_SEARCH_EMAIL_TO` (or
`DISCOVERY_SMTP_TO`) in `.env`; the Overview tab names exactly which are
missing. CLI equivalents: `cc job-search packet <id> [--trace]`,
`cc job-search request-changes <id> --notes "..."`, `cc job-search finalize <id>`.

## Controls

Use **Controls** for operator settings:

| Panel | What it shows/edits |
| --- | --- |
| Runtime APIs | Ledger, LiteLLM, AppFlowy, GatewayCore, and the action/chat endpoints |
| All Boards | Add/remove/update `configs/domain_surfaces.yaml` domain boards; view `configs/kanban_boards.yaml` provider registry |
| Job Search | Daily search limits, role-focus keywords, profile file paths, and draft application defaults |

`configs/domain_surfaces.yaml` controls the visible All Boards sections, card
components, data source, columns, column actions, summary fields, drawer fields,
and empty states. Controls -> All Boards edits that file in full-console mode
and validates the whole document with `DomainSurfacesConfig` before saving.
Provider-backed board wiring still belongs in `configs/kanban_boards.yaml`, so a
new `board_store` domain needs a matching provider registry entry.

## Applying

The MVP does **not** auto-submit applications. It prepares the packet and records
why Geoff is needed:

- `application.yml`: status, stage, salary, portal, manual blockers.
- `generated_resume.md`: tailored resume.
- `cover_letter.md`: draft cover letter.
- `answer_bank.md`: default answers and evidence-backed claims.
- `manual_checklist.md`: exact manual steps/blockers.
- `followups.md`: ready follow-up context.
- `communications.jsonl` and `recruiter_notes.md`: recruiter/hiring-manager
  notes during the process.

Run Codex-backed preparation with:

```powershell
uv run cc job-search process-selected --apply --backend internal --executor codex
```

The executor choice is recorded in `executor.json`. It does not change the
submit policy, claim validation, or manual blockers.

After Geoff manually submits, drag the job card to `Completed`. The cockpit
updates the application record, applied date, retention window, and follow-up
pack from the card's `application_id`.

To add notes from a recruiter call or email, open the job card and use
`Next-Step Notes`. The CLI is still available as a fallback:

```powershell
uv run cc job-search note <application_id> --type recruiter_call --file notes.md
uv run cc job-search followup <application_id>
```

## Codex Handoff

Open any section card and use `open in chat` to prefill the cockpit chat with
the card context. For jobs, Codex can run the CLI workflow, inspect generated
materials, summarize blockers, draft follow-ups, and update notes. It should not
claim submission unless the card is moved to `Completed` after Geoff confirms the
application was actually submitted.
