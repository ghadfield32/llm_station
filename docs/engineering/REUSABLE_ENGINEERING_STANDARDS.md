# Reusable LLM Station Engineering Standards

Use this block in implementation and review requests for LLM Station.

```text
You are working in the `llm_station` repository. Follow
`docs/engineering/AI_ASSISTED_DEVELOPMENT_WORKFLOW.md` and use the current
repository, committed configuration contracts, tests, and reproducible runtime
evidence as truth. `docs/MASTER.md` is the system overview; `configs/*.yaml`
are editable source of truth; Pydantic contracts plus `make validate` enforce
them; `generated/` is disposable output and must never be hand-edited.

Start by inspecting `git status --short`, branch, base SHA, concurrent edits,
and relevant code/contracts/docs. Run `uv run cc doctor` when the task touches
or relies on the local stack. Preserve unrelated work. Never use `git add -A`
or `git add .`; stage exact paths only.

For medium-risk work use:
plan -> bounded implementation -> deterministic verification -> semantic review
-> documentation and closeout.

For high-risk work (security, public endpoints, configs/schemas, durable state,
Ledger/queue/worktree behavior, dependencies, migrations/deletions, deployment,
agent autonomy, model routing, or incident fixes) use:
architecture -> fresh read-only Codex plan review -> reconciled frozen packet
-> bounded Codex implementation in a dedicated worktree
-> deterministic verification -> semantic review
-> fresh read-only Codex final-diff review -> findings resolution
-> complete affected re-verification -> documentation and closeout
-> user-controlled PR, merge, and deployment.

Claude Code owns architecture, methodology, contracts, documentation, and
semantic integration. Codex performs bounded implementation and independent,
fresh-context read-only reviews. Neither agent may approve its own work or
declare production readiness without deterministic evidence. Claude Code and
Codex are coding executors, not LiteLLM chat models.

Route work through stable capability profiles, then resolve the exact model
from the installed harness catalog. Codex-side executors consolidate to the
Sol family only: `deep_code` and `throughput` are both filled by Sol,
differentiated by reasoning effort, not by model. Query the live catalog
(e.g. `codex debug models`, lower `priority` = more current) each session
rather than reusing a model slug from memory or an earlier session. Current
preferred mappings are:
- `strategic_steward` -> Fable 5 for architecture, planning, methodology,
  documentation, security/threat review, validation design, and final semantic
  integration.
- `deep_code` -> Sol-capable GPT/Codex at reasoning effort `xhigh` (or the
  strongest tier the live catalog exposes for the hardest segments) for
  difficult cross-module coding, state/concurrency work, migrations, hard
  debugging, and deep code review.
- `generalist` -> Opus for most normal engineering, implementation, tests,
  review, documentation, and coordination.
- `throughput` -> Sol-capable GPT/Codex at reasoning effort `high` (the
  standing default; do not drop below it) for a large share of bounded
  implementation, targeted tests, mechanical refactors, inventories, and
  evidence collection.
- `independent_verifier` -> a fresh read-only model/session selected for the
  artifact: Fable-class for architecture/security/validation and Sol-class
  (effort matched to risk) for complex code paths when available.

For each medium/high-risk packet record the required capability profile,
preferred family, resolved harness/model ID, supported reasoning effort,
availability evidence, fallback/escalation rule, and independent review
profile. Model aliases and versions are replaceable mappings, not permanent
policy. If the preferred model is unavailable, use only a model already
qualified for the same profile; otherwise stop and escalate. Never silently
downgrade high-risk work or infer the actual model from an alias. Prefer
cross-family review; if unavailable, disclose reduced independence and require
a fresh read-only context plus deterministic gates.

Any delete/drop/truncate/force-overwrite or otherwise hard-to-undo action
requires two independent models to confirm it is safe (not two sessions of
the same model, unless disclosed as reduced independence) before it is even
proposed to the user, plus the user's explicit current-turn approval. A prior
approval for a similarly-shaped action does not carry forward.

Qualify replacements on representative repository tasks using correctness,
contract adherence, security findings, edit precision, test quality, tool
reliability, latency, and quota/cost evidence. Derive acceptance gates from the
recorded baseline and risk. Record model and harness versions, raw results,
decision, and rollback mapping; update the profile mapping without rewriting
the workflow. Vendor claims or one successful task are not promotion evidence.

Engineering requirements: make minimal, root-cause fixes; preserve typed
contracts and approval walls; use no swallowed exceptions, fake/default data,
silent fallbacks, invented thresholds, or speculative abstractions. Use real,
provenance-backed evidence. Keep quality evaluation separate from serving
evaluation. For time-ordered learning work, use past-only features and temporal
splits. Use `uv` for dependency changes, update every consuming
`pyproject.toml`, prove `uv sync`, and include dependency metadata with code.

Run all relevant verification. Config changes require `make validate`; code
changes require appropriate tests and normally `make lint`/`make test`; runtime
changes require proportionate health or smoke evidence. Record exact commands,
exit statuses, results, and artifact paths. Never report a check as passing if
it was not run successfully in the current state.

Do not edit or expose `.env` secrets; enable cloud/provider routes; bypass the
Ledger, Judge Gate, kanban approval wall, branch-protection/merge wall, or
contracts; approve cards; merge; push directly to `main`; deploy; rotate
credentials; or perform destructive/irreversible actions. Give the operator
clear remaining commands and evidence instead.

At completion, report the exact files changed, validation evidence, known
limitations, never-stage artifacts, and any operator-only next steps. Update
relevant documentation only when behavior, interfaces, contracts, or runbooks
changed.
```
