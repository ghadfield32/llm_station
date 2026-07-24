# AGT-15 · Adapter capability bench (declared vs observed) — RUNDOC

Stage 3 run-doc per [TODO_PROCESS.md](../../todos/TODO_PROCESS.md). Status:
**awaiting Stage-4 answers** — do not start execution with §5 open.

## 1. Objective & definition of done

An executable conformance suite for the agent-session adapters
(`claude_agent`, `claude_code_local`, `codex_agent`, `openrouter_agent`;
Copilot joins when AGT-4 lands): every capability cell (streaming, resume,
write-mode wall, attachments, model switching) is **earned by a probe** and
**reconciled against a self-declared per-adapter profile** — declared ✓ but
observed ✗ is a `DRIFT` failure. Done when: (a) each adapter carries a typed
`BenchProfile`-style declaration; (b) one command emits the full matrix with
a verdict per cell; (c) the offline probe subset runs in CI; (d) at least one
live run against real harnesses is recorded with the matrix artifact.

## 2. Research (verified)

- Pattern source: omnigent `docs/harness-bench-design.md` @ commit c8828ed,
  read raw 2026-07-23 (bench status there: shipped — 6 P0 probes, 6
  report-only P1 probes per its own dimension catalog — the doc's blurb still
  says five, an internal staleness — live/offline drivers, DRIFT verdicts
  already caught real declaration drift). Full analysis:
  [2026-07-23-omnigent-borrow-patterns.md](../../reviews/2026-07-23-omnigent-borrow-patterns.md).
- Their motivating failure is ours: capability truth split across a
  hand-known matrix, in-code flags, and scattered constants — it drifts the
  moment an adapter changes.
- Our seam today: `src/command_center/agent_sessions/adapters/` +
  `fake_harness.py` (offline driver candidate); the 14-case cockpit
  acceptance (Codex adapter, PR #33 workstream) is deep e2e for one adapter,
  not breadth-with-reconciliation. Never hand-run deploy proofs —
  `scripts/run_agent_deployment_proof.ps1` precedent applies to live probes.

## 3. KPIs & baseline

- Baseline (measured 2026-07-23): **0** probe-earned capability cells.
  Existing capability facts are code-declared but unverified — the registry
  already declares `supported_modes`, `interactive_approvals`,
  `external_egress` per adapter (`agent_sessions/registry.py`); no
  declared-vs-observed reconciliation exists.
- KPI-1: cells earned by probes / total declared cells (baseline 0).
- KPI-2: DRIFT count — **unknown until the first live run measures it**;
  thereafter driven to 0 by fixing declarations or adapters, never by
  deleting probes.
- KPI-2 feeds AGT-12's leaderboard as a standing runtime-quality metric.
- Stop condition: matrix command + CI offline subset + one recorded live
  run; widening the dimension set is a new challenger round.

## 4. Plan (bounded)

1. Typed capability declaration per adapter (profile object beside each
   adapter, never facts inside probe code).
2. Probes: harness-agnostic, one per dimension, event-stream inspection;
   offline versions against `fake_harness.py`.
3. Matrix command (`cc` subcommand) emitting verdict-per-cell JSON + human
   table; DRIFT = nonzero exit.
4. CI wiring for the offline subset only; live run stays operator-triggered.
- Allowed: `src/command_center/agent_sessions/`, `src/command_center/cli/`,
  `tests/`, `scripts/`.
- Forbidden: adapter behavior changes (bench observes, first packet never
  "fixes" adapters), `.env`, UI.
- Validation: targeted pytest (one process only — never two concurrent),
  `make lint`; matrix artifact path recorded.

## 5. Open questions (Stage-4 gate)

1. Dimension set v1: streaming / resume / write-mode wall / attachments /
   model-switch — right five? Add interrupt/steering?
2. Live probes spend real tokens and touch real CLIs — cadence and budget
   (per usage layer) for live runs?
3. Should DRIFT fail CI, or report-only until the first live baseline is
   recorded (their P1 probes are report-only)?
4. Does the matrix artifact live under `evaluation/` or `generated/`?

## 6. Model allocation

- Profile: **throughput** (broad explicit execution, test infrastructure) →
  **Sol writes**: `codex exec --sandbox workspace-write --full-auto -C
  <isolated worktree>`, effort **high**.
- Resolved live 2026-07-23: `codex debug models` → **gpt-5.6-sol**
  (priority 1, lowest = current).
- Fallback: classifier-blocked write-mode → surface to operator for a scoped
  permission rule; never a silent handoff.
- Independent review: Sol wrote → **Fable/Opus** read-only fresh session
  (probe-validity + honesty of the reconciliation semantics).

## 7. Links

- Master item: `docs/todos/GRAND_TODO_LIST.md` → AGT-15 (AGT-3-for-runtimes;
  KPI feeds AGT-12).
- Board/mission card: pending Stage-5 human approval — not created before
  that gate (the importer projects the AGT-15 card from the master list).
- Pattern doc: `docs/reviews/2026-07-23-omnigent-borrow-patterns.md`.
- Catalog row: `knowledge/research/source_catalog.yaml` →
  `omnigent-meta-harness`.
- Siblings: AGT-14 (policy stack — "policy DENY actually blocks" becomes a
  probe once both exist), AGT-16 (session spec).
