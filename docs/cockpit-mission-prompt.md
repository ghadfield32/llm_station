# Mission Prompt: First-Party Cockpit, Typed Visuals, Job Search End-to-End

Status: ready to run
Date: 2026-07-08
How to use: paste everything between the `BEGIN MISSION PROMPT` and `END MISSION PROMPT`
markers into a fresh Claude Code session opened at the repo root. Run the pre-flight
commands below first. A compact follow-up mission (external tool intake) is at the
bottom — run it only after this mission reports PASS.

## Pre-flight (run these yourself first)

```powershell
cd C:\Users\ghadf\vscode_projects\docker_projects\llm_station
git status --short          # expect the uncommitted job-search work; the mission commits it first
uv run cc doctor
uv run cc validate
uv run cc job-search --help # confirm the implemented subcommand surface
```

---

BEGIN MISSION PROMPT

You are working inside `C:\Users\ghadf\vscode_projects\docker_projects\llm_station`
(Command Center v4 — an LLM control plane, not a forecasting pipeline).

Mission: make the first-party `services/agent_kanban_ui/` the primary visual cockpit
with typed, domain-specific cards (jobs, LinkedIn posts, books, papers, repos, DAGs,
machine upkeep, missions), finish the job-search flow end-to-end inside it, make it
phone-usable over Tailscale, demote AppFlowy to an optional mobile/knowledge
projection, and leave behind setup + daily-use docs good enough for a new user.
Validate after every phase. Do not stop at implemented-but-untested.

## Verified repo facts (do not re-derive; verify only if something contradicts them)

- `configs/kanban_boards.yaml` is a provider-agnostic registry: each board declares
  `provider: appflowy | command_center_ui` with canonical statuses and an agent-verb
  contract (wall verbs forbidden). `betts_basketball` already runs on
  `command_center_ui`. Schema: `KanbanBoardSpec` in `src/command_center/schemas/contracts.py`.
- The kanban **event log is the source of truth** (`src/command_center/kanban_sync/`);
  AppFlowy is one write-through projection (`kanban_sync/projection.py`).
- Four separate inline AppFlowy httpx clients exist (no shared interface):
  `appflowy_kanban/growth-os/growthos/appflowy.py`, `src/command_center/job_search/board.py`,
  `src/command_center/cli/kanban_bridge.py`, `src/command_center/kanban_sync/projection.py`.
  `src/command_center/channels/board_state.py` reads boards via growthos actions.
- `services/agent_kanban_ui/` is a FastAPI + React/Vite/TS SPA (single container,
  FastAPI serves the built SPA). Views already built: Missions (Ledger kanban), Boards
  (snapshot/live + drag-to-move), Router (model lanes), Observability, Activity, and
  SSE Chat through GatewayCore. Gated by `configs/ui.yaml` (`agent_kanban_ui`,
  `enabled: false`, port 8787, loopback + password, `external_write_policy:
  governed_by_ledger`); chat/writes additionally behind `KANBAN_UI_CHAT_ENABLED=1`.
  It cannot approve/merge/deploy. Tracker: `docs/backend/projects/AGENT_KANBAN_SURFACE.md`.
- AppFlowy's REST API is insert/read-oriented: **no row delete, no view group-by
  setting, no select-option creation**; upstream bug #8665 = PUT row returns 200 but
  SingleSelect cells can silently stay empty. Blank "Untitled" cards in "No Status"
  are REST-created starter rows — documented in `docs/kanban-integration.md`,
  `docs/job_search/READINESS_FAQ.md`, and `board.py` (`blank_starter_rows` in
  board-doctor). The fix (delete rows, set Group by → Status) is **manual, human-only**.
- A LinkedIn-post preview renderer (`cc content-review --html`) already exists on
  branch `feat/desktop-action-latency-and-doctor`. Port it; do not rebuild it.
- Mobile access = Tailscale only (`docs/remote-access.md`): everything binds
  127.0.0.1, exposed via `tailscale serve`; **never `tailscale funnel`**.
- pytest needs the dev/fastapi extras installed (`uv sync` with the documented extras).
- Chat/tool model role is `chat` (qwen3:30b); qwen3-coder's parser leaks raw tool-call
  XML when prose precedes the call — keep chat surfaces on tool-safe roles
  (`tests/test_gateway_toolcall.py`, `tests/test_tool_safe_roles.py` if present).
