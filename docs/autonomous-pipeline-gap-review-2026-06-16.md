# Autonomous pipeline gap review - 2026-06-16

This review reconciles the attached "Autonomous Pipeline for Multi-Source
Context, Desktop Automation, Kanban Orchestration, Self-Improvement, and
Continuous Validation" proposal against this repository's current Command Center
+ Growth OS implementation.

The attachment is useful as a hardening checklist. It does not justify replacing
the current stack with a new supervisor or tool bundle. The correct move remains:
preserve one control plane, one action layer, one approval wall, one mission
Ledger, one Kanban bridge, one model gateway, and one repo execution boundary;
then fill the remaining contract/test gaps in order.

## Decisions

1. **Keep the current control plane.** Do not adopt LangGraph, OpenAI Agents
   SDK, AutoGen, OpenHands, or another runtime as a competing supervisor. Those
   may be evaluated later as isolated adapter experiments only after a measured
   gap exists.
2. **Keep AppFlowy as the primary open-source Kanban surface.** GitHub Projects
   remains a conditional future adapter for repo-adjacent work, not a second
   active Kanban write path.
3. **Keep LiteLLM + Ollama local-only for model roles.** LiteLLM remains useful
   for virtual keys, role aliases, budgets, and metadata, but no provider
   fallback or cloud key is introduced.
4. **Treat desktop autonomy as the riskiest missing plane.** The repo should
   add a desktop-rights contract before adding any browser/native/screenshot
   adapter. API calls are preferred over browser automation; browser automation
   is preferred over OS accessibility; screenshot-only control is last resort.
5. **Do not import example KPI numbers as gates.** The attachment's numeric
   targets are planning examples. Any threshold, canary guard, repetition count,
   or stop rule used here must be derived from local baseline data, a
   pre-registered experiment plan, or explicit human approval.

## Coverage map

| Attachment capability | Current repo coverage | Gap |
| --- | --- | --- |
| One action layer | Covered by `growthos/actions.py` and shared channel surfaces | Keep consolidating new AppFlowy writes behind this layer |
| One approval wall | Covered by AppFlowy Approved refusal, Ledger approval, and GitHub wall | Add more end-to-end evidence packages for live approval flows |
| Mission ledger | Covered by Ledger and improvement experiment artifacts | Add typed route/action/evidence events for replay |
| Kanban bridge | Covered by `configs/kanban.yaml` and bridge writeback | Add explicit forecast-before-write artifacts for live board mutations |
| Local model routing | Covered by local-only contracts, model scout, live benchmark harness | Add typed route decision artifacts and structured-output role repair |
| Open-weight model discovery | Covered by curated open-weight source and provenance fields | Add more scored open-weight feeds and broader role-specific A/B suites |
| Self-improvement loop | Covered by scan, proposal-only experiments, verifier, canary/promotion gates | Add whole-system validation evidence packages and continuous canary schedule |
| Multi-source context | Partially covered by OKF, board state injection, docs, and generated artifacts | Missing canonical chat/artifact/context event model |
| Repo autonomy | Partially covered by environments, standards, leases, and GitHub wall | Missing per-repo manifest schema with devcontainer, CI, auth, and risk ceiling |
| Desktop automation | Not implemented as a governed plane | Missing desktop target schema, verifier contract, adapter, and kill-switch policy |
| Completion verifier | Partially covered by tests, judges, and tool loop breakers | Missing generic completion verifier tied to forecast evidence |
| Telemetry | Partially covered by logs, Ledger artifacts, usage digest, and metrics | Missing canonical trace/event field contract and OpenTelemetry decision |
| Progress notification | Partially covered by channel config and notify dry-run | Live channel proof still depends on intentionally supplied credentials |
| Privacy controls | Covered in many gates; benchmark artifacts are redacted | Add artifact-class privacy scan to whole-system validation runs |

## Contract gaps to close

### 1. Canonical event contract

Add a versioned event schema before building more autonomy. Minimum event
families:

- `mission.forecast`
- `mission.action`
- `mission.verification`
- `mission.rollback`
- `route.decision`
- `repo.action`
- `kanban.mutation`
- `desktop.observation`
- `desktop.action`
- `model.call`
- `notification.sent`

Minimum common fields:

- event id
- mission id
- timestamp
- actor
- source authority
- risk tier
- tool or adapter
- target reference
- input artifact hashes
- output artifact hashes
- trace id
- approval id when applicable
- rollback id when applicable
- privacy classification
- result

These events should be stored through the Ledger/evidence path. Raw chat text,
raw screenshots, secrets, and raw model benchmark prompts/outputs should not be
stored unless a human approves that artifact class.

