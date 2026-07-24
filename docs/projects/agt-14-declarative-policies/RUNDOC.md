# AGT-14 · Declarative session policy stack — RUNDOC

Stage 3 run-doc per [TODO_PROCESS.md](../../todos/TODO_PROCESS.md). Status:
**awaiting Stage-4 answers** — do not start execution with §5 open.

## 1. Objective & definition of done

Typed, declarative policy documents that gate what an agent session may do,
evaluated at three stricter-first levels (session → agent → server) with
**ALLOW / DENY / ASK** verdicts, where ASK routes into the existing
approval-wall idiom. Done when: (a) a Pydantic `extra="forbid"` policy schema
validates under `make validate`; (b) at least the three seed builtins
(ask-on-os-tools, max-tool-calls-per-session, cost-budget with soft
ask-thresholds wired to `src/command_center/usage/` budgets) enforce on real
agent-session tool calls with tests proving ALLOW, DENY, ASK, and
declaration-order short-circuit; (c) policies can only tighten — a test
proves the hard floors (human-only resolutions, read-only cockpit sessions,
destructive double-agreement) cannot be loosened by any policy document.

## 2. Research (verified)

- Pattern source: omnigent `docs/POLICIES.md` @ main, read raw 2026-07-23
  (repo live-verified: 7,679★, Apache-2.0, v0.6.0). Full analysis:
  [2026-07-23-omnigent-borrow-patterns.md](../../reviews/2026-07-23-omnigent-borrow-patterns.md).
- Our seam today: enforcement is code-shaped across
  `src/command_center/agent_sessions/` (worker_app, mutation_proof,
  secret_paths), UI guards in `services/agent_kanban_ui/app.py`, and the
  chat→Kanban governance wall. No single inspectable policy artifact exists.
- The usage layer (PR #34 workstream) already keeps usage/limit/availability/
  budget distinct — `cost_budget` must consume that budget concept, not
  invent a parallel one.

## 3. KPIs & baseline

- Baseline (measured 2026-07-23): **0** declarative policy documents;
  session-level behavioral gates exist only as code.
- KPI-1: count of enforcement points gated by a validated policy document
  (baseline 0; target set at Stage 4 with the operator — not invented here).
- KPI-2: floor-integrity — the cannot-loosen test suite stays green (hard
  requirement, not a score).
- Stop condition: the three seed builtins enforced + floors proven, then
  reassess before widening coverage (champion/challenger on KPI-1).

## 4. Plan (bounded)

1. Schema: `PolicyDoc` / `PolicyLevel` / verdict enum under
   `src/command_center/schemas/` + a `configs/` policy file with
   `make validate` coverage.
2. Engine: declaration-order evaluation, session-first short-circuit, ASK →
   existing approval wall (no new approval surface).
3. Seed builtins + tests (ALLOW/DENY/ASK/short-circuit/floor-integrity).
4. Wire into the agent-session worker's tool-call path behind a flag.
- Allowed: `src/command_center/schemas/`, `src/command_center/agent_sessions/`,
  `src/command_center/usage/`, `configs/`, `tests/`.
- Forbidden: `services/agent_kanban_ui/` UI (later packet), `.env`, Ledger
  schema migrations, any loosening of existing walls, `docs/MASTER.md`
  (digest re-record — separate deliberate pass).
- Validation: `make validate`, targeted pytest, `make lint`; `uv run cc
  doctor` if worker wiring lands.

## 5. Open questions (Stage-4 gate)

1. Which enforcement points first — agent-session tool calls only, or also
   the chat→Kanban write proposals?
2. Where do policy documents live: one `configs/session_policies.yaml`, or
   per-agent files beside the (future AGT-16) session specs?
3. KPI-1 target: how many enforcement points must be policy-gated before
   this counts as shipped v1?
4. Is the flag-off default acceptable for the first merge (enforcement
   opt-in), or must it enforce from day one?

## 6. Model allocation

- Profile: **deep_code** (durable-state + security-sensitive contracts) →
  **Sol writes**: `codex exec --sandbox workspace-write --full-auto -C
  <isolated worktree>`, effort **xhigh**.
- Resolved live 2026-07-23: `codex debug models` → **gpt-5.6-sol**
  (priority 1, lowest = current; terra=2 retired from default mapping).
- Fallback: if the harness policy classifier blocks Sol write-mode, surface
  to operator for a scoped permission rule — never a silent Claude/Opus
  handoff.
- Independent review: Sol wrote → **Fable** (methodology/security) read-only,
  fresh session; floor-integrity test design reviewed by Fable before
  implementation.

## 7. Links

- Master item: `docs/todos/GRAND_TODO_LIST.md` → AGT-14 (feeds KAN-17).
- Board/mission card: pending Stage-5 human approval — not created before
  that gate (the importer projects the AGT-14 card from the master list).
- Pattern doc: `docs/reviews/2026-07-23-omnigent-borrow-patterns.md`.
- Catalog row: `knowledge/research/source_catalog.yaml` →
  `omnigent-meta-harness`.
- Siblings: AGT-15 (bench), AGT-16 (session spec — policy refs live there).
