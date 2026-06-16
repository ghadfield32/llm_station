# Whole-system validation prompt

Use this prompt when the goal is to prove the full Command Center + Growth OS
pipeline works end to end: self-improvement, local model routing, AppFlowy
kanban control, desktop repo autonomy, progress notification, privacy, and
human-gated promotion.

This is a validation and repair prompt, not permission to bypass the walls. The
agent should continue until every stage has passing evidence, or until a hard
external precondition is missing and the exact blocker, evidence, and next human
action are written down. Missing data is `unknown`; it is never guessed.

## Copy-paste mission prompt

You are acting as principal systems engineer, adversarial evaluator, release
manager, privacy reviewer, and independent verifier for this repository.

Your assignment is to pull together the current project state, the accumulated
chat goals reflected in `docs/MASTER.md`, and the implemented code/config/test
surface, then prove whether the complete local AI command center can reliably:

- improve itself through observer-only discovery, bounded experiments,
  independent verification, canary, and human promotion;
- adjust the open-source AppFlowy kanban workspace through the governed action
  layer, including edits and moves, while preserving the human-only approval
  wall;
- perform autonomous desktop work on registered repositories only, using
  leased worktrees and the configured executor path;
- route local model roles cheaply and correctly, with open-weight discovery and
  no hidden cloud fallback;
- notify the operator about state, progress, blockers, and required approvals;
- forecast the expected next state before every state-changing action, then
  compare observed state to the forecast and record drift;
- avoid data leakage, secret persistence, fake metrics, hardcoded thresholds,
  silent fallbacks, and fabricated success.

Do not stop at a narrative review. Reconstruct the real system from files,
contracts, generated artifacts, tests, and live endpoints where available. Fix
small documentation or test gaps that are necessary to make the pipeline
testable. Keep code changes scoped. Never revert unrelated user work.

### 0. Inputs and authority order

Read these in order:

1. `docs/MASTER.md`, especially sections 2, 5, 6, 7, 8, 11, 12, 13, and 14.
2. `docs/STATUS.md`, `docs/system-roadmap.md`, `docs/improvement-loop.md`,
   `docs/daily-self-improvement-dag.md`, `docs/kanban-integration.md`,
   `docs/channels.md`, `docs/model-routing.md`, `docs/model-update.md`,
   `docs/agent-multiturn-and-memory.md`, and
   `docs/whole-system-validation-prompt.md` if present.
3. `configs/*.yaml`, plus the Pydantic contracts under
   `src/command_center/schemas/` and `src/command_center/improvement/schema.py`.
4. `Makefile` and available CLI entry points.
5. The relevant tests under `tests/`.
6. Existing generated evidence under `generated/`, `data/improvement/`, and
   `evaluation/`, but treat generated files as evidence, not source of truth.
7. Current git status. Separate existing unrelated user changes from changes
   you make in this pass.

If chat history or pasted attachments are not available in the current context,
say so in the evidence record and rely on the repository state. Do not recreate
missing chats from memory.

Authority order:

1. Contracts and configs.
2. Code implementing those contracts.
3. Tests and live evidence.
4. MASTER and linked docs.
5. Generated reports.
6. Chat summaries.

When these disagree, prefer the earlier authority, then update docs to describe
the real state.

### 1. Non-negotiable constraints

Hold these throughout the run:

- No provider API keys for LiteLLM routing. Local model roles stay
  Ollama/LiteLLM local-only.
- No second model gateway, mission ledger, scheduler, autonomous control plane,
  or source of truth.
- No agent self-approval, self-promotion, self-merge, secret rotation, public
  deployment, or branch-protection bypass.
- No global hooks, shell profile edits, browser profile edits, MCP
  registrations, persistent daemons, or background schedulers unless the stage
  explicitly requires a human-approved production setup step.
- No production secrets in repo-task worktrees.
- No raw `.env`, tokens, credentials, private transcripts, raw benchmark
  prompts/outputs, or secret-bearing diffs in retained artifacts.
- No defensive coding that hides failures. Invalid state should fail loudly
  with evidence.
- No hardcoded thresholds, fake values, invented costs, invented confidence,
  guessed model fit, guessed token pricing, guessed status, or fallback success.
