# Command Center + Growth OS — The Complete System

> **This is the one doc.** It consolidates the `docs/` set into a single
> stage-by-stage walkthrough of the full setup: what the system is, what runs where,
> every pipeline stage, the full module tree with purposes, and a change log.
> Deep-dive references for each section are listed in [§12](#12-doc-index-where-the-detail-lives).
>
> Last full revision: **2026-06-12**. Latest readiness update:
> **2026-06-20**. Current source of truth is local `main` synced with
> `origin/main` at `0ac008c`.

---

## Current readiness snapshot (2026-06-20)

Phase 0 source reconciliation is complete. Local `main` is clean, synced with
`origin/main`, and the remote advertises only `main` plus `setup/github-ready`.
PR #10, #11, and #12 are closed and merged. PR #6 is closed unmerged as the
draft canary proof PR. The merged `main` line contains `configs/autonomy.yaml`,
the enabled `llm_station` repo manifest, the UI/chat/SSE/SMS work, the
capability catalog, proactive RCA intake, desktop no-op/timing evidence, and
the daily self-improvement DAG.

Phase 1 now has a real bootstrap/doctor surface:

- `uv run cc doctor` performs the full readiness doctor and emits PASS, FAIL,
  BLOCKED, or NOT_RUN for each check.
- `uv run cc bootstrap-local` is the local bootstrap command for render plus
  LiteLLM DB, LiteLLM, and Ledger.
- `uv run cc verify-stack` runs the same full readiness doctor.
- Redacted evidence for this pass is recorded at
  `evaluation/system-validation/20260620-phase1-doctor/doctor-report.json`.

Current doctor state: 19 PASS, 0 FAIL, 2 BLOCKED, 0 NOT_RUN. The two blockers
are real setup gaps, not code failures:

- AppFlowy kanban source is enabled but these env refs are absent:
  `APPFLOWY_BASE_URL`, `APPFLOWY_WORKSPACE_ID`, `APPFLOWY_EMAIL`,
  `APPFLOWY_PASSWORD`.
- `discord-main` is enabled but `DISCORD_ALLOWED_CHANNEL_IDS` is absent.

Next order:

1. Decide whether this machine should run AppFlowy mode now. If yes, set the
   AppFlowy env refs and run `uv run cc kanban-bridge --dry-run`. If not,
   disable the AppFlowy source until the new board registry lands.
2. Either set `DISCORD_ALLOWED_CHANNEL_IDS` or disable `discord-main` until
   Discord is intentionally live.
3. Rerun `uv run cc doctor`.
4. Continue Phase 2: board registry and `kanban-register` /
   `kanban-verify` / `kanban-sync --dry-run`.

## Table of contents

1. [What this is](#1-what-this-is)
2. [The contract model — the one rule](#2-the-contract-model--the-one-rule)
3. [Physical layout — machines and the mesh](#3-physical-layout--machines-and-the-mesh)
4. [Architecture — what runs where](#4-architecture--what-runs-where)
5. [Model lanes and routing](#5-model-lanes-and-routing)
6. [Stage by stage — the five pipelines](#6-stage-by-stage--the-five-pipelines)
   - 6.1 [Risk tiers L0–L4](#61-risk-tiers-l0l4-one-permission-system-for-everything)
   - 6.2 [The request pipeline (new work)](#62-the-request-pipeline-new-work--9-stages)
   - 6.3 [The kanban intake pipeline (cards → missions)](#63-the-kanban-intake-pipeline-cards--missions)
   - 6.4 [The proactive lane (already-shipped work)](#64-the-proactive-lane-already-shipped-work)
   - 6.5 [The model-update pipeline (no auto-promotion)](#65-the-model-update-pipeline-no-auto-promotion)
7. [Environments and isolation](#7-environments-and-isolation)
8. [The hard wall — GitHub](#8-the-hard-wall--github)
9. [Build phases — stage-by-stage setup](#9-build-phases--stage-by-stage-setup)
10. [The operator interface](#10-the-operator-interface)
11. [Module tree and purposes](#11-module-tree-and-purposes)
12. [Doc index — where the detail lives](#12-doc-index-where-the-detail-lives)
13. [What NOT to build](#13-what-not-to-build)
14. [Change log](#14-change-log)

---

## 1. What this is

Two systems joined by one bridge, governed by one permission model:

- **Command Center** (`llm_station/`, this repo) — the execution plane. A
  contract-validated control plane (LiteLLM gateway, Judge Gate, Ledger,
  Proactive Runner) that lets coding agents (Claude Code primary, Codex CLI
  fallback) do real repo work inside leased, isolated worktrees — with
  deterministic checks, LLM judge arrays, human approval gates, and GitHub
  branch protection as the final wall.
- **Growth OS** (`appflowy_kanban/growth-os/`) — the human surface and
  knowledge base. Self-hosted AppFlowy boards (todos, mission intake, papers /
  repos / signals, packages, guidelines, DAGs, library), self-updating
  watchers, a local assistant, an MCP server, and a Discord gateway — all
  backed by **one action layer** (`growthos/actions.py`).
- **The bridge** (`scripts/kanban_bridge.py`) — the only join between them.
  Approved kanban cards become Ledger missions; mission status is stamped back
  onto the cards.

The one-sentence design: **many channels, one brain gateway, one action layer,
one approval wall** — open-source local models do the routine work for ~$0;
Claude Code / Codex are engaged through gated missions for the big things; a
human drag-to-Approve and GitHub branch protection are the two boundaries no
agent can cross alone.

```
 CHANNELS (talk to it anywhere)              KNOWLEDGE (updates itself)
 ┌─────────────────────────────┐             ┌──────────────────────────────┐
 │ AppFlowy boards (phone/web) │             │ papers/repos/signals  hourly │
 │ chat.bat (terminal, Ollama) │             │ guidelines (standards+feeds) │
 │ Claude Code via MCP         │             │ packages (semver vs PyPI)    │
 │ Discord bot (anywhere)      │             │ dags (airflow_sync, live)    │
 │ [future: SMS/email/voice]   │             │ library/lessons/notes (you)  │
 └──────────────┬──────────────┘             └──────────────┬───────────────┘
                │  natural language                         │ rows
                ▼                                           ▼
 ┌─────────────────────────────┐  reads/writes  ┌──────────────────────────┐
 │ BRAIN GATEWAY: LiteLLM:4000 │◄──────────────►│ ACTION LAYER             │
 │  triage / planner / coder / │   tool calls   │ growthos/actions.py      │
 │  local-judge → Ollama       │                │ (~20 tools, one source   │
 │  (qwen3/devstral, $0,local) │                │  of truth for every agent│
 └─────────────────────────────┘                └────────────┬─────────────┘
                                                             │ add_mission_card
                                                             ▼  (Backlog only)
 ┌───────────────────────────────────────────────────────────────────────────┐
 │ THE WALL — human approval, enforced three ways:                           │
 │  1. agents cannot set Approved (actions.set_status refuses)               │
 │  2. the bridge applies ONLY Approved cards (configs/kanban.yaml)          │
 │  3. L3/L4 missions additionally hold at the Ledger awaiting approval      │
 │                 YOU drag the card → that is the entire UX                 │
 └─────────────────────────────────────┬─────────────────────────────────────┘
                                       ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ EXECUTION PLANE: bridge → Ledger:8091 → risk gates → judges (local      │
 │ models, judging against standards.yaml) → executors (Claude Code/Codex  │
 │ in leased worktrees) → PR behind the GitHub wall → morning-brief worklog │
 └─────────────────────────────────────────────────────────────────────────┘
```

Fourteen Mermaid diagrams covering every concern below live in
[visuals.md](visuals.md).

---

## 2. The contract model — the one rule

The whole system obeys one rule, and that rule is what makes it hard to break:

```
configs/*.yaml      = the editable source of truth
schemas/*.py        = Pydantic contracts that validate it
generated/*         = disposable rendered output (never hand-edited)
ledger.sqlite       = the only runtime state
Makefile / cc.ps1   = the only operator interface
.env                = secrets (never in YAML, never committed)
```

Edit YAML → `make validate` → `make render` → run a target. Nothing runs until
validate passes; nothing external happens until the Ledger and gates approve
it; nothing reaches a main branch without GitHub enforcing it.

**Proven, not asserted** — these bad edits are rejected by `make validate`
before they can ship (all tested):

- a typo'd key (`priorty:`) → rejected (`extra="forbid"`)
- two models with the same priority in one role → rejected
- two canaries in one role, or `canary_weight` outside 0–1 → rejected
- a missing risk tier, or **L3/L4 without `requires_approval`** → rejected
- a `repo_task` environment that is persistent or holds secrets → rejected
- a provider (OpenAI/Anthropic/OpenRouter) route in a LiteLLM role → rejected
- a scheduled check proposing L3/L4, `on_fail: auto_fix`, stewardship above
  L2, a check with no owner/schedule/evidence → rejected (eight cases firing)
- `scout.propose_only: false` → rejected ("swap to the leaderboard top" is
  not representable)

The dangerous mistakes — silently broken routing, an approval gate quietly
disabled, a sandbox that leaks secrets, a wandering refactor agent — cannot be
committed in the first place.

The config files and their contracts:

| File | Governs |
|---|---|
| `configs/models.yaml` | which model each role maps to (local-only, ranked candidates) + the `scout` source list |
| `configs/model-scout-curated-openweight.yaml` | strict, installed-and-digest-joined scored open-weight candidates (promotion-grade provenance) |
| `configs/model-scout-watchlist.yaml` | un-pulled frontier (GLM-5.2/Kimi) + pull-to-verify models, tracked by name with honest dual-budget fit (context, not promotion evidence) |
| `configs/model-benchmarks.yaml` | role-specific local A/B **quality** suites + metric policy + the "deep enough" methodology bar |
| `configs/model-serving-benchmarks.yaml` | **serving** SLO scenarios (TTFT/ITL/TTLT + operating point) — `quality_eval != serving_eval` |
| `configs/frontier-router-providers.yaml` | paid frontier-API backup lane: provider/model pricing metadata (off by default; not the local lane) |
| `configs/frontier-router-budgets.yaml` | hard caps + redaction + blocked-payload gate for the frontier-router lane (`enabled: false`) |
| `configs/judges.yaml` | judge arrays per stage, cross-provider pairing, budgets |
| `configs/gates.yaml` | L0–L4 risk/approval policy |
| `configs/environments.yaml` | one environment per activity, isolation rules |
| `configs/standards.yaml` | durable operating standards for Claude, Codex, and Judge Gate |
| `configs/breakage.yaml` | what ripples when you change a file (powers `make impact`) |
| `configs/proactive.yaml` | scheduled checks on already-done work, RCA caps, daily self-improvement scan |
| `configs/targets.yaml` | the watch inventory: repos, DAGs, data assets, services + SLOs |
| `configs/tools.yaml` | tool permissions the judges can cite |
| `configs/capabilities.yaml` | ARD-style internal capability discovery metadata: owner, type, representative queries, trust, provenance |
| `configs/evals.yaml` | routing/judge regression suite = the model-promotion gate |
| `configs/kanban.yaml` | bridge dispatch contract: sections, risk ceilings, ready statuses |
| `configs/ui.yaml` | WebUI safety defaults (single-container, password, ledger-governed writes) |
| `configs/channels.yaml` | chat transports (Discord/Slack/Telegram/WhatsApp) → transport + model alias |
| `configs/improvement.yaml` | self-improvement experiment definitions (+ `improvement-targets.yaml` per-target refs) |
| `configs/discovery.yaml` | daily-scan knobs: ranking / triage / code-health / acceptance (no inline literals) |
| `configs/agent_surface.yaml` | agent-kanban knobs: board-state re-injection cadence/size, fuzzy addressing, tuning bounds (`AgentSurfaceConfig`) |
| `configs/autonomy.yaml` | whole-system autonomy hardening: event contracts, repo manifests, desktop rights, canary blockers, telemetry/auth/runtime gates |

---

## 3. Physical layout — machines and the mesh

| Machine | Role | Why it's here |
|---------|------|---------------|
| **VPS** ($5–12/mo, 2 vCPU / 4 GB) | always-on brain | Must be up when the house, 4090, and 5080 are all off. The load-bearing decision — the brain can't live on hardware that sleeps. |
| **RTX 4090 desktop** | heavy worker + local model tier | Runs DAGs/CV, the git worktrees agents edit, and the free local models (Qwen/Devstral) for triage and cheap judging. |
| **RTX 5080 laptop** | human workstation | VS Code Remote Tunnel into the 4090's worktree; dashboards. You drive; the agent works. |
| **Pi / mini-PC** (optional) | home relay only | Wake-on-LAN for the 4090, watchdog, backup mirror. Skip unless needed; a mini-PC beats a Pi at 2026 prices. |

The brain reaches the muscle over a **Tailscale private mesh** — no public
SSH, no public dashboards. All web UIs bind to 127.0.0.1 and are reached over
Tailscale. Nothing is public unless you deliberately add Caddy + Cloudflare
Access (on the do-not-build list by default).

> **Current state (2026-06-12):** everything still runs on the Windows
> workstation; the VPS/4090 split and the Linux migration
> (`growth-os/deploy/linux/MIGRATION.md`) are the standing next steps when the
> prod box revives.

---

## 4. Architecture — what runs where

### The control plane (Docker Compose, on the VPS / currently local)

| Service | Job |
|---|---|
| **LiteLLM + Postgres** | The local-only model gateway to Ollama. Virtual keys restrict clients to approved aliases. Pinned by **digest** (never a tag, never pip — the March 2026 PyPI compromise is the cautionary tale). |
| **Judge Gate** | Risk classification + the judge arrays. Mounts `configs/standards.yaml`, so every judge cites the same rules rendered into repo instructions. |
| **Ledger (SQLite)** | Missions, leases, signed approvals, the kill switch, the audit log. What makes "keep working while I'm away" safe rather than just possible. |
| **Proactive Runner** | Scheduled checks on already-done work. Holds no secrets; its strongest autonomous act is opening a gated mission. |
| **Discord Gateway** | Discord ↔ LiteLLM (`chat`) ↔ the Growth OS action layer. Fail-fast without `DISCORD_BOT_TOKEN`. The `chat` role is qwen3 (instruct), **not** qwen3-coder — chat surfaces narrate before tool calls, and qwen3-coder's Ollama native parser drops those calls (see §14, 2026-06-13). |
| Uptime Kuma + restic | Health monitoring and backups. |
| *(optional profile `ui`)* **Agent Kanban UI** | First-party Cline-styled board + observability over the Ledger (missions kanban) and the agent-call log (metrics). **Read-only** — no write path; approve/kill stay in the signed Ledger endpoints, which it links out to. Loopback + Tailscale + password; `configs/ui.yaml` (`agent_kanban_ui`), repurposed from the deferred Hermes WebUI. React/Vite SPA built + served single-container by a FastAPI backend. |
| *(optional profile)* Hermes | **Not adopted — evaluated 2026-06-13 → DEFER.** Hermes Agent is real now (v0.16.0, PyPI/official image); the old "phantom image" note is stale. An isolated spike (see change log + `evaluation/capability-assessment/hermes/DECISION.md`) found cross-session memory works but is just a local `MEMORY.md` (not beyond-stack) and self-improving skills did not auto-fire. LiteLLM + Ollama + the action layer serve its role; revisit only if autonomous skill self-improvement materializes. |

### The worker (4090 / currently the same workstation)

- **Ollama** serving `qwen3-coder:30b`, `qwen3:30b`, `devstral:24b` (Q4,
  ~14–19 GB on the 24 GB card).
- **Git worktrees + devcontainers** — one isolated checkout per mission,
  ephemeral, no secrets.
- **Executors**: Claude Code (primary) and Codex CLI (fallback), authenticated
  by their own subscription/OAuth logins, never via API keys.

### Growth OS (always-on curator loop, `docker-compose.curator.yml`)

Watchers on a cadence — hourly: curate (+enrich) and airflow_sync; daily after
06:00: brief, guidelines, retention; every 15 min (host task): the kanban
bridge; on demand/host: packages, import_books/dags, selftest.

### The two human gates (the only UX that matters)

1. **Approvals**: drag a card to Approved on the board, or sign L3/L4 in the
   Ledger UI / a chat channel.
2. **Merge**: GitHub PR — CODEOWNERS review + required checks. The bot can
   never merge.

---

## 5. Model lanes and routing

LiteLLM is **local-only** in this repo. Every LiteLLM role renders to
`ollama_chat/...` against `OLLAMA_API_BASE`. There is **no cloud fallback**:
if Ollama is down or a virtual key isn't allowed an alias, the call **fails
closed**.

| Lane | Runs | Auth | Provider API charge |
|---|---|---|---:|
| **LiteLLM local gateway** | `triage`, `chat`, `planner`, `local-judge`, `security-judge`, `architect-judge`, `coder` aliases | `HERMES_LITELLM_KEY` / `JUDGE_GATE_LITELLM_KEY` (virtual keys you mint) | $0 |
| **Ollama on the 4090/host** | the actual model runtime behind LiteLLM | none | $0 |
| **Claude Code executor** | primary coding missions in leased worktrees | Claude subscription/OAuth login | $0 |
| **Codex executor** | fallback coding missions | ChatGPT login | $0 |

Hard rules, all enforced by validation and the live smoke test:

- **No provider API keys anywhere** — not in `.env`, process env, user env, or
  machine env. `scripts/check_forbidden_providers.py` and both live-smoke
  scripts verify this; the contract rejects provider routes in roles.
- The executor CLIs are **not generic APIs** for the gateway — they are
  controlled subprocesses that work only inside leased worktrees, behind the
  same pre-commit/pre-push gates.
- Local role meanings: `triage` first-pass risk sorting; `chat` the
  conversational gateway surface (Discord/Slack/…), qwen3 instruct so tool calls
  parse even when the model narrates first; `planner` plans + validation plans,
  also qwen3 (Hermes tool-calls through it, so it must be tool-robust);
  `local-judge` continuous cheap judging; `security-judge` local security/scope
  skeptic; `architect-judge` high-effort planning/debug; `coder` dry-runs and
  fallback summaries (not the executor auth path). **Tool-using roles (chat,
  planner) must not use qwen3-coder** — its Ollama native tool parser drops
  prose-prefixed calls; `make validate` enforces this (`check_tool_safe_roles`).

Two Ollama gotchas worth pinning: agents need **≥64k context** (Ollama
defaults to 4,096 — raise `num_ctx`), and Ollama serves **one request at a
time by default** (set `OLLAMA_NUM_PARALLEL` and `OLLAMA_KEEP_ALIVE=-1` so
parallel judge calls don't queue or thrash reloads).

### 5.1 External routing reference — Puppetmaster is BORROW_PATTERN_ONLY

Reviewed 2026-06-14 from the pasted Puppetmaster README plus its upstream
GitHub/PyPI docs and this repo's live contracts/tests. Decision: **do not
install or adopt Puppetmaster as a runtime router in this stack**. It is useful
as a reference for auditable routing and typed worker artifacts, but a wholesale
install would introduce a second supervisor/model registry/hook layer next to
LiteLLM, Judge Gate, the Ledger, and the approval wall. Its cloud/API
cost-router mode also conflicts with the local-only boundary above.

What is already done here:

1. **Local-only role contract** — `configs/models.yaml` roles must be
   `provider: ollama`, `local: true`; provider API keys are rejected by
   validation and forbidden-provider checks.
2. **Executor routing contract** — Claude Code is the primary leased-worktree
   executor; Codex is the cross-provider fallback/verifier path; local models
   do not become primary coding executors.
3. **Model discovery gate** — `model-scout` is propose-only and annotates
   candidates with real VRAM fit; promotion still requires validate, evals,
   canary, comparison, and a human tap.
4. **Routing improvement target** — the coded improvement loop already has a
   `routing` target with `routing_accuracy`, `routing_regret`, and
   `unsafe_downgrades`; it can evaluate routing changes without adding a third
   party runtime.

Borrow from Puppetmaster as patterns only:

- emit a typed `ROUTING` artifact for each non-trivial route decision;
- record the picked role/executor, required capability, source config hashes,
  observed token/cost fields when LiteLLM supplies them, and rejected
  alternatives with concrete rejection reasons;
- classify failures before retry/escalation: Ollama unavailable, model missing,
  model OOM/context-fit failure, invalid JSON/truncation, tool-parser failure,
  executor missing, timeout, auth/session failure, and human-approval-required;
- store worker/judge outputs as typed artifacts with evidence references,
  confidence, outcome, and sha256 so follow-up reads reuse artifacts instead of
  rerunning models.

Do **not** borrow:

- global hooks, MCP auto-invocation, or prompt-submit interception;
- cloud provider/API routes, OpenAI/Anthropic/OpenRouter keys, or a cloud
  fallback;
- a second model registry outside `configs/models.yaml`;
- a second job/artifact store outside the Ledger;
- silent fallback. A missing model, unsafe route, missing artifact field, or
  unavailable service fails loud and leaves an event; it does not fabricate a
  route, cost, metric, or success.

Data/privacy rule for any borrowed artifact shape: record only bounded,
operator-useful metadata and references. Do not persist raw chat transcripts,
secret-bearing environment values, `.env` content, provider tokens, full diffs
that may contain secrets, or hidden eval content. Evidence should be a path,
hash, mission id, config hash, redacted excerpt, or deterministic check result
unless a human explicitly approves retaining the full artifact.

Ordered next work (do not skip ahead):

1. **Done now — document the decision.** This section is the reference point:
   Puppetmaster is pattern material, not a runtime dependency.
2. **Done 2026-06-14 — make Judge Gate routing data-derived.** The inline
   `services/judge_gate/app.py` risk→alias table has been replaced by
   `configs/gates.yaml` `default_route_alias` values, required by schema,
   cross-checked against `configs/models.yaml`, and loaded by Judge Gate at
   startup. Missing or dangling aliases fail loudly; no inline defaults, fake
   costs, or hidden fallbacks.
3. **Add Ledger routing artifacts.** Add a small typed event/artifact for route
   decisions using only the fields above. The artifact should cite source
   config hashes and real LiteLLM usage fields when present; when usage is
   absent, say `unknown` rather than estimating dollars.
4. **Measure before learning.** Feed the new artifacts into the existing
   `routing` improvement target only after there is a declared fixture set or a
   pre-registered statistical plan. Until then the deterministic harness stays
   the baseline; do not invent thresholds or train on leaked outcomes.
5. **Then consider a one-mission adapter spike.** Only if artifacts show a real
   routing/work-reuse problem the current stack cannot solve, run a
   Ledger-invoked Puppetmaster adapter experiment with hooks disabled, no
   provider keys, no global installs, and rollback evidence. That experiment
   must pass the external capability-evaluation loop before any pilot.

### 5.2 External AI-agent idea intake — broad prompt first

Use [agent-ideas-evaluation-prompt.md](agent-ideas-evaluation-prompt.md) when
the candidate is broader than a single obvious dependency bump: ClawCodex,
Agno/GitWiki, SIA, MAPPA, codebase-memory-mcp, local-ai-server, dbt Wizard,
BigQuery Graph / ADK / A2UI / BigSet, agentcookie, or a generic multi-agent
framework. The goal is to decide whether there is a measured gap and a safe
capability to extract before any install, pilot, hook, daemon, provider key, or
control-plane change.

What is already done:

1. The broad prompt exists and starts from the implemented stack, not stale
   brainstorming assumptions.
2. The narrower [capability-evaluation-loop.md](capability-evaluation-loop.md)
   now points back to the broad prompt for wide candidate sweeps.
3. The no-build list below now rejects candidate bundles that lack a measured
   gap, control-plane overlap matrix, threat model, and pre-registered
   experiment plan.
4. The first read-only routing/performance pass is complete:
   [routing-performance-candidate-evaluation-2026-06-14.md](routing-performance-candidate-evaluation-2026-06-14.md).
   Verdict: improve routing natively first; pilot `codebase-memory-mcp` only as
   a manual read-only retrieval benchmark; keep Puppetmaster, MAPPA, Agno/GitWiki,
   A2UI, Docker Model Runner, and dbt skills as patterns/conditional pilots;
   reject control-plane/runtime adoption for ClawCodex, OpenClaw, generic
   agent frameworks, BigSet, agentcookie, and SIA-in-production.

Remaining order for this candidate batch:

1. Mission 1 is complete through final independent verification:
   Judge Gate classify routing is now config-derived from `configs/gates.yaml`
   and cross-checked against `configs/models.yaml`.
2. Add typed Ledger route artifacts and route failure classes before learning
   from routing. Missing usage/cost data is `unknown`, not estimated.
3. Run a pre-registered read-only `codebase-memory-mcp` benchmark against
   `rg`, Semble, and native agent search. Binary-only/manual invocation first;
   no auto-install, MCP registration, hooks, skills, instruction edits, or UI
   daemon before it wins.
4. Add deterministic post-run attribution inspired by MAPPA only after route
   artifacts exist.
5. Evaluate Git/Markdown knowledge projection against OKF/AppFlowy only after
   recurring-query gold cases exist.
6. Benchmark Docker Model Runner only behind LiteLLM, and only if Ollama
   throughput/context/reproducibility becomes a measured bottleneck.
7. Promote anything only through the existing improvement/verification/GitHub
   wall; no candidate may become its own evaluator or source of truth.

### 5.3 Continuous upgrade loop — Mission 1 verified

The continuous capability upgrade prompt is now active as a bounded evidence
program, not permission to keep adding tools. Current cycle:
**config-derived Judge Gate routing**.

What is done:

1. Baseline captured in
   [evaluation/continuous-upgrade/BASELINE.md](../evaluation/continuous-upgrade/BASELINE.md)
   and
   [evaluation/continuous-upgrade/baseline.json](../evaluation/continuous-upgrade/baseline.json).
2. Capability state register created:
   [evaluation/continuous-upgrade/capability-register.md](../evaluation/continuous-upgrade/capability-register.md).
3. Mission 1 evidence created with gap, experiment, machine-readable config,
   threat/privacy/authority review, and rollback:
   [GAP.md](../evaluation/continuous-upgrade/mission-1-config-derived-judge-routing/GAP.md),
   [EXPERIMENT.md](../evaluation/continuous-upgrade/mission-1-config-derived-judge-routing/EXPERIMENT.md),
   [experiment.yaml](../evaluation/continuous-upgrade/mission-1-config-derived-judge-routing/experiment.yaml),
   [THREAT_PRIVACY_AUTHORITY.md](../evaluation/continuous-upgrade/mission-1-config-derived-judge-routing/THREAT_PRIVACY_AUTHORITY.md),
   [ROLLBACK.md](../evaluation/continuous-upgrade/mission-1-config-derived-judge-routing/ROLLBACK.md).
4. Baseline commands passed before implementation: `uv run cc validate`,
   `uv run cc mission-dryrun`, `uv run cc evals`, and
   `uv run pytest tests/test_routing.py tests/test_safety_boundaries.py
   tests/test_sealed_evals.py tests/test_improvement_lifecycle.py` (39 passed).
5. The AI packages/tools notes were reconciled as inventory, not implementation
   truth. In particular, Hermes is not the active coordinator; it remains a
   previously deferred candidate per the existing evaluation record.

Current state:

- Config-derived Judge Gate routing: `INDEPENDENT_VERIFICATION_PASSED`.
- Implementation status: implemented in isolation.
- Promotion status: not requested; not promoted.
- Independent verifier status: initial verifier result was `FAIL` because this
  status section and `experiment.yaml` were stale, not because of a functional,
  security, or architecture block. The first re-check returned
  `PASS_WITH_LIMITATIONS` because older backlog text in this file was stale;
  after that text was corrected, the final narrow re-check returned `PASS`.
- Security posture: no new provider keys, daemons, MCP registrations, hooks,
  raw transcripts, hidden eval access, global config writes, second gateway,
  second ledger, or second scheduler.

Remaining order:

1. Do not promote Mission 1 automatically. Human approval remains required for
   promotion.
2. If accepted, include Mission 1 in the next reviewed commit/PR with the
   evidence artifacts.
3. Start Mission 2 next: typed Ledger routing artifacts.

### 5.4 Open-weight model evaluation — discover → fit → benchmark → promote (CANONICAL)

**This is the single canonical section for "how Command Center discovers, fit-checks,
evaluates, and promotes a local model."** It is local-first, propose-only, and human-gated:
discovery may only draft a `Proposed` card; only a human moves anything to Canary or
Promoted; no provider keys; no fabricated fit or score. Every live number comes from the
repo's own runs (`cc model-scout`, the `model_baselines`/`model_candidate_audit` harnesses),
never a vendor leaderboard. (The legacy detail below is retained; the 2026-06-20 update is the
current source of truth.)

#### 2026-06-20 update — watchlist, dual-budget fit, frontier-watch, runnable cards, DAG wiring

The discovery layer previously could only see a model **already installed locally** (the
`curated-openweight` source fails closed unless the exact tag/digest/quant/param is present)
or one surfaced by a keyed Artificial Analysis call. So it could not "check on GLM/Kimi and
implement them when found." That gap is now closed end-to-end.

**The four model lanes** (a model only earns the next lane by passing the prior gate):

| Lane | Purpose | Examples | Runs here? | DAG action |
|---|---|---|---|---|
| **Installed local** | benchmark what is already pulled | `qwen3:30b`, `qwen3-coder:30b`, `devstral:24b`, `qwen3:8b` | yes | full local quality + serving eval |
| **Laptop-fit candidate** | models worth pulling next | GLM 9B-class, Qwen 14B/30B-class, Gemma/Phi/Devstral-sized, `gpt-oss-20b` | usually | propose pull → benchmark → compare |
| **Frontier-watch** | huge models that shape strategy but cannot fit | GLM-5.2, Kimi K2, DeepSeek-large MoEs | no | record facts; **never** a local benchmark |
| **External-framework** | popular eval signals | Aider, EvalPlus, BigCodeBench, LiveBench, lm-eval | partly | attach signal + optional local runner |
| **Frontier-router backup** | budgeted paid-API escalation for too-big models | GLM-5.2, Kimi K2 via OpenRouter / Z.ai | no (external) | **off by default**; preflight + budget + redaction gate, then *optional* call |

The clean principle: **frontier models inform strategy; laptop-fit models get pulled; installed
models get benchmarked; only benchmarked models become incumbents; only human-approved
incumbents get promoted.** A model is never promoted for trending — it must pass the local role
**quality** suite, the **serving** SLO check, the **fit** gate, and the **human** wall.

The implementation:

1. **Watchlist source** (`configs/model-scout-watchlist.yaml`, `ModelWatchlistConfig`) tracks
   open-weight models **by name without installing them**, in two tiers:
   - `frontier_watch` — real flagships too large for this hardware. **Track-as-context only;
     never benchmarked locally.** Seeded with the verified landscape:
     - **GLM-5.2** (Z.ai) is REAL and is the current flagship: **~744B total / ~40B active
       MoE, ~1M context, MIT**. Full weights ~1.51 TB; the smallest Unsloth dynamic GGUF is
       still ~217 GB (1-bit) → ~245 GB (2-bit) → ~420 GB (Q4). It needs a 256 GB
       unified-memory class machine; on this 24 GB VRAM + 32 GB RAM box it is **~4–18× too
       large** and is cloud-only on Ollama (`glm-5.2:cloud`).
     - **Kimi K2** (~1T / 32B MoE, ~540–584 GB Q4), **DeepSeek-V3** (671B/37B), **Qwen3-235B-
       A22B** (235B/22B), **GLM-4.5-Air** (106B/12B, ~60–73 GB Q4 — even this exceeds the full
       56 GB combined budget). All NO on both budgets.
   - `pull_to_verify` — plausibly-fitting models not yet pulled (seed: **gpt-oss-20b**,
     21B/3.6B MoE, Apache-2.0, ~14 GB). The scan drafts a **propose-only "ollama pull +
     benchmark"** card for the declared role; it never auto-pulls.
2. **Dual-budget, honest fit + named verdicts.** `configs/environments.yaml` now declares the
   **16 GB `cc-dev-5080`** laptop budget alongside the 24 GB `cc-worker-4090`, and the scout
   reports fit for **both**, plus a **256 GB-class unified-memory reference** (where the biggest
   dynamic quants run, slowly; promotion-disallowed). Each watchlist record gets named
   `runnable_targets` verdicts — `does_not_fit` / `ram_only_frontier_experiment` /
   `unknown_pull_to_verify`. When a record declares a **verified `local_artifact`** (e.g.
   GLM-5.2's Unsloth dynamic 2-bit at **~238 GB**) that real size is authoritative; otherwise
   `vram.weights_only_verdict` uses a conservative params×bpw **lower bound** — either way a
   frontier flagship is a decisive `does_not_fit` on 24/16 GB and `ram_only_frontier_experiment`
   only at 256 GB, and the verdict is never a fabricated `FITS`. `vram.py` also records MoE expert
   counts and clamps `max_ctx_fits` to the model's native context.
3. **The daily DAG now sees these.** `model_scout.scan_feed_records` is the single feed shared
   by the CLI (`make model-scout-scan`) and the Airflow DAG; the DAG's model pillar fetch now
   calls it (the old "phantom upstream ingestion DAG" is real for this pillar). `frontier_watch`
   records become low-priority **track-as-context** findings (DOCUMENTATION target, never a
   local benchmark); `pull_to_verify` records become **propose-pull** findings.
4. **Discovered cards are runnable (no longer inert).** When the scout can bind a candidate to
   a role incumbent, the feed record carries a resolved `model_benchmark` block, and
   `Finding.to_experiment_definition` drafts a **runnable** live-A/B card
   (role/suite/baseline/candidate/endpoint/fit-derived context). The contract now **fails loud**
   on a MODEL card that targets the live harness without runnable params (an inert card can no
   longer validate clean); a paramless candidate is retargeted to a `model_benchmark_needed`
   proposal. Canary/promotion remain human-only.
5. **Source hardening.** `scout.sources` is validated against `KNOWN_SCOUT_SOURCES` at
   `make validate` (a typo is rejected, not a silent skip); an Artificial Analysis `ollama_tag`
   is verified against the local install before it can ever draft a runnable benchmark.

**Methodology — the "deep enough" bar.** The role suites score quality well, but the runtime
side follows the discipline documented in `configs/model-benchmarks.yaml`: tokens/sec alone is
a *fake* metric; latency is three numbers (**TTFT / ITL / TTLT**, all derivable from Ollama's
`/api/generate` timings); the operating point is the request rate where **p90** latency still
meets the SLO (predict via the three-nineties rule `p90 TTLT ≈ p90 TTFT + p90 ITL × output`).
A suite gates a promotion only at ≥8 labeled cases/role, execution-based or judged scoring for
coder/judge, decoupled per-tag scoring, and `require_significance=true` with a pre-registered
MDE — otherwise it is context, not a gate.

**Serving-performance benchmark — `quality_eval != serving_eval`.** A model can be the smartest
and still lose if it is unusably slow. `configs/model-serving-benchmarks.yaml`
(`ServingBenchmarksConfig`) declares realistic workloads (`repo_triage` / `code_patch` /
`long_repo_reader`) with p90 SLOs; `serving_benchmark.parse_ollama_timings` derives **TTFT /
ITL / TTLT** from Ollama's `/api/generate` timings; `serving_slo.py` computes p50/p90/p95/p99,
the three-nineties prediction, and the **operating point** = the highest request rate whose p90
still meets the SLO. `serving_load_driver.py` is the implemented concurrency-sweep executor
(injectable measure_fn + clock, fully unit-tested without live Ollama); a real run binds it via
`build_measure_fn`. Full detail:
[model-serving-benchmarks.md](model-serving-benchmarks.md). Serving **engines** (vLLM → SGLang →
TensorRT-LLM) are a separate `runtime` axis — measured experiments behind the same human wall,
**not** quality signals; Ollama stays the default, vLLM is the first throughput experiment.

**Popularized-framework integration (priority order).** Evaluate *through* standard frameworks
without leaderboard-chasing — popular frameworks are **signal + optional local runner; the repo
harness is the final gate**:

1. **EvalPlus** (HumanEval+/MBPP+, Apache-2.0, Ollama OpenAI endpoint) — first **local runner**;
   replaces the substring coder check with execution-based pass@1.
2. **BigCodeBench** — more realistic code tasks (diverse function calls, ~1,140 tasks); fits the
   repo-agent/code-change use case.
3. **lm-evaluation-harness** — general academic runner (local/OpenAI-compatible, esp. via vLLM).
4. **LiveBench** — contamination-resistant **discovery signal** (objective, refreshed).
5. **Aider polyglot** — keep as a coding discovery/ranking signal (not the only truth).
6. **SWE-bench** — heavier; milestone/periodic eval, not daily; do not run it locally by default
   (agent scaffold + ~120 GB Docker, contaminated). **Skip** OpenCompass/HELM (redundant; HELM
   frozen) and the dead HF Open LLM Leaderboard.

EvalPlus + BigCodeBench are now **scaffolded** (`configs/framework-evals.yaml` +
`FrameworkEvalsConfig` + `improvement/frameworks/{evalplus,bigcodebench}_runner.py`): config,
result parsers (pass@1), and a fail-soft availability gate are unit-tested; `trust` is
contract-pinned to `supporting_evidence_only` (a framework result can never gate a promotion —
`is_decision_gate()` is always False). They are off by default and never auto-launch the heavy
tool — enabling = install the tool + set `enabled: true` + pass an executor.

**Frontier-router backup lane (paid APIs, off by default).** Some open-weight frontier models
(GLM-5.2, Kimi K2) are too large for the local hardware but useful as external reference models.
They stay `frontier_watch` for fit, and may *optionally* enter `frontier_router_backup` for
**budgeted** API evaluation — they are **never** local incumbents and a router result can never
promote a local model or bypass the local/quality/serving/canary/human gates. Metadata lives in
`configs/frontier-router-providers.yaml` (OpenRouter + Z.ai pricing, `disabled_until_budgeted`)
and `configs/frontier-router-budgets.yaml` (`enabled: false`, monthly/run/request caps,
mandatory redaction, blocked-payload classes). `improvement/router_cost.py` estimates cost and
ranks providers by the *cheapest eligible* route per workload (data-derived, never hardcoded);
`improvement/frontier_router_eval.py` runs a **fail-closed preflight** — lane-enabled → task
class → known model/provider → payload redacted → API key present → cost under the per-request
cap — and **makes no live call in this build**. Router-backed runs serve only
`frontier_reference_eval`, `long_context_comparison`, `local_failure_fallback`, and
`external_framework_calibration`. Full lane spec is below in this doc.

**The local-only contract is intact.** `check_forbidden_providers` still forbids
`OPENROUTER_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` in `.env` / process env / compose
and forbids any cloud route in `models.yaml` / the LiteLLM config — and still **passes**,
because the router configs are pure metadata (no key added) and the lane makes no call.
**Enabling real egress is a deliberate, separate operator decision:** set the provider key,
reconcile `check_forbidden_providers` to treat the router-lane keys as an explicit exception
(distinct from the local lane), then run a tiny budgeted smoke test. Until then the lane is
documented scaffolding, not a live capability.

**External note (not model-eval):** Google's **ARD** (Agentic Resource Discovery, `ai-catalog.json`
+ registries) is a *tool/agent* discovery standard, adjacent to this model-discovery work and to
the repo's existing `configs/capabilities.yaml` (ARD-style internal capability metadata). It is
routed to the external-idea-evaluation loop ([§5.2](#52-external-ai-agent-idea-intake--broad-prompt-first)),
not the model-eval core.

#### Frontier router backup lane (full spec)

Some open-weight frontier models are too large for the local hardware targets but still useful
as external reference models. These models remain in `frontier_watch` for fit purposes and may
optionally enter `frontier_router_backup` for budgeted API evaluation.

Router-backed models are never local incumbents. They are used only for: long-context
comparison · local failure fallback · frontier reference evaluation · external framework
calibration.

Every router-backed run must pass, in order (fail-closed, no silent fallback):

1. lane enabled (`budgets.default.enabled`) — **false by default**,
2. task class in `allowed_task_classes`,
3. model + provider known in `frontier-router-providers.yaml`,
4. payload redaction (`require_redaction` is always true),
5. provider API key present,
6. token preflight estimate under the per-request cap,
7. post-run cost reconciliation when the provider returns real usage (the estimate is never
   overwritten; missing usage fails when `fail_on_missing_usage`).

A router-backed result can inform model strategy, but it cannot promote a local model by itself
and cannot bypass the local benchmark, serving benchmark, canary, or human approval gates. In
this build `frontier_router_eval.call_frontier` runs the preflight and then **refuses to make a
live call** — enabling real egress requires reconciling `check_forbidden_providers` (which
forbids the provider keys by design) plus an explicit operator opt-in and a tiny budgeted smoke
test. Provider pricing is a public signal; the cheapest *eligible* route is computed per
workload, never hardcoded.

**Operator commands (all read-only / no egress):**

- `make frontier-router-dry-run MODEL=glm-5.2 IN=120000 OUT=8000` — preview cost + policy
  verdict (`live_call: false`), even while the lane is disabled. Cheapest eligible provider if
  `PROVIDER=` is omitted.
- `make frontier-router-price-audit` — flag any provider price whose `price_observed_at` is
  older than `price_freshness.max_age_days` (default 14d). Prices are dated public signals;
  `auto_update` is **contract-refused** — stale prices are surfaced for a human, never patched.
- `make frontier-router-egress-check` — the explicit egress reconciliation:
  `check_forbidden_providers --allow-frontier-router-egress`. It permits the router-lane keys
  (`OPENROUTER_API_KEY` / `ZAI_API_KEY`) **only** when `frontier-router-budgets.yaml` is
  `enabled` with redaction + usage accounting; the local LiteLLM lane stays cloud-free in both
  modes, and `OPENAI`/`ANTHROPIC` keys are never permitted. Default `make validate` /
  `cc validate` is unchanged and stays strict (`forbidden-providers: PASS`).

The deliberate enablement sequence stays: dry-run → price-audit → `make frontier-router-egress-check`
(with the key set + budget enabled) → a tiny budgeted smoke test (≤$0.10, ≤2k in / 500 out, no
private repo content) whose first goal is to verify usage/cost/latency/refusal accounting, not
"is the model smart."

What is done (legacy detail):

1. `model-scout` now emits an open-weight-only candidate set by default. A source
   row is kept only when it has explicit open-weight evidence or is a local
   Ollama tag with installed weights. Aider polyglot rows remain useful public
   coding-score context, but they are filtered out of the open-weight feed unless
   another source supplies open-weight provenance.
2. `curated-openweight` is now a version-controlled scored source for candidates
   whose public benchmark evidence can be joined to an exact local Ollama
   identity. A curated record must declare model family, release id, source model
   id, source model URL and payload hash, Ollama tag, Ollama digest, parameter
   size, quantization, context length, license, benchmark name/version, score
   definition, evaluation date, source URL, retrieval timestamp, source payload
   hash, and justified candidate roles.
3. The curated source performs a strict identity join against the installed
   `/api/tags` record. Digest, parameter size, quantization, context, configured
   license, and candidate role names must match exactly. Mismatches fail loudly;
   no closest-name matching, parameter inference, license inference, or role
   expansion is allowed.
4. Local Ollama candidates now carry source provenance from `/api/tags` and
   `/api/show`: Ollama tag, digest, quant, parameter size, native context,
   VRAM-fit verdict, max fitting context, and headroom. Missing metadata is
   recorded as unknown/error; no digest, license, context, or fit value is
   fabricated.
5. `make model-scout` now writes both the human report
   `generated/model-scout-report.md` and the machine feed
   `generated/model-scout-feed.json`. The daily scan can consume that feed with
   `make improvement-scan FEEDS=generated/model-scout-feed.json`.
6. The daily scan understands `model_scout_candidate` records. It drafts only
   `Proposed` `model` experiments for scored open-weight candidates, and it
   carries declared candidate roles so a coding score can draft a coder
   benchmark without implying planner, judge, or routing superiority. It states
   that local role-specific A/B is required before any routing recommendation.
7. `configs/model-benchmarks.yaml` is validated by `cc validate` and defines the
   role-specific benchmark suites plus each suite's metric policy. Prompts,
   metric names, expected/forbidden markers, structured JSON expectations, and
   metric tags live in config, not in code.
8. Structured-output benchmark cases must declare `response_format: json` when
   they use `required_json_keys` or `expected_json_values`. Validation rejects
   JSON-scored cases without that declaration, and it also rejects `json` mode
   on cases that have no JSON checks. The live harness passes declared JSON mode
   to Ollama as `format: "json"`; there is no permissive parser fallback.
9. `command_center.improvement.live_model_benchmark` is registered as a live
   model A/B harness. It requires explicit experiment parameters for role,
   suite, baseline model, candidate model, suite path, and local Ollama endpoint.
   It stores only hashes, booleans, latency, token-rate data when Ollama reports
   it, metrics, and equivalence metadata in Ledger artifacts; it does not retain
   raw prompts or model outputs.
10. `command_center.improvement.model_baselines` builds baseline-only experiments
   from the current incumbents in `configs/models.yaml`. It requires an explicit
   local endpoint, derives runtime budget from configured suite size, repetitions,
   timeout, and generation limits, records artifacts in the Ledger only when
   `--apply` is used, and never writes live benchmark experiments into
   `configs/improvement.yaml`.
11. `command_center.improvement.model_metric_audit` reruns live incumbent suites
    into an isolated audit Ledger/evidence directory and checks metric/sample
    math, expected sample counts, artifact presence, and redaction. It is for
    proving the benchmark machinery, not for promotion.
12. `command_center.improvement.model_candidate_audit` runs one isolated
    baseline/candidate/verifier audit for an explicit role and context. The
    evaluated context must be supplied directly or derived from current VRAM fit
    evidence with explicit `fit_ctx` and `gpu_budget_gb` inputs. The live harness
    passes that context to Ollama as `num_ctx` and stores it in the equivalence
    key.
13. The runner's comparison recommendation now requires at least one required
    non-safety metric to improve in the good direction before it can say
    `promote`. Passing by tie/no-regression returns `revise`, even when all hard
    gates pass.
14. The human wall is unchanged: scout and scan can propose only; benchmark
   runner can only move to awaiting verification; canary and promotion remain
   human-only.

Metric policy for open-weight model upgrades:

1. Use **open-weight** as the enforceable gate. "Open source" may be recorded as
   an additional governance note, but the routing lane requires locally runnable
   weights plus explicit provenance. A high public score without open-weight
   evidence is capability context only.
2. There is no single "best LLM" score. The board is role-specific:
   - triage/planner: structured-output validity, instruction adherence,
     tool-call correctness, escalation quality, and bounded task completion;
   - coder: issue-resolution rate, patch-apply success, test pass rate,
     edit-format compliance, compile/lint success, diff minimality, and
     rollback frequency;
   - local judge: labeled-case calibration, missed-defect rate, false-block
     rate, safety-missed-defect rate, and bias checks for position/verbosity;
   - long-context repo reader: effective context length, retrieval-at-length,
     multi-hop repo reasoning, latency growth by context, and failure shape
     (omission, contradiction, truncation, or tool misuse);
   - terminal agent: terminal task pass rate, command ordering, stderr/error
     handling, isolation behavior, and no secret exfiltration.
3. Every role uses the same metric hierarchy:
   - **Primary metrics** decide whether the role actually improves.
   - **Hard non-regression metrics** cover reliability, safety, structured
     output validity, data handling, and canary regressions.
   - **Supporting metrics** cover speed, VRAM headroom, context cost, token
     throughput, cold/warm load behavior, and concurrency stability.
4. Source trust is explicit:
   - benchmark-only source: useful for public capability context, not enough for
     eligibility or promotion;
   - provenance-only source: proves license/tag/digest/quant/local install, not
     superiority;
   - promotion-grade evidence: local role-specific A/B artifacts plus
     validation, evals, canary telemetry, independent verification, and human
     approval.
5. Public benchmarks are proxy evidence. Prefer continuously refreshed or
   contamination-aware suites for discovery and tracking. Static benchmark
   saturation or leakage is a reason to reduce trust, not to invent a score.
6. Promotion evidence is incumbent-relative. A candidate can become
   recommendable only by beating the current role incumbent on the same suite,
   machine, quant, context settings, and run protocol, with bootstrap/confidence
   evidence when stochasticity matters. Universal thresholds such as "promote if
   score > X" are not allowed in the model-upgrade lane.
7. Acceptable outcomes are **Pareto improvement** (better on at least one
   primary metric and not worse on hard non-regression metrics) or **contextual
   specialization** (better for a declared workload slice without unacceptable
   regressions elsewhere). Both remain proposed recommendations until the human
   promotion wall.
8. Local runtime evidence is first-class: time to first token, prompt processing
   throughput, steady-state output tokens/sec, cold-load and warm-load time,
   VRAM fit/headroom, OOM rate, context-window scaling cost, concurrency failure
   rate, and repeatability across restarts/quant variants.
9. Privacy rule: model benchmarks use synthetic or public tasks first; raw
   prompts and outputs are not retained by the live harness; artifacts store
   hashes, metric summaries, case ids, and equivalence metadata. External
   evaluation traffic or raw transcript retention requires explicit approval.
10. Risky coding, terminal, or repo-writing evals run isolated. A benchmark that
    executes generated code must use the repo's isolation path before its result
    can be treated as promotion-grade evidence.

Current evidence and boundary:

- The latest scout run used sources `aider-polyglot`, `local-ollama-tags`,
  `curated-openweight`, and `artificial-analysis`. `artificial-analysis` was
  skipped because `AA_API_KEY` was not intentionally set. The report contained
  five candidates and the machine feed contained one scored, provenance-resolved,
  role-bound record.
- The feed record is `devstral:24b` for the `coder` role only. It carries
  Apache-2.0 license evidence, Ollama tag `devstral:24b`, digest
  `9bd74193e93935e9d8564d88607b220a9d341c4a36b748cffcbd9ad4f47a9ca9`,
  quant `Q4_K_M`, parameter size `23.6B`, native context `131072`, SWE-bench
  Verified score `46.8`, Mistral source payload hash
  `ef183a2ddb914a564c5131de082569b477c648a2a5c7c77eade732ccf1a6bdf9`, and
  Hugging Face model-card payload hash
  `c84d253789fe8a9d9e4e2fdfaba9302e7723a49130c35ba55be5a5523556cdc1`.
- The daily scan consumed `generated/model-scout-feed.json` and drafted one
  `Proposed` model experiment. No candidate was moved to Canary, Verified, or
  Promoted.
- The same scout evidence reports `devstral:24b` as `NO @ 64k` on the current
  24 GB budget. The current fit-derived candidate audit records
  `devstral:24b max_ctx_fits=50257` and `qwen3-coder:30b
  max_ctx_fits=40806`; both are below the requested 64k context on the 24 GB
  budget. Therefore challenger A/B runs must either use a candidate that fits
  the declared evaluated context or explicitly declare a lower-context
  specialization before running.
- A real local Ollama incumbent-baseline pass has been recorded in the Ledger
  with one repetition for each production role. This is a pilot distribution,
  not enough for promotion-grade statistical evidence.

Incumbent baseline pilot, recorded from local Ollama:

| role | incumbent | task success | invalid response | median latency ms | note |
| --- | --- | ---: | ---: | ---: | --- |
| triage | `qwen3-coder:30b` | 0.000 | 0.000 | 2899.819 | Structured output was parseable, but all role metrics failed. |
| chat | `qwen3:30b` | 0.000 | 1.000 | 3469.380 | JSON/tool-call contract failed. |
| planner | `qwen3:30b` | 0.000 | 1.000 | 3518.636 | Structured plan contract failed. |
| coder | `qwen3-coder:30b` | 0.667 | 0.000 | 3688.417 | Passed core patch reasoning, failed no-fake/no-fallback/test-awareness tags. |
| local-judge | `qwen3:30b` | 0.500 | 0.500 | 3413.881 | One labeled judgment passed, one failed or malformed. |
| security-judge | `qwen3:30b` | 0.000 | 1.000 | 14014.187 | Security judgment contract failed. |
| architect-judge | `qwen3-coder:30b` | 1.000 | 0.000 | 3129.806 | Pilot passed the configured architecture cases. |

The baseline artifacts are stored under
`data/improvement/EXP-model-baseline-*/baseline-*/` as redacted stdout,
`metrics.json`, and `equivalence.json`. Artifact inspection found no raw prompt
or model-output markers from the benchmark fixtures.

Deep live audit evidence:

- `uv run python -m command_center.improvement.model_metric_audit --reps 2
  --base-url-env OLLAMA_BASE_URL` ran all seven production roles against local
  Ollama in an isolated audit Ledger. Every role produced the expected sample
  count; every metric value matched its stored sample vector; every audit
  artifact passed the raw-prompt/base-URL redaction checks.
- The two-repetition audit now runs JSON-scored cases through explicit Ollama
  JSON mode. This proved the protocol path but did not hide model failures:
  `chat` and `planner` still had invalid_response_rate `1.000`; `local-judge`
  and `security-judge` had invalid_response_rate `0.750`; `triage`, `coder`,
  and `architect-judge` had invalid_response_rate `0.000`.
- Role quality remains uneven under the real local models: `coder`
  task_success_rate `0.667`; `architect-judge` `1.000`; `security-judge`
  `0.250`; `local-judge` `0.250`; `triage`, `chat`, and `planner` `0.000`.
  This is benchmark evidence that the structured-output roles need prompt,
  protocol, or role-model work before their current pass rates can support any
  promotion decision.
- `devstral:24b` was then audited as a lower-context coder candidate with
  `qwen3-coder:30b` as incumbent. The evaluated context was derived from live
  fit evidence: `min(qwen3-coder:30b max_ctx_fits=40806, devstral:24b
  max_ctx_fits=50257) = 40806`; this value was passed to Ollama as `num_ctx`
  and stored in the equivalence key.
- The isolated coder candidate audit completed baseline, candidate, statistics,
  independent verifier, and artifact checks. It produced `recommendation=revise`
  with note `no required non-safety metric improved`: task_success_rate tied at
  `0.667`, invalid/unsafe rates tied at `0.000`, and Devstral did not improve
  the required non-safety metrics. Runtime evidence also favored the incumbent
  on this small suite: `tokens_per_second` about `51.3` for Devstral vs `160.0`
  for qwen3-coder, and median latency about `5890 ms` vs `3465 ms`.
- The independent verifier reproduced the candidate metrics and verified the
  candidate artifacts by hash. This is evidence that the harness works at the
  lower context, not evidence to canary or promote Devstral.

Remaining order (2026-06-20, after the watchlist/fit/DAG work above):

1. **Wire the three latency numbers.** Record TTFT / ITL / TTLT in
   `live_model_benchmark.measure` from Ollama's `/api/generate` timings (TTFT ≈
   `load_duration + prompt_eval_duration`; ITL ≈ `eval_duration / eval_count`; TTLT ≈
   `total_duration`) and add them as supporting metrics to each suite, updating the
   metric-audit expected sample counts. This is the highest-value methods deepening.
2. **Add EvalPlus as a code-execution coder runner** (new `EvalPlusHarness` in `HARNESSES`,
   shelling to the `evalplus` CLI against the Ollama OpenAI endpoint in an isolated step,
   parsing pass@1 into `MeasureResult`). Specify a sampling budget (subset + n) — full
   HumanEval+/MBPP+ is minutes–hours per 20–30B model on a 24 GB card. Then optional
   `lighteval` (generative tasks via the LiteLLM backend) as a general harness.
3. **Add a live registry/HF discovery source** so genuinely new models are found by name
   (recent open-weight releases filtered by license/task), feeding the watchlist's
   `pull_to_verify` tier. Propose-only: never auto-pull, never edit `models.yaml`.
4. **Make significance mandatory for model promotions** (`StatisticalPlan.require_significance`
   = true + pre-registered MDE) and grow each suite to ≥8 cases with decoupled per-tag scoring;
   today co-tagged metrics share one boolean and live suites are pilot-grade.
5. **Enforce `canary_required` at the promote transition** and add the Ollama model digest to
   the live-benchmark equivalence key so a silently re-pulled/re-quantized tag invalidates
   equivalence.
6. **pull_to_verify follow-through:** when a `pull_to_verify` candidate (e.g. gpt-oss-20b) is
   pulled, add a `curated-openweight` record (digest join) so it returns as a runnable
   `model_scout_candidate`; canary tool-call template behavior before any chat/planner use
   (the qwen3-coder XML-leak history applies to every new tool-using model).
7. **Frontier flagships stay track-as-context.** GLM-5.2 / Kimi K2 / DeepSeek-V3 are recorded
   for awareness only; reaching their quality means a hosted API, which is outside this
   local-only, no-provider-keys pipeline. Re-tier to `pull_to_verify` only if a genuinely
   fitting variant/quant appears (and prove it with the weights-only bound first).
8. Keep Mission 2 routing artifacts separate: model discovery can inform routing, but it does
   not replace the typed Ledger route-decision work.

Historical evidence from the earlier pilot (incumbent baselines, the Devstral lower-context
`revise` result, deep-audit latencies, specific digests/contexts) lives in the change log
(§14) and under `data/improvement/` and `generated/`; it is dated pilot evidence, not current
production guidance.

### 5.5 Whole-system validation prompt

Use [whole-system-validation-prompt.md](whole-system-validation-prompt.md) when
the question is broader than one model, one UI feature, or one external tool:
"can this entire pipeline keep improving itself, control AppFlowy safely, run
registered desktop repo work autonomously, route local models cheaply, notify me,
and prove it did not leak data?"

The attachment-driven reconciliation is recorded in
[autonomous-pipeline-gap-review-2026-06-16.md](autonomous-pipeline-gap-review-2026-06-16.md).
It keeps the current single-control-plane architecture and treats the proposal
as a hardening checklist, not a replacement stack.

The executable source of truth for the hardening checklist is now
`configs/autonomy.yaml`, validated by `AutonomyConfig`. It declares the
canonical event families, repo registration manifest, desktop target rights
manifest, forecast/evidence completion verifier policy, disabled no-op canaries,
the current telemetry decision, the GitHub App production-auth review, and the
external-runtime evaluation gate. The config separates completed contract work
from remaining ordered activation work, so blocked items cannot be treated as
ready.

The prompt ties together the current implementation, the external idea
evaluation prompt, the coded improvement loop, the AppFlowy/Growth OS surface,
repo-task isolation, channel notification, and the model-upgrade lane. It is
explicitly forecast-first: before each state-changing action, the agent records
the expected state change, allowed fields, expected events, privacy boundary, and
rollback plan; after the action it compares observed state to the forecast and
classifies any drift.

Required output from that prompt:

1. A single evidence package under `evaluation/system-validation/<run-id>/`.
2. Scenario proofs for contracts, local-only routing, self-improvement,
   AppFlowy kanban control, registered repo autonomy, notifications, memory and
   knowledge reuse, fail-closed behavior, and privacy.
3. A validation ladder ending in `cc validate`, mission dry-run, evals,
   improvement/kanban/channel/provider gates, ruff, pytest, and `git diff
   --check`, plus live checks only when services and credentials are actually
   available.
4. A final `PASS`, `PASS_WITH_BLOCKERS`, or `FAIL` report with evidence paths.
5. A `docs/MASTER.md` update recording what was proven, what remains, and the
   next ordered work.

The bounded observer-only runner is `uv run cc system-validation --run-id
<run-id>`. It reads validated config and git metadata, writes markdown evidence,
and intentionally does not call models, mutate repos, write AppFlowy cards,
capture screenshots, send notifications, or read `.env`.

Rules that prompt must preserve: no provider fallback, no fake metrics, no
hardcoded thresholds, no guessed prices/statuses/model fit, no raw secret or
private transcript retention, no agent self-approval, and no promotion without
validate, evals, canary telemetry, independent verification, and human approval.

Current verified state from the hardening pass:

1. Canonical event schemas, repo registration manifest, desktop target rights
   manifest, forecast/evidence completion verifier contract, disabled no-op
   canaries, telemetry decision, and external-runtime gate are in
   `configs/autonomy.yaml` and validate through `AutonomyConfig`.
2. `llm_station` now has a declared devcontainer execution manifest and
   `autonomous_edits_enabled: true` for registered L2 feature-branch-only repo
   work after GitHub auth, branch-protection, local branch mission, and live
   PR/check evidence gates passed. Merge, deploy, settings, secrets, branch
   deletion, and other L4 actions remain outside autonomous scope.
3. The GitHub App is installed on the selected `ghadfield32/llm_station`
   repository. `uv run cc github-app-verify` can authenticate the app, mint a
   short-lived installation token in memory, read the selected repo, and read
   check/status endpoints without printing or storing secrets.
4. The GitHub App `issues: read` permission is explicitly operator-approved in
   policy and repository-permission verification now passes. The owner/admin
   observer token is present and can read `ghadfield32/llm_station`.
   `uv run cc branch-protection-verify` now passes against the active
   `protect-main-command-center` ruleset. It verifies branch protection,
   deletion restriction, force-push blocking, linear history, required PR review,
   CODEOWNERS review, conversation resolution, empty bypass actors, and required
   checks `validate` plus `lint-test`. The app must not be granted
   Administration solely to inspect branch protection.
5. The local agent route has live evidence for parsed tool calls, memory-block
   recall, 14-turn recall, and fresh-conversation abstention through `chat`.
   The AppFlowy staging card now verifies as `In Progress`, and the desktop
   adapter readiness gate exists. Timeout/takeover policy is declared for the
   staging target, but numeric TTL and per-action timeout controls are still
   pending no-op canary telemetry. Live desktop actions remain blocked because
   the target is still disabled pending canary policy and loop-breaker evidence.
6. `uv run cc branch-mission` now proves the tiny branch-only repo loop:
   one local mission id, one local feature branch, one temporary worktree, one
   docs-only change, declared validation commands, and redacted evidence. It
   does not push, open a PR, merge, deploy, change settings, or touch secrets.
7. `uv run cc pr-check-verify --apply --poll-interval 15 --poll-timeout 1800`
   proved the remote PR/check/evidence loop with draft PR #6. The GitHub App
   created one feature branch through the GitHub Git API, opened one draft PR,
   and observed the configured required checks `validate` and `lint-test`
   complete successfully. It did not merge, deploy, change settings, change
   secrets, delete branches, or store the installation token in evidence. The
   integration PR #7 merged through squash auto-merge after CODEOWNERS approval;
   the obsolete draft proof PR #6 was closed without deleting its branch. PR #8
   proved that a user-authored PR cannot satisfy the owner approval gate for the
   same user. Replacement PR #9 was authored by the GitHub App, approved by
   `ghadfield32`, passed required checks, and merged through the protected branch
   wall without weakening branch protection.
8. `configs/autonomy.yaml` now records
   `desktop_timeout_and_human_takeover_policy_declared`, declares the
   human-takeover and screenshot artifact policies for
   `appflowy_browser_staging`, and deliberately leaves numeric TTL and
   per-action timeout controls unset until telemetry derives them. The target
   remains disabled. The read-only no-op canary sample plan is now declared,
   three no-op timing samples are recorded, and timing derivation now proposes
   provisional candidates from measured evidence only. These candidates are not
   production controls; the next ordered work is reviewing/accepting them,
   wiring accepted values through the adapter gate, and keeping desktop live
   actions disabled until the gate passes.

---

## 6. Stage by stage — the five pipelines

### 6.1 Risk tiers L0–L4 (one permission system for everything)

Every pipeline below reuses the same five tiers — there is no second
permission system to keep in sync.

| Tier | Means | Auto? |
|------|-------|-------|
| **L0** read-only | summarize, inspect, search, scan | yes |
| **L1** plan-only | architecture/migration/RCA plan | yes, after plan critic |
| **L2** local edits | branch/worktree/devcontainer edits | yes *into a branch*, then gated |
| **L3** external write | push branch, open PR, comment | **human approval** |
| **L4** dangerous | merge, deploy, publish, secrets, delete | **manual only, never automated** |

Full power inside the sandbox, narrow audited power outside it. L3/L4
*cannot* be configured to skip approval — the contract rejects it.

### 6.2 The request pipeline (new work) — 9 stages

Every request flows through the same stages, each with a model tier and named
judges (`configs/judges.yaml`; worked examples in
[request-routing-examples.md](request-routing-examples.md)):

| # | Stage | Tier | Judges (in order) | Escalates to |
|---|-------|------|-------------------|--------------|
| 1 | **Sort** | local | risk-judge | security-judge if unsure |
| 2 | **Plan** | mid | scope-judge → plan-critic | architect-judge if high-impact |
| 3 | **Docs** | mid | docs-truth, minimality | — |
| 4 | **Scaffold** | mid | diff, scope | — |
| 5 | **Implement** | mid | *static checks first*, then diff → secret → defensive-coding | security-judge on ambiguity |
| 6 | **Stuck-escalation** | heavy | stuck-detector → segment-fixer | frontier fixes the stuck segment, then continues |
| 7 | **Debug / log-scan** | local→heavy | log-scanner → root-cause-debugger | frontier root-causes real issues |
| 8 | **Pre-push** | heavy | security-skeptic + scope | **human approval** (L3/L4) |
| 9 | **Architecture** | heavy | architect-skeptic + cost | human |

Principles that hold at every stage:

- **Deterministic checks always run before LLM judges** — ruff, mypy/pyright,
  pytest, gitleaks, semgrep. Cheaper, deterministic, easier to debug.
- **Cheap-first, escalate only when forced.** Money is spent climbing tiers
  only when a cheaper judge can't clear the call. Stages 6–7 are the "don't
  just fall back to pass" guarantee: when a cheap model loops, swallows an
  exception, or papers over a problem, a stronger model takes that exact
  segment, fixes it correctly, and only then lets the pipeline continue.
- **Cross-provider review**: whatever family *wrote* the code, a *different*
  family reviews it at the pre-push gate.
- The **defensive-coding judge** blocks bloat — swallowed exceptions,
  redundant guards, hardcoded fallbacks where data-driven values belong, dead
  flags, fake retries, out-of-scope rewrites — while allowing real boundary
  validation and clear error propagation.
- **Standards are data.** `configs/standards.yaml` is the single source for
  operating values; `make repo-install REPO=… PROFILE=python_ml_pipeline`
  renders the same rules into each repo's `CLAUDE.md`/`AGENTS.md`, and Judge
  Gate reads the same YAML. Edit one file, validate once, reinstall. The
  `python_ml_pipeline` profile (used by `betts_basketball` per
  `configs/targets.yaml`) encodes that repo's enforced operating contract:
  medallion stages per its `PIPELINE_STANDARDS_TEMPLATE.md` (module tree +
  stage registry at the top of every pipeline doc), temporal-leakage safety,
  R2-as-shared-production-database discipline (validate→dry-run→upload→verify;
  never delete `upload.lock` — wait out the TTL), the desktop-4090-writer /
  laptop-5080-dev-lane fleet split, multi-session git rules (exact-path
  staging, never `git add -A`), the uv dependency standard
  (`uv pip install` → pin range in `pyproject.toml` → `uv sync` → commit), and
  serving standards from its `UNIFIED_SERVING_GUIDE.md`.

The mission lifecycle that wraps stages 1–9: intake → Ledger mission ID →
triage → plan + critique → **one lease** on (repo, branch) → executor edits in
a devcontainer → static checks → pre-commit judge array → commit → pre-push
cross-provider skeptic → human approval (L3) → push/PR → required CI +
CODEOWNERS → human merge. Anytime: the Ledger UI shows the full audit trail
and can **kill** a runaway mission.

### 6.3 The kanban intake pipeline (cards → missions)

Growth OS and the Command Center are joined by a bridge, **not merged into one
authority boundary**. A card becomes work only after the bridge opens a Ledger
mission.

```text
Backlog → Ready (human staging) → Approved → Ledger mission → In Progress → Done/Rejected
```

Stage by stage:

1. **Draft** — any channel (board UI, chat.bat, Claude via MCP, Discord) can
   draft a card via `actions.add_mission_card`. Agent-created cards land in
   **Backlog only** and carry a `CardKey`.
2. **Approve** — a human drags the card to **Approved**. Agents structurally
   cannot do this: `actions.set_status` refuses Approved on every agent
   surface; the bridge applies `ready_statuses: [Approved]` only.
3. **Dispatch** — `scripts/kanban_bridge.py --apply` (scheduled every 15 min
   via a *user-run* schtasks one-liner; agent-created persistence is
   deliberately blocked) opens a Ledger mission per approved card. Imported
   hashes land in `generated/kanban-imported.json` so reruns never reopen a
   card.
4. **Writeback** — the bridge stamps `MissionID`, `Status=In Progress`, and
   `LastSync` back onto CardKey cards. Executors post events to the Ledger
   (`POST /mission/{id}/event`); `actions.mission_status(id)` returns status +
   the last 5 events from any channel; the morning brief's **Mission worklog**
   lists every bridged mission with its current Ledger state.
5. **Gates still apply** — section risk ceilings (`Learning` L1, `DAGs` and
   `Betts Basketball` L2) cap what a card may request; L3/L4 still hold at the
   Ledger; repo execution still needs one branch / worktree / devcontainer /
   lease; GitHub push/PR stays behind the wall.

Proven live: mission T-b5f2e70f dispatched with writeback; T-c8e1d7d6 held at
the L4 wall and never ran.

### 6.4 The proactive lane (already-shipped work)

Defined in `configs/proactive.yaml`, validated by `ProactiveConfig`, run by
`services/proactive_runner` (a thin scheduler invoked by host cron / systemd:
`docker compose run --rm proactive-runner`) or by a low-privilege Airflow wrapper.
Three lanes:

- **Runtime health** — DAG run health, data freshness, data quality
  (schema/nulls/rows/drift), service/pipeline perf.
- **Repo stewardship** — structure, test quality, docs freshness, dead code,
  dependency drift, and defensive-coding *debt* (the same things the judge
  blocks at commit time, swept for after the fact).
- **Self-improvement scan** — a daily observer-only pipeline
  (`scan → classify_and_dedup → score_and_rank → draft_proposals → emit`) across nine
  pillars: automation, structure, updated-metrics, code quality, standards, data handling,
  net-new ideas, reliability/observability, and cost. It drafts `Proposed` Backlog cards +
  one report and **nothing else** — it cannot approve, verify, promote, canary, merge, deploy,
  rotate secrets, or execute experiments (the `ObserverCharter` makes that structural). Ranking
  is **data-derived** — every knob lives in `configs/discovery.yaml`, and a learned `P(accept)`
  model (`acceptance.py`) takes over from the ICE/RICE/WSJF formula only once it beats it on
  held-out card outcomes. A blocking `make improvement-scan-validate` gate guards it. Reaches you
  three ways: **AppFlowy Kanban** (where you act, per-pillar swimlanes), an **email digest** (SMTP,
  Start-Here top-3 + new-since-yesterday + failed sources), and a **chat ping**. Implemented as the
  Airflow DAG `dags/self_improvement_daily.py` + the `improvement scan` CLI; full design + as-built
  reference in [daily-self-improvement-dag.md](daily-self-improvement-dag.md) and the project tracker
  [backend/projects/SELF_IMPROVEMENT_PIPELINE.md](backend/projects/SELF_IMPROVEMENT_PIPELINE.md).

Stage by stage:

1. **Scheduled trigger** → collect evidence (logs, freshness, checks, tree).
   Deterministic tools run first (Airflow/Dagster asset checks, Great
   Expectations, Evidently/whylogs; ruff/semgrep/pytest for repos) — LLMs only
   judge what the tools surface.
2. **Local scanner (cheap)** classifies: healthy → benign Ledger event;
   unclear → mid-tier verifier; real problem → step 3.
3. **Open an RCA mission** — the check's *strongest autonomous action*. It can
   never edit, push, merge, or refactor on its own; the contract makes the
   unsafe configs fail validation (L3/L4 from a schedule, `auto_fix`,
   stewardship above L2 — all rejected).
4. **RCA loop** — local log-scanner filters noise → cross-provider
   root-cause-debugger checks lineage, data quality, and recent code/config
   changes for the *actual cause* → writes a fix plan → any patch rejoins the
   normal pipeline (lease → checks → judges → human approval → PR).
5. **Post-watch** — 1h (immediate regressions), 24h (freshness/outputs/cost),
   7d (drift/recurring warnings). RCA report logged to the Ledger.

Skill/prompt updates follow the same rule: RCA output may *draft* a standards,
skill, or prompt change, but automated skill updates are capped at L2 gated
edits. Self-rewriting outside the pipeline is intentionally not supported.

The **usage digest** (`make usage-digest`) closes the feedback loop: weekly
spend/call/escalation/block-rate summary from LiteLLM virtual keys + the
Ledger, written to `generated/usage-digest.md`; budget/model/standard changes
it suggests become gated missions like anything else.

### 6.5 The model-update pipeline (no auto-promotion)

Models are data in `configs/models.yaml` (local-only: every role must use
`provider: ollama`, `local: true`).

```
1. make model-scout      → generated/model-scout-report.md + generated/model-scout-feed.json
2. make improvement-scan FEEDS=generated/model-scout-feed.json
3. Confirm the role's incumbent baseline distribution exists in Ledger; run the
   role suite first if it does not:
   uv run python -m command_center.improvement.model_baselines --reps <derived> --base-url-env OLLAMA_BASE_URL --apply
4. Audit the benchmark machinery before trusting model quality claims:
   uv run python -m command_center.improvement.model_metric_audit --reps <pilot> --base-url-env OLLAMA_BASE_URL
5. Confirm candidate machine fit at the declared evaluated context. If the
   candidate does not fit, either reject it for that role/context or declare a
   lower-context specialization before testing.
6. For an audit-only lower-context candidate check, use an explicit context or
   derive one from fit evidence:
   uv run python -m command_center.improvement.model_candidate_audit --role <role> --baseline-model <incumbent> --candidate-model <candidate> --reps <pilot> --base-url-env OLLAMA_BASE_URL --derive-context-from-fit --fit-ctx <ctx> --gpu-budget-gb <gb>
7. Register a bounded live model benchmark experiment if the scan drafts a
   scored open-weight candidate
8. Run baseline → candidate → independent verification; artifacts land in Ledger
9. Edit configs/models.yaml with a verified local Ollama candidate
10. make validate && make evals
11. make models           → render + pull local tags + restart LiteLLM
12. make models-canary ROLE=… MODEL=ollama_chat/<tag>   → small traffic slice
13. make live-smoke       → real local replies
14. compare task success · unsafe output · invalid response · runtime metrics · canary telemetry
15. make models-promote ROLE=…   or   make models-rollback ROLE=…
```

Current local picks: `qwen3-coder:30b` · `qwen3:30b` · `devstral:24b`.
The contract rejects `scout.propose_only: false` and any provider route, so
"swap to the leaderboard top" is structurally impossible.

### 6.6 The LinkedIn content pipeline (Claude-Code-authored → human-gated → shipped)

A content operation for two LinkedIn accounts — **geoffhadfield32** (personal
profile) and **World Model Sports LLC** (company Page) — that lives entirely
inside the existing AppFlowy stack and ships through LinkedIn's **official**
Posts API (no scraper, no third-party scheduler, content never leaves the box).
Validated by `ContentConfig` (`configs/content.yaml`).

One ordered, single-direction pipeline (idempotent by a stable per-row `Key`):

```
1. Source assembly   real artifacts only — repo commits, library/papers, project
                     state. Each post records its derivation in the Source column.
2. Draft (Claude Code)  authors posts grounded in step 1; upserts as "In Queue".
                        No local LLM, no autonomous loop — Claude Code is the only
                        thing that writes content (per the user's rule).
3. Review + approve (human)  edit text, set ScheduledFor, drag In Queue → In
                             Progress. The drag IS the approval (same human-gate
                             philosophy as the kanban bridge; the agent cannot
                             self-approve). This gate is also the data-leakage
                             control — nothing private reaches a public post
                             without a human moving it.
4. Publish (mechanical)  `cc linkedin-publish --apply` (q15min via schtasks) posts
                         every In Progress row whose ScheduledFor <= now and PostURN
                         is empty, using the right author URN (member vs organization),
                         then stamps PostURN + PublishedAt + Status=Completed back on
                         the same row. No LLM in this path.
```

Three board columns, exactly as asked: **In Queue → In Progress → Completed**
(boards `geoffhadfield32_content`, `world_model_sports_content`, created from the
`content_template` in `growth-os/config/schema.yaml` by `new_content_board.py`).

Discipline (same standards as the rest of the system):

- **No fake values / no silent fallback** — a publish failure leaves the row In
  Progress and retries; a media/non-text row is refused loudly (image posting is
  not wired yet) rather than dropped to text; a row is never marked Completed
  without a real PostURN from LinkedIn.
- **Temporal safety** — a row publishes only when `ScheduledFor <= now`; future
  rows are untouched.
- **No double-post** — a durable `PublishLedger` (`generated/linkedin-published.json`,
  gitignored, same role as the bridge's `kanban-imported.json`) records each Key
  PUBLISHING → PUBLISHED around the POST. A post whose AppFlowy writeback failed is
  *reconciled* on the next run, never re-sent; an ambiguous send (timeout) becomes
  `RECONCILE_REQUIRED` and is surfaced, never auto-retried. A single-process lock
  (`generated/linkedin-publish.lock`, OS advisory, no stale-timeout to guess) stops
  two scheduler runs touching the same row. Only `None`/`FAILED` (a definitive
  LinkedIn rejection — no post created) are eligible to (re)publish.
- **No data leakage** — official API direct from this host; secrets (incl. the
  OAuth token store) live only in gitignored `.env`/`generated/`, named-not-stored
  in `content.yaml`; the human gate bounds what ships.
- **Data-derived + least privilege** — endpoints/scopes/version/statuses are
  config, not literals; the LinkedIn-Version header has no code default (so the
  live value is explicit and must be checked vs LinkedIn's current "Latest" — it
  sunsets ~12 months after release); scopes are posting-only (no email/read).

**One publishing path (no external MCP).** `command_center.cli.linkedin_publish`
is the *only* component allowed to publish. `.mcp.json` deliberately registers **no
LinkedIn posting MCP**: an external one (e.g. `souravdasbiswas/linkedin-mcp-server`)
would be a second publish route that can post personal content *without* completing
the In Queue → In Progress board lifecycle, plus a second OAuth/token store — both
rejected. The `stickerdaniel` scraper cannot post at all (read-only, ban risk).
Claude Code needs no MCP to run the publisher (it edits the queue and invokes the
CLI); if conversational control is wanted later, wrap *our own* publisher in a thin
MCP — never add an independent publisher.

**Setup is a runbook + a self-check.** The ordered go-live steps are in
[linkedin-setup.md](linkedin-setup.md); `cc linkedin-publish --preflight` reads the
real local state (config, boards, env-key presence, token validity — no secrets
printed) and names the single next action, so the runbook is self-verifying.

#### 6.6.1 Content usability lane (preview · find-by-intent · routing)

Make the system **easier before making it bigger**. Three guarantees, all local
and offline, none of which makes a live paid call (`cc content-preview`,
`cc content-find` / `cc reference`, `content/llm_client.py`).

**Content usability — find by intent, not exact names.** User-facing content
commands resolve posts, libraries, kanban boards, references, and prior drafts
through a reference resolver that combines aliases, normalized text, fuzzy
matching (RapidFuzz), keyword search (BM25), and local embeddings
(`nomic-embed-text`), returning the top 3 when a query is ambiguous. Exact-name
matching is allowed only as the first fast path — **it is never the only path**.
The semantic tier degrades to lexical (with a note) if the local embedder is
down; it is never a silent failure. Seeded by `configs/content_reference.yaml`.

**LinkedIn preview contract.** Generated LinkedIn content must be rendered before
publishing in three forms: (1) copy-ready text, (2) a terminal markdown preview,
(3) a self-contained LinkedIn-styled HTML preview (offline, inline CSS). The
preview must show author context, body, line breaks, hashtags, media/link cards,
desktop/mobile "…see more" cutoffs, and validation warnings — over-length (a hard
fail), weak hook, missing CTA, and markdown LinkedIn won't preserve.

**Content model routing.** The content engine is local-first. Ollama remains the
default execution path; `ContentLLMClient` is the adapter seam (LiteLLM local,
direct Ollama, dry-run router, test). Paid routes (OpenRouter/Z.ai — GLM-4.7-Flash,
GLM-5, GLM-5.2, Kimi) are config **metadata** for the dry-run cost estimator only;
a live paid call stays disabled unless the budget, redaction, and explicit-egress
gates pass (operator-gated, like the model-eval frontier-router lane). Large
hosted models such as GLM-5.2 are **escalation** models, not default post
formatters.

---

## 7. Environments and isolation

Defined in `configs/environments.yaml`, validated by `EnvironmentsConfig`.
One environment per activity:

| Environment | Kind | Host | Persistent | GPU | Secrets |
|---|---|---|---|---|---|
| cc-control-vps | control_plane | VPS | yes | no | LiteLLM master, virtual keys, ledger secret — **no provider API keys** |
| cc-worker-4090 | worker | 4090 | yes | yes | GITHUB_TOKEN (minimal) |
| **cc-repo-task** | repo_task | 4090 | **no** | no | **none** |
| cc-judge | judge | VPS | yes | no | judge virtual key |
| cc-relay | relay | mini-PC | yes | no | none |

**The isolation invariant (enforced by contract):** one mission → one ledger
ID → one branch → one git worktree → one devcontainer → one lease. The Ledger's
unique index on (repo, branch) means two agents *physically cannot* lease the
same checkout. Any `repo_task` that is persistent or holds secrets fails
validation — that's how per-task isolation stays real rather than aspirational.

Human access: VS Code Remote Tunnel from the 5080 (or `vscode.dev`, or a
borrowed machine) into the *same* worktree the agent edits. The agent drives
the terminal/filesystem; you drive VS Code, the dashboards (Ledger 8091,
LiteLLM 4000/ui, Uptime Kuma 3001 — all over Tailscale), and GitHub.
Fallback when the 4090 is off: GitHub Codespaces.

---

## 8. The hard wall — GitHub

The LLM judges *reduce* risk; GitHub *prevents* the mistakes that can't be
undone.

The bot **may**: read repo, create branch, push *feature* branch, open/update
PR, comment, read CI status.
The bot **may not**: push main, merge, force-push, delete branches, change
settings/protections, administer secrets, deploy, publish, bypass checks.

The enforcement stack (full commands in [github-safety.md](github-safety.md)):

1. **Branch protection on main** — required status checks are the actual
   workflow jobs in this repo (`validate` and `lint-test` from
   `.github/workflows/contracts.yml`), not invented names. The wall also
   requires pull-request review, CODEOWNERS review, conversation resolution,
   linear history, and no force-push/deletes. Keep the owner/admin emergency
   path available unless a later policy deliberately changes that; the agent
   never holds an admin token.
2. **Scoped repo identity** — production autonomy uses the
    `llm-station-command-center` GitHub App, not a broad PAT. The app is
    installed on `ghadfield32/llm_station` and can mint an in-memory installation
    token. The operator-approved `issues: read` permission is now recorded in
    policy, repository permission verification passes, branch protection is
    verified through the owner/admin observer path, and token storage/rotation
    policy is finalized. The tiny branch-only mission now proves local
    branch/worktree/docs-only validation evidence. The live PR/check verifier
    now proves the remote branch -> draft PR -> required-check evidence loop
    through PR #6. Repo autonomy is enabled only for registered
    feature-branch-only L2 work; human review/CODEOWNERS and branch protection
    remain the merge wall. Devcontainer runtime execution remains
    manifest-verified, not invoked by the branch-only smoke. Fine-grained PATs
    remain pilot-only.
3. **Deploy = separate human-gated environment** — `production` environment
   with a required reviewer and prevent-self-review; the agent never gets its
   secrets.
4. **In-sandbox command policy** — allow git status/diff/log, grep/find,
   pytest/mypy/ruff, branch + edits, logged dep installs; push only after
   `scripts/pre_push_gate.sh` exits 0; deny reading `.env`/keys, sudo,
   `rm -rf`, `curl|bash`, force push, merge.

Current GitHub wall state: `uv run cc branch-protection-verify` passes using
the active `protect-main-command-center` ruleset. The verified wall has:

- Require a pull request before merging.
- Require 1 approval.
- Require status checks to pass before merging, selecting the real `validate`
  and `lint-test` checks after GitHub has observed them.
- Require conversation resolution before merging.
- Require linear history.
- Do not allow force pushes.
- Do not allow deletions.

The owner/admin observer token exists only to prove this wall from GitHub's
read APIs. It is not the runtime agent credential, and adding it to `.env` does
not make repo autonomy ready unless `uv run cc branch-protection-verify` passes.
Now that the verifier passes, remove or let the temporary observer token expire
after any final audit rerun that needs it.

---

## 9. Build phases — stage-by-stage setup

```
Phase 1   VPS control plane     → the brain runs without the 4090
Phase 2   4090 worker           → isolated worktrees, local models, VS Code tunnel
Phase 3   GitHub hardening      → protected main, CI, CODEOWNERS, App over PAT
Phase 3.5 proactive ops lane    → DAG/data checks, repo stewardship, RCA loop
Phase 4   workspace expansion   → Coder / OpenHands / Codespaces / WebUI / Mirage (all optional)
Phase 5   relay                 → mini-PC/Pi: Wake-on-LAN, watchdog, backup mirror (optional)
```

Phases 1–3.5 are the real system. Phases 4–5 are optional, added only when a
need is actually hit.

### Phase 0 — what you need first

- A VPS (Hetzner/DigitalOcean/Hostinger, 2 vCPU / 4 GB), Ubuntu 24.04.
- A Tailscale account (free Personal tier) on every machine.
- A GitHub fine-grained PAT scoped as in §8 (App later).
- **No provider API keys** — do not create or store OpenAI/Anthropic/OpenRouter
  keys for this architecture; validation forbids them.
- A verified **LiteLLM image digest** (the current checkout is already pinned;
  on upgrade: pull the GHCR image, inspect the immutable digest, replace the
  pin in `docker-compose.yml` + `Makefile`, revalidate + live-smoke). Never
  pip-install LiteLLM.

### Phase 1 — control plane (first-boot sequence)

```bash
# on the VPS, after Docker + Tailscale are up (Windows: .\scripts\cc.ps1 <target>)
git clone <this repo> && cd <repo>
make setup          # deps, .env, validate, build images
# edit .env: confirm OLLAMA_API_BASE; do NOT add provider API keys
make verify-base    # FAILS on placeholder digest / missing first-boot secrets
make bootstrap      # FIRST BOOT: litellm + db + ledger only, waits for health
make keys           # mints the 2 virtual keys → paste BOTH into .env
make verify         # full runtime prerequisites, including the virtual keys
make up             # verify → render → full stack
make health         # all OK?
make mission-dryrun # fake L0–L4 missions through gates+judges, no model calls
make live-smoke     # real local replies through Ollama + LiteLLM aliases
```

Why `bootstrap` before `up`: clients read their LiteLLM key from `.env`, but
that key doesn't exist until LiteLLM is up and `make keys` mints it.
`bootstrap` starts just the infra so keys can be minted first.

The live smoke proves: Ollama direct reply · LiteLLM `triage`/`planner`/
`local-judge` aliases · `gpt-*` and `claude-*` names **denied** through
LiteLLM · executor shell has no provider keys · forbidden-providers check
passes. No skip-Ollama path exists — Ollama is required; calls fail closed.

**Done when:** live smoke passes; a channel can open a Ledger mission and an
L3 request shows `awaiting_approval`.

### Phase 2 — 4090 worker + isolation + judges

1. Tailscale on the 4090; set the VPS `.env`
   `OLLAMA_API_BASE=http://<4090-tailscale-ip>:11434`; re-run `make models`
   then `make live-smoke` from the VPS.
2. `code tunnel` on the 4090; attach from the 5080 / `vscode.dev` / phone.
3. Executor CLIs: install + authenticate both — Claude Code (`claude`, then
   `/login` and `/status`) and Codex (`codex login status` → "Logged in using
   ChatGPT"). Verify the shell has no `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`
   at process, user, and machine scope (live smoke checks this).
4. Ollama install, `make models` pulls the three local tags; raise `num_ctx`
   ≥ 64k and set `OLLAMA_NUM_PARALLEL` / `OLLAMA_KEEP_ALIVE=-1`.
5. Leases: every mission acquires one via `POST /mission/{id}/lease`.
6. Per-repo: `make repo-install REPO=/path PROFILE=python_ml_pipeline` —
   installs pre-commit/pre-push hooks, CI, CODEOWNERS, devcontainer, and
   renders `CLAUDE.md`/`AGENTS.md` from `configs/standards.yaml`.

**Done when:** an L2 mission leases a branch, edits in an isolated worktree,
pre-commit judges pass/block correctly, and the cross-provider pre-push
skeptic reviews before a PR is allowed.

### Phase 3 — GitHub hardening

Work through §8 / [github-safety.md](github-safety.md). **Done when:** the
repo itself blocks merges without passing checks + your review, even if the
agent misbehaves.

### Phase 3.5 — proactive ops lane

`make proactive-validate` → `make proactive-smoke` → schedule
`docker compose run --rm proactive-runner` via cron/systemd → wire the real
evidence collectors per target (Airflow API, asset checks, ruff/semgrep).

### Phase 4 — optional expansion

Coder (managed workspaces) · OpenHands (issue→PR batches, behind the same
gates) · Codespaces fallback · the AppFlowy/agent **WebUI** behind Tailscale +
password, governed by `configs/ui.yaml` (single-container mode; its
shell-approval card is a convenience, never the policy layer) · **Mirage VFS**
only as a read-only data experiment on a throwaway branch (v0.0.1, ~59 stars —
watch-list, not core; see [optional-mirage.md](optional-mirage.md)) · skip
`local-ai-server` (Mac/MLX-only; LiteLLM already does the job).

### Phase 5 — home relay (optional)

Mini-PC preferred over a Pi: Wake-on-LAN for the 4090, watchdog, Tailscale
subnet router, local backup mirror. Only after Phases 1–2 are stable.

### Current status vs the phases (2026-06-12)

Done locally: validation green · digest pinned · keys minted · health passing ·
live smoke passing · models installed · bridge live and scheduled q15min ·
Discord gateway built (needs token for Phase-2-of-autonomy push
notifications) · Growth OS selftest 22/22.
Remaining: rent + provision the VPS · Tailscale split (4090 `OLLAMA_API_BASE`
from the VPS) · GitHub PAT + branch protection + bot-can't-merge verification ·
Claude Code interactive `/login` · the one-time AppFlowy UI clicks REST can't
do (per-view filters/sorts, delete blank starter rows) · Linux migration when
the prod box revives. Full checklist: [STATUS.md](STATUS.md) + [SETUP-FROM-SCRATCH.md](SETUP-FROM-SCRATCH.md) §12.

**LinkedIn content pipeline (2026-06-13) — see §6.6.**
Done by Claude Code (built + verified live against AppFlowy): both content boards
created with the 3-column kanban (`geoffhadfield32_content`,
`world_model_sports_content`) · `ContentConfig` + `configs/content.yaml` wired into
`cc validate` · `command_center.linkedin` client + `cc linkedin-publish`
(dry-run/--apply/--login) · durable anti-double-post ledger + single-process lock
(6 safety tests) · 30 days × 2 accounts (60 real, source-attributed drafts) seeded
as **In Queue** · publisher gate proven (0 due while nothing is approved) ·
`.mcp.json` keeps a single publish path (no external posting MCP).
Remaining is all yours (I cannot fake credentials). Full ordered runbook:
[linkedin-setup.md](linkedin-setup.md); `cc linkedin-publish --preflight` tells you
the next step at any time. Summary, in order — **personal and the WMS Page are
separate permission + live-smoke gates; install the scheduler LAST**:

1. Create the LinkedIn Developer app (own it with the WMS Page + verify it; redirect
   `http://localhost:3000/callback`; products: OpenID + Share on LinkedIn, and
   *Community Management API* for the Page — LinkedIn-reviewed). `LINKEDIN_*` → `.env`.
2. Confirm `configs/content.yaml` `linkedin.version` is LinkedIn's current Latest
   (202605 as of 2026-06-13; sunsets ~12 mo) → `cc validate`.
3. `cc linkedin-publish --login` (personal scopes). ~60-day token; expiry printed each run.
4. Approve ONE personal draft (In Queue → In Progress, due now) → `--account
   geoffhadfield32_content --apply`; confirm live + Completed + PostURN.
5. After Community Management approval: Page URN → `LINKEDIN_WMS_ORG_URN`,
   `--login --include-org`, repeat the smoke for `world_model_sports_content`.
6. One-time AppFlowy UI: each Board view **Group by → Status**; delete the 3 blank
   starter rows per grid.
7. ONLY after both smokes pass: schedule `linkedin-publish --apply` (Task Scheduler,
   q15min, run-if-logged-out + restart-on-fail + rotating log; see the runbook).

---

## 10. The operator interface

Everything routes through the `Makefile` (Linux/VPS) or `scripts\cc.ps1`
(Windows-native equivalent: `.\scripts\cc.ps1 help`).

```
# setup & lifecycle
make setup              # deps, .env, validate, build images
make verify-base        # FAILS on placeholder digest / missing first-boot secrets
make verify             # FAILS on placeholder digest / missing runtime keys
make bootstrap          # FIRST BOOT: litellm+db+ledger only, so keys can be minted
make keys               # mint the 2 virtual keys
make up / down / health / logs

# config (the source of truth)
make validate           # all configs through Pydantic — nothing runs until this passes
make standards-validate # renderable standards profiles for Claude/Codex/Judge Gate
make schema             # regenerate JSON Schema for editor autocomplete
make render             # configs → generated/litellm-config.yaml
make impact             # blast radius of your git diff (breakage.yaml)

# models
make model-scout        # discovery report + scan feed, never auto-promotes
make improvement-scan FEEDS=generated/model-scout-feed.json  # Proposed cards only
make models             # render + pull local tags + restart
make models-canary ROLE=… MODEL=…  /  models-promote ROLE=…  /  models-rollback ROLE=…
make evals              # routing/judge regression suite

# kanban / growth-os bridge
make kanban-validate    # contract-check configs/kanban.yaml
make kanban-bridge      # preview mission drafts (dry-run)
make kanban-bridge APPLY=1            # open Ledger missions from Approved cards

# proactive lane
make proactive-validate / proactive-smoke
make usage-digest       # spend by role/key + mission/judge summary (usage-report = alias)

# dry-runs & safety
make mission-dryrun     # fake L0–L4 missions through gates+judges, no model calls
make env-smoke          # environment isolation invariants
make live-smoke         # real local model replies + forbidden-provider checks
make repo-install REPO=… PROFILE=python_ml_pipeline
make backup / restore-drill
```

The breakage map ([breakage-map.md](breakage-map.md), `configs/breakage.yaml`)
answers "what breaks when I change X" — `make impact` reads your git diff and
prints the blast radius plus the checks to run before trusting the change.
The full maintenance surface is: **edit a `configs/*.yaml`, run
`make validate`, then the relevant target.**

---

## 11. Module tree and purposes

### 11.1 Command Center (`llm_station/`)

```
llm_station/
├── Makefile                    the only operator interface (Linux/VPS)
├── docker-compose.yml          control-plane stack; LiteLLM pinned by immutable digest
├── pyproject.toml / uv.lock    Python env (uv-managed; new deps via `uv add`)
├── .env / .env.example         secrets — never in YAML, never committed, no provider keys
├── .mcp.json                   project MCP servers for Claude Code (empty by design — single LinkedIn publish path is cc linkedin-publish, no external posting MCP)
│
├── configs/                    YAML SOURCE OF TRUTH (you edit these; see §2 table)
│   ├── models.yaml             role → ranked local model candidates (ollama-only)
│   ├── judges.yaml             per-stage judge arrays, cross-provider pairing, budgets
│   ├── gates.yaml              L0–L4 risk tiers + approval policy
│   ├── environments.yaml       one environment per activity + isolation invariants
│   ├── standards.yaml          operating standards → CLAUDE.md/AGENTS.md + Judge Gate
│   ├── breakage.yaml           what-breaks-when map (drives `make impact`)
│   ├── proactive.yaml          scheduled checks, on_fail policy, RCA risk caps, self-improvement scan
│   ├── targets.yaml            watch inventory: repos, DAGs, data assets, services
│   ├── tools.yaml              tool permissions the judges can cite
│   ├── evals.yaml              routing/judge regression suite (model-promotion gate)
│   ├── kanban.yaml             bridge dispatch contract: sections, ceilings, ready statuses
│   ├── content.yaml            LinkedIn content pipeline: accounts, statuses, official-API endpoints (ContentConfig)
│   ├── ui.yaml                 WebUI safety defaults (ledger-governed external writes)
│   ├── channels.yaml           chat transports → transport + model alias (tokens stay in .env)
│   ├── improvement.yaml        experiment definitions (worked set) + improvement-targets.yaml (per-target refs)
│   ├── discovery.yaml          daily-scan knobs: ranking/triage/code-health/acceptance (DiscoveryConfig)
│   └── agent_surface.yaml      agent-kanban knobs: re-injection cadence/size, fuzzy addressing, tuning (AgentSurfaceConfig)
│
├── src/command_center/         INSTALLABLE PACKAGE (uv pip install -e .; run via `make`/`python -m`)
│   ├── schemas/                PYDANTIC CONTRACTS that validate the YAML
│   │   ├── base.py             shared primitives / strict-mode base models
│   │   └── contracts.py        one contract per config (ModelRegistry … ChannelsConfig)
│   ├── registry/
│   │   ├── render.py           validate → generated/litellm-config.yaml
│   │   └── model_scout.py      local tags + leaderboards → ranked report (never promotes)
│   ├── cli/                    operator commands (`python -m command_center.cli.<name>`)
│   │   ├── validate_config.py  `make validate` engine (Pydantic per-file)
│   │   ├── check_cross_refs.py cross-file linter (incl. channel.model → models.yaml role)
│   │   ├── check_forbidden_providers.py  enforces the no-provider-keys boundary
│   │   ├── verify_env.py / init_env.py   digest + secret verification / .env scaffold
│   │   ├── render_standards.py standards.yaml → CLAUDE.md / AGENTS.md profiles
│   │   ├── render_json_schema.py  contracts → generated/json-schema/
│   │   ├── impact.py           git diff × breakage.yaml → blast radius
│   │   ├── run_evals.py        routing/judge regression suite
│   │   ├── smoke_mission.py    `make mission-dryrun` (fake L0–L4, no model calls)
│   │   ├── usage_digest.py     LiteLLM spend + Ledger summary → usage-digest.md
│   │   ├── kanban_bridge.py    Approved cards → Ledger missions (+CardKey writeback)
│   │   ├── linkedin_publish.py In Progress + due content rows → LinkedIn Posts API (--preflight/--login/--apply; ledger-dedup; stamps Completed)
│   │   ├── improvement.py      improvement-loop + daily-scan operator CLI (scan, scan-validate, …)
│   │   ├── knowledge.py        OKF knowledge-bundle CLI (generate, validate)
│   │   └── kanban_surface.py   agent-kanban digest + N/N gate (make kanban-digest / kanban-surface-validate)
│   ├── channels/               CHAT TRANSPORTS — one authority, many surfaces
│   │   ├── core.py             transport-agnostic GatewayCore.run_turn() (LiteLLM tool loop; re-injects board_state)
│   │   ├── board_state.py      harness-owned live board re-injected each turn (Cline focus-chain; fail-loud)
│   │   ├── discord.py · slack.py · telegram.py · whatsapp.py   thin per-platform adapters
│   │   └── __main__.py         runner: configs/channels.yaml → launch enabled adapters
│   ├── linkedin/               OFFICIAL LinkedIn API (no scraping): client.py (OAuth + text post member/org) + ledger.py (durable anti-double-post + process lock)
│   ├── kanban/                 AGENT KANBAN SURFACE — observability + data-derived tuning (reads the agent-call log spine)
│   │   ├── metrics.py          real metrics from _export/agent_calls.jsonl (redundant-call rate, verb adoption)
│   │   ├── features.py · tuning.py   pre-decision features (no leakage) · abstaining champion/challenger ratio learner
│   │   └── digest.py · validate.py   Markdown digest · blocking N/N PASS gate
│   ├── improvement/            SELF-IMPROVEMENT SUBSYSTEM (experiment loop + daily observer scan)
│       ├── lifecycle.py        experiment state machine (Canary/Promoted are human-only)
│       ├── registry.py         experiment records on ledger.db — the enforcement point
│       ├── runner.py · verifier.py   baseline-vs-candidate runner · independent verifier (can only reject)
│       ├── schema.py           ExperimentDefinition + DiscoveryConfig contracts
│       ├── proposals.py · board.py · attention.py · promotion.py   propose · Kanban board · brief · canary
│       ├── statistics.py · jury.py · drift.py · control.py   measurement-science layers (mSPRT/CUPED, κ-α, drift)
│       ├── selfmetrics.py      DORA · acceptance-by-pillar · convergence power-law · BWT/FWT
│       └── discovery/          the daily observer-only scan (sources→findings→triage→rank→draft→emit)
│           ├── pillars · findings · ranking · acceptance   9 pillars · ICE/RICE/WSJF/VOI · learned P(accept)
│           ├── charter · sources · triage · report · manifest   observer wall · scanners · dedup · report+sidecar
│           ├── pipeline · dag_support · validate   orchestrator · Airflow glue · blocking N/N gate
│           └── delivery/        email digest (stdlib SMTP) + chat ping (board.py drives the Kanban)
│   └── knowledge/              OKF KNOWLEDGE PRODUCER (observer-only; source → derived bundle)
│       ├── profile.py          OkfConcept — the strict growth-os-0.1 frontmatter contract
│       ├── document.py         concept read/write (frontmatter + generated block + human notes)
│       ├── producers.py        deterministic source→concept extractors (no source → no concept)
│       ├── bundle.py           assemble concepts + per-section index.md (progressive disclosure)
│       └── validate.py         the blocking N/N PASS gate
│
├── generated/                  DISPOSABLE rendered output — never hand-edited
│   ├── litellm-config.yaml     rendered gateway config (only ollama_chat/... models)
│   ├── json-schema/            editor autocomplete for the configs
│   ├── kanban-imported.json    bridge dedupe state (which cards already dispatched)
│   ├── model-scout-report.md   latest propose-only model discovery report
│   └── usage-digest.md         latest spend/escalation/block-rate digest
│
├── services/                   Docker control-plane services (each Dockerfile + app.py)
│   ├── ledger/                 missions, leases (unique per repo+branch), signed
│   │                           approvals, events, kill switch — the only runtime state
│   ├── judge_gate/             risk classification + judge arrays; mounts standards.yaml
│   │   └── judgectl.py         CLI for invoking judges from hooks/scripts
│   ├── proactive_runner/       thin scheduler for configs/proactive.yaml checks;
│   │                           holds no secrets; max action = open a gated mission
│   └── agent_kanban_ui/        OPTIONAL Phase-4 (profile `ui`): read-only FastAPI over
│                               Ledger + agent-call log; web/ = React/Vite SPA (Cline-styled
│                               board + observability), built + served single-container
│
├── scripts/                    non-Python wrappers: cc.ps1 (Windows), live_smoke.{ps1,sh}
├── dags/                       Airflow DAGs: self_improvement_daily.py (observer-only daily scan)
├── knowledge/                  OKF knowledge bundle (Git-backed, derived; `make knowledge-generate`)
├── tests/                      contract regression tests (pytest; run by CI)
│
├── repo-template/              installed into each onboarded repo by `make repo-install`
│   ├── .devcontainer/          pinned runtime for repo_task isolation
│   ├── .github/workflows/      validate.yml — the four required CI checks
│   ├── .pre-commit-config.yaml static tools → judge array on every commit
│   ├── CODEOWNERS              mandatory human review on merge
│   └── scripts/                pre_push_gate.sh, run_precommit_judges.sh
│
├── .github/workflows/contracts.yml   CI: this repo's own validate gate
├── data/book-checklist.md      275-book curriculum source for the library board
├── appflowy_kanban/            Growth OS (see 11.2)
└── docs/                       the docs set + this one (see §12); backend/ = borrowed standards (§13)
```

### 11.2 Growth OS (`appflowy_kanban/growth-os/`)

```
appflowy_kanban/growth-os/
├── growthos/
│   ├── config.py        contracts: Settings(.env) · Config(sources.yaml) ·
│   │                    ProjectsConfig(projects.yaml) — pydantic, fail-fast
│   ├── appflowy.py      the ONE AppFlowy client: GoTrue login, pre_hash
│   │                    upserts (idempotent), row reads
│   ├── actions.py       the ONE tool layer (~20 tools) shared by assistant /
│   │                    MCP / Discord; Approved structurally refused here;
│   │                    every list tool validates enums LOUDLY (anti-loop)
│   ├── curate.py        hourly: arxiv+github+rss → score → dedupe → enrich → upsert
│   ├── score.py         embedding scorer (Ollama) with keyword fallback (loud)
│   ├── enrich.py        curate stage 3.5: ≤35-word "useful for <project>"
│   │                    annotation per newly kept item → Suggested column
│   ├── airflow_sync.py  hourly: live DAG run state + root-cause failure
│   │                    summaries → dags board; drafts Backlog fix cards
│   ├── packages.py      host/daily: lockfiles vs PyPI → packages board
│   ├── guidelines.py    daily: standards.yaml mirror + release feeds
│   ├── retention.py     daily: Inbox rows older than retention.days → Archived
│   ├── brief.py         daily: morning brief + LLM overview + Mission worklog
│   ├── assistant.py     chat.bat brain: Ollama tool-calling loop with
│   │                    repeat-call breaker + forced final answer
│   └── observability.py CENTRALIZED agent-call log: every tool call on every surface
│                        (Discord/MCP/assistant) → one JSONL + `python -m growthos.observability` monitor
├── agent/growthos_mcp.py    MCP registration over actions (Claude; stdio or --http; logged)
├── scripts/
│   ├── setup_workspace.py   create/RECONCILE databases from schema.yaml
│   ├── create_views.py      Board/Calendar views (idempotent)
│   ├── import_books.py      data/book-checklist.md → library (never clobbers triage)
│   ├── import_dags.py       dag files → dags board (static inventory)
│   ├── new_project.py       stamp per-project board + validated kanban.yaml section
│   ├── new_content_board.py create/RECONCILE the LinkedIn content boards from content_template
│   ├── seed_content.py      content_seed/*.json → In Queue rows (clobber-safe, 1/day)
│   ├── seed_workspace.py    sources mirror + starter todos
│   ├── selftest.py          22 live checks across the whole system (target: 100%)
│   └── test_abilities.py    abilities/routing exercise: each tool ≥5 ways + the approval wall
├── config/
│   ├── schema.yaml          database shapes (first select = board grouping); incl. content_template
│   ├── sources.yaml         feeds, interest weights, scoring, retention
│   ├── projects.yaml        ★ OBSERVE registry: repos the watchers watch
│   ├── content_seed/        Claude-authored LinkedIn drafts (geoffhadfield32.json, world_model_sports.json)
│   └── databases.json       generated id map — reconcile via setup_workspace, never hand-edit
└── docker-compose.curator.yml   the always-on watcher loop
```

**The two registries (deliberately not merged):**
`growth-os/config/projects.yaml` owns what the system **observes** (package
watch, dags dirs, airflow endpoints — consumed by packages/import_dags/
airflow_sync); `llm_station/configs/kanban.yaml` owns what work **dispatches**
(sections, risk ceilings, ready statuses — consumed by the bridge). Adding a
repo takes ~3 minutes: a `projects.yaml` block, then optionally
`new_project.py --name X --repo X --risk L2` + the Section option.

---

## 12. Doc index — where the detail lives

| Doc | What it holds |
|---|---|
| [MASTER.md](MASTER.md) | **this doc** — the consolidated system guide |
| [SETUP-FROM-SCRATCH.md](SETUP-FROM-SCRATCH.md) | **cold-start** — every prerequisite, first boot, and per-channel enablement, in order |
| [channels.md](channels.md) | chat transports (Discord/Slack/Telegram/WhatsApp): architecture + per-platform setup + how to add a new one |
| [LINKEDIN_PIPELINE.md](LINKEDIN_PIPELINE.md) | **Living doc** for the LinkedIn/content pipeline — status, architecture, invariants, the content engine, and the improvement roadmap |
| [linkedin-setup.md](linkedin-setup.md) | **LinkedIn content pipeline runbook** — ordered go-live steps (app → OAuth → live smoke → schedule) + daily operation; `--preflight` self-check |
| [STATUS.md](STATUS.md) | done / in-progress / TODO-in-order — the multi-session work tracker |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | multi-session git safety, engineering standards, the uv dependency workflow |
| [backend/](backend/) | reference standards copied from the betts pipeline (data-engineering, R2/fleet, modeling, serving) — see the N/A note in §13 |
| [visuals.md](visuals.md) | 14 Mermaid diagrams, one per concern |
| [model-routing.md](model-routing.md) | lanes, local roles, fail-closed behavior |
| [model-update.md](model-update.md) | safe model rollout + current local picks |
| [request-routing-examples.md](request-routing-examples.md) | 8 worked examples: request → route → expected response |
| [proactive-ops.md](proactive-ops.md) | proactive lanes, RCA loop, contract-rejected configs |
| [daily-self-improvement-dag.md](daily-self-improvement-dag.md) | observer-only daily self-improvement scan — implemented (`dags/self_improvement_daily.py` + `improvement scan` CLI): report + Proposed cards across 9 pillars |
| [whole-system-validation-prompt.md](whole-system-validation-prompt.md) | reusable end-to-end validation prompt for self-improvement, AppFlowy kanban control, registered repo autonomy, notifications, local model routing, forecast-before-action checks, and privacy |
| [autonomous-pipeline-gap-review-2026-06-16.md](autonomous-pipeline-gap-review-2026-06-16.md) | attachment reconciliation for the autonomous pipeline proposal: what this repo already covers, what remains, and the ordered hardening path for events, repo manifests, desktop rights, completion verification, and canaries |
| [github-app-production-auth-review-2026-06-16.md](github-app-production-auth-review-2026-06-16.md) | GitHub App production-auth review: local evidence, current GitHub-doc basis, blockers, and remaining steps before repo autonomy can use GitHub App auth |
| [github-token-storage-rotation.md](github-token-storage-rotation.md) | GitHub App private-key, installation-token, and owner/admin observer-token storage and rotation policy |
| [backend/projects/SELF_IMPROVEMENT_PIPELINE.md](backend/projects/SELF_IMPROVEMENT_PIPELINE.md) | the scan's project tracker — module tree, 5-stage registry, standards-conformance matrix (data-derived ranking, validation gate, manifest) with evidence |
| [backend/projects/AGENT_KANBAN_SURFACE.md](backend/projects/AGENT_KANBAN_SURFACE.md) | the agent-kanban-surface tracker — harness-owned board state + intent verbs + observability/tuning + the first-party UI; module tree, stage registry, standards matrix, done/left checklist, honest deviations |
| [knowledge-format.md](knowledge-format.md) | the observer-only OKF knowledge producer (`growth-os-0.1` profile) — a Git-backed, derived projection of system knowledge agents share; never a source of truth |
| [breakage-map.md](breakage-map.md) | what breaks when you change something |
| [environment-map.md](environment-map.md) | environment table + activity mapping |
| [github-safety.md](github-safety.md) | branch protection commands, PAT/App scopes, deploy gating |
| [ui-options.md](ui-options.md) | dashboards/ports and per-device access matrix |
| [ecosystem.md](ecosystem.md) | what's load-bearing vs convenience vs skip (WebUI, Ollama gotchas, local-ai-server) |
| [optional-mirage.md](optional-mirage.md) | Mirage VFS watch-list verdict + safe Phase-4 experiment shape |
| [kanban-integration.md](kanban-integration.md) | the bridge contract, sections, writeback, AppFlowy quirks |
| [autonomy-idea-map.md](autonomy-idea-map.md) | channels/brain/knowledge/wall picture + autonomy phases |
| [growth-os-engineering.md](growth-os-engineering.md) | Growth OS living engineering reference (module tree, standards, cross-session rules) |
| [capability-evaluation-loop.md](capability-evaluation-loop.md) | reusable mission brief for evaluating external tools/repos/skills — staged, evidence-first, L2-capped, with command-center mapping |
| [agent-ideas-evaluation-prompt.md](agent-ideas-evaluation-prompt.md) | broad copy-paste prompt for evaluating ClawCodex, Agno/GitWiki, SIA, MAPPA, codebase-memory-mcp, local-ai-server, multi-agent frameworks, and similar ideas before any install/adoption |
| [agentic-process-improvements-2026-06-20.md](agentic-process-improvements-2026-06-20.md) | decision note for Headroom, Airflow RCA, ARD-style metadata, and Gemma 4 12B candidate handling |
| [routing-performance-candidate-evaluation-2026-06-14.md](routing-performance-candidate-evaluation-2026-06-14.md) | read-only one-by-one verdicts for the broad candidate batch, focused on routing/performance impact and ordered next work |
| [improvement-loop.md](improvement-loop.md) | **the coded improvement loop** — lifecycle, runner, promotion/canary/rollback, operator CLI (the system improves itself, human-gated) |
| [experiment-registry.md](experiment-registry.md) | the experiment tables added to the one `ledger.db` — schema, events, negative-result memory, migration |
| [independent-verification.md](independent-verification.md) | the verifier that checks the work: separation, reproduction, sealed evals, self-verification prevention |
| [judge-calibration.md](judge-calibration.md) | judges as measured components — precision/recall, safety-first gate, anti-self-certification |
| [human-attention-governance.md](human-attention-governance.md) | human attention as a constrained resource — queue metrics, morning brief, bottleneck warnings |
| [improvement-loop-audit.md](improvement-loop-audit.md) | the pre-work discrepancy report (documented vs implemented vs tested) |
| [improvement-roadmap-phases.md](improvement-roadmap-phases.md) | **measurement-science layers (Phases 1–6)** — mSPRT/CUPED, judge/jury κ-α, anti-Goodhart, bandit scheduling, drift/canary stats, AI-control + observability spec |

---

## 13. What NOT to build

Kubernetes · public dashboards by default · Caddy/Cloudflare unless public
URLs are truly needed · auto-merge · auto-deploy · agent-held production
secrets · multiple coding agents editing one checkout · a broad PAT · an
unscoped LiteLLM key · auto-promoted model updates · hand-edited generated
configs · unsupervised skill self-rewrites · a wandering refactor agent · a
second model gateway (LiteLLM is it) · a separate channel *service* (channels
are thin transports onto the action layer) · agent-side approval or
agent-installed scheduled self-dispatch (twice classifier-blocked — the wall
catching its own builder is the system working) · public exposure (tailnet
only) · a third coding-agent executor (Cline CLI / etc.) — Claude Code is
primary, Codex the cross-provider fallback; a new executor brings no
gates/judges/ledger/leases and would have to be wrapped in them to be safe
(Cline + Ollama evaluated 2026-06-13 → DEFER, watch-list only) · Puppetmaster
as a second runtime/router/hook layer (borrow routing-artifact patterns only;
see §5.1) · a candidate zoo/tool bundle without a measured gap, control-plane
overlap matrix, threat model, and pre-registered experiment plan · another
abstraction layer unless it prevents a failure actually hit.

The system is a handful of trusted layers with strong contracts, not more
agents. That's the whole design.

### 13.1 What does NOT apply here (the forecasting-pipeline standards)

`docs/backend/` holds reference standards copied from the betts_basketball
**forecasting** pipeline — medallion bronze/silver/gold, Cloudflare R2 transport,
Airflow DAGs, GPU training, dbt, and Bayesian/GBDT/clustering modeling. **None of
that runs in this repo.** Command Center is a control plane; its "pipeline" is
`edit config → validate contract → render generated → serve via LiteLLM / services /
channels`. The **transferable** standards are applied here — the module tree at the
top of this doc, a staged + linear flow, no defensive coding / no hardcoded
fallbacks (the defensive-coding judge enforces it), strict uv/pyproject dependency
discipline, and the multi-session git rules below. The forecasting-specific pieces
(R2 advisory locks, DAG run-location, medallion layers, champion promotion) have no
analog here and must **not** be cargo-culted in. Treat `docs/backend/` as a library
of principles to borrow, not a spec this repo implements.

### 13.2 Multi-session git safety (the single-writer rules that DO apply)

From `docs/backend/engineering/MULTI_SESSION_R2.md`, the git half applies verbatim
even though R2 / Railway / Airflow do not:

- Stage **explicit paths** you own (`git add path/a path/b`); never `git add -A` / `.`.
- Never force-push to a shared branch, never `--amend` a pushed commit, never `--no-verify`.
- Before pushing: `git log origin/main..HEAD --oneline`; if another session's commit
  is in the tree, **rebase rather than overwrite** — keep their work.
- The `appflowy_kanban/AppFlowy-Cloud` submodule is pinned; don't bump it as a side effect.

The full version (with the no-defensive-coding and uv rules) lives in `CONTRIBUTING.md`.

---

## 14. Change log

Newest first. Dates are from the docs themselves; early entries predate the
first commit and reconstruct the record git now preserves.

### 2026-06-20 — Kanban event emission is now the DEFAULT sync path

- The live-sync engine (PR #19) is the source of truth, but emission was **opt-in**
  (`KANBAN_EMIT_EVENTS=1`). It is now the **standard path — ON BY DEFAULT**: every
  governed kanban write on every surface emits one event unless explicitly disabled.
- `GatewayCore._wire_kanban_events` states: default = active once a board resolves
  (sole board or `KANBAN_PRIMARY_BOARD_ID`); multiple-boards-no-primary = inactive
  with a surfaced reason (no guess, no crash); `KANBAN_EMIT_EVENTS=0` = opt-out;
  `KANBAN_EMIT_EVENTS=1` with no resolvable board = loud failure (explicit request).
- `cc setup` now reports emission **status** (ACTIVE/inactive + board + reason +
  exactly what to set). Forbidden event taxonomy aligned (`kanban.merge_by_agent`,
  `kanban.deploy_by_agent`). Tests: `tests/test_kanban_emission_default.py` (6).
- NB: everything else in the "live kanban sync" north star was already merged —
  Phase 4 engine (#19), simpler commands (#18/#20), 2nd repo betts (#21-#23),
  daily DAG (#17), cross-conversation memory (#16), demo+docs (#18). This change
  closes the one remaining gap (emission as the standard path).

### 2026-06-20 — Generic bounded-loop prover (works for any repo)

- **Why:** the existing `pr-check-verify` is llm_station-specific (it replays the
  "fix the fastapi `[dev]` extra" CI scenario against llm_station's exact pyproject
  shape). It can't prove an arbitrary repo's loop.
- **`cc repo-loop-proof`** (`cli/repo_loop_proof.py`): repo-agnostic. The App opens
  a feature branch with a trivial, CI-safe marker file, opens a draft PR, the repo's
  OWN required checks (`RepoManifest.required_status_check_contexts`) run, and it
  verifies they succeed **and the App did not merge** (the wall holds) — then closes
  the PR + deletes the branch and writes evidence. Never merges; writes redacted
  evidence; 4 hermetic tests. repo-verify's loop gate is posture-aware (external
  repos prove via this live PR loop; the local branch-mission smoke is self-only).
- **betts proof run (honest result):** the prover worked end-to-end (opened betts
  PR #7, polled, verified no-merge, cleaned up) but is **BLOCKED** — betts's own
  `Unit Tests` check is **failing on main** (pre-existing; `Bayesian`/`GBDT`/
  `Schemathesis`/`Autoswagger` pass). The prover correctly refuses to certify a loop
  on a red required check (no fake pass). **To enable betts, betts's `Unit Tests`
  must be fixed green.** (CODEOWNERS PR betts#6 also still pending.)

### 2026-06-20 — Merge-wall postures: local pre-push guard for private+free repos

- **Why:** GitHub won't allow branch protection / rulesets on a **private repo on a
  free plan** (verified: betts returns *"Upgrade to GitHub Pro or make this
  repository public"*; llm_station's ruleset works only because it's public). So a
  private+free repo can't have a server-side merge wall.
- **New posture.** `RepoManifest.merge_wall`:
  - `github_branch_protection` (default) — server-side ruleset/protection (strongest).
  - `local_pre_push_and_human_merge` — a real local `pre-push` guard blocks direct
    pushes to protected branches on this machine; the agent stays PR-only
    (structural, via the action layer); a human merges. **LOWER ASSURANCE** (no
    server backstop) — recorded as such, never as "branch protection verified".
- **`cc repo-merge-guard install|verify`** writes/verifies the guard hook (tested:
  it rejects a `main` push exit 1, allows a feature push exit 0). repo-verify's
  `branch_protection_verified` gate is generalized to `merge_wall_verified` and is
  posture-aware.
- **betts** set to `merge_wall: local_pre_push_and_human_merge` + `auth_mode:
  github_app` (App verified on betts); guard installed; `merge_wall_verified` PASSES.
  Remaining betts gates: CODEOWNERS (PR betts#6, merge + pull) and the bounded-loop
  proof (branch-mission needs external-repo adaptation — next). Tests added.

### 2026-06-20 — Enabling betts_basketball: App-installed + per-repo CI checks

- **github_app_installed gate now PASSES (verified, not faked).** The user added
  betts to the existing `llm-station-command-center` App installation; confirmed by
  read-back (a betts-scoped App token reads betts 200). So
  `github_app_auth.selected_repositories` now legitimately includes betts.
- **Per-repo required CI checks.** New `RepoManifest.required_status_check_contexts`
  + `pr_check_verify.required_checks_for()`: each repo's PR-check loop (and its
  branch protection) uses ITS OWN checks; the self/control repo falls back to the
  global list. betts declares `["Unit Tests"]` (its hermetic CI job); llm_station
  keeps `validate`/`lint-test`. Test added.
- **CODEOWNERS** opened as a PR on betts (`betts_basketball#6`, via the App on a
  feature branch — never a direct main push); human merges it, then `git -C betts pull`.
- **Still blocked (cannot fake):** branch protection — the `GITHUB_OWNER_ADMIN_TOKEN`
  fine-grained PAT 403s on betts Administration (verified: 404 on llm_station = has
  admin, 403 on betts = lacks it), so the user must grant Administration on betts to
  that token or set protection in the UI. The bounded-loop proof needs branch-mission
  adapted for external repos (next). AppFlowy board-live needs `APPFLOWY_*` creds.

### 2026-06-20 — Second repo onboarded: betts_basketball (disabled) + multi-board

- **First external repo registered (DISABLED).** `betts_basketball` added to
  `configs/autonomy.yaml` with `autonomous_edits_enabled: false`,
  `auth_mode: github_app_pending`, blocker `repo_autonomy_not_yet_verified`,
  `local_path_ref: env:BETTS_BASKETBALL_LOCAL_PATH` (no absolute path committed).
- **Two boards, both registered (kanban-verify PASS).** `betts_basketball`
  (command_center_ui) — validated **live-working** (event→fold→UI projection; the
  wall holds: agent can't set an approval status). `betts_basketball_appflowy`
  (appflowy, env refs) — contract-valid; write-through **fail-closed `degraded`**
  with no AppFlowy creds on this machine (NOT a fake pass — live needs `APPFLOWY_*`).
- **Bug fixed (surfaced by the 2nd repo): repo-verify gates were control-repo-scoped.**
  `devcontainer_present`/`codeowners_present` resolved against the *control* repo,
  and `branch_mission_proven`/`pr_check_evidence_proven` read the control repo's
  evidence — so an external repo falsely inherited llm_station's files/proof. Now
  they resolve against the **target** repo's local path, and per-repo loop evidence
  lives under `RUN_ID/<repo_id>/`. `self` (llm_station) behaviour unchanged. betts's
  checklist is now honest: devcontainer PASS, codeowners BLOCKED, loop NOT_RUN, plus
  App-selection + branch-protection blockers — 5 real gates before it can enable.
- Evidence: `evaluation/system-validation/20260616-autonomy-contracts/betts-onboarding.json`
  (redacted). Regression test in `tests/test_repo_registry.py`.

### 2026-06-20 — Operator command wrappers (keep it simple)

- **`cc setup`** runs the real `doctor` (its exit code is returned — a failing
  machine is never masked as ready) then prints a registry summary + the live-sync
  activation env (`KANBAN_EMIT_EVENTS`/`KANBAN_PRIMARY_BOARD_ID`) + next steps.
- **`cc onboard repo --path <dir>`** infers repo id (folder), remote URL (git
  origin), and board id, then runs `repo-register` (dry-run) + `repo-verify` and
  prints the gate checklist. Writes nothing without `--apply`; local path stored as
  an `env:` ref. **`cc onboard kanban --provider <p> --repo <id>`** wraps
  `kanban-register` (dry-run) + `kanban-verify`; appflowy boards demand `env:` refs.
- The friendly set is now `doctor / setup / onboard repo|kanban / operate /
  improve / demo`; every lower-level evidence command stays. Docs:
  `docs/OPERATOR_COMMANDS.md`. Tests: `tests/test_operator_wrappers.py` (7).

### 2026-06-20 — Live kanban sync: one event stream, many projections

- **Source of truth = the kanban event log.** New `command_center.kanban_sync`
  (`events.py` + `projection.py`): a `KanbanEvent` schema, an append-only event
  log (`generated/kanban-events.jsonl`, gitignored), and `emit_event` as the
  **single legal writer**. Wall actions (`approve_card`/`merge`/`deploy`/
  `delete_card`/`delete_board`) raise `GovernanceViolation` — they can never
  become an event, so no surface can project them.
- **The wall is structural on the action AND the status value.** Wall actions
  raise `GovernanceViolation`; and a permitted verb cannot carry a human-owned
  **status** — `emit_event`, the `KanbanEvent` validator, and `write_through` all
  reject any approval status (case/space/underscore-folded, so the lowercase
  `missions` board's `approved` is protected too). An agent can never emit,
  project, or write an approval.
- **Surfaces are projections.** `project_cards` folds events into current state;
  the UI renders from that. `verify_projection` (PASS/BLOCKED/DEGRADED). `reconcile`
  classifies each difference as **drift** (repairable) vs **conflict**
  (`review_required`) for human approval, a human re-opening a terminal card, or a
  card on the board not in the log. `--apply` repairs drift to the **fold target**
  only — never conflicts. No silent last-write-wins.
- **Wired into the one action layer.** `GatewayCore` funnels every governed
  card/todo verb (Discord/SMS/in-app console) through `emit_event` via
  `wrap_governed_dispatch`. Opt-in: `KANBAN_EMIT_EVENTS=1` + `KANBAN_PRIMARY_BOARD_ID`
  (fails loud if unresolvable); the UI `/api/action` is covered (surface `app`).
- **Level 1 (immediate) internal UI.** `GET /api/events/kanban` (SSE; each frame
  carries `id:` so `Last-Event-ID` resumes with no replay) + `/api/events/kanban/snapshot`.
- **Level 2 (near-real-time) AppFlowy.** `AppFlowyProjection.write_through` is a
  projection-only writer; **fails closed** (`degraded`) without board env, and
  **refuses** to write a human-owned status — no fake live-sync.
- **Commands:** `cc kanban-emit` / `kanban-project` / `kanban-verify-projection` /
  `kanban-reconcile`, plus high-level `cc operate verify --all`. Lower-level
  evidence commands stay.
- **Adversarially reviewed before commit** (6-dimension workflow, 36 agents): two
  critical wall holes (lowercase `approved` unprotected; `status_after` bypass) and
  the integration-island gap were found and fixed. Tests: `test_kanban_sync.py`
  (19) + `test_kanban_wiring.py` (4) + `test_kanban_ui_events.py` (4).
- **Docs:** `docs/LIVE_KANBAN_SYNC.md` (architecture, three levels, conflict
  policy, activation).

### 2026-06-20 — Phase 8/9: full-loop demo + "ready for anyone" docs

- **Full-loop demo.** `cc demo full-loop --repo <id> --board <board_id>` verifies
  the loop is wired (runs `kanban-verify` + `repo-verify`, read-only) and prints
  the canonical 14-step sequence, marking each step `VERIFY` / `AUTOMATABLE` /
  `HUMAN_GATE`. It performs **no writes and never merges**; steps 5/9/10/14 are
  human gates. 3 hermetic tests.
- **Docs for fresh setup → daily operation.** Added `docs/GETTING_STARTED.md`,
  `INSTALL_WINDOWS.md`, `INSTALL_WSL.md`, `ADDING_A_REPO.md`, `ADDING_A_KANBAN.md`,
  `RUNNING_DAILY_SELF_IMPROVEMENT.md`, `SECURITY_MODEL.md`,
  `OPERATIONS_RUNBOOK.md`, `TROUBLESHOOTING.md` — covering UI vs AppFlowy board
  selection, repo/kanban registration, the daily DAG, the human approval/merge
  walls, emergency stop, and the known gotchas (App has no `workflows:write`;
  workflow PRs need human creds; tests need dev/gateway extras;
  most-recent-push approval rule).
- **"Ready for anyone" status.** Phases 2–5 + 8/9 are done. The only remaining
  gated item is Phase 6 (live desktop actions), correctly blocked until a real
  AppFlowy sandbox board is wired (`APPFLOWY_SANDBOX_*`) so action-latency
  evidence can be measured — never fabricated.

### 2026-06-20 — Phase 4: daily self-improvement commands (observer/draft-only)

- **Operator surface for the existing observer pipeline.** Added
  `cc self-improvement-scan` / `self-improvement-daily` / `self-improvement-report`
  over `command_center.improvement.discovery` (the `self_improvement_daily` DAG's
  pipeline). The scan reads network-free sources, ranks findings, and drafts ONLY
  `Proposed` experiment cards through the `ObserverCharter`.
- **Observer/draft-only by design.** `scan`/`report` make zero registry writes;
  `daily --draft-kanban true` drafts `Proposed` cards (human approval still
  required before any code change); `daily --apply true` (applying code) is
  **refused** — `code_apply_not_supported_daily_is_observer_draft_only`. The
  charter structurally forbids promote/canary/merge/deploy/set_status
  (`CharterViolation`), so even a buggy scan can't escalate.
- **Evidence.** `self-improvement-daily.json` records date, findings, drafted
  card ids, and `applied_code_changes: false`. Drafted cards are always
  `Proposed`; an approved card becomes a Ledger mission running the
  branch/worktree/devcontainer/PR loop. 5 hermetic tests.
- **Next (Phase 6).** Real desktop action-latency evidence (needs a wired sandbox
  board) → desktop enablement gates; then Phase 8/9 (full-loop demo + docs).

### 2026-06-20 — Phase 5: safe cross-conversation / project memory

- **Durable memory layer.** `command_center.memory` (store + `MemoryRecord`/
  `MemoryConfig`) adds the persistent cross-conversation layer the gateway lacked
  (it kept only an ephemeral per-conversation deque). Scopes: conversation,
  project, board, user_preference, artifact.
- **Recall is approval-gated + namespaced + provenanced.** `inject` returns a
  record only if `approved_by_human`, `inject_policy != never`, not stale, and
  the scope+subject namespace matches — so unapproved memory is never recalled in
  another conversation and one repo's project memory can't leak into another.
  Every recalled record cites its `source_ref`.
- **Secrets never stored.** `MemoryRecord` rejects secret-bearing values at add
  time; `source_ref` is required; confidential records must be `redaction_status:
  redacted`; project/board subjects must be stable-id namespaces. The store is
  per-deployment runtime state (`generated/memory/`, gitignored), not committed.
- **No magic thresholds.** Staleness is per-record (`retention_policy:
  keep_until_superseded` or `expire_after_days:<N>`), not a global constant.
- **Commands.** `cc memory-add` (pending until `--approved-by`), `cc
  memory-review`, `cc memory-prune [--apply]`, `cc memory-verify`. 11 tests.
- **Next (Phase 4).** Productize the daily self-improvement DAG (observer/
  draft-only, scheduled).

### 2026-06-20 — Phase 3: generalized repo registration + autonomy gates

- **RepoManifest extended.** Added `kanban_board_id` (binds a repo to a board in
  `kanban_boards.yaml`, cross-checked by repo-verify) and `local_path_ref`
  (`self` or `env:NAME` only — a committed absolute path would leak machine
  layout). Enabling autonomy now also requires both fields. `llm_station`'s
  manifest gained `kanban_board_id: llm_station_command_center`, `local_path_ref:
  self`.
- **Commands.** `cc repo-register` (adds a DISABLED manifest with blockers;
  dry-run by default, stores the local path as an `env:` ref and tells you to set
  it in `.env`; `--apply` inserts the block + re-validates), `cc repo-verify`
  (gates: devcontainer present, CI commands declared, CODEOWNERS present, kanban
  board mapping, local_path_ref resolves, GitHub App installed for the repo,
  branch protection verified, no-runtime-secrets policy, and branch-mission +
  PR-check evidence both PASS — never faked, NOT_RUN when absent), `cc
  repo-enable-autonomy` (re-runs verify and refuses unless every gate passes;
  `--apply` flips `autonomous_edits_enabled` + clears blockers).
- **Safety.** No new repo can be autonomy-enabled until all gates pass; the
  enabled-manifest schema invariants are re-validated before any write. No direct
  main push, no merge, no branch-protection change.
- **Next (Phase 5).** Cross-conversation persistent memory with provenance,
  redaction, and human approval.

### 2026-06-20 — Phase 2: provider-agnostic kanban board registry

- **New registry contract.** `configs/kanban_boards.yaml` (`KanbanBoardsConfig`)
  maps a `board_id` to a surface (`provider: appflowy` OR `command_center_ui`),
  the repos it drives, the canonical status workflow (backlog/ready/in_progress/
  done/blocked/rejected/awaiting_approval), required mission-card fields, and the
  agent verb contract. Both providers share ONE action contract by construction.
- **Wall verbs enforced in the contract.** `approve_card`, `merge`, `deploy`,
  `delete_card`, `delete_board` must be forbidden on every board; `allowed_agent_
  verbs` may only grant the non-destructive set (add/stage/start/finish/block/
  reject). AppFlowy `workspace_ref` must be an `env:` reference, never an inline
  secret.
- **Commands.** `cc kanban-verify` (status/field/verb contract + board-snapshot
  duplicate-MissionID and unredacted-secret detection; NOT_RUN without a
  snapshot, never faked); `cc kanban-register` (dry-run validate by default,
  `--apply` writes); `cc kanban-sync --dry-run` (read-only plan; actual mutation
  stays with `cc kanban-bridge`). No writes, no approvals, no merges.
- **Next (Phase 3).** `cc repo-register/repo-verify/repo-enable-autonomy` to
  onboard other local repos, each bound to a registered `kanban_board_id`.

### 2026-06-20 — Representative desktop action-latency measurement (root-cause fix)

- **Root cause found.** `desktop-timing-derive` derived `action_timeout_seconds`
  from read-only no-op canary timing (snapshot reads, ~15–33 ms), which does not
  represent real desktop-action latency. It then labeled those sub-second values
  `proposed` even though the schema (`action_timeout_seconds: int ≥ 1`) can never
  accept them — misleading, not data-representative.
- **Fix, no fabrication.** Added `DesktopActionLatencyCanarySpec` +
  `cc desktop-action-canary`: measures a **reversible sandbox** AppFlowy
  `direct_api` round-trip (create→delete a throwaway row on a SANDBOX database,
  never the production board) and records `action_create_ms` / `action_delete_ms`
  / `action_roundtrip_ms`. Credentials are env refs only; it **fails closed**
  (`representative_action_source_not_configured`) when absent — verified blocked
  in this env (no AppFlowy sandbox wired).
- **Derive made honest.** `desktop-timing-derive` now treats read-only evidence
  as **observation timing only** and returns `blocked`
  (`action_latency_evidence_required_for_production_candidates`) instead of
  `proposed`; `action_timeout` is derived solely from action-latency round-trips
  (max observed, ceil to whole seconds, no multiplier). `ttl_minutes` is a
  session lifetime, not an action latency, so it is reported as needing separate
  session-duration evidence (`ttl_evidence_required_from_session_durations`),
  never fabricated.
- **Still correctly blocked.** `enable_desktop_target_only_after_timeout_takeover
  _and_canary_plan` stays gated: no AppFlowy sandbox is configured, so no real
  action-latency evidence exists yet, and `ttl` has no evidence source. **Next:**
  wire `APPFLOWY_SANDBOX_*` env to a sandbox board to produce real action-latency
  evidence; then design a session-duration evidence source for `ttl`.

### 2026-06-20 — Source reconciled and Phase 1 doctor productized

- **Source of truth reconciled.** Local `main` is clean and synced with
  `origin/main` at `0ac008c`. The remote has `main` and `setup/github-ready`;
  `feat/agent-kanban-surface` is no longer a separate ahead branch. PR #10,
  #11, and #12 are merged. PR #6 is closed unmerged as the draft canary proof
  PR.
- **`cc doctor` upgraded.** The doctor now runs the setup checks as structured
  PASS / FAIL / BLOCKED / NOT_RUN results with exact blockers, next commands,
  and redacted JSON evidence. It checks Python, uv, `uv sync --frozen --extra
  dev --extra gateways`, Docker, Docker Compose, Ollama, LiteLLM, Ledger,
  model role resolution, AppFlowy config, internal UI config, Airflow DAG
  presence, GitHub App env refs, GitHub App installation, branch protection,
  CODEOWNERS/devcontainer guardrails, forbidden providers, committed config
  secret literals, generated/evaluation dirtiness, and enabled channel token
  refs by presence/name only.
- **Bootstrap aliases added.** `uv run cc bootstrap-local` now maps to the
  local bootstrap path, and `uv run cc verify-stack` runs the full doctor.
- **Current blockers are setup gaps.** Doctor evidence
  `evaluation/system-validation/20260620-phase1-doctor/doctor-report.json`
  reports 19 PASS, 0 FAIL, 2 BLOCKED, 0 NOT_RUN: missing AppFlowy env refs and
  missing `DISCORD_ALLOWED_CHANNEL_IDS` while `discord-main` is enabled.
- **Next ordered work.** Clear or intentionally disable those two setup
  blockers, rerun `uv run cc doctor`, then move to Phase 2 board registry and
  board verification.

### 2026-06-20 — Desktop timing sample plan and candidates proposed

- **Sample plan declared.** `configs/autonomy.yaml` now includes
  `desktop_timing_sample_plans[appflowy_browser_staging]`. Its required sample
  count is derived from the listed repo-relative evidence refs, not from a code
  default, CLI fallback, or production threshold.
- **Additional no-op samples recorded.** Two post-merge read-only samples were
  captured under
  `evaluation/system-validation/20260616-autonomy-contracts/desktop-noop-canary-samples/`.
  They perform no desktop actions, screenshots, clipboard reads, password reads,
  AppFlowy writes, or production config writes.
- **Candidates are proposed only.** `cc desktop-timing-derive` now reads the
  config sample plan and proposes TTL/action-timeout candidates from the maximum
  observed no-op timing values with no multiplier. The artifact records
  `production_values_written: false`, `desktop_target_enabled: false`, and
  `placeholder_values_used: false`.
- **Still blocked before live actions.** `cc desktop-adapter` still blocks until
  accepted TTL/action-timeout controls are wired into the desktop target. The
  next ordered work is `enable_desktop_target_only_after_timeout_takeover_and_canary_plan`,
  which starts with review/acceptance of the proposed candidates, not automatic
  target enablement.

### 2026-06-20 — Capability catalog and proactive RCA pilot activated safely

- **Capability catalog added.** `configs/capabilities.yaml` records ARD-style
  routing/discovery metadata for internal tools, workflows, skills, and model
  candidates. It grants no execution authority; `configs/tools.yaml`,
  `configs/autonomy.yaml`, and the approval wall still control actions.
- **No local path leakage.** Capability provenance avoids workstation paths.
  Airflow snapshot evidence records repo-neutral `evidence_ref` values, not
  local absolute paths; missing required snapshots now fail loudly instead of
  becoming judge-visible partial evidence.
- **Airflow RCA intake wired behind real evidence.**
  `configs/proactive.yaml#airflow-failure-rca-intake` can collect failed DAG
  snapshots only when `PROACTIVE_AIRFLOW_EVIDENCE_DIR` points at real redacted
  JSON. Without that env var, collectors remain unwired and the proactive runner
  skips the check instead of fabricating evidence. With the env var set, every
  snapshot must declare `schema_version: command-center.airflow-evidence.v1`,
  `redaction_status: redacted`, and `data`; wrong schema versions, unredacted
  snapshots, missing files, and secret-bearing field names fail closed.
- **Headroom and Gemma stay gated.** Headroom compression is a proposed
  manual improvement experiment, not a global wrapper; `automated: false` keeps
  the runner from fabricating a lifecycle run before a real measurement harness
  and evidence source exist. Gemma 4 12B is cataloged as a model candidate only
  and still needs exact tag, digest, license, fit, canary, evals, and human
  promotion evidence before any routing change.
- **What remains, in order.** First build the external Airflow snapshot producer
  that emits the redacted schema above. Second assemble labeled Headroom
  raw/compressed cases and run the independent verifier. Third collect exact
  Gemma identity and fit evidence before editing model routing. Fourth add
  representative-query tests before using the capability catalog for routing.

### 2026-06-20 — Desktop no-op canary telemetry added

- **Read-only canary path added.** `cc desktop-noop-canary` records redacted
  timing evidence for `appflowy_browser_staging` from the existing target
  snapshot and verifier. It performs no clicks, typing, screenshots, clipboard
  reads, password reads, AppFlowy writes, or desktop live actions.
- **Derivation initially stayed blocked.** `cc desktop-timing-derive` could
  derive provisional candidates only from measured canary evidence and an
  explicit sample plan. The first merged-main sample proved instrumentation
  only and did not set `ttl_minutes` or `action_timeout_seconds`.
- **Evidence recorded.** The current artifacts are
  `desktop-noop-canary.json` and `desktop-timing-candidates.json` under the
  `20260616-autonomy-contracts` system-validation package.
- **Next ordered work at that point.** Declare the desktop timing sample plan,
  run additional no-op samples from that plan, then derive provisional timing
  candidates while keeping desktop live actions disabled.

### 2026-06-20 — PR #9 merged through the protected GitHub App path

- **PR #8 retired.** PR #8 is historical only. It was user-authored, so
  `ghadfield32` reviews landed as comments and could not satisfy the required
  non-author approval gate.
- **Correct path proved.** Replacement PR #9 was created through the configured
  GitHub App identity, approved by `ghadfield32`, passed `validate` and
  `lint-test`, and merged as squash commit `0eb46bc`. Branch protection stayed
  intact: no direct main push, no branch-protection weakening, no check bypass,
  and no self-approval.
- **Desktop gate merged.** The timeout/takeover policy gate is now on `main`.
  Live desktop actions remain disabled. Numeric TTL and per-action timeout
  controls remain unset until measured no-op canary telemetry derives them.
- **Next ordered work.** Build measured no-op desktop/browser canary telemetry
  and readiness evidence before proposing any desktop target enablement.

### 2026-06-19 — Desktop timeout and takeover policy declared

- **Post-merge cleanup done.** PR #7 merged via squash auto-merge after
  CODEOWNERS approval. Local `main` was fast-forwarded to the merge commit, and
  obsolete draft proof PR #6 was closed without deleting its feature branch.
- **Policy declared, actions still disabled.** `configs/autonomy.yaml` now
  records `desktop_timeout_and_human_takeover_policy_declared`, declares the
  human-takeover hotkey and `redacted_hashes_and_refs_only` screenshot artifact
  policy for `appflowy_browser_staging`, and deliberately leaves numeric TTL
  and per-action timeout controls unset until no-op canary telemetry derives
  them. The target remains `enabled: false`; this is a safety policy
  declaration, not live GUI approval.
- **Evidence boundary explicit.** [desktop-timeout-takeover-policy.md](desktop-timeout-takeover-policy.md)
  records that the current policy is declaration evidence only. No live-GUI
  timing percentile is claimed, no raw screenshots are retained, and the target
  must still pass no-op canary evidence before live actions can be enabled.
- **Adapter evidence improved.** `cc desktop-adapter` now reports whether the
  timeout/takeover policy is declared, whether TTL and action-timeout controls
  are measured, and whether human-takeover and screenshot policies exist while
  retaining only the presence of the takeover hotkey, not the key sequence.
- **Next ordered work.** Start with
  `enable_desktop_target_only_after_timeout_takeover_and_canary_plan`, then
  derive the GUI loop-breaker threshold from event history before autonomous GUI
  retries, then enable no-op canaries, telemetry, and external-runtime gates.

### 2026-06-19 — Live PR/check evidence loop verified

- **Remote repo loop passed.** `uv run cc pr-check-verify --apply
  --poll-interval 15 --poll-timeout 1800` created feature branch
  `mission/llm_station/pr-check/20260619T122507591431Z`, opened draft PR #6,
  and observed both configured required checks succeed: `validate` and
  `lint-test`. Evidence is recorded in
  `evaluation/system-validation/20260616-autonomy-contracts/pr-check-loop.json`.
- **Credential and privacy boundary held.** The verifier uses the
  `llm-station-command-center` GitHub App installation token in memory only. It
  does not use the owner/admin observer token, does not print or store the
  installation token, does not put tokens into git remotes, and does not merge,
  deploy, alter settings, alter secrets, or delete branches. The PR remains a
  draft with human review/CODEOWNERS as the merge wall.
- **Required-check contract fixed.** The protected `lint-test` job installs
  `.[dev,gateways]` before full pytest, matching the repo manifest's declared
  validation command because collected tests import channel adapters. The
  `contracts` workflow now runs for every PR targeting `main` instead of using a
  path filter, so docs/evidence-only PR commits cannot leave required checks
  permanently unreported. Future PR-check canaries read `pyproject.toml` from
  the protected base branch through the GitHub contents API, then apply only the
  bounded canary changes instead of copying unrelated local working-tree
  content.
- **Ruleset approval actor clarified.** The active GitHub ruleset requires approval
  of the most recent reviewable push. Integration PR maintenance commits should
  be pushed by the GitHub App or another non-approving actor so `ghadfield32`
  approval remains the human merge wall instead of self-approval by the last
  pusher.
- **Gate moved forward.** `configs/autonomy.yaml` now records
  `pr_check_evidence_loop_verified`, removes
  `verify_pr_check_evidence_loop_before_autonomous_edits` from ordered work,
  and enables `llm_station` repo autonomy with an L2 feature-branch-only risk
  ceiling and no repo blockers. `cc system-validation` now reports repo
  autonomy PASS only when the config is enabled and `pr-check-loop.json` is
  PASS, preventing config intent from being reported as verified evidence.
- **Next ordered work.** Start with
  desktop timeout/takeover policy declaration before live actions; this was
  completed later on 2026-06-19.

### 2026-06-18 — Branch-only repo mission passed

- **Bounded mission command added.** `uv run cc branch-mission` creates one
  local mission id, one local feature branch, and one temporary worktree under
  `C:\tmp\command-center-repo-missions`, writes only
  `docs/branch-mission-smoke.md`, runs the repo manifest's declared validation
  commands, and emits `evaluation/system-validation/20260616-autonomy-contracts/branch-mission.json`.
  It records canonical forecast, repo-action, and verification events plus a
  completion-verifier verdict, while retaining command output only as hashes and
  line counts.
- **Clean-worktree dependency gap fixed.** The first branch mission correctly
  blocked because a clean worktree could not run `pytest` without optional test
  dependencies. `configs/autonomy.yaml` keeps the local branch-mission command
  explicit as `uv run --extra dev --extra gateways pytest` while this work is
  still unmerged. The PR/check verifier adds the `pyproject.toml` dev dependency
  fix on its canary branch because the existing protected `lint-test` job
  installs `.[dev]` before running full pytest. The bot does not need workflow
  write permission.
- **Result and remaining gate.** The final branch mission passed: docs-only
  change, `cc validate` PASS, full pytest PASS, completion verifier PASS, no
  push, no PR, no merge, no deploy, no settings change, and no secret value
  retention. `configs/autonomy.yaml` now marks
  `tiny_branch_only_repo_mission_passed`; this gate was superseded by the
  2026-06-19 live PR/check/evidence pass.

### 2026-06-18 — Branch wall verified

- **Observer token is not the blocker.** Re-ran
  `uv run cc branch-protection-verify` with `GITHUB_OWNER_ADMIN_TOKEN` present.
  GitHub accepts the token for repo, branch, protected-branch list, active-rule,
  and ruleset reads. The active `protect-main-command-center` ruleset now
  verifies `main` protection, required checks, PR review count, CODEOWNERS
  review, conversation resolution, linear history, deletion restriction,
  force-push blocking, and an empty bypass list. GitHub wall verification is
  complete.
- **Setup language simplified.** §8 now names the two identities directly:
  the GitHub App is the normal long-lived agent identity and must not receive
  Administration permission; the owner/admin observer token is a temporary
  read-only proof tool only. The next ordered work is no longer GitHub setup;
  it is a tiny branch-only repo mission to prove the branch/worktree/validation
  evidence loop without merging.

### 2026-06-17 — GitHub permissions verified; agent validation added

- **Verifier state corrected.** The local GitHub App verifier now proves the
  app is installed on the selected `ghadfield32/llm_station` repo, can mint an
  installation token in memory, can read the selected repository, and can read
  commit check/status endpoints. The old "install the app" blocker is closed.
- **Repository permissions verified.** `issues: read` is now explicitly
  operator-approved in `configs/autonomy.yaml`; the verifier passes repository
  permission checks without printing or storing secrets. Administration, secrets,
  variables, deployments, environments, workflows, and actions remain forbidden.
- **Branch-protection proof.** Branch-protection inspection still returns 403
  with the GitHub App token, and the app must not receive Administration solely
  to inspect settings. Added `uv run cc branch-protection-verify`, which proves
  expected check contexts from `.github/workflows/contracts.yml`, checks
  CODEOWNERS path presence, reads the owner/admin observer token without
  printing it, and now probes both classic branch protection and GitHub active
  branch rules/rulesets. The 2026-06-17 observer run proves the token can read
  `ghadfield32/llm_station`, but `main` has no classic protection and no active
  ruleset evidence, so the blocker is now configuration of the branch wall, not
  credential visibility.
- **Token policy drafted.** Added
  [github-token-storage-rotation.md](github-token-storage-rotation.md), which
  records env-ref-only storage, out-of-repo PEM handling, in-memory installation
  tokens, one-run owner/admin observer token use, and rotation steps. It is not
  a repo-autonomy approval until branch protection verifies.
- **Agent route proof.** Added `uv run cc agent-validation`, a read-only live
  validator for the `chat` route. It passes parsed tool-call parsing,
  memory-block recall, 14-turn recall, and fresh-conversation abstention, with
  only synthetic scenario status stored in `agent-validation.json`.
- **Desktop target proof.** Added `uv run cc desktop-target-verify`, a read-only
  snapshot verifier. The configured AppFlowy test card was moved to
  `In Progress` through the existing `move_item` intent and now verifies from a
  regenerated live snapshot.
- **Desktop adapter readiness.** Added `uv run cc desktop-adapter`, a manifest
  readiness gate. It performs no clicks, screenshots, clipboard reads, or
  desktop writes; it currently blocks because live actions are disabled and no
  timeout, takeover hotkey, or screenshot policy is declared.
- **Evidence package refreshed.** `evaluation/system-validation/20260616-autonomy-contracts/`
  now includes regenerated `NEXT.md`, `GAPS.md`, `SCENARIOS.md`, the redacted
  `github-app-verify.json`, `branch-protection-verify.json`,
  `agent-validation.json`, `desktop-target-verify.json`,
  `desktop-adapter-readiness.json`, an implementation note, and validation
  results.

### 2026-06-16 — Autonomous pipeline attachment reconciled

- **What changed.** Added
  [autonomous-pipeline-gap-review-2026-06-16.md](autonomous-pipeline-gap-review-2026-06-16.md)
  to reconcile the attached autonomous pipeline proposal against the current
  Command Center + Growth OS implementation. The decision is to keep the
  existing single-control-plane architecture and use the proposal as a
  hardening checklist, not to adopt a second supervisor or runtime stack.
- **What is already covered.** The current repo already has one action layer,
  one approval wall, one mission Ledger, one Kanban bridge, local-only model
  routing, open-weight model discovery, proposal-only self-improvement, and
  branch-protected repo execution boundaries.
- **Contract pass.** Added `configs/autonomy.yaml` plus `AutonomyConfig`,
  canonical event records, and a forecast/evidence completion verifier. The
  contract now declares the required event families, registered repo manifest,
  desktop rights manifest, disabled no-op canaries, structured-events-only
  telemetry decision, GitHub App production-auth review, and external-runtime
  gate. Raw payload retention, missing event families, overlapping desktop
  actions, enabled desktop targets without TTL/takeover policy, enabled canaries
  with blockers, and production repo autonomy without GitHub App + devcontainer
  are rejected by tests.
- **Evidence runner.** Added `uv run cc system-validation --run-id <run-id>`,
  an observer-only evidence package writer under
  `evaluation/system-validation/<run-id>/`. It records config state, git
  metadata, blockers, privacy boundaries, forecasts, completed contract work,
  and remaining ordered work without calling models, mutating repos, writing
  AppFlowy, sending notifications, capturing screenshots, or reading `.env`.
- **Live local-model check.** `uv run cc live-smoke` initially failed because
  LiteLLM `planner` spent the whole 160-token smoke budget in
  `reasoning_content` and returned empty visible `content`. Live prompt/budget
  checks showed `Output only <sentinel>`, deterministic `temperature: 0`, and a
  smoke-only 512-token completion budget return visible content for `planner`
  and `local-judge`. No provider fallback or alias substitution was added; the
  smoke scripts now prove Ollama direct, LiteLLM `triage`, `planner`,
  `local-judge`, denied cloud-model names, and the forbidden-provider scan.
- **Repo manifest pass.** Added `.devcontainer/devcontainer.json` for
  `llm_station` using a digest-pinned Python 3.12 devcontainer image and the
  locally observed `uv==0.8.11`; `configs/autonomy.yaml` now records
  `execution_mode: devcontainer` and `devcontainer_path:
  .devcontainer/devcontainer.json`. Cross-reference validation now proves the
  declared devcontainer and CODEOWNERS files exist inside the repository.
- **GitHub App auth review.** Added
  [github-app-production-auth-review-2026-06-16.md](github-app-production-auth-review-2026-06-16.md).
  Local evidence verified the GitHub remote, default branch, branch heads,
  CODEOWNERS, and CI workflow. The app identity is now recorded in
  `configs/autonomy.yaml` as env-var references only:
  `llm-station-command-center`, owner `ghadfield32`, homepage
  `https://github.com/ghadfield32/llm_station`, webhook disabled, selected repo
  `ghadfield32/llm_station`, and least-privilege permission policy. Added
  `uv run cc github-app-verify`, an observer-only verifier that mints no stored
  credential, prints no secrets, performs no writes, and records redacted
  evidence. The PEM that was placed in the repo was moved to
  `C:\Users\ghadf\.secrets\github-apps\llm-station-command-center.2026-06-16.private-key.pem`,
  `.env` now points at that path, and `.gitignore` blocks future PEM/key files.
  Current verifier result authenticates the app (`/app` and `/app/installations`
  return 200), discovers the selected-repo installation, mints an installation
  token in memory, reads `ghadfield32/llm_station`, and reads check/status
  endpoints. The operator-approved `issues: read` permission is now recorded in
  `configs/autonomy.yaml`, and repository permission verification passes.
  Branch-wall approval remains blocked separately: app-token branch-protection
  inspection returns 403 by design, while the owner/admin observer run now shows
  `main` has no classic protection and no active branch ruleset. Do not add
  Administration permission to the app only to inspect settings.
- **Staging AppFlowy target.** `configs/autonomy.yaml` now selects
  `mission_intake` / `card-review q3 odds metrics` from
  `generated/board-snapshot.json` as the staging candidate for future no-op
  desktop/kanban tests. The live snapshot now proves the card exists and is
  `In Progress`; live desktop actions are still disabled until timeout,
  takeover, and evidence policies are declared.
- **Runtime completion gate.** The Ledger now exposes
  `POST /mission/{id}/verify-completion`, which reads mission forecast/action/
  verification events, requires evidence refs, compares observed vs expected
  state, blocks exact repeated action signatures, writes
  `mission.completion_verdict`, and marks the mission `done` only on PASS.
  The generic `/mission/{id}/status` endpoint rejects direct `done` updates.
- **What remains.** The next ordered work is now in `configs/autonomy.yaml`:
  declare desktop timeout and human-takeover policy before live actions, enable
  the desktop target only after timeout/takeover and canary policy are declared,
  derive loop-breaker policy from event history before GUI autonomy, enable
  canaries only after blockers clear, decide whether OpenTelemetry is needed
  after structured-event gaps are measured, and evaluate external runtimes only
  after a measured control-plane gap.

### 2026-06-16 — Whole-system validation prompt added

- **What changed.** Added
  [whole-system-validation-prompt.md](whole-system-validation-prompt.md), a
  reusable mission prompt for proving the whole pipeline rather than one
  subsystem: self-improvement, AppFlowy kanban control, registered desktop repo
  autonomy, progress notification, local-only model routing, memory/knowledge
  reuse, fail-closed behavior, and privacy.
- **Forecast-first testing.** The prompt requires every state-changing action to
  record expected state, expected events, allowed fields, expected no-change
  boundaries, privacy boundary, and rollback plan before execution, then compare
  observed state to the forecast and classify drift.
- **No hidden shortcuts.** It preserves the existing constraints: no provider
  fallback, no fake metrics, no hardcoded thresholds, no guessed prices/statuses
  or model fit, no raw secret/private transcript retention, no agent
  self-approval, and no promotion without validate/evals/canary telemetry,
  independent verification, and human approval.
- **Next use.** The next broad readiness pass should run this prompt and produce
  a single evidence package under `evaluation/system-validation/<run-id>/`, then
  update this MASTER section and the remaining-order list with the exact gaps.

### 2026-06-16 — Explicit JSON model-benchmark protocol and live audit refresh

- **What changed.** JSON-scored live model benchmark cases now require
  `response_format: json` in `configs/model-benchmarks.yaml`; validation rejects
  missing JSON mode for JSON checks and rejects JSON mode on non-JSON cases. The
  live harness sends declared JSON cases to Ollama with `format: "json"` and
  still stores only hashes, booleans, runtime metrics, and equivalence metadata.
- **Real LLM evidence.** Re-ran the isolated metric audit with `reps=2` after
  the protocol change. Sample counts, metric/sample math, artifacts, and
  redaction all passed. The audit exposed real role failures rather than hiding
  them: `chat` and `planner` invalid_response_rate stayed at `1.000`; `local-
  judge` and `security-judge` were `0.750`; `triage`, `coder`, and
  `architect-judge` were `0.000`.
- **Candidate evidence refreshed.** Re-ran the lower-context coder audit for
  `qwen3-coder:30b` vs `devstral:24b` under the current benchmark config hash.
  Context was fit-derived at `40806`. The result remains `revise`: required
  quality metrics tied, safety held, Devstral did not improve any required
  non-safety metric, and runtime evidence favored qwen3-coder on this suite.
- **Current next step.** Structured-output role behavior is now the next
  Proposed experiment: compare prompt/protocol/model/context variants on
  synthetic or public cases, keep malformed/empty JSON-mode responses as failed
  samples, and do not add permissive parser fallbacks.

### 2026-06-15 — Deep live model audit and metric-gate hardening

- **What changed.** Hardened baseline/candidate equivalence so the runner now
  compares the full harness-owned equivalence key, not only retrieval-specific
  corpus fields. A changed live benchmark config, suite hash, endpoint hash,
  model id, commit, or evaluated context now excludes the candidate run.
- **Metric correctness.** Added direct tests for JSON scoring, invalid-response
  scoring, forbidden-marker safety, metric-tag aggregation, redacted stdout, and
  prompt-leak rejection. Added `model_metric_audit` to rerun live incumbent
  suites in an isolated audit Ledger and verify sample counts, metric/sample
  math, artifacts, and redaction.
- **Context correctness.** Added explicit `model_benchmark.context_length`
  support to the live harness. When present, it is passed to Ollama as `num_ctx`
  and stored in the equivalence key. Invalid context values fail before any run.
- **Candidate audit.** Added `model_candidate_audit` for one isolated
  role/incumbent/candidate check. It requires either an explicit context or
  explicit fit-derived inputs (`fit_ctx` and `gpu_budget_gb`) and never edits
  routing, starts canary, or promotes.
- **Real LLM evidence.** Ran `model_metric_audit` with `reps=2` across all seven
  roles on local Ollama. Every audit passed sample-count, metric math, artifact,
  and redaction checks. Then ran an isolated coder audit:
  `qwen3-coder:30b` vs `devstral:24b`, context `40806` derived from current
  VRAM fit evidence. The candidate tied task success and safety metrics but was
  slower, so the result is `revise`, not promotion evidence. The independent
  verifier reproduced candidate metrics and verified candidate artifacts by hash.
- **Recommendation gate.** Fixed the comparison recommendation so `promote`
  requires a real positive improvement on at least one required non-safety
  metric. Passing only by tie/no-regression now returns `revise`.
- **Validation.** `uv run cc validate`, focused model/runner/discovery tests
  (51 tests), full `uv run pytest` (586 tests), and `uv run ruff check src
  tests` passed. The full test run still reports one existing Starlette/httpx
  deprecation warning in `tests/test_agent_kanban_ui.py`.
- **Current next step.** Do not canary Devstral from this evidence. Either add
  richer coder fixtures and a declared specialization hypothesis, or find a
  scored open-weight candidate that fits the required context and can show a
  measured primary-metric improvement.

### 2026-06-15 — Curated open-weight source and real incumbent baselines

- **What changed.** Added the `curated-openweight` scout source and
  `configs/model-scout-curated-openweight.yaml` as the first scored,
  provenance-resolved source. The source joins public benchmark evidence to an
  exact installed Ollama tag and digest, then exports only role-bound Proposed
  candidates.
- **Source provenance.** The first curated record is `devstral:24b` for the
  `coder` role. It records license, Ollama tag, digest, quant, parameter size,
  native context, benchmark name/version, score definition, retrieval timestamp,
  source payload hash, source model id, source model URL, and model-card payload
  hash. Negative tests cover digest mismatch, unknown role, and license
  conflict.
- **Scout-to-scan proof.** The latest scout report contained five candidates and
  the feed contained one scored open-weight record. The daily scan consumed
  `generated/model-scout-feed.json` and produced one `Proposed` model experiment
  only. No candidate was promoted, verified, or canaried.
- **Real LLM baselines.** Added `command_center.improvement.model_baselines` and
  recorded one local Ollama pilot baseline for each role: triage, chat, planner,
  coder, local-judge, security-judge, and architect-judge. Ledger artifacts were
  written as redacted stdout, metric summaries, and equivalence metadata.
- **Privacy check.** Baseline artifacts were scanned for raw prompt/output
  fixture markers; none were found in the Ledger artifacts.
- **Validation.** `uv run cc validate`, focused model-scout/live-benchmark/
  baseline/discovery tests (33 tests), full `uv run pytest` (577 tests), and
  `uv run ruff check src tests` passed. The full test run reported one existing
  Starlette/httpx deprecation warning in `tests/test_agent_kanban_ui.py`.
- **Current blocker.** `devstral:24b` is scored and provenance-clean, but the
  current 64k fit check says `NO @ 64k` on the 24 GB budget. The next A/B must
  either use an explicitly declared lower-context coder specialization or choose
  a different scored candidate that fits the declared context.

### 2026-06-15 — Trusted metric policy for open-weight LLM upgrades

- **What changed.** Reviewed the trusted-metrics attachment against the current
  open-weight discovery loop and added the role-specific metric board to §5.4:
  triage/planner, coder, local judge, long-context repo reader, and terminal
  agent are evaluated separately rather than collapsed into one "best model"
  number.
- **Metric hierarchy.** The model-upgrade lane now documents primary metrics,
  hard non-regression metrics, and supporting runtime metrics. Promotion
  evidence must be incumbent-relative and role-specific; public leaderboard
  scores remain proxy evidence.
- **Source trust.** The doc now separates benchmark-only, provenance-only, and
  promotion-grade evidence. A source can suggest what to test, but only local
  A/B artifacts plus validate/evals/canary telemetry/independent verification
  and human approval can justify a routing change.
- **Privacy and leakage control.** The benchmark rule is explicit: synthetic or
  public tasks first, hashes instead of raw prompts/outputs, local-only traffic
  unless explicitly approved, and isolated execution for risky coding or
  terminal evals.
- **Code alignment.** Model-scout scan findings no longer invent fixed
  confidence/priority constants for open-weight candidates. The finding derives
  confidence/readiness from the actual provenance fields present and still only
  drafts a Proposed live benchmark.
- **Validation.** `uv run cc validate`, focused live model/discovery/model-scout
  tests (25 tests), broader improvement/discovery tests (77 tests),
  and `ruff check` on the touched source/tests passed. A temp model-scout JSON
  and feed run succeeded; the feed stayed empty because no scored open-weight
  source is currently configured.
- **Remaining order.** Add a scored open-weight source with explicit provenance,
  collect incumbent baseline distributions by role, then benchmark candidates
  against those incumbents before any canary or human promotion decision.

### 2026-06-15 — Open-weight model discovery feed and live benchmark harness

- **What changed.** `model-scout` now defaults to an open-weight candidate
  filter, writes `generated/model-scout-feed.json` for the daily scan, and adds
  provenance fields for local Ollama tags: license when known from
  `configs/models.yaml`, tag, digest, size, quant, parameter size, native
  context, VRAM fit, max fitting context, and headroom. Candidates without
  explicit/local weight evidence are filtered out of the feed. Local tags
  without causal-LM attention metadata are not treated as LLM candidates.
- **Self-improvement link.** `ModelRegistryScanner` now accepts
  `model_scout_candidate` feed records and drafts only `Proposed` model
  experiments for scored open-weight candidates. It does not claim that a model
  is better until a local role-specific benchmark runs.
- **Benchmark path.** Added validated `configs/model-benchmarks.yaml` and the
  `command_center.improvement.live_model_benchmark` harness. Live benchmark
  experiments must declare role, suite, baseline model, candidate model, suite
  path, and local Ollama endpoint in structured experiment parameters. Runner
  artifacts store redacted logs, metric summaries, and equivalence metadata in
  the Ledger; raw prompts and model outputs are not retained.
- **Validation.** `uv run cc validate` passed. Focused tests passed:
  `uv run pytest tests/test_model_scout.py tests/test_discovery_sources.py
  tests/test_live_model_benchmark.py` (25 tests). A temp live scout JSON/feed
  run succeeded; its feed was empty because the available scored source did not
  prove open-weight status and installed local tags were unscored.
- **Decision.** Scout, scan, benchmark, canary, and promotion remain ordered and
  human-gated. No provider route, provider key, auto-promotion, fake score,
  hidden fallback, or raw transcript retention was introduced.

### 2026-06-14 — Continuous upgrade loop Mission 1 implemented + validation passed

- **What changed.** Created the continuous-upgrade evidence set under
  `evaluation/continuous-upgrade/`: baseline, machine-readable baseline,
  capability register, and Mission 1 artifacts for config-derived Judge Gate
  routing (`GAP.md`, `EXPERIMENT.md`, `experiment.yaml`,
  `THREAT_PRIVACY_AUTHORITY.md`, `ROLLBACK.md`, `RESULTS.md`,
  `VERIFIER_REPORT.md`). Implemented Mission 1 by moving Judge Gate classify
  route aliases into `configs/gates.yaml`, requiring them in the gates schema,
  cross-checking them against `configs/models.yaml`, and making Judge Gate load
  the route map from mounted config at startup.
- **Baseline.** Current branch is `feat/agent-kanban-surface` at
  `da28b6dd7f864e62b177bc2b9cd90d19049877de` with a dirty worktree. Baseline
  commands passed before implementation: `uv run cc validate`; `uv run cc
  mission-dryrun`; `uv run cc evals`; focused pytest for routing, safety,
  sealed evals, and improvement lifecycle = 39 passed. Full suite, live smoke,
  and Growth OS selftest were not run in this pass and are not claimed.
- **Validation.** Post-change `uv run cc validate`, `uv run cc mission-dryrun`,
  and `uv run cc evals` passed. Focused route/Judge Gate startup tests passed
  (16 tests); wider focused safety/sealed-eval/improvement tests passed
  (50 tests); `ruff check src services tests` passed; `mypy` passed for the
  touched schema file; full `uv run pytest` passed (562 tests, one existing
  Starlette/httpx deprecation warning). Broad `mypy src` still has existing
  repo-wide typing issues and is not claimed as passing.
- **Decision.** Mission 1 is `INDEPENDENT_VERIFICATION_PASSED`, not promoted.
  The first independent verifier found the implementation/security acceptable
  but returned `FAIL` because status docs were stale; the first re-check
  returned `PASS_WITH_LIMITATIONS`; after the remaining stale backlog text was
  corrected, the final narrow re-check returned `PASS`.
  No external router, provider key, hook, daemon, MCP registration, fake metric,
  hidden fallback, raw transcript retention, or sealed-eval exposure was
  introduced.
- **Reconciliation.** The uploaded AI packages/tools notes are treated as
  inventory. MASTER remains implementation truth: Hermes is deferred, LiteLLM
  remains the only model gateway, Ledger remains the state authority, and Judge
  Gate remains the review/classification service.

### 2026-06-14 — Routing/performance candidate batch evaluated

- **What changed.** Added
  [routing-performance-candidate-evaluation-2026-06-14.md](routing-performance-candidate-evaluation-2026-06-14.md),
  a read-only, one-by-one evaluation of Puppetmaster, codebase-memory-mcp,
  Semble, abtop, asm, ClawCodex, Agno/GitWiki, SIA, MAPPA, generic multi-agent
  frameworks, dbt Wizard / dbt Agent Skills, OpenClaw / Docker Model Runner,
  Google ADK, BigQuery Agent Analytics, A2UI, BigSet, agentcookie,
  Git/Markdown knowledge, verifier loops, and Hermes/WebUI ideas against this
  system's routing/performance path.
- **Decision.** No external runtime/router/control plane should be adopted for
  core routing. The first native routing fix is complete: Judge Gate's inline
  risk-to-alias route table now comes from validated config. The remaining
  ordered work is to add typed Ledger route artifacts, classify failures, and
  feed measured artifacts into the existing `routing` improvement target only
  after a benchmark plan exists.
- **Conditional pilots.** `codebase-memory-mcp` is the only new external tool
  worth a performance benchmark now, and only in binary-only/manual/read-only
  mode with no auto config, MCP registration, hooks, instruction edits, or UI
  daemon. abtop stays opt-in/read-only; Semble stays blocked on its measured
  large-repo/symlink/pinning issues.
- **Pattern-only decisions.** Borrow artifact/failure ideas from Puppetmaster,
  per-event attribution from MAPPA, branch-reviewed knowledge projection from
  Agno/GitWiki, declarative UI ideas from A2UI, and backend benchmark ideas from
  Docker Model Runner. Reject or defer control-plane/runtime adoption for
  ClawCodex, OpenClaw, generic agent frameworks, SIA-in-production, BigSet, and
  agentcookie.

### 2026-06-14 — Broad AI-agent idea evaluation prompt added

- **What changed.** Added
  [agent-ideas-evaluation-prompt.md](agent-ideas-evaluation-prompt.md), a
  copy-paste mission prompt for evaluating ClawCodex, Agno/GitWiki, SIA, MAPPA,
  codebase-memory-mcp, dbt Wizard, RamiKrispin/local-ai-server, BigQuery Graph /
  ADK / A2UI / BigSet, agentcookie, and generic multi-agent frameworks against
  this system before any install or adoption.
- **Baseline preserved.** The prompt treats this repo's current contracts as the
  source of truth: `configs/*.yaml` + Pydantic validation, LiteLLM as the single
  model gateway, Ollama as the local runtime, Claude Code primary with Codex as
  fallback/verifier, Judge Gate, Ledger, Growth OS/AppFlowy, GitHub wall,
  one-worktree leases, and the human-gated improvement loop. It corrects stale
  "Hermes as primary" assumptions from older brainstorming notes.
- **Data discipline.** No hardcoded thresholds, fake values, optimistic
  estimates, silent fallbacks, provider keys, global hooks, raw transcript
  retention, production secrets, or hidden eval leakage. Unknown values stay
  `unknown`; metrics, sample counts, budgets, and stop rules must be declared in
  the experiment contract or benchmark plan before a run.
- **Order of work.** Phase 0 inventory/baseline; Phase 1 read-only experiment
  plans; Phase 2 isolated pilots; Phase 3 feature-flag integration; Phase 4
  monitored canary; Phase 5 human promotion; Phase 6 cleanup/negative-result
  memory. Use [capability-evaluation-loop.md](capability-evaluation-loop.md) for
  the detailed staged execution once a broad idea is selected.

### 2026-06-14 — Kanban row powers extended + validated across agent surfaces

- **What changed.** Added three real, schema-derived Kanban powers to the shared
  `growthos.actions` layer and exposed them through the local assistant,
  GatewayCore channel tools, MCP, and the in-app console governed action list:
  `annotate_item(database, title, note)` appends dated Notes without clobbering;
  `set_item_field(database, title, field, value)` changes real schema fields
  such as Section, Area, Priority, Risk, Due, Tags, Pillar, Format, Module,
  Action, Acceptance, and Owners; `remove_item_field_value(database, title,
  field, value)` removes one exact value from grouped text fields such as Tags,
  Topics, Owners, and Media without clearing the field.
- **How it stays careful.** Field names, field types, and select options are
  read from `appflowy_kanban/growth-os/config/schema.yaml` (including
  `*_board` and `*_content` templates), not invented in prompts. Status/column
  movement remains routed through `move_item` or lifecycle verbs. Approval,
  row-key, writeback, and generated fields (`Status`, `CardKey`, `Key`,
  `MissionID`, `LastSync`, `Created`, etc.) are not editable through the generic
  field tool. If a row's stable key cannot be determined, the write refuses
  rather than risking a duplicate row.
- **Honest boundary.** This does **not** pretend to change AppFlowy board
  view-layout/group-by/visual formatting: the current REST client writes row
  fields, not view settings, and existing setup scripts already document that
  board grouping must be set in the UI. Blank field clearing is also not
  claimed because the current client intentionally drops empty writes; removing
  a free-text grouping is supported only when another grouped value remains,
  while select fields must be changed to another valid option.
- **Validation.** Focused tests passed: `pytest tests/test_actions_intent.py
  tests/test_agent_kanban_ui.py` = 42 passed. Broader surface tests passed:
  `pytest tests/test_gateway_toolcall.py tests/test_memory.py
  tests/test_board_state.py tests/test_kanban_surface.py
  tests/test_tool_safe_roles.py tests/test_actions_intent.py
  tests/test_agent_kanban_ui.py` = 89 passed. Full suite passed: 555 passed.
  `ruff check` passed on all touched code/tests.
  `uv run cc validate` passed (config validation, cross-refs, render,
  forbidden-provider gate). Live/read-only abilities smoke passed 24/24 via the
  shared logged dispatch (`scripts/test_abilities.py`): all five hops live,
  field-edit verbs present, no approve verb, and 31 tools wrapped by the
  agent-call log. Structural exposure check passed: assistant tools + GatewayCore
  dispatch both include memory and all three Kanban field verbs; in-app governed
  actions include all three field verbs. Live read-only GatewayCore multi-turn
  check passed: one conversation recalled a marker on turn 2 with zero tools; a
  fresh conversation abstained with zero tools; no board or memory writes.
- **Tracker synced.** The detailed agent-kanban tracker now carries the same
  row-power contract and honest AppFlowy REST boundary:
  [AGENT_KANBAN_SURFACE.md](backend/projects/AGENT_KANBAN_SURFACE.md).
- **Scratch hygiene.** The sandbox-created `.codex_tmp/` pytest directory was
  ACL-owned by the sandbox identity and could not be deleted by the normal user;
  it is now ignored as local scratch so it cannot pollute git status or
  repo-corpus hash tests.
- **Left in order.** (1) Verify AppFlowy REST support for clearing values and
  view-layout/group-by changes before adding those powers. (2) If verified, add
  a narrow view-layout tool with explicit schema/API evidence and tests. (3)
  Feed real action outcomes into the existing data-derived Kanban tuning path;
  no speculative learner or fake threshold before that signal exists.

### 2026-06-14 — Puppetmaster reviewed as a routing reference, not adopted

- **Decision.** Added §5.1: Puppetmaster is **BORROW_PATTERN_ONLY** for
  auditable routing artifacts, rejected-route reasons, failure classification,
  and typed worker outputs. It is **not** adopted as a runtime router because
  that would duplicate LiteLLM/Judge Gate/Ledger authority, add hooks/MCP
  auto-invocation, and re-open provider-API routing this repo forbids.
- **Safety/data boundary.** The borrowed artifact shape may store bounded
  metadata, config hashes, real LiteLLM usage fields when present, redacted
  evidence references, outcome, confidence, and sha256. It must not retain raw
  transcripts, secrets, `.env` content, provider tokens, hidden eval content,
  or full secret-bearing diffs.
- **Ordered backlog.** Mission 1 is complete: Judge Gate's risk→alias mapping is
  now data-derived from validated configs. The next work is linear: add Ledger
  routing artifacts; then feed those artifacts into the existing `routing`
  improvement target once a declared fixture/statistical plan exists; only then
  consider a one-mission Puppetmaster adapter spike with hooks disabled and no
  provider keys. No defensive fallback, fake cost, invented threshold, or
  speculative learner is permitted along that path.
- **Checks run before this doc update.** `uv run cc validate` passed;
  `pytest tests/test_routing.py tests/test_model_scout.py tests/test_vram.py`
  passed (29 tests); `pytest tests/test_all_target_types.py
  tests/test_improvement_lifecycle.py tests/test_promotion.py
  tests/test_experiment_runner.py` passed (47 tests).

### 2026-06-14 — durable memory WIRED into the live gateway + validated 8/8 (deep + cross-conversation)

Applied the wiring the 2026-06-13 entry below built + staged, and validated it live end-to-end.
Memory now works through the real gateway — the cross-conversation gap from the multi-turn proof
is closed in production.

- **Wired at the root, mirroring `board_state`.** `core.py` loads `self.memory_cfg` once in
  `__init__` (right after `load_tool_layer` puts growthos on the path, like `self.board_knobs`) and
  re-injects via `_memory_messages(query) -> list[dict]` at turn start + mid-loop on memory's **own**
  refresh cadence (guarded against a 0 cadence exactly like the board's `refresh and …`).
  `assistant.py` registers the `remember`/`forget` verbs in `TOOL_FNS` + a SYSTEM instruction;
  `collect_memory_state(query, cfg)` takes the config (loaded once, not per call). No defensive code:
  fail-loud-render mirrors `board_state`, the cadence guard mirrors the board's, the embedder fails
  loud, the store is per-owner + curated-only. Patch doc marked applied:
  [memory-integration-patch.md](memory-integration-patch.md).
- **Live-validated 8/8** (real `qwen3:30b` + `nomic-embed-text` + AppFlowy board). **S1**: remembered
  in conversation A → recalled "black, no sugar" in a **fresh** conversation B → `forget` propagated to
  D. **S2**: a 7-turn conversation recalled focus + deadline at turn 7. **S3**: facts saved in **three
  different conversations** all recalled in a 4th. **S4**: recall used **zero tools** (pure
  re-injection, confirmed via `run_turn_events`). The store held only curated facts (no transcripts),
  with the agent self-tagging facts to the `betts_basketball` project. **Definitive deep proof**: a
  fact stated at turn 1, after enough turns to evict it from the `deque(12)` rolling window, was still
  recalled in the same conversation — `in_deque=False` + recall succeeded + fact in store ⇒ provably
  from memory, not history.
- **Hygiene.** The S2 agent over-eagerly staged 2 mission cards + 1 todo on the real board (it read
  failing-DAG context and acted); **reverted** to Backlog/Todo (the pre-existing `geo_social_pipeline`
  Ready card left untouched). **No memory leak**: tests isolated `memory.db` to a temp dir
  (`GROWTHOS_STATE_DIR` verified to take effect); production `_state/memory.db` has **0 rows**.
- **Gates.** ruff clean on all applied files; 39 hermetic tests green (21 memory + 18 vram); full
  suite exit 0; `core.py` adds no new mypy errors (the growthos imports match the pre-existing
  pattern; only the pre-existing line-73 `logged` typing remains, not mine).
- **Backlog (worked 2026-06-14; ordered, each with its real blocker — nothing built speculatively):**
  1. **Per-conversation project scoping — DEFERRED (no data-derived source yet; not a fabrication).**
     The store + `retrieve(project=…)` support it and are tested, but there is no clean source for a
     conversation's *active project* today: the channels are general-purpose (no inherent project); a
     per-channel `project` config would touch ~6 agent-surface files for a feature **no channel uses**
     (dormant ⇒ speculative); inferring it from the text is guessy; and an agent `focus(project)` verb
     can't work because the tool layer is conversation-agnostic (tools get `name`+`args`, never the
     `conversation_id`). Meanwhile **relevance already separates projects softly** — a betts fact won't
     surface for an unrelated query — so `project=None` is *correct* for general channels. **Activation
     path when wanted:** introduce a project-specific channel, add an optional `project` to its
     `channels.yaml` spec, thread it `GatewayConfig → collect_memory_state(project=spec.project or None)`.
     That is an operator/product decision (which channel is project-scoped), not code I should invent.
  2. **Sharing-vs-acting — PARTIALLY ADDRESSED 2026-06-14.** Refined the memory SYSTEM instruction
     (`assistant.py`): "simply sharing a fact is NOT a request to create/stage/change a board card or
     todo — remember it and reply; touch the board only when the user asks." A live re-run of the exact
     S2 trigger now made **zero board writes** (vs S2 staging cards) — suggestive, but one turn is noisy
     (LLM variance) and proactive `remember` stays model-dependent (explicit "remember X" is the reliable
     path, proven 8/8). The broader board action-bias is still the **agent-surface session's** persona to
     fully tune.
  3. **Learned retrieval-weight tuner — BLOCKED on a usefulness signal.** A tuner needs
     `(query, injected facts, was-it-useful)`; the **usefulness label is not logged and has no clean
     source** (no explicit feedback; `forget` is only weak negative signal). Prerequisite, in order:
     define + log a usefulness signal, let it accrue, *then* the abstain-until-it-beats-the-config-
     baseline tuner (same discipline as the cadence learner). Building it now would be a learner with no
     signal — not done.
  4. **Router learned pre-router — DEFERRED** (data-gated; the cascade covers it until escalation data
     justifies it), per the prior router decision. Unchanged.
  No defensive code, no hardcoded thresholds, no fabricated values, no leakage at any step — and,
  deliberately, **no speculative plumbing for sources that don't exist yet.**

### 2026-06-13 — durable cross-conversation memory (built + proven), embedder VRAM budget, router decision

Executes the `memory_state` design the multi-turn analysis pre-specced (see the entry below
and [agent-multiturn-and-memory.md](agent-multiturn-and-memory.md)). The board already carried
durable *work state* across conversations (board_state); this adds durable *conversational*
memory the same way.

- **Memory subsystem — built, tested, proven live (not yet wired).** New
  [growthos/memory.py](../appflowy_kanban/growth-os/growthos/memory.py) +
  [config/memory.yaml](../appflowy_kanban/growth-os/config/memory.yaml): `remember(fact)` /
  `forget(fact)` intent verbs (siblings of `stage_card`/`reject_card` — the agent saves a
  *curated* fact by explicit intent; nothing is auto-harvested from raw conversation, so there
  is **no leak surface**) plus a `collect_memory_state` re-injection that mirrors `board_state`.
  Backed by a per-owner SQLite store with the real local `nomic-embed-text` (reused from
  score.py). It keys on a **stable owner, not the conversation id** — that is what makes recall
  cross-conversation (a fresh conversation has a new id but the same owner) and it survives a
  restart. Retrieval is `cosine × recency-decay`, top-k — no relevance threshold; **fails loud**
  if the embedder is down (no keyword/recency degrade). Every knob is required in `memory.yaml`
  (no hidden code default). 21 hermetic tests ([test_memory.py](../tests/test_memory.py)) + a
  live real-embedding proof: a fact saved in conversation A is recalled in a **fresh** conversation
  B, survives a store restart, is superseded by `forget`, and is project-scoped — with **no
  cross-project or cross-owner leak**.
- **Wiring staged, not applied.** The two touchpoints (`core.py` memory_state injection,
  `assistant.py` verb registration) are the agent-surface session's hot files (core.py was being
  edited minute-by-minute), so the ~10-line, pattern-anchored patch is staged in
  [memory-integration-patch.md](memory-integration-patch.md) to apply once that session lands.
  Coordination rule held — none of their files were touched.
- **Embedder charged against the GPU budget (applied).**
  [vram.py](../src/command_center/registry/vram.py) gained `resident_weight_gb` (data-derived
  from `/api/ps` ground-truth → `/api/tags` weights + the CUDA baseline, **never a hardcoded GB**)
  and a `reserved_gb` term threaded through the fit math; `model-fit --reserve-model
  nomic-embed-text` now sizes chat models *after* the resident embedder. 5 new tests. Live: the
  embedder reserves **1.1 GB** (0.3 GB weights + the CUDA baseline) — small enough that it does
  not flip any verdict; a 30B-Q4's fit stays context-bound (it holds ~29k ctx on the 24 GB card
  with the embedder resident, and is NO at the full 65k default). The gate now charges for the
  embedder instead of assuming it free — the number is data-derived, not asserted.
- **Router decision — keep the spine, defer the pre-router.** The stack already runs the two
  strategies the current router literature rates highest: domain routing (the `roles` map) and
  cascading (stuck-escalation, local → Claude Code/Codex on *observed* failure). LiteLLM stays the
  gateway. A learned complexity *pre-router* (wrap `ulab-uiuc/LLMRouter` or RouteLLM, trained on
  the escalation + Ledger outcome logs already being collected) is **deferred until it can beat the
  cascade on a temporal holdout** under the existing promotion wall — abstain-until-better, can only
  improve on the baseline, never regress. No build now; collect the signal first.
- **Left, in order:** (1) apply the staged wiring patch when the agent-surface session lands, then
  run the post-apply two-conversation check; (2) optional — give `memory_state` its own
  refresh cadence + thread a per-conversation project context; (3) accumulate escalation data, then
  add the pre-router only once it beats the cascade. No defensive code, no hardcoded thresholds, no
  fabricated values, no data leakage at any step.

### 2026-06-13 — Chat bot full-capability pass: research comprehension (`read_item`), capability-tiered prompt, proactive updates (`cc notify`)

Once the tool-call leak was fixed (entry below), made the bot able to do work at
**every tier**, not just board hygiene. Data-derived scope: grepped which tools
each capability needs; only three real gaps existed (the repo-work loop was
already wired end-to-end). Nothing breaches the approval wall — the bot still only
DRAFTS and MONITORS; executors complete gated missions.

- **Understand papers/repos (`read_item`).** New read-only tool in
  `growthos/actions.py` (+ `TOOL_FNS`): returns ONE row's full detail (abstract,
  score, curator "suggested-for", url) so the bot can actually explain/triage an
  item, not just list titles. Exact match → else closest candidates (never a
  silent guess). Verified live end-to-end: asked to explain a paper, the bot
  called `read_item` and summarized it + flagged it suggested for betts_basketball.
- **Capability-tiered system prompt (`channels/core.py build_system`).** Rewrote
  the terse prompt to enumerate all four tiers (boards · research · awareness ·
  repo work) and HOW to drive repo work: `add_mission_card(section, action,
  acceptance, risk, repo)` → human drags to Approved → gated Ledger mission →
  executor (Claude Code/Codex) completes it → `mission_status` to track. A model
  only uses abilities its prompt names. Verified: asked to fix a failing betts DAG,
  the bot drafted a card (section DAGs, repo betts_basketball, measurable
  acceptance, L2) with the approve-to-dispatch handoff — write intercepted, no
  junk card on the board.
- **Proactive updates (`cli/notify.py`, `cc notify` / `make notify`).** Channels
  are reactive; this is the one job that messages YOU: composes the daily brief
  headline + active Ledger missions and posts to your Discord channel. "Active" =
  `board_state.LIVE_COLUMNS["missions"]` (one source of truth, no re-listed
  literal). Fail-loud on missing creds / unreachable Ledger (never a fake
  all-clear). Run it on a host schedule like the kanban bridge. Verified: real
  push of a 1237-char digest (2 active missions) to the channel.
- **Repo-work loop confirmed already wired:** "Betts Basketball" is a kanban
  section (`configs/kanban.yaml`) → repo `betts_basketball`; the bridge turns an
  Approved card into a gated mission an executor runs. The bot's part (draft +
  monitor) is what the prompt now teaches.
- Tests: `tests/test_actions_intent.py` (+read_item), `tests/test_notify.py` (5).
  Full suite 541 pass (1 pre-existing flake, passes in isolation, untouched code).
- **Follow-ups resolved (2026-06-13):** (1) **`cc notify` schedule — documented**
  as a run-yourself `schtasks`/cron one-liner in `docs/channels.md`, mirroring the
  kanban-bridge/snapshot tasks; agents do not self-install host persistence (§13),
  so the one command is yours to run. (2) **`read_item` extended to `notes`** —
  verified live; its valid set is now `STATUSES | {notes}` (`READABLE_DBS`), since
  notes is a real content board with no Status workflow. (3) **kanban.yaml risk
  strings — no change needed:** `RiskTier` values literally ARE `L0_read_only`…
  `L4_dangerous`, so kanban.yaml's `L2_local_edits` is the canonical enum value
  (the bridge also accepts the agent's short `L2`); shortening it would break the
  `KanbanSection` contract. Not a defect — the earlier note was speculative.
- **Only genuinely-open item:** you run the `cc notify` schtasks one-liner once to
  make the daily push automatic (until then it's `cc notify` on demand).

### 2026-06-13 — Discord bot leaked raw `<function=..>` XML — root-caused to qwen3-coder's Ollama tool parser; chat surfaces moved to a `chat` (qwen3) role

**Symptom.** The Discord bot replied with raw tool-call markup
(`I found "Alan Turing: The Enigma"… <function=book_note><parameter=…>…</tool_call>`)
instead of acting on the kanban. The local AppFlowy assistant never had this.

**Root cause (reproduced, not guessed).** Discord routed through role `triage` →
`ollama_chat/qwen3-coder:30b`. qwen3-coder's Ollama Modelfile carries
`RENDERER/PARSER qwen3-coder` (a compiled-in native parser for its
`<tool_call><function=..><parameter=..>` XML); its Go template has **no** tool
handling. When the model writes a sentence of narration *before* the call
(which it does naturally), that native parser fails to extract the block, dumps
prose+XML into `message.content`, and returns `tool_calls: []`. `core.py` then
treats the markup as a final answer and sends it to Discord. qwen3 / devstral
use Ollama's Go-template tool path, which parses calls regardless of surrounding
prose. The local assistant works because it runs **qwen3:8b**, not qwen3-coder.
Measured, narration induced: qwen3-coder **7/8** (Ollama) and **6/6** (full
LiteLLM path) leaked; qwen3:30b **0/8**. Fix verified e2e via `model=chat`: **0/4**.

**Scope — which roles actually tool-call (data-derived).** Grepped every model
call: only `channels/core.py` (chat) and Hermes (`HERMES_DEFAULT_MODEL=planner`)
pass `tools` through LiteLLM. `judge_gate` uses JSON-mode completion (no tools);
no local code tool-calls `coder`/`architect-judge`/`security-judge`. So qwen3-coder
is correct for those (plain completion) and only the **chat** and **planner**
roles needed to move off it. `triage` (judge-gate JSON) is unchanged.

**Fix (data-derived, no patching).**
- `configs/models.yaml`: new `chat` role → `qwen3:30b` (tool-robust, fits 4090);
  `planner` moved off qwen3-coder → `qwen3:30b` (+ `devstral:24b` cross-family
  failover) because Hermes tool-calls through it. Both documented off-limits to
  qwen3-coder. `triage`/`coder`/judges keep qwen3-coder (no tool-calling).
- `configs/channels.yaml`: all chat channels `model: triage` → `model: chat`.
- `channels/core.py`: final answers run through `_clean()` (strip `<think>`,
  parity with the assistant); a **fail-loud tripwire** (`_leaked_tool_call`) now
  refuses to forward unparsed tool-call markup — it logs the evidence and returns
  a diagnostic naming the cause + fix, so a future fragile-model regression is
  loud, never silent.
- `cli/check_cross_refs.py`: new `check_tool_safe_roles` makes the fix
  self-enforcing — `make validate` FAILS if a chat channel's role or `planner` is
  ever backed by a qwen3-coder-family model (prefix match, so future tags too).
- Rendered + restarted LiteLLM (`chat` + new `planner` live in `/v1/models`);
  `make validate` green. Verified live (narration induced) via `model=chat` and
  `model=planner`: **0 leaks, 23 tool calls parsed**. Tests:
  `tests/test_gateway_toolcall.py` (5) + `tests/test_tool_safe_roles.py` (5).
  Everything stays local (qwen3/devstral on Ollama) — fail-closed invariant kept.

### 2026-06-13 — LinkedIn content pipeline (two AppFlowy content boards + official-API publisher)

A Claude-Code-authored content operation for **geoffhadfield32** (personal) and
**World Model Sports LLC** (company Page), shipping through LinkedIn's **official**
Posts API — no scraper, no third-party scheduler, content never leaves the box.
Full design in §6.6; what's left (all user-credential prerequisites) in §9.

- **Boards.** `content_template` added to `growth-os/config/schema.yaml`; new
  `scripts/new_content_board.py` (create + reconcile, mirrors `new_project.py`)
  stamped `geoffhadfield32_content` and `world_model_sports_content` — Grid +
  Board view, 3 columns **In Queue → In Progress → Completed** (the only kanban
  the user asked for). A `Key` field round-trips the writeback `pre_hash`.
- **Contract.** `ContentConfig` (+ `ContentSource`/`ContentStatuses`/`LinkedInApi`/
  `LinkedInAccount`) in `schemas/contracts.py`, file `configs/content.yaml`, wired
  into `cc validate`. Endpoints/scopes/statuses are config; the LinkedIn-Version
  header has **no code default** (always explicit). `.env.example` gains the
  `LINKEDIN_*` keys; secrets are named-not-stored.
- **Client + publisher.** `src/command_center/linkedin/` (3-legged OAuth + text
  post for member & organization authors; raises loudly, never fakes a publish)
  and `cli/linkedin_publish.py` (dry-run default · `--login` · `--apply`). Mirrors
  the kanban bridge: reads each board, ships only `In Progress` rows with
  `ScheduledFor <= now` and empty `PostURN`, stamps `Completed` + `PostURN` +
  `PublishedAt` by `Key`. Temporal-safe; failures stay In Progress and retry.
- **Seed.** 60 real, **source-attributed** drafts (30/account, derived from
  llm_station, betts_basketball, bball_homography_pipeline, Growth OS curriculum)
  in `config/content_seed/*.json`, loaded by `scripts/seed_content.py` (clobber-safe
  insert-only, 1/day) as **In Queue**. Verified live: 30+30 rows, publisher reports
  **0 due** (the human approval gate holds).
- **One path, no external MCP.** `.mcp.json` registers **no** posting MCP — the sole
  publish path is `linkedin_publish`. An external posting MCP would be a second route
  bypassing the board gate + a second token store; the `stickerdaniel` scraper can't
  post anyway. Future conversational control = a thin MCP over *our* publisher.

**Hardening pass (same day, after external review):**

- **LinkedIn-Version fix.** `202506` is **June 2025** (YYYYMM), sunset 2026-06-15 —
  corrected to **`202605`** (current Latest). Comment now flags the YEAR+MONTH format
  and the ~12-month sunset; it must be re-checked before going live.
- **Anti-double-post.** New `linkedin/ledger.py` — a durable `PublishLedger`
  (`generated/linkedin-published.json`) marks each Key PUBLISHING→PUBLISHED around the
  POST, so a post whose AppFlowy writeback failed is reconciled, never re-sent; an
  ambiguous send (timeout) → `RECONCILE_REQUIRED`, never auto-retried. A
  `ProcessLock` (OS advisory, no stale timeout) stops overlapping scheduler runs.
  `tests/test_linkedin_publish.py` 6/6 (gate, temporal safety, ledger, lock).
- **Least privilege + secrets.** Scopes trimmed to posting-only (dropped `email`,
  `r_*_social`); the OAuth token store + ledger + lock added to `.gitignore`
  (token = secret). `--apply` prints token expiry each run (60-day token).

### 2026-06-14 — agent kanban surface: Phase 6 usability round 4 (inline field editing)

- **Edit any field from the card drawer.** Each field gets an inline `edit` (→ governed `set_item_field`) and an
  "+ Note" box (→ `annotate_item`, clobber-safe), built on the field-editing verbs a concurrent session added.
  Adjust Priority/Area/Risk/Due/Tags/etc. on any board at any time. Verified live: `Priority=P3` set; **Status
  edit refused** ("use move_item"); **invalid `P9` rejected** with the data-derived allowed set
  `['P0','P1','P2','P3']`; note added; reverted. The wall holds (Status/keys not editable here; protected fields
  server-refused). Frontend-only (uses existing `/api/action`); SPA recompiled clean.

### 2026-06-14 — agent kanban surface: Phase 6 usability round 3 (drag-and-drop)

- **Drag-and-drop on the Boards kanban.** Cards drag between columns; dropping calls the governed `move_item`
  and the live board refreshes. The card-details dropdown does the same (the earlier "won't let me" was the
  absence of drag, not a backend bug — `Ready -> In Progress` verified working). **The wall holds through drag**:
  dropping onto `Approved` is refused with a clear message (human-only), shown as a toast. Verified live:
  drag→In Progress reflected on the live board; Approved drop refused; reverted.
- **Clarity** — Missions is labeled the gated execution lane (open → Ledger to approve/kill); Boards →
  mission_intake is where you move work freely; a live/snapshot label on the board. SPA recompiled clean.

### 2026-06-13 — agent kanban surface: Phase 6 usability round 2 (formatting + detail)

- **Stack-health topbar.** New `/api/status` runs real liveness probes (Ledger; + LiteLLM + AppFlowy when the
  console is on) — live: `{ledger: ok, litellm: ok, appflowy: ok}`. The topbar shows a colored dot per hop +
  last-updated + a manual refresh button. A hop is "ok" only if it answered (no fabrication).
- **Nav counts** for quick orientation; **persistent chat** (the Chat view stays mounted so the conversation
  survives view switches); **Escape** closes any drawer.
- **Richer mission drawer** — colored event timeline with timestamps, an Approvals section, and an "Open in
  Ledger to approve / kill" link for L3/L4 / awaiting-approval (the signed path stays in the Ledger UI).
  `test_agent_kanban_ui` 15/15; ruff clean; SPA recompiled clean.

### 2026-06-13 — agent kanban surface: Phase 6 fix+polish (from the live visual pass)

- **Governed writes now work.** The visual pass surfaced two real bugs: the in-app channel logs every tool call
  (like Discord) but the agent-call log was mounted `:ro` (→ `Read-only file system`), and AppFlowy was unreachable
  from the container (growth-os/.env `localhost:8081` = the container, not the host). Fixed: log mount `:rw`;
  `APPFLOWY_BASE_URL=host.docker.internal:8081` (the Ollama pattern). Verified live: `stage_card -> Ready`,
  `move_item -> Backlog`, HTTP 200, board reverted.
- **Observable agent chain.** `load_tool_layer(surface)` records each channel's calls under its own surface; in-app
  calls now show as `app` in Activity (verified). `/api/action` routed through the logged dispatch (was bypassing
  the log).
- **Adjust any board, see it at once.** `board_view` carries each board's full legal statuses; the card drawer
  gains a "Move to…" dropdown (→ `move_item`) for EVERY board + quick verb buttons for cards/todos. `/api/boards/live`
  (console-only) reads AppFlowy live so a write reflects immediately; the drawer refreshes after each action.
- **Chat polish.** Cleaner tool-call rendering (verb + arg) + a clear button. `test_agent_kanban_ui` 14/14; ruff
  clean; SPA recompiled clean (caught a missing import before merge).

### 2026-06-13 — agent kanban surface: Phase 6.4–6.6 (the console becomes a channel — chat, writes, streaming, SMS)

- **In-app chat + governed writes + model pick (6.4).** The UI is now a first-class **channel**: `/api/chat`
  embeds the same `GatewayCore` Discord uses, so you talk to the agent in-app and it moves/assigns tasks through
  the **governed action layer**; `/api/action` exposes the governed verbs directly (card action buttons). You
  **pick the model role per turn** (validated against `models.yaml` — no free-form model). Gated by
  `KANBAN_UI_CHAT_ENABLED`: off ⇒ the read-only board deployment holds **no creds**; on ⇒ the full console mounts
  growth-os + `.env` (the trust fork). **L3/L4 approve/kill never reach the browser** — the action verbs refuse
  Approved structurally. **Live-verified**: the in-app agent answered "1 mission awaiting approval" correctly from
  the injected board state, and `approve_card` was refused (400).
- **Live streaming (6.5).** New `GatewayCore.run_turn_events` async-generator + `/api/chat/stream` (SSE) stream
  each step — round / tool call / tool result / final — so you watch the LLM work live. **Verified**: events
  stream as they happen.
- **SMS + multi-channel (6.6).** New `channels/sms.py` (Twilio webhook → `GatewayCore` → REST reply); `sms` added
  to the `ChannelSpec` transport literal (the runner auto-dispatches it); a disabled `sms-main` in `channels.yaml`.
  Agents are now reachable from Discord/Slack/Telegram/WhatsApp/**SMS** + **in-app**. **Phone access** = the
  responsive console over Tailscale (6.1). SMS needs Twilio creds + a public webhook to run (like WhatsApp).
- **Standards held:** writes governed (no Approved/L3/L4 in the browser); model list + router data-derived from
  config; chat gated so the secure read-only default holds no creds; SSE errors surfaced as events, never
  swallowed; fail-loud throughout. `test_agent_kanban_ui` 19/19; `make validate` green; ruff clean; SPA recompiled
  clean. Remaining polish (tracker §8): per-board move UI for the long-tail boards, token-level streaming, SMS
  live test once Twilio creds exist.

### 2026-06-13 — agent kanban surface: Phase 6.1–6.3 (operator console — redesign, deep detail, router)

- **Console redesign (6.1).** The UI is now a left-nav multi-view console — **Missions · Boards · Router ·
  Observability · Activity** — responsive for phone (`@media` collapses the nav, stacks columns, full-width
  drawer), with per-view filtering (free-text + risk). Rebuilt + live on `127.0.0.1:8787`.
- **Deep detail (6.2).** `actions.board_view` now carries every scalar card field; clicking ANY item opens a
  drawer — missions show status/risk + the event timeline, AppFlowy cards show **all fields** (where it is, what
  it is). Snapshot regenerated against live AppFlowy (cards carry CardKey/Section/Risk/Acceptance/Action/…).
- **Router / agent-chain (6.3).** New `/api/models` reads `models.yaml` + `judges.yaml` (configs mounted RO) —
  live: **7 roles, 2 executors, 9 judge stages**, all data-derived (no hardcoded model names). The mission drawer
  surfaces the per-mission routing chain from `model_call`/`judge_verdict` Ledger events.
- **Standards:** still **read-only** (writes/chat are the planned 6.4 fork); router/lanes data-derived from real
  config + real events; fail-loud (missing config/snapshot = loud 503). `test_agent_kanban_ui` 12/12; ruff clean;
  SPA recompiled clean (caught + fixed two TS strict errors before merge). Plan for 6.4 (in-app chat + governed
  writes + model pick), 6.5 (live streaming), 6.6 (SMS/multi-channel): tracker §8.

### 2026-06-13 — agent kanban surface: Phase 5 (parity — AppFlowy breadth + Cline depth)

- **Parity review.** Measured the surface against the two yardsticks (AppFlowy availability+databases,
  Cline look&feel for agent use) and closed the gaps. Full review + per-use-case verdicts in
  [backend/projects/AGENT_KANBAN_SURFACE.md](backend/projects/AGENT_KANBAN_SURFACE.md) §6.
- **5.1 — regression fixed.** Dropping `set_status` (Phase 2) had removed the agent's ability to triage
  papers/repos/signals and update library/lessons status. New title-addressed `move_item(database, title,
  status)` restores action on **every** board with statuses — loud validation, harness owns the key, Approved
  still structurally refused. Dedicated verbs remain the ergonomic path for cards/todos. (`test_actions_intent` 13/13.)
- **5.2 — AppFlowy database breadth in the UI, with NO creds in the UI container.** `actions.board_view()` +
  `board_state.all_boards_json()` produce a structured read of every board; `make kanban-board-snapshot` runs on
  the **worker** (where AppFlowy creds live) and writes `generated/board-snapshot.json`; the UI mounts that file
  **read-only** and serves `/api/boards` (frontend board tabs: mission_intake/todos/dags + research inboxes).
  Snapshot freshness shown; missing snapshot = loud 503. Resolves the creds-in-container tradeoff (same pattern as
  the agent-call log). Per-board fail-loud.
- **5.3 — Cline depth.** `/api/activity` (recent agent actions, newest-first, from the agent-call log) drives an
  activity feed; mission cards are now clickable → a **detail drawer** (`/api/mission/{id}` status/risk/events with
  per-kind tags). (`test_agent_kanban_ui` 10/10.)
- **Standards held:** every read fail-loud; snapshot per-board errors recorded never hidden; UI stays read-only
  (no write path); no new deps. `make validate` + `make kanban-surface-validate` + full pytest + ruff green.
- **Live-verified.** Snapshot CLI now self-bootstraps growth-os (sys.path + CWD at the growth-os root) so
  `make kanban-board-snapshot` produces real data — ran it: 6 boards, 0 errors (dags 87, papers 68, repos 55,
  signals 56, cards 12, todos 8). Freshness via a **user-run** schtasks/cron (agents don't self-schedule, §13).
  `docker compose --profile ui up agent-kanban-ui` built (SPA compiled) + healthy on 127.0.0.1:8787; all
  `/api/*` endpoints returned live data and `/` served the built SPA. Only a human eyeball at the URL remains.

### 2026-06-13 — agent kanban surface: Phase 4 (first-party Cline-styled web UI)

- **The styling, combined.** New optional service `services/agent_kanban_ui/` fills the
  already-budgeted Phase-4 WebUI slot — repurposed from the deferred Hermes WebUI. A FastAPI
  backend serves a React/Vite/TypeScript SPA (Cline-style dark board: missions grouped into
  status columns with risk-colored cards + an observability panel) **single-container** (the SPA
  is built in a node stage and served as static assets), behind loopback/Tailscale/password.
- **Read-only by construction.** It reads the **Ledger** (missions = the execution kanban) and the
  **agent-call log** (metrics, via the same `command_center.kanban.metrics` as `make kanban-digest`,
  so UI and CLI can't disagree). There is **no write path**: approving/killing stays in the signed
  Ledger endpoints (the HMAC secret is never given to the UI), so `external_write_policy:
  governed_by_ledger` holds by construction. AppFlowy stays the human staging surface. Ledger-down
  is a loud 502, never an empty board.
- **Wiring.** `configs/ui.yaml` block + `WebUIConfig` field renamed `hermes_webui` → `agent_kanban_ui`
  (contract unchanged); `docker-compose.yml` service behind `profiles: ["ui"]` (loopback-bound,
  agent-call log mounted read-only, healthcheck); multi-stage Dockerfile (node build → python serve).
  Backend `tests/test_agent_kanban_ui.py` 5/5 (grouping, unknown-status disclosure, 502-not-empty,
  metrics reuse, read-only). `make validate` + `make ui-validate` green; ruff clean. The SPA build
  runs in the Docker node stage (authored this session; not npm-built here).

### 2026-06-13 — agent kanban surface: Phases 1–3 (the function half — harness-owned state, intent verbs, observability)

- **Phase 1 — the harness owns board state.** New `src/command_center/channels/board_state.py`
  re-injects the live board (open cards/todos/missions, grouped by column, overflow disclosed) into
  BOTH agent loops every turn ([channels/core.py](../src/command_center/channels/core.py),
  growthos `assistant.py`) so the model never calls `list_*` just to remember the board — the Cline
  focus-chain pattern. Fail-loud: an unreadable source renders an explicit `ERROR:` line, never an
  empty/stale block. Cadence/size/fuzzy knobs are externalized to a new validated `configs/agent_surface.yaml`
  (`AgentSurfaceConfig`, in `make validate`). `tests/test_board_state.py` 7/7.
- **Phase 2 — intent verbs replace generic CRUD.** `actions.py` gains `stage_card/block_card/reject_card`
  and `start_todo/finish_todo/block_todo`, addressed by title (the harness owns the board, the canonical
  column, and key resolution — `_resolve()` fuzzy-matches with a data-derived ratio and returns candidates
  on a miss, never a silent guess). Generic `set_status` dropped from BOTH agent surfaces (assistant
  `TOOL_FNS` + MCP registrations); it stays for the bridge/scripts. Approved remains structurally human-only.
  `tests/test_actions_intent.py` 7/7.
- **Phase 3 — observability + data-derived tuning.** The existing agent-call log (`growthos.observability`
  → `_export/agent_calls.jsonl`) is reused as the event spine — no parallel store. New
  `src/command_center/kanban/` computes real metrics (redundant-call rate, intent-verb adoption, error/latency),
  a champion–challenger `fuzzy_min_ratio` learner that **abstains below the decision floor** (mirrors the
  discovery scan's `acceptance.py`; temporal split, no leakage), a Markdown digest, and a blocking N/N gate.
  `make kanban-digest` + `make kanban-surface-validate` (6/6 PASS — the gate caught a real verb→terminal-column
  bug before merge). `tests/test_kanban_surface.py` 9/9.
- **Standards.** All knobs in `configs/agent_surface.yaml` (no literals); decisions data-derived or honestly
  abstaining (no fabricated cadence); fail-loud (no silent fallbacks); no leakage (pre-decision features only);
  AppFlowy/Ledger keep write-authority. `make validate` green · full suite green · ruff clean · mypy
  baseline-consistent. Tracker: [backend/projects/AGENT_KANBAN_SURFACE.md](backend/projects/AGENT_KANBAN_SURFACE.md).
  **Phase 4 (the first-party Cline-styled web UI in the repurposed WebUI slot) is the remaining, separable lift.**

### 2026-06-13 — agent kanban surface: Phase 0 (decision + tracker + doc reconcile)

- **Direction set.** The fix for "agents don't drive the AppFlowy board well" is to invert who owns board
  state (adopt Cline's harness-owned-state + intent-verb pattern), keep AppFlowy/Ledger as the data/authority
  layer, add a data-derived observability lane, and put a first-party Cline-styled board + observability UI in
  the **already-budgeted** Phase-4 WebUI slot (`configs/ui.yaml` / `WebUIConfig`) — repurposed from the
  now-deferred Hermes WebUI/Kanban. Not a §13 "another abstraction layer": it fixes a failure actually hit and
  adds no competing authority boundary. Ordered plan + standards-conformance matrix:
  [backend/projects/AGENT_KANBAN_SURFACE.md](backend/projects/AGENT_KANBAN_SURFACE.md).
- **Doc reconcile.** Stale Hermes-WebUI references corrected to the first-party repurpose:
  `configs/ui.yaml` comment, [ui-options.md](ui-options.md) dashboard table, [ecosystem.md](ecosystem.md)
  banner. The `WebUIConfig` contract (loopback/password/`governed_by_ledger`/single-container) is unchanged;
  the block key renames to `agent_kanban_ui` in Phase 4. Docs-only; no code/config-value change yet.

### 2026-06-13 — Cline CLI + Ollama evaluated → DEFER (watch-list)

- **Cline CLI (Ollama `ollama launch cline`) assessed against the stack → DEFER.**
  Cline is an *executor* (read repo / edit files / run commands / diffs, plus a
  local per-task kanban) — a peer to Claude Code and Codex CLI, **not** to
  Command Center. As a replacement for the control plane it's a strict
  downgrade: it brings none of the L0–L4 wall, Judge Gate, Ledger/leases,
  one-mission→one-worktree isolation, proactive/RCA lane, or the kanban→Ledger
  bridge (its kanban has no approval wall). As an alternate *executor* it's only
  marginally interesting and is Phase-4 "only when a need is actually hit"
  territory — Claude Code already covers primary coding, the `coder` alias covers
  local. Its `--model …:cloud` path would also break the no-provider-keys,
  fail-closed local-only contract. Less differentiated than the Hermes spike,
  which was already deferred — so an easier DEFER by the same yardstick. Recorded
  in §13. No code, config, or dependency change.

### 2026-06-13 — agent abilities verified + centralized agent-call logging

- **One action layer, three surfaces, all logged.** Confirmed the Discord agent, the MCP/Claude
  agent, and the local `chat.bat` assistant all dispatch through the *same* 20-tool layer
  (`growthos/actions.py`); the model picks the tool. New `growthos/observability.py` wraps every
  surface's dispatch so **every tool call is recorded** (surface · tool · truncated/secret-safe
  args · ok/error · latency) to one JSONL; `python -m growthos.observability` is the live monitor.
- **Abilities proven.** `book_note` exercised live on *Alan Turing: The Enigma* (5 dated notes,
  persisted + read back). New `scripts/test_abilities.py` drives each query tool ≥5 ways and the
  approval wall ≥5 ways through the logged dispatch — **25/25 PASS, 9 tools routed, every Approved
  attempt refused**. Hermetic test `tests/test_agent_observability.py` (4/4).
- **Board layout — resolved (no destructive flatten).** The queue→in-progress→complete flow is
  delivered by the agent-kanban-surface session as lifecycle *intent verbs* (`stage_card`,
  `start_todo`, `finish_todo`, `block`/`reject`) over the existing statuses, so the semantic boards
  keep their lifecycles and the wall is now *structural* — there is **no `approve` verb**. Verified:
  `test_actions_intent.py` (14) + `test_abilities.py` (23/23: query tools routed, wall holds, all
  24 tools logged).
- **Self-improve daily → human-gated Kanban card.** New `discovery/kanban.py` +
  `improvement scan --kanban` drafts the top findings as `mission_intake` Backlog cards (Section =
  Command Center, risk mapped from the finding's tier to L0–L4, fails loud on an unmappable tier —
  no fallback); the daily DAG drafts them each morning behind `SELF_IMPROVEMENT_KANBAN` (off by
  default). Observer-only — a human drags to Approved → the bridge opens a gated mission → applied.
  Proven live (a "remove swallowed exceptions" card on the board). Tests: `test_discovery_kanban.py`
  + `test_dag_support.py`; tracker [SELF_IMPROVEMENT_PIPELINE.md](backend/projects/SELF_IMPROVEMENT_PIPELINE.md).
- **Multi-turn + cross-conversation memory — proven & assessed.** A live 6-message conversation
  through the shared `GatewayCore` (`model: chat` → `qwen3:30b`): read 13 cards → drafted a card →
  **recalled it with no tool call** (within-conversation memory) → "stage *that* card" → "reject it"
  (context resolution + the structural wall, no `approve` verb), then a *fresh* conversation id that
  could **not** recall the draft and answered from the re-injected board instead. That pins the model:
  board/work state is durable & shared across conversations (via `board_state` over one AppFlowy
  board), but conversation history is per-conversation `deque(12)`, in-memory, lost on restart. All
  four channel adapters (discord/slack/telegram/whatsapp) wire to this same core + `chat` role, so the
  proof covers every channel; only Discord is live. Assessment + tiered, data-derived recommendation
  (instrument first via the agent-call log; `memory_state` re-injection if cross-chat reference shows
  up; persisted histories for restart-durability — no leakage, no hardcoded thresholds):
  [agent-multiturn-and-memory.md](agent-multiturn-and-memory.md).

### 2026-06-13 — OKF knowledge bundle + dashboards on the tailnet

- **OKF knowledge producer.** New observer-only subsystem `src/command_center/knowledge/` (+ the
  `knowledge` CLI / `make knowledge-generate|validate`) that reads authoritative sources (configs,
  the Ledger, code, DAGs) and writes a Git-backed `knowledge/` bundle of OKF concepts under a strict
  `growth-os-0.1` profile. Source systems produce OKF; OKF never modifies them (every concept is
  `authority: derived` and points at its source). Clobber-safe generated/human split; data-derived
  freshness (no timestamp churn on unchanged source); a blocking N/N validation gate (frontmatter,
  source-path existence, link resolution, secret scan). First generation: 14 concepts, 7/7 PASS.
  Design: [knowledge-format.md](knowledge-format.md).
- **Dashboards on the tailnet.** Airflow / Ledger / LiteLLM / Uptime-Kuma now served over Tailscale
  (8443 / 10000 / 11000 / 12000) — tailnet-only, verified reachable. [remote-access.md](remote-access.md) updated.

### 2026-06-13 — self-improvement scan: data-derived ranking + delivery + standards pass

- **Data-derived ranking.** Every scan decision moved out of code into `configs/discovery.yaml`
  (`DiscoveryConfig`, in `make validate`) — no inline literals. Added `improvement/discovery/
  acceptance.py`: a pure-Python logistic `P(accept)` learner from the Ledger's card accept/reject
  history (leakage-controlled features, temporal split, champion–challenger vs the ICE/RICE/WSJF
  formula; abstains below a documented sample floor). Records features at draft time (the feedback loop).
- **Delivery.** `improvement/discovery/delivery/` — an email digest (stdlib SMTP; dry-run writes
  HTML, fail-loud on missing creds), a one-line chat ping, and a `Pillar` column on the Kanban board
  for per-pillar swimlanes. CLI flags `--email/--board/--ping` + a new-since-yesterday diff.
- **Standards (principles-only).** Module-tree + 5-stage header on `pipeline.py`; a blocking
  `improvement scan-validate` gate (10/10 — asserts the observer wall + no-leakage); a report
  manifest sidecar (sha256 + provenance). Verified the `docs/backend/` R2/fleet/Railway/medallion
  standards are the betts pipeline's and **don't apply here** (no such infra) — applied only the
  transferable principles. Tracker: `docs/backend/projects/SELF_IMPROVEMENT_PIPELINE.md`.
- **Zero new deps**; full suite + ladder (validate · scan-validate · evals) green; ruff + mypy clean.

### 2026-06-13 — model-selection track + routing check + Hermes spike

- **WS1 hardware-fit selector.** `registry/vram.py` (GQA-aware VRAM formula off Ollama
  `/api/show` + `/api/tags`, `/api/ps` ground-truth) + `cli/model_fit.py` + `make model-fit`
  + `tests/test_vram.py`. Budget reads `gpu_vram_gb` (new `EnvironmentSpec` field) from
  `environments.yaml`. Live finding: the 30B incumbents need ~39k ctx (not 64k) on the 4090.
- **WS2 model scout rewrite.** Fixed 3 bugs (dead source-gate, archived HF leaderboard,
  AA-shaped score keys); keyless-first sources (Aider polyglot + Ollama tags, AA optional via
  `AA_API_KEY`); every candidate annotated with the WS1 fit gate. `tests/test_model_scout.py`.
- **WS3 confirmed pre-built** — the `model` target was already wired end to end (harness,
  adapter, `EXP-model-ref`, parametrized lifecycle test); no new code. Deleted the dead
  `llama3-groq-tool-use:70b` (can't fit 24 GB).
- **Routing check.** Coding is executor-driven (Claude primary, Codex cross-provider fallback);
  local models never do primary coding. Added judge-route cross-ref validation to
  `check_cross_refs.py` (a typo'd `escalation_role` was unchecked) + `tests/test_routing.py`.
- **WS4 Hermes spike → DEFER.** Ran v0.16.0 isolated (local Ollama, no keys). Cross-session
  memory PASS (local `MEMORY.md` — not beyond-stack); self-improving skills FAIL (curator
  auto-created 0 skills). The "phantom image" note (§ above) is now corrected. Evidence under
  `evaluation/capability-assessment/hermes/`; tested `safety_preflight.py` corrected to the real
  v0.16.0 schema (the drafted `data_collection` key does not exist).
- **Roadmap.** `docs/system-roadmap.md` is the consolidated whole-system map; `STATUS.md` tracks
  the tactical order. Track A (model selection) + the routing check are complete.

### 2026-06-12 — docs consolidated to one setup path

- **Four overlapping setup docs became one.** `runbook.md` (phases + daily flow),
  `COMPLETE-SETUP.md` (prior master map + buy checklist; stale at "ten config files"),
  and `SETUP-REMAINING.md` (remainder checklist + "complete means") were folded into
  `SETUP-FROM-SCRATCH.md` — now the single ordered path from nothing-installed to
  definition-of-done. `growth-os-system.md` (status snapshot) folded into `STATUS.md`.
- **`PREFLIGHT-FIXES.md` retired.** Historical; its "add ANTHROPIC/OPENAI keys" advice
  was already superseded by the local-only correction (recorded below) and keeping the
  file risked someone following it.
- **Stale duplicates removed from disk:** `_staging/` (three pre-`src/`-layout copies of
  this repo). All live references updated (README, this doc, visuals, Makefile,
  autonomy-idea-map, growth-os-engineering, growth-os selftest process check).
  Changelog mentions of the retired files below are intentionally left as history.

### 2026-06-12 — GitHub-ready: src/ layout, multi-channel gateway, hygiene

- **Repo made GitHub-ready.** Comprehensive `.gitignore` (secrets, caches, dumps,
  staging); every secret confirmed ignored via `git check-ignore` before staging;
  stray tarball + egg-info removed; `appflowy_kanban/AppFlowy-Cloud` registered as a
  pinned **git submodule** (was a vendored clone with its own `.git`); MIT `LICENSE`,
  `CONTRIBUTING.md`, and a PR template added.
- **Full `src/` relocation.** `schemas/` → `src/command_center/schemas/`, `registry/`
  → `src/command_center/registry/`, `scripts/*.py` → `src/command_center/cli/`;
  editable-installed package. Every `from schemas import` → `command_center.schemas`,
  `sys.path` bootstraps dropped, `parents[1]` repo-root anchors → `parents[3]`. The
  Makefile, `cc.ps1`, CI, `breakage.yaml`, the evaluation gold-set, and the two
  growth-os cross-imports were all rewired. `pyproject.toml` gains optional-dependency
  groups (gateways, dev), console entry points, and ruff/mypy config; `tests/` + a CI
  lint-test job added; `ruff check src` is clean.
- **Multi-channel gateway.** The Discord gateway became a transport-agnostic
  `command_center.channels.core.GatewayCore`, with real adapters for **Discord, Slack
  (Socket Mode), Telegram (long-poll), and WhatsApp (Meta Cloud webhook)**, a
  `configs/channels.yaml` validated by the new `ChannelsConfig` contract (each
  `channel.model` cross-checked against `models.yaml`), and a runner
  (`python -m command_center.channels [--dry-run] [--channels …]` / `make gateway`).
  The repeat-call breaker and forced-final-answer guards are preserved; selftest now
  points at `core.py`.
- **Docs.** Added `SETUP-FROM-SCRATCH.md`, `channels.md`, `STATUS.md`; refreshed this
  doc's module tree (§11.1), doc index (§12), and the §13 N/A note. Reference
  standards copied into `docs/backend/`.

### 2026-06-12 — capability-evaluation Batch 1 executed

- **Ran the evaluation loop end-to-end** against this repo for semble, abtop,
  asm. Artifacts in `evaluation/capability-assessment/` (baseline, per-candidate
  evidence/threat-model/benchmark/results, raw outputs, independent
  verifier-report, DECISION matrix). Three-role separation honored
  (Investigators + Implementer + a fresh-context Verifier that re-ran critical
  commands and corrected the recall figure from 10/10 to **7/10**).
- Dispositions (measured, not guessed): **abtop → PILOT** (7/7 Claude session
  detection on Windows, read-only verified; Codex 0/4 on Windows is the gap),
  **semble → PILOT** (7/10 NL-query recall, `.env` excluded; the "98% fewer
  tokens" claim did not reproduce vs skilled ripgrep), **asm → DEFER**
  (knocked out — zero skill files exist to manage, no Windows support,
  "signed manifests" claim false).
- Authority boundaries intact: no config/contract/service/agent file modified,
  no MCP registration, no `--setup`, no provider keys, nothing pushed. semble
  in `.venv` only; abtop binary in the eval dir only. Deterministic baseline
  re-verified PASS at the concurrently-relocated `src/command_center/cli/`
  paths. Each PILOT's next step is a separate human-approved L2 mission.

### 2026-06-12 — PILOT next steps (abtop wired · semble blocked on betts · asm parked)

- **abtop**: wired into `src/command_center/cli/usage_digest.py` as an opt-in,
  read-only `--abtop` / `--abtop-bin` section — shells the pinned binary with
  `--json` only (never `--setup`), fail-loud on a missing binary, omitted by
  default. ruff/mypy/compile clean, no new deps, baseline PASS, vendored
  binary gitignored. ADOPT still gated on Codex-on-Windows detection; re-test
  deferred (v0.4.8 is the latest release).
- **semble**: benchmarked on betts_basketball — recall 6/8 (NL search held up),
  but **not pilot-ready there**: indexing crashes out-of-the-box on a WSL
  symlink (`WinError 1920`) and the package was pruned by a concurrent
  `uv sync` (not in `uv.lock`). MCP registration gated on a committed
  `.sembleignore` + a lockfile-pinned install. betts left unmodified.
- **asm**: parked (DEFER) with re-evaluation conditions recorded.
- Full record under `evaluation/capability-assessment/` (DECISION.md is
  authoritative).

### 2026-06-12 — betts standards encoded + capability-evaluation loop

- **`configs/standards.yaml` `python_ml_pipeline` profile expanded** to encode
  the betts_basketball operating contract so every mission renders it into
  `CLAUDE.md`/`AGENTS.md` and Judge Gate cites it: pipeline-template structure
  (module tree + stage registry per doc), temporal-leakage safety,
  R2-as-shared-production-DB rules (validate before / verify after upload;
  never delete `upload.lock`), desktop-4090-writer vs laptop-5080-dev-lane
  fleet split, multi-session git discipline, the uv dependency standard, atomic
  shared-volume writes, serving standards, and done/next doc hygiene.
  Sources: betts `PIPELINE_STANDARDS_TEMPLATE.md`,
  `DATA_ENGINEERING_PIPELINE.md` §0.x, `LOCAL_FLEET_R2_WORKFLOW.md`,
  `UNIFIED_SERVING_GUIDE.md`. Validated (`validate: PASS`) and test-rendered.
- **Added [capability-evaluation-loop.md](capability-evaluation-loop.md)**:
  the staged, evidence-first external-tool evaluation prompt (Stage 0–11,
  three separated roles, knockout gates, A/B benchmarks, chaos testing,
  independent verification, five dispositions), with a Part-A mapping onto
  this stack — entry via kanban/Ledger at L2, cross-provider Verifier,
  local-only-gateway and uv-dependency amendments as knockout criteria —
  and a Part-C pre-registered roster of 13 candidates (Semble, abtop, asm,
  dbt-agent-skills, Puppetmaster, MAPPA, Agno GitWiki, verifier-loop pattern,
  BigSet, BigQuery Graph, SIA, ClawCodex, AgentCookie) with sources, seams,
  stack-specific knockout risks, batch order, and a ready-to-run Batch-1
  mission brief.

### 2026-06-12 — this doc

- **Added `docs/MASTER.md`**: consolidated all 18 docs into one stage-by-stage
  system guide with module tree and this change log.
- Reconciled drift between older and newer docs in favor of current reality:
  LiteLLM is **local-only** (provider keys forbidden, fail-closed), and
  **Hermes is optional/deferred** (phantom image; the live channels are
  AppFlowy boards, chat.bat, Claude-via-MCP, and Discord). Older Hermes-centric
  passages in COMPLETE-SETUP/visuals/runbook describe the optional future
  orchestrator slot, not the present stack.

### 2026-06-12 (late) — context enrichment + loop hardening (Growth OS)

- DAG rows now carry full context every sync (Description, Owners, Tags,
  NextRun from the Airflow API) alongside root-cause Notes — the dags board is
  a self-describing inventory.
- `Suggested` column on papers/repos/signals (`growthos/enrich.py`, curate
  stage 3.5): one ≤35-word "useful for <project>" line per newly kept item,
  local model only, honest by construction; Ollama down → loud warning,
  curation never blocks.
- `book_note(title, note)` tool: dated reading notes on library rows from any
  channel.
- **In-app AppFlowy AI — verdict: blocked upstream** (the `appflowy_ai` image
  license-walls every request despite correct LiteLLM wiring). Container
  stopped; the guidelines feed watches AppFlowy releases for a change.
- Agent-loop hardening after the Discord tool-round stall: loud boundary
  validation on every list tool + deterministic loop-breakers (repeat-call
  message, forced final no-tools answer). `project_status()` one-call context
  pack and `network_health()` 5-hop liveness added. **selftest.py 22/22.**

### 2026-06-12 — local-only correction + live smoke green (Command Center)

- Architecture corrected to **local-only LiteLLM**: every role renders to
  `ollama_chat/...`; OpenAI/Anthropic/OpenRouter deployments are
  contract-rejected; `make forbidden-providers` + live smoke enforce the
  boundary; no cloud fallback — calls fail closed. **This supersedes
  `PREFLIGHT-FIXES.md`'s instruction to add provider API keys.**
- State green on the workstation: digest pinned, virtual keys minted, health
  passing, `live-smoke` printing real local replies, `cc.ps1 check` passing
  (recorded in SETUP-REMAINING.md).
- Hermes made optional in Compose behind a profile (the
  `nousresearch/hermes-agent` image is not published).
- Airflow sync live: 81 DAGs, root-cause failure summaries (deepest
  non-site-packages frame), auto-drafted Backlog fix cards; human-set
  `Retired` rows never touched.
- `mission_intake` gained the writeback fields (MissionID, CardKey, LastSync);
  bridge proven end-to-end: T-b5f2e70f dispatched + written back,
  T-c8e1d7d6 held at the L4 wall. Bridge scheduled q15min (user-run schtasks).

### 2026-06-11/12 (evening) — Growth OS autonomy layer

- Library seeded with the full 275-book curriculum (import idempotent, never
  clobbers Status/Notes).
- Approval made **structurally human-only**: `actions.set_status` refuses
  Approved on every agent surface; bridge applies Approved-only.
- **Discord gateway** built (`services/discord_gateway/`, LiteLLM `triage`,
  same action layer, fail-fast without token).
- Knowledge watchers live: papers/repos/signals hourly (embedding-scored),
  guidelines daily (standards mirror + uv/Airflow/AppFlowy/Ollama release
  feeds), packages (122 direct deps watched, semver-derived severity),
  retention (7d). `projects.yaml` observe-registry added;
  `new_project.py` board stamper proven.
- Decisions recorded: no separate channel service; no agent-installed
  scheduling (classifier-blocked twice, by design); Claude-mobile remote
  connectors can't reach the tailnet (accepted trade).

### 2026-06-11 — v4 contract stabilization (Command Center)

- **Typed contract layer** over the v3 architecture: every `configs/*.yaml`
  validates against a Pydantic model; `extra="forbid"`; cross-file linter;
  JSON Schema rendering for editors; breakage map + `make impact`.
- Added the proactive ops lane (runtime health + repo stewardship + RCA loop,
  eight unsafe-config rejections tested), standards rendering
  (`standards.yaml` → CLAUDE.md/AGENTS.md + Judge Gate), usage digest, and
  propose-only model scout with canary/promote/rollback targets.
- Pre-flight fixes (PREFLIGHT-FIXES.md): `make bootstrap`/`verify-base` to
  break the first-boot key circularity; placeholder digest now **blocks**
  (`verify` exits 1, `up` runs `verify` first); `OLLAMA_API_BASE` wired into
  the litellm service. *(Its provider-key instructions were later superseded —
  see 2026-06-12 above.)*

### Earlier — v3 architecture (carried forward)

- The base design this all stands on: VPS brain · Tailscale mesh · gateway +
  Judge Gate + Ledger · leases · 4090 worker · VS Code tunnel ·
  pre-commit/pre-push judge arrays · L0–L4 gates · GitHub branch-protection
  wall.
- v4 keeps all of it and layers on: the typed contract layer (above), a
  proactive ops lane (DAG/data health + repo stewardship), standards rendering,
  usage digests, and propose-only model scouting. Everything the README once
  filed under "unchanged from v3, still current" lives in this guide now —
  §6 (the five pipelines), §7 (isolation), §8 (the GitHub wall), §5 (model
  lanes), and the doc index in §12. The README no longer tracks the v3→v4
  delta; it points here.
