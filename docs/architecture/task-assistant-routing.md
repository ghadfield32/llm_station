# Task-category assistant routing

Status: proposed implementation packet. Runtime implementation and independent
review are not complete.

Date: 2026-07-16

Base: `main` at `963b0631844b8549cf6ca4cda416400890231e34`. The
worktree was already extensively dirty, so this packet changes no runtime,
configuration, generated evidence, provider posture, or durable state.

## Objective and boundaries

Add an adjustable, explainable `Auto` route from a task category to an
Assistant, using current availability and usage evidence without silently
changing runtime, authority, model lane, or cost posture.

```text
context + task category + risk + requested permission
  -> capability profile
  -> eligible Assistant candidates
  -> usage/availability evaluation
  -> human-visible preview
  -> confirmed Assistant
  -> conditional model/effort settings
  -> existing GatewayCore or agent-session transport
```

An Assistant is a runtime boundary. GatewayCore is the local completion/tool
runtime; Claude Code and Codex are coding-agent runtimes. Growth OS, boards,
tasks, captures, and repositories are context. A frontier model is a model lane
inside GatewayCore, not an Assistant.

Non-goals for the first implementation slice:

- no model promotion, provider enablement, budget change, or credential change;
- no automatic paid-frontier selection;
- no automatic write permission, mission approval, merge, or deployment;
- no task-category inference by an external model;
- no reassignment of a conversation after its first committed turn;
- no replacement of the existing GatewayCore or agent-session transports;
- no learned policy before a past-only evaluation has sufficient evidence.

Operator-only actions remain: start/restart the host agent worker, set or rotate
its token, approve provider/budget changes, approve a write-capable mission,
deploy, commit, publish, merge, or promote a routing challenger.

## Grounded current state

| Seam | Authority | Current conclusion |
| --- | --- | --- |
| Local model roles | `configs/models.yaml` | Seven local Ollama/LiteLLM roles exist. Coding executors are separate subscription/OAuth harnesses. Role priority is model routing, not Assistant routing. |
| Frontier lane | `configs/frontier-router-providers.yaml` and `configs/frontier-router-budgets.yaml` | The paid lane is separately budgeted, redacted, usage-logged, and task-class-restricted. It cannot be an autonomous Assistant fallback. |
| Usage layer | `configs/usage-monitoring.yaml` and `command_center.usage` | Canonical availability, limit, budget, staleness, attribution, and `RoutingDecision` types exist. `allow_silent_fallback` is contract-refused. No Assistant router consumes them yet. |
| Assistant catalog | `GET /api/assistants` and `command_center.assistants.catalog` | Auto, GatewayCore, and three production agent harnesses are normalized. Auto is descriptive only; there is no category policy or dispatcher. |
| Cockpit selector | `services/agent_kanban_ui/web/src/App.tsx` | The UI still builds choices from chat runtime plus `/api/agent-harnesses`; it does not use `/api/assistants` as its single catalog or offer an Auto preview. |
| Dispatch | `/api/chat*` and `/api/agent-sessions*` | GatewayCore and agent sessions are intentionally separate paths and must remain separate. |
| Live catalog | `GET /api/assistants`, 2026-07-16 | GatewayCore, Auto, Codex Agent, and local-subscription Claude report available after the operator-authorized host-worker restart. The optional Claude API lane remains visible and unavailable because its SDK extra is not installed. |
| Live usage | `GET /api/model-usage`, 2026-07-16 | Codex and Claude records exist, but their current observations are stale. Stale or unknown evidence cannot be presented as current capacity. |

The cockpit error-boundary/SDK-shape fix is deployed separately. The host worker
was restarted with the matching `AGENT_WORKER_TOKEN` and verified through both
the direct authenticated API and cockpit proxy. That live run exposed one more
SDK wrapper→enum effort shape; recursive normalization now returns a nonempty
Codex catalog with string-only effort values instead of a browser object or an
opaque failure.

## Configuration contract

Introduce `configs/assistant-routing.yaml`, validated by a strict Pydantic
contract (`extra="forbid"`) and cross-reference validation:

```yaml
schema_version: command-center.assistant-routing.v1
enabled: false
default_mode: preview_only

evidence:
  usage_max_age_seconds: 300
  preview_ttl_seconds: 60
  unknown_usage:
    local_unmetered_gateway: eligible_with_disclosure
    agent_or_paid_lane: confirmation_required

categories:
  conversation:
    capability_profile: local_action_chat
    risk_ceiling: L1
    candidates:
      - {assistant_id: gatewaycore, preference: 1}
  repository_analysis:
    capability_profile: generalist
    risk_ceiling: L2
    candidates:
      - {assistant_id: claude_code_local, preference: 1}
      - {assistant_id: codex_agent, preference: 2}
  deep_code:
    capability_profile: deep_code
    risk_ceiling: L3
    candidates:
      - {assistant_id: codex_agent, preference: 1}

manual_only_model_lanes: [frontier, local_frontier]
```