- Real CLI surface (from `cc --help`): `validate`, `doctor`, `setup`, `onboard`,
  `verify-stack`, `start`, `open`, `kanban-verify/-register/-sync/-emit/-project/
  -verify-projection/-reconcile`, `operate verify --all`, `repo-register`,
  `repo-verify`, `demo`, `job-search`, `linkedin-publish`, `system-validation`,
  `agent-validation`, `live-smoke`, `appflowy-init`, `appflowy-up`, `lint`, `test`.
  Commands like `cc cockpit`, `cc ui-validate`, `cc knowledge-*` DO NOT exist — never
  invent commands; discover with `--help` and map validations onto what is real.

## Hard rules (non-negotiable)

- One control plane, one Ledger, one approval wall, one model gateway (LiteLLM), one
  GitHub merge wall. Add none of these a second time.
- AppFlowy never becomes execution authority; external board tools are watch-list only.
- Agents never approve, merge, deploy, publish, submit applications, send messages,
  bypass checks, or read secrets. `auto_submit_enabled` stays false (schema-rejected
  if flipped). Job materials require explicit Geoff selection.
- No provider API keys added to the core stack. Local-only provider boundary stays
  (`cc forbidden-providers`).
- `data/job_search/` stays gitignored; never commit private job/resume data.
- No silent passes: a missing service or env var is reported as DEGRADED/BLOCKED with
  the exact fix, never masked. Never fabricate validation results.
- Work on a feature branch; commit per phase with passing validation; never force-push.

## Phase 0 — Baseline, land pending work, environment reset

The working tree currently holds the ENTIRE job-search implementation uncommitted
(`configs/job_search.yaml`, `dags/job_search_daily.py`, `src/command_center/job_search/`,
`tests/job_search/`, `docs/job_search/`, modified `.gitignore`, schemas, CLI). Losing
it would lose days of work.

1. `git status --short`, `git diff --stat`, current branch, recent log. Read the diff
   of modified tracked files before anything else.
2. Run the job-search tests (`uv run pytest tests/job_search -q`) and `uv run cc validate`.
   Fix small breakage if present; then commit the pending work as one or more logical
   commits on the current branch (`feat/research-digest-intake-hygiene-main`) or a
   dedicated `feat/job-search-mvp` branch. Verify `git check-ignore -v` on a file
   under `data/job_search/` first so nothing private is staged.
3. Environment reset: `uv sync` with the documented extras, then
   `uv run cc doctor`, `uv run cc validate`, `uv run cc verify-stack`,
   `uv run cc setup`. Record what is READY vs BLOCKED (Docker, Ollama, LiteLLM,
   Ledger, AppFlowy env, Tailscale).
4. AppFlowy decision: if `APPFLOWY_*` env is unset, proceed WITHOUT it — nothing in
   this mission may block on AppFlowy. Record its status honestly.
5. Create the mission working branch for cockpit work.

Acceptance: pending work committed and pushed nowhere private; doctor/validate pass or
blockers listed with exact commands; baseline recorded in the final report skeleton
under `evaluation/system-validation/<run-id>/`.
Validation: `uv run cc doctor && uv run cc validate && uv run pytest tests/job_search -q && git diff --check`.
Rollback: phase is additive (commits + docs); revert the branch if validation fails.

## Phase 1 — Decision record + AppFlowy triage (small, fast)

1. Write `docs/reviews/2026-07-08-cockpit-decision.md`: first-party
   `agent_kanban_ui` is the primary cockpit; AppFlowy = optional mobile/knowledge
   projection; Plane REJECTED (verified July 2026: mobile apps require the Commercial
   Edition — not the AGPL CE; workflows = Business tier, approvals = Enterprise);
   AFFiNE rejected for now (open self-host mobile connection bugs; EE-licensed
   backend); Vikunja (alpha mobile), Focalboard (unmaintained), Huly (no mobile,
   heavy) rejected. No external board runtime.
2. Run the job-search board doctor (`uv run cc job-search --help` to find the exact
   subcommand; the logic is `board_doctor` in `src/command_center/job_search/board.py`).
   From its output write a short **operator checklist** into
   `docs/job_search/READINESS_FAQ.md` (or a linked section): delete blank starter
   rows in the AppFlowy UI, set Board Group by → Status, check
   `appflowy_kanban/growth-os/config/databases.json` for duplicate
   `job_search_pipeline` grids (8 blanks vs the expected 3/grid suggests a double
   creation). These are HUMAN-ONLY steps — list them, do not attempt them via API.

Validation: `uv run cc validate && git diff --check`. Rollback: docs-only.

## Phase 2 — BoardProvider abstraction

