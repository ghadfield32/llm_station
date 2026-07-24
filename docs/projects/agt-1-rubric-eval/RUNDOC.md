# RUNDOC — AGT-1 packet 1 · Adaptive-rubric LLM-as-judge eval (methodology port)

Through the [`TODO_PROCESS.md`](../../todos/TODO_PROCESS.md) loop. Research verdict
(memory `research-verdicts-skillopt-postiz-agentscli`): **do NOT adopt the
google/agents-cli tool** (Google-Cloud/Gemini/ADK-coupled — violates local-first
+ the no-cloud-routes boundary); **PORT its eval methodology** (adaptive rubrics,
LLM-as-judge with a sampling count, rubric-verdict + loss-pattern analysis) into
our own local eval harness. This packet ships that port as a bounded,
**off-by-default, local-only, supporting-evidence-only** eval.

## 1. Objective & definition of done

A local adaptive-rubric LLM-as-judge scorer that grades a (prompt, response)
against a typed rubric of weighted criteria, runs the judge `sampling_count`
times for self-consistency, aggregates to a per-criterion + overall score with
agreement, and surfaces **loss patterns** (which criteria fail most across a
batch) — all as **supporting evidence only, never a promotion gate** (the
`framework-evals.yaml` contract). Done when: a typed `Rubric` schema
(`extra="forbid"`); a **pure** rubric scorer + loss-pattern analyzer (no model
call in the core, unit-tested); a `rubric_judge` framework runner following the
existing `frameworks/*_runner.py` pattern (judge call INJECTED, fake in tests,
missing/non-numeric score → `None`, never fabricated); registration in
`framework-evals.yaml` (enabled: false, local Ollama judge, `supporting_evidence_only`);
`make validate` + targeted tests + `make lint` green.

## 2. Research (verified seam map, 2026-07-24; main @ 44bb172)

- **Home = `src/command_center/improvement/`** (the eval/leaderboard package):
  - `jury.py` — the LLM-as-judge harness ALREADY has the diverse panel + majority
    vote + disagreement set + inter-rater agreement (Cohen's κ `cohens_kappa`,
    Fleiss' κ, Krippendorff's α, `agreement_label`) + bias controls
    (`position_consistent`, `verbosity_bias_slope`, `anonymize`). Its docstring:
    judges "can reject/flag but never promote", and "a real diverse LLM panel
    slots in behind the same `Jury` interface when models are reachable". **Reuse
    its agreement math for the sampling-consistency metric; do NOT duplicate it.**
  - `frameworks/runner.py` — `FrameworkResult(framework, informs_role, status,
    note, metric, score, dataset, n_samples)` + `run_framework(FRAMEWORK, spec,
    parse_fn=, subprocess_runner=, available_fn=)`. Each runner
    (`frameworks/evalplus_runner.py`, `bigcodebench_runner.py`) defines a
    `FRAMEWORK` name + a `parse_*` fn + `run(spec, ...)`. The runner OWNS parsing
    (unit-tested); the executor is INJECTED (never auto-launched, never tested
    live); **a missing/non-numeric score becomes `None` (never fabricated)** —
    follow this exactly, with the judge-model call as the injected executor.
  - `benchmark_scoring.py`, `evals.py` — how framework results feed the loop.
- **Config precedent** = `configs/framework-evals.yaml`: frameworks are
  `enabled: false`, `backend: openai_compatible`, `base_url_env:
  OLLAMA_OPENAI_BASE_URL`, `sample_budget: N`, `trust: supporting_evidence_only`
  ("they can never be a promotion gate; the repo role suites decide"). Register
  `rubric_judge` here in the same shape (+ `judge_role: local-judge`,
  `sampling_count`).
- **Judge role** = `configs/judges.yaml` local-only array (`local-judge`,
  `max_cost_usd: 0.0`, fails closed if Ollama down). The rubric judge uses the
  `local-judge` alias — no external egress, no provider key.
- **Schema home** = `src/command_center/schemas/contracts.py` (the typed,
  `extra="forbid"` contracts; framework-eval specs live in this world). Add the
  `Rubric`/`RubricCriterion` schema here (or the nearest schema module the
  framework-evals spec already uses — match the existing pattern).
- **agents-cli methodology** (verified from its docs): a metric = `prompt_template`
  with `{prompt}`/`{response}`/`{agent_data}` placeholders + `judge_model` +
  `judge_model_sampling_count` (1–32); the judge returns
  `{"score": <numeric>, "explanation": "<reason>"}`; analyze rubric verdicts +
  loss patterns to drive improvements. Port the SHAPE, not the Google client.
- Test anchors: `tests/` has framework-runner + jury tests (e.g.
  `test_*jury*`, `test_*framework*`/`test_evalplus*`) — mirror them; `make
  validate` covers the new config; `test_safety_boundaries` / the
  forbidden-provider scan must stay green (local-only judge, no provider route).

