# System Roadmap — the whole machine, what's done, what's left, in order

> **Archived — dated 2026-06-13, ~3 weeks stale.** The "What's DONE" / "What's
> LEFT" checklists predate the job-search subsystem, the research-digest
> productization, and several completed items (e.g. Discord is live, not
> pending). The "Settled decisions" and "Known non-goals" sections are still
> accurate and have been folded into `docs/MASTER.md` §13. Do not treat the
> checklists below as current status.

_Last updated: 2026-06-13._

The high-level, forward-looking map of the entire system: the control plane, the
knowledge base, the managed projects, and the two-machine fleet. For the tactical
deployment checklist see [STATUS.md](../operations/STATUS.md); for the deep system reference see
[MASTER.md](../MASTER.md). This doc is the strategic "where is this going and what's
the order" — kept high-level on purpose.

**The one boundary that governs everything below:** `llm_station` is a **control
plane**, not a data pipeline. It has no bronze/silver/gold, no R2, no Airflow DAGs,
no GPU training of its own. Its pipeline is `configs/*.yaml → Pydantic contracts →
render/validate → serve`. The medallion / R2 / DAG / serving / Bayesian-GBDT-clustering
standards in [docs/backend/](../reference/betts-basketball-standards/) are **real and authoritative — for the managed
projects** (betts_basketball and its peers). The control plane's job is to *enforce*
those standards on the projects, never to *become* one. See [MASTER.md](../MASTER.md) §13.1.

---

## Module tree (the system, top to bottom)

```text
                        ┌─────────────────────────────────────────────┐
   HUMAN SURFACES       │  AppFlowy / GrowthOS boards (12 DBs)         │  ← you add data here
   (where you live)     │  Discord gateway · chat.bat · Claude-via-MCP │  ← you talk to it here
                        └───────────────┬─────────────────────────────┘
                                        │  Approved cards only
                                        ▼
   ┌────────────────────────────────────────────────────────────────────────────┐
   │  CONTROL PLANE  ·  llm_station  (this repo, src/command_center/)             │
   │                                                                              │
   │   Knowledge base ───┐    Kanban bridge ───┐    Improvement loop ───┐         │
   │   (GrowthOS curator)│    (cards→missions) │    (experiments→canary)│         │
   │                     ▼                     ▼                        ▼         │
   │   ┌──────────────────────────────────────────────────────────────────────┐ │
   │   │  Contracts (schemas/) → Registry (models/scout) → Gates → Ledger      │ │
   │   │  Judge arrays  ·  Channels (core+adapters)  ·  Proactive runner       │ │
   │   └──────────────────────────────────────────────────────────────────────┘ │
   │                     │  LiteLLM (local-only gateway, virtual keys)            │
   └─────────────────────┼────────────────────────────────────────────────────── ┘
                         ▼
   ┌───────────────────────────────┐        ┌──────────────────────────────────┐
   │  MODEL RUNTIME (4090 station)  │        │  EXECUTORS (own auth, not LiteLLM)│
   │  Ollama: qwen3-coder:30b,      │        │  Claude Code (primary)            │
   │  qwen3:30b, devstral:24b       │        │  Codex CLI (fallback)             │
   └───────────────────────────────┘        └──────────────────────────────────┘
                         │  gated missions (one branch/worktree/lease each)
                         ▼
   ┌────────────────────────────────────────────────────────────────────────────┐
   │  MANAGED PROJECTS  (separate repos; govern themselves by docs/backend/)      │
   │  betts_basketball: Bronze→Silver→Gold→dbt→FastAPI→R2  (medallion + DAGs)     │
   │  <future projects>: stamped via new_project.py, standards rendered in        │
   └────────────────────────────────────────────────────────────────────────────┘

   FLEET:  4090 desktop = production R2 writer + heavy model host + scheduler
           5080 laptop  = read-only dev/candidate lane (writes .r2_staging only)
           VPS          = always-on control-plane host (points at 4090 Ollama)
```

**Each block, one line:**

- **Human surfaces** — AppFlowy boards are intake + knowledge; Discord/chat/MCP are conversation. None can approve or execute; they only open cards/missions.
- **Knowledge base** — the GrowthOS curator: deterministic feeds (papers/repos/signals/guidelines/packages) → scored → triaged → optionally a mission. This is the control plane's *only* "data pipeline," and it follows the transferable principles, not medallion/R2.
- **Kanban bridge** — Approved cards become Ledger missions; nothing else dispatches work.
- **Improvement loop** — the contract-driven experiment → baseline-lock → independent verify → human-gated canary → promote/rollback machinery. Model selection rides this.
- **Contracts/Registry/Gates/Ledger/Judges** — the spine: every config is a validated contract; every action has a risk tier and an audit trail.
- **Model runtime vs executors** — local Ollama models (via LiteLLM) do triage/judge/plan; Claude Code/Codex do the hard coding, authenticated on their own subscriptions.
- **Managed projects** — where the real data pipelines live and where docs/backend/ applies in full.
- **Fleet** — the 4090/5080/VPS division and the R2 single-writer discipline.