Goal: one shared interface so `command_center_ui` boards are fully functional without
AppFlowy, and AppFlowy stays a swappable projection.

1. Add `src/command_center/boards/` with `provider.py` (interface), `types.py`,
   `appflowy_provider.py` (wraps the existing client logic), and
   `command_center_provider.py` (full board state over the kanban event log).
2. Interface: list boards, get schema, list cards, upsert card, move card, set field,
   snapshot, validate, and `capabilities()` returning explicit flags —
   `supports_delete_row`, `supports_group_by_api`, `supports_select_option_create`,
   `supports_mobile_native`, `supports_custom_card_rendering`, `supports_live_sync`.
3. AppFlowy provider fails LOUD (typed unsupported-operation result, never a silent
   no-op) for row delete / group-by / select-option creation.
4. Migrate consumers incrementally behind the interface: `kanban_sync/projection.py`
   first (cleanest seam), then `kanban_bridge.py`, `job_search/board.py`,
   `channels/board_state.py`. The growth-os curator can stay as-is this mission.
5. Every existing command keeps working (`kanban-verify`, `kanban-project`,
   `kanban-verify-projection`, `kanban-reconcile`, job-search board commands).

Validation: `uv run cc validate`, `uv run cc kanban-verify`, `uv run cc kanban-project`,
`uv run cc kanban-verify-projection`, `uv run pytest tests/test_kanban_sync.py
tests/test_kanban_wiring.py tests/test_kanban_registry.py tests/test_agent_kanban_ui.py -q`,
`uv run cc lint`, `git diff --check`.
Rollback: keep the new interface feature-flagged and old paths intact if a consumer breaks.

## Phase 3 — Cockpit on by default

1. Flip `configs/ui.yaml` → `agent_kanban_ui.enabled: true`, read-only mode as the
   default; chat/writes stay behind `KANBAN_UI_CHAT_ENABLED=1`. If AppFlowy env is
   missing, the Boards view must load with an honest "AppFlowy projection unavailable"
   state — internal boards still render from the event log.
2. Do NOT add new `cc cockpit` commands — `cc start` / `cc open` already exist; extend
   `cc open` to include the cockpit URL and document it.
