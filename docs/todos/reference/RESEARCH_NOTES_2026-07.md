# Research Notes — 2026-07 upgrade batch ("check out X" items resolved)

Live web research performed 2026-07-23 by three parallel read-only research
agents, converting every "check out X" todo in the master tracker into a
verified adopt / trial / skip decision. Each verdict is written back into the
corresponding [`GRAND_TODO_LIST.md`](../GRAND_TODO_LIST.md) item's Notes.

| Item | Topic | Verdict | One-liner |
| --- | --- | --- | --- |
| AGT-5 | Stanford STORM | **Trial** | MIT, LiteLLM-native since v1.1.0 — right shape for todo→run-doc pre-research; prove quality on local models first |
| AGT-3 | Harness score | **Trial (narrow)** | Real MIT tool (repo-readiness scanner, NOT task quality); baseline recorded 63/108 L1 |
| AGT-6 | 2026 agents guide | **Adopt as audit rubric** | Best-substantiated source: Perrone "AI Agents Stack (2026)" (O'Reilly); 5-practice audit checklist below |
| AGT-2 | Aiden AI OS | **Skip; pattern-mine** | AGPL-3.0 core, bus-factor 1, heavy overlap with what we built; 4 borrowable ideas |
| AGT-1 | agents CLI (metrics) | **Trial AgentsView** | fandf.co = ad-agency shortlink; best candidates AgentsView (MIT, mature) + caut (quota schema) |
| AGT-4 | Copilot option | **Trial** | Copilot CLI GA 2026-02; true headless analogue of `codex exec`; PAT auth; flags unstable — pin versions |
| AGT-7 | "Claude design" OSS | **Skip dep; pattern-mine** | = Open Design (nexu-io, Apache-2.0, ~81k stars); not a component library; DESIGN.md convention is the useful bit |
| CVP-1 | ARKit realtime iPhone | **Archived** (operator de-scoped CV 2026-07-23) | Research preserved: "Outlet" doesn't exist — tool is **ARFlow** (Apache-2.0) + Rerun; depth dead at court distance; Record3D if revived |
| SCL-1 | Social managers OSS | **Trial Postiz** (publish arm) | Best OSS publisher; NO inbound API. LinkedIn inbound = walled by LinkedIn CMA (entity required). Mixpost Pro inbox = conditional later |

## AGT-5 — Stanford STORM (todo pre-research engine)

- **What**: LLM research system: multi-perspective question asking + retrieval
  → cited references + outline → full article. Co-STORM adds human-in-loop
  discourse. `pip install knowledge-storm`, entry `STORMWikiRunner`.
- **Repo**: github.com/stanford-oval/storm — MIT, ~30.3k★, v1.1.0
  (2025-01-23) made it **LiteLLM-compatible** → it can point at our own
  gateway/Ollama directly. Issues active into 2026; release cadence stalled.
- **Fit**: the pre-writing stage's output (Q&A trail, cited refs, outline) is
  essentially a PROC-2 run-doc skeleton. Risks: quality on qwen3:30b-class
  local models unproven; many LLM calls per topic; retrieval needs a backend
  (SearXNG or DuckDuckGo need no keys).
- **Verdict: TRIAL.** First step: scratch venv, `LitellmModel` at the local
  proxy + DuckDuckGo retriever, run one real board todo topic, judge whether
  the artifact is good enough to seed a run-doc.

## AGT-3 — Harness score (grading our LLM systems)

- **What it actually is**: `paladini/harness-score` (MIT) — a deterministic
  static scanner (`npx harness-score`) grading a **repo's readiness for AI
  coding agents**: 36 checks, 6 dimensions, 108 pts, levels L0→L4. It does
  **not** measure agent task performance.
- **BASELINE RECORDED 2026-07-23** (v1.3.2, evidence:
  [`../../projects/agt-3-harness-score/baseline-2026-07-23.json`](../../projects/agt-3-harness-score/baseline-2026-07-23.json)):
  llm_station = **63/108 (58%), Level 1 "Documented"**. Sensors 20/20,
  Hygiene 23/23, CI 11/14, Context 9/20, **Skills 0/17, Hooks 0/14**.
  Next-level gaps: context ≥60%, skills ≥30% or hooks ≥30%. → the cheap wins
  are a substantive AGENTS.md/skills setup + hooks; feed as KPI-leaderboard
  attempts.
- **For actual task-completion quality** (what AGT-12 wants): use METR-style
  task standards + the Artificial Analysis Coding Agent Index pattern
  (scores model+harness pairs); SWE-bench Verified / Terminal-Bench v2 for
  external calibration.
- **Verdict: TRIAL (narrow)** as advisory repo-harness lint; never a gate at
  48★/single-maintainer maturity.

## AGT-6 — "How to build AI agents, 2026" (pipeline audit)

- **Finding**: the viral LinkedIn item is a genre, not one document. Best
  substantiated match: **Paolo Perrone, "The AI Agents Stack (2026
  Edition)"** — O'Reilly Radar (2026-06-08) republication = editorial vetting.
