# Results - Mission 1 config-derived Judge Gate routing

Status after implementation: `INDEPENDENT_VERIFICATION_PASSED`.

Promotion status: not requested.

## Implementation summary

Implemented the smallest native change:

- `configs/gates.yaml` now carries `default_route_alias` for each risk tier.
- `src/command_center/schemas/contracts.py` requires `default_route_alias` on
  every `TierPolicy`.
- `src/command_center/cli/check_cross_refs.py` validates every gate default
  route against `configs/models.yaml` roles.
- `services/judge_gate/app.py` loads `ROUTES_BY_RISK` from `GATES_CONFIG` and
  validates it against `MODELS_CONFIG` at import/startup.
- `docker-compose.yml` mounts `gates.yaml` and `models.yaml` read-only into the
  Judge Gate container.
- `tests/test_routing.py` covers route cross-reference and route parity.
- `tests/test_judge_gate_routing_config.py` covers service startup route
  loading, missing route rejection, and dangling alias rejection.

No external router, package, provider key, daemon, MCP registration, hook,
second gateway, second ledger, raw transcript store, or hidden eval access was
added.

## Validation results

Post-change commands:

| Command | Result |
| --- | --- |
| `uv run cc validate` | PASS |
| `uv run cc mission-dryrun` | PASS |
| `uv run cc evals` | PASS |
| `uv run pytest tests/test_routing.py tests/test_judge_gate_llm.py tests/test_judge_gate_routing_config.py` | PASS, 16 passed |
| `uv run pytest tests/test_routing.py tests/test_judge_gate_llm.py tests/test_judge_gate_routing_config.py tests/test_safety_boundaries.py tests/test_sealed_evals.py tests/test_improvement_lifecycle.py` | PASS, 50 passed |
| `uv run ruff check src services tests` | PASS |
| `uv run mypy src/command_center/schemas/contracts.py` | PASS |
| `uv run pytest` | PASS, 562 passed, 1 Starlette/httpx deprecation warning |

Broad static check note:

- `uv run mypy src` failed with 39 existing repository-wide issues, mostly
  missing PyYAML stubs, growthos import stubs, and unrelated typing problems.
  This is not claimed as passing. The touched schema file passes mypy, and the
  full pytest suite passes.

## Privacy and data handling

No secret-bearing files, `.env` content, provider tokens, raw transcripts,
browser cookies, or hidden eval answers were copied into the evidence. Evidence
is limited to config paths, hashes, route aliases, command summaries, and test
results.

## Independent verification

Initial independent verifier result: `FAIL`.

Reason: the verifier found the functional/security implementation acceptable
but blocked promotion-readiness because `docs/MASTER.md` and `experiment.yaml`
still said the mission was pre-implementation.

Verifier re-check result: `PASS_WITH_LIMITATIONS`.

The limitation was stale older backlog text in `docs/MASTER.md` that still
described Mission 1 as future work. That text has been corrected. Mission 1 is
not promoted automatically; human promotion remains separate.

Final narrow verifier re-check result: `PASS`.

The final re-check found no remaining stale text framing config-derived Judge
Gate routing as future work and no pending verifier-state text.
