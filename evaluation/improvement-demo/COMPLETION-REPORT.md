# Completion report — controlled recursive-improvement loop

## Current-state audit

The methodology, the model-only promotion pipeline, the gated-mission spine, the HMAC
approval wall, and the lease isolation **already existed and were sound**. What was missing
was the *coded, contract-enforced, Ledger-backed, generalized* version of the loop. Key
findings (full report: `docs/improvement-loop-audit.md`):

- `docs/capability-evaluation-loop.md` described a three-role verifier loop **as a manual
  prompt** run by hand for *external* tools (`evaluation/capability-assessment/`). There was
  **no code** for an experiment contract, registry, runner, coded verifier, sealed evals,
  calibration, or negative-result memory.
- The Ledger had `missions/events/approvals/leases` only. Model canary/promote was the only
  coded promotion path and was model-specific.
- `tests/test_contracts.py` (4 tests) only checked that *shipped* configs pass — it had **no
  negative tests** proving bad configs are rejected, despite the README claiming "all tested".
- The README's "Layout" block was stale (`schemas/` at root; truth is `src/command_center/`).

## Architecture decision

The loop was added **on top of** the existing Ledger (new tables in the same `ledger.db`),
the existing `configs/` + Pydantic contract pattern, the existing gates/approval wall, and the
existing Growth OS action layer — **not** as a second orchestrator, gateway, datastore, or
approval mechanism. Every promotion terminates at the same human HMAC gate; no new way to say
"approved" was introduced. The standalone Ledger container can't import the package, so the
experiment DDL is mirrored there and kept honest by a drift test.

## Implemented changes

- **Package** `src/command_center/improvement/`: `lifecycle.py`, `events.py`, `schema.py`,
  `ledger_schema.py`, `registry.py`, `runner.py`, `verifier.py`, `evals.py`, `calibration.py`,
  `proposals.py`, `promotion.py`, `board.py`, `attention.py`, `retrieval_strategies.py`.
- **Configs**: `configs/improvement.yaml` (new, registered in `CONFIG_CONTRACTS`),
  `configs/evals.yaml` (+ sealed/adversarial suites), `configs/breakage.yaml` (+ entry).
- **Ledger service**: 6 experiment tables + REST endpoints in `services/ledger/app.py`;
  Canary/Promoted gated by the existing HMAC wall.
- **Data**: `data/sealed-evals/` (access-controlled held-out content), `data/calibration/`.
- **CLI**: `src/command_center/cli/improvement.py` + `make improvement-*` /
  `judge-calibration` / `attention-digest` and Windows `cc.ps1` equivalents (dry-run default).
- **Generated**: `generated/json-schema/improvement.schema.json`.
- **Docs**: 5 new (improvement-loop, experiment-registry, independent-verification,
  judge-calibration, human-attention-governance) + audit + MASTER/capability-eval updates;
  7 Mermaid diagrams.

## Contract proofs (unsafe configs rejected)

`tests/test_improvement_contracts.py` proves rejection of: automatic_promotion, human-approval
disabled, missing rollback, missing baseline, no required metric, unbounded safety metric,
self-verification, missing budget field, L3/L4 experiment, secret-bearing experiment,
raw-evidence retention disabled, evidence-without-raw-logs, control-plane target without
elevated review, post-watch unknown metric, duplicate ids, unknown keys.
`tests/test_safety_boundaries.py` proves the §2 walls still hold (L3/L4 approval, repo_task
isolation, forbidden tool actions, kanban ≤L2, proactive ≤L2, no self-promotion,
deterministic-first gate). `evaluation/improvement-demo/unsafe-experiment.yaml` is rejected by
`make improvement-validate`.

## Test results

