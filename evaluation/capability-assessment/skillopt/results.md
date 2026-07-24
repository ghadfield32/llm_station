# Results — SkillOpt (AGT-17), measured 2026-07-24 (Windows 11, local stack)

All evidence LOCALLY_REPRODUCED on this workstation against the running local
stack (`cc doctor`: ollama/litellm/ledger reachable = PASS). Raw logs in `raw/`.

## Status: WIRING_VERIFIED (heading into PILOT)

### CONFIRMED — install + Windows
- SkillOpt v0.2.0 clones + `uv pip install -e .` (exit 0) + `import skillopt`
  OK + `scripts/train.py --help` works. `--backend` set includes
  `claude_code_exec` and `codex_exec` (drives our executors — enables Tier 2).

### CONFIRMED — local-gateway wiring (no egress, no provider key)
- `model.target_backend=openai_compatible` + `TARGET_OPENAI_COMPATIBLE_BASE_URL=
  http://localhost:11434/v1` + model `qwen3:8b` + dummy key → the trainer prints
  `optimizer=qwen3:8b (openai_compatible) target=qwen3:8b (openai_compatible)`,
  loads config/splits/initial skill, and reaches the baseline-evaluation stage.
  Everything on-box; no external egress; no provider key.

### CONFIRMED — materialization works
- Bundled `data/*_id_split/` are lookup manifests (IDs only), not runnable
  payloads. `uv pip install datasets` + `python scripts/materialize_searchqa.py`
  downloaded public `lucadiliello/searchqa` and wrote runnable splits:
  **train=400, val=200, test=1400**. (Other benchmarks need per-benchmark
  materialization; only SearchQA ships a materialize script.)

### CONFIRMED — real baseline (champion) number
- SearchQA, no-skill initial skill, qwen3:8b via Ollama, 3-item selection set:
  per-item rollouts acc = 1.000 / 0.500 / 0.667 →
  **`[baseline result] selection hard=0.6667 soft=0.8889 gate[hard]=0.6667`**.
  This is a genuine champion baseline from the local stack (raw:
  `raw/searchqa_baseline.log`). The training loop then executed rollouts
  (epoch 1, step 1) before the Windows crash below.

### CONFIRMED — two Windows blockers (found + fixed / documented)
1. `UnicodeEncodeError: 'charmap' codec can't encode '→'` — the optimizer
   prints non-cp1252 chars (e.g. `->`) that crash the default Windows console
   mid-run. **Fix: `PYTHONUTF8=1`** (applied in later runs; abtop "POSIX-first
   on Windows" lesson).
2. `train_size` must EQUAL the loaded split when `split_mode=split_dir`
   (searchqa config hardcodes `train_size: 400`). A custom/tiny split needs a
   matching `train.train_size` override — a config-bookkeeping requirement, not
   a bug.

### CONFIRMED — full-loop E2E completes on Windows (EXIT=0), gate works
SearchQA tiny 6/3/3, qwen3:8b target+optimizer via Ollama, 1 epoch, `PYTHONUTF8=1`
(raw: `raw/searchqa_e2e.log`; wall=167s):
- Baseline selection `hard=0.6667`.
- **2 training steps, both edits GATE-REJECTED** (`accept=0 reject=2`): step 1
  `REJECT hard=0.3333 <= 0.6667`, step 2 `REJECT hard=0.6667 <= 0.6667`. The
  optimizer *did* propose edits (skill grew 104→107→163 chars, artifacts
  `skills/skill_v0000..0002.md`, `steps/step_0001/candidate_skill.md`) — the
  gate correctly refused both because neither improved the held-out selection
  score. `best_score=0.6667 (step 0)`.
- Held-out TEST (3 items, `valid_unseen`): init/baseline `test_hard=1.0000`,
  best-on-val `test_hard=0.6667`, final/last `test_hard=1.0000`. On 3 items
  these are **small-sample noise, NOT a lift signal** — correctly no promotion.
- **The single most important verified property**: SkillOpt's accept-only-if-
  improves gate rejects non-improving edits — the champion-challenger safety
  guarantee, demonstrated live on our stack. Emitted `meta_skill_result.json`,
  `slow_result.json`, per-step candidate skills.

## What this does NOT yet show (honest gaps → next steps)
- **No lift claim.** A PILOT lift number requires a CAPABLE optimizer (Sol/Claude
  native backend, or a frontier via the opt-in lane) on the full split, across
  **≥2 scenarios** (variety), independently reproduced. That is the next run;
  it lands on `LEADERBOARD.md`.
- **Tier 2 (llm_station cockpit tasks) not started** — the real adoption prize;
  operator-gated (drives claude_code_exec/codex_exec under the walls); env built
  from `skillopt/envs/_template/`.

## Disposition
**PILOT-track** (abtop/semble precedent): tool is install- and wiring-verified
with a real baseline; recommend proceeding to the capable-optimizer Tier-1 runs,
then the Tier-2 custom env. No repo/config/agent change was made; nothing
promoted. Await operator go for the (cost-bearing) capable-optimizer run.
