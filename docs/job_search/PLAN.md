# Job Search Command Center — original plan and phase tracker

Status: original design doc, dated 2026-07-07; tracker refreshed 2026-07-08.
The safe MVP is now built around local/profile ingestion, claim-checked
material generation, 30-day application memory, the daily maintenance DAG,
and both AppFlowy and cockpit-native board paths. The remaining genuinely
open work is live job discovery/source adapters, PDF/ATS rendering checks,
Gmail/recruiter matching, actual rich-file purging/storage reporting, and any
future `bot_possible` submit path. See the `[x]`/`[ ]` marks in
"Implementation Phases" plus [JOB_SEARCH_COMMAND_CENTER.md](JOB_SEARCH_COMMAND_CENTER.md)
and [READINESS_FAQ.md](READINESS_FAQ.md) for the shipped behavior.

This plan turns the current resume-generator idea into a controlled job-search
command center for Geoff. The operating model is:

```text
Daily DAG finds and ranks jobs
-> Geoff reviews Suggested Jobs
-> Geoff moves good jobs to Selected by Geoff
-> bot prepares materials and attempts only allowed workflows
-> blocked jobs move to Needs Geoff
-> successful/manual-confirmed jobs move to Completed
-> active applications keep rich 30-day memory
-> recruiter/email/interview notes refresh follow-up packs
```

The important boundary is that the system recommends, prepares, tracks, and
drafts. It does not mass-apply, bypass portal controls, answer legal/EEO/self-ID
questions, or send recruiter messages without Geoff approval.

## Context Reviewed

- `data/job_search/Master_Resume_Bullet_Bank.docx` exists and has role-specific
  summaries, JPMorgan bullets, Driveline bullets, sports analytics projects,
  skills sections, education, and resume-tailoring rules.
- The bullet bank does not yet include World Model Sports as a Founder/CEO or
  founder-operator experience source.
- The pasted `MadsLorentzen/ai-job-search` repo is useful as a workflow pattern:
  setup profile, scrape/rank jobs, tailor CV/cover letter, verify PDF/ATS output,
  and record outcomes.
- That repo's built-in job portal skills are mostly Danish-market examples; for
  Geoff, the reusable parts are the profile/rank/apply/outcome patterns, not the
  default portal list.
- This repo already has the right host system: AppFlowy boards, a human approval
  wall, config validation, a daily DAG pattern, a memory store, and a LinkedIn
  content pipeline that uses a similar "draft -> human approve -> execute" flow.

## System Boundary

This should be a domain workflow inside `llm_station`, not a separate tracker.
It should use:

- `data/job_search/` for Geoff's profile source, generated materials, active
  application cache, and archive ledger.
- `src/command_center/job_search/` for job-search logic.
- `dags/job_search_daily.py` for the daily recommendation and maintenance DAG.
- A cockpit-native board named `job_search_pipeline_internal` for the primary
  first-party UI, plus an AppFlowy domain board named `job_search_pipeline`
  when the external workspace surface is useful.
- Existing Command Center principles: no self-approval, no restricted actions,
  no hidden failures, and no unvalidated long-lived config.

The job-search board is a domain board like the LinkedIn content boards, not the
same thing as `mission_intake`. Code changes to build this system still go
through `mission_intake`; job applications themselves go through
`job_search_pipeline`.

`data/job_search/` is local-only and gitignored. It will hold personal resume
source material, generated resumes, job descriptions, salary details, recruiter
communications, and interview notes. Reusable templates and schemas should live
in `docs/`, `configs/`, or `src/`, not in the personal data directory.

## Board Workflow

Support the same pipeline on the cockpit-native internal board and, where
desired, an AppFlowy board/database called `job_search_pipeline` with these
columns:

```text
Suggested Jobs
Selected by Geoff
In Progress
Needs Geoff
Completed
Interviewing
Rejected / Skip
Closed / Archived
```

Column behavior:

- `Suggested Jobs`: daily DAG output only. These are ranked jobs with short
  explanations, risks, salary notes, likely resume variant, location fit, and
  automation classification.
