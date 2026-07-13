# Improvement-loop pre-work audit (discrepancy report)

> **Archived — pre-work snapshot (2026-06-12).** Everything this audit found
> missing (experiment contract, registry, coded runner/verifier) was built
> afterward; see [docs/improvement/improvement-loop.md](../improvement/improvement-loop.md).
> Kept for the historical rationale, not as current state.

Produced before any change, per the mission's "read current truth first" rule. Behavior was
confirmed in **code and tests**, not only docs. Baseline test ladder captured 2026-06-12 (all green:
`validate`, `cross-refs`, `forbidden-providers`, `evals` 6/6, `schema`, `mission-dryrun` L0–L4,
`pytest` 4/4, `ruff` clean; `mypy` 16 pre-existing errors, all missing third-party stubs).

The repository layout differs from the top-level README in one way worth recording up front: the
README's "Layout" block shows `schemas/` and `registry/` at repo root, but the code actually lives
under `src/command_center/` (`src/command_center/schemas/`, `src/command_center/registry/`). The
`src/` move is the newer truth (commit *"Make repo GitHub-ready: src/ layout…"*); the README block is
stale. Not load-bearing for this work, noted for accuracy.

## documented_behavior

- `docs/capability-evaluation-loop.md` describes a **three-role** (Investigator / Implementer /
  independent Verifier) evidence-first evaluation loop with A/B baseline-vs-candidate benchmarks,
  cross-provider verification that *re-runs* commands, evidence classification, bounded correction,
  and a PROMOTE/PILOT/DEFER/REJECT decision matrix. It reads as a live capability.
- `docs/model-update.md` + `docs/MASTER.md` describe model canary/promotion: `model-scout → validate
  → evals → models → models-canary → live-smoke → compare → models-promote | models-rollback`, with
  "no auto-promotion" enforced by `scout.propose_only`.
- `docs/proactive-ops.md` describes observe → cheap judge → escalate → root-cause → gated mission →
  post-watch (1h/24h/7d).
- `docs/autonomy-idea-map.md` Phase 4: the proactive runner *proposes* cards from evidence, "autonomy
  grows by proposing more, never by approving itself."

## implemented_behavior

- The **capability-evaluation loop is a manual prompt + hand-authored artifacts**, not a coded
  subsystem. `evaluation/capability-assessment/` holds real per-candidate `acceptance-rubric.yaml`,
  `benchmark-plan.yaml`, `raw/` logs, `evidence.md`, `threat-model.md`, `rollback.md`, `results.md`,
  `DECISION.md`. There is **no** experiment contract, registry, runner, coded verifier, sealed-eval
  mechanism, calibration, or negative-result store. The loop was *run by hand* for three external
  tools (abtop, semble, asm).
- **Model** canary/promote/rollback is the only coded promotion path
  (`registry/render.py --canary/--promote`, Makefile targets). It is model-specific; nothing
  generalizes it to prompts/skills/judges/routing/tools/standards/etc.
- The **Ledger** (`services/ledger/app.py`) has `missions`, `events`, `approvals`, `leases` only.
  Approvals are HMAC-signed (agents can't sign); the active-lease unique index enforces one-mission-
  one-checkout. No experiment tables, no artifact/hash storage, no structured experiment events.
- The **Growth OS curator** (`appflowy_kanban/growth-os/growthos/`) has boards for papers/repos/
  signals/todos/mission_intake/dags/library/lessons/packages/guidelines/notes/review. Clobber
  protection is real but **per-feature ad hoc** (`book_note` appends; `packages.py` only sets Status
  on new rows; `set_status` refuses `mission_intake→Approved`). There is **no** improvements board and
  no general "agent writes land non-approved, human status never clobbered" helper.
- The **proactive runner** observes and opens gated missions but has **no proposal generator** (no
  evidence thresholds, dedup, or cooldowns) and no experiment-drafting path.

## tested_behavior

- `tests/test_contracts.py` (4 tests) asserts only that **shipped configs validate** and the channel
  registry is internally consistent. It does **not** test that bad configs are *rejected*.
- `make evals` / `make mission-dryrun` re-assert the L3/L4-approval invariant deterministically.
- Growth OS `scripts/selftest.py` exercises the curator live (needs AppFlowy reachable).

## unverified_behavior

- The README claims the dangerous bad-edits ("two canaries in one role", "repo_task with secrets",
  "L3/L4 without requires_approval") are "**all tested**". The *validators exist* in
  `schemas/contracts.py`, but **no negative test exercises them**. This is asserted-not-proven.
- Model canary/promote/rollback has never been exercised on a real model swap (docs say "live
  (untested)").
- `docs/capability-evaluation-loop.md` presents the verifier loop as routine, but only one manual
  batch was ever run; nothing enforces verifier independence structurally.

## stale_or_conflicting_documentation

- README "Layout" shows root-level `schemas/`+`registry/`; truth is `src/command_center/…`.
- `docs/capability-evaluation-loop.md` blurs **methodology** (exists, manual) with **mechanism**
  (did not exist in code). This audit and the new `docs/independent-verification.md` draw that line.
- `judges.yaml` ships `cross_provider_review: false` while several docs describe cross-provider
  review as the norm — true today because the executors (Claude Code / Codex) are the cross-provider
  pair, and the local judge array is single-provider Ollama. Noted so the improvement loop's
  "different model family preferred" flag is understood as *preference, not guarantee* here.

## Conclusion → architecture decision

The methodology, the model-only promotion pipeline, the gated-mission spine, the HMAC approval wall,
and the lease isolation **already exist and are sound**. What is missing is the *coded, contract-
enforced, Ledger-backed, generalized* version of the loop. Therefore the improvement loop is added
**on top of** the existing Ledger (new tables in the same `ledger.db`), the existing `configs/` +
Pydantic contract pattern, the existing gates/approval wall, and the existing Growth OS action layer —
**not** as a second orchestrator, gateway, datastore, or approval mechanism. Every promotion still
terminates at the same human HMAC gate; no new way to say "approved" is introduced.
</content>
</invoke>