## 3. KPIs & baseline

| KPI | Baseline | Target |
| --- | --- | --- |
| structured rubric scoring of an output | none (jury.py gives labels, not weighted-criteria rubric scores) | per-criterion + weighted-overall score + agreement across N samples |
| loss-pattern visibility | none | ranked criteria-failure counts across a batch |
| contract safety | n/a | `supporting_evidence_only`, never a promotion gate — proven by a test |
| validate/lint/tests | green | green |

## 4. Plan (bounded — backend/config only)

1. **Schema** (`contracts.py` or the framework-evals schema module): typed
   `extra="forbid"` `RubricCriterion` (name, guidance, weight>0, scale e.g. 1–5)
   + `Rubric` (id, criteria non-empty, weights validated, prompt_template with the
   required placeholders, `sampling_count` bounded 1–32, `judge_role`). Validate
   at load; fail loud on a bad rubric (no silent defaults).
2. **Pure scorer** (`improvement/rubric.py`): given per-criterion, per-sample
   numeric judge scores → aggregate: per-criterion central value (median across
   samples) + per-criterion sample-agreement (reuse jury.py's κ/agreement math),
   then weighted-overall from criterion weights; return a typed `RubricVerdict`
   (overall, per-criterion score+agreement+explanations). PURE — no model call,
   no I/O; fully unit-tested. Missing/non-numeric sample → dropped, and if a
   criterion has zero valid samples its score is `None` (never fabricated); an
   overall with any `None` criterion is flagged, not silently imputed.
3. **Loss-pattern analyzer** (same module): given a batch of `RubricVerdict` +
   a pass threshold → ranked `Counter` of criteria that fail most (the
   improvement signal). Pure, unit-tested.
4. **Runner** (`frameworks/rubric_judge_runner.py`): `FRAMEWORK = "rubric_judge"`,
   a `parse_rubric_judge` that normalizes the judge's `{score, explanation}` JSON
   per criterion (missing/non-numeric → `None`), and `run(spec, *, judge_runner=,
   available_fn=)` following `run_framework`'s injected-executor pattern — the
   `judge_runner` (a callable that calls the local Ollama judge with the rendered
   template) is INJECTED so tests pass a fake judge; never auto-launched, never
   tested live. Emits `FrameworkResult`s (metric `rubric_score`,
   `supporting_evidence_only` note).
5. **Config**: add `rubric_judge` to `configs/framework-evals.yaml`
   (enabled: false, backend openai_compatible, base_url_env OLLAMA_OPENAI_BASE_URL,
   judge_role local-judge, sampling_count, sample_budget, trust
   supporting_evidence_only) + the schema/validator so `make validate` accepts it.
6. **Tests** (`tests/`): schema validation (bad weights/placeholders rejected),
   scorer aggregation (weighted overall, median-across-samples, agreement),
   None-handling (never fabricated), loss-pattern ranking, parse fn
   (missing→None), and a **contract test**: `rubric_judge` trust ==
   `supporting_evidence_only` and it is NOT in any promotion path (never a gate).
7. Verify: `make validate`, targeted `pytest` (new tests + `test_safety_boundaries`
   + jury/framework tests), `make lint`.

**Allowed files**: `src/command_center/improvement/rubric.py` (new),
`src/command_center/improvement/frameworks/rubric_judge_runner.py` (new),
`src/command_center/schemas/contracts.py` (schema add — extend, don't break),
`configs/framework-evals.yaml`, `tests/test_rubric_eval.py` (new), and IF the
framework-evals spec/validator lives elsewhere, that exact module. This RUNDOC.
**Forbidden**: `services/agent_kanban_ui/**` (all the open UI PRs), `judges.yaml`
routing changes, the Judge Gate (`services/judge_gate/**`), `promotion.py` /
any promotion path (rubric-judge must NEVER become a gate), `.env`, provider
routes (`frontier-router-*`), `package.json`.

## 5. Open questions / decisions (defaults under standing "continue")

1. **Off-by-default + local-only + supporting-evidence-only** (default, non-
   negotiable): mirrors framework-evals; the rubric judge uses the `local-judge`
   Ollama alias — no external egress, no provider key, and it can flag/inform but
   NEVER promote. Rationale: the CLAUDE.md quality-vs-serving separation + the
   no-cloud-routes boundary + the agents-cli verdict (port methodology, not the
   cloud tool).
2. **Sampling = same-judge self-consistency** (default): `sampling_count` runs
   the SAME local judge N times and aggregates (distinct from jury.py's DIVERSE
   panel — the two compose later). Packet 1 does the sampling dimension; a
   diverse-panel-of-rubric-judges is a later slice (recorded).
3. **Median across samples, weighted mean across criteria** (default): robust to
   an outlier sample; weights come from the rubric. Adjustable.
4. **Never impute a missing score** (default, hard): a criterion with no valid
   sample is `None` and flagged; the overall is not silently completed.

## 6. Model allocation (resolve live 2026-07-24)

- Implementation: `deep_code` → current lowest-priority Sol model
  (`gpt-5.6-sol`, priority:1 via `codex debug models`), effort **xhigh** — durable
  typed contracts + correctness-sensitive aggregation/agreement math + a hard
  never-promote contract. Isolated worktree off origin/main, detached (no wrapper
  timeout shorter than verify), fail-closed on blocked verification.
- Independent review: Fable (non-author), lenses: (a) supporting-evidence-only /
  never-a-gate contract holds, (b) no fabricated/imputed scores, (c) local-only
  judge (no provider route), (d) reuses jury.py math (no duplication).
- Fallback: if Codex is unavailable/blocked → STOP and surface; never silent
  self-implementation.

## 7. Links

- Master item: [`docs/todos/GRAND_TODO_LIST.md`](../../todos/GRAND_TODO_LIST.md) → AGT-1
- Precedents: `improvement/jury.py` (agreement math + never-promote), the
  `frameworks/*_runner.py` pattern, `configs/framework-evals.yaml` contract.
  Complements AGT-17 (SkillOpt) — both are quality-eval, both supporting-evidence.
  Leaderboard theme: AGT-12.

## 8. Execution log

- 2026-07-24 — Run-doc created from the improvement/ seam map (jury.py +
  frameworks/runner.py + framework-evals.yaml). Packet 1 launching: port the
  agents-cli adaptive-rubric LLM-as-judge methodology as an off-by-default,
  local-only, supporting-evidence-only eval. Branched off main (backend/config —
  disjoint from all open UI PRs).
- 2026-07-24 — Packet 1 implemented in the bounded allowlist: strict rubric
  contracts; pure median/weighted scoring with `jury.py` Cohen's κ agreement,
  fail-closed missing-score handling, and ranked loss patterns; injected local
  rubric-judge runner; off-by-default local Ollama config; and contract tests
  proving supporting-evidence-only/non-gating behavior.
- 2026-07-24 — Verification: the repository's actual entry point
  `python -m command_center.cli.main validate` passed config validation,
  cross-references, rendering, and forbidden-provider checks (the requested
  `python -m command_center.cli validate` form cannot start because the package
  has no `command_center.cli.__main__`). Ruff passed for all `src/` and the
  changed test. The rubric + safety + jury + framework suite passed 44 tests
  with `--noconftest -p no:cacheprovider`. The exact requested rubric + safety
  pytest command was also run, but the sandbox denied pytest access to
  `C:\Users\ghadf\AppData\Local\Temp\pytest-of-ghadf`; all 19 selected tests
  stopped in the suite-wide `tmp_path` fixture before assertions. Isolated mypy
  passed for both new modules with imports skipped; full mypy remains red on six
  pre-existing errors in unchanged research-topic code in `contracts.py`.
  `make` is not installed in this environment. Pytest-created ignored temp
  directories could not be removed because recursive deletion is policy-blocked;
  no temp path is staged.
- 2026-07-24 — Git staging/commit blocked by the managed worktree boundary.
  Explicit `git add` of only the six allowed deliverables failed with
  `fatal: Unable to create 'C:/Users/ghadf/vscode_projects/docker_projects/llm_station/.git/worktrees/agt1-rubric/index.lock': Permission denied`.
  Nothing was staged, the required commit was not created, and nothing was
  pushed.
- 2026-07-24 — Reviewer (Fable, non-author; Codex/Sol implemented) completed the
  sandbox-blocked host verification and committed. Host results (PYTHONPATH pinned
  to this worktree): `cc validate` exit 0 (config + cross-refs + **forbidden-providers
  PASS** — no provider route added); `pytest test_rubric_eval + test_safety_boundaries
  + test_jury + test_framework_evals` exit 0 (44 tests); `ruff` clean; `mypy` clean on
  both new modules ("no issues found"). The 6 full-repo mypy errors are in unrelated
  `normalize_research_topics` code (contracts.py L1393-1419), pre-existing on main
  (renumbered by AGT-1's added lines), and non-blocking (the repo has merged PRs with
  them). Independent review APPROVED on all four lenses: (a) never-a-gate — machine-
  proven by `test_runner_...` asserting `is_decision_gate() is False` + the
  `promotion_paths` check; (b) no fabricated/imputed scores — `overall = None if
  missing`, `_numeric` drops bool/non-Real/non-finite/out-of-scale; (c) local-only —
  `judge_role: local-judge`, `base_url_env: OLLAMA_OPENAI_BASE_URL`, enabled:false, no
  provider key; (d) reuses jury.py κ math (no duplication). Committing.