The values above are an illustrative disabled seed and require operator review.
Contract rules:

1. Category IDs and candidate preferences are unique.
2. Capability profiles come from a committed enum shared with the engineering
   workflow; model IDs never appear in category policy.
3. Static Assistant IDs cross-reference GatewayCore plus production harness
   descriptors. Dynamic catalog absence is a runtime rejection.
4. Version one initially permits only `preview_only`.
5. Silent fallback is not configurable.
6. Frontier lanes cannot occur in Assistant candidate lists.
7. Permission and risk ceilings narrow authority; they never grant it.
8. Evidence age and preview lifetime come from config, not hidden constants.
9. No implicit candidate is synthesized.
10. Ties, cycles, or duplicate preferences fail config validation.

## Resolver contract

The resolver is pure and side-effect-free:

```python
resolve_route(request, policy, assistant_catalog, usage_snapshots, now)
    -> RoutePreview
```

`RouteRequest` contains the explicit task category, stable context kind/ID,
risk, requested permission, optional Assistant override, repo availability, and
a client idempotency key. It does not need raw private task text.

`RoutePreview` contains:

- preview ID, policy hash, evidence timestamp, and expiry;
- category and capability profile;
- every configured candidate in preference order;
- catalog state, capability/permission fit, usage state/freshness, evidence IDs,
  eligibility, and plain-language accept/reject reason per candidate;
- exactly one recommendation or none;
- whether confirmation is required and why;
- transport only after confirmation;
- the selected runtime's conditional settings endpoint.

### Eligibility and ranking

Evaluation is lexicographic, not an opaque score:

1. Reject a missing/disabled Assistant, unavailable runtime, failed auth,
   unsupported mode/context, missing repo, excessive risk, or insufficient
   permission.
2. Reject `exhausted` according to the usage contract.
3. Treat unknown and stale evidence honestly. A configured local, unmetered
   GatewayCore route may remain eligible with disclosure. Agent or paid lanes
   require confirmation and cannot be called available from usage evidence.
4. Respect reserved high-risk capacity. Near-limit capacity is deprioritized
   for lower-risk categories; warning/critical thresholds come from
   `usage-monitoring.yaml`.
5. Among eligible candidates, use configured preference. Availability cannot
   promote a candidate lacking the required capability.
6. A tie is a configuration error.

If the primary is rejected and another candidate is eligible, the result is a
**proposed fallback**. The user must see the original rejection, replacement,
and authority/settings change before confirmation. With no eligible candidate,
return a blocked preview with all reasons and no dispatch token.

Paid frontier behavior is stricter: routing may suggest a manual GatewayCore
model-lane choice only when all budget/task/payload gates pass. It never inserts
`frontier:*` as an Assistant fallback, and live repo context still requires
the frontier contract's human approval.

## Preview, confirmation, and dispatch APIs

```text
GET  /api/assistant-routing/policy
POST /api/assistant-routing/preview
POST /api/assistant-routing/confirm
```

The policy endpoint returns safe UI metadata, never credentials. Preview is
read-only. Confirmation supplies preview ID, selected Assistant, policy hash,
evidence IDs, and explicit acknowledgement reasons. The server re-evaluates if
the preview expired or policy/catalog/evidence changed; a changed answer returns
a new preview and performs no dispatch.

On unchanged confirmation:

- GatewayCore returns a one-use selection receipt for the existing chat path.
- An agent route creates a session through the existing agent-session service.
- The coordinator never forwards agent messages into GatewayCore or vice versa.

Confirmation and session creation share one idempotency key. A replay returns
the same receipt/session. Worker failure after selection is recorded and
surfaced; no other Assistant is substituted. Explicit manual selection remains
available and records a manual routing decision. Auto means “recommend and
explain,” not “run without review.”

## Conditional model and effort settings

- GatewayCore choices come from `models.yaml` plus separately gated frontier
  catalogs.
- Agent model/effort choices load lazily from the selected harness endpoint.
- The typed boundary continues rejecting object-shaped effort values before
  React renders them.
- The router records the required capability profile and does not infer it from
  a stale model string or alias.
- SDK-default fallback is acceptable only when current policy permits it and the
  resolved default is evidenced as profile-compatible.

Model discovery failure is visible and blocks when the model is a hard profile
requirement. It never silently selects a model, Assistant, or lower effort.

## Durable evidence

Before dispatch enablement, version routing telemetry to capture one attempt ID
and one row per evaluated candidate:

- policy hash, category, capability profile, risk, and permission;
- preference, catalog availability, and reason;
- usage state, staleness, timestamps, limit IDs, and budget state;
- selected Assistant/transport/model/effort and fallback/manual-override flags;
- confirmation actor/time/reasons;
- receipt/session ID and terminal dispatch result;
- superseded preview ID after re-evaluation.