- Missing data is `unknown` or `blocked`, with the exact missing input named.
- Any threshold, budget, repetition count, statistical stop rule, or canary
  guard must come from config, a pre-registered experiment plan, observed pilot
  variance, or explicit human approval.
- Deterministic checks run before LLM judges.
- A model or judge verdict cannot override a failed deterministic check.
- The producing agent cannot be the only evaluator.

### 2. Evidence package

Create or update a single evidence package for the validation run. Prefer:

```text
evaluation/system-validation/<mission-or-run-id>/
```

If there is a Ledger mission id, use it. If there is no mission id, use the
current UTC timestamp. The package should contain:

- `BASELINE.md` - current implementation summary, git status, services, local
  models, AppFlowy availability, registered repos, and available channels.
- `SCENARIOS.md` - scenario matrix, expected state forecasts, observed state,
  pass/fail, and evidence paths.
- `COMMANDS.md` - every command run, exit status, and concise result.
- `PRIVACY.md` - what data was touched, retained, redacted, or proven absent.
- `FORECASTS.md` - before/after state forecasts and drift analysis.
- `GAPS.md` - real blockers and missing coverage, in priority order.
- `NEXT.md` - the next ordered work. Keep it linear and testable.

Do not store raw secrets or raw private transcripts in this package. Use hashes,
row ids, event ids, redacted summaries, and file paths.

### 3. Baseline reconstruction

Build a current baseline before changing anything:

1. Record branch, commit, dirty files, untracked generated evidence, and files
   that appear unrelated to this task.
2. Enumerate configured roles from `configs/models.yaml`.
3. Enumerate risk tiers and approval rules from `configs/gates.yaml`.
4. Enumerate dispatch sections from `configs/kanban.yaml`.
5. Enumerate channels from `configs/channels.yaml`.
6. Enumerate registered observed projects from
   `appflowy_kanban/growth-os/config/projects.yaml`.
7. Enumerate repo-task isolation and GPU budgets from
   `configs/environments.yaml`.
8. Enumerate improvement experiments and targets from
   `configs/improvement.yaml` and `configs/improvement-targets.yaml`.
9. Enumerate model benchmark suites from `configs/model-benchmarks.yaml`.
10. Record which live services are reachable: Docker, Ledger, LiteLLM, Ollama,
    AppFlowy, Growth OS, and enabled notification channels.

For every service that is not reachable, record `blocked` plus the exact command
or credential needed. Do not substitute a fake service.

### 4. Forecast-before-action rule

Before every state-changing action, write a small forecast:

```text
action_id:
  source_authority:
  command_or_tool:
  expected_allowed_fields:
  expected_state_before:
  expected_state_after:
  expected_events:
  expected_no_change:
  privacy_boundary:
  rollback_or_revert_plan:
```

Then run the action, inspect the real state, and record:

```text
observed_state_after:
observed_events:
unexpected_change:
drift_class:
drift_reason:
pass_or_fail:
```

Drift classes are exact categories, not scores:

- `none`
- `expected_external_precondition_missing`
- `contract_mismatch`
- `implementation_bug`
- `doc_stale`
- `test_gap`
- `operator_input_required`

Do not invent probabilities. If a forecast needs a probability or confidence,
derive it from historical Ledger/AppFlowy/benchmark data or mark it `unknown`.

### 5. Scenario matrix to prove

Run the deepest version of each scenario that the local environment permits.
When a live credential or service is missing, run the deterministic/dry-run
version and record the live blocker.

#### A. Contract and source-of-truth integrity

Prove:

- configs validate against schemas;
- cross-file references are checked;
- provider routes are rejected;
- missing required fields fail loudly;
- generated files are disposable and reproducible.

Suggested commands:

```powershell
uv run cc validate
uv run cc mission-dryrun
uv run cc evals
uv run ruff check src tests
uv run pytest
```

If full pytest is too slow for the first pass, run focused suites first and
then full pytest before declaring the pipeline complete.

#### B. Local-only model routing and cheapest-role behavior

Prove:

- every LiteLLM role is local-only;
- local model aliases resolve to configured Ollama roles;
- tool-using roles do not route to known unsafe parser models;
- model-scout emits Proposed candidates only;
- open-weight candidates include license, tag, digest, quant, parameter size,
  context, fit/headroom, and source hashes;
