# SkillOpt KPI Leaderboard (AGT-17)

Champion-challenger board per CLAUDE.md. **Champion** = frozen target + the
env's initial/no-learned skill. **Challenger** = same target + a SkillOpt-trained
`best_skill.md`. A row is admitted ONLY with reproducible runtime evidence and
all `acceptance-rubric.yaml` gates. Promote a challenger to champion ONLY when it
beats the incumbent on held-out test AND clears the same gates. Unknowns are
recorded as unknown, never estimated.

## Tier 1 — standard benchmarks (variety of scenarios)

### SearchQA (retrieval / multi-hop factoid QA)

| # | role | target | optimizer | split (tr/sel/test) | selection hard | test hard | gate | commit | provenance |
|---|------|--------|-----------|---------------------|----------------|-----------|------|--------|------------|
| baseline-0 | **champion (no-skill)** | qwen3:8b (Ollama) | — | 3-item selection | **0.6667** (soft 0.8889) | — | n/a | skillopt@fdeebaf | `raw/searchqa_baseline.log` — CONFIRMED |
| chal-1 | challenger (trained skill) | qwen3:8b (Ollama) | qwen3:8b | 6/3/3 tiny | 0.6667 (2 edits **gate-REJECTED**, accept=0) | 0.6667 (best-on-val); noise on 3 items | use_gate=true | skillopt@fdeebaf | `raw/searchqa_e2e.log` — EXIT=0, wall=167s. Loop + gate-reject PROVEN; NOT a lift claim |

> Note: qwen3:8b as optimizer proves the **loop**, not capability — no lift is
> claimed from an 8B optimizer. The PILOT lift rows (a CAPABLE optimizer on the
> full split) are the next runs and land here with full provenance.

### Other Tier-1 scenarios (pending materialization + capable-optimizer run)
| scenario | type | status |
|---|---|---|
| OfficeQA | office-doc tool-use QA | pending doc materialization |
| LiveMathematicianBench | competition math | pending HF materialization |
| SpreadsheetBench | spreadsheet ops | pending payload materialization |
| ALFWorld | embodied planning | pending alfworld-download |

## Tier 2 — llm_station cockpit tasks (the adoption prize)
| env | harness | status |
|---|---|---|
| custom llm_station env (run-doc / packet / review tasks) | claude_code_exec / codex_exec | not started — operator-gated; built from `skillopt/envs/_template/` |

## Promotion log
- (none yet) — WIRING_VERIFIED; no challenger has cleared the PILOT bar
  (capable optimizer, >=2 scenarios, independently reproduced).
