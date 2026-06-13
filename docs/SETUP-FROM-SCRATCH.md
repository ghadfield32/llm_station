# Setup from scratch

The one setup doc: from "nothing installed" to "control plane up, channels chatting,
agents working in leased worktrees" — in build order. The deep reference is
[MASTER.md](MASTER.md); per-channel detail is [channels.md](channels.md).

**Four equivalent interfaces** — use whichever fits (full table in the [README](../README.md#ways-to-run-it-make--uv--docker)):
`make <target>` (Linux/macOS) · `.\scripts\cc.ps1 <target>` (Windows) · **`uv run cc <command>` (any OS, zero-install)** · `docker compose up -d` (pure Docker; it renders its own config). The fastest start on a fresh machine is **`uv run cc start`** (one button: control plane → keys → health → opens the UIs; add `--appflowy --channel telegram`). The steps below use `make`; substitute freely.

> This doc consolidates the former `runbook.md`, `COMPLETE-SETUP.md`, and
> `SETUP-REMAINING.md`. Live progress tracking lives in [STATUS.md](STATUS.md).

## 0. What to obtain first

**Hardware / accounts** (the control plane itself is ~$5–12/mo + your hardware):

- [ ] A **VPS** (2 vCPU / 4 GB is plenty — Hetzner/DigitalOcean/Hostinger), *or* run
      everything on one workstation first, as the current local setup does.
- [ ] **Tailscale** account (free Personal tier) — the private mesh; nothing is public.
- [ ] A **GitHub fine-grained PAT** scoped to: Contents R/W, Pull requests R/W,
      Issues R, Metadata R — nothing else. (Migrate to a GitHub App long-term.)
- [ ] Chat-platform tokens for whichever channels you want (step 6; none required).

**Software:**

| Tool | Why | Check |
|---|---|---|
| **Docker** (+ Compose) | runs the control-plane stack | `docker --version` |
| **uv** | Python env + locked installs | `uv --version` |
| **Ollama** | the local models LiteLLM routes to | `ollama --version` |
| **git** | clone + the AppFlowy-Cloud submodule | `git --version` |

LiteLLM is pinned by **immutable digest** (not pip) on purpose — supply-chain guard.
You never `pip install litellm`.

> **Low VRAM / laptop / CPU?** The default models are ~24 GB-class (need a big GPU). Run
> **`make models-light`** at step 5 to switch to a `qwen3:8b` profile (~5 GB) so you still get
> real replies. `make doctor` warns you up front if the routed models aren't pulled.

## 1. Clone (with the submodule)

```bash
git clone --recurse-submodules https://github.com/ghadfield32/llm_station.git
cd llm_station
# if you already cloned without it:
git submodule update --init --recursive   # fetches appflowy_kanban/AppFlowy-Cloud @ pinned commit
```

## 2. Install the Python package

```bash
uv venv .venv
uv pip install -e .                 # control plane only (validate/render/serve)
uv pip install -e ".[gateways]"     # + chat transports (Discord/Slack/Telegram/WhatsApp)
uv pip install -e ".[dev]"          # + ruff/mypy/pytest, if you'll develop
```

`make setup` does the venv + install + `.env` scaffold + render + service image build in
one step on Linux; on Windows run `.\scripts\cc.ps1 init-env` then continue below.

## 3. Secrets (`.env`)

```bash
make setup            # or: python -m command_center.cli.init_env   (Windows: .\scripts\cc.ps1 init-env)
```

This copies `.env.example` → `.env` and generates the three local secrets
(`LITELLM_MASTER_KEY`, `POSTGRES_PASSWORD`, `LEDGER_APPROVAL_SECRET`). Then edit `.env`:

- Confirm `OLLAMA_API_BASE` (local Docker: `http://host.docker.internal:11434`; VPS: the
  4090's Tailscale URL).
- **Do not** add any `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` — the
  boundary check (`make forbidden-providers`) fails if you do. LiteLLM is local-only;
  Claude Code / Codex authenticate through their own subscription/OAuth logins.
- `GITHUB_TOKEN` is optional (enables L3 push/PR automation).
- Channel tokens stay blank until you enable a channel (step 6).

When installing or upgrading LiteLLM: pull the official GHCR image, inspect its immutable
digest, replace the pin in `docker-compose.yml` **and** `Makefile`, then
`make verify-base` (Windows: `.\scripts\cc.ps1 verify-base`).

## 4. Preflight + validate before booting

```bash
make doctor           # one green/red checklist: docker, uv, ollama, ports, .env, providers, digest
make validate         # configs match contracts + cross-refs + render + provider boundary
make mission-dryrun   # L0–L4 lifecycle is coherent (no model calls)
```

`make doctor` surfaces every prerequisite at once instead of failing one at a time. All three
must pass before you boot.

## 5. First boot (Phase 1 — the control plane)

**The easy way — one command** (chains doctor → setup → bootstrap → keys → up → health; it pauses
once if `.env` still needs `OLLAMA_API_BASE`, then just re-run it):

```bash
make first-boot       # Windows: .\scripts\cc.ps1 first-boot
```

**Or step by step**, if you want to watch each stage:

```bash
make bootstrap        # FIRST BOOT: litellm-db + litellm + ledger only, waits for health
make keys             # mints the two virtual keys AND writes them into .env (no copy-paste)
make verify           # full runtime prerequisites, including the virtual keys
make up               # full control plane
make health           # every service OK?
make live-smoke       # real local-model replies through Ollama/LiteLLM
```

Windows: the same targets via `.\scripts\cc.ps1 bootstrap | keys | verify | up | health | live-smoke`.

> Why `bootstrap` before `up`: clients read their LiteLLM virtual key from `.env`, but
> that key doesn't exist until LiteLLM is up and `make keys` mints it. `bootstrap` starts
> just the infra so keys can be minted first. `make keys` now writes both keys into `.env`
> for you — no manual paste.

### Environment & stacks map

Three `.env` files and three Docker stacks, each with a clear owner — fill only what you use:

| File | Owns | When |
|---|---|---|
| `.env` (repo root) | control plane (LiteLLM/Judge Gate/Ledger) + chat-channel tokens | always |
| `appflowy_kanban/AppFlowy-Cloud/.env` | the AppFlowy board server (Postgres, GoTrue, S3/MinIO, external URL) | if you use AppFlowy (§6) |
| `appflowy_kanban/growth-os/.env` | the Growth OS curator (AppFlowy creds, GitHub PAT) | if you use the curator (§6) |

| Stack | Compose file | Brought up by |
|---|---|---|
| Control plane | `docker-compose.yml` | `make up` |
| AppFlowy server | `appflowy_kanban/AppFlowy-Cloud/docker-compose.yml` | `make appflowy-up` (after `make appflowy-init`) |
| Growth OS curator | `appflowy_kanban/growth-os/docker-compose.curator.yml` | `make appflowy-up` (brings up both) |

The live smoke proves: Ollama direct reply · LiteLLM `triage`/`planner`/`local-judge`
aliases · `gpt-*` and `claude-*` names **denied** through LiteLLM · executor shell has no
provider keys · forbidden-providers check passes. There is no skip-Ollama path — calls
fail closed if Ollama is down.

**Phase 1 done when:** live smoke passes, a channel can open a Ledger mission, and an L3
request shows `awaiting_approval`.

## 6. Channels (Discord, Slack, Telegram, WhatsApp, …)

Channels are optional and additive — thin transports onto the same action layer. Full
per-platform steps (and how to add a brand-new transport) in [channels.md](channels.md).

1. Add the platform's tokens to `.env` (names are in `.env.example`).
2. Set `enabled: true` for that channel in `configs/channels.yaml`.
3. `make validate` (the channel's `model` is checked against `models.yaml`).
4. `make gateway` (all enabled) or `make gateway CHANNELS=slack,telegram` (subset).
   Dry-run first: `python -m command_center.channels --dry-run`.

| Channel | Public webhook? | Tokens |
|---|---|---|
| Discord | no | `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_CHANNEL_IDS` |
| Slack | no (Socket Mode) | `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` |
| Telegram | no (long-poll) | `TELEGRAM_BOT_TOKEN` |
| WhatsApp | **yes** (Meta Cloud API) | `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN` |

## 7. Phase 2 — the 4090 worker: isolation, judges, executors

1. **Tailscale on the 4090.** Put its Tailscale IP into `.env` as `OLLAMA_API_BASE` so the
   VPS LiteLLM reaches Ollama over the private mesh, then re-run `make models` and
   `make live-smoke`.
2. **Local models:** `curl -fsSL https://ollama.com/install.sh | sh`, then `make models`
   (pulls `qwen3-coder:30b`, `qwen3:30b`, `devstral:24b` — ~14–19 GB at Q4 on a 24 GB
   card). L0/L1 + cheap judging now cost ~$0.
3. **VS Code Remote Tunnel:** `code tunnel` on the 4090; attach from the laptop,
   `vscode.dev`, or phone. The agent uses the terminal/worktree; you use the IDE.
4. **Executor CLIs:** install and authenticate both — Claude Code primary (`claude`,
   `/login`, `/status`), Codex CLI fallback (`codex login status` → "Logged in using
   ChatGPT"). They authenticate **outside** LiteLLM. Before launching either, the shell
   must have no `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` in process, user, or machine env —
   `scripts/live_smoke.{sh,ps1}` checks this.
5. **Leases:** every mission acquires one Ledger lease (`POST /mission/{id}/lease`); a
   unique index on (repo, branch) means two agents physically cannot lease the same
   checkout.
6. **Per-repo install:** `make repo-install REPO=/path/to/repo PROFILE=python_ml_pipeline`
   — pre-commit static tools + judge array, pre-push cross-provider skeptic, devcontainer,
   and `CLAUDE.md`/`AGENTS.md` rendered from `configs/standards.yaml`.

**Done when:** an L2 mission leases a branch, edits in an isolated worktree, pre-commit
judges pass/block correctly, and the pre-push skeptic reviews before a PR is allowed.

## 8. Phase 3 — GitHub hardening

Work through [github-safety.md](github-safety.md): protect `main`, CODEOWNERS, the scoped
PAT (→ GitHub App later), `validate.yml` as required checks, a human-reviewed `production`
environment.

**Done when:** the repo itself blocks merges without passing checks + your review, even if
the agent misbehaves.

## 9. Optional phases

- **Phase 3.5 — proactive ops lane:** scheduled DAG/data/repo checks → gated missions,
  plus the observer-only daily self-improvement report/card scan
  ([proactive-ops.md](proactive-ops.md), [daily-self-improvement-dag.md](daily-self-improvement-dag.md)).
- **Phase 4 — workspace platforms:** Coder / OpenHands / Codespaces, only when tunnels are
  outgrown. Mirage stays a read-only watch-list experiment ([optional-mirage.md](optional-mirage.md)).
- **Phase 5 — home relay:** a mini-PC for Wake-on-LAN/watchdog/backup mirror, only after
  Phases 1–2 are stable.

## 10. Backups

Wire `make backup` to a restic repository (ledger SQLite + `.env` escrow + AppFlowy
volumes are the state that matters), schedule it, and run `make restore-drill` monthly —
a backup you haven't restored is a hope, not a backup.

## 11. The daily flow

1. Phone/chat → channel: "On `betts_basketball`, add a test for the age-curve spline and open a PR."
2. Ledger opens a mission; triage (local model) classifies **L3**; a **lease** is acquired.
3. Plan → plan-critic + scope-judge; implement (Claude Code) in the leased worktree.
4. Static checks → pre-commit judge array → commit; pre-push security-skeptic → **your L3 approval**.
5. Bot pushes the branch + opens the PR; GitHub required checks + CODEOWNERS gate the merge.
6. Anytime: Ledger UI for the audit trail, or kill a runaway mission.

## 12. Definition of done (the "complete means" checklist)

- [ ] No provider API keys in `.env`, `.env.example`, process/user/machine env.
- [ ] `generated/litellm-config.yaml` contains only `ollama_chat/...` models.
- [ ] The Hermes virtual key can call `triage`/`planner`/`local-judge` and **cannot** call
      arbitrary `gpt-*`/`claude-*` names.
- [ ] No cloud fallback: with Ollama down, model calls fail closed.
- [ ] `codex login status` and Claude Code `/status` both report subscription/OAuth auth.
- [ ] `make live-smoke` prints real local responses; `make validate` + `make mission-dryrun` pass.
- [ ] An L3 mission holds at `awaiting_approval` until a human approves.

Current machine-by-machine progress against this list is tracked in [STATUS.md](STATUS.md).
