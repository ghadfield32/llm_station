# AGT-14 p2 — finding-4 fix brief (flag-off identity)

The fresh-Sol deep review (DO-NOT-ENABLE) found finding 4: flag-off is NOT
byte-for-byte identical because the worker's board-policy endpoint is always
registered and always evaluates, regardless of `AGENT_SESSION_POLICIES_ENABLED`.
Fix ONLY that, minimally. Branch: `feat/agt-packet2-followons` (this worktree).
Profile deep_code, effort high. Sol writes; Fable reviews.

## Fix

1. In `src/command_center/agent_sessions/worker_app.py`, the
   `POST /api/agent-sessions/{session_id}/board-change-policy` endpoint
   (`evaluate_board_change_policy`) must be **inert when the flag is off**:
   when `os.environ.get("AGENT_SESSION_POLICIES_ENABLED", "") != "1"`, return
   HTTP 503 with a clear detail ("agent-session policy enforcement disabled;
   set AGENT_SESSION_POLICIES_ENABLED=1") and evaluate NOTHING (no policy
   load, no event). This makes the worker board-policy surface flag-off
   identical to pre-AGT-14-p2 (the endpoint refuses instead of evaluating).
2. Add a test to `tests/test_session_policy_board_gate.py`:
   `test_worker_board_policy_endpoint_is_inert_when_flag_off` — hit the worker
   endpoint directly with the flag off, assert 503 and that NO policy event is
   appended to the session.
3. Leave `BoardFormatPlanIn.session_id` as an optional field (it is inert
   flag-off — the cockpit gate only reads it when the flag is on); add a
   one-line comment noting it is accepted-but-ignored when the flag is off.

## Constraints

- Touch ONLY worker_app.py (+ the one test, + the one comment). Do NOT change
  the engine, builtins, board_change.py, or the cockpit gate logic. Do NOT
  attempt to fix findings 1/2/3/5 — those are tracked separately as
  enablement blockers. No new deps.

## Validate (record exit codes)

```
uv run python -m command_center.cli.validate_config
uv run pytest tests/test_session_policy_board_gate.py tests/test_session_policy.py -q
uv run ruff check src/command_center/agent_sessions/worker_app.py
```

If the sandbox blocks the commit, report implemented-uncommitted (I commit
host-side). Done = endpoint inert flag-off, test proves it, commands exit 0.
