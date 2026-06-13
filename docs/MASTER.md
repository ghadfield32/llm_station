# Command Center + Growth OS — The Complete System

> **This is the one doc.** It consolidates the `docs/` set into a single
> stage-by-stage walkthrough of the full setup: what the system is, what runs where,
> every pipeline stage, the full module tree with purposes, and a change log.
> Deep-dive references for each section are listed in [§12](#12-doc-index-where-the-detail-lives).
>
> Last full revision: **2026-06-12**. State at that date: local validation green,
> LiteLLM pinned by digest, local models installed, virtual keys minted, live smoke
> passing, Growth OS selftest 22/22, kanban bridge live with writeback.

---

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

The thirteen config files and their contracts:

| File | Governs |
|---|---|
| `configs/models.yaml` | which model each role maps to (local-only, ranked candidates) |
| `configs/judges.yaml` | judge arrays per stage, cross-provider pairing, budgets |
| `configs/gates.yaml` | L0–L4 risk/approval policy |
| `configs/environments.yaml` | one environment per activity, isolation rules |
| `configs/standards.yaml` | durable operating standards for Claude, Codex, and Judge Gate |
| `configs/breakage.yaml` | what ripples when you change a file (powers `make impact`) |
| `configs/proactive.yaml` | scheduled checks on already-done work, RCA caps, daily self-improvement scan |
| `configs/targets.yaml` | the watch inventory: repos, DAGs, data assets, services + SLOs |
| `configs/tools.yaml` | tool permissions the judges can cite |
| `configs/evals.yaml` | routing/judge regression suite = the model-promotion gate |
| `configs/kanban.yaml` | bridge dispatch contract: sections, risk ceilings, ready statuses |
| `configs/ui.yaml` | WebUI safety defaults (single-container, password, ledger-governed writes) |
| `configs/channels.yaml` | chat transports (Discord/Slack/Telegram/WhatsApp) → transport + model alias |

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
| **Discord Gateway** | Discord ↔ LiteLLM (`triage`) ↔ the Growth OS action layer. Fail-fast without `DISCORD_BOT_TOKEN`. |
| Uptime Kuma + restic | Health monitoring and backups. |
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
| **LiteLLM local gateway** | `triage`, `planner`, `local-judge`, `security-judge`, `architect-judge`, `coder` aliases | `HERMES_LITELLM_KEY` / `JUDGE_GATE_LITELLM_KEY` (virtual keys you mint) | $0 |
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
- Local role meanings: `triage` first-pass risk sorting; `planner` plans and
  validation plans; `local-judge` continuous cheap judging; `security-judge`
  local security/scope skeptic; `architect-judge` high-effort planning/debug;
  `coder` dry-runs and fallback summaries (not the executor auth path).

Two Ollama gotchas worth pinning: agents need **≥64k context** (Ollama
defaults to 4,096 — raise `num_ctx`), and Ollama serves **one request at a
time by default** (set `OLLAMA_NUM_PARALLEL` and `OLLAMA_KEEP_ALIVE=-1` so
parallel judge calls don't queue or thrash reloads).

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
- **Self-improvement scan** — daily report + Proposed backlog cards across
  automation, structure, metrics, code quality, standards, data handling,
  net-new ideas, reliability/observability, and cost. It cannot approve, verify,
  promote, canary, merge, deploy, rotate secrets, or execute experiments.
  Implemented as the observer-only Airflow DAG `self_improvement_daily` (+ the
  `improvement scan` CLI / Kanban / Discord touchpoints); full design in
  [self-improvement-dag.md](self-improvement-dag.md).

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
1. make model-scout      → generated/model-scout-report.md (ranked, propose-only)
2. Edit configs/models.yaml with a local Ollama candidate
3. make validate         → license / priority / canary rules
4. make evals            → routing/judge regression suite
5. make models           → render + pull local tags + restart LiteLLM
6. make models-canary ROLE=… MODEL=ollama_chat/<tag>   → small traffic slice
7. make live-smoke       → real local replies
8. compare cost · latency · false blocks · missed issues
9. make models-promote ROLE=…   or   make models-rollback ROLE=…
```

Current local picks: `qwen3-coder:30b` · `qwen3:30b` · `devstral:24b`.
The contract rejects `scout.propose_only: false` and any provider route, so
"swap to the leaderboard top" is structurally impossible.

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

1. **Branch protection on main** — required status checks (`validate / tests,
   lint, typecheck, secret-scan` from `repo-template/.github/workflows/validate.yml`),
   required CODEOWNERS review, linear history, no force-push/deletes.
   `enforce_admins:false` so *you* can fix emergencies; the agent never holds
   an admin token.
2. **Scoped agent token** — fine-grained PAT for MVP: Contents R/W, Pull
   requests R/W, Issues R, Metadata R, everything else No access. Migrate to a
   **GitHub App** (starts with zero permissions) once long-lived.
3. **Deploy = separate human-gated environment** — `production` environment
   with a required reviewer and prevent-self-review; the agent never gets its
   secrets.
4. **In-sandbox command policy** — allow git status/diff/log, grep/find,
   pytest/mypy/ruff, branch + edits, logged dep installs; push only after
   `scripts/pre_push_gate.sh` exits 0; deny reading `.env`/keys, sudo,
   `rm -rf`, `curl|bash`, force push, merge.

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
make model-scout        # discovery report, never auto-promotes
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
│   ├── ui.yaml                 WebUI safety defaults (ledger-governed external writes)
│   └── channels.yaml           chat transports → transport + model alias (tokens stay in .env)
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
│   │   └── kanban_bridge.py    Approved cards → Ledger missions (+CardKey writeback)
│   └── channels/               CHAT TRANSPORTS — one authority, many surfaces
│       ├── core.py             transport-agnostic GatewayCore.run_turn() (LiteLLM tool loop)
│       ├── discord.py · slack.py · telegram.py · whatsapp.py   thin per-platform adapters
│       └── __main__.py         runner: configs/channels.yaml → launch enabled adapters
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
│   └── proactive_runner/       thin scheduler for configs/proactive.yaml checks;
│                               holds no secrets; max action = open a gated mission
│
├── scripts/                    non-Python wrappers: cc.ps1 (Windows), live_smoke.{ps1,sh}
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
└── docs/                       18 docs + this one (see §12)
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
│   └── assistant.py     chat.bat brain: Ollama tool-calling loop with
│                        repeat-call breaker + forced final answer
├── agent/growthos_mcp.py    MCP registration over actions (Claude; stdio or --http)
├── scripts/
│   ├── setup_workspace.py   create/RECONCILE databases from schema.yaml
│   ├── create_views.py      Board/Calendar views (idempotent)
│   ├── import_books.py      data/book-checklist.md → library (never clobbers triage)
│   ├── import_dags.py       dag files → dags board (static inventory)
│   ├── new_project.py       stamp per-project board + validated kanban.yaml section
│   ├── seed_workspace.py    sources mirror + starter todos
│   └── selftest.py          22 live checks across the whole system (target: 100%)
├── config/
│   ├── schema.yaml          database shapes (first select = board grouping)
│   ├── sources.yaml         feeds, interest weights, scoring, retention
│   ├── projects.yaml        ★ OBSERVE registry: repos the watchers watch
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
| [STATUS.md](STATUS.md) | done / in-progress / TODO-in-order — the multi-session work tracker |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | multi-session git safety, engineering standards, the uv dependency workflow |
| [backend/](backend/) | reference standards copied from the betts pipeline (data-engineering, R2/fleet, modeling, serving) — see the N/A note in §13 |
| [visuals.md](visuals.md) | 14 Mermaid diagrams, one per concern |
| [model-routing.md](model-routing.md) | lanes, local roles, fail-closed behavior |
| [model-update.md](model-update.md) | safe model rollout + current local picks |
| [request-routing-examples.md](request-routing-examples.md) | 8 worked examples: request → route → expected response |
| [proactive-ops.md](proactive-ops.md) | proactive lanes, RCA loop, contract-rejected configs |
| [daily-self-improvement-dag.md](daily-self-improvement-dag.md) | observer-only Airflow wrapper plan for daily improvement report + Proposed cards |
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
only) · another abstraction layer unless it prevents a failure actually hit.

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

Newest first. Dates are from the docs themselves; the repo has no git history
yet (first commit pending), so this reconstructs the record the next commit
should preserve.

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
