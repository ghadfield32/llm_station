# LLM Station — Project Instructions

Standing rules for working in the `llm_station` repository (Command Center v4 —
the LLM control plane). These override default behavior. This file wires the
protocol into every Claude Code session — terminal, desktop, or a **cockpit
agent session** launched by the host worker (those load this file via the
session cwd). The full workflow is
[docs/engineering/AI_ASSISTED_DEVELOPMENT_WORKFLOW.md](docs/engineering/AI_ASSISTED_DEVELOPMENT_WORKFLOW.md);
the pasteable operating block is
[docs/engineering/REUSABLE_ENGINEERING_STANDARDS.md](docs/engineering/REUSABLE_ENGINEERING_STANDARDS.md).
This file is the always-loaded summary; those docs are authoritative.

## Sources of truth (descending, for an affected concern)

1. Current repository code, tests, and committed configuration contracts.
2. `configs/*.yaml`, their Pydantic schemas, and `make validate`.
3. The runtime Ledger and the configured kanban/mission workflow (runtime
   state and approvals).
4. `docs/MASTER.md` and the applicable architecture/operations/runbook docs.
   `WORKLOG.md` is the compact done/doing/next log — add one-liner entries when
   behavior changes.

Chat summaries and agent assertions are context, not evidence — deterministic
checks, the actual diff, and reproducible runtime evidence are authoritative.
`generated/` is disposable rendered output: never hand-edit it.

## Session ritual

1. Inspect `git status --short`, current branch, base SHA, and concurrent edits
   (especially `configs/`, shared orchestration code, the Ledger/kanban seam,
   and shared docs).
2. Run `uv run cc doctor` when work touches or depends on the local stack.
3. Define scope, non-goals, allowed/forbidden files, validation evidence, and
   operator-only actions before editing.
4. Preserve unrelated work. Never use `git add -A` or `git add .`; stage exact
   file paths only. One editing agent per worktree; commit load-bearing new
   files immediately when working in a shared checkout.

## AI Workflow & Model Allocation

Full policy: [docs/engineering/AI_ASSISTED_DEVELOPMENT_WORKFLOW.md](docs/engineering/AI_ASSISTED_DEVELOPMENT_WORKFLOW.md).

Claude Code and Codex are **coding executors** authenticated through their own
subscription/OAuth sessions. They are **not** LiteLLM chat models — never add
them to the chat model picker or route them through the local model gateway.
The local gateway's served models are qualified separately via
[MODEL_VERIFICATION_WORKFLOW.md](docs/engineering/MODEL_VERIFICATION_WORKFLOW.md);
that is a different concern from coding-executor allocation.

**Route by capability profile, never by a hardcoded model name:**

- `strategic_steward` → **Fable 5**: architecture, planning, contracts,
  methodology, documentation, security/threat review, validation design, final
  semantic integration.
- `generalist` → **Opus**: most normal engineering, implementation, tests,
  review, documentation, coordination.
- `deep_code` and `throughput` → **Codex = Sol family only**, split by
  reasoning effort, not by model: `throughput` = **`high`** (standing default),
  `deep_code` = **`xhigh`** (migrations, concurrency/durable state,
  security-sensitive code, hard debugging, final high-risk review). Terra is
  retired from the default mapping.
- `independent_verifier` → a **fresh, read-only** session, never the one that
  did the work; prefer cross-family (Fable for methodology/security/validation,
  Sol for deep code).

**Resolve models live — do not trust a remembered slug.** Each session run
`codex debug models` (lower `priority` = more current) and pick the current
lowest-`priority` Sol-family model. Naming an older dotted version when a newer
Sol model is live is a resolution error, not a substitution.

**Don't let Fable or Opus absorb a whole divisible task** — carve deep code to
Sol `xhigh` and broad explicit execution to Sol `high`; parallelize via
multiple concurrent Sol worktrees, not by dropping to a cheaper family. Tool
friction is not "unavailable" — fix the worktree/sandbox first. Record in every
medium/high-risk packet: required profile, resolved model + effort, availability
evidence, fallback rule, independent-review profile, and the work allocation.

