# AGT-17 · SkillOpt — pre-registration (written BEFORE the measured run)

Adopting **microsoft/SkillOpt** as a **challenger** in the champion-challenger
KPI loop (CLAUDE.md "Goal-Driven KPI Leaderboard Loop"). This document fixes
the hypothesis, KPIs, test scenarios, gates, and knockouts *before* the measured
run so results cannot be rationalized after the fact (the abtop/semble
Stage-5 "benchmark plan written before implementation" discipline).

/ Tracker: AGT-17. License: MIT. Version pinned: see `install-manifest.json`.

## 1. What SkillOpt is (verified, not assumed)

A text-space optimizer that treats a single natural-language skill document as
trainable parameters for a **frozen** model: it rolls out on scored tasks,
proposes bounded add/delete/replace edits to the skill via a separate optimizer
model, and **accepts an edit only if a held-out validation score strictly
improves** (`evaluation.use_gate: true`). The deployable artifact is a compact
`best_skill.md`. Its accept-only-if-improves gate **is** our champion-challenger
evidence gate, implemented in text space — which is the core reason it fits.

Verified locally on this Windows workstation (2026-07-24), see `results.md`:
- Installs and imports (v0.2.0); `scripts/train.py` runs.
- Its `openai_compatible` backend initializes against our **local Ollama
  gateway** (`http://localhost:11434/v1`, `qwen3:8b`) with a dummy key — **no
  external egress, no provider key** — and the trainer loads config, splits, and
  the initial skill and reaches the baseline-evaluation stage.
- Its `--backend` set includes `claude_code_exec` and `codex_exec` — it can
  drive the **exact executors the cockpit already runs**, which is what makes
  Tier 2 (below) possible.

## 2. Hypothesis

> A SkillOpt-trained `best_skill.md`, deployed against a frozen target, raises
> task success on held-out tasks versus the same target with no learned skill,
> and does so under SkillOpt's own accept-only-if-improves gate — first on
> standard benchmarks (variety of scenarios), then on llm_station's own
> cockpit-agent tasks.

## 3. KPIs and the two tiers of test scenarios

The champion is always **the frozen target with the initial/no learned skill**;
the challenger is **the same target with the trained `best_skill.md`**. Primary
KPI = **held-out test accuracy** (`evaluation.gate_metric: hard`, exact/graded
match), champion vs challenger, per scenario. Secondary KPIs = per-task latency,
tokens, and the number of gate-accepted edits (skill growth).

### Tier 1 — Validation across a VARIETY of standard scenarios (de-risk)

Reproduce SkillOpt's gated lift locally across genuinely different task types,
so "it helps" is proven on our stack before we invest in a custom environment.
The bundled benchmarks span the variety:

| Scenario | Type | Runnable locally? |
|---|---|---|
| SearchQA | retrieval / multi-hop factoid QA (context provided inline) | **yes** — self-contained after `materialize_searchqa.py`; text-only |
| OfficeQA | office-document tool-use QA | needs doc materialization (`officeqa_full.csv` + docs) |
| LiveMathematicianBench | competition math reasoning | needs HF materialization of the four monthly files |
| SpreadsheetBench | spreadsheet manipulation | needs spreadsheet payloads |
| ALFWorld | embodied/agentic text-game planning | needs `alfworld-download` + `$ALFWORLD_DATA` |
| DocVQA | document **visual** QA | needs a vision target (out of scope for qwen3 text) |

Tier-1 acceptance = **≥2 scenarios** show a **non-negative, gate-accepted**
held-out delta with a capable optimizer, independently re-run. SearchQA is the
first (self-contained); a second text scenario (OfficeQA or LiveMath) follows.
Each result lands on `LEADERBOARD.md` with full provenance.

### Tier 2 — Adoption: llm_station's OWN cockpit-agent tasks (the prize)

The value to us is not beating math benchmarks — it is a `best_skill.md` that
makes **our Claude Code / Codex executors better at llm_station's recurring
work**: writing a bounded run-doc, implementing a packet under DESIGN.md,
running an independent review, fail-closed verification. Build a custom SkillOpt
env (the shipped `skillopt/envs/_template/`) over a held-out set of
representative cockpit tasks with deterministic graders, trained through the
`claude_code_exec` / `codex_exec` backends. Tier-2 acceptance = the challenger
skill beats the no-skill champion on held-out llm_station tasks AND clears the
normal walls. This is the ADOPT-decision evidence and is **operator-gated**
(runs the paid/loopback executors, must respect the Ledger/approval walls).

## 4. Gates (a result COUNTS only if all hold)

1. **SkillOpt's own gate**: `use_gate: true` — an edit is kept only if it
   improves the held-out selection score. No ungated skills scored.
2. **Reproducibility**: fixed `seed`, pinned SkillOpt commit, pinned target +
   optimizer, exact command recorded; the number re-runs.
3. **Independent verification**: a fresh, non-authoring session re-runs the
   champion-vs-challenger eval before any promotion (CLAUDE.md reviewer
   independence).
4. **No leakage**: test split never seen during training/selection
   (`split_mode: split_dir` with disjoint train/val/test).
5. **Honesty**: unknown values recorded as unknown, never estimated
   (`unknown_values_policy: record unknown; do not estimate`).

## 5. Knockouts (any TRUE ⇒ DEFER, per abtop/semble governance)

- Requires a provider API key or external egress for the **local** path — **NO**
  (verified: Ollama, dummy key, no egress).
- License non-permissive — **NO** (MIT).
- Writes skills into agent config dirs without approval — **NO** (writes
  `best_skill.md` to `out_root`; deploying a skill INTO Claude Code/Codex is a
  separate, operator-gated step, never automatic).
- Cannot run on Windows — **NO** (installs + wires + reaches baseline eval;
  full run needs the documented materialize step, which is a data step, not a
  platform block).

## 6. Model allocation

- Smoke/feasibility target+optimizer: **qwen3:8b via local Ollama** (free,
  on-box) — proves wiring, not capability.
- Tier-1 measured run optimizer: a **capable** model (Sol/Claude via their
  native SkillOpt backends, or a frontier via the gateway's opt-in lane) — an
  8B optimizer is too weak to expect real lift; capability is a cost/authority
  decision recorded per run.
- Independent verifier: fresh non-authoring session (cross-family).

## 7. Decision ladder (abtop/semble precedent)

INSTALL-VERIFIED → WIRING-VERIFIED → **PILOT** (measured Tier-1 lift on ≥2
scenarios, independently reproduced) → **ADOPT** (Tier-2 lift on held-out
llm_station tasks + clears the walls). We are at WIRING-VERIFIED heading into
Tier-1; see `DECISION.md` when the measured runs land.
