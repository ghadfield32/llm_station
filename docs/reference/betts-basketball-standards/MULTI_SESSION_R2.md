# Multi-session R2 + Railway safety runbook (PR 69 S5)

How to push code, data artifacts, and model artifacts to production
without overwriting another Claude session's work or corrupting the
R2 manifest.

The existing infrastructure already solves this — this doc captures
the contracts so session-N can honor what session-(N-1) shipped.

## The three single-writer boundaries

### 1. Git main → GitHub (code + docs + configs)

**Rule.** Stage only the files this session owns; never `git add -A`.

**Mechanism.** Each session reads `git status --short` before committing and
stages exact paths:

```bash
git add path/to/file1.py path/to/file2.yml        # explicit
# NOT: git add . / git add -A
```

**Concurrency.** Two sessions editing the same file is the only failure
mode. Resolve by reading the remote file first (`git pull --rebase`),
deciding whether to append or merge, then pushing.

**Never.** Force-push to `main` (rewrites history for the other session).
Skip hooks (`--no-verify`). Amend a pushed commit.

### 2. R2 via `scripts/upload_data.sh` (parquets, pkls, DuckDB files)

**Rule.** Every R2 write goes through `upload_data.sh`. Direct
`aws s3 cp` or `rclone` from a DAG is a contract violation.

> **Machine writer-boundary.** The single-writer boundary is also a
> single-*machine* boundary: the **desktop** is the only production R2 writer;
> the **laptop** is read-only from prod. `upload_data.sh` is fail-closed on
> `BETTS_CAN_WRITE_PROD_R2=1`. Full contract:
> [LOCAL_FLEET_R2_WORKFLOW.md](LOCAL_FLEET_R2_WORKFLOW.md).

**Mechanism.** The script acquires an advisory R2 lock
(`upload.lock`, TTL 10 minutes) before any write and releases it on
exit. A second invocation aborts with a clear holder/age message
instead of trampling the in-flight manifest rotation; rerun only after
the first writer finishes or the stale TTL expires.

From §26.25:
```
scripts/upload_data.sh --boards        # push prospect boards
scripts/upload_data.sh --sportsbook    # push sportsbook pricing
scripts/upload_data.sh --dry-run       # no push; inspect upload plan only
scripts/upload_data.sh --validate      # validate, then upload if the gate passes
```

**Concurrency.** Two sessions (or two DAG tasks) that both call
`upload_data.sh --boards` are safe only when one writer runs at a time.
The second session must stop, let the current writer finish, then rerun
fresh. No interleaving, no manifest corruption.

**WSL note.** When running from Docker Desktop / WSL bind-mount mirrors
(`/mnt/wsl/docker-desktop-bind-mounts/...`), keep `upload_data.sh` on
the WSL-safe Python uploader path. Falling back to a Windows
`python.exe` against a bind-mount temp file can lose the local lock JSON
before `upload.lock` is published.

**PowerShell note.** Do not wrap `upload_data.sh` in `uv run` from a
Windows shell while another venv is active. `uv` will try to reconcile
the repo `.venv` before the bash uploader even starts, and WSL-created
`.venv/lib64` symlinks can fail on Windows with `Access is denied`.
Use:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/upload_data.ps1 --playoff-strategy
```

That wrapper clears `VIRTUAL_ENV`, pins `UV_PROJECT_ENVIRONMENT`, and
delegates the actual publish to the canonical WSL/bash writer path.

**Never.** Call `aws s3 cp` or `boto3.put_object()` to the R2 public
allowlist paths directly. The allowlist in
`api/src/airflow_project/dags/_r2_upload_utils.py::_PUBLIC_ALLOWLIST_PREFIXES`
is the contract boundary.

### DuckDB / Quack lab sessions are not R2 writers

DuckDB Quack can let several DuckDB clients query one server-owned DuckDB
session, but it does not change the R2 production contract.

**Rule.** A Quack server may inspect only a copied/promoted read-only artifact
or a disposable test database unless the user explicitly approves a write lab.
It must never point at a live writer path for `basketball.duckdb`, mutate the
Railway serving copy, or publish artifacts to R2.

**Mechanism.** One session owns the Quack server process, token, authz policy,
logs, and cleanup report. Other sessions can run read-only queries through
`quack_query(...)` or `ATTACH 'quack:host'` only after the owner shares the
approved URI and scope. Production movement still goes through
`scripts/upload_data.sh`; if an R2 upload is needed after a Quack analysis, the
operator stops the server, validates the generated artifacts locally, then runs
the canonical uploader as the single writer.

**Never.** Use Quack to bypass `upload.lock`, direct-write R2 manifests,
expose raw SQL to the frontend, or hide missing/stale data behind fallback rows.

### 3. Airflow metadata DB (schema.dag_run, task_instance, etc.)

**Rule.** Cleanups happen inside a single `BEGIN; ... COMMIT;` block.

**Mechanism.** Direct SQL deletes for stale history are acceptable
(§26.32 cleared 289 task_instance rows this way) but ONLY inside a
transaction. Two sessions running uncoordinated DELETEs against the
same DAG's history can miscount.

**Never.** Run `TRUNCATE` on `task_instance`, `dag_run`, or
`ingest.*` tables. Row-targeted DELETEs only.

## Railway production push

### Via Railway CLI

```bash
railway up                             # deploys the Railway-linked service
railway run --service=<api> python ... # run ad-hoc command inside the service
```

**Precondition.** Commit and push to GitHub `main` first. Railway
watches `main`. A `railway up` from an unpushed working tree deploys
state the repo doesn't see, creating drift between GitHub and the
live service.

### Via Railway MCP

When a Claude session has the Railway MCP available it can:
- List services / deployments
- Pull service logs
- Restart a service

**Rule.** All service *restarts* are mutations and require user
confirmation. The MCP should not auto-restart based on an agent's
judgment alone.

### Hot-reload artifacts from R2

`upload_data.sh` uploads to R2 → Railway API's `/admin/reload_models`
endpoint rereads the manifest → champions swap in-process without a
container restart. That means:

- A `upload_data.sh --sportsbook` run _can_ affect live predictions
  within ~30 seconds.
- Running the upload during a Claude session with a user question
  in-flight is user-visible. Confirm before invoking.

## What to do if you see work you don't recognize

1. **Git.** `git log --author-date-order -20 --format="%h %ai %an %s"` —
   is another session's commit in the tree? If so, rebase rather than
   force-push; keep their work.
2. **R2.** `scripts/upload_data.sh --dry-run` is the non-mutating
   check. `scripts/upload_data.sh --validate` still uploads if the
   validation gate passes. If the manifest shows a version you didn't
   write, someone else uploaded; read their PR before overwriting.
3. **Airflow metadata.** `airflow dags list-runs -d <dag>` shows every
   run state. Scheduled runs marked `success` that you didn't trigger
   manually are the scheduler doing its job — never roll them back.

## Sanity-check commands

```bash
# What's in the repo but not pushed?
git log origin/main..HEAD --oneline

