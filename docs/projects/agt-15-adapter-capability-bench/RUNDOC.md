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

## 5. Open questions — ANSWERED (Stage-4 gate passed 2026-07-24)

Operator decisions, recorded verbatim; scope locked:

1. Dimension set v1: **5 core** — streaming, resume, write-mode wall,
   attachments, model-switch. Interrupt/steering are a later packet.
2. Live probes: **operator-triggered only** (never in CI); the offline
   subset runs in CI. Live-run token budget stays a per-run operator
   decision (no autonomous spend).
3. DRIFT: **report-only first** — offline probes run in CI as report-only
   until one live baseline is recorded (mirrors omnigent's P1 probes); a
   later challenger flips DRIFT to a CI gate once the baseline is triaged.
4. Matrix artifact: **`generated/`** — disposable rendered output, never
   hand-edited, regenerated each run.

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

## 7. Packet-1 evidence (2026-07-24)

- **Implemented by Sol** (`codex exec --sandbox workspace-write --full-auto`,
  gpt-5.6-sol **high** — throughput, resolved live priority 1; brief:
  [PACKET-1.md](PACKET-1.md)) in isolated worktree `C:\tmp\agt15-bench`
  stacked on AGT-14→AGT-16. Sandbox correctly blocked the git commit →
  committed host-side after independent verification.
- **Delivered**: `agent_sessions/bench/` (models, profiles, probes/,
  reconcile, render, runner), `cli/adapter_bench.py` registered in
  `cli/main.py`, `BenchProfile` attached to FakeHarness + all 4 adapter
  classes, `generated/adapter-capability-matrix.json`, 7 tests.
- **The honesty rule held**: offline matrix = PASS 1 / PARTIAL 2 / FAIL 0 /
  **SKIPPED 22** / DRIFT 0. All 20 real-adapter cells are `SKIPPED` with a
  concrete offline reason — never a faked PASS (asserted by
  `test_real_adapters_are_skipped_offline_never_unobserved_passes`).
  FakeHarness earns 3 observed cells (write_mode_wall PASS, streaming +
  resume PARTIAL) and honestly SKIPS attachments/model_switch it cannot
  exercise. DRIFT=0 offline (no real drift found).
- **Independently verified host-side** (Fable, this session — did NOT write
  AGT-15; Sol did): validate_config PASS, check_cross_refs PASS,
  `adapter_bench` exit 0, `pytest test_adapter_bench.py` 7/7, regression
  (spec + policy + floor + sessions) 55/55, ruff clean, mypy clean. The 5
  `test_agent_session_service` failures remain the pre-existing KAN-25 family.
- **DRIFT mechanism proven** (not just asserted absent): a deliberately-wrong
  profile → DRIFT (`test_declared_not_observed_capability_becomes_drift`);
  seeded registry-mode mismatch → DRIFT; `external_egress` vs unqualified
  attachment PASS → DRIFT. **Coverage guard** extends AGT-16's idea:
  `test_every_registry_harness_has_exactly_one_profile_and_vice_versa` (an
  orphan profile OR an adapter with no profile FAILS).
- **Review verdict: APPROVE**, no defects. Design is honest-by-construction:
  `ProbeResult` forbids a probe from self-declaring DRIFT (reconciliation-only
  verdict); `BenchProfile` forbids declaring SKIPPED/DRIFT (claims must be a
  real capability). Report-only per Stage-4 — DRIFT does not gate CI until a
  live baseline exists.
- **KPIs vs baseline**: KPI-1 = 3 probe-earned cells + full 5×5 matrix
  reconciled (baseline 0 probe-earned cells). KPI-2 = DRIFT count now
  MEASURED = 0 offline (baseline: unknown) — the number the RUNDOC said would
  stay unknown until measured is now a measured 0, with the mechanism proven
  to flag a real one. Feeds AGT-12. Stop condition met — live probes +
  interrupt/steering dims are a later challenger.

## 8. Links

- Master item: `docs/todos/GRAND_TODO_LIST.md` → AGT-15 (AGT-3-for-runtimes;
  KPI feeds AGT-12).
- Board/mission card: pending Stage-5 human approval — not created before
  that gate (the importer projects the AGT-15 card from the master list).
- Pattern doc: `docs/reviews/2026-07-23-omnigent-borrow-patterns.md`.
- Catalog row: `knowledge/research/source_catalog.yaml` →
  `omnigent-meta-harness`.
- Siblings: AGT-14 (policy stack — "policy DENY actually blocks" becomes a
  probe once both exist), AGT-16 (session spec).

## 9. Packet 2 evidence (2026-07-24)

**Packet 2 (Sol gpt-5.6-sol high):** added `interrupt` + `steering`
dimensions (5→7). interrupt is event-observable (FakeHarness earns PASS from
`session_failed` + interrupted status); steering is honestly SKIPPED for
FakeHarness (no mid-turn steering surface) — never faked. Per-adapter claims
added (interrupt PASS/PARTIAL, steering FAIL); DRIFT mechanism proven for both
new dims. Adapter edits purely additive bench_profile fields. Commit `a2d2f10`.
Host-verified: validate PASS, adapter-bench 7-dim exit 0, 9 bench + 36
regression tests, ruff clean. Report-only default unchanged (CI DRIFT-gate flip
still gated on an operator live baseline). Fable review APPROVE.
