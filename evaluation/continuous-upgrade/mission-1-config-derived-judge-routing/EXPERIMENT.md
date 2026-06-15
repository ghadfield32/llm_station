# Experiment - Mission 1 config-derived Judge Gate routing

## State

`EXPERIMENT_PREREGISTERED`

This experiment is registered before any implementation change to Judge Gate
routing.

## Hypothesis

Moving Judge Gate risk-to-role routing out of inline service constants and into
validated configuration will preserve current routing behavior while improving
auditability, cross-reference validation, and future route artifact provenance.

## Baseline

Current service-code route map in `services/judge_gate/app.py`:

```text
L0_READONLY -> triage
L1_PLAN -> planner
L2_LOCAL_CHANGE -> coder
L3_EXTERNAL_WRITE -> coder
L4_DANGEROUS -> architect-judge
```

Baseline validation results are recorded in
`evaluation/continuous-upgrade/BASELINE.md`.

## Candidate

A native config/schema implementation that:

1. defines the classify route map in validated configuration;
2. verifies every route alias resolves to an existing `configs/models.yaml`
   role;
3. preserves the current route map unless a reviewed config edit changes it;
4. fails validation or startup for missing aliases;
5. does not add any provider keys, model gateway, router, scheduler, or new
   control plane.

## Alternatives

1. Keep inline route constants.
2. Add route map to `configs/gates.yaml`.
3. Add route map to `configs/judges.yaml`.
4. Add a new `configs/routing.yaml`.

The implementer must choose the smallest option that preserves config truth and
clear ownership. If a new config file is introduced, it must be registered in
the existing validation flow.

## Fixture set

Frozen route fixtures:

| Fixture | Risk tier | Expected alias |
| --- | --- | --- |
| `route_l0_readonly` | `L0_read_only` | `triage` |
| `route_l1_plan` | `L1_plan_only` | `planner` |
| `route_l2_local_edits` | `L2_local_edits` | `coder` |
| `route_l3_external_write` | `L3_external_write` | `coder` |
| `route_l4_dangerous` | `L4_dangerous` | `architect-judge` |

Failure fixtures:

| Fixture | Expected result |
| --- | --- |
| missing route for a risk tier | config validation or service startup fails |
| route alias not in `configs/models.yaml` roles | config validation fails |
| provider route introduced in LiteLLM role | existing forbidden-provider validation fails |
| L3/L4 approval disabled | existing gate validation fails |

These are functional invariants, not invented performance thresholds.

## Required validation commands

Run after implementation:

```powershell
uv run cc validate
uv run cc mission-dryrun
uv run cc evals
uv run pytest tests/test_routing.py tests/test_safety_boundaries.py tests/test_sealed_evals.py tests/test_improvement_lifecycle.py
```

Add focused tests for the new route map owner before running the existing test
set. The exact test file is an implementation detail, but it must cover all
fixtures above.

## Metrics

| Metric | Type | Required result |
| --- | --- | --- |
| route parity | deterministic fixture result | current five route fixtures resolve to the same aliases |
| missing route rejection | deterministic fixture result | validation/startup rejects missing tier route |
| dangling alias rejection | deterministic fixture result | validation rejects unknown alias |
| provider boundary | existing validation result | provider routes remain forbidden |
| approval boundary | existing validation result | L3/L4 still require approval |
| secret/privacy boundary | inspection/test result | no `.env`, token, raw transcript, or hidden eval content persisted |

No latency, cost, or token values are claimed for this mission unless measured
by an actual command. Missing values remain `unknown`.

## Security and privacy criteria

- No new secrets.
- No provider API keys.
- No raw transcript storage.
- No hidden eval material in logs or artifacts.
- No global config edits.
- No MCP registration.
- No service ports added.
- No change to LiteLLM as the single model gateway.
- No change to Ledger as the state/evidence authority.

## Rollback criterion

Rollback is acceptable only if returning to the prior route behavior restores:

- current five route aliases;
- `uv run cc validate` PASS;
- `uv run cc mission-dryrun` PASS;
- `uv run cc evals` PASS;
- focused routing tests PASS.

## Independent verification

The verifier should receive:

- this experiment file;
- `GAP.md`;
- `THREAT_PRIVACY_AUTHORITY.md`;
- `ROLLBACK.md`;
- the implementation diff;
- raw command outputs;
- route fixture outputs.

Verifier result may be `PASS`, `PASS_WITH_LIMITATIONS`,
`INSUFFICIENT_EVIDENCE`, `FAIL`, `SECURITY_BLOCK`, or `ARCHITECTURE_BLOCK`.

The implementer may not be the only verifier.
