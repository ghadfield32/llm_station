# Chat channels

Chat from any platform to the Growth OS / Command Center. Every channel is **one
more surface, not a new authority**: messages route through LiteLLM (local
open-source models first) to the same growthos action layer (~25 tools) the local
assistant and Claude MCP use, and **no channel can approve mission cards** — that is
refused in `growthos/actions.py`, not just in the prompt. The bot can read boards,
triage, and *draft* mission cards (they land in Backlog; you drag to Approved).

What the bot can do, by tier (enumerated in `core.py build_system` so the model
actually uses its full range):

1. **Boards** — read + adjust by intent: todos, mission cards, DAGs, papers/repos/
   signals triage (`move_item`), library/lessons/notes.
2. **Research** — `read_item(database, title)` returns ONE item's full detail
   (abstract, score, curator "suggested-for", url) so it can *explain* a paper/repo.
3. **Awareness** — `project_status`, `dag_health` (live Airflow), `network_health`,
   `mission_status`, `latest_brief`.
4. **Repo work** — it DRIVES, executors complete: `add_mission_card(section, action,
   acceptance, risk, repo)` → you drag to Approved → a gated Ledger mission an
   executor (Claude Code/Codex) runs in an isolated worktree → `mission_status` to
   track. The bot can never approve or merge (the wall).

**Proactive updates** — channels are reactive; `cc notify` (`make notify`,
`cc notify --dry-run` to preview) is the one job that messages YOU: the daily brief
headline + active Ledger missions, posted to your Discord channel. Run it on a host
schedule (Task Scheduler / cron / systemd timer), the same way the kanban bridge
runs. Fail-loud: missing creds or an unreachable Ledger stop it, never a fake digest.

### Scheduling `cc notify` (run yourself — agent-created persistence is deliberately blocked)

Same convention as the kanban bridge and snapshot tasks: the schedule is a
**user-run** one-liner; agents do not self-install host schedules. Pick a time and
register it once. Windows (daily at 08:00):

```powershell
schtasks /create /tn "CC notify" /sc daily /st 08:00 /tr "cmd /c cd /d C:\Users\ghadf\vscode_projects\docker_projects\llm_station && .venv\Scripts\python.exe -m command_center.cli.notify"
```

Linux/worker cron (daily at 08:00): `0 8 * * * cd <repo> && .venv/bin/python -m command_center.cli.notify`.
Preview first with `cc notify --dry-run` (composes + prints, sends nothing).

## Architecture

```
platform event ──► adapter (discord.py / slack.py / telegram.py / whatsapp.py)
                      │  translate to (conversation_id, text)
                      ▼
              GatewayCore.run_turn()            ← src/command_center/channels/core.py
                      │  LiteLLM /chat/completions tool-call loop (<= max_rounds),
                      │  repeat-call breaker + forced final answer, errors surfaced
                      ▼
              growthos action layer  ──►  board store / Ledger (gated)
```

- **`core.py`** holds the only logic: the LiteLLM tool loop, the shared system prompt,
  and the growthos tool dispatch. It is transport-agnostic and has no SDK dependencies.
- **Adapters** are thin: parse the platform event, call `run_turn`, send the reply. They
  hold no policy.
- **`configs/channels.yaml`** declares which transports are on and which model alias each
  speaks (cross-checked against `models.yaml` by `make validate`). **Tokens are never in
  YAML** — they live in `.env`. Channels speak the **`chat`** role (qwen3 instruct), not
  `triage` (qwen3-coder): chat surfaces narrate before a tool call, and qwen3-coder's
  Ollama native tool parser drops prose-prefixed calls — they then leak to the user as raw
  `<function=..>` XML. `core.py` also fail-loud-rejects any unparsed tool-call markup rather
  than forwarding it, so a future fragile-model regression is loud. See `configs/models.yaml`
  `chat:` and MASTER.md §14 (2026-06-13).
- **The runner** `python -m command_center.channels` reads `channels.yaml` and launches
  every enabled adapter concurrently.

## Running

