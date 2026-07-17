# LLM Station — CLAUDE.md

You are working in `llm_station` (Command Center v4 — the LLM control plane).
The authoritative standards live in `docs/`; this file wires the protocol into
every Claude Code session: terminal, desktop, or a cockpit agent session
launched by the host worker (those load this file via the session cwd).

## Read first

- `docs/engineering/AI_ASSISTED_DEVELOPMENT_WORKFLOW.md` — model allocation,
  capability profiles, review chains.
- `docs/engineering/REUSABLE_ENGINEERING_STANDARDS.md` — the operating
  contract (evidence, verification, closeout).
- `docs/MASTER.md` — architecture + current status. `WORKLOG.md` — the
  compact done/doing/next log; add one-liner entries when behavior changes.

## Claude ⇄ Codex protocol (the AI-assistance division of work)

Two coding runtimes share the work by capability profile, per the workflow
doc — hand work back and forth instead of monopolizing it:

- **Claude (this session)**: architecture, planning, contracts, docs,
  semantic review, integration, general implementation.
- **Codex**: difficult cross-module coding, durable state/concurrency/
  migrations, hard debugging, performance work, independent final-diff
  review.

How to hand off:

- **Direct Claude Code session** (terminal/desktop): the `skill-codex`
  plugin is installed — use `/codex` (codex exec / codex resume) to delegate
  bounded deep-code work or to run an independent READ-ONLY review of your
  diff before closeout. Record what was delegated and the verdict.
- **Cockpit agent session** (read-only analysis wall; slash commands and MCP
  are disabled there by design): do not try to run Codex yourself — state
  plainly "this is Codex-profile work", and point the operator at the
  assistant switcher / Roles ▾ panel, which resumes each runtime's own
  session within the conversation.
- Independent review is never skipped on high-risk work. If Codex is
  unavailable (usage limit), say so and record it — never silently
  self-review.

## Session ritual (condensed — full form in the workflow doc)

1. `git status --short` + branch + base SHA before editing. Never
   `git add -A` / `git add .` — stage exact paths only.
2. `uv run cc doctor` when work touches the local stack.
3. Config changes require `uv run cc validate`; code changes require
   targeted tests and `uv run cc lint`. Never claim a check passed unless it
   ran against the current change.
4. `generated/` is disposable rendered output — never hand-edit it.
5. Resolve models live from the installed executors; never name a model from
   memory.

## Walls (non-negotiable)

- Never approve mission cards, merge, push to `main`, deploy, rotate
  credentials, or take destructive/irreversible actions autonomously.
- Never edit or expose `.env` secrets. Never bypass LiteLLM, the Ledger,
  Judge Gate, kanban approval, branch protection, or merge controls.
- Cockpit agent sessions are read-only analysis: report findings; do not
  attempt mutation.
