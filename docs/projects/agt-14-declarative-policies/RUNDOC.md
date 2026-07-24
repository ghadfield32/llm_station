# AGT-14 · Declarative session policy stack — RUNDOC

Stage 3 run-doc per [TODO_PROCESS.md](../../todos/TODO_PROCESS.md). Status:
**awaiting Stage-4 answers** — do not start execution with §5 open.

## 1. Objective & definition of done

Typed, declarative policy documents that gate what an agent session may do,
evaluated at three stricter-first levels (session → agent → server) with
**ALLOW / DENY / ASK** verdicts, where ASK routes into the existing
approval-wall idiom. Done when: (a) a Pydantic `extra="forbid"` policy schema
validates under `make validate`; (b) at least the three seed builtins
(ask-on-os-tools, max-tool-calls-per-session, cost-budget with soft
ask-thresholds wired to `src/command_center/usage/` budgets) enforce on real
agent-session tool calls with tests proving ALLOW, DENY, ASK, and
declaration-order short-circuit; (c) policies can only tighten — a test
proves the hard floors (human-only resolutions, read-only cockpit sessions,
destructive double-agreement) cannot be loosened by any policy document.

## 2. Research (verified)

- Pattern source: omnigent `docs/POLICIES.md` @ main, read raw 2026-07-23
  (repo live-verified: 7,679★, Apache-2.0, v0.6.0). Full analysis:
  [2026-07-23-omnigent-borrow-patterns.md](../../reviews/2026-07-23-omnigent-borrow-patterns.md).
- Our seam today: enforcement is code-shaped across
  `src/command_center/agent_sessions/` (worker_app, mutation_proof,
  secret_paths), UI guards in `services/agent_kanban_ui/app.py`, and the
  chat→Kanban governance wall. No single inspectable policy artifact exists.