---

## The knowledge base as an ordered pipeline (control-plane style)

The "add my data and have it stay updated" system already exists as the GrowthOS curator.
Its stages are linear and deterministic — the right altitude for a curation feed (no
medallion, no R2):

```text
S0  sources.yaml         declared feeds (arXiv / GitHub / RSS) + interest profile
      │
S1  fetch                pull new items only; never clobber human triage decisions
      │
S2  score                embed (nomic-embed-text) vs interest profile → relevance
      │
S3  land in AppFlowy     papers / repos / signals / guidelines / packages DBs (Inbox/Review)
      │
S4  human triage         you promote: Saved / Reading / Using / Current  (or Archive)
      │
S5  (optional) mission   a triaged item that needs work → a kanban card → Ledger mission
```

Live today: `guidelines.py` (standards mirror + uv/Airflow/AppFlowy/Ollama release watch),
`packages.py` (6-stage dependency-drift watch), and the 12 AppFlowy DBs (library, lessons,
papers, repos, signals, sources, review, mission_intake, todos, dags, guidelines, packages).

---

## What's DONE (live components)

| Area | Component | Evidence |
|---|---|---|
| Knowledge base | 12 AppFlowy DBs + guidelines/packages watchers | `growthos/guidelines.py`, `growthos/packages.py`, `config/schema.yaml` |
| Project onboarding | `new_project.py` template stamper (board + validated kanban section) | proven, idempotent |
| Kanban → work | Approved-card bridge with writeback | [kanban_bridge.py](../src/command_center/cli/kanban_bridge.py), [kanban.yaml](../configs/kanban.yaml) |
| Conversation | Discord gateway live (Slack/Telegram/WhatsApp ready) | [channels/core.py](../src/command_center/channels/core.py) |
| Standards enforcement | standards.yaml → per-repo CLAUDE.md/AGENTS.md | [render_standards.py](../src/command_center/cli/render_standards.py) |
| Managed project | betts_basketball registered across targets/proactive/kanban/projects | [targets.yaml](../configs/targets.yaml) |
| Improvement loop | experiments → verify → canary → promote/rollback, human-gated | [src/command_center/improvement/](../../src/command_center/improvement/) |
| Self-improvement scheduler contract | daily observer scan, capped to report + Proposed backlog cards | [proactive.yaml](../configs/proactive.yaml), [daily-self-improvement-dag.md](../improvement/daily-self-improvement-dag.md) |
| Model registry | roles → local Ollama models, propose-only scout | [models.yaml](../configs/models.yaml) |

---

## What's LEFT, in order

Ordered by dependency. WS1 gates WS2/WS3; the knowledge-base and Hermes tracks are independent.

### Track A — model selection (so we run the best model the 4090 can hold)
1. **WS1 — Hardware-fit selector. ✅ done.** `registry/vram.py` (GQA-aware formula off Ollama `/api/show` + `/api/tags`, `/api/ps` ground-truth) + `cli/model_fit.py` + `make model-fit` + `tests/test_vram.py`. Budget from [environments.yaml](../configs/environments.yaml) `gpu_vram_gb`.
2. **WS2 — Fix the scout. ✅ done.** [model_scout.py](../src/command_center/registry/model_scout.py) rewritten: 3 bugs fixed, keyless-first sources (Aider polyglot + Ollama tags, AA optional), every candidate annotated with the WS1 fit gate. + `tests/test_model_scout.py`.
3. **WS3 — Evaluate upgrades. ✅ already built.** The `model` target was already wired end to end (`harness_library.ModelHarness` stand-in, model promotion adapter, `EXP-model-ref`, parametrized lifecycle test). Dead 70B deleted. **Remaining:** a live-model A/B harness (env-blocked) + a pulled candidate; interim path is `make models-canary` → `make evals` → `make models-promote`.
4. **Routing check. ✅ done.** Investigated: coding is executor-driven (Claude primary, Codex cross-provider fallback "if Claude stalls"); local models never do primary coding, so they can't flail; `stuck-escalation` escalates *judging* to a stronger local `architect-judge`. Added judge-route cross-ref validation to [check_cross_refs.py](../src/command_center/cli/check_cross_refs.py) (closes the gap where a typo'd `escalation_role` was unchecked) + `tests/test_routing.py` (5 tests).

