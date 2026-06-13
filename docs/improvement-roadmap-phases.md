# Improvement loop — measurement-science roadmap (Phases 1–6)

The base loop (registry, runner, independent verifier, promotion/canary/rollback, sealed evals,
calibration, attention, proposals — `improvement-loop.md`) answers *can we run a human-gated
experiment*. This doc covers the **measurement-science layers** built on top of it, in the order
the research roadmap prioritizes them. Every layer feeds the **Proposed → Verified** portion
(eligibility, evidence, the verifier's reject path) or **scheduling of Proposed experiments** —
**none** can approve, promote, canary, or merge. Promotion and canary stay human-only throughout.

> **Status legend**: **[implemented]** code exists · **[tested]** a deterministic test exercises it ·
> **[blocked]** needs a live model/stack · **[human]** human action by design.

## Phase 1 — statistical rigor for baseline-vs-candidate

**[implemented] [tested]** `statistics.py`, `tests/test_statistics*.py`. Pure stdlib (no numpy/scipy).

| capability | what it gives | test |
|---|---|---|
| bootstrap CIs | distribution-free uncertainty on every metric | CI contains mean, deterministic |
| paired/unpaired diff tests | catch a misreported result | shift detected, null not significant |
| Benjamini-Hochberg FDR | multiplicity control across metrics/targets | rejection count vs hand value |
| **mSPRT** always-valid p | continuous monitoring with no peeking penalty (Ville's inequality) | null FP-rate ≤ α over 400 streams; early-stop on a real effect |
| **CUPED** | ~halve variance using the baseline as covariate (Bing, WSDM 2013) | >50% variance cut on correlated data; mean preserved |
| SRM chi-squared | invalidate a broken baseline/candidate split (p < 0.001) | 600/400 flagged, 520/480 not |
| power / MDE | pre-registered minimum detectable effect | formula match; underpowered → INCONCLUSIVE |
| A/A | false-positive-rate control proof | FP ≈ α |

Wired into the runner (each candidate run carries a multidimensional `StatisticalReport` as a
hashed `statistics.json` artifact) and the verifier (**C9**, off by default via
`statistics.require_significance`; when on: SRM→FAIL, underpowered→INCONCLUSIVE, significant FDR
+mSPRT win→PASS, else FAIL — reject-only).

## Phase 2 — judge/jury hardening

**[implemented] [tested]** `jury.py`, `tests/test_jury.py`. LLM-judge bias is large and unsolved;
the practice is a diverse panel + bias controls + agreement-with-humans tracking.

- **Cohen's κ / Fleiss' κ / Krippendorff's α** — verified against hand-computed values (κ=0.4 table,
  Fleiss=−1/3, α≈0.696). `kappa_vs_human` is now a field on every `CalibrationReport`.
- **`Jury`** — diverse-judge panel, majority vote, **disagreement set** routed to human attention;
  mean pairwise κ reports panel cohesion.
- **bias controls** — position-swap consistency, verbosity-bias slope (score vs length), identity
  anonymization (attacks self-preference).
- **[blocked]** a *live* diverse LLM panel needs reachable models; the `Jury` interface accepts them.

## Phase 3 — anti-Goodhart eval infrastructure (permanent)

**[implemented] [tested]** `evals.py`, `tests/test_antigoodhart.py`. Goodhart is the default failure
mode of optimization, so these are permanent, not a milestone.

- **contamination detection** — fuzzy n-gram overlap of any sealed item with implementer-visible
  evidence (catches paraphrased leakage the exact-match scan misses). Verifier **C10**.
- **Goodhart gap** — proxy improvement − held-out improvement; large positive = gaming the proxy.
- **generalization gap** — visible − sealed; large gap auto-routes to Inconclusive (existing C5).
- **saturation → rotation** — a suite all recent candidates ace is recommended for retirement.

## Phase 4 — smarter experiment selection (advisory only)

**[implemented] [tested]** `scheduling.py`, `tests/test_scheduling.py`. Allocates scarce
run/review capacity across **Proposed** experiments; output is advisory (feeds the brief/scheduler).

- **Thompson sampling** (Beta-Bernoulli) and **UCB1** — both converge to the best arm; cumulative
  regret stays sublinear (far below random-arm play).
- **`MetaRanker`** — Laplace-smoothed P(verify | feature) from Ledger outcomes; ranks proposals.
- **`recommend_order`** — orders Proposed experiments by expected value. It cannot run or promote.

## Phase 5 — drift detection + formal canary analysis

**[implemented] [tested]** `drift.py`, `tests/test_drift.py`.

- **PSI** (stable < 0.1 / moderate / significant > 0.2), **KL** (asymmetric), **Jensen-Shannon**
  (symmetric, ≤ ln 2), **KS** two-sample — all checked against known/closed-form values.
- **`evaluate_canary`** — champion-vs-challenger per-metric regression with reasons; any safety
  regression forces it. Wired into `PromotionController.evaluate_canary_metrics`, which routes a
  detected regression through the existing **reversible/local/within-tier auto-rollback** (a safe
  reversion — not a forward promotion). `ramp_schedule` gives the 5→20→50→100 progressive delivery.

## Phase 6 — AI-control for the autonomy frontier

**[implemented] [tested]** `control.py`, `tests/test_control.py`. Hardens the reject path and
formalizes *how much evidence reaches a human* — never removes the human.

- **`paraphrase`** — deterministic canonicalization (strip comments / zero-width / identity markers)
  before the monitor reads implementer output, breaking collusion/steganographic channels.
- **honeypots** — planted-attack fixtures; a monitor that misses one is itself flagged (`catch_rate`).
- **`MonitorEnsemble`** — trusted + untrusted monitors; flag on any catch (defense in depth) and
  surface trusted-vs-untrusted **disagreement** as a collusion signal.
- **`audit_budget`** — top-K most-suspicious actions for scarce human review.
- **`autonomy_gate`** — required evidence per L0–L4 tier before a candidate is *eligible* to reach a
  human (L4 also needs independent replay). **Eligibility only — promotion/canary stay HUMAN-ONLY.**

## Observability / dashboard spec

Do **not** collapse the metric space (collapsing invites Goodhart). One OEC per target type plus
explicit guardrails, visualized multidimensionally. Dashboards to build from the data already
recorded in the Ledger + `StatisticalReport`s:

1. **Evaluation leaderboard** — candidate vs baseline per metric, CIs, sealed/held-out columns, the
   generalization gap highlighted.
2. **Experiment funnel** — counts/rates Proposed→…→Promoted. Expect a sobering base rate: most
   candidates fail (Kohavi: ~10–35% of experiments improve their metric; >90% at well-optimized
   surfaces). Design the human-attention budget around that.
3. **Time-to-decision** — latency per stage, esp. Awaiting Verification / Awaiting Human Promotion.
4. **Reviewer-override panel** — how often humans promote against / reject with the verifier signal.
5. **Post-promotion regression** — 1h/24h/7d rollbacks, attributed to proposal class.
6. **Judge/jury health** — κ/α vs gold, bias slopes, disagreement-set size.
7. **Drift & safety** — PSI/KL on inputs and judge scores; honeypot catch rate; behavior drift.
8. **Calibration** — ECE/Brier + reliability diagrams (judges and the risk model).

## Open problems (honest)

Several pillars are monitored risks, not solved engineering: detecting *naturally emergent*
deception (probes are validated only on planted backdoors); credit assignment over long agent
traces; scalable oversight at large capability gaps; and contamination detection (limited success
in the literature — hence rotating, post-cutoff sealed sets). LLMs cannot reliably self-correct
without external feedback — the empirical bedrock under the no-self-promotion wall. Goodhart is
guaranteed under optimization pressure: the sealed-eval / guardrail / multidimensional discipline
is a permanent cost, not a phase that finishes.