- `Selected by Geoff`: the human approval wall. Nothing is prepared or submitted
  unless Geoff moves the card here or explicitly selects it through a CLI/UI.
- `In Progress`: the bot may create the application folder, save the posting,
  extract salary/keywords, choose a resume variant, generate materials, run
  checks, and attempt an allowed workflow.
- `Needs Geoff`: portal or judgment blockers. The card must include the URL,
  generated materials, exact manual checklist, and the question(s) Geoff needs
  to answer.
- `Completed`: submitted by bot where allowed, or manually marked submitted by
  Geoff. This starts the 30-day rich-memory window.
- `Interviewing`: any recruiter or hiring-manager signal. Rich memory is kept
  until 30 days after the last active-process event.
- `Rejected / Skip`: jobs Geoff rejects, low-fit jobs, expired postings, or
  roles that should not be pursued.
- `Closed / Archived`: stale or final-outcome applications after retention has
  compacted bulky data into the archive ledger.

Suggested card fields:

```yaml
job_key: stable hash or source id
company: string
role_title: string
location: string
remote_type: remote | hybrid | onsite | unknown
source: LinkedIn | company_site | greenhouse | lever | ashby | other
portal: string
apply_url: string
salary_text: string | null
salary_min: number | null
salary_max: number | null
category: product_data_scientist | applied_ml_data_scientist | analytics_data_scientist | analytics_engineer | ml_engineer | sports_data_scientist | lead_senior_data_scientist | data_architecture_manager | founder_operator_product_ai
fit_score: 0-100
automation_class: bot_possible | prepare_only | manual_required | skip
manual_reason: string | null
resume_variant: string
why_apply: string
risks: string
deadline: date | null
last_seen_at: datetime
```

## Automation Classes

Every job gets one automation classification before anything is attempted.

```yaml
bot_possible:
  meaning: Public posting and application flow appears simple, low-risk, and not restricted.
  allowed_actions:
    - prepare materials
    - fill non-sensitive profile fields from approved profile data
    - submit only if no login, captcha, MFA, legal certification, self-ID, or subjective judgment appears

prepare_only:
  meaning: The job is worth applying to, but submission should be manual.
  allowed_actions:
    - save posting
    - generate resume and cover letter
    - generate recruiter note
    - create checklist
    - move card to Needs Geoff

manual_required:
  meaning: Portal or question set requires Geoff.
  allowed_actions:
    - prepare materials
    - list exact manual steps
    - track once Geoff confirms submitted

skip:
  meaning: Low fit, bad location, below-threshold salary, restrictive terms, expired, duplicate, or hard requirement mismatch.
  allowed_actions:
    - explain why skipped
    - keep short skip record for dedupe
```

Manual-required triggers:

- LinkedIn Easy Apply or Indeed where automation conflicts with platform terms
  or account controls.
- Login, MFA, captcha, bot checks, or session challenges.
- EEO, voluntary self-ID, disability, veteran status, legal certification, or
  background-check acknowledgements.
- Work authorization, sponsorship, clearance, relocation, salary expectation,
  non-compete, or start-date questions.
- Workday/Greenhouse/Lever/Ashby/custom ATS questions that require judgment.
- Any page where confidence falls below the configured threshold.
- Any recruiter or hiring-manager message. The system may draft, but Geoff
  reviews before send.

## Resume And Target Controls

Use structured controls so Geoff can change the search without editing code.
These should be added as validated config contracts before they become live
`configs/*.yaml`.

Planned files:

```text
data/job_search/profile/
  Master_Resume_Bullet_Bank.docx
  achievement_bank.yml
  resume_variants.yml
  job_targets.yml
  writing_style.yml
  manual_only_rules.yml
  claim_policy.yml

data/job_search/evidence/
  jpmorgan.md
  driveline.md
  world_model_sports.md
  betts_basketball.md
  sports_projects.md
  education.md
```

Control meanings:

- `achievement_bank.yml`: compact, tagged bullet bank. Each bullet has tags,
  role families, tools, domains, impact metrics, source evidence, confidence,
  and whether it is safe for resume use.
- `resume_variants.yml`: which summaries, skills, bullets, and projects are
  eligible for each resume family.
- `job_targets.yml`: role categories, preferred titles, negative titles,
  locations, salary preferences, seniority rules, and source queries.
- `writing_style.yml`: resume and cover-letter tone, length, banned phrases,
  and Geoff-specific wording preferences.
- `manual_only_rules.yml`: automation blockers and portal-specific rules.
- `claim_policy.yml`: no generated resume claim can be used unless backed by
  `achievement_bank.yml` or an evidence file.

Initial resume variants:

```text
product_data_scientist
applied_ml_data_scientist
analytics_data_scientist
analytics_engineer
ml_engineer
sports_data_scientist
lead_senior_data_scientist
data_architecture_manager
founder_operator_product_ai
```

Initial search controls:

```yaml
locations:
  primary:
    - Remote US
    - Florida
    - Phoenix hybrid
  acceptable_for_strong_fit:
    - Tampa
    - Orlando
    - Miami
    - New York
    - Colorado Springs
    - Seattle
    - Bay Area

role_priority:
  highest:
    - Product Data Scientist
    - Applied Data Scientist
    - Senior Analytics Engineer
    - Analytics Engineer
    - Sports Data Scientist
    - Basketball Data Scientist
    - Data Scientist, Experimentation
    - Data Architecture Manager
  secondary:
    - ML Engineer
    - BI Engineer
    - Strategy Analytics
    - Fan Analytics
    - Revenue Analytics
    - Data Engineer, Analytics

ranking:
  min_score_to_show: 70
  min_score_to_recommend_apply: 82
  sports_domain_bonus: 8
  founder_operator_bonus_for_startups: 6
  missing_salary_penalty: 3
  manual_required_penalty: 5  # superseded — live configs/job_search.yaml uses 2 (re-tuned 2026-07-08; see READINESS_FAQ.md)
```

## World Model Sports Profile Addition

World Model Sports should become a first-class experience source because it
proves founder-led product, applied AI, sports analytics, full-stack execution,
and domain depth.

Add this role to the structured profile:

```text
World Model Sports LLC - Founder & CEO / Principal Data Scientist
2026 - Present
```

Use title variants by role type:

- Leadership, startup, strategy, product, sports, and senior analytics:
  `Founder & CEO`.
- IC data scientist, analytics engineer, ML engineer, and hands-on roles:
  `Founder / Principal Data Scientist`.

Initial WMS summary:

```text
Founder and principal builder of World Model Sports, an applied AI sports
analytics platform focused on NBA player value, future roster forecasting,
contract efficiency, graph/network analysis, lineup strategy, and explainable
basketball intelligence.
```

Initial WMS bullets to structure and tag:

```text
- Founded World Model Sports LLC and led product, data, engineering, and go-to-market planning for Hoops World Model, a basketball intelligence platform for player valuation, roster strategy, contract efficiency, and explainable NBA analytics.
- Architected an end-to-end basketball analytics platform spanning data ingestion, player valuation, future value forecasting, salary/contract efficiency, graph/network analysis, lineup strategy, and frontend decision-support views.
- Built production-oriented NBA analytics workflows using Python, SQL, FastAPI, Docker, validation checks, and frontend analytics surfaces to convert research models into usable decision-support tools.
- Developed player value and roster-construction research across multi-league data, archetype clustering, age curves, Bayesian modeling, surplus value, market value, and future team-building scenarios.
- Designed graph/network analysis workflows to visualize player, lineup, team, and roster relationships, helping explain fit, role interaction, lineup pockets, and strategic basketball decisions.
- Built founder-led documentation, validation, and implementation standards for sports analytics pipelines, including schema checks, historical validation, real-data examples, KPI definitions, and reproducible deployment plans.
- Developed a public-facing sports intelligence product strategy covering fan, bettor, analyst/journalist, coach, and team-builder use cases, with roadmap planning for subscriptions, consulting/pilots, alerts, content, and future API/licensing.
- Led full-stack execution across backend APIs, model pipelines, frontend analytics views, CI/testing, deployment planning, and product documentation while operating as founder, principal analyst, and technical owner.
```

