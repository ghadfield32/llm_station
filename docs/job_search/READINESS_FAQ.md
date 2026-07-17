# Job Search Command Center - Readiness FAQ

Status: live-validated against the real AppFlowy board and 3 real job postings
on 2026-07-08, then extended the same day with card links, a KPI-level score
explanation, company/role filtering, and a categorized answer bank. This is
the single reference for "what happens when X happens," including data
retention (see "What data is kept") and executor fallback (see "What if
Claude Code is unavailable"). See also `JOB_SEARCH_COMMAND_CENTER.md`
(architecture), `MANUAL_APPLICATION_RULES.md`, and `RESUME_CLAIM_POLICY.md`.

## FIRST-TIME BOARD SETUP: turn on the columns (one 20-second step)

If the board opens as a single "No Type" column with cards that only show a
"Done" checkbox and nothing to drag between - that is expected on a
freshly-created board, and it is a one-time client-side fix, not a data
problem. Here is why and how:

AppFlowy's self-hosted **REST API cannot set a board view's "Group by"
field** (it also can't edit select options, delete/reorder fields, or delete
rows - those are all client-only operations over its sync protocol). A brand
new AppFlowy database always ships a default "Type" single-select field, and
a REST-created board auto-groups by the first such field it finds - the empty
"Type" - which is why you see one "No Type" column. Our `Status` field
(which has all 8 pipeline stages) exists and every card is already tagged
"Suggested Jobs"; the board view just needs to be pointed at it.

**Fix (do this once):**

1. Open `job_search_pipeline` and click the **Board** tab (not Grid).
2. Open the board's view settings - the **`...` (Settings)** menu at the
   top-right of the board on desktop, or the settings icon on mobile.
3. Choose **Group by** and pick **Status**.
4. All eight columns appear instantly - Suggested Jobs, Selected by Geoff,
   In Progress, Needs Geoff, Completed, Interviewing, Rejected / Skip,
   Closed / Archived - with your cards under Suggested Jobs. Now you can drag.

**Optional one-time cleanup** (cosmetic; the REST API can't do these for you):

- Delete the 3 blank starter rows AppFlowy auto-created (right-click a blank
  card -> Delete). They carry no `job_key`.
- Hide the default `Type` and `Done` fields on cards via the card/field
  settings so cards only show the fields we populate.

**Verify anytime** with:

```powershell
uv run cc job-search board-doctor
```

It confirms the `Status` field has all 8 stage options, counts your real vs.
blank rows, flags the leftover `Type`/`Done` default fields, and reprints
these grouping steps. If it says `status_has_all_stage_options: true`, the
database is correct and the only thing left is the Group-by-Status step above.

## If the AppFlowy board ever looks empty or "deleted"

This happened once, on 2026-07-08: the entire **"General" space** (the parent
folder holding every board, including `job_search_pipeline`) got moved to
AppFlowy's trash. Nothing was lost - AppFlowy's trash is a real undo, not a
countdown to deletion. Recovery:

```text
GET  /api/workspace/{ws}/trash                              # list what's trashed
POST /api/workspace/{ws}/page-view/{view_id}/restore-from-trash
```

Restoring the space's `view_id` brings back every child board and every row
in it - verified live: all 8 cards on `job_search_pipeline` were intact after
restore, byte-for-byte. If this happens again, tell Claude "the AppFlowy
boards disappeared" and it can check `/trash` and restore the right item in
under a minute. The likely cause is an accidental right-click delete on the
space itself (not a single card) - AppFlowy doesn't ask "are you sure" the
same way for spaces as it does for a single page in every client.

## The five-minute mental model

```text
Daily DAG / manual suggest -> Suggested Jobs (score >= 70)
Geoff reviews on phone/AppFlowy, drags good ones -> Selected by Geoff
process-selected --apply -> In Progress -> Needs Geoff (always, for now)
Geoff applies manually using the generated materials + checklist
Geoff drags card to Completed -> 30-day rich memory starts
Explicitly marked furthering recruiter/interview activity -> Interviewing -> retention extends
```

Nothing is ever auto-submitted. `auto_submit_enabled` is schema-rejected if
set to `true` (see `test_config_rejects_auto_submit_enabled`). Every
suggested/selected/prepared job still requires a human click to actually
apply.

## Card links and the score explanation (new 2026-07-08)

Every card now carries three extra fields beyond the original set:

- **`apply_url`** - the original posting, already a clickable URL field.
  Tap it to review the job on the company's own site.
- **`claude_review_url`** - tap this to open a *new* Claude conversation
  (`claude.ai/new?q=...`) pre-filled with the job's company, title, score,
  and reasons, and a prompt asking Claude to help you sanity-check it before
  you apply. This uses claude.ai's URL-based chat-prefill convention; if
  Anthropic ever changes that URL scheme this field would stop prefilling
  (it would still open claude.ai, just blank) - low risk, easy to notice.
- **`score_explanation`** - a long-text field. AppFlowy shows long-text
  fields collapsed in the row/board view and expands them when you open the
  card, which is the closest AppFlowy has to a "dropdown for details." It's a
  full KPI-style breakdown: base score, achievement/keyword overlap, every
  bonus and penalty applied with its point value, which of *your* past
  projects (JPMorgan/Driveline/World Model Sports/sports projects) drove the
  match, any company-tier bonus, and where the final number sits relative to
  the show/recommend-apply bars. Example (Axios, Analytics Engineer, 72/100):

  ```text
  Score breakdown:
    +45  Base score
    +16  Achievement/keyword overlap
    +5   Core Python/SQL match
    +8   Analytics engineering stack (Snowflake/dbt/Airflow)
    -2   Manual-required portal/questions

  Your experience that drove this score:
    - JP Morgan Chase / Self-serve analytics ELT (jpmc_snowflake_dbt_elt)
    - World Model Sports LLC / World Model Sports platform (wms_founder_platform)
  ```

## Filtering: Data Science first, Analyst/Engineering only at target companies

You asked for Data Science as the main search, with room to also look at
Analyst and Engineering roles specifically at major companies or sports
organizations. There's no live scraping yet (see "still off" below), so this
shows up today as **scoring + two card fields you filter on in AppFlowy**,
not a separate search mode:

- `category` on the card is one of the 9 role categories. The "Data Science"
  ones are `product_data_scientist`, `applied_ml_data_scientist`,
  `sports_data_scientist`, `lead_senior_data_scientist`, and
  `founder_operator_product_ai` - these are `role_focus: primary` in
  `configs/job_search.yaml` and always searched broadly. `analytics_data_scientist`,
  `analytics_engineer`, `ml_engineer`, and `data_architecture_manager` are
  `role_focus: secondary` - still scored and shown, but the intent is to
  lean on them mainly when `company_tier` is not `none`.
- `company_tier` is `none`, `sports_team`, `sports_tech`, `faang`, or
  `major_other`, computed from `configs/job_search.yaml -> company_targets`
  (FAANG: Meta/Facebook/Google/Alphabet/Amazon/Apple/Netflix; major_other:
  Disney, ESPN, Figure AI; sports_tech: Second Spectrum, Sportradar, Genius
  Sports, Hawk-Eye, Catapult, Zelus, Kitman Labs, Sportlogiq, DraftKings,
  FanDuel, Swish Analytics, STATS Perform, Opta, PFF, Synergy Sports,
  Tracab; sports_team: matches league names/keywords like NBA/NFL/MLB/NHL/MLS
  anywhere in the company or posting text, so it also catches "supports NBA
  analytics" roles at non-team employers, not just literal team front
  offices). **"Figure" is assumed to mean Figure AI (humanoid robotics) - fix
  `configs/job_search.yaml -> company_targets.major_other` if that's wrong.**
  A `company_tier` match also adds `ranking.target_company_bonus` (6 points)
  to the fit score.
- Set up two AppFlowy filtered views on `job_search_pipeline` once (any Grid
  or Board view, "Filter" in the toolbar):
  - **"Data Science"**: `category` is any of the 5 primary ids above.
  - **"Analyst/Engineering @ target companies"**: `category` is any of the 4
    secondary ids above, AND `company_tier` is not `none`.
  This is native AppFlowy filtering - no code needed, and it works on
  the phone view the same as desktop.

## The answer bank - ready-made answers by project type and by package

Every prepared application now includes `answer_bank.md` alongside the
resume/cover letter/checklist. It picks the single best-matching story per
project type for *this specific job* (by tool/domain overlap), so instead of
one generic set of talking points you get:

- **Python project** -> usually the Bayesian/NBA player-value or Driveline
  biomechanics story.
- **Engineering project** -> usually a JPMorgan Snowflake/dbt/Airflow
  pipeline story.
- **Analyst project** -> usually the A/B-testing framework or reporting
  automation story.
- **Leadership project** / **Founder project** -> team-lead or World Model
  Sports stories.

Each is a full STAR narrative (Situation/Task/Action/Result), built only from
facts already in `achievement_bank.yml` - nothing invented beyond what's
already claim-checked. The file ends with a **package/tool index** (e.g.
"PyTorch -> jpmc_fastapi_mlflow_models", "dbt -> jpmc_snowflake_dbt_elt") so
if an application or interviewer asks about a specific package, you know
exactly which story to reach for. To add more stories or packages, add
`project_type` and `full_story` to an achievement in `achievement_bank.yml`
(see `docs/job_search/RESUME_CLAIM_POLICY.md`) - same inbox-drop-then-ask-Claude
workflow as adding a plain achievement.

## Jobs this system currently CANNOT submit for you (you do these yourself)

- Anything on **LinkedIn, Indeed, Workday, Greenhouse, Lever, or Ashby** -
  these are hard-coded `manual_portals`. In practice this is nearly the
  entire modern ATS market, so expect almost every real posting to land as
  `manual_required`. That is intentional, not a bug.
- Any posting behind **login, MFA, or captcha**.
- Any question about **EEO, voluntary self-ID, disability, veteran status,
  legal certification, background checks, work authorization, sponsorship,
  salary expectation, relocation, start date, non-compete, or security
  clearance**. These are in `never_auto_answer` and `review_required` in
  `configs/job_search.yaml` - the system will draft a suggested answer for
  some of these (see `draft_defaults`) but will never submit them for you.
- Any **recruiter or hiring-manager message** - drafted only, you send it.
- Anything scored below `ranking.min_score_to_show` (currently 70) - it will
  not appear in Suggested Jobs at all. If you want to evaluate a job anyway,
  run `cc job-search suggest --from-file <file> --write` directly; it still
  gets scored and cached even if it wouldn't have been surfaced automatically.
- Any posting whose source **blocks automated fetching**. Validated live on
  2026-07-08: Greenhouse job-board pages fetched fine; **Lever.co, LinkedIn,
  and most job aggregators (TeamTailor, RemoteRocketship, SportsTechJobs,
  etc.) returned 403/404/410 to automated fetch.** For those, copy the full
  posting text yourself into a markdown file with frontmatter (see
  `docs/job_search/examples/*.md` for the format) rather than relying on a
  fetch.
- Actual submission even for `bot_possible` jobs. The MVP always routes to
  `Needs Geoff` regardless of automation class, by design, until submission
  logic gets its own dedicated safety pass (Phase 6 in the plan).

## What happens when a recruiter reaches out?

```text
uv run cc job-search note <application_id> --type recruiter_call --file notes.md --furthers-process
```

This appends a summary to `communications.jsonl`, moves the board card to
`Interviewing`, extends the retention window to 30 days past *this* event,
and regenerates `followups.md` with a next action. The explicit
`--furthers-process` flag is required for the stage/retention change; recruiter
rejections and ordinary notes can be recorded without it and do not advance the
card or clock. The cockpit exposes the same choice as a checkbox.

Note: as of 2026-07-08, regenerating materials (`generate-materials` /
`process-selected`) for a job that already has notes logged **no longer
wipes `communications.jsonl` or `recruiter_notes.md`** - this was found and
fixed during live validation (see `test_regenerating_materials_does_not_wipe_existing_communications`).
Before this fix, a same-day re-run of material generation would have
silently erased any recruiter notes already logged that day.

## What data is kept, for how long, and why?

- Every application gets a rich folder under
  `data/job_search/applications_active/<application_id>/`:
  `application.yml`, `job_description.md.gz`, `generated_resume.md`,
  `cover_letter.md`, `recruiter_message.md`, `resume_selection_report.md`
  (claim traceability), `answer_bank.md` (see "The answer bank" above),
  `communications.jsonl`, `recruiter_notes.md`, and `followups.md`.
- Rich data is kept through the per-record `retention_until` date (30 days by
  default and adjustable from Cockpit Controls). A note refreshes that date only
  when the operator explicitly marks it as furthering the process; an ordinary
  note or stale active status does not extend retention.
  Statuses recognized as active while the current window is still valid:
  `recruiter_contact`,
  `interviewing`, `phone_screen`, `take_home`, `onsite`, `offer`,
  `negotiation`.
- After that, `cc job-search retention --apply` writes an idempotent minimal
  ledger row in `data/job_search/applications_archive/outcomes.sqlite`
  (company, title, source, portal, outcome, category, resume variant, fit
  score, salary range, bullet IDs used) and writes an
  `ARCHIVED_MINIMAL_LEDGER_WRITTEN.txt` marker. The MVP writes minimal
  archive rows only - rich file deletion is disabled through
  `purge_rich_files: false`. Always run `--dry-run` first to see exactly what
  would be archived. Repeated apply runs leave the original archive timestamp
  unchanged. A later explicitly furthering communication reactivates the rich
  record and starts a new window. Prepared-but-never-submitted packets never
  enter the applied-job outcome ledger.
- Because rich deletion is disabled, this does **not** bound disk growth. It
  preserves the rich folder plus the minimal outcome row so a later follow-up
  can use the original evidence.

## What if Claude Code is unavailable?

The repo declares executor fallback in `configs/models.yaml` (`priority 1:
claude-code`, `priority 2: codex-cli`). Every job-search command is a plain
CLI call, so Codex (or any other executor) runs the identical workflow:

```powershell
uv run cc job-search ingest-profile --executor codex
uv run cc job-search validate-examples --executor codex
uv run cc job-search suggest --from-file <posting.md> --write --executor codex
uv run cc job-search generate-materials <job_key> --selected-by-geoff --executor codex
```

`executor.json` records which executor ran and asserts
`auto_submit_enabled: false` regardless. Executor choice never changes claim
validation, manual-blocker routing, or the no-submit rule - validated live
against a real posting (BetterHelp) on 2026-07-08.

## What if the fit score or resume variant looks wrong?

The scorer is a keyword-overlap heuristic, not a model call - it will
sometimes be too conservative on real postings that use different phrasing
than the achievement bank. Two live findings from 2026-07-08 validation:

1. **Category selection** used to pick the resume variant with the most
   incidental keyword hits, so a role literally titled "Analytics Engineer"
   could get miscategorized as `analytics_data_scientist` just because the
   posting also mentioned SQL/dashboard/Tableau more than dbt/Snowflake. This
   is now fixed: if the job title itself names a category (e.g. "Analytics
   Engineer", "Product Data Scientist"), that title wins over the keyword
   count.
2. **Real postings scored lower than fixtures** because the keyword
   vocabulary (`KNOWN_KEYWORDS` in `scoring.py`) was narrow, and the flat
   `manual_required_penalty` (5 points) was being applied to nearly every
   real posting (since almost all ATS-hosted jobs are `manual_required` by
   definition). The keyword list was broadened (NLP/LLM/Looker/BigQuery/
   Redshift/ELT/KPI/etc.) and the penalty reduced to 2 - two of three live
   test postings moved from below-threshold to correctly surfaced without
   changing fixture behavior (all 33+ tests still pass).

There is currently **no CLI flag to manually override a resume variant** for
a specific job. Workaround: edit the cached suggestion at
`data/job_search/source_cache/suggestions/<job_key>.json` (change
`selection.resume_variant`) before running `generate-materials <job_key>`
without `--from-file` (which reads the cache instead of re-scoring). This is
a known gap worth a real CLI flag later if it comes up often.

## How do I add new achievements (including World Model Sports updates)?

Drop the raw material (bullet list, resume excerpt, `.docx`, whatever you
have) into `data/job_search/profile/inbox/`, then run:

```powershell
uv run cc job-search ingest-profile
```

The report will list `pending_inbox_files` and an `inbox_hint` if anything is
sitting there. **This step is intentionally not fully automatic** - turning
freeform text into a schema-correct `achievement_bank.yml` entry requires
judgment calls (which evidence file backs it, confidence level, whether it's
resume-safe, how to phrase it per resume variant) that a bare parser
shouldn't make silently. The intended workflow is: drop the file, then ask
Claude Code (or Codex) to read it and propose new entries in
`achievement_bank.yml` following `RESUME_CLAIM_POLICY.md` (every claim needs
an achievement ID, an evidence file, and non-low confidence), and you approve
before it's used in any resume. World Model Sports is already seeded as
`Founder & CEO / Principal Data Scientist` with two achievement entries and
`evidence/world_model_sports.md` - bring more evidence (metrics, specific
deliverables) any time and it gets merged the same way.

## Board mechanics on the live AppFlowy `job_search_pipeline` board

- Columns: `Suggested Jobs -> Selected by Geoff -> In Progress -> Needs
  Geoff / Completed -> Interviewing -> Rejected / Skip -> Closed / Archived`.
- You only ever need to touch two columns yourself day-to-day: drag good
  suggestions into `Selected by Geoff`, and drag rejects into
  `Rejected / Skip`. Everything else is bot-driven or CLI-driven.
- `publish-suggestions` never touches a card you've already moved out of
  `Suggested Jobs`, and never overwrites your own notes/priority/comments
  fields (`notes`, `custom_priority`, `geoff_comments`, `manual_decision`)
  once you've set them.
- `process-selected` only ever reads cards currently in `Selected by Geoff`;
  everything else is ignored, even if it looks stale.
- Card `Status` should move to `Completed` only after a real submission. The
  cockpit drag now updates `application.yml`, retention, and follow-up state
  from the card's `application_id`; the old CLI command is fallback only.
- 3 blank rows may appear in `Suggested Jobs` the first time a board is
  created - that's AppFlowy's own default starter rows on a brand-new
  database, not something our code wrote. Safe to delete manually in the UI.

## Phone access

AppFlowy is self-hosted and reachable on your Tailscale tailnet at
`https://vengeance.taile6a055.ts.net` (already configured via `tailscale
serve`, tailnet-only - not exposed to the public internet). Open that on your
phone's browser with Tailscale connected, log in, and the
`job_search_pipeline` board is there like any other AppFlowy board.

If AppFlowy ever looks unreachable (empty replies, connection reset) even
though `docker ps` shows it healthy, the nginx reverse-proxy container can go
stale after the host sleeps or Docker Desktop's networking hiccups. Fix:
`docker restart appflowy-nginx-1`, then retry after a few seconds. This
happened once during 2026-07-08 validation and was the only infrastructure
issue found.

## Things intentionally still off

- Live job-board scraping (only manual paste or `--from-file` today).
- Gmail sync / auto-matching recruiter emails to applications.
- Sending any drafted message (recruiter reply, cover letter, LinkedIn note).
- `bot_possible` submission - MVP always routes to `Needs Geoff`.
- Resume/cover letter PDF or ATS-parseability checks (Markdown only so far).
- A CLI flag to override resume variant per job (workaround above).