- benchmark artifacts retain hashes and metrics, not raw prompts/outputs;
- a candidate cannot promote unless it improves at least one required
  non-safety metric and passes hard non-regression, independent verification,
  canary telemetry, and human approval.

Suggested commands:

```powershell
make forbidden-providers
make model-fit
make model-scout
make improvement-scan FEEDS=generated/model-scout-feed.json SHOW=1
$env:OLLAMA_BASE_URL='http://localhost:11434'; uv run python -m command_center.improvement.model_metric_audit --reps <declared_reps> --base-url-env OLLAMA_BASE_URL
```

`<declared_reps>` must come from the scenario plan, pilot variance, or a human
instruction. Do not pick a repetition count because it is convenient and then
call it statistically meaningful.

#### C. Self-improvement loop

Prove:

- the daily scan is observer-only;
- findings are derived from configured sources and real evidence;
- proposals are `Proposed`, not applied;
- experiment lifecycle is register -> baseline -> candidate -> verify ->
  awaiting human promotion -> human canary -> human promote/rollback;
- sealed evals are not visible to the producing agent;
- failed verification blocks promotion.

Suggested commands:

```powershell
make improvement-scan-validate
make improvement-list
make improvement-scan SHOW=1
uv run pytest tests/test_improvement_lifecycle.py tests/test_improvement_e2e.py tests/test_verifier.py tests/test_sealed_evals.py tests/test_antigoodhart.py
```

For any real experiment, use a pre-registered experiment id and record all
Ledger artifact paths.

#### D. AppFlowy kanban control

Prove:

- the agent reads the real board state;
- the action layer can create, annotate, edit allowed fields, move, stage,
  start, finish, block, and reject cards where configured;
- allowed statuses and fields are read from schema/board/config, not hardcoded;
- `Approved` remains human-only;
- the bridge only dispatches configured ready statuses;
- AppFlowy writes are reversible in the test;
- every tool call is logged with redacted arguments and latency.

Suggested commands:

```powershell
make kanban-validate
make kanban-surface-validate
make kanban-digest
make kanban-bridge
make appflowy-audit DETAILS=1
python appflowy_kanban/growth-os/scripts/selftest.py
python appflowy_kanban/growth-os/scripts/test_abilities.py
uv run pytest tests/test_actions_intent.py tests/test_agent_observability.py tests/test_kanban_surface.py tests/test_growthos_board.py tests/test_board_state.py
```

Live board writes must use a test card or a user-approved target card. Before
each write, forecast the exact field changes; after the write, compare and
revert or move the row to the expected final test state.

#### E. Desktop repo autonomy on registered repos

Prove:

- a repo must be registered before autonomous work targets it;
- repo-task environments are ephemeral and secret-free;
- a mission gets a lease, branch/worktree, standards render, deterministic
  checks, local judges, progress events, and final status;
- the agent cannot modify unregistered repos or jump outside the leased
  worktree;
- GitHub merge/deploy remains human-protected.

Suggested checks:

```powershell
make env-smoke
make tools-validate
make standards-validate
make repo-install REPO=<registered-test-repo> PROFILE=<profile>
uv run pytest tests/test_control.py tests/test_ledger_rest.py tests/test_safety_boundaries.py tests/test_routing.py
```

Use a scratch registered repo or a harmless fixture repo for live worktree
tests. Do not use a production repo for mutation tests unless the user has
explicitly approved that target and scope.

#### F. Channels and progress notification

Prove:

- channel configs validate;
- disabled channels stay disabled;
- enabled channels fail loudly when required credentials are absent;
- dry-run notification emits the expected digest without secrets;
- live notification, where credentials exist, sends progress, blockers, and
  approval-required messages;
- notifications contain references and summaries, not raw secret-bearing
  content.

Suggested commands:

```powershell
make channels-validate
make notify ARGS=--dry-run
uv run pytest tests/test_notify.py tests/test_gateway_toolcall.py
```

Run live channel tests only for channels whose credentials are intentionally
present.

#### G. Memory and knowledge reuse

Prove:

- within-conversation memory is bounded and does not become cross-chat leakage;
- durable knowledge is the OKF/AppFlowy/Git-backed projection, not hidden model
  memory;
- generated knowledge validates and links back to authoritative sources;
- retrieval/memory changes go through the improvement loop before adoption.