For most resumes, use two to four WMS bullets only. The generator should decide
whether WMS is a main experience section, a recent project section, or a short
add-on depending on the job category.

## Application Memory

Keep rich detail only while it is useful.

```text
data/job_search/applications_active/
  <application_id>/
    application.yml
    job_description.md.gz
    generated_resume.pdf
    generated_resume.docx or .tex
    cover_letter.pdf
    recruiter_message.md
    recruiter_notes.md
    communications.jsonl
    followups.md

data/job_search/applications_archive/
  outcomes.sqlite
```

Rich active cache:

- Keep full job description, salary, keywords, generated materials, notes, and
  communications for 30 days after application date.
- If there is recruiter contact, an interview, a take-home, an offer, or another
  active-process signal, extend rich retention until 30 days after the last
  activity.
- Once closed or stale, purge bulky files unless Geoff marks the role as keep.

Permanent archive ledger:

- Keep company, title, source, portal, apply URL hash, applied date, final
  outcome, category, resume variant, fit score, salary range, and application
  status.
- Keep bullet IDs and resume variant IDs, not full job descriptions forever.
- Keep communications summaries, not full emails, unless a process is active.

Application record shape:

```yaml
application_id: "2026-07-07_company_role"
company: "Company"
role_title: "Senior Analytics Engineer"
category: "analytics_engineer"
source: "LinkedIn"
portal: "Greenhouse"
apply_url: "https://..."
status: "applied"
stage: "completed"
automation_class: "prepare_only"
manual_required: true
manual_reason: "Greenhouse custom questions"
resume_variant: "analytics_engineer"
applied_at: "2026-07-07"
last_activity_at: "2026-07-07"
retention_until: "2026-08-06"
salary:
  listed: true
  min: 130000
  max: 170000
  currency: USD
fit:
  score: 87
  reasons:
    - "Strong SQL/dbt/Snowflake/Airflow match"
  risks:
    - "May prefer direct sportsbook experience"
keywords:
  required: []
  preferred: []
  matched: []
  gaps: []
materials:
  resume_pdf: "generated_resume.pdf"
  cover_letter_pdf: "cover_letter.pdf"
  job_description_gz: "job_description.md.gz"
followup:
  next_action: "wait_5_business_days_then_follow_up"
  suggested_reply_ready: true
  talking_points: []
```

Communications should be append-only JSONL:

```json
{"ts":"2026-07-08T10:12:00-04:00","type":"email_received","summary":"Recruiter asked for availability.","action_needed":"Reply with times.","source":"gmail"}
```

## Follow-Up Packs

Every active application gets `followups.md`, regenerated when new activity
arrives.

Follow-up pack sections:

- Why Geoff applied.
- Best proof points from JPMorgan, Driveline, World Model Sports, and projects.
- Role-specific 60-second pitch.
- Salary notes and compensation framing.
- Recruiter reply draft.
- Hiring-manager note draft.
- Interview prep bullets.
- Likely questions and best story bank.
- Notes from any prior recruiter/email/interview communications.
- Next action and due date.

The system may draft replies and LinkedIn notes, but it must not send them
without Geoff approval.

## Gmail And Notes Integration

Optional connector flow once Gmail access is configured:

```text
For every active application:
  search Gmail by company, domain, role title, recruiter name, job code, and ATS subject
  summarize matching thread events
  append to communications.jsonl
  update last_activity_at
  move board card to Interviewing or Needs Geoff if action is required
  regenerate followups.md
  draft a reply when useful
```

Manual note flow:

```text
cc job-search note <application_id> --type phone_screen --file notes.md
```

The note command should append a summary to `communications.jsonl`, update
`last_activity_at`, and refresh the follow-up pack.