No raw prompt, private todo text, credential, env value, or provider response is
needed. Evidence stays append-only under the existing indefinite routing
retention policy.

## Cockpit experience

Use `/api/assistants` as the catalog and show three progressive fields:

1. **Context** — board, task, repo, or life scope.
2. **Assistant** — Auto or an explicit runtime.
3. **Settings** — only those supported by the selected runtime.

Auto shows one recommendation, the category, current evidence freshness, why
the primary was accepted/rejected, and the exact result of confirmation.
Alternatives live under “Other assistants.” A fallback banner names both
runtimes and the reason. Paid frontier has a distinct cost/egress confirmation.
Unavailable Assistants remain visible with server reasons. Stale/unknown
evidence is never a green badge.

The mobile layout is one column, keyboard/screen-reader accessible, and never
uses color alone. An established thread's Assistant is immutable. Changing it
starts a new thread with an inspectable redacted handoff; it never moves or
rewrites the existing transcript.

## Failure, security, and concurrency rules

- The server owns eligibility and reasons; React cannot forge them.
- Inputs are strict and length-bounded; browser requests use stable IDs.
- Collector failure leaves usage unknown/stale.
- Worker/token failure blocks agents and never degrades to GatewayCore.
- Provider/budget/redaction failure blocks frontier.
- Permission profiles only narrow authority; routing cannot approve, write,
  merge, deploy, or bypass human walls.
- Confirmation compares policy hash and evidence IDs.
- Idempotency prevents duplicate sessions on retries/double-clicks.
- A confirmed preview is consumed once; replay returns the same result.
- Logs use reason codes and safe summaries, not prompts or secrets.
- The feature defaults to preview-only; rollback leaves explicit transports.

## Goal-driven KPI leaderboard

The baseline is explicit manual Assistant selection. Evaluate challengers
offline using only evidence available before each decision (temporal split; no
future outcomes or quota state).

Hard gates, all required at zero:

- silent fallbacks;
- stale evidence represented as current;
- capability/permission violations;
- frontier calls without confirmation;
- duplicate session creation;
- conversation-target mutation;
- lost routing evidence.

Rank eligible challengers using correct first recommendation, override rate by
category, explanation completeness, dispatch success, authoritative task
completion, exhaustion avoidance, latency, and fallback acceptance. Report
support/confidence and abstain when evidence is insufficient. Promotion remains
human-only and requires a later temporal fold. Generated leaderboard evidence
is reproducible and never hand-edited.

## Verification matrix

The implementation must add:

- strict config/cross-reference negative tests;
- resolver tables for every catalog and usage state, including staleness;
- proof that rejected primaries are visible and fallbacks require confirmation;
- expiry, changed-evidence, idempotency, concurrency, replay, and post-confirm
  worker-failure tests;
- GatewayCore/agent transport-separation tests;
- frontier budget/redaction/approval negative tests;
- durable telemetry and privacy tests;
- catalog degradation tests;
- React conditional-settings, stale badge, fallback, immutable handoff,
  accessibility, and error-boundary tests;
- temporal leakage and baseline/challenger reproducibility tests;
- affected pytest, `cc lint`, `cc validate`, TypeScript/Vite build,
  `cc doctor`, and live read-only validation.

## Staged delivery and rollback

1. Contracts, disabled config, resolver, and telemetry versioning.
2. Read-only preview API behind a feature flag.
3. Context → Assistant → Settings preview UI.
4. Confirmed dispatch canary for selected low-risk categories.
5. Broaden only after KPI evidence, independent review, and approval.
6. Evaluate a past-only challenger; human promotion or rollback.

Rollback disables Auto and preserves explicit selectors plus all sessions,
transcripts, usage records, and routing evidence.

## Review allocation and open gates

- Required capability: `strategic_steward` for policy/authorization semantics
  and `deep_code` for the future resolver/idempotency/durable-state slice.
- Live Codex catalog on 2026-07-16: Codex CLI 0.144.4 exposes
  `gpt-5.6-sol`; `xhigh` is supported and was selected for plan review.
- Claude Code 2.1.210 is authenticated and accepts the `fable` alias, but
  exposes no exact model catalog; no exact Claude model ID is claimed.
- The fresh read-only Codex plan review did not start because the account's
  external usage limit was reached. No independent verdict is claimed. This
  remains a blocking gate before runtime implementation.
- `cc doctor` reports 20 PASS and one inherited
  `dirty_generated_evidence` failure. Operator-owned evidence was untouched.

Before runtime implementation, obtain a fresh read-only plan review, reconcile
its findings, and freeze exact allowed files/tests. After implementation, run a
separate fresh final-diff review and rerun every accepted finding gate.
