# RUNDOC — KAN-2 · Repo-scoped agent workspaces

Through the [`TODO_PROCESS.md`](../../todos/TODO_PROCESS.md) loop. Objective:
registered folders are ALL an agent session works in ("never again: the home
directory tree is too large / traversal timing out"), and adding a repo is an
easy registration agents instantly know.

## 1. Objective & definition of done

- A cockpit agent session started with a `repo_id` is scoped to that repo's
  folder: secret-path denylist enforced, workspace bounds explicit, no
  home-tree traversal.
- `bball_homography_pipeline` is registered (disabled manifest — autonomy
  stays off) so sessions can select it; the `.env` path line is the
  operator's (never edited by agents).
- Registration remains one call (`POST /api/repos/register` dry-run→apply),
  and the catalog feeds the chat picker — already true, verified below.

## 2. Research (verified seam map, 2026-07-23 read-only sweep)

- **Registration already exists and is governed**: `POST /api/repos/register`
  → `run_repo_register` (src/command_center/cli/repo_registry.py L267-310):
  dry-run/apply, writes ONLY autonomy.yaml, env-ref paths (never absolute),
  new repos start DISABLED (`github_app_pending`,
  `blockers=[repo_autonomy_not_yet_verified]`); enabling autonomy is a
  separate human `cc repo-enable-autonomy` gate. Board must pre-exist.
- **Session cwd resolution**: adapters → `_resolve_repo_path(repo_id)` →
  `context_resolver.resolve_context_path` → manifest `local_path_ref`
  (`self` | `env:NAME`). Claude lane: `claude` spawned `cwd=repo_path` +
  `--add-dir repo_path`, read-only tools (Read/Glob/Grep), plan mode, no
  MCP. Codex lane: `Sandbox.read_only`, `ApprovalMode.deny_all`,
  `cwd=repo_path`.
- **THE GAPS (root causes of the pain):**
  1. `secret_paths` denylist + `home_workspace.is_readable` are enforced
     only in attachments + the OpenRouter adapter — **NOT wired into
     claude_code_local or codex_agent** (neither imports them).
  2. Nothing tells or prevents the native runtimes from reading OUTSIDE the
     repo root by absolute path — cwd + `--add-dir` scope convenience, not
     access; the home-traversal pain comes from sessions operating at
     `home_workspace` scope or wandering out of the repo.
  3. `bball_homography_pipeline` is unregistered, so those todos can't even
     select a scoped workspace.
- Full map with line numbers preserved in this run-doc's source
  investigation (agent sweep 2026-07-23).

## 3. KPIs & baseline

- Baseline: native sessions have no path denylist; no workspace-bounds
  contract; 2 registered repos.
- Target: both native adapters enforce/declare scope (tests prove:
  secret-path probe refused; out-of-root probe refused or contractually
  bounded); bball registered (disabled) and selectable; zero regressions in
  the agent-session suites.

## 4. Plan (bounded)

**Step A — registration (operational, this session):** dry-run
`run_repo_register` for `bball_homography_pipeline`
(board: `personal_todos` — the register flow's own inline-UI default; a
dedicated board can supersede later), evidence recorded, then apply.
OPERATOR-ONLY tail: add `BBALL_HOMOGRAPHY_PIPELINE_LOCAL_PATH=<path>` to
`.env` (agents never touch .env); GitHub App install only if/when autonomy
is ever wanted there.

**Step B — adapter scoping (Codex packet):**
1. Wire `secret_paths.is_secret_path` into BOTH native adapters as a
   pre-spawn + per-turn contract: claude_code_local adds permission deny
   rules for secret segments/suffixes via the CLI's `--settings`/
   `--disallowedTools` seams where supported — if the installed CLI version
   (resolve at wiring time, never from memory) lacks a read-deny seam,
   fall back to an explicit workspace-bounds system prompt + document the
   limitation honestly in the run-doc.
2. Workspace-bounds contract in the session context for both lanes: the
   resolved repo root is THE workspace; instruct no traversal outside it
   (prompt-level, cheap, kills the aimless home-tree walks).
3. `home_workspace` sessions: keep (it's deliberately whole-home read-only)
   but inject the same secret-path denylist contract and a "targeted reads,
   no full-tree traversal" instruction.
4. Tests: secret-path probe (e.g. `.ssh/`) refused/absent from args;
   bounds text present in session context; existing agent-session suites
   green.

Allowed files (Step B): `src/command_center/agent_sessions/adapters/
claude_code_local.py`, `adapters/codex_agent.py`, `context_resolver.py`
(only if a shared helper belongs there), matching tests. Forbidden: .env,
configs (Step A handles autonomy.yaml via the governed CLI), worker
lifecycle scripts.

## 5. Decisions (documented defaults per operator's standing "continue")

1. bball board = `personal_todos` for now (flow default; revisit with a
   dedicated board later).
2. Registration applied with autonomy DISABLED (flow's only mode) — read
   scoping only; `.env` line + any GitHub App install = operator.
3. Enforcement depth packet 1 = denylist wiring + bounds contract
   (settings-level read-deny only if the installed CLI exposes it — no
   invented flags).

## 6. Model allocation (resolved live 2026-07-23)

- Step B implementation: `deep_code` → Codex gpt-5.6-sol, effort xhigh
  (security-adjacent adapter seams), isolated worktree off origin/main,
  detached launch (no wrapper timeout), fail-closed rules as in KAN-3/25.
- Independent review: Fable (non-author) with a security lens (the denylist
  is a wall — check bypasses).

## 7. Links

- Master item: [`docs/todos/GRAND_TODO_LIST.md`](../../todos/GRAND_TODO_LIST.md) → KAN-2
- Related: KAN-13 (chat repo dropdown UX), memory `secret_paths` module.

## 8. Execution log

- 2026-07-23 — Run-doc created from the seam-map sweep; Step A dry-run next.