## Daily DAG

Planned DAG: `dags/job_search_daily.py`

Schedule: daily around Geoff's morning review window. The first useful default
is 08:00 America/New_York.

Stages:

```text
load_config
load_profile
search_sources
normalize_jobs
dedupe_jobs
score_fit
classify_resume_variant
classify_automation
create_or_update_suggested_cards
process_selected_cards
generate_materials
attempt_allowed_or_route_manual
create_or_update_application_memory
refresh_followup_packs
enforce_retention
emit_daily_digest
```

Stage notes:

- `search_sources`: start with company ATS boards and public listings where
  access is allowed. Add LinkedIn public listings only with low volume and clear
  terms warnings. Avoid auth-walled scraping.
- `normalize_jobs`: produce one canonical job object regardless of source.
- `dedupe_jobs`: dedupe by normalized company, title, location, and URL hash.
- `score_fit`: score skills, role category, domain, seniority, location, salary,
  resume evidence strength, and manual difficulty.
- `classify_resume_variant`: select one resume variant and eligible bullet set.
- `classify_automation`: classify as `bot_possible`, `prepare_only`,
  `manual_required`, or `skip`.
- `create_or_update_suggested_cards`: write cards only to `Suggested Jobs`.
- `process_selected_cards`: only cards Geoff selected move to application work.
- `generate_materials`: run resume/cover/recruiter-message generation and
  checks. Do not submit yet.
- `attempt_allowed_or_route_manual`: MVP always routes prepared applications to
  `Needs Geoff`; future submit work needs separate approval and tests.
- `enforce_retention`: compact stale inactive applications.
- `emit_daily_digest`: write a short report to `generated/job-search-digest.md`
  and optionally notify a configured channel.

## CLI Surface

Add one operator namespace:

```text
uv run cc job-search ingest-profile
uv run cc job-search suggest --from-file <posting.md> --write
uv run cc job-search validate-examples
uv run cc job-search board-setup --dry-run
uv run cc job-search board-snapshot
uv run cc job-search publish-suggestions --dry-run
uv run cc job-search process-selected --dry-run
uv run cc job-search digest
uv run cc job-search generate-materials <job_key> --selected-by-geoff
uv run cc job-search mark-submitted <application_id>
uv run cc job-search note <application_id> --type recruiter_call --file notes.md
uv run cc job-search followup <application_id>
uv run cc job-search retention --dry-run
uv run cc job-search retention --apply
```

Dry-run should be the default for discovery, board write planning, and retention
until the first end-to-end slice is proven.

## Implementation Phases

### Phase 0 - Repo Fit And Safety Contract

- [ ] Decide whether to vendor `ai-job-search` as a reference under
  `integrations/ai-job-search/` or port only the patterns.
- [x] Document portal terms and automation boundaries before adding source
  integrations.
- [x] Add `JobSearchConfig` and related Pydantic schemas before adding live
  `configs/job_search*.yaml`.
- [x] Add tests proving no job-search path can bypass manual blockers or send
  messages without approval.

### Phase 1 - Profile Ingestion

- [x] Copy or move the master `.docx` into `data/job_search/profile/`.
- [x] Convert the `.docx` bullet bank into `achievement_bank.yml`.
- [x] Add World Model Sports as a first-class experience source.
- [x] Add `evidence/world_model_sports.md`.
- [x] Add any new achievement list Geoff brings into
  `data/job_search/profile/inbox/` and merge it into the achievement bank.
- [x] Tag every bullet by role family, skill, tool, domain, proof strength, and
  source evidence.

### Phase 2 - Resume Variant Controls

- [x] Create `resume_variants.yml`.
- [x] Create `job_targets.yml`.
- [x] Create `writing_style.yml`.
- [x] Create `claim_policy.yml`.
- [x] Implement claim validation so generated resumes only use approved claims.
- [x] Add a resume diff/check report showing which bullets were selected and why.

### Phase 3 - Job Board

