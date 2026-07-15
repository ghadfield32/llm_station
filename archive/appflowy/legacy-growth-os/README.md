# Growth OS

A self-hosted, always-on **learning + self-improvement operating system**. It keeps
your books, lessons, notes, and day-to-day improvement loop in one place, and a
background Curator continuously pulls in the **papers, repos, and advances** that
matter to your work. You use it from your phone (AppFlowy app) and an agent
(Claude via MCP) reads and writes all of it for you.

## What it does, mapped to your goals
- **Keep & update notes / lessons / books** → eight AppFlowy databases (below).
- **Continually learn** → `Lessons` DB with spaced-repetition review (SM-2-lite).
- **Auto-populate papers** → arXiv fetcher, scored to your interests.
- **New repos to look at** → GitHub search fetcher (recent, min-stars).
- **Advances in LLMs/coding/DS** → RSS/HN/lab-blog fetcher (`Signals`).
- **Always-on, phone-accessible** → Docker stack + Tailscale + AppFlowy mobile.
- **Easy for agents** → AppFlowy MCP + stable schema + `agent/recipes.md`.
- **Mission intake** → `mission_intake` cards can be promoted into Command Center
  Ledger missions through the dry-run-first Kanban bridge.

## The databases (see `config/schema.yaml`)
`library` (books) · `lessons` (spaced review) · `notes` (pages) · `papers` (auto) ·
`repos` (auto) · `signals` (auto) · `sources` (editable feeds) · `review`
(daily log + habits) · `mission_intake` (DAG/Learning/Betts Basketball work cards).

## Architecture (five layers)
1. **Storage** — AppFlowy Cloud (Docker): your databases + notes.
2. **Curator** — `growthos/` Python service: fetch → score → dedupe → upsert.
3. **Brief** — `growthos/brief.py`: daily brief + review queue.
4. **Agent** — AppFlowy MCP server: Claude reads/writes everything.
5. **Scheduler** — host cron/systemd timer (or the bundled compose loop).

Data flow: `arxiv|github|rss → CuratedItem → score(interest_profile) → dedupe(state) → top-N → AppFlowy rows`.
Mission flow: `mission_intake Ready/Approved card → Command Center Kanban bridge → Ledger mission → normal gates/judges/executors`.
Relevance is data-driven (weighted terms in `config/sources.yaml`) and selection is
**top-N per source**, so there is no arbitrary global threshold to babysit.

---

## Setup

### 0. Prerequisites
Docker, Python 3.12, `uv` (for the MCP), a domain or Tailscale, and a GitHub PAT (optional).

### 1. Stand up AppFlowy Cloud
Clone `AppFlowy-IO/AppFlowy-Cloud`, fill its `deploy.env`
(`POSTGRES_PASSWORD`, `GOTRUE_JWT_SECRET`, `API_EXTERNAL_URL`, admin email/pw, S3/MinIO),
then `docker compose up -d`. Point the AppFlowy desktop/mobile app at your `API_EXTERNAL_URL`.

### 2. Create the databases (automated)
```bash
python scripts/setup_workspace.py
```
Creates the eight databases from `config/schema.yaml` via the REST API and
writes the name -> {view_id, database_id, field ids} mapping to
`config/databases.json` (idempotent: re-runs only create what's missing).
The first schema column of each database maps onto the grid's primary
column. Import your existing `curriculum-appflowy.csv` to seed `library`.

### 3. Configure the Curator
```bash
cp .env.example .env          # fill APPFLOWY_* and GITHUB_TOKEN
pip install -r requirements.txt
python scripts/bootstrap_appflowy.py     # prints workspace_id + database ids
# put workspace_id in .env
```

### 4. First run — dry run (safe)
```bash
python -m growthos.curate --dry-run      # writes _export/papers.csv, repos.csv, signals.csv
```
Inspect the CSVs. This is real, scored, deduped output.

### 5. Go live
The live write path is **verified** against self-hosted AppFlowy Cloud: rows
are upserted with `PUT /api/workspace/{ws}/database/{db}/row` and a
`pre_hash` of the item's external id, so the server itself dedupes. Set
`GROWTHOS_DRY_RUN=false` in `.env` and run:
```bash
python -m growthos.curate
python -m growthos.brief                 # daily brief -> review DB + _export/brief_*.md
```

### 6. Always-on schedule
The bundled loop (hourly curate, daily brief after 06:00):
```bash
docker compose -f docker-compose.curator.yml up -d --build
```
…or a host cron/Task Scheduler job calling `scripts/run_daily.sh` once a day.

### 7. Phone access (anywhere, secure)
Install **Tailscale** on the server and your phone; point the AppFlowy mobile app
at the server's tailnet URL. No ports exposed to the internet. (Cloudflare Tunnel
is the alternative if you want a public hostname.)

### 8. Agent layer
Copy `agent/mcp.config.example.json` into your Claude config (Desktop or Code),
fill the paths/creds, restart. Use `agent/recipes.md` for daily prompts. The
filesystem MCP entry also lets the agent read this repo (configs, brief files).

---

## Robustness & efficiency built in
- **Idempotent**: `state.py` remembers every `external_id`; reruns never double-post.
- **Fails fast**: Pydantic validates config/env at startup.
- **Resilient writes**: one bad row is logged and skipped, not fatal; retries with backoff on auth.
- **Rate-aware**: respects arXiv/GitHub limits; GitHub PAT raises ceilings.
- **Dry-run first**: CSV fallback means the pipeline is useful before the write path is tuned.
- **Backups**: `pg_dump` the AppFlowy Postgres on a timer; back up `_state/`.

## Honest caveats
- The row-write endpoint **is now verified** against the current self-hosted
  AppFlowy Cloud (see `growthos/appflowy.py` docstring); if a future image
  changes it, `ENDPOINTS` is still the single place to adjust.
- Select values only persist when the option already exists on the field, so
  free-form tags (Topics/Tags/Habits) are plain text in `config/schema.yaml`.
- The **AppFlowy MCP** servers are community-built; read the source before trusting writes.
- AppFlowy Cloud is **open-core**: the self-host free tier allows **1 user**
  (+3 guests) — the GoTrue admin is a separate system account and does not count.

## Extending
Add a source = write `growthos/sources/<x>.py` returning `list[CuratedItem]` and
wire it into `curate.py`. New database = add to `schema.yaml` + `FIELD_MAP`.
