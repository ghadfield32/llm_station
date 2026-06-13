# Command Center — v4 (contract-stabilized)

> **Start here:** [`docs/SETUP-FROM-SCRATCH.md`](docs/SETUP-FROM-SCRATCH.md) is the ordered cold-start (prerequisites → first boot → channels → definition of done). [`docs/MASTER.md`](docs/MASTER.md) is the consolidated system guide — every pipeline stage by stage, the full module tree with purposes, the doc index, and the change log. This README covers the contract model; those docs cover everything.

```bash
git clone --recurse-submodules https://github.com/ghadfield32/llm_station.git
cd llm_station && uv venv .venv && uv pip install -e .
make validate   # nothing runs until the contracts pass
```

Same architecture as v3 (VPS brain · Tailscale · Hermes · LiteLLM · Judge Gate · Ledger · leases · 4090 worker · VS Code tunnel · pre-commit/pre-push judges · GitHub gates), now with a proactive ops lane (DAG/data health + repo stewardship), standards rendering, usage digests, and propose-only model scouting. v4 adds the thing that makes it **repeatable and hard to break**: a **typed contract layer**. Every editable config validates against a Pydantic model before it can do anything, and a breakage map tells you what ripples when you change something.

Kept **lean on purpose** — a personal command center, not an enterprise platform. Contracts exist where they prevent real breakage: models, judges, gates, environments, standards, proactive checks, targets, tools, evals, and the ledger wire format. No schema file is just a typed restatement of trivial config.

---

## The contract model (the whole idea in five lines)

```
YAML in configs/                          = the editable source of truth
Pydantic in src/command_center/schemas/   = the contract that validates it
generated/            = disposable rendered output (litellm config, json-schema)
ledger SQLite         = the only runtime state
Makefile              = the only interface
```

Rules: secrets never live in YAML; generated files are never hand-edited; a typo fails at `make validate`, not at 2am.

---

## Why this is "hard to break" (proven, not asserted)

`make validate` runs every `configs/*.yaml` through its contract. These bad edits are **rejected before they ship** (all tested):

- a typo'd key (`priorty:`) → rejected (`extra="forbid"`)
- two models with the same priority in one role → rejected
- two canaries in one role, or `canary_weight > 1` → rejected
- a missing risk tier, or **L3/L4 without `requires_approval`** → rejected
- a `repo_task` environment that is persistent or holds secrets → rejected (isolation invariant)

The dangerous mistakes — silently broken routing, an approval gate quietly disabled, a sandbox that leaks secrets — can't be committed.

---

## Layout

**New here? Read [`docs/SETUP-FROM-SCRATCH.md`](docs/SETUP-FROM-SCRATCH.md)** — the ordered
cold-start (prerequisites → first boot → channels). [`docs/MASTER.md`](docs/MASTER.md) is the
deep system guide; [`docs/channels.md`](docs/channels.md) covers Discord/Slack/Telegram/WhatsApp.

```
command-center/
├── Makefile                 # the operator interface (Windows: scripts/cc.ps1)
├── pyproject.toml / uv.lock # installable package; extras: [gateways], [dev]
├── docker-compose.yml       # control plane (LiteLLM pinned by digest)
├── .env.example
├── configs/                 # YAML source of truth (you edit these)
│   ├── models.yaml          #   role -> ranked model candidates
│   ├── judges.yaml          #   per-stage judge arrays, cross-provider
│   ├── gates.yaml           #   risk tiers L0-L4 + approval policy
│   ├── environments.yaml    #   one environment per activity
│   ├── standards.yaml       #   one source for Claude/Codex/judge standards
│   ├── proactive.yaml       #   scheduled checks, usage digest, RCA caps
│   ├── targets.yaml         #   repos/DAGs/data/services to watch
│   ├── tools.yaml           #   tool permissions judges can cite
│   ├── evals.yaml           #   model/judge regression suite
│   ├── breakage.yaml        #   what-breaks-when map (drives `make impact`)
│   └── channels.yaml        #   chat transports -> transport + model (tokens in .env)
├── src/command_center/      # the installable package
│   ├── schemas/             #   Pydantic contracts (base.py + contracts.py)
│   ├── registry/            #   render.py (validate->litellm), model_scout.py
│   ├── cli/                 #   make/`python -m` commands (validate, render, evals, …)
│   └── channels/            #   core.py + discord/slack/telegram/whatsapp adapters + runner
├── generated/               # disposable: litellm-config.yaml, json-schema/
├── services/                # judge_gate (+ judgectl), ledger (missions/leases/approvals/kill), proactive_runner
├── tests/                   # contract regression tests (pytest; run by CI)
├── repo-template/           # per-repo: pre-commit, CI, CODEOWNERS, pre-push gate, devcontainer
├── appflowy_kanban/         # Growth OS curator + AppFlowy-Cloud (pinned submodule)
└── docs/                    # SETUP-FROM-SCRATCH, MASTER, channels, runbook, github-safety, …
```

---

## The interface (every operation)