- `pytest`: **274 passed** in ~111s (was 4 at baseline). 29 test files. Includes the full
  measurement-science roadmap (Phases 0–6, all deterministic/offline, mypy-clean):
  - **P0/P1** `statistics.py` — bootstrap CIs, paired/unpaired tests, Benjamini-Hochberg FDR, SRM
    chi-squared, power/MDE, A/A, **mSPRT** always-valid stopping (no-peeking FP ≤ α), **CUPED**
    (>50% variance cut); verifier **C9** (reject-only).
  - **P2** `jury.py` — Cohen's κ / Fleiss' κ / Krippendorff's α (vs hand-computed values), diverse
    `Jury` + disagreement set, position/verbosity/anonymize bias controls; `kappa_vs_human` in calibration.
  - **P3** `evals.py` — n-gram contamination, Goodhart gap, generalization gap, saturation→rotation;
    verifier **C10**.
  - **P4** `scheduling.py` — Thompson + UCB1 bandits (converge, sublinear regret) + meta-ranker
    (advisory ordering of Proposed experiments only).
  - **P5** `drift.py` — PSI/KL/JS/KS + champion-vs-challenger canary analysis wired into auto-rollback.
  - **P6** `control.py` — paraphrase (anti-collusion), honeypots, monitor ensemble, audit budget,
    graduated-autonomy gate (promotion/canary stay HUMAN-ONLY).
  - See `docs/improvement-roadmap-phases.md`.
- `ruff check src`: **all checks passed**.
- `mypy`: 32 errors, all `import-untyped` (missing yaml/httpx stubs) — same category as the
  pre-existing 16; **zero genuine type errors** in new code.
- Full existing ladder green and unweakened: `validate`, `cross-refs`, `forbidden-providers`,
  `schema`, `evals`, `improvement-validate`, `env-smoke`, `proactive-validate`,
  `standards-validate`, `mission-dryrun L0–L4`.

## Demonstrated experiment

Retrieval A/B (literal vs ranked search over the repo), full transcript in `E2E-PROOF.md`:
registered against an L2 mission → baseline (recall 0.0) → candidate (recall 1.0, safety held)
→ implementer refused self-verification → independent verifier 8/8 PASS → request human
promotion (rollback demonstrated) → **human** canary → **human** promote → post-watch. A second
experiment auto-rolled-back on a canary regression and stayed searchable. Board == Ledger.

## Judge calibration

Reference judge on the shipped set: precision 1.0, recall ≈0.85, **safety missed-defect rate
0.0**, 2 honest non-safety misses. Safety-first gate + anti-self-certification tested.
Unresolved: live LLM-judge numbers and human-agreement columns are not yet captured (the
deterministic reference judge is the offline stand-in).

## Human-attention findings

The structural bottleneck is the **human-promotion** step — by design (the wall working).
Recommended starting limits (wired): bottleneck warning at ≥5 awaiting promotion; stale
callout at 48h; `pct_independently_reproduced` should hold at 100%.

## Remaining work

- **code remaining**: none for breadth — **all 13 target types** now run end to end through
  the same machinery (`tests/test_all_target_types.py`), the Ledger REST surface is tested via
  TestClient, and the AppFlowy upsert logic via a fake client. The 11 generic harnesses are
  deterministic stand-ins; swapping in real measurements (e.g. a live prompt eval) is per-target
  work but needs no new machinery.
- **environment remaining**: the one untested line is the real network call to a reachable
  AppFlowy (the upsert logic is fully tested via a fake client); and real Ollama LLM-judge
  numbers (the prediction-scoring path is tested, the model call is env-blocked).
- **human-only actions**: promotion + canary (permanent, by design — and proven unreachable by
  an agent for every target type and on the REST surface).
- **blocked upstream**: live AppFlowy network upsert + a reachable Ollama judge.
- **future optional**: secret-scanning / dependency-audit wired as proactive evidence sources;
  swap the 11 generic harnesses for richer per-target measurements as needed.

## Final verdict

| capability | status |
|---|---|
| safe supervised improvement | **yes — exercised end to end** |
| independent verification | **yes — separation + reproduction + lying-implementer caught** |
| bounded experiments | **yes — budgets + stopping rules + equivalence** |
| human-gated promotion | **yes — Canary/Promoted human-only, structurally** |
| negative-result memory | **yes — terminal results retained + searchable** |
| judge calibration | **yes — for the deterministic reference judge; live judge pending** |
| attention governance | **yes — metrics + prioritized morning brief** |
| tested rollback | **yes — demonstrated-before-promote + auto-rollback on regression** |

No capability above is claimed that was not exercised by a passing test or the E2E transcript.
