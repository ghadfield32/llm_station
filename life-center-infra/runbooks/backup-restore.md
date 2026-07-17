# Backup & restore runbook (3-2-1)

Backups follow the plan/GATE0 contract: **3 copies, 2 media, 1 off-site**, and
**a backup is not accepted until a restore is proven.** Restic is the default
engine (Kopia is the documented alternative — pick one, not both).

## Layers

| Layer | Where | Notes |
| --- | --- | --- |
| Local snapshots | ZFS/pool 6-hourly | Fast rollback; NOT an independent backup |
| Local encrypted repo | separate 16 TB-class disk, connected only for backup/verify/restore | `RESTIC_REPOSITORY=/backups/restic` |
| Off-site | Backblaze B2, client-side encrypted, append/write-scoped credential | high-value set only |

Three separate identities (per readiness doc): **writer** (append-only),
**restore reader**, **offline maintainer** (prune/forget). Never one all-powerful key.

## Run a backup

```bash
./lc backup            # restic backup one-shot (foundation tier)
```

Application-consistent first: dump databases with the app's supported exporter
(e.g. Paperless document exporter, Nextcloud `occ` maintenance) BEFORE snapshotting
their volumes. A live volume copy is not a valid database backup.

## Restore-test drill (do this quarterly; log dated evidence)

1. Provision a clean, version-matched instance in `restore-tmp/`.
2. Restore the target snapshot: `restic -r $RESTIC_REPOSITORY restore latest --target restore-tmp/`.
3. Import the application export into the clean instance.
4. Verify: row/object counts, a known document opens, hashes match the manifest.
5. Record: snapshot id, schema/app version, restore command, result, operator.
6. Tear down `restore-tmp/`.

Each database snapshot records: dump, schema + application versions, source
timestamp, row/object counts, SHA-256 manifest, encryption metadata, restore
command, and restore-test result.

## Recovery objectives

RPO/RTO targets per class are in
[`LIFE_CENTER_GATE0.md`](../../docs/operations/LIFE_CENTER_GATE0.md) — do not
loosen them without a documented impact/cost decision.
