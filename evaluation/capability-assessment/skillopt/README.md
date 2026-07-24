# AGT-17 · SkillOpt capability assessment

Adopting **microsoft/SkillOpt** (MIT) as a **champion-challenger** in the KPI
loop: it trains a deployable `best_skill.md` for a frozen model and accepts an
edit only if a held-out score improves — our evidence gate, in text space. It
also drives `claude_code_exec` / `codex_exec`, the executors the cockpit runs.

Follows the repo's `capability-assessment` precedent (abtop/semble/hermes).

| File | What |
|---|---|
| `PRE-REGISTRATION.md` | hypothesis, two-tier KPI framework (variety of scenarios), gates, knockouts — written BEFORE the run |
| `benchmark-plan.yaml` | A/B (champion vs challenger) design + metrics + governance |
| `acceptance-rubric.yaml` | knockouts, gates, decision ladder, pass thresholds |
| `threat-model.md` | egress/artifact/executor/Windows risk + mitigations |
| `install-manifest.json` | pinned version + commit + install + Windows notes |
| `config/searchqa-ollama-local.md` | exact reproducible local-gateway run recipe |
| `results.md` | LOCALLY_REPRODUCED evidence (install, wiring, materialize, baseline, full-loop + gate-reject) |
| `LEADERBOARD.md` | the KPI leaderboard (champion baseline + challenger rows) |
| `experiment.yaml` | continuous-upgrade champion-challenger record |
| `raw/` | trimmed provenance logs |

## Status (2026-07-24): WIRING_VERIFIED → heading into PILOT

**Proven on this Windows box, local stack:** installs; `openai_compatible →
Ollama qwen3:8b` wiring; SearchQA materialization; a real no-skill baseline
(`selection hard=0.6667`); and the **full loop E2E (EXIT=0)** with the
accept-only-if-improves **gate correctly rejecting non-improving edits**
(`accept=0 reject=2`). Two Windows blockers found + fixed (`PYTHONUTF8=1`;
`train_size` must match the split).

**Not yet claimed (honest):** no lift — an 8B optimizer proves the loop, not
capability. The lift evidence ("improvement across a variety of scenarios") is
the **next** run: a CAPABLE optimizer on ≥2 full-split scenarios, independently
reproduced → PILOT. Then Tier 2: a custom llm_station-task env via
`claude_code_exec`/`codex_exec` → ADOPT. Both are operator-gated (cost / the
approval walls). Nothing was installed into production, promoted, or merged.