**Sol write-mode implementation.** `deep_code`/`throughput` work means **Sol
writes the code**, not Claude/Opus on Sol's behalf: `codex exec --sandbox
workspace-write --full-auto -C <isolated worktree>` — always a dedicated
worktree/clone, never the shared checkout, never `--sandbox danger-full-access`.
The normal verify → independent-review → operator-merge gates (and the Ledger /
kanban approval walls) still apply. If the harness policy classifier blocks the
write (it treats an approvals-off write+exec agent as unsafe by default), that
is a **blocker to surface to the operator** (who can allow it with a scoped
`Bash(codex exec --sandbox workspace-write:*)` permission rule) — **not** a
silent handoff to Claude/Opus logged as a routine exception. When the exception
fires every session, the allocation contract is fiction.

**Reviewer independence flips with the author** (no model or session reviews its
own output): Claude/Opus wrote → **Sol** reviews (fresh, read-only); Sol wrote →
**Fable/Opus or a fresh Sol session** reviews — never the implementing session.

**Destructive-action double-agreement gate:** any delete / drop / truncate /
force-overwrite / irreversible action (including Ledger/queue/durable-state
mutations) requires **two independent models** to confirm it is safe (Sol +
Claude/Fable — two sessions of the same model don't count unless nothing else is
reachable, and that must be disclosed) **before it is even proposed to the
user**, then the user's explicit current-turn approval. A prior approval for a
similar action never carries forward. On disagreement or unavailability, stop
and surface it.

### Claude ⇄ Codex handoff in practice (by session type)

- **Direct Claude Code session** (terminal/desktop): the `skill-codex` plugin
  is installed — use `/codex` (codex exec / codex resume) to delegate bounded
  deep-code work or to run an independent READ-ONLY review of your diff before
  closeout. Record what was delegated and the verdict.
- **Cockpit agent session** (read-only analysis wall; slash commands and MCP are
  disabled there by design): do not try to run Codex yourself — state plainly
  "this is Codex-profile work", and point the operator at the assistant switcher
  / Roles ▾ panel, which resumes each runtime's own session within the
  conversation.
- Independent review is never skipped on high-risk work. If Codex is unavailable
  (usage limit), say so and record it — never silently self-review.

## Goal-Driven KPI Leaderboard Loop

Run every non-trivial improvement/evaluation task as a **champion-challenger
loop against a persistent KPI leaderboard**, not a one-shot.

1. **Frame** — Define the KPI(s) and the goal (target + stop condition) from
   data, never an invented threshold. Record the current champion as baseline
   (none → the first validated attempt becomes it). Keep quality-evaluation
   KPIs distinct from serving-evaluation KPIs.
2. **Attempt (loop body)** — One challenger via the full workflow: bounded
   packet → Sol implementation (effort by risk) → deterministic verification
   (`make validate`/`make test`, `uv run cc doctor`) → fresh independent review.
   No fake/default values; past-only inputs + temporal splits for time-ordered
   work.
3. **Evidence gate** — A challenger scores **only** with reproducible runtime
   evidence from real data (historical where time-ordered, plus a current run)
   and passing validations/tests. Unproven attempts do not enter.
4. **Leaderboard** — Append each validated challenger's KPIs with provenance
   (commit, config/contract version, exact command, exit status) to the ranked
   leaderboard artifact. Promote to champion **only** when it beats the
   incumbent on the agreed metric AND clears the same gates. Do not bypass the
   Ledger or kanban/mission flow to record or promote a result.
5. **Goal check, then keep improving** — When the goal is met and validated,
   report it with the leaderboard, then keep looping challenger attempts to push
   past it, surfacing the updated leaderboard each round, until diminishing
   returns, budget exhaustion, or the user's stop.
6. **Stop honestly** — A metric gain alone never promotes: require baselines,
   coverage, calibration/uncertainty where applicable, and out-of-time behavior.
   Report regressions and dropped coverage; never silently truncate the search
   or the leaderboard.

## Engineering standards

- Make minimal, root-cause fixes. Preserve typed contracts, `extra="forbid"`
  validation, and the human approval and human merge walls.
- No swallowed exceptions, silent fallbacks, fake/default data, invented
  thresholds, speculative abstractions, or unsupported "done" claims.
- Use real, provenance-backed evidence. Keep quality evaluation separate from
  serving evaluation. Time-ordered learning uses past-only features + temporal
  splits.
- New dependency: `uv` install, pin a compatible range in every consuming
  `pyproject.toml`, prove `uv sync`, commit metadata with the code.
- Update docs when behavior, interfaces, contracts, or runbooks change.

## Verification

Run every applicable check. Config changes require `make validate`; code
changes require targeted tests and normally `make lint`/`make test`; runtime
changes require proportionate health or smoke evidence (`uv run cc doctor`).
Record exact commands, exit statuses, relevant metrics/counts, and artifact
paths. Never claim a check passed unless it was run successfully against the
current change.

## Safety boundaries (operator-controlled)

- Never edit or expose `.env` secrets.
- Never enable cloud/provider routes or bypass LiteLLM, the Ledger, the Judge
  Gate, kanban approval, branch protection, or merge controls.
- Never approve mission cards, merge, push directly to `main`, deploy, rotate
  credentials, or perform destructive/irreversible actions autonomously.
- Cockpit agent sessions are read-only analysis: report findings; do not attempt
  mutation.
- Prepare clear commands and evidence; leave those actions to the operator.

At completion, report exact files changed, validation evidence, known
limitations, never-stage artifacts, and required human next steps.
