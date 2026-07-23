# Todo → Project Process — the consistent loop for every todo

The one process every todo follows, from raw idea to verified done. It is the
operating contract behind [`GRAND_TODO_LIST.md`](GRAND_TODO_LIST.md) and the
`grand_todo` board, designed so each step is the same every time: easy to
check into, easy to adjust, hard to do in the wrong direction.

Related standards: [`../engineering/AI_ASSISTED_DEVELOPMENT_WORKFLOW.md`](../engineering/AI_ASSISTED_DEVELOPMENT_WORKFLOW.md)
(model allocation, review independence, KPI leaderboard loop) and
[`../engineering/REUSABLE_ENGINEERING_STANDARDS.md`](../engineering/REUSABLE_ENGINEERING_STANDARDS.md).

## The loop at a glance

| # | Stage | Output (evidence) | Human gate |
| --- | --- | --- | --- |
| 1 | Capture | Tracked item in the master list (ID, repo, priority, source) | — |
| 2 | Designate | Registered repo + docs folder resolved | — |
| 3 | Run-doc | Researched, up-to-standards run-doc in the designated repo | — |
| 4 | Questions (KPI meeting) | Open questions answered; run-doc updated; scope locked | ✅ answers |
| 5 | Mission setup | Mission/board card linked to run-doc + plan; model allocation recorded | ✅ approve |
| 6 | Monitored execution | Progress on the card; adjustable folder/model/scope mid-flight | check-ins |
| 7 | Panel review | Independent multi-LLM review verdicts recorded | — |
| 8 | Close | Evidence-backed done; leaderboard/KPIs updated; docs current | ✅ accept |

Stages never skip. A stage may be *small* (a personal errand's run-doc is two
lines), but it is always present so the trail is consistent.

## 1. Capture — every todo enters the master list

- New todos land as tracked items in [`GRAND_TODO_LIST.md`](GRAND_TODO_LIST.md)
  (or the [Intake Queue](reference/INTAKE_QUEUE.md) if raw/bulk), each with:
  stable ID, `**Repo:**` designation, `**Priority:**`, `**Source:**`
  provenance, and the original wording preserved in Notes.
- Betts items are reconciled into the Betts tracker
  (`betts_basketball/docs/backend/projects/GRAND_TODO_LIST.md`) — one
  canonical file per repo, the master list designates and links.
- Sync to the board: `uv run cc grand-todo-import --board grand_todo --apply`
  (dry-run without `--apply`). The Markdown stays canonical; the board is a
  merge-only projection.

## 2. Designate — repo and folder before any work

- The `**Repo:**` field names the only workspace agents may touch. Repos must
  be registered with the Command Center (`configs/autonomy.yaml`
  `repo_manifests`) before agent work starts (KAN-2 hardens this wall).
- Project docs live inside the designated repo:
  `docs/projects/<item-id>-<slug>/` (create via the PROC-3 template once it
  exists; until then, create the folder by hand following this doc).
- `personal` items have no repo; their artifacts live in this repo under
  `docs/todos/reference/` lists or the card itself.

## 3. Run-doc — researched plan, up to standards, before execution

Every todo that becomes a project gets a run-doc:
`docs/projects/<item-id>-<slug>/RUNDOC.md` in the designated repo (PROC-2).

Required sections:

1. **Objective & definition of done** — measurable, from the todo's own words.
2. **Research** — only true, verified findings (links read, APIs checked,
   repo code inspected). No speculation presented as fact; unknowns go to
   §5 Questions. (AGT-5 STORM will pre-fill this stage.)
3. **KPIs & baseline** — the champion/challenger frame from the KPI
   leaderboard loop: metric(s), current baseline, target, stop condition —
   from data, never invented.
4. **Plan** — bounded steps, allowed/forbidden files, validation commands,
   operator-only actions.
5. **Open questions** — everything that would otherwise cause work in the
   wrong direction.
6. **Model allocation** — capability profile per step (strategic_steward /
   generalist / deep_code / throughput), resolved live per the workflow doc,
   plus the independent-reviewer profile.
