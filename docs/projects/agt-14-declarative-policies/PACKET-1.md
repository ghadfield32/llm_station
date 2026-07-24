# AGT-14 packet 1 — implementation brief (Sol write-mode)

Authoritative context: `RUNDOC.md` in this directory (§1 DoD, §4 plan, §5
LOCKED Stage-4 decisions), plus repo `CLAUDE.md` engineering standards.
Branch: `feat/agt14-session-policies` (this isolated worktree, stacked on the
AGT-16 spec branch so `AgentSessionSpec.policy_refs` already exists). Never
push; commit locally with exact-path staging only.

Profile: **deep_code** (security-sensitive durable contract) — effort
**xhigh**. You are Sol; a separate Fable session wrote AGT-16 and will review
you, so reviewer independence holds.

## The idea (from omnigent docs/POLICIES.md, borrow_pattern_only)

Declarative policy gates evaluated at an enforcement point, returning
**ALLOW / DENY / ASK**. ASK pauses for human approval (approved→ALLOW,
refused→DENY). Policies compose in declaration order; any DENY short-circuits.
Three levels, **stricter-first**: session (evaluated FIRST, can short-circuit)
→ agent → server (evaluated LAST). We borrow the shape, not their code.

## Deliverables

1. **Schema** — `src/command_center/schemas/session_policy.py` (subclass
   `Strict`, `extra="forbid"`):
   - `PolicyVerdict` StrEnum: `allow`, `deny`, `ask`.
   - `PolicyLevel` StrEnum: `session`, `agent`, `server` (evaluation order is
     session→agent→server, i.e. stricter-first).
   - `PolicyRule`: `handler` (dotted path StrEnum over the builtins below —
     NOT a free-form import string; unknown handler must fail validation),
     `params: dict` (validated per-handler at load, see §3), optional `note`.
   - `PolicySet`: `name` (slug), `level`, `rules: list[PolicyRule]`.
   - `SessionPoliciesConfig`: `schema_version`, `policy_sets: list[PolicySet]`
     with unique names.
2. **Config** — `configs/session_policies.yaml` with the three seed sets
   wired + comment headers matching other configs/. Validated by
   `make validate` (extend `validate_config` the same way AGT-16 added the
   agent_sessions glob — one more contract entry).
3. **Engine** — `src/command_center/agent_sessions/policy_engine.py`:
   - A pure `evaluate(rules_in_level_order, action) -> PolicyDecision` that
     runs declaration order, returns the first DENY (short-circuit), else ASK
     if any ASK, else ALLOW. `action` is a typed `ToolAction` dataclass
     (tool name, is_os_tool bool, estimated_cost_usd float|None, session
     tool-call count).
   - A `resolve(policy_sets, action)` that evaluates **session level first,
     then agent, then server**, short-circuiting on the first DENY at any
     level — this is the stricter-first floor: a permissive server set can
     NEVER un-DENY what session/agent denied.
4. **Three builtins** — `src/command_center/agent_sessions/policy_builtins.py`:
   - `ask_on_os_tools` → ASK when `action.is_os_tool`.
   - `max_tool_calls_per_session(limit)` → DENY when count > limit.
   - `cost_budget(max_cost_usd, ask_thresholds_usd=[])` → DENY over the hard
     cap, ASK at/over a soft threshold, else ALLOW. Consume the
     `src/command_center/usage/` budget concept for the running total — do
     NOT invent a parallel cost store; read the existing one. If the usage
     layer's read surface isn't a clean fit, wire the minimal read and note
     it in your report — do not duplicate accounting.
5. **Flagged enforcement hook** — in `service.py` (the session worker path):
   when env `AGENT_SESSION_POLICIES_ENABLED=1` (default OFF), the service
   evaluates a tool action against the session's resolved policy sets before
   it is dispatched/approved; a DENY raises a typed refusal recorded as an
   event, an ASK routes into the EXISTING `approval_required`/`resolve_approval`
   path (no new approval surface), ALLOW proceeds. Flag off → the send/approval
   path is byte-for-byte unchanged. Resolve policy sets lazily per call (no
   import-time scan; tests monkeypatch).
6. **Floor-integrity is the point** — a dedicated test module proving:
   - A permissive server-level ALLOW cannot override a session-level DENY
     (stricter-first).
   - No policy set can produce a verdict that grants an agent MORE than the
     hard floors: human-only resolution (an ASK is resolved only by a human
     decision, never auto-allowed by another policy), read-only cockpit
     sessions stay read-only, and there is no policy input that turns a DENY
     into ALLOW. Encode these as explicit tests that would FAIL if someone
     later added a "grant"/"override" verdict.
7. **Tests** — `tests/test_session_policy.py`:
   - Schema: YAML round-trip, unknown-key rejection, unknown-handler
     rejection, per-handler param validation.
   - Engine: ALLOW/DENY/ASK, declaration-order short-circuit, stricter-first
     across levels.
   - Builtins: each of the three, incl. cost_budget soft-threshold ASK vs
     hard-cap DENY, and the usage-layer read.
   - Consumer: flag off → identical path (assert no policy events, same
     behavior with FakeHarness); flag on → DENY recorded + dispatch refused,
     ASK routes to approval_required. Monkeypatch env + policy dir.
   - Floor-integrity module (§6).
   - `configs/session_policies.yaml` validates.

## Constraints (hard)

- No new dependencies. No edits to `.env*`, `docs/MASTER.md`,
  `services/agent_kanban_ui/`, Ledger schema files, or the existing approval
  wall's semantics (you consult it, you do not weaken it). Do not loosen any
  existing wall. Policies may only TIGHTEN.
- No swallowed exceptions, no silent fallbacks, no fake/default data, no
  invented thresholds (the seed config's numbers are examples, clearly
  commented as operator-tunable — not claimed as validated limits).
- Match surrounding code style/comment density (see registry.py, protocol.py,
  spec_bridge.py idioms). One editing agent in this worktree: you.

## Validation to run and record (commands + exit codes in your final output)

```
uv sync --extra dev                                     # once, in this worktree
uv run python -m command_center.cli.validate_config
uv run python -m command_center.cli.check_cross_refs
uv run pytest tests/test_session_policy.py -q           # ONE pytest process at a time
uv run pytest tests/test_agent_session_spec.py tests/test_agent_sessions.py -q   # no regression
uv run ruff check <changed files>
```

Run everything FROM this worktree (`uv sync` here; the sandbox blocks network
so if sync fails, fall back to the provisioned env + this worktree's
`PYTHONPATH=<worktree>/src` and say so). If the sandbox blocks the git commit
(it did for AGT-16 — worktree git metadata is read-only to the sandbox), that
is expected: do NOT fight it, report "implemented, uncommitted" and I commit
host-side.

## Done =

All deliverables present, all commands above exit 0 (or the pre-existing
5-failure `test_agent_session_service` set unchanged — do not touch it),
final message lists: files changed, commands + exit codes, floor-integrity
test names, and any deviation from this brief (flagged, never silent).
