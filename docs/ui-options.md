# UI options — from any device

All web UIs bind to 127.0.0.1 on the VPS; reach them over **Tailscale** (`http://<vps-tailscale-ip>:PORT`). Nothing public unless you deliberately add Caddy+Cloudflare Access.

## Web dashboards (Tailscale)
| Service | Port | What you do |
|---|---|---|
| Agent Kanban UI | 8787 | first-party Cline-styled board + observability over AppFlowy/Ledger; optional Phase 4, governed by `configs/ui.yaml`. **Read-mostly** — writes flow through the Ledger/action-layer gates; the UI cannot set Approved |
| Ledger UI | 8091 | missions: status, risk, diffs, leases, approvals, **kill** |
| LiteLLM Admin | 4000/ui | spend, budgets, rotate virtual keys |
| Uptime Kuma | 3001 | health of all nodes/services |

> **2026-06-13:** the Phase-4 WebUI slot was repurposed from the deferred Hermes WebUI/Kanban
> (see MASTER.md change log — Cline/Hermes DEFER) to a **first-party agent kanban + observability**
> surface over AppFlowy/Ledger. Tracker: `docs/backend/projects/AGENT_KANBAN_SURFACE.md`. It runs
> single-container behind Tailscale with a password set; it is a convenience UI, **not** the policy
> layer — external writes still go through the Ledger/gates (`external_write_policy: governed_by_ledger`).

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
