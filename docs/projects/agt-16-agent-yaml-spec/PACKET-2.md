# AGT-16 packet 2 — spec-listing API + runtime-agnostic chrome read (Sol write-mode)

Context: AGT-16 packet 1 (on main) built the typed `AgentSessionSpec`
(`schemas/agent_session_spec.py`), `spec_bridge.load_spec`, the
`configs/agent_sessions/` validated set, and the flag-off
`AGENT_SESSION_SPEC_ENABLED` boot consumer. KAN-26 (on main, #81) built the
runtime-agnostic chat chrome in `services/agent_kanban_ui/web/src/App.tsx`
under the `services/agent_kanban_ui/DESIGN.md` contract. Read all of that
first. Branch: `feat/agt16-p2` (this worktree, off current main). Never push;
commit local, exact paths. Profile: **generalist/throughput**, effort
**high**. You are Sol; Fable reviews you.

## Objective

Make the validated agent-session specs VISIBLE to the runtime-agnostic chat
chrome via a typed read-only API, and consume it in the chrome so the runtime
choice + capability profile render from the spec (not hardcoded). This is the
read path only — no session mutation. It also defines the emission interface
AGT-10's allocator (future) will target.

## Deliverables

1. **Read-only API** — in `services/agent_kanban_ui/app.py`, add
   `GET /api/agent-session-specs` that lists the validated specs from
   `configs/agent_sessions/` via `spec_bridge` (load + validate each; on a
   bad file return a typed error entry, never a 500). Each item:
   `{name, harness, capability_profile, effort, mode, instructions_source:
   "inline"|"file", policy_refs}`. NEVER expose instructions bodies,
   credentials, or any secret. Follow the existing read-endpoint style near
   `/api/chat/runtime` (app.py ~9730) and `agent_harnesses()` (~10314).
   Reuse the existing `CONFIGS_DIR` resolution the other endpoints use.
2. **Chrome consumption** — in `App.tsx`, fetch that endpoint and render the
   specs as a runtime-agnostic selectable list (matching the DESIGN.md chat
   contract: runtime differs only by a small badge, compact viewport-fitting
   select, no hardcoded colors). Selecting a spec sets the chat's harness +
   profile display. Do NOT wire it to start a session yet (that's gated by
   `AGENT_SESSION_SPEC_ENABLED` on the worker, out of scope) — this is a
   display/selection read path. If specs are empty/endpoint 404, degrade
   gracefully (no error toast spam).
3. **AGT-10 emission interface (doc + type only)** — add a short docstring/
   TypeScript type comment naming the shape AGT-10's allocator will emit into
   this same spec list (so AGT-10 has a target). Do NOT build AGT-10 — it does
   not exist yet; just define the seam.
4. **Tests** —
   - Python: extend `tests/test_agent_kanban_ui*.py` (or a new focused test)
     asserting `/api/agent-session-specs` returns the two seed specs with the
     documented fields and NO instructions body / secret; a malformed spec
     file yields a typed error entry not a 500.
   - Front-end: if there's an existing `web/tests/*.mjs` pattern (e.g.
     chatPresentation.test.mjs), add a small unit test for the spec-list
     rendering/parse helper. Keep it consistent with the existing test style.

## Constraints (hard)

- No new dependencies. No edits to `.env*`, `docs/MASTER.md`, Ledger,
  `configs/` schemas. Do NOT add a write/mutation path. Do NOT expose
  instructions bodies or secrets. Conform to `services/agent_kanban_ui/DESIGN.md`
  (no hardcoded colors; 390px fit; runtime-agnostic chrome). One editing
  agent: you.

## Validation to run and record (commands + exit codes)

```
uv sync --extra dev                                   # sandbox may block → PYTHONPATH fallback, say so
uv run python -m command_center.cli.validate_config
uv run pytest tests/test_agent_kanban_ui.py -q        # + any test file you touch/add (ONE process)
cd services/agent_kanban_ui/web && npm ci && npm run build   # vite build MUST pass (App.tsx compiles)
# (if you added a web test) node --test web/tests/<your>.test.mjs  OR the repo's web test command
uv run ruff check <changed python files>
```

If the sandbox blocks the git commit, report "implemented, uncommitted" — I
commit host-side. Report any DESIGN.md tension you hit. Done = all
deliverables, all commands exit 0 (vite build included), deviations flagged.
