# Growth OS — upgrade report (2026-06-12, second pass)

> **Third pass — Tailscale cutover (same day):** Tailscale installed on this
> box (`vengeance.taile6a055.ts.net`). Verified: `msi` is a *different*
> machine, and `betts-airflow-prod-01` has been **offline for 92 days** — the
> migration target isn't running, so this box stays the host for now.
> Done: AppFlowy now issues tokens for `https://vengeance.taile6a055.ts.net`
> (FQDN/https/wss in `.env`), nginx rebound to loopback-only
> `127.0.0.1:8081` (8080 was taken by the bball pipeline), curator repointed
> internally, full stack + curator verified green afterwards.
> **Serve is enabled and verified end-to-end** (2026-06-12): health 200,
> web UI 200, and GoTrue login all confirmed over
> `https://vengeance.taile6a055.ts.net` — TLS by Let's Encrypt, tailnet-only
> (no Funnel, nothing on the LAN). Survives reboots: the serve config is
> persistent and `--bg` re-applies on tailscaled start.
> Phone: Tailscale app (same account) + AppFlowy app → self-hosted server
> `https://vengeance.taile6a055.ts.net` → gmail login.
>
> **Reliability fix found during the cutover:** while `appflowy_cloud` was
> briefly down, failed row writes were still being marked "seen" and would
> never retry (three sportsdataverse repos were silently lost this way).
> `upsert()` now returns the pre_hashes that actually wrote and the curator
> marks only those — failures stay eligible for the next hourly run.

Executed the prioritized plan as far as permissions allow. Two facts changed
the plan's premises, both verified directly:

- **This machine's hostname is `VENGEANCE`, not `msi`**, and **Tailscale is
  not installed on it**. Whatever tailnet view listed `msi` as "where the
  stack runs" — double-check machine identities before migrating.
- **SSH to `betts-airflow-prod-01` was denied by the permission policy**, so
  the P0 migration is a runbook, not a done deed:
  [growth-os/deploy/linux/MIGRATION.md](growth-os/deploy/linux/MIGRATION.md)
  (with systemd units + backup timer in `deploy/linux/`).

## What is live now (all verified end-to-end)

### 1. Embedding-based relevance scoring (P1)

`scoring.method: embedding` in [sources.yaml](growth-os/config/sources.yaml);
`nomic-embed-text` pulled into your Ollama. Items score by cosine similarity
to a weighted profile vector; keyword penalties + star bonus still apply;
selection stays top-N. Falls back to keyword scoring with a warning if Ollama
is unreachable. Measured effect: *"Hierarchical priors improve NBA
shot-quality models"* scored **6.88** semantic vs **2.0** keyword; ranking
came out exactly right on the test set.

**The curator container uses it too** — Docker Desktop's
`host.docker.internal` proxies from host loopback, so it reaches your
loopback-only Ollama without exposing anything. Verified in the container
logs: `scoring: embedding (nomic-embed-text @ host.docker.internal:11434)`.

### 2. LLM-written daily brief (P1)

`python -m growthos.brief` now opens with a **"Why today matters"** section:
`qwen3:8b` clusters the day's items into themes, says why each matters for
your work, and bolds the must-read. Falls back to the plain list if Ollama is
down. Today's brief (in `review` and `_export/brief_2026-06-12.md`) has it.

### 3. Trustworthy MCP server (P2)

[growth-os/agent/growthos_mcp.py](growth-os/agent/growthos_mcp.py) — wraps
the *verified* client only; no community MCP code. Tools, all tested live:
`list_inbox`, `search`, `set_status` (validated statuses; partial updates
verified to preserve other cells), `add_lesson`, `add_book`, `add_note`,
`review_lesson` (SM-2-lite scheduling), `latest_brief`.

- Claude Desktop/Code: merge [agent/mcp.config.json](growth-os/agent/mcp.config.json)
  (no secrets in it — the server reads `growth-os/.env`).
- Phone later: run with `--http` (binds 127.0.0.1:8765) behind
  `tailscale serve` as a remote connector.

### 4. Backups (P3)

[scripts/backup.ps1](growth-os/scripts/backup.ps1) — pg_dump + `_state`,
14-day retention. Ran once: `backups/appflowy_2026-06-12.sql` (1.1MB).
Schedule it: `schtasks /create /tn "GrowthOS backup" /sc daily /st 02:00 /tr
"pwsh -NoProfile -File <path>\backup.ps1"`. Linux equivalents are in
`deploy/linux/`.

Seeded along the way: *Statistical Rethinking* (library), one lesson, one note.

## Blocked on you (in priority order)

1. **The migration** (`deploy/linux/MIGRATION.md`) — or grant SSH to
   `betts-airflow-prod-01` and I'll run it.
2. **Tailscale on this machine** — needed both for phone access while the
   stack lives here and for `scp` in the migration.
3. **`OLLAMA_HOST=0.0.0.0` + Ollama restart** — only needed once the curator
   moves to the Linux box and must reach Ollama over the tailnet (locally the
   Docker Desktop proxy already works; I was not permitted to widen the bind).
4. **GitHub PAT** in `growth-os/.env` (one search query still 403s hourly).
5. **`curriculum-appflowy.csv`** — not on this machine; drop it anywhere in
   the project and ask Claude to import it (the row API + venv make that a
   one-liner now).