### 2. Repo registration manifest

The current project registry records observed projects and the Kanban dispatch
contract records sections/risk ceilings. Autonomous repo work needs a stricter
execution manifest before broad use.

Proposed contract:

```yaml
schema_version: command-center.repo.v1
repo_id: example
remote_url: https://github.com/org/example
default_branch: main
auth_mode: github_app
allowed_base_branches:
  - main
execution_mode: devcontainer
devcontainer_path: .devcontainer/devcontainer.json
ci_commands:
  - uv run pytest
secret_policy: no_runtime_secrets_inside_container
codeowners_required: true
risk_ceiling: L2_local_edits
```

Validation should reject missing CI commands, missing devcontainer definition,
direct protected-branch writes, production secrets in repo-task environments,
unknown risk tiers, unknown auth modes, and unregistered repo targets.

### 3. Desktop rights manifest

Desktop automation must be rights-first. Add the contract before any adapter:

```yaml
schema_version: command-center.desktop-target.v1
target_id: appflowy-browser-staging
os_family: windows
surface: browser
allowed_windows:
  - AppFlowy
allowed_actions:
  - click
  - type
  - select
  - drag
  - keyboard_shortcut
forbidden_actions:
  - clipboard_read
  - password_field_read
  - system_settings_change
  - file_delete
verifier:
  type: ui_assertion
  must_show:
    - In Progress
ttl_minutes: 20
human_takeover_hotkey: Ctrl+Alt+Pause
```

Validation should reject overlapping allowed/forbidden actions, missing
verifier, unknown windows, excessive TTL without approval, password/clipboard
reads by default, and any desktop target that lacks a rollback or block policy.

### 4. Completion verifier and loop breaker

The system already has local tests and some tool-call loop breakers. The missing
piece is a generic mission completion verifier:

1. Compare observed state to the forecast.
2. Require concrete evidence references before `DONE`.
3. Detect repeated action triples or unchanged state hashes.
4. Force a strategy change after repeated failed verification.
5. Mark the mission `BLOCKED` rather than inventing success.

This should be deterministic first. Model-assisted judges can review whether the
evidence proves completion, but they cannot override a failed deterministic
verifier.

### 5. Continuous canary schedule

The repo has validations and live audits, but not a unified canary schedule for
the full pipeline. Add canaries as proposed work, not immediate autonomous
writes:

- read-only repo scan
- no-op Kanban roundtrip on a staging/test card
- browser task on a staging board
- prompt/judge suite
- model routing benchmark
- notification dry-run
- privacy artifact scan

The schedule and pass criteria must be config-derived. Numeric stop rules must
come from local baseline history or a pre-registered experiment.

## Ordered next work

1. **Add canonical event schemas and tests.** Start with route decisions,
   forecast/action/verification events, and evidence references. This unlocks
   reliable replay and learning without leaking raw data.
2. **Add repo registration manifest schema.** Cross-check observed projects,
   Kanban dispatch sections, environments, devcontainer presence, CI commands,
   auth mode, CODEOWNERS requirement, and risk ceiling.
3. **Add desktop target manifest schema.** Browser-first only at first. Validate
   rights, forbidden actions, verifier, TTL, target windows, and takeover policy.
4. **Add forecast/evidence verifier harness.** Make `DONE` impossible without
   matching observed state and retained evidence references.
5. **Add system-validation evidence runner.** It should create
   `evaluation/system-validation/<run-id>/` with baseline, scenarios, commands,
   privacy, forecasts, gaps, and next steps.
6. **Add no-op live canaries behind explicit config.** Begin with dry-run or
   staging cards only. Do not schedule production writes until a human approves
   the canary plan.
7. **Decide telemetry after event contracts exist.** OpenTelemetry can be added
   if the event schema shows a need for cross-service traces. Do not add another
   observability stack just because the attachment names one.
8. **Evaluate GitHub App auth as a separate production-hardening mission.**
   Fine-grained PATs may remain pilot-only; production long-lived repo autonomy
   should prefer a GitHub App if the registered repos are GitHub-hosted.
9. **Only then evaluate external runtimes.** LangGraph, OpenAI Agents SDK,
   AutoGen, and OpenHands should go through the external candidate evaluation
   loop and must not become second authorities.

## Validation notes from this pass

- This pass did not verify the external benchmark numbers in the attachment.
  They are treated as motivation for verifiers, loop breakers, and narrow
  authority, not as repository evidence.
- This pass did not enable desktop automation or new live writes.
- The current validated state remains the latest committed code plus the
  existing dirty user worktree changes outside this scope.
