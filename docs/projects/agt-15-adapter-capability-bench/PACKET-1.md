# AGT-15 packet 1 — implementation brief (Sol write-mode)

Authoritative context: `RUNDOC.md` in this directory (§1 DoD, §4 plan, §5
LOCKED Stage-4 decisions), plus repo `CLAUDE.md` standards. Branch:
`feat/agt15-adapter-bench` (isolated worktree, stacked on AGT-14 → AGT-16, so
the policy + spec code already exist). Never push; commit local, exact paths.

Profile: **throughput** (broad explicit test infrastructure) — effort
**high**. You are Sol; Fable reviews you (reviewer independence holds).

## The idea (omnigent docs/harness-bench-design.md, borrow_pattern_only)

Turn the hand-known capability matrix of the agent-session adapters into an
**executable conformance suite**: each capability cell is *earned* by a probe
that inspects the event stream, then **reconciled against a self-declared
per-adapter profile** — declared ✓ but observed ✗ is a `DRIFT` verdict. We
borrow the shape, not their code.

## Honesty constraint (non-negotiable)

The only offline driver is `FakeHarness` (no SDK/subprocess/network). Real
adapters (`codex_agent`, `claude_code_local`, `claude_agent`,
`openrouter_agent`) CANNOT be truly observed offline. Therefore:

- A cell the offline driver genuinely exercises → `PASS` / `PARTIAL` / `FAIL`
  from the OBSERVED event stream.
- A cell whose runtime is unavailable offline → **`SKIPPED` with a concrete
  reason** (e.g. "codex SDK not probed offline"). **NEVER** report a real
  adapter's dimension as `PASS` without an observation — that would be the
  exact fabrication this bench exists to catch.
- `DRIFT` only when there IS an observation that disagrees with the
  declaration.

## Deliverables

1. **Per-adapter declared profile** — a typed `BenchProfile` (Strict) giving
   each adapter's *claimed* verdict across the **5 core dimensions**:
   `streaming`, `resume`, `write_mode_wall`, `attachments`, `model_switch`.
   Attach a `bench_profile()` (or a declared classattr) to each of the 5
   harnesses (`fake_harness.py` + the 4 adapters) — facts live ON the
   harness, never inside probe code (their key rule). Reconcile the profile's
   `write_mode_wall`/mode claims against the registry `supported_modes`
   already declared in `registry.py`, and `attachments`/egress against
   `interactive_approvals`/`external_egress` where those already encode a
   fact — a mismatch between two existing declarations is itself a DRIFT the
   bench must surface.
2. **Harness-agnostic probes** — `src/command_center/agent_sessions/bench/`
   (new subpackage): one probe per dimension, each takes a live harness +
   store and returns `ProbeResult{dimension, observed_verdict, detail}` from
   the event stream. Offline probes run against `FakeHarness`; a probe whose
   dimension the given harness can't exercise returns `SKIPPED` with a reason,
   never a guess.
3. **Reconciliation + matrix** — `reconcile(profile, probe_results) ->
   list[Cell]` where `Cell{adapter, dimension, declared, observed, verdict}`
   and verdict ∈ {`PASS`,`PARTIAL`,`FAIL`,`SKIPPED`,`DRIFT`}. DRIFT = declared
   truthy but observed contradicts. A matrix renderer (JSON + human table).
4. **CLI** — `cc adapter-bench` (add to `cli/` + register in `cli/main.py`):
   - default = offline subset, writes `generated/adapter-capability-matrix.json`
     + prints the table; **report-only** (exit 0 even on DRIFT for now — the
     Stage-4 decision; a `--strict` flag may exit 1 on DRIFT for later CI
     gating, but default stays report-only until a live baseline exists).
   - `--live` is **operator-only** (never in CI): probes real adapters; if a
     runtime is unavailable it records `SKIPPED`, never fails the run.
5. **CI wiring** — the offline subset only, report-only (document how it's
   invoked; do not add autonomous live runs). If there's an existing test/CI
   entrypoint pattern, follow it; otherwise a `tests/`-level test that runs the
   offline bench and asserts it produces a matrix with no `FAIL` is enough —
   DRIFT must NOT fail this first-baseline run.
6. **Tests** — `tests/test_adapter_bench.py`:
   - Each probe against FakeHarness returns the expected observed verdict.
   - A deliberately-wrong `BenchProfile` (claims a dimension FakeHarness does
     NOT support) → reconciliation yields `DRIFT` (proves the mechanism).
   - `SKIPPED` is produced (not PASS) for a real adapter offline — assert no
     real-adapter cell is `PASS` without an observation.
   - Matrix JSON schema is stable + written under `generated/`.
   - The registry-declaration cross-check (profile vs `supported_modes`) flags
     a seeded mismatch.
   - This is also the **AGT-15 seed of the enum↔registry idea AGT-16 started**:
     assert every registered harness id has a `BenchProfile` and vice-versa
     (a new adapter with no profile, or a profile with no adapter, FAILS).

## Constraints (hard)

- No new dependencies. No edits to `.env*`, `docs/MASTER.md`,
  `services/agent_kanban_ui/`, Ledger schema files. **Do not change adapter
  behavior** — the bench OBSERVES; packet 1 never "fixes" an adapter to make a
  cell pass. If you find a real DRIFT, record it in your report, don't patch
  the adapter.
- No fabricated observations, no silent SKIP-as-PASS, no invented verdicts.
- `generated/` is disposable — the committed matrix is illustrative; the CLI
  regenerates it. Match surrounding style. One editing agent: you.

## Validation to run and record (commands + exit codes in your final output)

```
uv sync --extra dev                                     # once (sandbox may block → PYTHONPATH fallback, say so)
uv run python -m command_center.cli.validate_config
uv run python -m command_center.cli.check_cross_refs
uv run python -m command_center.cli.adapter_bench       # offline; writes generated/ matrix
uv run pytest tests/test_adapter_bench.py -q            # ONE pytest process
uv run pytest tests/test_agent_session_spec.py tests/test_session_policy.py tests/test_agent_sessions.py -q   # no regression
uv run ruff check <changed files>
```

If the sandbox blocks the git commit (it did for AGT-14/16 — worktree git
metadata is read-only to the sandbox), report "implemented, uncommitted" and I
commit host-side. Do NOT fight the sandbox wall.

## Done =

All deliverables present, all commands exit 0 (pre-existing 5-failure
`test_agent_session_service` set unchanged, untouched), matrix written to
`generated/`, final message lists: files changed, commands + exit codes, every
real DRIFT found (with the declared-vs-observed detail), and any brief
deviation (flagged, never silent).
