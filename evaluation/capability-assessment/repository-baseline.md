# Repository baseline — Stage 0 preflight

Evaluation: Batch 1 (semble, abtop, asm) per `docs/capability-evaluation-loop.md`.
Date: 2026-06-12. Operator: Claude Code session (Implementer/Investigator roles;
Verifier runs in a separate context).

## Repository state

- **Repo**: `llm_station` (command center), Windows workstation.
- **Git**: branch `master`, **zero commits** — the entire tree is untracked.
  - **Deviation from the loop**: branch/worktree isolation is impossible with
    no initial commit. Mitigation: this evaluation is **strictly additive** —
    new files under `evaluation/capability-assessment/` and reversible local
    package installs only; no existing file is modified except the documented
    Part C/changelog updates. Rollback = delete the directory + `uv pip
    uninstall` the candidates.
- **Language/stack**: Python 3.12.6, `uv 0.8.11` (uv-managed venv,
  `pyproject.toml` + `uv.lock`), Docker Compose control plane, Pydantic
  contract layer.
- **Pre-existing uncommitted changes**: everything (no commits yet) — recorded,
  not touched.

## Current capability per candidate seam

| Seam | What exists today |
|---|---|
| Repository retrieval (semble) | ripgrep 14.1.1 + Claude Code native Glob/Grep/Read; no semantic index |
| Agent observability (abtop) | `scripts/usage_digest.py` → `generated/usage-digest.md` (LiteLLM spend + Ledger missions); no live session/process monitor. At baseline-time: 2 live `claude.exe` + 3 live `codex.exe` processes (good test conditions). |
| Skill management (asm) | **No skill files exist**: no `~/.claude/skills`, no `~/.claude/commands`, no `.claude/skills` in-repo; `~/.claude/plugins` holds only `blocklist.json` + `installed_plugins.json`; Codex side has `AGENTS.md` only. Skill governance policy exists in `configs/standards.yaml` (`skill_updates`, L2 cap) but there is no inventory to manage. |

## Governance mechanisms (must remain authoritative)

- Model gateway: LiteLLM (local-only, virtual keys); no provider API keys
  anywhere (validated by `scripts/check_forbidden_providers.py`).
- Approval: AppFlowy drag-to-Approved + kanban bridge + Ledger L3/L4 holds.
- Isolation: one mission → one lease → one worktree → one devcontainer
  (repo_task secret-free).
- GitHub wall: branch protection plan per `docs/github-safety.md`.

## Deterministic baseline (all PASS, zero pre-existing failures)

| Command | Result | Wall time |
|---|---|---|
| `python scripts/validate_config.py` (11 configs) | PASS | 0.31 s |
| `python registry/render.py` (6 roles) | PASS | 0.31 s |
| `python scripts/run_evals.py` | PASS | 0.29 s |
| `python scripts/smoke_mission.py` (L0–L4 dryrun) | PASS | 0.31 s |

(Single timings — these are smoke gates, not the timing-sensitive benchmark;
the retrieval benchmark uses its own repetitions.)

Not run at baseline: `growth-os selftest.py` (requires the live
AppFlowy/Ollama/LiteLLM/Ledger/Airflow stack; out of scope for these three
read-only/local candidates), `make live-smoke` (same reason). Recorded as
NOT_RUN, not as passing.

## Problem statements (Stage 0 requirement)

- **semble**: Claude Code/Codex sessions burn context reading files found via
  ripgrep/Glob over a ~19-doc + multi-service repo (and betts_basketball,
  which is far larger). Hypothesis: a local semantic index returns the right
  snippets with fewer tokens. Measurable: retrieval recall on a gold set +
  tokens-to-answer.
- **abtop**: no live view of running agent sessions/tokens/rate limits;
  usage-digest is retrospective. Hypothesis: a read-only monitor improves
  operator awareness and could feed the morning brief. Measurable: correct
  detection of the live sessions recorded above; stable JSON.
- **asm**: **no current problem** — zero skill files exist across providers.
  Pre-registered expectation (Part C) was PILOT for inventory/audit; Stage 0
  reality check says the seam is empty today. Per the loop: a candidate with
  no repository-specific problem statement is `NO_JUSTIFIED_USE_CASE` and may
  not proceed to installation.
