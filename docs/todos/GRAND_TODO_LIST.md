# GRAND TODO LIST — Master Tracker (all of life)

This file is the canonical master todo tracker for **everything** — Command
Center / kanban work, job search, socials, Betts Basketball, computer-vision
projects, and personal life admin. It lives in `llm_station` because the
Command Center is the control plane that routes, tracks, and executes todos.

Every tracked item carries a **Repo:** designation naming the repository (or
`personal`) where the work happens, so agents know exactly which registered
folder to work in and never traverse outside it.

The Betts Basketball detail tracker remains canonical for Betts items:
`betts_basketball/docs/backend/projects/GRAND_TODO_LIST.md` (projected to the
`betts_basketball_grand_todo` board). This master list designates and links it
rather than duplicating its ~150 items — one canonical file per repo, no drift.

## How to use this file

- Tracked items use stable IDs (`KAN-1`, `PROC-3`, …). The importer projects
  each item to a card on the `grand_todo` board; the Markdown stays canonical.
- Item format: `#### ID · Title`, then a tracking line
  `` `STATUS` · **Target:** … · **Done:** … ``, then `**Repo:**`,
  `**Priority:**`, `**Source:**`, and `**Notes:**`.
- Statuses: `💡 IDEA`, `📋 PLANNED`, `🚧 WIP`, `🚀 SHIP-TAIL`, `⛔ BLOCKED`,
  `✅ DONE`, `📦 ARCHIVED`, `🔁 RITUAL`.
- **Repo:** one of `llm_station`, `betts_basketball`,
  `bball_homography_pipeline`, or `personal`. New repos must be registered
  with the Command Center (see KAN-2) before agents may work in them.
- **Priority:** `P1` (working now) / `P2` (next) / `P3` (later) / `_TBD_` —
  initial values from the 2026-07-23 migration are suggestions; adjust freely.
  Business impact and timeline fields roll out with KAN-12.
- Working a todo end-to-end follows [`TODO_PROCESS.md`](TODO_PROCESS.md):
  todo → designated repo/folder + run-doc → clarifying questions (KPI-meeting
  style) → mission setup → monitored execution → multi-LLM panel review → done.