7. **Links** — the master-list item, the board card, related run-docs.

Every addition to a run-doc gets a review pass (is it helpful, organized,
correct, up to standard?) before it lands — the PROC-3 review chain.

## 4. Questions — the KPI-meeting checkpoint

- The run-doc's open questions are put to the operator *before* execution,
  KPI-meeting style: short, concrete, answerable quickly (voice-friendly once
  KAN-11 ships).
- Answers are written back into the run-doc (decisions section), the scope is
  locked, and the card records the question/answer trail.
- If answers change the KPIs or plan, loop within stage 3-4 until stable —
  never start execution with material questions open.

## 5. Mission setup — card, links, allocation

- The board card gets: link to the run-doc, link to the plan, priority /
  impact / timeline (KAN-12), and the recorded model allocation + fallback
  rule.
- Mission tracking is optional-but-default for multi-session work (inert
  mission card; no auto-execute). Approval walls stay human-only.
- The operator approves the packet before agent execution starts.

## 6. Monitored execution — adjustable mid-flight

- Work proceeds in the designated repo only, by the allocated model
  (Sol write-mode in an isolated worktree for deep_code/throughput; Claude/
  Opus for generalist work), with progress visible on the card/chat session.
- The operator can check in at any point and adjust: the folder/repo, the
  model, the scope, or pause/continue the mission. The agent asks questions
  along the way as they arise instead of guessing.
- Deterministic checks run as work lands: `make validate` for configs,
  targeted tests for code, `uv run cc doctor` for runtime — recorded with
  exact commands and exit statuses.

## 7. Panel review — multiple LLMs, different roles, never the author

- Independent review is never skipped on medium/high-risk work, and no model
  or session reviews its own output:
  - Claude/Opus wrote → Sol (Codex) reviews, fresh and read-only.
  - Sol wrote → Fable/Opus (or a fresh Sol session) reviews.
  - Methodology/security/validation design → Fable profile.
- Panel roles to cover per review: correctness, defensive coding/security,
  standards/organization, and KPI/validation honesty.
- Verdicts and what was delegated are recorded on the card/run-doc. If a
  reviewer is unavailable (usage limits), say so and record it — never
  silently self-review.

## 8. Close — evidence or it didn't happen

- Done requires: definition of done met, validations green (commands + exit
  statuses recorded), KPIs vs baseline reported (regressions included),
  docs/WORKLOG updated, and the leaderboard appended when the work was an
  improvement attempt.
- The master-list item moves to `✅ DONE` (via the board or the Markdown —
  the importer reconciles both directions), with the Done date filled.
- Destructive/irreversible follow-ups (deletes, merges, deploys, rotations)
  are prepared as exact commands for the operator, never executed
  autonomously; deletes additionally need the two-model agreement gate.

## Continuous improvement of the process itself

- This doc is itself under the loop: every completed todo that exposed
  friction adds a tracked improvement (successes *and* fails), so the process
  keeps getting better based on evidence (PROC-3's "reiteration" clause).
- The cockpit surfaces for this loop are tracked as KAN-11 (intake flow),
  KAN-12 (priorities), KAN-16 (idea router), KAN-24 (grand-todo board
  parity), and AGT-12 (completion KPIs / leaderboard).

## Current tooling map (2026-07-23)

| Stage | Today | Upgrades tracked as |
| --- | --- | --- |
| Capture | Edit master list + `cc grand-todo-import` | KAN-16, KAN-11 |
| Designate | `configs/autonomy.yaml` repo manifests | KAN-2, KAN-13, KAN-14 |
| Run-doc | Hand-authored per this doc | PROC-2, PROC-3, AGT-5 |
| Questions | Chat/PR discussion | KAN-11 (voice-friendly) |
| Mission | Board cards + optional mission cards | KAN-12, KAN-23 |
| Execution | Agent sessions, `cc branch-mission`, worktrees | KAN-15, AGT-10 |
| Panel | `/codex` cross-review + fresh sessions | AGT-11, AGT-12 |
| Close | `make validate` / tests / doctor + WORKLOG | KAN-18 (leaderboard board) |
