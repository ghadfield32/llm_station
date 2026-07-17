# Open Design — dev-lane bring-up

Open Design ([`nexu-io/open-design`](https://github.com/nexu-io/open-design),
Apache-2.0) is a **local-first design canvas** driven by coding agents. It runs
on the **desktop/laptop dev lane** — next to the coding-agent CLIs (Claude Code,
Codex, …) and GPUs — **not** on the Life Center appliance, which lacks those
agents and model access. The appliance's only role is to **back up the `.od/`
project files** (design systems, skills, templates) as Class B data.

Usage/billing is BYOK: an agent subscription you already hold, your own API key,
or a local model — so you can draft cheap, polish with a stronger model, move to
Codex when a Claude allowance runs tight, or stay fully local for private work.

## Prerequisites

- Node ~24 and `pnpm` (~10.33.x) on PATH
- At least one supported coding agent on PATH (auto-detected), e.g. `claude`
  (Claude Code), `codex`, `cursor`, `gemini`
- `git`

## Bring it up

```bash
# macOS/Linux
./up.sh
```
```powershell
# Windows (dev lane)
.\up.ps1
```

`up.*` clones Open Design (first run), installs deps, detects a coding agent on
PATH, and starts the local web canvas. It creates a `.od/` directory
(SQLite + per-project artifacts) inside the checkout.

## Back up the `.od/` project files to the Life Center

```bash
./backup-od.sh        # rsync .od/ -> $OPEN_DESIGN_BACKUP_TARGET (Class B)
```
```powershell
.\backup-od.ps1
```

The desktop/laptop holds the **authoritative** copy; the Life Center holds the
backup. Point `OPEN_DESIGN_BACKUP_TARGET` (in `../../.env`) at a Life Center
path such as `/tank/models-archive/open-design`, then include it in the restic
3-2-1 job (`runbooks/backup-restore.md`).

> Install specifics (exact commands/ports) can change upstream — check the
> current Open Design README before first run rather than trusting these
> defaults blindly.