```bash
make setup           # deps + .env + validate + render + build services
make verify-base     # digest pin + base provider/internal secrets before first boot
make verify          # digest pin + all runtime keys before full stack
make validate        # configs match contracts (the safety net)
make standards-validate
make schema          # contracts -> generated/json-schema (editor autocomplete)
make render          # validate + build generated/litellm-config.yaml
make up / down       # control plane
make keys            # budgeted LiteLLM virtual keys
make health          # all services OK?
make models          # validate+render, pull local tags, restart litellm
make models-canary ROLE=coder MODEL=ollama_chat/qwen3-coder:30b
make models-promote ROLE=coder
make models-rollback ROLE=coder
make impact          # blast radius of your current git diff
make model-scout     # leaderboard/API scan -> generated proposal report
make usage-digest    # LiteLLM spend + Ledger mission summary
make usage-report    # alias for usage-digest
make live-smoke      # real Ollama/LiteLLM replies once keys are wired
make mission-dryrun  # fake L0..L4 missions through gates+judges (no model calls)
make env-smoke       # validate environments + isolation invariants
make repo-install REPO=/path/to/repo
make backup / restore-drill
```

On Windows, use the native helper for local validation and first-boot commands:

```powershell
.\scripts\cc.ps1 init-env
.\scripts\cc.ps1 check
.\scripts\cc.ps1 verify-base
.\scripts\cc.ps1 bootstrap
.\scripts\cc.ps1 verify
.\scripts\cc.ps1 up
.\scripts\cc.ps1 model-scout
.\scripts\cc.ps1 usage-digest
.\scripts\cc.ps1 live-smoke
```

Maintenance surface, in full: **edit a `configs/*.yaml`, run `make validate` then the relevant target.** Add a repo: `make repo-install REPO=...`.

---

## Everything else (unchanged from v3, still current)

- **UI from any device** — `docs/ui-options.md`: Hermes channels (phone), CLI, WebUI/Kanban, VS Code Remote Tunnel + `vscode.dev`, Ledger/LiteLLM/Kuma dashboards, GitHub web/mobile, Codespaces fallback. Agent drives the terminal/worktree; you drive VS Code + dashboards + GitHub.
- **Kanban-driven work** — `docs/kanban-integration.md`: AppFlowy/GrowthOS stays the human task and learning surface; ready cards become Ledger missions through a dry-run-first bridge, then normal leases, judges, and approvals apply.
- **Request lifecycle** — intake → ledger+lease → triage → plan → plan-critic → leased-worktree implement → static checks → pre-commit judge array → commit → pre-push cross-provider skeptic → human approval (L3/L4) → push/PR → CI → human merge. Deterministic checks before LLM judges, always. Sample routed responses live in `docs/request-routing-examples.md`.
- **Judge arrays** — `configs/judges.yaml`: local-first, callable anytime, and fail-closed if Ollama is unavailable. The defensive-coding judge blocks **bloat** (swallowed excepts, redundant guards, hardcoded fallbacks where data-driven values belong, dead flags, fake retries, out-of-scope rewrites) — not legitimate boundary validation.
- **Per-task isolation** — one mission → one branch → one worktree → one devcontainer → one ledger **lease** (unique index: two agents physically can't lease the same checkout). Pair with `hermes -w`.
- **Standards everywhere** — `configs/standards.yaml` renders into `CLAUDE.md` and `AGENTS.md` for each onboarded repo and is mounted into Judge Gate. Claude/Codex get the same rules your judges enforce: no defensive coding, empirical thresholds, minimal diffs, data-science rigor, and never weakening tests.
- **Models/executors** — `docs/model-update.md` and `configs/models.yaml`: LiteLLM is local-only and routes aliases to Ollama. Claude Code is the primary coding executor and Codex CLI is the fallback; both authenticate outside LiteLLM through their own subscription/OAuth login. `make model-scout` can propose local model candidates, but promotion stays canary + evals + human approval.
- **GitHub safety** — `docs/github-safety.md`: branch protection, scoped PAT → GitHub App, required CI, CODEOWNERS, human-gated deploy environment. The agent can push a feature branch and open a PR; never merge/deploy/publish.
- **Security** — LiteLLM pinned by **digest** (not pip; the March 2026 PyPI compromise), virtual keys scoped+budgeted, `.env` never in a sandbox.

Start with [`docs/SETUP-FROM-SCRATCH.md`](docs/SETUP-FROM-SCRATCH.md) (cold start → phases → daily flow → definition of done). Live progress is tracked in [`docs/STATUS.md`](docs/STATUS.md).

---

## Cost

Lean control plane ~$15–35/mo plus your hardware/electricity. LiteLLM model calls are local Ollama calls, so they do not create OpenAI/Anthropic/OpenRouter API charges. Claude Code and Codex executor work uses their own login/subscription lanes.

## Before production
The local checkout is pinned to a verified LiteLLM digest. When upgrading LiteLLM,
pull the new image, inspect its immutable digest, replace the pinned digest in
`docker-compose.yml` and `Makefile`, then rerun `.\scripts\cc.ps1 check` and
`.\scripts\cc.ps1 live-smoke`.
