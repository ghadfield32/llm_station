# Omnigent (omnigent-ai/omnigent) — borrow_pattern_only (2026-07-23)

Verdict for the operator question *"continue with our own chat, or include
Omnigent as a kanban link that can also adjust the kanban?"*: **neither
adoption path. Keep our chat; do not wire Omnigent as a write-capable link.
Borrow three patterns** (tracked as AGT-14/AGT-15/AGT-16) and keep the runtime
on the research catalog at watch cadence.

This closes the pre-decided verdict in
[docs/cockpit-mission-prompt.md](../cockpit-mission-prompt.md) (follow-up
mission B: `omnigent-ai/omnigent = borrow_pattern_only`), which had never been
executed — no pattern doc existed before this one.

## Live provenance (verified, not README-trusted)

Checked 2026-07-23 via `gh api repos/omnigent-ai/omnigent` (and
`/releases/latest`, `/contents/docs`):

- 7,679★, Apache-2.0, not archived, default branch `main`, pushed
  2026-07-23T21:47Z (same day as this review).
- Latest release **v0.6.0**, published 2026-07-21; README self-declares
  **alpha**; 686 open issues+PRs combined.
- Primary sources read raw the same day, pinned at `main` commit
  **c8828ed** (2026-07-23): `docs/POLICIES.md`, `docs/AGENT_YAML_SPEC.md`,
  `docs/harness-bench-design.md`, plus the README.

## Why we do not adopt the runtime

- **Concern mismatch.** Omnigent is a session/harness orchestration layer.
  `llm_station` is a work-tracking + governance control plane. Omnigent has no
  boards-as-governance, no durable Ledger, no human-owned kanban approval
  workflow (its ASK policies do pause per-session for user approval — a
  different, ephemeral thing), no grand-todo seam; its `projects` entity
  landed at Stage 1 CRUD two days before this review (#2765). Swapping chat
  runtimes gains none of that and orphans all of it.
- **We already built the overlapping half:** four session adapters
  (`src/command_center/agent_sessions/adapters/` — claude_agent,
  claude_code_local, codex_agent, openrouter_agent), durable session ledger +
  fingerprint/handoff/mutation-proof, GatewayCore+LiteLLM model plane, the
  usage/limits layer, PWA-over-Tailscale + 5 messaging channels.
- **Governance regression risk.** Our walls (Ledger, Judge Gate, human
  approval/merge, read-only cockpit sessions) are stricter than Omnigent's
  policy builtins. Replacing the runtime would re-litigate every wall.
- **Alpha churn.** 686 open issues+PRs and a fast-moving harness registry are
  exactly the wrong foundation to pin a control-plane seam to.
- **Telemetry** is on by default (opt-out), which fails our local-first
  posture (KAN-17) as a default.

## Why not "a link that can also adjust the kanban"

Adjusting the kanban from an external runtime requires a **write-capable**
kanban API/MCP surface exposed to that runtime. Today none is: `.mcp.json`
registers zero servers, and the `src/command_center/mcp/` package's stated
posture is typed, allowlisted, *"never exposes a generic action/command
surface."* (Precision, per review: `life_center_actions.py` in that package
does contain an unregistered internal action server whose catalog-projection
refresh runs `life_center_sync` and thus moves kanban cards — so the accurate
wall is "no write-capable kanban MCP is registered or exposed to external
runtimes," not "everything under mcp/ is read-only.") Wiring a third-party
write path would punch through the chat→Kanban governance wall
(proposal/preview/receipt, human-only resolutions). If an external write
surface is ever built, our own governed agents are first in line — not an
external meta-harness.

## Naming collision — do not wire `OMNIGENT_CHAT_URL` to this repo

`OMNIGENT_CHAT_URL` / `OMNIAGENT_CHAT_URL` in this repo already mean
**OmniAgent (Om-AI-Lab)** — the long-video/audio evidence specialist
(README L111, `docs/MASTER.md`, COCKPIT quickstart/mobile docs,
`services/agent_kanban_ui/web/src/App.tsx` chat specialist card). That is a
different project from omnigent-ai/omnigent. Rule: never point those env vars
at omnigent-ai/omnigent. Follow-up: disambiguate the naming the next time
those files are touched (deliberately, in one pass — a MASTER.md edit forces
a `capabilities.yaml` digest re-record, so it should not ride along here).

## Pattern 1 — three-level declarative policy stack (→ AGT-14)

Source: `docs/POLICIES.md` @ main, 2026-07-23.

- Policies are declarative gates evaluated at enforcement points, returning
  **ALLOW / DENY / ASK** (ASK pauses for human approval; refusal becomes
  DENY). Multiple policies compose in declaration order; any DENY
  short-circuits.
- Three levels with distinct personas, **stricter-first**: session (end
  user, evaluated first, can short-circuit), agent spec (developer), server
  (admin, evaluated last). Registered via dotted `handler` paths +
  `factory_params`.
- Builtins worth copying: `ask_on_os_tools` (ask before shell/file writes),
  `max_tool_calls_per_session` (hard call cap),
  `cost_budget(max_cost_usd, ask_thresholds_usd=[...])` (hard cap + soft
  warning thresholds), scoped `github_policy(write_repos, write_branches)`.
- **Our gap:** our walls are code-shaped (scattered through worker/adapters/
  UI guards). We have no single declarative, inspectable, per-level policy
  document that says what an agent session may do — which is exactly what
  KAN-17 ("top-level security… so it all feels secure") and the usage layer's
  budget concept need. The ASK verdict maps 1:1 onto our approval-wall idiom.
- **Keep ours where stricter:** human-only resolutions, read-only cockpit,
  destructive-action double-agreement are non-negotiable floors a policy file
  can tighten but never loosen.

## Pattern 2 — harness capability bench: declared vs observed (→ AGT-15)

Source: `docs/harness-bench-design.md` @ c8828ed, 2026-07-23 (status:
shipped — 3 transport drivers, 6 P0 probes, **6** report-only P1 probes per
its own dimension catalog and Current-state list; the doc's status blurb
still says five — an internal staleness their own DRIFT idea would catch).

- Their motivating observation is ours too: capability knowledge drifts
  across **three disagreeing sources of truth** (a hand-maintained matrix,
  in-code capability flags, scattered per-harness constants).
- The bench turns the matrix into an **executable conformance suite**: each
  cell is *earned* by running a live probe and inspecting the event stream,
  then **reconciled against declared flags — declared ✓ but observed ✗ is a
  `DRIFT` failure**, not a production surprise.
- Per-harness facts live on a self-declared **profile object**, never in
  probe code; probes are harness-agnostic; offline/live drivers let CI run
  the cheap subset.
- **Our gap:** the 4 agent-session adapters' capabilities (streaming, resume,
  write-mode, attachment support, model switching) are hand-known; the
  14-case cockpit acceptance is deep per-adapter e2e, not a
  declared-vs-observed breadth matrix. This is AGT-3's harness-score idea
  applied to **runtimes instead of repos**, and it becomes a real KPI for
  AGT-12 (drift count, cells earned vs declared).