- Raw, un-triaged input goes to the [Idea Bank](#idea-bank) or the
  [Intake Queue](reference/INTAKE_QUEUE.md); never delete information —
  reference docs and `**Source:**` lines preserve provenance.

## Category tree (navigation)

- **KAN** — Kanban / Cockpit platform (`llm_station`)
- **AGT** — Agents, models & evaluation (`llm_station`)
- **PROC** — Todo→Project process & standards (`llm_station`)
- **JOBS** — Job search & career (`llm_station`)
- **SCL** — Socials, content & business (`llm_station`)
- **BB** — Betts Basketball (`betts_basketball` — detail lives in its tracker)
- **CVP** — Court CV / homography pipeline (`bball_homography_pipeline`)
- **LIFE** — Personal, home & errands (`personal`)
- Reference lists: [Media Watchlist](reference/MEDIA_WATCHLIST.md) ·
  [Reading List](reference/READING_LIST.md) ·
  [Home & Maintenance](reference/HOME_MAINTENANCE.md) ·
  [Intake Queue](reference/INTAKE_QUEUE.md)

## KAN — Kanban / Cockpit Platform

Repo default: `llm_station`. The cockpit (agent_kanban_ui) and its backend.

#### KAN-1 · Job boards organized by step, main docs linked at top
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L1 (2026-07-23 migration)
**Notes:** "The job boards should be all based on the steps they are in so it's not over cluttered. We should organize it so the main docs are easily adjusted via a link at the top and then the steps would just be there to show the overall and if we want we can click into those steps and see the actions taken for each so we can have this broken down linearly and easily adjusted."

#### KAN-2 · Repo-scoped agent workspaces — registered folders are the whole search space
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P1
**Source:** soon_to_be_deleted_todos.md L2 (2026-07-23 migration)
**Notes:** Kanban agent search scope is far too wide. The designated/registered folders must be all an agent can work with, and newly added repositories must be registered with the kanban so agents instantly know them. Goal: never again see "Those timed out — the home directory tree is too large… Directory traversal keeps timing out (the tree is huge)." Includes registering `bball_homography_pipeline` (currently unregistered — only `llm_station` and `betts_basketball` are in `configs/autonomy.yaml` `repo_manifests`).

#### KAN-3 · Load performance + zero "Load failed" (boards, notes, router, app-switch)
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P1
**Source:** soon_to_be_deleted_todos.md L9 (2026-07-23 migration)
**Notes:** Notes-to-books loads take forever; switching between boards takes forever; boards fail when leaving the app (must be smooth across app switches — PWA lifecycle); switching back and forth shows "boards: Load failed"; "router: load failed" seen entering the Life Center. Definition of done: those errors never surface and board/notes navigation feels instant. **Run-doc (2026-07-23, root cause verified):** [docs/projects/kan-3-load-performance/RUNDOC.md](../projects/kan-3-load-performance/RUNDOC.md) — `reloadBoards`/lanes null out last-good data on any transient fetch rejection and print the raw WebKit "Load failed" message; fix = keep-last-good + error classification + visibilitychange refetch; latency measured before optimized. Awaiting §5 KPI-meeting answers to start execution.

#### KAN-4 · Fit-to-screen layout everywhere (mobile + desktop)
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L9 (2026-07-23 migration)
**Notes:** Everything must fit the screen: the chat dropdown in the chat is way too wide; page width should be screen-wide for mobile and web.

#### KAN-5 · Books surface: one combined search + dropdown control
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L9 (2026-07-23 migration)
**Notes:** The search bar and dropdown for books should be the same control rather than two separate ones; also covers the slow notes→books load path (with KAN-3).

#### KAN-6 · Global search bar to find boards fast
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L9 (2026-07-23 migration)
**Notes:** A search bar at the top to find kanbans faster.

#### KAN-7 · "+" add-board button with self-added, fully editable template
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L9 (2026-07-23 migration)
**Notes:** A + button at the end of the boards so we can add on; it self-adds the kanban template with complete edit ability. (BoardModuleSpec wizard workstream is the natural seam.)

#### KAN-8 · Card actions: single "Open in chat" + small model dropdown
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L9 (2026-07-23 migration)
**Notes:** Boards should only have "Open in chat"; remove "Ask Claude" and "Ask Codex"; include a small dropdown next to Open in chat to pick/set up a model easily.

#### KAN-9 · Notes: add/delete anywhere, delete restricted to human users
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L9 (2026-07-23 migration)
**Notes:** Be able to delete or add notes as wanted; only allow deleting of notes if it's me or a (human) user — agents never delete.

#### KAN-10 · Board position memory — easy way back from cards
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L9 (2026-07-23 migration)
**Notes:** Have an easy way to get back to where you were in the board from the cards.

#### KAN-11 · Todo→project intake flow in the board (run-doc + questions + voice)
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P1
**Source:** soon_to_be_deleted_todos.md L9 (2026-07-23 migration)
**Notes:** When a todo first becomes a kanban project, the system should produce the full run-doc and ask the questions needed to fulfil it (KPI-discussion style, before any work in the wrong direction). The user answers easily — voice or anything. Once assembled it offers to move the card to In Progress, then starts the chat/process; we can step in at any point and it asks questions along the way. UI counterpart of PROC-3; process contract in [`TODO_PROCESS.md`](TODO_PROCESS.md).

#### KAN-12 · Priority system + priority viewer (priority / business impact / timeline)
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P1
**Source:** soon_to_be_deleted_todos.md L18 + L50 (2026-07-23 migration)
**Notes:** Everything is created with level of priority, business impact, and timeline. A priority viewer sits at the top of everything, filters as each board is selected, is adjustable by priority level, and is searchable for quick interaction. Include areas-of-life filters (home/study/work/portfolio/self-work/jobs/books/etc.) and an algorithm to make the most of every day.

#### KAN-13 · Chat repository setter — dropdown preselect/add + in-chat confirmation
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L14 (2026-07-23 migration)
**Notes:** Update the repository setter in the chat: an easy dropdown for preselected repos or add a new one; the chat should simply show that the registered repo was updated.

#### KAN-14 · Registered-repo git options: init new repo, or git skills + standing reviewer
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L15 (2026-07-23 migration)
**Notes:** Registered repos get the option to be made into a new git repo, or to have git skills so agents can review and use git history per project — structured and safe, best practices, with a reviewer always in place.

#### KAN-15 · Agent sessions in kanban chat: env fix + auto-engage on select
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L56 (2026-07-23 migration)
**Notes:** Fix `KANBAN_UI_AGENT_SESSIONS_ENABLED=1` in `.env` for Codex and Claude; have them normally set up in the chat and auto-engage when selected. Complete the LLM setup entirely so tasks run with the combination of models (feeds AGT-10).

#### KAN-16 · Idea intake router — ideas auto-land on the right board with a full packet
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L63 (2026-07-23 migration)
**Notes:** Submit ideas for posts/papers/todos (daily batch or on the spot); the system detects which kanban each belongs to from my idea list, researches it, creates the task/board entries, and I verify or adjust via chat. The chat helps assemble a full packet ahead of time — run-doc thinking, everything listed — and it is re-reviewed through our chain of LLMs before launching the task.

#### KAN-17 · Top-level security + local-first storage for docs and boards
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L66 (2026-07-23 migration)
**Notes:** Top-level security (and local keeping, with upgrade available to cheapest space) for the LLM-station documents and boards so it all feels secure.

#### KAN-18 · LLM leaderboard as a board — reviewable any time, always current
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L77 (2026-07-23 migration)
**Notes:** Surface the KPI leaderboard (champion/challenger results) as its own board. Pairs with AGT-12.

#### KAN-19 · Watch/track boards — authors, repos, papers, posts with suggestions
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L78 (2026-07-23 migration)
**Notes:** Update repos/papers/books kanbans to track chosen authors/repos going forward; the daily run picks up updates and suggests who to follow in fields the user picks. Allow post input so submissions go through reviews (possibly their own user section like jobs).

#### KAN-20 · Self-improvement board — process reporting + recommendations → missions
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L79 (2026-07-23 migration)
**Notes:** A self-improvements kanban board reporting the process and showing recommendations we can continue with, or we input our own from repos/papers/DAGs; it creates a mission the same as any request and we follow along. (The daily self-improvement report pipeline already exists — this surfaces it as a board.)

#### KAN-21 · Space/usage audit DAG across R2, Railway, local + capacity alert emails
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L81 (2026-07-23 migration)
**Notes:** Auto-check DAG on spacing/usage across R2, Railway, local, and anywhere else; report savings strategies so bills stay low; red-flag alert emails for capacity issues so anything wrong triggers an immediate email.

#### KAN-22 · Books board seeded from the Reading List
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L84 (2026-07-23 migration)
**Notes:** Add the book list to the kanban board — seed from [`reference/READING_LIST.md`](reference/READING_LIST.md) (phases, priority routes, currently-reading).

#### KAN-23 · Timeline reminders + mobile app signup portion
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L88 (2026-07-23 migration)
**Notes:** Add timeline reminders to the kanban and complete the mobile-app portion for easy signup.

#### KAN-24 · Master grand-todo board: full cockpit parity (sync UI, source editor, write-through moves)
`🚀 SHIP-TAIL` · **Target:** 2026-07-23 · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P1
**Source:** 2026-07-23 migration follow-up (this file)
**Notes:** Implemented 2026-07-23 by Codex gpt-5.6-sol in an isolated worktree (branch `feat/kan-24-grand-todo-ui-parity`, commit 3e54a24) per [docs/projects/kan-24-grand-todo-ui-parity/RUNDOC.md](../projects/kan-24-grand-todo-ui-parity/RUNDOC.md): parameterized sync/edit endpoints + all cockpit gates over both boards; 174 tests green, build green, literal KPI met; independent Fable review APPROVED. Tail: operator merges the branch and rebuilds the cockpit to ship the new bundle. First feature todo through the full TODO_PROCESS loop (with PROC-1).

#### KAN-25 · Restore main CI to green (12 pre-existing lint-test failures)
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P1
**Source:** discovered 2026-07-23 while shipping PR #74
**Notes:** main's `contracts` workflow has been red since 2026-07-17 (4 consecutive runs). 12 failures in 4 families, none from the grand-todo work (PR #74 fixes one, adds zero): (1) `test_agent_kanban_ui_capture_convert` ×5 — capture-convert's private-history sub-request resolves container-default paths (`/app/generated/.locks`, `PermissionError: /app`) on the Linux runner; (2) `test_agent_kanban_ui_usage` — `KeyError: 'glm-5.2'` fixture drift; (3) `test_agent_pickers` — `_build_args()` signature drift vs the stdin chat fix; (4) `test_agent_session_service` ×5 — approval/event-order assertions. A red main gate undermines every verification loop — fix before further merges. Evidence: runs 30032453677 (PR) vs main run same-day; failure sets identical minus the domain-pin fix.

## AGT — Agents, Models & Evaluation

Repo default: `llm_station`. Model allocation, agent quality, evaluation.

#### AGT-1 · Agents CLI for kanban metrics
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L3 (2026-07-23 migration)
**Notes:** Check out the agents CLI for the kanban and ensure we use it for the metrics that help us better answer. Link: https://fff97757.click.kit-mail3.com/mvu2e6knk0b5hq4039vtmhrenrgz8c3h5ed66/9qhzhnhdoxq835a9h3/aHR0cHM6Ly9mYW5kZi5jby8zUjVsVzB0 **Research verdict (2026-07-23):** the link is an influencer-agency shortlink (unpinnable); best candidate = **AgentsView** (kenn-io/agentsview, MIT, mature) — TRIAL read-only as a validator for our usage.v1 numbers; pattern-mine caut's `caut.v1` quota schema. Details: [RESEARCH_NOTES_2026-07.md](reference/RESEARCH_NOTES_2026-07.md).

#### AGT-2 · Evaluate "Aiden" (open-source AI operating system) for the kanban
`✅ DONE` · **Target:** _TBD_ · **Done:** 2026-07-23
**Repo:** `llm_station`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L4 (2026-07-23 migration)
**Notes:** https://www.linkedin.com/posts/alvaro-cintas_theres-a-new-full-open-sourced-ai-operating-share-7483599852195622913-fUW5/ **Research verdict (2026-07-23): SKIP adoption** (taracodlabs/aiden — AGPL-3.0 core, single maintainer, heavy overlap with Command Center). Pattern-mine 4 ideas: tiered approval risk levels; failure-classification + verify-outcome loop; memory distillation/graduation; trigger bus. Details: [RESEARCH_NOTES_2026-07.md](reference/RESEARCH_NOTES_2026-07.md).

#### AGT-3 · Harness score — grade our LLM systems on the kanban
`🚧 WIP` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L7 (2026-07-23 migration)
**Notes:** Use harness score to grade our LLM systems on the kanban. https://www.linkedin.com/posts/fernandopaladini_harnessengineering-aicoding-cursor-ugcPost-7483472351603503104-Lzen/ — feeds the AGT-12 completion-KPI leaderboard. **Research + BASELINE (2026-07-23):** it's paladini/harness-score (MIT) — a repo-readiness scanner (NOT task quality). Baseline run: **63/108 (58%), L1 "Documented"** — Sensors 20/20, Hygiene 23/23, CI 11/14, Context 9/20, **Skills 0/17, Hooks 0/14**; next-level gaps: context ≥60%, skills or hooks ≥30%. Evidence: [baseline JSON](../projects/agt-3-harness-score/baseline-2026-07-23.json). Task-quality grading belongs to AGT-12 via METR-style task standards. Advisory only, never a gate.

#### AGT-4 · Copilot as a kanban agent option
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L10 (2026-07-23 migration)
**Notes:** https://www.linkedin.com/posts/rorypreddy_msft-ai-microsoft-share-7483794621219721216-znuA/ **Research verdict (2026-07-23): TRIAL.** Copilot CLI is GA (2026-02) with a true headless mode (`copilot -p "..." -s --no-ask-user --allow-tool=...`), PAT auth (`COPILOT_GITHUB_TOKEN`, "Copilot Requests" permission), multi-model. Viable third agent runtime beside Claude Code + Codex. Caveats: proprietary, per-prompt billing, flag churn (pin CLI versions). First step: read-only adapter behind the same wall as the Codex adapter + rerun the 14-case acceptance. Details: [RESEARCH_NOTES_2026-07.md](reference/RESEARCH_NOTES_2026-07.md).

#### AGT-5 · STORM researcher add-on — pre-research todos and fill in details
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L11 (2026-07-23 migration)
**Notes:** Check out STORM as a researcher add-on so it does the research ahead of time for any todo and fills in details, making everything as easy as possible. Natural engine for the PROC-3 run-doc research stage. **Research verdict (2026-07-23): TRIAL.** stanford-oval/storm — MIT, ~30.3k★, LiteLLM-native since v1.1.0 (points at our own gateway/Ollama); pre-writing output (cited refs + outline) ≈ a run-doc skeleton. Risks: local-model quality unproven, release cadence stalled, needs a retrieval backend (DuckDuckGo/SearXNG keyless). First step: scratch-venv trial on ONE real board todo. Details: [RESEARCH_NOTES_2026-07.md](reference/RESEARCH_NOTES_2026-07.md).

#### AGT-6 · Audit our kanban agentic pipeline against the 2026 AI-agents guide
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L22 (2026-07-23 migration)
**Notes:** https://www.linkedin.com/posts/how-to-build-ai-agents-updated-2026-guide-share-7483626518561308672-OQ0B/ — ensure the pipeline is the best it can be. **Research verdict (2026-07-23): ADOPT as audit rubric.** Best-substantiated source: Perrone "The AI Agents Stack (2026 Edition)" (O'Reilly Radar 2026-06). 5-practice audit: three-tier evals per surface; authorize-before-action at the tool layer; observability≠evals gap hunt; history-first memory audit; right-sized orchestration. Next: one-session gap audit → gap list on the board. Details: [RESEARCH_NOTES_2026-07.md](reference/RESEARCH_NOTES_2026-07.md).

#### AGT-7 · Add open-sourced "Claude design" to the open-source setup
`✅ DONE` · **Target:** _TBD_ · **Done:** 2026-07-23
**Repo:** `llm_station`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L23 (2026-07-23 migration)
**Notes:** https://www.linkedin.com/posts/ole-lehmann-918a6094_lol-someone-already-open-sourced-claude-design-share-7482938344658587648-Ivzr/ **Research verdict (2026-07-23): SKIP as dependency** — the project is **Open Design** (nexu-io/open-design, Apache-2.0, ~81k★): a design-generation product driven by your existing coding agent, NOT a Claude-style component library; license clean. Pattern-mine: daemon-spawns-agent-CLI/session-resume architecture + the portable DESIGN.md design-system convention for cockpit visual language. Details: [RESEARCH_NOTES_2026-07.md](reference/RESEARCH_NOTES_2026-07.md).

#### AGT-8 · Set up jlnsrk/GLM-5.2-colibri-int4 (Hugging Face)
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L51 (2026-07-23 migration)
**Notes:** Candidate for the model watchlist / dual-budget fit check before pulling.

#### AGT-9 · Upgrade kanban work checks with agent observability
`💡 IDEA` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L53 (2026-07-23 migration)
**Notes:** https://www.linkedin.com/posts/alindnbrg_aiengineering-codingagents-observability-share-7483128665170595840-hSCb/

#### AGT-10 · Best-combination model allocator (hardware/subscription/usage-aware)
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L57 (2026-07-23 migration)
**Notes:** The best combination of models gets the best answers in the best roles for each task, fitted to the user's hardware, continuously accounting for usage, usage end dates, and available models — always the best combination for any kanban task, watching itself as we move forward. Auto-adjust to people's systems and subscriptions (fill env variables or login to Claude/GPT etc.); quick and auto-adjusting to the goaled tasks. Builds on the unified usage/limits layer (PR #34 workstream).

#### AGT-11 · Daily Codex cross-review ritual in the workflow
`🔁 RITUAL` · **Target:** _ongoing_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L67 (2026-07-23 migration)
**Notes:** Have Codex analyze moves occasionally as we code in Claude; use the Codex plugin for Claude for easy cross-reviews. Codex runs high/medium to code while Claude plans deep sessions, keeps relevancy current, and does defensive-coding checks at the end. https://github.com/openai/codex-plugin-cc — already partially standing policy in CLAUDE.md; make it a checked ritual.

#### AGT-12 · Task-completion KPIs + system-vs-Codex/Claude leaderboard
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L82 (2026-07-23 migration)
**Notes:** New task-completion metrics for the kanban (actual completion, defensive coding added along the way, ecosystem strengthening, extra real issues tackled vs created, abstraction level, efficiency, steps taken, …) to benchmark our OpenRouter loop against Claude Code and Codex on full-loop project scores. Build the leaderboard, improve until it beats Codex, then track how long until small open-source models do the same. Runs as the standard KPI leaderboard loop; AGT-3's harness score is a candidate KPI.

## PROC — Todo→Project Process & Standards

Repo default: `llm_station`. The consistent pipeline every todo goes through.
Contract: [`TODO_PROCESS.md`](TODO_PROCESS.md).

#### PROC-1 · Prove one todo end-to-end through the full loop
`🚀 SHIP-TAIL` · **Target:** 2026-07-23 · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P1
**Source:** soon_to_be_deleted_todos.md L13 (2026-07-23 migration)
**Notes:** PROVEN 2026-07-23 with KAN-24 as the first feature todo through every stage: capture → repo designation → run-doc → KPI-meeting questions (operator-approved packet) → mission (Codex gpt-5.6-sol write-mode, isolated worktree) → monitored execution (mid-flight on-plan check; hung-pipe incident recovered) → deterministic verification (174 tests, build) → independent panel review (Fable, non-author, APPROVED) → evidence-gated close. Tail: operator merge = the final "done" gate, by design. Process lesson logged in the KAN-24 RUNDOC (no wrapper timeout shorter than the verify phase). Next through the loop: KAN-3.

#### PROC-2 · Every new todo gets its own up-to-standards doc
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P1
**Source:** soon_to_be_deleted_todos.md L16 (2026-07-23 migration)
**Notes:** Every new todo gets an up-to-standards doc we can later link to other docs for other projects. Template and location convention defined in [`TODO_PROCESS.md`](TODO_PROCESS.md) (§ Run-doc).

#### PROC-3 · Todos→projects template: docs scaffold + standards doc + review chain + card links
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P1
**Source:** soon_to_be_deleted_todos.md L24 (2026-07-23 migration)
**Notes:** "For todos becoming projects (most of them), they should have a template that sets up the docs folder if it's not already within the registered folder and with the organization and then set up a doc completely up to standards that we can continue to add onto and adjust and update as we do more about the project and add more todos relating to that project, every time we add something it should have a full review to ensure it's helpful/organized and added correctly and up to standard/and a plan we can add a link to into the card for the todo as well as a link to the doc so we can continue and keep up with this and go and chat with the doc and update it myself anytime within the chat. Once we have this set, continue to ensure that we are up to standards, have the best ones for continued success and reiteration to ensure we are always doing this the best possible based on our successes and fails, ensure it can be done in one area so it's easy and we can do it ourselves in the todo list also."

#### PROC-4 · Grand-todo migration — master list in llm_station, Betts list stays in Betts
`🚀 SHIP-TAIL` · **Target:** 2026-07-23 · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P1
**Source:** soon_to_be_deleted_todos.md L83 (2026-07-23 migration)
**Notes:** Move notes and todos over to the grand todo lists, then add the grand todo list to the kanban board so we can start working through it. This migration created this file, the reference docs, the intake queue, the `grand_todo` board, and the process doc. Remaining: KAN-24 (cockpit parity), BB-3 (Betts intake reconciliation), operator deletion of `soon_to_be_deleted_todos.md` once verified.

## JOBS — Job Search & Career

Repo default: `llm_station` (job-search pipeline + boards live here).

#### JOBS-1 · Proactive job submissions with a quick human review
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P1
**Source:** soon_to_be_deleted_todos.md L17 (2026-07-23 migration)
**Notes:** Proactive job submissions: it just sends me a link and a brief list, and I go over them quickly in a quick review showing everything they (the employer) will see. Submit remains validation-gated and human-approved (existing packet-review loop).

#### JOBS-2 · Application walkthrough mode — page by page together
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L45 (2026-07-23 migration)
**Notes:** Make the kanban job hunt have a go-through-application-with-you setup so we can work through it one by one, page by page together if wanted.

#### JOBS-3 · LinkedIn follow-ups + recommended connections on the job board
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L46 (2026-07-23 migration)
**Notes:** The kanban should include follow-up messages to people we actually know on LinkedIn and recommended people to connect with on LinkedIn.

#### JOBS-4 · Company watch add-on
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L47 (2026-07-23 migration)
**Notes:** An easy company-search add-on that keeps up with whatever companies you want.

#### JOBS-5 · Question bank — learn from questions we can't answer
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L48 (2026-07-23 migration)
**Notes:** Learns from application questions we can't answer, adds them to our collection with typical answers for different job types.

#### JOBS-6 · Applied-jobs database — 30-day retention (adjustable) unless furthered
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L49 + L89 (2026-07-23 migration)
**Notes:** Keep a bare database of jobs applied to (lasting 30 days, adjustable) unless we mark that a communication furthered the process. Track what we applied with and basic details for next steps if actioned.

#### JOBS-7 · Within-reach job filtering + project-skill evidence
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L55 (2026-07-23 migration)
**Notes:** The job search should only find jobs within the person's preview or within reach (switchable on/off, e.g. for a kid), but still include skills from projects to show they deserve the job.

## SCL — Socials, Content & Business

Repo default: `llm_station` (LinkedIn content engine, publishers).

#### SCL-1 · Socials hub — all networks, notifications, respond/post from the app
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L9 (2026-07-23 migration)
**Notes:** Add the ability to keep up with any and all socials via this app; easy to use; keeps up with notifications in all of them and responds or posts accordingly. Research open-source projects that already do multi-social management before building. **Research verdict (2026-07-23): TRIAL Postiz** (gitroomhq/postiz-app, AGPL, 33.7k★) as the multi-network **publishing** arm behind our approval gate — real REST API, but NO inbound/notifications API. **Hard constraint from LinkedIn itself:** comment/engagement reading needs the Community Management API, granted only to registered legal entities (ties to SCL-4 business registration). Mixpost Pro ($299 one-time) has the only shipped unified inbox — conditional later. Brightbean too young; Ayrshare closed. First step: docker-compose Postiz + publish ONE approved draft via API vs `cc linkedin-publish`. Details: [RESEARCH_NOTES_2026-07.md](reference/RESEARCH_NOTES_2026-07.md).

#### SCL-2 · Post enterer (LinkedIn-style) for the post board
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L58 (2026-07-23 migration)
**Notes:** Create a post enterer like LinkedIn's for the post-board setup.

#### SCL-3 · 30 days of content (me + company) + weekly creation alert + scheduled posts
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L107-109, L172 (2026-07-23 migration)
**Notes:** LinkedIn completely prepared for posting the next 30 days (me + company): ESEA post, research-paper posts. Weekly alert to create more; kanban agents can create and propose drafts; scheduled posts at traffic times with a pre-publish check on LinkedIn. Drafts remain human-approved before publish (existing content-board gate).

#### SCL-4 · Business + LinkedIn founder updates, verification, ESEA readiness
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `llm_station`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L112, L128, L168 (2026-07-23 migration)
**Notes:** Update LinkedIn with CEO/founder and get the first posts out for company and me; follow up on business creation, finish LinkedIn verification, have content prepped to hit the ground running with ESEA acceptance; check on the LinkedIn community API.

## BB — Betts Basketball

Repo: `betts_basketball`. Detail tracker is canonical:
`betts_basketball/docs/backend/projects/GRAND_TODO_LIST.md`
(board `betts_basketball_grand_todo`, ~150 items across DE, MOD, PV, PR, TR,
TS, CO, RF, LN, SIM, XFG, CV, VID, LLM, FE, ACC, BET, INFRA, SOC, DOC, MLB).
New Betts todos land here or in the Intake Queue, then get reconciled into the
Betts tracker — never tracked in two canonical places at once.

#### BB-1 · Betts tracker upkeep — work Betts todos from the Betts board
`🔁 RITUAL` · **Target:** _ongoing_ · **Done:** _—_
**Repo:** `betts_basketball`
**Priority:** P2
**Source:** 2026-07-23 migration (this file)
**Notes:** The Betts list stays just for Betts. Sync with `uv run cc grand-todo-import --apply`; work items via the `betts_basketball_grand_todo` board. This master item exists so the whole of life is visible from one tracker.

#### BB-2 · Beyond forecasting: causality checks + improvement engine
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `betts_basketball`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L19 (2026-07-23 migration)
**Notes:** Models are currently only for forecasting and explaining forecasts. Two directions: (1) create ways to improve above and beyond expectations — the biggest value isn't forecasting, it's improving teams/players/coaches/GMs/owners past what the forecast shows; (2) causality checks. Reconcile into the Betts tracker as its own category (candidate: a "beyond-forecast improvement" section next to TS/world-model work).

#### BB-3 · Reconcile Intake Queue Betts bullets into the Betts tracker
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `betts_basketball`
**Priority:** P2
**Source:** 2026-07-23 migration (reference/INTAKE_QUEUE.md L59-226 region)
**Notes:** Most bullets in [`reference/INTAKE_QUEUE.md`](reference/INTAKE_QUEUE.md) source-lines 59-174 and 211-226 are Betts site/pipeline work (many already tracked there — e.g. draft lottery, trade history, fatigue, refs, modal/Lightsail). For each: mark "already tracked as <ID>" or add a new item to the Betts tracker; strike through here with the pointer.

## CVP — Court CV / Homography Pipeline

Repo: `bball_homography_pipeline`. **Category ARCHIVED 2026-07-23 by
operator instruction ("forget about topic 1 and anything else that includes
CV")** — items retained for the record, no effort until un-archived.

#### CVP-1 · Try Outlet for real-time ARKit streaming on iPhone
`📦 ARCHIVED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `bball_homography_pipeline`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L20 (2026-07-23 migration)
**Notes:** https://www.linkedin.com/posts/pablo-vela_i-got-real-time-streaming-of-arkit-outputs-ugcPost-7483941558690455552-3Xzu/ De-scoped by operator 2026-07-23. Research was completed first and is preserved in [RESEARCH_NOTES_2026-07.md](reference/RESEARCH_NOTES_2026-07.md): "Outlet" doesn't exist — the tool is ARFlow (Apache-2.0) + Rerun; iPhone depth is useless at court distance; if ever revived, start with Record3D + rerun-sdk.

#### CVP-2 · SAM real-time monitoring upgrade
`📦 ARCHIVED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `bball_homography_pipeline`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L54 (2026-07-23 migration)
**Notes:** Upgrade our SAM real-time monitoring: https://www.linkedin.com/posts/ahsaanraazaa_ai-computervision-segmentanything-ugcPost-7483128324744073217-BtTP/ De-scoped by operator 2026-07-23.

#### CVP-3 · Modal-for-rerun decision + ground-truth review frontend + live-on-phone path
`📦 ARCHIVED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `bball_homography_pipeline`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L73 (2026-07-23 migration)
**Notes:** Check whether Modal is needed for CV when rerunning the pipeline with updated data; finish the frontend for reviewing how ground truth did (full pipeline speed for ground truth vs upload-and-expect-results); understand how to get it live with video on the phone. De-scoped by operator 2026-07-23.

#### CVP-4 · Multi-camera capture rig research (~10 cameras, iPhone-level, cheap)
`📦 ARCHIVED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `bball_homography_pipeline`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L72 (2026-07-23 migration)
**Notes:** Find the best ~10-camera setup (or however many is needed) to buy and start using; iPhone-level camera quality, cheap and easy to set up. De-scoped by operator 2026-07-23.

## LIFE — Personal, Home & Errands

Repo: `personal` (no code repo). House detail lives in
[`reference/HOME_MAINTENANCE.md`](reference/HOME_MAINTENANCE.md); media in
[`reference/MEDIA_WATCHLIST.md`](reference/MEDIA_WATCHLIST.md); books in
[`reference/READING_LIST.md`](reference/READING_LIST.md).

#### LIFE-1 · Backup EMS stuff + factory-reset upstairs laptop + Parsec/Brave
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `personal`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L60 (2026-07-23 migration)
**Notes:** Backup EMS stuff; factory reset the upstairs laptop; see about remoting in to downstairs if latency gets better; then download Parsec and Brave.

#### LIFE-2 · Book MJ appointment
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `personal`
**Priority:** P1
**Source:** soon_to_be_deleted_todos.md L40 (2026-07-23 migration)
**Notes:** From the pre-Philly-trip list.

#### LIFE-3 · GPU course — understand GPUs better
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `personal`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L162 (2026-07-23 migration)
**Notes:** Try out a GPU course to understand GPU computing better.

#### LIFE-4 · Migrate photos to Dropbox, delete off phone
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `personal`
**Priority:** P2
**Source:** soon_to_be_deleted_todos.md L163 (2026-07-23 migration)
**Notes:** Migrate photos to Dropbox, delete off phone, update.

#### LIFE-5 · World-models learning day (JEPA) — build a very basic one
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `personal`
**Priority:** P3
**Source:** soon_to_be_deleted_todos.md L68 (2026-07-23 migration)
**Notes:** Learn about world models like JEPA and spend a day creating one — very basic, but to understand.

#### LIFE-6 · Submit paperwork for charges to be dropped (2 lesser charges)
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `personal`
**Priority:** P1
**Source:** soon_to_be_deleted_todos.md L170 (2026-07-23 migration)
**Notes:** Submit paperwork for charges to be dropped for ourselves (2 lesser charges).

#### LIFE-7 · Philly trip prep — clean, organized, ready
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
**Repo:** `personal`
**Priority:** P1
**Source:** soon_to_be_deleted_todos.md L37-50 (2026-07-23 migration)
**Notes:** Feel clean and organized and ready for the trip to Philly; kanban working well enough to continue and repair itself while away (KAN items); movies for the trip are on the [Media Watchlist](reference/MEDIA_WATCHLIST.md).

## Idea Bank

Raw, un-triaged concepts. Everything here either graduates to a tracked item
above (with a `**Source:**` pointer) or is consciously retired — never
silently dropped. The bulk backlog awaiting triage lives in
[`reference/INTAKE_QUEUE.md`](reference/INTAKE_QUEUE.md) (source lines 37-226
of the migrated file, verbatim, with a triage map).

- Organize browser tabs or implement them into the kanban for future todos
  (source L42) — pairs with KAN-16 idea intake.
- "Ensure we are able to adjust the got plugin level for ourselves at any
  moment" (source L64, verbatim — likely "git plugin level"; clarify intent
  before tracking).
- Kanban open-code cost check: see costs of open code to see if fun is worth
  trying to improve performance or if we can do this via open source (L106).
- Voice cloning for the game-voice pipeline — my voice + random voices,
  possibly an amalgamation of old sportscasters (L52, Betts-bound):
  https://www.linkedin.com/posts/stasbel_someone-shipped-an-open-source-alternative-share-7481285843500892160-iJq2/
- World models / video distortion to upgrade from "just me" to any kind of
  person or thing (L59, Betts/CVP-bound).
- Go through the sports-projects note and the laptop notepad notes and add
  them to this list (L119) — another intake sweep like this migration.

## Change log

- 2026-07-23 — Master tracker created in `llm_station` (migration from
  `soon_to_be_deleted_todos.md` + designation split from the Betts tracker).
  65 tracked items seeded across KAN/AGT/PROC/JOBS/SCL/BB/CVP/LIFE with
  per-item Repo designations; bulk lists moved to `reference/`.
- 2026-07-23 — KAN-24 implemented (Codex gpt-5.6-sol, worktree branch
  `feat/kan-24-grand-todo-ui-parity` @ 3e54a24, Fable review approved) and
  PROC-1 loop proven end-to-end with it; both moved to SHIP-TAIL pending
  operator merge. Migration committed on `feat/grand-todo-master`
  (adab21a, f94ac5f, 996e0f6); cockpit rebuilt with the grand_todo board
  live; source-file deletion left to the operator (classifier-blocked).