### Track B — knowledge-base completeness (so "add data, stays updated" runs end-to-end)
5. **Audit the auto-ingest.** Confirm papers/repos/signals feeds are scheduled and actually populating AppFlowy (DBs + sources exist; verify the scheduled curator runs).
6. **Install the daily self-improvement Airflow wrapper.** The control-plane contract is defined as `self_improvement_scans.daily-self-improvement-brief`, and the DAG + pipeline + touchpoint CLI are now **implemented in-repo** (`dags/self_improvement_daily.py`, `src/command_center/improvement/discovery/`, `improvement scan`). The remaining work is purely deployment: copy the DAG into the managed Airflow environment under a low-privilege service identity (read-only on Kanban/Ledger/scan artifacts; write only Proposed cards + one report; no GitHub/deploy/secret/promotion scopes). See [daily-self-improvement-dag.md](../improvement/daily-self-improvement-dag.md).
7. **Watch the AppFlowy-AI unblock.** In-app AI is license-walled upstream; guidelines feed already watches AppFlowy releases. Until then chat.bat + Claude-via-MCP + Discord cover it. No build.

### Track C — Hermes (evaluate, don't adopt)
8. **WS4 — Isolated spike. ✅ ran → DEFER.** Installed v0.16.0 in an isolated venv pointed at Ollama `:11434` direct, no keys. **Cross-session memory PASS** (verified `memories/MEMORY.md`) but it's a local MEMORY.md — not beyond-stack. **Self-improving skills FAIL** — curator auto-created 0 skills ("no candidates"). Rubric gates 1 & 3 fail → DEFER; LiteLLM stays, Hermes stays a note not a container. Evidence: [evaluation/capability-assessment/hermes/DECISION.md](../../evaluation/capability-assessment/hermes/DECISION.md). Tested `safety_preflight.py` (9 green) corrected to the real v0.16.0 schema.

### Track D — deployment (from [STATUS.md](../operations/STATUS.md))
9. Commit + push + PR; bring one channel live; VPS + Tailscale + live-smoke from the VPS.

---

## Standards governance (how docs/backend/ reaches the projects)

The control plane does not run medallion/R2/DAG code — it *propagates* those rules:

- **Authoring:** [standards.yaml](../configs/standards.yaml) `python_ml_pipeline` profile carries the medallion flow, R2 discipline, leakage prevention, GPU-backend verification, uv-pin-then-sync. `render_standards.py` writes it into each managed repo's CLAUDE.md/AGENTS.md.
- **Watching:** [targets.yaml](../configs/targets.yaml) + [proactive.yaml](../configs/proactive.yaml) watch the projects' DAGs/data assets/repos; failures open gated RCA missions.
- **Dispatching:** approved kanban cards → Ledger missions → leased worktrees on the fleet.

**Fleet / R2 / multi-session rules (govern managed-project execution, per [LOCAL_FLEET_R2_WORKFLOW.md](../reference/betts-basketball-standards/LOCAL_FLEET_R2_WORKFLOW.md)):** 4090 desktop is the *only* production R2 writer; 5080 laptop is read-only dev writing `.r2_staging` only; the `upload.lock` is single-writer (TTL 10 min) — **wait for it, never delete it**; validate before *and* after every R2 op; push with exact staging (never `git add -A`); multiple Claude sessions coordinate through git truth + the R2 manifest + the Ledger's one-branch-one-worktree-one-lease invariant. New packages: `uv pip install` → pin range in pyproject.toml → `uv sync`.

---

## Settled decisions (do not re-litigate)

- **AA API key:** not the primary path — keyless-first (Aider polyglot + Ollama tags), AA optional tiebreaker, **your sealed evals decide**, your one tap promotes.
- **VRAM fit:** wrap `quantest` + `gguf-parser-go`, don't hand-roll the formula.
- **Best 24 GB candidate:** Qwen 3.6-27B dense (feed to evals). **Qwen3-Coder-Next rejected** — 80B MoE, won't fit the 4090.
- **Hermes:** evaluate isolated, don't adopt — everything it orchestrates is already covered, and the LiteLLM path is buggy. **LiteLLM stays.** (Hermes Agent is real now, v0.16.0 — the old "phantom image" note is stale.)
- **Separate LLM channel:** no. Discord gateway is the "anywhere" surface; all channels share one action layer.
- **AppFlowy in-app AI:** blocked upstream (license-walled). Covered by chat.bat + MCP + Discord.
- **Claude mobile over tailnet:** doesn't work (cloud connectors can't reach the tailnet). Phone = AppFlowy boards + Discord.

## Known non-goals (don't cargo-cult)

The forecasting standards in [docs/backend/](../reference/betts-basketball-standards/) (R2 locks, DAG run-location, medallion
layers, GPU training, dbt, champion promotion) **do not apply to this control plane** — only
to the managed projects. The transferable parts (no defensive coding, data-derived thresholds,
uv discipline, multi-session git rules) apply everywhere. See [MASTER.md](../MASTER.md) §13.1.