# What does the R2 manifest say is live?
curl -s "$BUCKET_URL/manifest.json"

# What did the scheduler do in the last hour?
docker exec betts_basketball-airflow-scheduler-1 airflow dags list-runs | head -20

# What's in the failure-triage window right now?
docker exec betts_basketball-airflow-scheduler-1 \
    python /workspace/scripts/ops/ingest_ops.py failure-triage --hours 48 --top 20

# GPU training cadence + spend
docker exec betts_basketball-airflow-scheduler-1 \
    python /workspace/scripts/ops/gpu_schedule_report.py
```

## The negative rules (never do these)

- `git add -A` or `git add .` blindly
- `git push --force` to `main` or any shared branch
- `git commit --amend` on a commit that is already pushed
- `aws s3 cp` / `rclone` directly to the R2 public-allowlist prefixes
- `TRUNCATE` or unscoped DELETE on Airflow metadata DB
- Auto-deploying to Railway from an uncommitted local tree
- Restarting a Railway service without user confirmation
- Calling `upload_data.sh` twice in parallel from the same session (the
  lock resolves it but wastes time; serialize in the caller)

## Pipeline-specific addenda

### Geo-social (Basketball-GO)

**R2 prefix.** `geo-social/` (per `_PUBLIC_ALLOWLIST_PREFIXES`).

**Which artefacts ship.** Privacy-safe parquet exports written by
`s6_refresh_exports.py` (region activity, venue playability rollups, safety
KPIs). Operational tables (`geo_social_venues`, `geo_social_events`,
`geo_social_user_wearable`, etc.) live in Postgres on Railway and are NOT
shipped to R2 — they're the live serving plane. Only the
privacy-safe-aggregate marts go through the upload contract.

**Upload command.** `scripts/upload_data.sh --geo-social`. Validation gate:
`validate_frontend_contract.py` V5 must pass 3/3 before the writer accepts
the upload (last green: Session 640).

**Multi-session contention surface.**
- Two sessions running `index_us_courts.py` against the same Railway DB are
  safe — `backfill_venues.run()` is idempotent on
  `(source_provider, source_id)`. The OSM Overpass 2 s rate-limit is
  per-session, so two parallel runs from different machines double the
  Overpass load — coordinate.
- Two sessions running `s1_refresh_geo_index.py` simultaneously will both
  recompute H3 cells; the writes are last-wins per row. Run only one at a
  time; the script is fast (<60 s with current 15,857 venues).
- `seed_test_data.py` is per-title idempotent and per-source-id
  idempotent for venues. Safe to re-run; no R2 side-effects.
- Migration runs (`alembic upgrade head`) are auto-invoked by Railway's
  `start.sh` on container boot. Do not run `alembic upgrade head` from a
  local session against the production DB — the deploy will run it for you.

**Frontend contract changes.** Touching any of
`api/src/pipelines/geo_social/contracts.py`,
`web/src/services/geoSocialService.js`, or any
`web/src/hooks/useGeoSocial*.js` requires re-running
`scripts/geo_social/validation/validate_frontend_contract.py` (V5) before
the next R2 upload. The validator parses both sides and asserts every key
the frontend reads is present in the Pydantic schema with a matching type.

**What NOT to do.**
- Do not `aws s3 cp` parquets directly to `geo-social/` (the allowlist guard
  refuses but the contract violation is the actual issue).
- Do not push frontend dist files manually — Railway rebuilds the Vite
  bundle from `Dockerfile` on each `main` push.
- Do not seed against the Railway DB without `railway run` — without it
  the script writes to the local Postgres, not the production one, and the
  user sees no change. This is the #1 source of "I seeded but nothing
  appeared" reports.
