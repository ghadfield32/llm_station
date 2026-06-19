# Rollback - Mission 1 config-derived Judge Gate routing

## Goal

Restore the pre-mission Judge Gate classify routing behavior if the
config-derived route change fails validation, verification, startup, or safety
review.

## Pre-mission behavior

```text
L0_READONLY -> triage
L1_PLAN -> planner
L2_LOCAL_CHANGE -> coder
L3_EXTERNAL_WRITE -> coder
L4_DANGEROUS -> architect-judge
```

## Rollback requirement

Rollback must restore behavior, not merely reintroduce hidden fallback. If the
config route representation is kept, it must still be validated and explicit.

## Rollback procedure

1. Stop the Judge Gate service if it is running.
2. Revert only the Mission 1 implementation files.
3. Preserve evaluation artifacts and raw command outputs.
4. Re-run:

```powershell
uv run cc validate
uv run cc mission-dryrun
uv run cc evals
uv run pytest tests/test_routing.py tests/test_safety_boundaries.py tests/test_sealed_evals.py tests/test_improvement_lifecycle.py
```

5. Record rollback result in this directory and update `docs/MASTER.md`.

## Rollback success criteria

- Current five risk tiers resolve to the pre-mission aliases.
- L3 and L4 still require approval.
- Forbidden provider checks pass.
- No global config, MCP, hook, credential, or hidden eval file was touched.
- Evidence remains available for audit.

## Rollback blockers

Any of these means rollback is not proven:

- route behavior cannot be reproduced;
- validation fails;
- missing alias is silently accepted;
- unknown route produces a default alias;
- a secret or raw transcript appears in evidence;
- global config was changed and cannot be restored.
