# Command Center — v4 (contract-stabilized)

A personal LLM **command center** that runs **entirely on your own machine** — no cloud bill
([Cost](#cost)). You chat with it from Discord/Telegram/Slack, it routes through a **local**
model (Ollama via LiteLLM), drafts work behind risk gates and cross-provider judges, and
**cannot approve its own actions** — you do, by dragging a card to Approved.

Kept **lean on purpose** — a command center, not an enterprise platform. The thing that makes
it repeatable and hard to break is a **typed contract layer**: every editable config validates
against a Pydantic model before it can do anything ([the idea, in five lines](#the-contract-model)).

> **Deep docs:** [`docs/SETUP-FROM-SCRATCH.md`](docs/SETUP-FROM-SCRATCH.md) is the annotated cold-start ·
> [`docs/MASTER.md`](docs/MASTER.md) is the full system guide (every pipeline, the module tree, the change log) ·
> [`docs/STATUS.md`](docs/STATUS.md) tracks live progress. This README gets you **built and chatting**; those cover everything else.

---

## Build it (Quickstart)

Local, end-to-end: **clone → control plane up → chat with it from a channel.** All on your
machine, no cloud bill. **Needs Docker, [uv](https://docs.astral.sh/uv/), Ollama, and git.**

### 0 — Prerequisites

- **Docker** (the services run here) · **Ollama** (the local model engine, on your host) ·
  **[uv](https://docs.astral.sh/uv/)** (runs the operator CLI with zero install) · **git**.
- Run `uv run cc doctor` any time for a green/red preflight (docker daemon, Ollama, ports, `.env`, provider boundary).

### 1 — Get the code

```bash
git clone --recurse-submodules https://github.com/ghadfield32/llm_station.git
cd llm_station
```

`--recurse-submodules` pulls **AppFlowy-Cloud** (the self-hosted board server) into
`appflowy_kanban/AppFlowy-Cloud`. Already cloned without it? `git submodule update --init --recursive`.

### 2 — One button: bring up the control plane

```bash
uv run cc init-env     # create .env with local secrets (edit it: set OLLAMA_API_BASE;
                       #   local default http://host.docker.internal:11434 is fine.
                       #   do NOT add OpenAI/Anthropic keys — local-only by contract)
uv run cc models-light # pull a small model so there's something to route to (~5 GB qwen3:8b).
                       #   Big-GPU? use `uv run cc models` for the default 24 GB-class profile.
uv run cc start        # ONE BUTTON: doctor → build → bootstrap → mint keys → up → health → opens the UIs
```

`cc start` does the whole first-boot sequence and opens the **LiteLLM admin** (`:4000/ui`),
**Ledger** (`:8091`), and **Uptime Kuma** (`:3001`) dashboards. After this, the steady-state
command is just `uv run cc up` (or `docker compose up -d` — see [Ways to run](#ways-to-run-it)).

```bash
uv run cc live-smoke   # proves real local replies through Ollama → LiteLLM
```

### 3 — Talk to it from a channel

Telegram is easiest (no public webhook). `cc channel` is guided — it opens the bot-creation page
if your token is missing, enables the channel, and launches it.

```bash
# get a bot token (Telegram: message @BotFather) and put it in .env: TELEGRAM_BOT_TOKEN=...
uv run cc channel telegram      # guided setup + launch (or: discord / slack / whatsapp)
```

Now message your bot: *"what's on my todo board?"* or *"draft a mission card: add retry logic to
the odds DAG, L2, repo betts_basketball."* It routes through your local model to the action layer —
and **cannot** approve its own mission cards (you drag the card to Approved; that's the wall).

### 4 — (Optional) Stand up AppFlowy boards

AppFlowy Cloud is the **human surface** — todos, mission cards, a 275-book library. One command
brings up the board server + the Growth OS curator:

```bash
uv run cc start --appflowy   # scaffolds both .env files + brings up the board server + curator
```

Then point the **AppFlowy desktop/mobile app** ([download](https://appflowy.io)) at the printed URL,
sign up a user, put the creds in `appflowy_kanban/growth-os/.env`, and run `setup_workspace.py`
(it prints the exact steps). Full detail: [`appflowy_kanban/growth-os/README.md`](appflowy_kanban/growth-os/README.md).
`appflowy-init` uses AppFlowy's shipped localhost defaults — fine for local/tailnet; **rotate the
secrets before any public exposure**.

---

## Ways to run it

`uv run cc` is the recommended driver — **any OS, zero install** — but it isn't the only one. All
four interfaces do the same operations; pick whatever fits your machine.

| Interface | Best for | One-button first boot |
|---|---|---|
| **`uv run cc <command>`** | **any OS, zero install** (recommended) | `uv run cc start` |
| **`make <target>`** | Linux/macOS with GNU Make | `make first-boot` |
| **`.\scripts\cc.ps1 <target>`** | Windows, no Make | `.\scripts\cc.ps1 first-boot` |
| **`docker compose up -d`** | steady-state control plane | *(see note ↓)* |

**Is `docker compose up -d` one command for everything? No — and here's the honest scope.**
Docker is the engine, not the entrypoint. One `docker compose up -d`:

- ✅ **renders its own LiteLLM config** (the `config-render` one-shot service — genuinely make-free) and
- ✅ **starts the control plane** (LiteLLM + Postgres + Ledger + Judge Gate + Uptime Kuma), but it
- ❌ **needs `.env` to already exist** — Compose interpolates the local secrets; generate them once with `cc init-env`;
- ❌ **can't mint the virtual key Judge Gate needs on a cold boot** — that key only exists *after* LiteLLM is healthy (first-boot is two-phase: bring up LiteLLM → mint → bring up the rest). `cc start` / `make first-boot` sequence this for you;
- ❌ **doesn't pull Ollama models** (they live on your host) or **run the chat channels** (a host process).

So: use **`cc start` for the first boot**, then **`docker compose up -d` / `cc up` for every boot after**.
The portable `cc` command also adds conveniences the raw compose file can't: `cc open` (open the
dashboards), `cc channel <name>` (guided channel setup), `cc start --appflowy`/`--hermes`. Run
`uv run cc help` for the full list. The **Hermes** UI is opt-in (`cc start --hermes`) and currently a
placeholder — set a real `hermes` image in `docker-compose.yml` first (see [STATUS.md](docs/STATUS.md)).

---

## The contract model

The whole idea in five lines:

```text
YAML in configs/                          = the editable source of truth (you edit these)
Pydantic in src/command_center/schemas/   = the contract that validates it
generated/                                = disposable rendered output (litellm config, json-schema)
ledger SQLite                             = the only runtime state
cc / make / cc.ps1                        = the interface (same ops, three drivers)
```

**Rules:** secrets never live in YAML; generated files are never hand-edited; a typo fails at
`cc validate`, not at 2am.

**Why it's hard to break (proven, not asserted).** `cc validate` runs every `configs/*.yaml`
through its contract. These bad edits are **rejected before they ship** (all tested):

- a typo'd key (`priorty:`) → rejected (`extra="forbid"`)
- two models with the same priority in one role, or two canaries in one role, or `canary_weight > 1` → rejected
- a missing risk tier, or **L3/L4 without `requires_approval`** → rejected
- a `repo_task` environment that is persistent or holds secrets → rejected (isolation invariant)

The dangerous mistakes — silently broken routing, an approval gate quietly disabled, a sandbox that
leaks secrets — **can't be committed**.

---

## Layout

```text
command-center/
├── pyproject.toml / uv.lock # installable package (extras: [gateways], [dev]); exposes `cc`
├── Makefile                 # the make driver (Windows: scripts/cc.ps1; portable: uv run cc)
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
│   ├── breakage.yaml        #   what-breaks-when map (drives `cc impact`)
│   └── channels.yaml        #   chat transports -> transport + model (tokens in .env)
├── src/command_center/      # the installable package
│   ├── schemas/             #   Pydantic contracts (base.py + contracts.py)
│   ├── registry/            #   render.py (validate->litellm), model_scout.py
│   ├── cli/                 #   cc / make / `python -m` commands (validate, render, evals, …)
│   └── channels/            #   core.py + discord/slack/telegram/whatsapp adapters + runner
├── generated/               # disposable: litellm-config.yaml, json-schema/
├── services/                # judge_gate (+ judgectl), ledger, proactive_runner
├── tests/                   # contract regression tests (pytest; run by CI)
├── repo-template/           # per-repo: pre-commit, CI, CODEOWNERS, pre-push gate, devcontainer
├── appflowy_kanban/         # Growth OS curator + AppFlowy-Cloud (pinned submodule)
└── docs/                    # SETUP-FROM-SCRATCH, MASTER, channels, runbook, github-safety, …
```

---

## The interface (every operation)

Same commands across all three drivers — `uv run cc <x>`, `make <x>`, or `.\scripts\cc.ps1 <x>`.
Run `uv run cc help` (or `make help`) for the full list. The maintenance loop is always the same:
**edit a `configs/*.yaml`, run `cc validate`, then the relevant command.**

```bash
# lifecycle
cc doctor          # green/red preflight
cc init-env        # create .env with local secrets
cc start           # ONE BUTTON first boot (+ --appflowy / --channel NAME / --hermes)
cc up / down       # control plane (steady state)
cc keys            # mint budgeted LiteLLM virtual keys into .env
cc health          # all services OK?
cc open            # open the dashboards (LiteLLM, Ledger, Kuma)

# config (the safety net)
cc validate        # configs match contracts + cross-refs + render + provider boundary
cc render          # build generated/litellm-config.yaml
cc schema          # contracts -> generated/json-schema (editor autocomplete)
cc impact          # blast radius of your current git diff

# models (local only; promotion stays canary + evals + human approval)
cc models          # pull the default profile + restart litellm
cc models-light    # switch to the small-GPU/CPU profile (qwen3:8b)
cc model-scout     # propose local model candidates -> generated report (never edits configs)
cc usage-digest    # LiteLLM spend + Ledger mission summary

# safety dry-runs (no model calls)
cc mission-dryrun  # fake L0..L4 missions through gates+judges
cc evals           # routing/judge regression suite
cc live-smoke      # real Ollama/LiteLLM replies once keys are wired

# channels + boards
cc channel <name>  # guided discord|slack|telegram|whatsapp setup + launch
cc gateway         # run all enabled channels from configs/channels.yaml
```

`make` exposes a few extra targets the `cc` wrapper doesn't (`make impact FILES=...`,
`make repo-install REPO=...`, `make models-canary/-promote/-rollback`, `make backup`, the full
`improvement-*` experiment loop). See `make help`.

---

## How it works (the short version)

The full system — every pipeline stage, the module tree, model lanes, and the change log — is in
[`docs/MASTER.md`](docs/MASTER.md). The essentials:

- **Local-only by contract.** LiteLLM routes aliases to **local Ollama** — no OpenAI/Anthropic/OpenRouter
  charges, ever (the contract *forbids* provider keys). Claude Code is the primary coding executor,
  Codex CLI the fallback; both authenticate through their own subscription/login, outside LiteLLM.
- **Request lifecycle.** intake → ledger + lease → triage → plan → plan-critic → leased-worktree
  implement → static checks → pre-commit judge array → commit → pre-push cross-provider skeptic →
  human approval (L3/L4) → push/PR → CI → human merge. **Deterministic checks before LLM judges, always.**
- **Per-task isolation.** one mission → one branch → one worktree → one devcontainer → one Ledger
  **lease** (a unique index means two agents physically can't lease the same checkout).
- **Judge arrays** (`configs/judges.yaml`) are local-first, callable anytime, and fail **closed** if
  Ollama is down. The defensive-coding judge blocks bloat (swallowed excepts, fake retries, dead flags,
  out-of-scope rewrites) — not legitimate boundary validation.
- **Standards everywhere.** `configs/standards.yaml` renders into `CLAUDE.md`/`AGENTS.md` for each
  onboarded repo and is mounted into Judge Gate — executors get the same rules your judges enforce.
- **The GitHub wall** ([`docs/github-safety.md`](docs/github-safety.md)). branch protection, scoped
  PAT → GitHub App, required CI, CODEOWNERS, human-gated deploy. The agent can push a feature branch
  and open a PR; it can **never** merge/deploy/publish.
- **Security.** LiteLLM is pinned by **digest** (not pip — the March 2026 PyPI compromise); virtual
  keys are scoped + budgeted; `.env` never enters a sandbox.

More surfaces: [`docs/ui-options.md`](docs/ui-options.md) (phone, CLI, VS Code Remote Tunnel,
dashboards) · [`docs/channels.md`](docs/channels.md) (per-platform token steps) ·
[`docs/kanban-integration.md`](docs/kanban-integration.md) (AppFlowy cards → Ledger missions).

---

## Cost

**Running it locally costs $0 in cloud charges** — the default, and how it runs today. Everything
(LiteLLM, Judge Gate, Ledger, AppFlowy, Ollama) is Docker on your own machine:

- **Model calls** route through LiteLLM to **local Ollama** — no provider API charges, ever.
- **Claude Code / Codex** executor work uses your existing **subscription/login**, not metered billing.
- You pay only **your own electricity/hardware**.

The only *optional* recurring cost is a **VPS (~$5–12/mo)** if you later want an always-on "brain"
that stays up when your workstation/4090 sleep (Phase 1 in [SETUP-FROM-SCRATCH](docs/SETUP-FROM-SCRATCH.md)).
Not required — skip it and run on one machine.

---

## Before production

The checkout is pinned to a verified LiteLLM digest. When upgrading LiteLLM, pull the new image,
inspect its immutable digest, replace the pinned digest in `docker-compose.yml` and `Makefile`,
then rerun `cc verify` and `cc live-smoke`.
