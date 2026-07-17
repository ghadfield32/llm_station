# AI-Assisted Development Workflow

## Module tree

```text
AI-Assisted Development Control Plane
|
|- A0  Session intake and safety preflight
|- A1  Standards and current-state intake
|- A2  Architecture and bounded implementation packet
|- A3  Independent, read-only Codex plan review
|- A4  Plan reconciliation and scope freeze
|- A5  Bounded implementation in an isolated worktree
|- A6  Deterministic verification
|- A7  Semantic and operational review
|- A8  Independent, read-only Codex final-diff review
|- A9  Findings resolution and re-verification
`- A10 Documentation, closeout, PR, and operator gate
```

## Purpose and authority

This workflow explains how to use Claude Code and Codex together for LLM
Station development. It supplements the repository's deterministic contracts;
it does not replace them.

Sources of truth, in descending order for an affected concern, are:

1. The current repository code, tests, and committed configuration contracts.
2. `configs/*.yaml`, their Pydantic schemas, and `make validate`.
3. The runtime Ledger and the configured kanban/mission workflow for runtime
   state and approvals.
4. `docs/MASTER.md` and the applicable architecture, operations, setup, and
   runbook documents.

Chat summaries and agent assertions are context, not evidence. Deterministic
checks, the actual diff, and reproducible runtime evidence are authoritative.

Claude Code and Codex are coding executors authenticated through their own
subscription/OAuth sessions. They are not LiteLLM chat models and must not be
added to the chat model picker or routed through the local model gateway.
Qualification and promotion of the local models behind that gateway follows
[`MODEL_VERIFICATION_WORKFLOW.md`](MODEL_VERIFICATION_WORKFLOW.md); model
quality evidence and coding-executor allocation are separate concerns.

## Capability profiles and replaceable model mapping

Route work by **capability profile**, not by a permanently hardcoded model
name. Model names, aliases, CLI support, context limits, and provider quotas
change. The workflow should remain stable when the preferred model changes.

**Codex-side executors consolidate to the Sol family only** (2026-07-16
policy). `deep_code` and `throughput` are filled by the same model — Sol —
differentiated by **reasoning effort**, not by which model answers. This
removes a failure class where a session silently used a stale or wrong model
name for one profile but not the other.

The current preferred mapping is:

| Capability profile | Current preferred model family | Primary work |
| --- | --- | --- |
| `strategic_steward` | Fable 5 (`fable` or the current Fable model ID) | High-level architecture, planning, methodology, documentation, threat modeling, security review, validation design, and final semantic integration |
| `deep_code` | Sol-capable GPT/Codex (`gpt-*-sol` or its current successor), reasoning effort **`xhigh`** as the standing default, escalating to the strongest tier the live catalog exposes for the hardest segments | Difficult implementation, cross-module coding, concurrency/state work, hard debugging, migrations, performance-sensitive code, and adversarial code review |
| `generalist` | Opus (`opus` or the current Opus model ID) | Most day-to-day engineering: repository exploration, normal implementation, tests, documentation, review, and coordination across a bounded task |
| `throughput` | Sol-capable GPT/Codex (`gpt-*-sol` or its current successor), reasoning effort **`high`** as the standing default | A large share of well-specified implementation, targeted tests, mechanical refactors, inventories, evidence collection, and low/medium-risk documentation updates |
| `independent_verifier` | A fresh model/session chosen for independence and the artifact being reviewed | Read-only plan or diff review; use Fable-class judgment for architecture/security/validation and Sol-class judgment (effort matched to risk) for deep code paths when available |

These mappings express **intended use**, not an unsupported claim that one
family is universally stronger. A model may serve more than one profile after
role-specific evaluation, but the task packet must still name the profile it
is filling. Parallelization comes from running multiple concurrent Sol
sessions in separate worktrees (not from switching to a cheaper model
family) — a `deep_code` session at `xhigh` for the hard segment, one or more
`throughput` sessions at `high` for the broad segment.

### Selection procedure

Every medium- or high-risk packet records:

```text
required_capability_profile
task_risk
preferred_model_family
resolved_harness
resolved_model_id
resolved_reasoning_effort
availability_evidence
fallback_or_escalation_rule
independent_review_profile
```

Resolve those fields in this order:

1. Classify the work by artifact and risk, not convenience or remaining quota.
2. Query the installed harness's live model catalog when it has one. For
   aliases without a live catalog, verify the installed CLI accepts the alias.
3. Resolve the preferred family to the exact available model and supported
   reasoning effort; record both in the session/mission evidence. Within the
   Sol family, default `throughput` to `high` and `deep_code` to `xhigh` (or
   the strongest tier the live catalog exposes); do not drop below `high` as
   a default for either — `low`/`medium` are for trivial, unambiguously
   low-risk confirmatory checks only, and that choice must be recorded.
4. Confirm context/tool requirements and the executor's read/write mode before
   starting the task.
5. If the preferred model is unavailable, use another model already qualified
   for the **same capability profile**. Otherwise stop and escalate; do not
   silently substitute a lower-assurance profile for high-risk work.
6. When a task proceeded on a documented unavailable-profile exception, its
   deferred independent review is a standing debt. Before merge, re-verify
   availability; if the profile is now reachable, run the originally-required
   review rather than treating the exception as permanently closed.

`configs/agent-session-models.yaml` may hold a preferred runtime model, but it
does not override the required capability profile. Its SDK-default fallback is
acceptable only when the resolved default is known to satisfy the packet's
profile. Record the actual model; never infer it from an alias alone.

### Task routing and review pairings

- Use `strategic_steward` for system boundaries, security/authorization,
  validation methodology, acceptance gates, durable-state design, and the
  document that freezes a high-risk implementation packet.
- Use `deep_code` for the hardest coding segments. Give it the frozen contracts
  and acceptance evidence; do not ask it to silently redefine the plan.
- Use `generalist` as the default for most ordinary work and for integrating
  well-understood changes across code, tests, and docs.
- Use `throughput` for broad but bounded execution where the contract is clear.
  Escalate novel architecture, ambiguous security behavior, or a failing
  acceptance gate rather than improvising.
- For security-sensitive changes, pair a Fable-class semantic/threat review
  with a Sol-class code-path review when both are available.
- For implementation performed by Sol (either `deep_code` or `throughput`
  tier), prefer a fresh Fable- or Opus-class semantic reviewer, or a fresh Sol
  session — never the implementing session — for a second code-focused pass
  on high-risk work. For implementation performed by Opus, prefer a fresh Sol
  code reviewer for complex code and Fable for architecture or security. A
  reviewer must not approve its own prior output.
- Prefer a different model family/provider for independent review. If that is
  unavailable, require a fresh read-only context, disclose the reduced
  independence, and rely on deterministic gates rather than presenting the
  review as cross-family verification.

### Reasoning effort and context

Use the strongest supported reasoning effort for architecture, security,
methodology, difficult debugging, and final high-risk review. Use balanced
effort for normal implementation and tests, and fast/low effort only for
repetitive extraction or formatting with deterministic checks. Effort labels
are harness-specific; record the resolved value rather than assuming every
model supports the same vocabulary.

For the Sol family specifically: `high` is the standing default for all
Sol-routed work (both `deep_code` and `throughput`); escalate to `xhigh` (or
the strongest tier the live catalog exposes) for migrations,
concurrency/durable-state, security/leakage-sensitive code, and final
high-risk diff reviews. Use `low`/`medium` only for trivial confirmatory
checks, never as the default.

Do not route solely on context-window size. Split an oversized task into
contracted slices when possible; use a long-context model only when the
cross-file relationships themselves must be reasoned about together.

### Destructive-action double-agreement gate

Any action that deletes, drops, truncates, force-overwrites, or otherwise
cannot be trivially undone requires, before it is even proposed to the user:

1. The proposing agent states the exact target and the concrete evidence
   that it is safe (confirmed orphaned, confirmed unreferenced, etc.).
2. A second, independent model — not the one proposing it — confirms or
   refutes the claim (Sol confirming a Claude-proposed deletion, or Claude
   confirming a Sol-proposed one). Two sessions of the same model do not
   satisfy this unless no other model is reachable, and that reduced
   independence must be disclosed.
3. Only after both agree is the action presented to the user, with the exact
   command, both confirmations, and what would be lost if wrong.
4. The user gives explicit, current-turn approval; a prior approval for a
   similarly-shaped action does not carry forward.
5. If either model is unavailable or the two disagree, do not proceed —
   surface the disagreement to the user.

This is an additional pre-check and does not replace the operator-control
requirements in A10 or the safety boundaries below.

### Model qualification, promotion, and retirement

A new model replaces a preferred mapping only after a role-specific evaluation
against representative repository tasks. Compare correctness, contract
adherence, security findings, edit precision, test quality, tool reliability,
latency, and quota/cost behavior. Acceptance gates must be derived from the
recorded baseline and task risk, not invented constants.

Record the candidate model/version, harness/CLI version, task set, raw evidence,
reviewer identity, decision, and rollback mapping. Update the profile-to-model
mapping without rewriting the workflow. Retire or demote a model when current
evidence shows regression, incompatibility, unavailable tooling, or repeated
scope/contract failures. Never promote a model based only on vendor claims or a
single successful task.

## A0 — Session intake and safety preflight

Before planning or editing:

1. Inspect `git status --short`, the current branch, and the declared base SHA.
2. Check for other sessions' in-flight edits, especially in `configs/`, shared
   orchestration code, the Ledger/kanban seam, and shared documentation.
3. Run `uv run cc doctor` for work that touches or depends on the local stack.
4. Read the applicable contracts, tests, and operational docs before proposing
   a change.
5. State the task's scope, non-goals, allowed files, and operator-only actions.

Treat an unknown worktree, branch, ownership conflict, or unhealthy required
service as a real condition to resolve or report. Do not overwrite concurrent
work. Never use `git add -A` or `git add .`; stage exact paths only.

## A1–A4 — Plan, independent review, and scope freeze

For medium- and high-risk changes, Claude Code (or an explicitly assigned
architect) produces an implementation packet with:

```text
Objective and non-goals
Repository, worktree, base branch, and base SHA
Allowed and forbidden files
Current behavior and affected contracts
Inputs, outputs, state ownership, and failure behavior
Security, approval, and concurrency implications
Required capability profile, resolved model/effort, and fallback rule
Acceptance criteria and evidence required
Tests and validation commands
Documentation updates and never-stage artifacts
Operator-only actions
```

For high-risk work, a **fresh Codex session in read-only mode** reviews the
packet before implementation. It must not be the implementation session and
must cite concrete evidence: files, contracts, tests, commands, or missing
acceptance criteria.

High-risk work includes security or authorization changes; new public
endpoints; config/schema changes; Ledger, queue, worktree, or durable-state
changes; new dependencies; migrations/deletions; deployment behavior; agent
autonomy; model routing; or production incident fixes.

The architecture owner resolves blocking findings, then freezes a bounded
packet. The implementation agent must stop and request a revised packet rather
than silently changing architecture, approval boundaries, scope, or contracts.

## A5 — Bounded implementation

Codex is well suited to implementing a frozen, bounded packet in a dedicated
worktree. It must:

- Inspect relevant code before editing and stay within the approved scope.
- Preserve typed contracts, `extra="forbid"` validation, and the human approval
  and human merge walls.
- Keep diffs minimal; do not add speculative abstractions, silent fallbacks,
  fake/default values, or swallowed exceptions.
- Use `uv` for dependency work: record an appropriate compatible range in every
  consuming `pyproject.toml`, prove `uv sync`, and include metadata with code.
- Never edit or reveal `.env` values, enable provider routes, bypass the Ledger
  or Judge Gate, approve a mission card, merge a PR, push directly to `main`,
  deploy, or rotate credentials.

LLM Station model work must distinguish quality evaluation from serving
evaluation. Any time-ordered learning work needs past-only inputs and temporal
splits; do not claim evidence that has not been produced from real data.

## A6 — Deterministic verification

Run every check the change affects. Typical checks are:

```bash
make validate
make lint
make test
uv run cc doctor
```

Use targeted tests in addition to the broadest proportionate checks. Config
changes require `make validate`; public endpoints require the applicable
security baseline update and tests; runtime changes require relevant health or
smoke evidence. Record exact commands, exit statuses, pertinent counts or
metrics, and artifact paths. Do not call a result green unless it was run
successfully in the current relevant state.

## A7–A9 — Semantic review, final diff review, and fixes

After implementation, Claude Code (or the assigned semantic reviewer) reviews
the actual diff and deterministic evidence for contract fit, system semantics,
security, operational behavior, test quality, documentation truthfulness, and
scope discipline.

For high-risk work, a second **fresh, read-only Codex session** independently
reviews the diff against the declared base SHA. It must not reuse the
implementation context. Its report should contain:

```text
verdict
blocking_findings[]
non_blocking_findings[]
file and line
evidence and violated contract
production or operational impact
recommended fix and required test
reviewed_base_sha
reviewed_head_sha
```

Resolve accepted findings in the implementation worktree, then rerun all
affected validation. A narrow passing test does not close a finding that also
affects a shared contract or runtime behavior.

## A10 — Documentation, closeout, and human control

When behavior, contracts, interfaces, or runbooks change, update the relevant
documentation with current behavior, decisions, evidence, known limits,
remaining work in order, base/head SHAs, and exact touched files. Do not edit
generated output by hand; logs, transient reports, and review artifacts belong
in a repository-recognized never-stage location.

The operator controls approval, final staging/commit approval, PR publication,
merge, deployment, credential changes, and destructive or irreversible
actions. An agent may prepare clear commands and evidence, but must not perform
those actions autonomously.

## Risk-scaled workflow

Low risk (typos, formatting, narrow documentation correction):

```text
bounded change -> proportionate deterministic check -> accurate closeout
```

Medium risk (routine endpoint, bounded refactor, internal feature):

```text
architecture/plan -> bounded Codex implementation -> deterministic verification
-> semantic review -> documentation and closeout
```

High risk (the categories listed in A1–A4):

```text
architecture -> fresh read-only Codex plan review -> reconciled frozen packet
-> bounded Codex implementation -> deterministic verification -> semantic review
-> fresh read-only Codex final-diff review -> findings resolution
-> complete affected re-verification -> documentation and closeout
-> operator-controlled PR, merge, and deployment
```