- **Audit rubric for our kanban pipeline** (map each to covered/partial/missing):
  1. Three-tier evals built before deployment (PR-time / nightly / production
     monitoring) — audit every agent surface, not just the leaderboard.
  2. Authorize-before-action at the tool-call layer — confirm no mutation
     path is guarded only by prompts/output filtering.
  3. Observability ≠ evals — find surfaces with Ledger traces but no scored
     quality signal.
  4. Postgres-history-first memory / context engineering — audit what each
     agent actually sees per turn before adding vector memory.
  5. Right-sized orchestration — strip workflow scaffolding from stateless
     tool-callers.
- **Verdict: ADOPT as audit rubric.** First step: one-session gap audit,
  output = gap list on the board.

## AGT-2 — Aiden (open-source AI OS)

- **What**: taracodlabs/aiden — local-first agent runtime (TS/Node/SQLite/
  Playwright): task planning, outcome verification with 16 failure classes,
  3-namespace memory with distillation, SQLite trigger bus, tiered approval
  engine, sub-agent fanout, 19 providers incl. Ollama. v4.15.1 (2026-07),
  ~741★, single maintainer. **Core AGPL-3.0** (skills Apache-2.0).
- **Verdict: SKIP adoption** (AGPL + bus-factor-1 + heavy overlap with what
  Command Center already has). **Pattern-mine 4 ideas**: tiered risk levels
  on approvals; failure-classification + verify-outcome loop; memory
  distillation/graduation; trigger bus (relevant to `cc notify` scheduling).
  First step: one-page gap comparison vs our memory + self-improvement loop.

## AGT-1 — "agents CLI" for metrics

- **Finding**: the fandf.co link is a Freeman & Forrest (influencer agency)
  paid-placement shortlink — exact target unpinnable. Best candidates:
  1. **AgentsView** (kenn-io/agentsview, MIT, ~4.5k★, v0.38.1 2026-07):
     single-binary local session browser + token/cost/tool-usage metrics
     across 40+ agents incl. Claude Code, Codex CLI, Copilot CLI.
  2. **caut** (Dicklesworthstone/coding_agent_usage_tracker): quota %/rate-
     window/credits polling with a versioned `caut.v1` JSON — immature (76★)
     but its schema matches our usage layer's "provider" source tier.
- **Verdict: TRIAL AgentsView read-only** as a validator for our usage.v1
  estimates (diff its per-session numbers against ours for a week);
  pattern-mine caut's quota schema. Neither replaces the Ledger-backed layer.

## AGT-4 — GitHub Copilot as a third agent runtime

- **State 2026**: Copilot CLI GA 2026-02-25; headless analogue of
  `claude -p`/`codex exec`:
  `copilot -p "prompt" -s --no-ask-user --allow-tool='...' --model <m>`;
  headless auth via fine-grained PAT with "Copilot Requests" permission in
  `COPILOT_GITHUB_TOKEN`. Multi-model (Claude, GPT-5.3-Codex, Gemini).
  Proprietary; per-prompt premium-request billing; **flag churn risk** (they
  removed `--headless --stdio` without deprecation — pin CLI versions).
- **Verdict: TRIAL.** First step: a `copilot` adapter behind the same
  READ-ONLY wall as the Codex adapter; mint the PAT; re-run the 14-case
  read-only cockpit acceptance with zero tool grants before any write-mode
  consideration.

