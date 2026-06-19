# Continuous upgrade baseline - 2026-06-14

Scope: Phase 0 baseline for the continuous capability upgrade loop. This is
pre-implementation evidence for Mission 1, config-derived Judge Gate routing.

No runtime behavior was changed while creating this baseline. No candidate tool
was installed, registered, scheduled, or given credentials.

## Source prompts

Latest attachment hashes:

- Continuous capability prompt:
  `C:\Users\ghadf\.codex\attachments\174a97c6-32aa-48c0-b6bf-51d34050737b\pasted-text.txt`
  SHA256 `748E31D49CA56962BAC1303DB7F9A8D5E29F9182E7CB1A471AC5191E6BFE22E2`
- AI packages/tools notes:
  `C:\Users\ghadf\.codex\attachments\f77604f0-1fa2-4520-9f26-79ba34bdc79e\pasted-text.txt`
  SHA256 `BB0EA280A7F2337D00653FAEB461FFBBA93AAAF3E00587D041FD189CFBA2992D`

These hashes match the earlier attachment copies inspected in this session.

## Repository state

- Branch: `feat/agent-kanban-surface`
- Commit: `da28b6dd7f864e62b177bc2b9cd90d19049877de`
- Worktree: dirty before this artifact set was written.
- Platform: `Microsoft Windows NT 10.0.26200.0`
- PowerShell: `7.5.5`
- Python: `3.12.6`
- uv: `0.8.11`
- Docker: `29.0.1`
- Ollama: `0.30.8`
- `uv.lock` present: yes
- `uv.lock` SHA256:
  `D24F4DB82AE39597EB20A83436DAEC66C9E8B981914DD0E57855A5C1F9285F53`

Dirty files captured before writing this artifact set:

```text
M .gitignore
M appflowy_kanban/growth-os/agent/growthos_mcp.py
M appflowy_kanban/growth-os/growthos/actions.py
M appflowy_kanban/growth-os/growthos/assistant.py
M appflowy_kanban/growth-os/scripts/test_abilities.py
M docs/MASTER.md
M docs/backend/projects/AGENT_KANBAN_SURFACE.md
M docs/capability-evaluation-loop.md
M services/agent_kanban_ui/app.py
M src/command_center/channels/core.py
M tests/test_actions_intent.py
M tests/test_agent_kanban_ui.py
?? docs/agent-ideas-evaluation-prompt.md
?? docs/routing-performance-candidate-evaluation-2026-06-14.md
```

These are not reverted or normalized here.

## Config hashes

- `configs/models.yaml` SHA256:
  `438183494D6CAD84E842F933FB8C67099F0C6E60C02E054A37462F861A78DCE1`
- `configs/judges.yaml` SHA256:
  `1282478E1B9C5C18765B942B80E3D390DB44982878D46D89D213A47AB01A7B65`
- `configs/gates.yaml` SHA256:
  `44DE8B265452105A5819475E9D96950125AD2A291A3D91D1ADB72867F2596B55`
- `services/judge_gate/app.py` SHA256:
  `02EDBACA6E526C8AD9B141796CFDE28A944CADE80497BE19FCFF328DB128B71E`

## Implemented architecture truth

The incumbent architecture is the one in `docs/MASTER.md` and the live code:

- `configs/*.yaml` plus Pydantic contracts are source of truth.
- LiteLLM is the only model gateway for roles.
- Ollama is the current local runtime behind LiteLLM.
- Claude Code is the primary repository executor.
- Codex CLI is the fallback and independent verification executor.
- Judge Gate owns risk classification and judge/review policy.
- Ledger owns missions, leases, events, approvals, and experiment state.
- Growth OS/AppFlowy is the human work and knowledge surface.
- GitHub branch protection and human review remain the final wall.

The AI packages/tools attachment describes Hermes Agent as a primary
coordinator, but current repository truth is different: Hermes was evaluated
and deferred; it is not the active coordinator. This pass treats the attachment
as inventory, not implementation truth.

## Current routing seam

`services/judge_gate/app.py` contains the current local routing seam:

```text
ROUTE = {
    Risk.L0_READONLY:       "triage",
    Risk.L1_PLAN:           "planner",
    Risk.L2_LOCAL_CHANGE:   "coder",
    Risk.L3_EXTERNAL_WRITE: "coder",
    Risk.L4_DANGEROUS:      "architect-judge",
}
```

This is the confirmed hardcoded policy seam for Mission 1. It is small and
auditable, but it is not data-derived from `configs/gates.yaml`,
`configs/judges.yaml`, and `configs/models.yaml`.

## Baseline validation

Commands run on 2026-06-14:

| Command | Result | Evidence |
| --- | --- | --- |
| `uv run cc validate` | PASS | 17 config files validated; cross-refs PASS; rendered 7 roles; forbidden providers PASS |
| `uv run cc mission-dryrun` | PASS | L0, L1, L2, L3, L4 dry-runs PASS; L3/L4 require approval |
| `uv run cc evals` | PASS | 6 eval cases PASS |
| `uv run pytest tests/test_routing.py tests/test_safety_boundaries.py tests/test_sealed_evals.py tests/test_improvement_lifecycle.py` | PASS | 39 passed |

Full test suite was not run in this baseline pass. That is recorded as
`not_run`, not assumed.

## Baseline decision

Capability: config-derived Judge Gate routing.

Current state after this artifact set: `EXPERIMENT_PREREGISTERED`.

Reason: the gap is confirmed, baseline validation passed, and the experiment,
threat review, and rollback plan are written. Implementation has not started.

Next action: implement Mission 1 only, with tests, then rerun the frozen
baseline plus new routing fixtures.