```bash
uv pip install -e ".[gateways]"                 # transport SDKs (once)
python -m command_center.channels --dry-run     # list what would start, connect to nothing
make gateway                                    # install the extra + run all enabled channels
make gateway CHANNELS=slack,telegram            # run a subset
```

Turn a channel on by setting `enabled: true` in `configs/channels.yaml` **and** adding its
tokens to `.env`. With a token missing, the adapter fails fast with setup instructions —
by design.

## Per-platform setup

### Discord
1. <https://discord.com/developers/applications> → **New Application** → **Bot** →
   **Reset Token** (copy) → enable **MESSAGE CONTENT INTENT**.
2. **OAuth2 → URL Generator** → scope `bot` → permissions *Send Messages* + *Read Message
   History* → open the URL, invite to your server.
3. Right-click your channel → **Copy Channel ID** (enable Developer Mode first).
4. `.env`: `DISCORD_BOT_TOKEN=...`, `DISCORD_ALLOWED_CHANNEL_IDS=123...` (comma-separated;
   DMs from the owner are always allowed).

### Slack (Socket Mode — no public URL needed)
1. <https://api.slack.com/apps> → **Create New App** (from scratch).
2. **Socket Mode** → enable → create an **App-Level Token** with `connections:write`
   (`xapp-...`).
3. **OAuth & Permissions** → Bot Token Scopes: `chat:write`, `app_mentions:read`, and
   `channels:history` / `im:history` for the surfaces you want → install → copy the **Bot
   User OAuth Token** (`xoxb-...`).
4. **Event Subscriptions** → subscribe to `message.channels` and/or `message.im`.
5. `.env`: `SLACK_BOT_TOKEN=xoxb-...`, `SLACK_APP_TOKEN=xapp-...`, optional
   `SLACK_ALLOWED_CHANNEL_IDS=...`.

### Telegram (long-poll — no public URL needed)
1. Message **@BotFather** → `/newbot` → copy the token.
2. (Optional) find your chat id (e.g. message **@userinfobot**) to build an allowlist.
3. `.env`: `TELEGRAM_BOT_TOKEN=...`, optional `TELEGRAM_ALLOWED_CHAT_IDS=...`.

### WhatsApp (Meta Cloud API — needs a public HTTPS webhook)
1. <https://developers.facebook.com> → create an app → add the **WhatsApp** product.
2. Copy the **temporary access token**, **phone number ID**, and pick any string as your
   **verify token**.
3. `.env`: `WHATSAPP_ACCESS_TOKEN=...`, `WHATSAPP_PHONE_NUMBER_ID=...`,
   `WHATSAPP_VERIFY_TOKEN=<your string>`, optional `WHATSAPP_ALLOWED_NUMBERS=...`.
4. Expose the local webhook publicly — e.g. `cloudflared tunnel --url http://localhost:8080`
   or `ngrok http 8080` — and in the Meta app's **Webhooks** config set the callback URL to
   `https://<public-host>/webhook` and the verify token to the same string. Subscribe to
   `messages`.
5. Run it (`make gateway CHANNELS=whatsapp`); Meta calls `GET /webhook` to verify, then
   `POST`s inbound messages.

## Adding a new channel (e.g. a future "Stoat", Matrix, SMS, …)

Three steps, no new service:

1. **Write the adapter** `src/command_center/channels/<transport>.py` exposing
   `async def run(spec) -> None`: read its tokens from `.env` (fail fast if missing),
   build `GatewayConfig.build(surface=..., model=spec.model, ...)`, construct a
   `GatewayCore`, wire the platform's inbound event to `core.run_turn(conversation_id,
   text)` and send the reply back. Keep it thin; put no logic in it. Lazy-import any SDK so
   the base install stays clean, and add that SDK to the `gateways` extra in
   `pyproject.toml` (then `uv sync`).
2. **Extend the contract** — add the transport to the `Literal[...]` in `ChannelSpec`
   (`src/command_center/schemas/contracts.py`).
3. **Register it** — add a block to `configs/channels.yaml` (`enabled: false` until tokens
   exist) and its token names to `.env.example`. `make validate` then covers it, and the
   runner picks it up automatically.

Everything else — the model loop, the action layer, the no-approval wall — you inherit
from `core.py` for free.