Suggested commands:

```powershell
make knowledge-generate
make knowledge-validate
uv run pytest tests/test_memory.py tests/test_knowledge_bundle.py tests/test_knowledge_foundations.py
```

#### H. Failure and no-fallback behavior

Prove fail-closed behavior with deliberate missing inputs:

- missing Ollama/LiteLLM endpoint fails the model call;
- missing channel credentials fail the enabled channel;
- invalid AppFlowy status is refused using the real allowed set;
- attempting agent-set `Approved` is refused;
- provider route in model config is rejected;
- missing model benchmark JSON mode is rejected;
- missing candidate provenance is rejected from the open-weight feed;
- failed deterministic checks block model/judge approval.

Use existing tests where possible. If a gap is found, add a focused test before
changing implementation.

#### I. Privacy and leakage audit

Scan retained artifacts from this validation run:

- no `.env` values;
- no provider API keys;
- no raw private transcripts;
- no raw model benchmark prompts/outputs where the harness promises hashes;
- no secret-bearing diffs;
- no full AppFlowy export unless explicitly approved;
- no hidden eval contents in producer-visible artifacts.

Record exact files scanned and the patterns/classes checked. Do not print
secrets if found; record the path, key class, and containment action.

### 6. Repair protocol

When a scenario fails:

1. Classify the failure as contract, implementation, doc, test, environment,
   credential, external service, or operator-input.
2. If it is contract or implementation, add the smallest focused failing test
   first when practical.
3. Fix the narrowest code/config/doc surface that owns the failure.
4. Re-run the focused test.
5. Re-run the affected scenario.
6. Re-run the validation ladder before declaring complete.
7. Update `docs/MASTER.md` and the evidence package with what changed and what
   remains.

Do not add generic try/except swallowing, default credentials, guessed status
values, broad fallbacks, synthetic success metrics, or hardcoded status lists.

### 7. Validation ladder

Before finalizing, run the highest ladder the environment permits:

```powershell
uv run cc validate
uv run cc mission-dryrun
uv run cc evals
make improvement-scan-validate
make kanban-surface-validate
make channels-validate
make forbidden-providers
uv run ruff check src tests
uv run pytest
rtk git diff --check
```

Add live commands only when their services and credentials are intentionally
available:

```powershell
make health
make live-smoke
make appflowy-audit DETAILS=1
make kanban-bridge
make notify ARGS=--dry-run
```

For model routing audits, use explicit endpoint and declared repetitions:

```powershell
$env:OLLAMA_BASE_URL='http://localhost:11434'
uv run python -m command_center.improvement.model_metric_audit --reps <declared_reps> --base-url-env OLLAMA_BASE_URL
```

### 8. Required final report

The final report must lead with outcomes, not intentions:

```text
Overall status:
  PASS | PASS_WITH_BLOCKERS | FAIL

What works:
  - scenario, evidence path, command proof

What failed or is blocked:
  - blocker, exact missing input, evidence path, next action

State-changing actions performed:
  - forecast, observed result, revert/final state

Privacy result:
  - artifact classes scanned, leaks found or none found

Routing/model result:
  - incumbent/candidate, metrics, recommendation, promotion status

Kanban result:
  - read/write/move/approval-wall evidence

Repo autonomy result:
  - registered repo, lease/worktree/gates/progress evidence

Self-improvement result:
  - scan/proposal/experiment/verification/canary/promotion evidence

Docs updated:
  - `docs/MASTER.md` sections changed
  - evidence package path

Next ordered work:
  1. ...
  2. ...
```

Use `PASS_WITH_BLOCKERS` only when all deterministic local checks pass and the
remaining gaps are explicit external prerequisites such as missing channel
credentials, AppFlowy not running, Ollama unavailable, or no human-approved live
target. Use `FAIL` when a core contract or safety invariant fails.

### 9. MASTER update rule

Update `docs/MASTER.md` during the pass:

- add a concise "What is done" entry for any validated capability;
- add a "Remaining order" entry for gaps;
- add a changelog item with commands and evidence;
- keep the doc linear and ordered;
- if the user says `docs/mater.md`, treat it as `docs/MASTER.md` and note the
  correction only if needed.

Do not let docs claim a live test passed unless the command actually ran and
the evidence is retained.
