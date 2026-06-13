# UI options — from any device

All web UIs bind to 127.0.0.1 on the VPS; reach them over **Tailscale** (`http://<vps-tailscale-ip>:PORT`). Nothing public unless you deliberately add Caddy+Cloudflare Access.

## Web dashboards (Tailscale)
| Service | Port | What you do |
|---|---|---|
| Hermes WebUI | 8787 | chat, file browser, approvals — `nesquena/hermes-webui` (MIT, mature); optional Phase 4, governed by `configs/ui.yaml` |
| Hermes Kanban | (first-party) | multi-agent task board across profiles |
| Ledger UI | 8091 | missions: status, risk, diffs, leases, approvals, **kill** |
| LiteLLM Admin | 4000/ui | spend, budgets, rotate virtual keys |
| Uptime Kuma | 3001 | health of all nodes/services |

> The WebUI auto-detects your `~/.hermes` and uses your existing models — works whether Hermes was installed manually or via `ollama launch hermes`. Run single-container (avoids the #681 two-container tool-location limit), behind Tailscale, with `HERMES_WEBUI_PASSWORD` set. It's a convenience UI, not the policy layer — external writes still go through the Ledger/gates. See `docs/ecosystem.md`.

## From the 5080 laptop (your front end)
- VS Code Desktop + **Remote Tunnel** into the 4090 worktree — same files the agent edits.
- Browser tabs for the dashboards. `ssh`/`tmux` over Tailscale for CLI.

## From the 4090 desktop (worker)
- Local `hermes` CLI (live subagent tree-view). `ollama serve` for the local judge tier. Local VS Code if seated.

## From your phone
- **Telegram/Discord** to Hermes: fire missions, approve gates, get alerts.
- **GitHub mobile** for PR review + merge. `vscode.dev` for a quick look.

## From any borrowed machine
- `vscode.dev` against your tunnel (zero install) · Tailscale web · GitHub web.

## The two human gates
1. **Approvals** (L3/L4): Telegram message or Ledger UI, signed.
2. **Merge**: GitHub PR — your CODEOWNERS review + required checks. The bot can never merge.

> Model: agent drives terminal/filesystem; you drive VS Code + dashboards + GitHub. Same workspace, different controls.
