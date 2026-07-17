# Kanban and TODO data recovery

The cockpit uses immutable, content-addressed runtime snapshots as a prerequisite
for recurring board maintenance and daily DAG mutation. This is a loss-aware
recovery layer, not a cross-database transaction claim: each source is captured
from a stable before/after fingerprint, SQLite uses its online backup API, and a
final source-set watermark proves exactly which versions belong to the snapshot.

## What is protected

The allowlist includes the live Ledger SQLite database, first-party board stores,
Kanban event history, board/domain configs, job-search state and memory, Growth OS
canonical state and exports, the autonomy repo registry that grounds research
project-fit analysis, Betts GRAND TODO Markdown, chat threads/transcripts,
memory, append-only maintenance decisions, and retained AppFlowy recovery evidence.
Missing required sources fail closed. Optional sources are recorded as absent.

Secrets, caches, test directories, temporary files, locks, logs, symlinks,
`source_cache`, and the cycle-changing watcher status receipt are excluded. The
backup implementation refuses source/root recursion and refuses to guess a host
`data/ledger.db`; `KANBAN_BACKUP_LEDGER_DB` must identify the actual live Ledger.

Snapshots contain SHA-256 inventories, semantic JSONL/YAML checks, SQLite
`PRAGMA integrity_check`, a manifest written last, directory fsync where supported,
and an atomic staging-to-final rename. Existing snapshots are never overwritten
or automatically deleted. A current identical watermark is fully reverified and
reused; any canonical data change produces a new snapshot.

The required autonomy snapshot keeps each paper/repo analysis reproducible:
onboarding a repository changes the source-set watermark before a new project-fit
analysis can be written.

## Scheduling and mutation gates

- `growthos-watcher` verifies or creates a current snapshot before every hourly
  cycle. Failure marks every mutation `skipped_backup`.
- The job-search and self-improvement DAGs have the same verified-backup task as
  an upstream dependency.
- The daily Kanban maintenance scan runs only after preceding source syncs succeed.
  It is skipped on partial source state instead of making cleanup suggestions from
  an incomplete picture.
- The watcher records each result in `growth_os/_state/watcher_status.json`; this
  operational receipt is intentionally not a canonical backup source.

The bootstrap snapshot created before the 2026-07-16 DAG window is
`20260716T044230.008156Z-cd53ab7d51fa`, with source-set watermark
`cd53ab7d51fa9e33b996808d8f6eed995c48fc1aa810355e9968b9f96d0516b0`.

## Operator commands

Run against the watcher container so `/backup-sources/ledger/ledger.db` is the
mounted live named volume, not a possibly stale host file:

```powershell
docker compose --profile ui exec growthos-watcher python -m command_center.cli.runtime_backup create
docker compose --profile ui exec growthos-watcher python -m command_center.cli.runtime_backup list
docker compose --profile ui exec growthos-watcher python -m command_center.cli.runtime_backup verify
```

Restore is staging-only and refuses a non-empty target. It never writes to a live
source path:

```powershell
docker compose --profile ui exec growthos-watcher python -m command_center.cli.runtime_backup restore --target /backups/restore-drills/verify-YYYYMMDD
```

After the command, compare the restored manifest, open each restored SQLite file
read-only and run `PRAGMA integrity_check`, validate YAML/JSONL, and only then plan
a separately approved live recovery. Never copy a restore over running services.

## Storage-failure boundary

The default `./backups` bind mount protects against application defects, bad
imports, and accidental logical changes, but is a degraded disaster-recovery
posture when it shares the source disk. For disk/host loss protection, set
`KANBAN_BACKUP_HOST_PATH` to an encrypted external or off-host synchronized path
before starting the watcher and Airflow profiles. Confirm that path is itself
monitored and versioned. The system reports snapshots as a `local-layer` and does
not claim zero data loss or off-host protection unless the operator supplies that
storage.

Recommended operational objectives are: a verified snapshot before every
mutation window, an hourly maximum logical-change exposure while the watcher is
healthy, a daily independent restore drill, and no automatic snapshot deletion.
If backup verification fails, fix storage/permissions first; do not bypass the
gate to make board changes.
