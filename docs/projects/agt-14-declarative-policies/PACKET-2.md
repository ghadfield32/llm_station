# AGT-14 packet 2 — board-change proposal policy gate (Sol write-mode)

Context: AGT-14 packet 1 (on main) built the declarative session-policy stack
(`schemas/session_policy.py`, `agent_sessions/policy_engine.py`,
`policy_builtins.py`), the flag-off `AGENT_SESSION_POLICIES_ENABLED`
enforcement hook in `agent_sessions/service.py` for the agent tool-call path,
and machine-proven floors (policies only tighten). The chat→Kanban write wall
lives in `src/command_center/kanban_sync/board_change.py`
(propose→preview→**human-allowlist** confirm→apply→receipt→rollback) and is
surfaced in `services/agent_kanban_ui/app.py` (`make_proposal`,
`BoardChangePreviewIn`, `mint_board_change_approval`,
`KANBAN_UI_BOARD_CHANGE_APPLY`). Read all of it first. Branch:
`feat/agt-packet2-followons` (this worktree). Profile: **deep_code**, effort
**xhigh**. You are Sol; a FRESH Sol session + Fable will review you.

## The safety invariant (read twice)

The existing board-change wall is an ALLOWLIST human gate — already STRICTER
than any policy verdict. Your job is to add a policy evaluation **BEFORE** a
board-change proposal is created, so a policy can DENY (block the proposal
from ever existing) or ASK. **You may only TIGHTEN.** You must NOT:
- weaken, bypass, or alter the human-allowlist confirm/apply wall;
- let a policy verdict turn into an approval (ASK is subsumed by the human
  wall — it never auto-approves);
- change `make_proposal` / `mint_board_change_approval` /
  `BoardChangeReceipt` integrity semantics;
- make enforcement default-on.
A test must prove the human wall is unchanged whether the policy flag is on or
off, and that no policy path can produce an apply without the human token.

## Deliverables

1. **A board-change ToolAction shape** — extend the policy engine's action
   model (or add a sibling) so a board-change proposal can be evaluated:
   e.g. `is_os_tool=False`, a `tool_name` like `board_change:<kind>`, and the
   proposing `author_harness` / session id. Reuse `resolve()` — do NOT fork
   the engine.
2. **The gate** — at the point in `app.py` where an AGENT-authored
   board-change proposal is created (the `make_proposal` entry from a chat/
   agent session, NOT a human action), when
   `AGENT_SESSION_POLICIES_ENABLED=1`: resolve the session's policy sets
   against the board-change action; DENY → block proposal creation, record a
   durable `policy_denied` event/response (reuse packet-1's shape), return a
   typed 4xx; ASK → record and route to the EXISTING human wall (do not create
   a second approval surface); ALLOW → proceed to the normal
   propose→preview→human-confirm flow untouched. Flag off → the proposal path
   is byte-for-byte unchanged.
3. **A board-scoped builtin (optional, only if clean)** — if a natural builtin
   fits (e.g. deny board-change proposals of certain kinds), add it to
   `policy_builtins.py` behind the closed handler enum with a validated param
   model. If it doesn't fit cleanly in scope, SKIP it and say so — do not
   force it.
4. **Tests** — `tests/test_session_policy_board_gate.py` (new):
   - flag off → an agent board-change proposal follows the identical
     pre-AGT-14 path (assert no policy events, wall intact).
   - flag on + a DENY policy → proposal creation blocked, `policy_denied`
     recorded, NO proposal/receipt minted.
   - flag on + an ASK policy → proposal still requires the human-allowlist
     token to apply (ASK never auto-approves); the human wall is unchanged.
   - **floor test**: no policy configuration produces a board apply without
     the human token; a permissive policy cannot un-gate the human wall.

## Constraints (hard)

- No new dependencies. No edits to `.env*`, `docs/MASTER.md`, Ledger schema,
  the human-allowlist semantics, or `board_change.py`'s integrity/hash/receipt
  code. Reuse packet-1 engine + event shapes. No swallowed exceptions, no
  silent fallbacks. One editing agent: you.

## Validation to run and record (commands + exit codes)

```
uv sync --extra dev                                   # sandbox may block → PYTHONPATH fallback, say so
uv run python -m command_center.cli.validate_config
uv run pytest tests/test_session_policy.py tests/test_session_policy_floor_integrity.py tests/test_session_policy_board_gate.py -q
uv run pytest tests/test_agent_kanban_ui.py -q        # board-change endpoints still pass
uv run ruff check <changed files>
```

If the sandbox blocks the git commit, report "implemented, uncommitted" — I
commit host-side. Done = all deliverables, all commands exit 0, the safety
invariant proven by tests, deviations flagged. The flag stays OFF — enabling
it on the live worker is an OPERATOR action gated behind a fresh-Sol deep
review (separate step), never done here.
