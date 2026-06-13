# Status — done / in progress / next

The multi-session work tracker. Newest changes are in `MASTER.md` §14; this is the
forward-looking "what's left, in what order" list. Keep it short and honest.
(Absorbs the former `SETUP-REMAINING.md` deployment checklist and
`growth-os-system.md` status snapshot.)

_Last updated: 2026-06-12._

## Done

- **GitHub-ready hygiene.** Comprehensive `.gitignore`; all secrets/caches/dumps confirmed
  ignored via `git check-ignore`; stray tarball + egg-info removed; `AppFlowy-Cloud`
  pinned as a submodule; MIT `LICENSE`, `CONTRIBUTING.md`, PR template.
- **`src/command_center/` layout.** `schemas` / `registry` / `cli` relocated and installed
  editable; all imports, the Makefile, `cc.ps1`, CI, `breakage.yaml`, the evaluation
  gold-set, and the growth-os cross-imports rewired. `ruff check src` clean; `pytest` green.
- **Multi-channel gateway.** `GatewayCore` + Discord/Slack/Telegram/WhatsApp adapters +
  `configs/channels.yaml` (validated by `ChannelsConfig`, channel→model cross-checked) +
  `python -m command_center.channels` runner.
- **Docs.** `SETUP-FROM-SCRATCH.md`, `channels.md`, this file; `MASTER.md` module tree +
  doc index + §13 N/A note refreshed; reference standards copied to `docs/backend/`.

- **Docs consolidated (2026-06-12).** `runbook.md`, `COMPLETE-SETUP.md`, and
  `SETUP-REMAINING.md` folded into `SETUP-FROM-SCRATCH.md`; `growth-os-system.md` folded
  here; `PREFLIGHT-FIXES.md` retired (its history lives in `MASTER.md` §14 — note its
  provider-key advice was superseded by the local-only correction). Stale `_staging/`
  bundle copies removed from disk.
- **Local control plane green (2026-06-12).** Validation green, LiteLLM digest-pinned,
  local models installed, virtual keys minted, health + live smoke passing, Growth OS
  selftest 22/22, kanban bridge live with writeback.

## In progress / awaiting a human

- **First commit.** The tree is staged-ready but uncommitted. Stage explicit paths (never
  `git add -A`), commit on a branch off `main`, push, open a PR. The submodule + `.gitmodules`
  go in that first commit.
- **Channels are wired but off.** Discord is `enabled: true` in `channels.yaml` but needs
  `DISCORD_*` tokens in `.env` to actually connect; Slack/Telegram/WhatsApp are `enabled:
  false` pending tokens. Live-test each once tokens exist (`make gateway CHANNELS=<one>`).
- **Growth OS end-to-end proof-drag** (from the former growth-os-system doc): two
  acceptance cards sit in Backlog on mission_intake — an L1 freshness-check card and an
  L4 wall-test card. Drag both to **Approved**, run the bridge with `--apply`, confirm the
  L1 card gets a MissionID/In Progress and the L4 mission holds at the Ledger awaiting
  approval. Then schedule the bridge (schtasks one-liner in `kanban-integration.md`).
- **Deployment remainder** (machine-by-machine, against the SETUP-FROM-SCRATCH §12
  definition of done): VPS rent + Docker/Tailscale + same bootstrap flow; Tailscale on the
  4090 + point VPS `OLLAMA_API_BASE` at it + `make live-smoke` from the VPS; GitHub
  branch protection + scoped token. Local items (digest pin, keys, health, live smoke,
  `cc.ps1 check`) are all done.

## Next (suggested order)

1. **Commit + push + open PR** for this GitHub-readiness work; let CI (`contracts.yml`)
   prove validate + ruff + pytest on a clean runner.
2. **Bring one new channel live end-to-end** (Telegram is the lowest-friction — no public
   webhook, no app review) to exercise `GatewayCore` on a second transport in production.
3. **WhatsApp webhook** when wanted: stand up the public tunnel + Meta app, register the
   webhook (`docs/channels.md`), confirm the `GET` verify + `POST` inbound round-trip.
4. **`make lint` mypy pass.** Ruff is clean and CI runs ruff; mypy over `src/` is available
   via `make lint` but not yet wired into CI — tighten types and add it to CI when green.
5. **Path-independence (optional).** The config-pipeline CLIs read `configs/` relative to
   the CWD (run from repo root via `make` / `python -m`). If you want the console scripts to
   work from any directory, anchor their file reads to the repo root and expose the rest as
   entry points.

## Honest scope notes (carried from growth-os-system)

- **AppFlowy in-app AI is blocked on this machine**, not configured away: the server AI
  container needs an OpenAI key (no base-URL override in shipped compose) and the desktop
  Local-AI path white-screens on this GPU/driver. Assistant + MCP + boards cover the same
  asks; revisit when upstream moves.
- **Claude mobile remote connectors run from Anthropic's cloud** — they can't reach a
  tailnet-only URL, and public Funnel is on the do-not-build list. Phone control today =
  AppFlowy boards (drag to approve) + chat channels.
- Everything lives on the Windows workstation; the Linux migration runbook is
  `appflowy_kanban/growth-os/deploy/linux/MIGRATION.md`.

## Known non-goals (don't cargo-cult)

- The forecasting-pipeline standards in `docs/backend/` (R2 locks, DAG run-location,
  medallion layers, GPU training, dbt, champion promotion) **do not apply** to this control
  plane — see `MASTER.md` §13.1. Only the git multi-session rules and the engineering
  standards transfer.
