# Local Model Verification Workflow

## Purpose

This is the operator path for evaluating a local Ollama model before it can
serve a role in LLM Station. It complements
`AI_ASSISTED_DEVELOPMENT_WORKFLOW.md`; it does not evaluate Claude Code or
Codex subscriptions.

The cockpit has two selectors because they answer different questions:

| Selector | Question | Source of truth |
|---|---|---|
| **Assistant** | Which runtime should handle this conversation? | Growth OS/GatewayCore, Claude Code, or Codex availability |
| **Chat model** | Which GatewayCore role or explicitly enabled frontier lane should answer? | `configs/models.yaml` plus frontier-lane contracts |
| **Agent model / effort** | Which model exposed by the selected Claude/Codex runtime should run this agent session? | the runtime catalog plus `configs/agent-session-models.yaml` preferences |

Growth OS is the local, action-aware product surface. GatewayCore is its chat
runtime. Claude Code and Codex are separate coding runtimes with filesystem and
tool loops. A model is the inference engine inside the selected runtime. Keeping
runtime selection separate from model selection prevents a local chat alias
from accidentally acquiring coding-agent authority.

## Module tree

```text
Local model verification
|
|- M0  Inspect roster and choose one role
|- M1  Discover candidate and prove provenance
|- M2  Prove hardware/context fit
|- M3  Run incumbent/candidate quality A/B
|- M4  Independently verify raw quality evidence
|- M5  Run serving SLO/load audit
|- M6  Check suite readiness and deterministic regressions
|- M7  Human-approved canary
`- M8  Human promote or rollback, then post-watch
```

No stage may silently stand in for another. Quality is not serving performance;
fit is not quality; a verifier PASS is not a promotion; and a canary is not a
human approval.

## Authority and boundaries

Use these sources in order:

1. `configs/models.yaml` and its `ModelRegistry` contract for the routed roster.
2. `configs/model-benchmarks.yaml` for role-specific quality cases and metric
   policy.
3. `configs/model-serving-benchmarks.yaml` for measured workload sizes,
   concurrency points, and p90 SLOs.
4. `configs/environments.yaml` and live Ollama metadata for fit.
5. Raw Ledger/generated audit evidence from the current run.

The workflow is local-only. Scout and audit commands never promote. Do not add
provider keys, bypass LiteLLM, treat a leaderboard as local evidence, or edit
`generated/` by hand. Canary, routing edits, promotion, and rollback remain
operator-controlled.

## The shortest honest path

Run from the repository root. Replace bracketed values with explicit values
from the candidate packet; do not guess repetitions, context, or workload.

### M0-M2: roster, discovery, and fit

```powershell
uv run cc model-status
uv run cc model-scout
uv run cc model-fit --model <ollama-tag> --ctx <required-context> --env cc-worker-4090
```

Stop if the exact installed tag/digest/provenance is unknown or the candidate
does not fit at the context the role needs. A lower-context specialization must
be declared before testing; it is not an implicit fallback.

### M3-M4: isolated quality A/B plus independent verifier

First prove or refresh the incumbent baseline and benchmark arithmetic when the
candidate packet requires them:

```powershell
uv run python -m command_center.improvement.model_baselines --roles <role> --reps <repetitions> --base-url http://127.0.0.1:11434 --apply
uv run python -m command_center.improvement.model_metric_audit --reps <repetitions> --base-url http://127.0.0.1:11434
```

Then run the candidate audit through the discoverable wrapper:

```powershell
uv run cc model-verify --role <role> --baseline-model <incumbent-tag> --candidate-model <candidate-tag> --reps <repetitions> --base-url http://127.0.0.1:11434 --derive-context-from-fit --fit-ctx <required-context> --gpu-budget-gb <declared-budget>
```

Default evidence is isolated under:

- `generated/model-candidate-audit-summary.json`
- `generated/model-candidate-audit-ledger.db`
- `generated/model-candidate-audit-evidence/`

`status: completed` means the audit ran. It does not mean the model should be
promoted. Read the comparison recommendation, every hard non-regression metric,
the evaluated context/equivalence key, and the independent verifier verdict.

### M5: serving SLO/load audit

Choose one committed scenario that represents the role's actual workload:
`repo_triage`, `code_patch`, or `long_repo_reader`. Record why it applies.

```powershell
uv run cc model-serving-verify --model <candidate-tag> --scenario <scenario> --base-url http://127.0.0.1:11434 --output generated/model-serving-audit-<role>-<candidate>.json
```

This is a real live load sweep using the committed p90 input/output sizes and
concurrency points. It sends synthetic filler only, records TTFT/TTLT, RPS,
error rate, and the highest operating point meeting the SLO, and never changes
routing. Run the same scenario for the incumbent so the comparison has the same
model, quant, runtime, workload, and hardware conditions.

### M6: readiness gates

A candidate may proceed only when all of these are evidenced:

- exact local identity and license/provenance;
- fit at the evaluated context on the target environment;
- same-suite incumbent and candidate quality runs;
- no hard safety/non-regression failure;
- independent verifier PASS from raw evidence;
- a role suite deep enough to gate promotion;
- candidate and incumbent serving audits under the same configured scenario;
- `uv run cc validate`, `uv run cc evals`, and the applicable live smoke pass;
- rollback command and post-watch signals recorded before canary.

Current limitation: the routed role suites are still pilot-grade. The committed
methodology requires at least eight labeled cases per role, execution-based or
judged scoring for coder/judge roles, decoupled metric scoring, and a
pre-registered significance plan. At present the routed suites contain 2-3
cases each; `chat_text_only` has 10 cases but does not cover the tool-using
`chat` role by itself. Therefore current audits are useful comparison evidence,
not sufficient production-promotion evidence. Deepen the affected role suite
and validate that change before M7.

The new serving command closes the missing callable **operating-point** path,
but the repository's full promotion evidence contract also calls for ITL and
p50/p95/p99 distributions plus VRAM/RAM capture. Those fields are not yet
emitted by `serving_load_driver`; until they are, the serving summary is also
comparison evidence rather than a complete promotion gate. Do not enter M7 on
the operating-point PASS alone.

### M7-M8: operator-only canary, promote, or rollback

After the readiness gates pass and the candidate exists in `configs/models.yaml`
as `status: scout`:

```powershell
uv run cc model-canary --role <role> --model ollama_chat/<candidate-tag> --weight 0.1 --apply
docker compose restart litellm
uv run cc live-smoke
uv run cc model-promote --role <role> --candidate <candidate-alias> --approver <human-name> --apply
uv run cc render
docker compose restart litellm
```

If canary evidence regresses, do not promote:

```powershell
make models-rollback ROLE=<role>
```

The human controls the canary decision, config change approval, promotion,
rollback, commit/PR, merge, and deployment.

## Candidate packet and closeout

Record: role, incumbent, candidate exact tag/digest/quant/license, target
environment, required/evaluated context, repetitions, suite/version, serving
scenario, raw artifact paths, quality and serving verdicts, deterministic check
results, canary weight/window, rollback triggers, and human approver.

At closeout, report commands and exit codes, never-stage generated artifacts,
known limitations, and the next operator-only action. Never summarize a pilot
suite as promotion-grade.