- [x] Add a GrowthOS/AppFlowy schema for `job_search_pipeline`.
- [x] Create fields listed in this plan.
- [x] Add a board setup/reconcile command modeled after the content board scripts.
- [x] Add a board snapshot command for testing and digesting.
- [x] Verify that only Geoff-selected cards can enter material generation.
- [x] Add the cockpit-native `internal` backend (`job_search_pipeline_internal`)
  so the first-party UI can run without AppFlowy quirks.
- [x] Wire the first-party `Domains` view so the Jobs domain reads the internal
  board store directly and keeps fixture/demo origins honest for other domains.

### Phase 4 - Job Discovery And Ranking

- [ ] Implement source adapters for safe/public sources first.
- [x] Normalize all jobs to one schema.
- [x] Add dedupe with stable hashes.
- [x] Add scoring against target roles, location, salary, seniority, domain,
  tools, and evidence strength.
- [x] Generate one-screen explanations for every suggested card.
- [ ] Generate skip reasons for rejected/low-fit jobs.

### Phase 5 - Material Generation

- [x] Generate targeted resume from `achievement_bank.yml`.
- [x] Generate cover letter draft.
- [x] Generate recruiter message draft.
- [ ] Run PDF/ATS parseability checks.
- [x] Run unsupported-claim checks.
- [x] Save materials into the active application folder.

### Phase 6 - Apply Or Route Manual

- [x] Detect blockers before submission.
- [x] Implement `prepare_only` and `manual_required` paths first.
- [ ] Add `bot_possible` submission only after the blocker tests are strong.
- [x] Move selected cards to `Needs Geoff` with a checklist and materials.
- [x] Let Geoff mark manual applications submitted.
- [x] Create active application records for Geoff-selected prepared materials.

### Phase 7 - Active Memory And Follow-Ups

- [x] Add active application directory writer.
- [x] Add `outcomes.sqlite`.
- [x] Add `communications.jsonl` append helpers.
- [x] Generate and refresh `followups.md`.
- [ ] Add Gmail thread matching once connector access is ready.
- [x] Add manual note ingestion for recruiter calls and interviews.

### Phase 8 - Retention

- [x] Implement 30-day rich-cache retention.
- [x] Extend retention for active recruiter/interview processes.
- [x] Archive minimal outcomes to SQLite.
- [ ] Purge compressed job descriptions/materials for stale inactive roles.
- [ ] Produce a weekly storage report.

### Phase 9 - Daily DAG And Digest

- [x] Create `dags/job_search_daily.py`.
- [ ] Run read-only discovery first.
- [x] Draft Suggested Jobs cards from cached local suggestions.
- [x] Process selected cards only.
- [x] Enforce retention.
- [x] Write `generated/job-search-digest.md`.
- [x] Add tests for idempotency and duplicate-card prevention.

## MVP Acceptance Criteria

The first usable version is done when:

- Geoff can drop achievements into `data/job_search/profile/inbox/`.
- The system converts the resume bank plus WMS into structured achievements.
- The daily run surfaces ranked jobs in `Suggested Jobs`.
- Geoff can select jobs by moving cards to `Selected by Geoff`.
- Selected jobs produce targeted resume materials and a manual checklist.
- Blocked applications move to `Needs Geoff`.
- Confirmed applications create active 30-day application memory.
- `followups.md` exists for every completed application.
- Retention can dry-run and show exactly what would be purged.

## First Build Slice

Build this in the smallest safe order:

1. Add structured profile/evidence files and WMS bullets.
2. Add job-search schemas and config validation.
3. Add local-only CLI commands for profile ingest, ranking from pasted job text,
   material generation, and active application records.
4. Add the AppFlowy `job_search_pipeline` board schema and safe board commands.
5. Add discovery adapters and the daily DAG.
6. Add Gmail/recruiter note integration.
7. Add controlled `bot_possible` submission after manual routing is reliable.

This order gives Geoff value before any risky automation exists: targeted
materials, job ranking, manual blocker lists, and 30-day follow-up memory.
