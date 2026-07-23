# RUNDOC — KAN-25 · Restore main CI to green (12 pre-existing lint-test failures)

Through the [`TODO_PROCESS.md`](../../todos/TODO_PROCESS.md) loop. A red main
gate makes every merge untrustworthy — this is the platform P1.

## 1. Objective & definition of done

The `contracts` workflow's `lint-test` job passes on a PR branched from
current main, fixing all 12 failures at root cause with **zero behavior
regressions** (no prior-passing test breaks, no production-path behavior
changes beyond correctness fixes).

## 2. Research (verified from CI logs, 2026-07-23; main red since 07-17)

Evidence: run 30032453677 (PR #74) and the same-day main run — identical
failure sets (minus the domain-pin fix #74 carried). Four families:

1. **`test_agent_kanban_ui_capture_convert.py` ×5** — capture-convert's
   "private history" internal sub-request 500s: the handler resolves
   **container-default paths** on the runner (`FileNotFoundError:
   /app/generated/.locks`, `PermissionError: /app`) — some component in that
   path ignores the test's monkeypatched dirs and falls back to
   `KANBAN_BOARD_STORE`-style defaults. NOTE: on Windows dev machines this
   silently "passes" by creating `C:\app` — the CI Linux runner exposes the
   truth. Fix at root cause: the component must accept/inherit the injected
   paths (module-attr read at call time, same pattern as
   `_grand_todo_source`), not a default snapshot. Never fix by chmod/mkdir.
2. **`test_agent_kanban_ui_usage.py::test_portfolio_combines_local_openrouter_and_local_frontier_usage`**
   — `KeyError: 'glm-5.2'`: fixture/config drift (frontier lane model set
   changed vs the test's expected portfolio keys). Decide the intended
   current model set from `configs/` + usage code; align the test (or the
   portfolio builder if it wrongly hardcodes).
3. **`test_agent_pickers.py::test_claude_local_effort_reaches_build_args_and_event`**
   — `TypeError: _build_args() takes 4 positional arguments but 5 were
   given`: the stdin chat fix (prompt moved out of argv) changed the
   signature; this test still passes the prompt positionally. Align the test
   with the stdin contract (and assert the prompt is ABSENT from argv, per
   the fix's intent).
4. **`test_agent_session_service.py` ×5** — `KeyError: 'approval_id'` (×2)
   and event-order assertion drift (`['user_message'...]` vs
   `['assistant_message'...]`) (×3). Behavior/test drift in the
   agent-session service (Ledger-backed durable state). **Decision rule:**
   inspect `git log` for the service module vs the test file; the later,
   intentional change wins; align the other side; document which way and why
   in the execution log. Do NOT blind-update assertions.

## 3. KPIs & baseline

- Baseline: lint-test red, 12 failures (4 families) — every run since 07-17.
- Target: lint-test green on this packet's PR; full local
  `python -m pytest tests/ -q` regression delta limited to the 12 (i.e. the
  same tests that failed before now pass; nothing else changes state).

## 4. Plan (bounded)

One family per commit, in order 3 → 2 → 1 → 4 (cheapest to hardest):
each commit = root-cause fix + local proof (run the family's tests).
Allowed files: the four test files, plus the specific product modules the
root causes live in (capture-convert/private-history path resolution; usage
portfolio builder if wrong; claude_code_local harness only if its signature
is inconsistent — do NOT touch the stdin behavior itself). Forbidden:
configs/, docs/todos/, workflow YAML (GitHub App has no workflows:write),
anything grand-todo.

Verification: `PYTHONPATH=<worktree>/src` + main venv python —
`python -m pytest tests/test_agent_kanban_ui_capture_convert.py
tests/test_agent_kanban_ui_usage.py tests/test_agent_pickers.py
tests/test_agent_session_service.py -q` green, then the broader affected
suites (`tests/test_agent_kanban_ui.py tests/test_domain_surfaces.py`)
green, then ruff on changed files.

## 5. Open questions

None blocking — the §2 decision rules cover the judgment calls; record each
in the execution log.

## 6. Model allocation (resolved live 2026-07-23)

- Implementation: `deep_code` → Codex **gpt-5.6-sol** effort **xhigh**
  (hard debugging + durable-state seams per the allocation contract),
  `codex exec --sandbox workspace-write --full-auto`, isolated worktree
  `feat/kan-25-ci-green` off origin/main. Detached launch, no wrapper
  timeout (KAN-24 lesson); Codex sandbox may block pytest — if so, fail
  closed and the reviewer verifies on host (KAN-3 precedent).
- Independent review: Fable (non-author), full-diff, with special attention
  to family 4's behavior decision.

## 7. Links

- Master item: [`docs/todos/GRAND_TODO_LIST.md`](../../todos/GRAND_TODO_LIST.md) → KAN-25
- Board card: `grand_todo` / `grand-todo-kan-25`
- CI evidence: actions run 30032453677 + same-day main run (see item notes)

## 8. Execution log

- 2026-07-23 — Run-doc created; packet launching.
- 2026-07-23 — Family 3: aligned the stale `_build_args` test with commit
  `13bc15b`'s stdin contract. The prompt is no longer passed positionally and
  the test now explicitly asserts it is absent from argv; effort propagation
  through argv and the session event remains covered.
- 2026-07-23 — Family 2 decision: the configs are authoritative and remain
  internally consistent — `frontier-router-providers.yaml` still configures
  `glm-5.2`, while `local-frontier-providers.yaml` configures
  `glm-5.2-colibri`. The portfolio intentionally creates frontier rows from
  observed ledger evidence and defaults to a rolling seven-day window. The
  test's fixed July 10/11 ledger rows had simply aged out, so the fixture query
  now requests `window=all`; no config or product behavior changed.
- 2026-07-23 — Family 1 root cause: the durable
  `_todo_assignment_guard()` added by `dca1d34` reads `KANBAN_EVENT_LOG` at
  request time, but the capture-convert loader injected only `CONFIGS_DIR`.
  That left the real lock pointed at the import-time container default
  `/app/generated/.locks`. The hermetic loader now injects
  `KANBAN_EVENT_LOG` and `BOARD_STORE_DIR` under `tmp_path`, exercising the
  actual cross-process lock without creating or chmodding `/app`. A direct
  TestClient check confirmed the lock path follows the injected module
  attribute at call time. The pre-existing `C:\app` tree was inspected before
  that check and predates this run (created 2026-07-10; last written
  2026-07-15), so it was not modified.
- 2026-07-23 — Family 4 decision/evidence: service and test were introduced
  together by `23b28a3` on July 13; later commit `dca1d34` on July 17 changed
  only `agent_sessions/service.py` to durably emit `user_message`, explicitly
  fixing transcript replay that otherwise omitted the human half. The later
  intentional service behavior wins. Updated the stale test event order,
  approval-event position, restart history, and continued sequence (`5`, not
  `4`); production code remains unchanged.
- 2026-07-23 — Verification: direct contract checks passed for all four
  families (stdin/effort, all-window portfolio, injected capture-convert lock,
  and durable event/approval/restart sequencing). Ruff passed all four changed
  tests; AST parsing and `git diff --check` also passed. There are no changed
  product files, so the requested product-file Ruff set is empty.
- 2026-07-23 — Pytest constraint: both the exact four-file packet suite and
  the `test_agent_kanban_ui.py` + `test_domain_surfaces.py` regression guard
  were attempted with the main-checkout venv and this worktree's `PYTHONPATH`.
  The managed Windows sandbox denied pytest's temp root at fixture setup
  (`PermissionError: C:\Users\ghadf\AppData\Local\Temp\pytest-of-ghadf`);
  retrying with an in-worktree `--basetemp` was also denied. No test body ran.
- 2026-07-23 — Commit constraint: the linked worktree's Git administrative
  directory is outside the writable roots. `git add`/`git commit` cannot create
  `C:\Users\ghadf\vscode_projects\docker_projects\llm_station\.git\worktrees\kan25-ci-green\index.lock`
  (`Permission denied`), so the required per-family commits could not be
  created inside this sandbox.
- 2026-07-23 — Sandbox artifact note: the denied pytest runs created
  `.pytest-tmp/` and two `pytest-cache-files-*` directories in this worktree
  with ACLs that prevent traversal/removal. Exact-target cleanup via native
  PowerShell was policy-blocked and `git clean` could not enter them; no other
  untracked path was targeted.