- The usage layer (PR #34 workstream) already keeps usage/limit/availability/
  budget distinct — `cost_budget` must consume that budget concept, not
  invent a parallel one.

## 3. KPIs & baseline

- Baseline (measured 2026-07-23): **0** declarative policy documents;
  session-level behavioral gates exist only as code.
- KPI-1: count of enforcement points gated by a validated policy document
  (baseline 0; target set at Stage 4 with the operator — not invented here).
- KPI-2: floor-integrity — the cannot-loosen test suite stays green (hard
  requirement, not a score).
- Stop condition: the three seed builtins enforced + floors proven, then
  reassess before widening coverage (champion/challenger on KPI-1).

## 4. Plan (bounded)

1. Schema: `PolicyDoc` / `PolicyLevel` / verdict enum under
   `src/command_center/schemas/` + a `configs/` policy file with
   `make validate` coverage.
2. Engine: declaration-order evaluation, session-first short-circuit, ASK →
   existing approval wall (no new approval surface).
3. Seed builtins + tests (ALLOW/DENY/ASK/short-circuit/floor-integrity).
4. Wire into the agent-session worker's tool-call path behind a flag.
- Allowed: `src/command_center/schemas/`, `src/command_center/agent_sessions/`,
  `src/command_center/usage/`, `configs/`, `tests/`.
- Forbidden: `services/agent_kanban_ui/` UI (later packet), `.env`, Ledger
  schema migrations, any loosening of existing walls, `docs/MASTER.md`
  (digest re-record — separate deliberate pass).
- Validation: `make validate`, targeted pytest, `make lint`; `uv run cc
  doctor` if worker wiring lands.

## 5. Open questions — ANSWERED (Stage-4 gate passed 2026-07-24)

Operator decisions, recorded verbatim; scope locked:

1. Enforcement points: **agent-session tool calls only** for packet 1 (the
   session worker's tool-call/approval path). Chat→Kanban write proposals
   stay on their existing governance wall — a later packet.
2. Policy home: **one `configs/session_policies.yaml`** — a validated file of
   named policy sets; AGT-16 specs reference them via the existing
   `policy_refs` field.
3. KPI-1 target v1: the **three seed builtins** enforcing on the tool-call
   path (ask-on-os-tools, max-tool-calls-per-session, cost-budget) + the
   floor-integrity suite green. Widening coverage is a later challenger.
4. Flag default: **flag-off on first merge** — `AGENT_SESSION_POLICIES_ENABLED`
   defaults OFF (same opt-in idiom as AGT-16's `AGENT_SESSION_SPEC_ENABLED`);
   floors are tested regardless of the flag.

## 6. Model allocation

- Profile: **deep_code** (durable-state + security-sensitive contracts) →
  **Sol writes**: `codex exec --sandbox workspace-write --full-auto -C
  <isolated worktree>`, effort **xhigh**.
- Resolved live 2026-07-23: `codex debug models` → **gpt-5.6-sol**
  (priority 1, lowest = current; terra=2 retired from default mapping).
- Fallback: if the harness policy classifier blocks Sol write-mode, surface
  to operator for a scoped permission rule — never a silent Claude/Opus
  handoff.
- Independent review: Sol wrote → **Fable** (methodology/security) read-only,
  fresh session; floor-integrity test design reviewed by Fable before
  implementation.

## 7. Packet-1 evidence (2026-07-24)

- **Implemented by Sol** (`codex exec --sandbox workspace-write --full-auto`,
  gpt-5.6-sol **xhigh** — deep_code, resolved live priority 1; brief:
  [PACKET-1.md](PACKET-1.md)) in isolated worktree `C:\tmp\agt14-policies`
  stacked on the AGT-16 spec branch. Sandbox correctly blocked the git
  commit → committed host-side after independent verification.
- **Delivered**: `session_policy.py` (Strict schema, **closed** PolicyHandler
  enum so YAML can never name an import), `policy_engine.py` (pure monotone
  session→agent→server `resolve`, no grant/override op), `policy_builtins.py`
  (3 builtins), `configs/session_policies.yaml` (validated; numbers labeled
  operator-tunable examples), flag-off `AGENT_SESSION_POLICIES_ENABLED`
  enforcement hook in `service.py` routing DENY→durable `policy_denied`
  event + typed `PolicyRefusal`, ASK→existing approval wall; canonical usage
  read via new `UsageService.session_cost_usd` (no parallel accounting).
- **Independently verified host-side** (Fable, this session — did NOT write
  AGT-14; Sol did — so a valid cross-family reviewer per the
  reviewer-independence rule): validate_config PASS, check_cross_refs PASS,
  `pytest test_session_policy.py + floor_integrity` 29/29, regression
  (spec + sessions + registry) 34/34, ruff clean on all 11 files. The 5
  `test_agent_session_service` failures remain the pre-existing KAN-25
  `user_message` family (unchanged; resolves on merge with main).
- **Floor-integrity (the point)** — machine-proven, 4 tests:
  `test_permissive_server_allow_cannot_override_session_deny` (checks **all
  permutations** of declaration order → session DENY always wins),
  `test_human_only_ask_is_never_auto_allowed_by_another_policy`,
  `test_read_only_and_destructive_floors_survive_every_policy_verdict`
  (one approval ≠ destructive double-agreement; read_only stays read_only),
  `test_policy_language_has_no_grant_or_override_verdict` (locks the verdict
  set to allow/deny/ask — a future "grant" verdict fails this test).
- **Review verdict: APPROVE.** Non-blocking notes for a later packet:
  (1) cosmetic redundant `yield event` in both ASK branches of
  `send_message`; (2) an ASK abandons the harness generator to pause — correct
  for the read-only analysis milestone, revisit when write-mode/steering
  lands; (3) deep-review-before-enable: since the flag is OFF by default, a
  fresh-Sol deep read is available on request before the operator flips
  `AGENT_SESSION_POLICIES_ENABLED=1`.
- **KPIs vs baseline**: KPI-1 = 3/3 seed builtins enforcing on the tool-call
  path behind the flag (baseline 0 declarative policy docs). KPI-2 =
  floor-integrity suite green (hard requirement met). Stop condition met —
  reassess before widening to chat→Kanban proposals.

## 8. Links

- Master item: `docs/todos/GRAND_TODO_LIST.md` → AGT-14 (feeds KAN-17).
- Board/mission card: pending Stage-5 human approval — not created before
  that gate (the importer projects the AGT-14 card from the master list).
- Pattern doc: `docs/reviews/2026-07-23-omnigent-borrow-patterns.md`.
- Catalog row: `knowledge/research/source_catalog.yaml` →
  `omnigent-meta-harness`.
- Siblings: AGT-15 (bench), AGT-16 (session spec — policy refs live there).

## 9. Packet 2 evidence + pre-enablement deep review (2026-07-24)

**Packet 2 (Sol gpt-5.6-sol xhigh):** a tighten-only policy gate BEFORE an
agent-authored board-change proposal is created, flag-gated by
`AGENT_SESSION_POLICIES_ENABLED` (default OFF). DENY → durable `policy_denied`
event + typed 403 before `make_proposal` runs; ASK → routes to the EXISTING
human-token wall (no second approval surface); ALLOW → untouched flow. Commit
`a7aa2d3`; finding-4 fix `c32b6b1`. Host-verified: validate PASS, 36 policy/
floor/board-gate + 56 UI + 93 board/worker/proxy tests, ruff clean, vite build
exit 0. `board_change.py` integrity code untouched (verified). Safety invariant
machine-proven: no policy verdict (allow/ask/deny) applies without the human
token; flag-off path identical (after the finding-4 fix flag-gates the worker
endpoint).

**Fresh-Sol pre-enablement DEEP REVIEW — VERDICT: DO-NOT-ENABLE.** An
independent read-only Sol session (xhigh) audited the whole policy system
(packet 1 on main + packet 2). It confirmed what HELD (board wall never
bypassed; `resolve()` monotone; closed enum, no import injection; no
permission-profile mutation; flag-off identity after finding-4). It found
**four blockers to flipping the flag**, now tracked as **AGT-19 (BLOCKED,
P1)**: (1) CRITICAL — tool-call enforcement is observational not preventative
(evaluates on `tool_started`/`command_started` after the harness began; ASK is
an effective auto-pass, adapters record approval `effective: False`); (2) no
mandatory server floor (unspec'd session → ALLOW); (3) cost policy fails open
silently when usage is unavailable; (4) generated ASK approvals aren't
human-verified. **The flag stays OFF. Enablement gate: clear AGT-19 → fresh-Sol
re-review → operator flips the flag.** Nothing here enabled it.
