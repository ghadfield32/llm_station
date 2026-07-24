# Threat model — SkillOpt (AGT-17)

SkillOpt runs an optimization loop that (a) calls a **target** model on tasks,
(b) calls an **optimizer** model to propose skill-document edits, and (c) writes
a `best_skill.md` artifact. Risk surface and mitigations:

## Data flow / egress
- **Local path (used here):** target + optimizer = local Ollama
  (`http://localhost:11434/v1`). No off-box egress; a dummy API key. Task data
  (benchmark content) is downloaded once from public HF datasets during
  *materialization* and stays local. **No provider key, no egress** — verified.
- **Paid/external path (NOT used):** SkillOpt also supports `azure_openai`,
  `openai_chat`, `minimax`, and — for Tier 2 — `claude_code_exec` / `codex_exec`.
  Any external-egress or paid backend is an **operator decision**, recorded per
  run, and is subject to the usual egress/cost/authority rules. Never enabled by
  default here.

## Artifact / deployment risk
- SkillOpt writes `best_skill.md` to `out_root` only. It does **not** install a
  skill into an agent's config directory. **Deploying** a trained skill into the
  cockpit's Claude Code / Codex executors is a **separate, explicit, gated step**
  (never automatic) — treated like any skill/config change under the human
  approval + merge walls. A trained skill is untrusted text until reviewed:
  it could contain prompt-injection-style instructions, so it is read and
  reviewed before any deployment, exactly like an external contribution.

## Executor risk (Tier 2)
- `claude_code_exec` / `codex_exec` drive real coding executors. Tier-2 training
  must run under the same isolation as any write-mode agent (dedicated worktree,
  no `danger-full-access`, approvals/Ledger walls intact). Deterministic graders
  only; no autonomous merge/deploy. Operator-gated.

## Reproducibility / integrity
- Pinned SkillOpt commit + version, fixed seed, pinned models, exact command,
  disjoint splits (no leakage). Results are only scored with real runtime
  evidence and are independently re-run before any promotion.

## Windows-specific
- Requires `PYTHONUTF8=1` (optimizer prints non-cp1252 chars). Without it the run
  crashes mid-optimizer — fail-loud, not silent-wrong. Documented in
  `install-manifest.json`.

## What this evaluation did NOT change
- No repo config, contract, gateway, Ledger, gate, or agent config modified. The
  cloned tool + its venv + materialized data + run outputs live in scratch
  (gitignored); only design docs, the pinned manifest, the leaderboard, and
  excerpted raw evidence are committed.