3. Write `docs/setup/COCKPIT_QUICKSTART.md`: one-command start (`uv run cc start`),
   local URL (http://127.0.0.1:8787), Tailscale exposure
   (`tailscale serve --bg --https=8787` on vengeance; never funnel), phone access via
   the tailnet URL, password location, and how to enable chat.
4. Update `docs/ui-options.md` to name the cockpit as the recommended surface.

Validation: start the service (docker compose profile or documented run path), then
`curl http://127.0.0.1:8787/api/status`, `/api/missions`, `/api/models`, and the
boards endpoint with AppFlowy env unset (expect DEGRADED, not empty-and-green);
`uv run pytest tests/test_agent_kanban_ui.py tests/test_kanban_ui_events.py
tests/test_board_state.py -q`; `uv run cc lint`; `git diff --check`.
Rollback: revert `ui.yaml` to disabled; docs still explain CLI usage.

## Phase 4 — Typed domains + polymorphic cards (the visuals; biggest phase)

1. Add a typed domain registry (`configs/domain_surfaces.yaml` + Pydantic schema, or
   extend the board registry if that is cleaner — pick one, record why). Domains:
   `job_application`, `linkedin_post`, `book`, `paper`, `repo`, `dag`,
   `machine_upkeep`, `mission`, `generic_task`.
2. Backend: `/api/domains`, `/api/domain/{id}/cards`, `/api/domain/{id}/card/{card_id}`,
   `/api/domain/{id}/actions` — served from event log/Ledger/registries, AppFlowy optional.
3. Frontend card components, one per domain, each with a typed detail drawer:
   - Job: company, role, fit score badge, salary, automation class, blockers, resume
     variant, JD summary, follow-up pack, communications timeline.
   - LinkedIn post: rendered post preview (port the `cc content-review --html`
     renderer from `feat/desktop-action-latency-and-doctor` via `git show`/cherry-pick
     — do not rebuild), account (Geoff/WMS), scheduled time, approval state, PostURN.
   - Paper: title/venue, abstract, notes, figure thumbnails when available, linked project.
   - Book: cover/title, progress, notes, tags.
   - Repo: branch, PR + checks, autonomy gates, last mission, sandbox status, risk tier.
   - DAG: last/next run, freshness, failure summary, owning repo.
   - Machine upkeep: checklists, service health, backup status.
   - Mission: Ledger events, approvals, risk, branch/worktree, validation evidence.
4. Design bar: one consistent visual system (spacing/typography/status colors), light
   and dark, real empty states per domain ("No jobs yet — run the daily DAG or
   `cc job-search suggest`"), filters (status, domain, repo, priority, text), and
   layouts that survive a 390px-wide viewport.
5. Ship at least one fixture card per domain (test fixtures, no private data) so every
   view renders something on a fresh install.

Validation: frontend production build succeeds; `uv run pytest
tests/test_agent_kanban_ui.py -q` plus new domain-surface tests; visual smoke — open
the cockpit, screenshot each domain view at desktop and phone width into
`evaluation/system-validation/<run-id>/screenshots/`; `uv run cc validate`;
`uv run cc lint`; `git diff --check`.
Rollback: domain surfaces behind a feature flag; generic board view keeps working.

## Phase 5 — Job search end-to-end in the cockpit

1. Register `job_search_pipeline` as a `command_center_ui` board in
   `configs/kanban_boards.yaml` (keep the AppFlowy entry as an optional projection —
   two board entries or a projection flag, matching Phase 2's design). Columns per
   `docs/job-search-command-center-plan.md`: Suggested Jobs → Selected by Geoff → In
   Progress → Needs Geoff → Completed → Interviewing → Rejected/Skip → Closed/Archived.
2. UI actions that call the EXISTING job-search core (no duplicated business rules):
   select, reject/skip, generate materials, mark needs-Geoff, mark submitted, add
   recruiter note, generate follow-up, archive. Selection is the approval gate:
   generation without selection must fail (negative test).
3. Fixtures: sports-analytics DS role, product DS role, analytics-engineer role.
4. Prove the loop with the real CLI: ingest-profile → suggest --from-file →
   (selection) → generate-materials → follow-up pack → retention --dry-run → digest.
   Use the actual subcommand names from `uv run cc job-search --help`.
5. Update the remaining unchecked TODOs in `docs/job-search-command-center-plan.md`
   to match reality (check off what this mission completes; leave honest ones open).

Validation: the CLI sequence above end-to-end; negative test (materials without
selection fails); `uv run pytest tests/job_search -q`; UI action tests;
`uv run cc validate`; `git diff --check`.
Rollback: CLI flow must keep working even if UI actions are reverted.

## Phase 6 — Repo/DAG/mission operations + chat clarity

1. Repo surface: registered repos from the repo registry with autonomy gate status
   (`cc repo-verify` results), merge-wall posture, GitHub App status, recent missions,
   PR/check state. `llm_station` must appear; `betts_basketball` if configured.
2. DAG surface: last/next run, status, failure summary per DAG (Airflow if reachable,
   else honest "scheduler not running").
3. UI action: draft a mission card (goes through `mission_intake`/kanban-emit — never
   self-approved). No approve/merge/deploy control may exist on any agent surface.
4. Chat: uses GatewayCore only; model roles from configs (chat/planner/coder — chat
   stays on the tool-safe `chat` role, NOT qwen3-coder); executors shown honestly
   (Claude Code primary, Codex fallback, Ollama local, Hermes optional, Gemini
   unavailable unless configured). Chat can explain boards, draft missions, summarize
   jobs, inspect repo/DAG state; it cannot approve/merge/submit/send.

Validation: `uv run cc repo-verify --repo self`, `uv run cc demo full-loop` (read-only),
`uv run cc operate verify --all`, `uv run cc agent-validation`, `uv run pytest
tests/test_gateway_toolcall.py tests/test_agent_kanban_ui.py -q` (+
`tests/test_tool_safe_roles.py` if present), `uv run cc live-smoke` if models are up,
`git diff --check`.
Rollback: repo/DAG surfaces read-only if verification fails; disable UI chat if it
cannot validate safely.

## Phase 7 — PWA / mobile polish

1. Add `manifest.webmanifest` + icons + a service worker that caches STATIC ASSETS
   ONLY — never API payloads (private data must not persist offline).
2. Mobile layout pass: bottom/collapsible nav, large touch targets, tap alternatives
   to drag (move-to-column menu), full-screen drawers on phone.
3. Document install-to-home-screen over the tailnet URL in COCKPIT_QUICKSTART.
4. AppFlowy remains the optional native-mobile fallback; say so in the docs.

Validation: frontend build; mobile-viewport check (Playwright if present, else
manual screenshots at 390px into the evidence dir); verify the service worker never
caches `/api/*`; `uv run pytest tests/test_agent_kanban_ui.py -q`; `git diff --check`.
Rollback: remove the service worker, keep responsive web.

## Phase 8 — Docs, TODO sync, final end-to-end proof

1. Docs (discover exact existing filenames under `docs/setup/` and `docs/operations/`
   first; update in place, create only what is missing): getting-started/setup-from-
   scratch (clone → install uv/docker/ollama → `uv run cc doctor` → `uv run cc
   bootstrap-local` → `uv run cc validate` → `uv run cc start` → open cockpit),
   adding a repo (`cc onboard repo` / `cc repo-register`), adding a board/domain
   (`cc onboard kanban` / `cc kanban-register` + domain registry entry), operations
   runbook, and the "choose your board mode" section (recommended: first-party
   cockpit; optional: AppFlowy projection; not recommended: external board runtimes).
2. Daily workflow (open cockpit → review jobs/posts/missions → select jobs → review
   materials → approve missions manually) and weekly workflow (doctor, validate,
   retention dry-run, self-improvement-report, usage-digest) written down.
3. TODO sync: reconcile `docs/job-search-command-center-plan.md` checkboxes,
   `docs/MASTER.md` status sections, and any stale claims touched by this mission.
4. Final matrix — run ALL of: `cc doctor`, `cc validate`, `cc verify-stack`,
   `cc kanban-verify`, `cc kanban-verify-projection`, `cc operate verify --all`,
   `cc repo-verify --repo self`, the job-search CLI sequence, `cc linkedin-publish
   --preflight` (expect BLOCKED on OAuth — that is honest, not a failure),
   `cc system-validation`, `uv run cc test` (full suite), `uv run cc lint`,
   `git diff --check`. Any unavailable command: report name, nearest real
   replacement, blocker or not, next action.
5. Manual visual checklist for Geoff (10 items): cockpit opens locally and over
   Tailscale; missions render; every domain card renders; job cards show fit/salary/
   blockers; post preview looks like LinkedIn; repo/DAG cards show health; phone
   width works; PWA installs; AppFlowy absence degrades gracefully; no agent-facing
   approve/merge/deploy/submit control anywhere; chat streams and refuses unsafe asks.
6. Deliverables: `evaluation/system-validation/<run-id>/FINAL_REPORT.md` (+
   `commands.json`, screenshots) with PASS / PASS_WITH_BLOCKERS / FAIL, files changed,
   command results, what works, what is intentionally disabled, remaining blockers
   with exact next commands, the operator checklist from Phase 1 (manual AppFlowy
   fixes), and the exact daily/weekly workflows.

## Stop condition

Stop only when: (1) the cockpit runs and renders every domain with typed cards,
(2) job search works end-to-end with the selection gate proven by a negative test,
(3) AppFlowy is optional everywhere and its manual fixes are documented for the human,
(4) mobile/PWA access over Tailscale is documented and smoke-checked, (5) all
validations in the final matrix ran or are listed as explicit blockers, (6) setup +
operator docs and the plan-doc TODOs are updated, (7) no safety boundary changed.
If genuinely blocked on something only Geoff can do (AppFlowy manual cleanup,
LinkedIn OAuth, Tailscale on the phone), finish everything else and list those as the
only remaining items.

END MISSION PROMPT

---

## Follow-up mission B (run later, separately): external tool intake

Small, separate mission — do not bundle it into the cockpit work. Paste this after
mission A reports PASS:

```text
In llm_station: record external-tool verdicts through the EXISTING research intake
(cc research-digest + its source catalog; docs/watch-list/ and docs/reviews/).
Verdicts: karpathy-llm-wiki = adopt_pattern_in_knowledge_layer;
apache-airflow-providers-anthropic = conditional_adopt (docs + a disabled example DAG
only if Airflow 3+ is actually installed; no provider keys in core; batch/L0-L1 only);
stablyai/orca, alookai/alook, omnigent-ai/omnigent = borrow_pattern_only (write one
short pattern doc each under docs/architecture/ or docs/reviews/);
teamchong/pxpipe = pilot_only (docs/reviews/pxpipe-pilot-plan.md with strict
exclusions: never hashes, IDs, secrets, schemas, migrations, eval gold data, security
reviews). Install NOTHING as a runtime dependency. Validate with cc validate,
cc research-digest (report mode), pytest for research/discovery tests, cc lint,
git diff --check. Update MASTER.md's watch-list section. Stop when catalog rows
validate and docs exist.
```
