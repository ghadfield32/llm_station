# Gap - Mission 1 config-derived Judge Gate routing

## Capability

Config-derived Judge Gate routing.

## Current owner

`services/judge_gate/app.py` currently owns the risk-to-role route map with an
inline `ROUTE` constant.

## Current implementation

The current route map is:

```text
L0_READONLY -> triage
L1_PLAN -> planner
L2_LOCAL_CHANGE -> coder
L3_EXTERNAL_WRITE -> coder
L4_DANGEROUS -> architect-judge
```

The risk tiers are defined separately in `configs/gates.yaml`. Judge stages are
defined in `configs/judges.yaml`. Role aliases and executor aliases are defined
in `configs/models.yaml`.

## Gap statement

The policy that maps a risk tier to a model role is load-bearing routing
authority, but it currently lives as service code. That violates the local
contract pattern that configuration policy belongs in validated YAML and
schemas, then services consume validated data.

This gap is narrow. It does not justify adding a router, gateway, agent
framework, or model registry.

## Evidence

- `LOCAL_FACT`: `services/judge_gate/app.py` contains an inline `ROUTE` table.
- `LOCAL_FACT`: `configs/gates.yaml` defines the risk tiers but not default
  route aliases.
- `LOCAL_FACT`: `configs/judges.yaml` validates judge stage aliases against
  model roles, but the Judge Gate classify route table is not cross-referenced
  by config validation today.
- `LOCAL_FACT`: `uv run cc validate` passed before implementation.
- `LOCAL_FACT`: `uv run cc mission-dryrun` passed before implementation.
- `LOCAL_FACT`: `uv run cc evals` passed before implementation.
- `LOCAL_FACT`: focused tests passed before implementation:
  `uv run pytest tests/test_routing.py tests/test_safety_boundaries.py tests/test_sealed_evals.py tests/test_improvement_lifecycle.py`
  = 39 passed.

## Affected workflows

- `/classify` response `model_alias` in Judge Gate.
- Operator trust that routing policy changes are visible in config review.
- Future Ledger route artifacts, because route artifacts need source config
  hashes and validated route references.
- Future routing improvement experiments, because they should compare config
  variants rather than service-code constants.

## Why native improvement is sufficient

The current system already has:

- validated configs;
- local-only model roles;
- judge cross-reference validation;
- risk-tier approval rules;
- a routing improvement target;
- deterministic evals.

The smallest solution is to extend the existing config/schema/cross-ref path.
No external router is needed.

## Alternatives considered

| Alternative | Decision | Reason |
| --- | --- | --- |
| Keep inline `ROUTE` | Reject | Leaves routing policy outside config truth. |
| Add Puppetmaster runtime | Reject | Duplicates LiteLLM, Judge Gate, Ledger, leases, and model registry. |
| Add new route config under `configs/gates.yaml` | Candidate | Keeps risk-tier policy and route policy together; must preserve schema validation. |
| Add new route config under `configs/judges.yaml` | Candidate | Keeps route aliases near judges; may blur stage judges and classify route ownership. |
| Add a new `configs/routing.yaml` | Candidate | Clean separation; adds another config file and validation surface. |

The implementation decision is not made in this gap doc. It must be selected
during implementation based on minimal schema change, cross-reference clarity,
and `MASTER.md` consistency.

## Privacy and leakage

No raw prompts, `.env` values, provider tokens, transcripts, hidden eval
answers, or secret-bearing diffs are needed for this mission. Evidence should
be config hashes, route fixture names, command results, and redacted logs if an
error occurs.

## Current state

`GAP_CONFIRMED`.
