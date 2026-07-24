# AGT-16 packet 1 — implementation brief (Sol write-mode)

Authoritative context: `RUNDOC.md` in this directory (§1 DoD, §4 plan, §5
LOCKED Stage-4 decisions), plus repo `CLAUDE.md` engineering standards.
Branch: `feat/agt16-session-spec` (this isolated worktree). Never push;
commit locally with exact-path staging only.

## Deliverables

1. **Schema** — `src/command_center/schemas/agent_session_spec.py`:
   - Subclass the existing `Strict` base (`schemas/base.py`) — `extra="forbid"`.
   - `AgentSessionSpec`: `name` (kebab/snake slug, validated), `instructions`
     (inline string) XOR `instructions_file` (path relative to the spec file —
     exactly one of the two, validated), `harness` (StrEnum whose values are
     exactly the registry harness ids: `fake`, `codex_agent`,
     `claude_code_local`, `claude_agent`, `openrouter_agent`),
     `capability_profile` (StrEnum: `strategic_steward`, `generalist`,
     `deep_code`, `throughput`), optional `effort` (StrEnum: `low`, `medium`,
     `high`, `xhigh`; default None = session default), `mode` (must be one of
     the registry's supported_modes strings for that harness — cross-checked
     at bridge time, not hardcoded in the schema), `policy_refs: list[str]`
     (default empty — PLACEHOLDER for AGT-14; no resolution logic yet).
   - **NO auth field, NO model-slug field** (locked decisions: auth is
     registry-owned; profiles only, resolution always live). Do not add either.
2. **Example specs** — `configs/agent_sessions/` with 2+ validated examples
   (e.g. `codex-analysis.yaml` generalist/codex_agent/analysis,
   `claude-local-analysis.yaml` generalist/claude_code_local/analysis).
   Comment headers explaining fields, matching the style of other configs/.
3. **Validation wiring** — extend `command_center.cli.validate_config` so
   `make validate` loads + validates every `configs/agent_sessions/*.yaml`
   (fail loudly on any invalid file; a missing/empty directory is valid).
4. **Registry bridge** — in `src/command_center/agent_sessions/` (new module,
   e.g. `spec_bridge.py`): `resolve_spec(spec, registry) -> HarnessDescriptor`
   that (a) errors loudly if `spec.harness` is not registered, (b) errors
   loudly if `spec.mode` is not in the descriptor's `supported_modes`,
   (c) returns the descriptor so callers use its existing `factory` — the
   bridge never constructs SDKs itself and never imports vendor SDKs.
5. **Flagged consumer (KAN-15 seam)** — in the worker/service layer
   (`agent_sessions/service.py` / `worker_app.py`, NOT the UI): when env
   `AGENT_SESSION_SPEC_ENABLED=1` (default OFF) a session-start request may
   name a spec (`spec_name`); the boot path loads the validated spec from
   `configs/agent_sessions/`, derives harness/mode/instructions from it via
   the bridge, and records the spec name in the session's stored metadata.
   Flag off (default) → behavior byte-for-byte unchanged. No import-time
   directory scans or lookup dicts (tests monkeypatch — resolve lazily per
   call).
6. **Tests** — new test module(s) under `tests/`:
   - YAML → model round-trip; unknown-key rejection (`extra="forbid"`);
     instructions XOR instructions_file enforcement.
   - **Drift guard**: harness enum values == `default_registry(...)`
     descriptor ids, both directions (this is the AGT-15-style
     declared-vs-observed cell — a new adapter without an enum value, or
     vice versa, must fail).
   - Bridge: resolves every registered id; unknown harness and unsupported
     mode raise with the offending value in the message.
   - Consumer: flag off → spec_name ignored/absent path identical to today;
     flag on → spec-derived boot recorded (use FakeHarness; monkeypatch env).
   - Example configs in `configs/agent_sessions/` all validate.

## Constraints (hard)

- No new dependencies. No edits to `.env*`, `docs/MASTER.md`,
  `services/agent_kanban_ui/` (UI is KAN-26's packet), Ledger schema files,
  or any file outside the deliverables above + this run-doc directory.
- No swallowed exceptions, no silent fallbacks, no fake/default data.
- Match surrounding code style/comment density (see registry.py's idiom).
- One editing agent in this worktree: you.

## Validation to run and record (commands + exit codes in your final output)

```
uv sync --extra dev --extra fastapi          # once, in this worktree
uv run python -m command_center.cli.validate_config
uv run python -m command_center.cli.check_cross_refs
uv run pytest tests/<your new/changed test files> -q    # ONE pytest process at a time
uv run ruff check <changed files>
```

Run everything FROM this worktree so imports resolve to this tree's src
(fresh `uv sync` here, never the main checkout's venv).

## Done =

All deliverables present, all commands above exit 0, committed locally on
`feat/agt16-session-spec` (exact paths, no `git add -A`), final message
lists: files changed, commands + exit codes, any deviations from this brief
(deviations must be flagged, never silent).
