# AGT-15 packet 2 — interrupt + steering dimensions (Sol write-mode)

Context: AGT-15 packet 1 (already on main) built the 5-dim bench
(`src/command_center/agent_sessions/bench/`), `cc adapter-bench` with `--live`
and `--strict` already present, and the honesty rule (real adapters SKIPPED
offline, never faked PASS). Read that code first. Branch:
`feat/agt-packet2-followons` (this worktree, off current main). Never push;
commit local, exact paths. Profile: **throughput**, effort **high**. You are
Sol; Fable reviews you.

## Objective

Add two new capability dimensions to the bench — **`interrupt`** and
**`steering`** — end to end, preserving every packet-1 invariant (honesty
rule, ProbeResult can't self-declare DRIFT, BenchProfile can't declare
SKIPPED, report-only default).

## Deliverables

1. **Dimension enum** — add `INTERRUPT = "interrupt"` and
   `STEERING = "steering"` to `bench/models.py` `Dimension`. `CORE_DIMENSIONS`
   picks them up automatically.
2. **BenchProfile fields** — add `interrupt: Verdict` and `steering: Verdict`
   to `BenchProfile` (models.py), keep the `_claims_are_capabilities`
   validator covering them.
3. **Two probes** — `bench/probes/interrupt.py`, `bench/probes/steering.py`,
   following the existing probe pattern (each takes a live harness + store,
   returns `ProbeResult` from the observed event stream; a harness that can't
   exercise the dimension returns `SKIPPED` with a concrete reason, never a
   guess). Register them so the runner covers all 7 dimensions.
   - interrupt: FakeHarness CAN exercise this — `interrupt()` sets status
     `interrupted` and emits `session_failed`; observe that → a real observed
     verdict (PARTIAL or PASS as the evidence warrants).
   - steering: FakeHarness has NO mid-turn steering concept → `SKIPPED` with a
     concrete reason ("fake harness has no mid-turn steering surface"). Do NOT
     fake it.
4. **Per-adapter declarations** — add honest `interrupt`/`steering` claims to
   every `bench_profile` (FakeHarness + the 4 adapters). Base each claim on
   what the adapter's code/protocol actually supports (e.g. the protocol has
   `interrupt()`; steering/mid-turn-queue is not implemented on the
   read-only-analysis adapters → declare FAIL there, honestly). If a
   declaration would contradict a registry fact, that's a DRIFT the bench must
   surface — do not paper over it; report it.
5. **Regenerate matrix** — `cc adapter-bench` now emits a 7-row-per-adapter
   matrix to `generated/`. Leave the generated file uncommitted (disposable).
6. **Tests** — extend `tests/test_adapter_bench.py`:
   - interrupt probe against FakeHarness earns its observed verdict.
   - steering is SKIPPED (not PASS) for FakeHarness with a reason.
   - the coverage/count assertions updated for 7 dims.
   - a deliberately-wrong interrupt/steering profile → DRIFT (mechanism still
     works for the new dims).

## Constraints (hard)

- No new dependencies. No adapter BEHAVIOR changes (only additive
  `bench_profile` field declarations). No edits to `.env*`, `docs/MASTER.md`,
  UI, Ledger. Do not touch the `--live`/`--strict` flags' default
  (report-only stays default; CI DRIFT-gate flip is operator-gated on a live
  baseline — out of scope here). Honesty rule is absolute.

## Validation to run and record (commands + exit codes)

```
uv sync --extra dev                                   # sandbox may block → PYTHONPATH fallback, say so
uv run python -m command_center.cli.validate_config
uv run python -m command_center.cli.adapter_bench     # 7 dims now
uv run pytest tests/test_adapter_bench.py -q
uv run pytest tests/test_agent_session_spec.py tests/test_session_policy.py -q   # no regression
uv run ruff check <changed files>
```

If the sandbox blocks the git commit, report "implemented, uncommitted" — I
commit host-side. Report every real DRIFT the new dims surface. Done = all
deliverables, all commands exit 0, deviations flagged.