## Pattern 3 — agent-as-YAML with a `harness:` enum (→ AGT-16)

Source: `docs/AGENT_YAML_SPEC.md` @ c8828ed, 2026-07-23.

- One YAML file defines an agent: `name`, `prompt` (or `instructions:` file
  path), `executor.harness` (enum: claude-sdk, codex, cursor, …),
  `executor.model`, `executor.auth`, `tools` (function / mcp / sub-agent /
  `inherit`), `policies` in the same file, `os_env` opt-in for OS tools.
- Precision: in *their* spec the whole `executor` block (harness + model +
  auth) is runtime-entangled — cursor/kiro carry harness-specific model and
  auth rules. The **adaptation we intend** is stronger than the source: our
  four adapters already own their auth lanes, so *our* spec can collapse the
  runtime choice to one swappable enum field with everything else
  runtime-agnostic. Sub-agents and cross-vendor reviewers declared in the
  same file is theirs verbatim.
- **Our gap:** KAN-26's DESIGN.md contract demands runtime-agnostic chat
  chrome ("Claude/Codex/GatewayCore/future Copilot differ only by a small
  badge"); KAN-15 wants auto-engage on select; AGT-10 wants an allocator that
  chooses the combination. All three need a typed, declarative session-spec
  seam (`harness` + model + limits + policies) instead of the code-shaped
  adapter registry. A Pydantic `extra="forbid"` spec of that shape gives the
  allocator something to emit and the UI something to render.
- **Not borrowed:** their auth plumbing, Databricks profiles, and harness
  breadth (Cursor/Kiro/Antigravity/…) — our adapter set is deliberate.

## Confirmation, not news

Polly (their example orchestrator) routes each diff to a reviewer from a
different vendor than the author — independently identical to our CLAUDE.md
reviewer-independence rule. Treated as convergent validation of the standing
policy, nothing to change.

## Re-evaluate the runtime itself when

- It reaches a stable 1.0 with a settled harness registry AND
- its projects/board entities mature into something our kanban could project
  onto AND
- we have a measured gap our stack can't close (most plausible: managed cloud
  sandboxes per session — the one capability we genuinely lack — or
  phone-native co-driving beyond the PWA).

Until then: catalog row `omnigent-meta-harness` (verdict `build` for the
three extracted patterns; runtime stays watch-cadence), reviewed with the
model-registry cadence.

## Provenance of this review

- `gh api repos/omnigent-ai/omnigent` (+ `/releases/latest`,
  `/contents/docs`, raw fetches of the three source docs), 2026-07-23, all
  exit 0.
- Repo-side evidence: `.mcp.json` (zero registered servers) +
  `src/command_center/mcp/` (posture and the life_center_actions caveat),
  `src/command_center/agent_sessions/` (adapters + ledger),
  `docs/todos/GRAND_TODO_LIST.md` (KAN-15/17/26, AGT-3/10/12),
  README L111 + `App.tsx` (OMNIGENT_CHAT_URL collision).
- Tracked: AGT-13 (this research, done) → AGT-14/15/16 (bounded adoption
  packets, run-docs under `docs/projects/`).