## AGT-7 — Open-sourced "Claude design"

- **What**: the post refers to **Open Design** (nexu-io/open-design,
  Apache-2.0, ~81k★, v0.16.1) — an Electron app where your existing coding
  agent (Claude Code/Codex/25+ CLIs) generates designs/prototypes/exports.
  License clean, no Anthropic branding rip. NOTE: it is a design-generation
  product, **not** a Claude-style component library — no drop-in cockpit UI.
- **Verdict: SKIP as dependency; pattern-mine** (1) daemon-spawns-agent-CLI +
  session-resume architecture (same shape as our host worker), (2) the
  portable `DESIGN.md` design-system convention (see
  VoltAgent/awesome-claude-design) to standardize cockpit visual language for
  agent-generated UI. First step: one local session; extract one DESIGN.md
  spec for the cockpit.

## CVP-1 — Real-time ARKit streaming (iPhone)

- **Correction**: no project called "Outlet" exists. Pablo Vela's demo is
  **ARFlow** — Unity/ARFoundation mobile client streaming ARKit RGB + depth +
  camera pose over gRPC into a Python server logging live to the **Rerun**
  viewer. Vela (rerun.io) forked it with SLAM-translation logging in
  `rerun-io/pi0-lerobot@hand-kinematic-fitting`.
- **Repos**: cake-lab/ARFlow (Apache-2.0, v0.4.0 2025-06, research-grade);
  rerun-io/rerun (MIT/Apache-2.0, very active — worth adopting in the bball
  pipeline regardless).
- **Honest limits for basketball**: iPhone LiDAR depth is 256x192 and
  effectively dead beyond ~5 m → **useless at court distances**; ARKit
  body-skeleton streaming unverified in ARFlow; no local buffering (packet
  loss on gym Wi-Fi); you compile the iOS client yourself. The valuable
  stream is **per-frame camera pose (VIO) + RGB** as a homography/scale prior
  and live-capture UX.
- **Verdict: TRIAL** as research scaffolding; recording-then-processing stays
  the production path. **First step (≤1 h, no Unity)**: `pip install
  rerun-sdk` + the Record3D iOS app (`record3d` Python lib) → posed RGB-D
  into Python over USB/Wi-Fi; prove the pose-prior value for homography
  before touching ARFlow's Unity build.

## SCL-1 — Open-source multi-social management

- **Field (verified 2026-07)**: **Postiz** (gitroomhq/postiz-app, AGPL-3.0,
  33.7k★, very active) — best OSS publisher: real REST API
  (`POST /public/v1/posts`), SDK, MCP, self-host parity; **no read-side API**
  (no comments/mentions/notifications endpoints). **Mixpost** (Lite MIT free;
  Pro one-time $299) — v6 shipped a **unified DM/comments inbox (Pro only,
  2026-06)** + webhooks. **Brightbean Studio** — 4 months old, skip for now.
  **Ayrshare** — closed SaaS, fails self-host requirement.
- **The decisive constraint is LinkedIn, not the tools**: personal-profile
  posting is self-serve, but company pages and ANY comment/engagement
  reading require LinkedIn's **Community Management API — granted only to
  registered legal entities** after review. No self-hosted tool can give an
  individual account LinkedIn inbound. (Relevant: business registration is
  already an SCL-4 thread — completing it unlocks this.)
- **Fit**: we already have a governed LinkedIn publish path
  (`cc linkedin-publish` + approval boards). These tools earn their place
  when adding X/Bluesky/IG/TikTok/YouTube.
- **Verdict: TRIAL Postiz** as the multi-network publishing arm behind the
  existing approval gate; **Mixpost Pro = conditional later** if/when the
  inbound→kanban leg matters and the LinkedIn entity wall is cleared;
  Brightbean/Ayrshare skip. **First step**: docker-compose Postiz locally,
  connect the LinkedIn personal provider via our own developer app, publish
  ONE already-approved draft via its API; judge coexist-vs-replace against
  `cc linkedin-publish`.

## Provenance

Three parallel read-only research agents (WebSearch/WebFetch), 2026-07-23.
Source links preserved per section. Harness-score baseline run locally the
same day (`npx harness-score --json`, v1.3.2).
