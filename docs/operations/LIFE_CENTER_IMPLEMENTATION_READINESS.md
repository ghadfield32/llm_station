# Life Center implementation readiness contract

**Status:** design gate; no Life Center, auxiliary node, backup repository,
VLAN, B2 repository, or controlled action is deployed.
**Purpose:** make the final architecture operationally testable without
pretending that a validated document is a working recovery system.

## Canonical roles

```text
RTX 4090 desktop: always-on llm_station, Betts production coordination, CV/video,
                  local models, agents, and the only normal local production writer.
Life Center:      authoritative mirrored storage and household/archive services.
MSI RTX 5080:     portable human work, remote desktop access, bounded sample CV.
Old laptops:       optional dedicated backup/restore/cache/worker roles only.
Phone/remote PC:   Tailscale, read-only cockpit, native-app deep links, approvals.
```

Old laptops are non-authoritative and preemptible. Do not build distributed
storage, RAID across laptops, Ceph, GlusterFS, Storage Spaces over shares, or a
backup set whose restoration needs several sleeping laptops.

## Critical-backup exception

The healthiest old 2 TB laptop may defer the 16 TB full-pool backup disk only
while **all** conditions below hold:

- the measured protected critical set is below 1.2 TiB and its 12-month forecast
  stays below 80% of usable laptop capacity;
- every omitted source is explicitly reproducible from another authority or
  intentionally accepted as losable;
- the laptop is a dedicated `backup` role with no secondary role, no SMB share,
  no Docker/agent endpoint, no browser/general use, and no delete/prune token;
- disk SMART short and long tests, read/surface test, sustained write, thermal,
  battery, power-adapter, reboot, disk-encryption, and recovery-key tests pass;
- encrypted append-only backup works, the writer cannot alter/delete snapshots,
  a separate maintainer identity is offline except for maintenance, and a restore
  works after writer-credential revocation; and
- 0.5–1 TiB of the highest-value data has an independently restored encrypted
  off-site copy.

Purchase the separate full-pool local backup target immediately when any one
condition fails, the critical set reaches 70% of usable capacity, 12-month
forecast reaches 80%, health degrades, restore time misses RTO, more original CV
media is retained, or full-pool local recovery is required. A same-building
different-room laptop is a separate local copy, never an off-site copy.

Run the local helper on the candidate laptop before admitting it:

```powershell
.\scripts\qualify_life_center_backup_laptop.ps1 -BackupRoot 'D:\LifeCenterBackup'
.\scripts\qualify_life_center_backup_laptop.ps1 -BackupRoot 'D:\LifeCenterBackup' -RunWriteTest -WriteTestGiB 8
```

The default invocation is read-only. The explicit write test leaves an 8 GiB
random file for manual verification/deletion. Its ignored local output does not
claim that SMART, append-only access, restores, off-site backup, or physical
separation have passed.

## Backup identities and proof

Use exactly three separate identities:

| Identity | May do | Must not exist on |
| --- | --- | --- |
| backup writer | append snapshots only | desktop, agents, cockpit, maintainer workstation |
| restore reader | read/restore only | routine backup job |
| backup maintainer | explicit prune/repair/retention | desktop, Life Center runtime, agent, cockpit |

The writer must be tested attempting a forbidden delete/alter action. Maintenance
credentials are offline except for deliberate maintenance. The first working
implementation uses encrypted restic snapshots and an append-only `rest-server`
or equivalent reviewed backend; repository password/recovery material stays
offline and separate from the repository.

Required evidence before the exception is accepted: successful repository check,
sample file restore, application-consistent database restore, reboot restore,
writer-revocation restore, B2 restore, and recorded physical location class.

## Storage decisions

Three-year capacity is:

```text
current authoritative retained TiB + (3 × annual retained growth TiB)
+ planned new collections TiB
```

Use only non-overlapping authoritative paths. A 10 TB mirror is eligible at or
below 6.3 TiB, a 12 TB mirror at or below 7.6 TiB, otherwise re-price 16 TB or
larger. Do not count Docker, project, or system envelopes alongside children.

Create this **ignored local** file after making the retention decision; do not
commit real paths, filenames, or secrets:

```json
{
  "targets": [
    {"name": "authoritative_docs_photos", "class": "authoritative-retained", "path": "PRIVATE_LOCAL_PATH"},
    {"name": "critical_backup_source", "class": "critical-backup", "path": "PRIVATE_LOCAL_PATH"},
    {"name": "b2_high_value_source", "class": "offsite-protected", "path": "PRIVATE_LOCAL_PATH"}
  ]
}
```

Save it as `generated/life-center-growth/backup-scope.json`, then run the daily
measurement. New scope targets need their own 30 days of observations; their
classes can overlap each other but paths inside a class cannot overlap. The
report stores aggregate counts only and refuses the three-year forecast until
every authoritative target is mature.

Use a 1 TB Life Center NVMe only after a clean forecast proves OS, databases,
metadata, indexes, logs, caches, upgrade copies, and rollback headroom remain
below 400–500 GiB. Otherwise use 2 TB; an optional laptop cannot host appdata,
PostgreSQL, or Docker state.

Keep original video only when legally and operationally justified. Default
retention: decoded frames 3–7 days, failed scratch 7 days, temporary
crops/transcodes 14 days, reproducible intermediates 30 days; retain gold labels
and final structured results.

## Agent and network boundary

Start with a redacted read-only status surface: service health, backup age,
capacity, archive freshness, model inventory, auxiliary status, security
findings, and pending maintenance. It never returns paths, filenames, contents,
photo metadata, keys, credentials, full logs, URLs, shell access, SQL, Docker
arguments, image names, volume paths, or environment variables.

No dashboard, MCP service, or agent receives Docker socket access. Future
actions are fixed typed handlers with approval, timeout, idempotency, evidence,
rollback, and audit events; arbitrary commands are structurally absent. L4
operations—original/backup deletion, storage destruction, DNS/router/Tailscale
changes, vault/key changes, or public exposure—remain offline human-only.

Use Tailscale grants/tags with deny-by-default policy. The initial service is
tailnet-only via Serve; Funnel is disabled. An auxiliary worker cannot assign
itself a backup or Life Center tag.

## Repository and purchase gate

This checkout is on `main`; auxiliary and scoped-growth additions must be a
tracked reviewed change before they are considered canonical. Do not directly
edit or push `main`. Create a dedicated branch, confirm `git status` contains
only the intended paths, run checks, commit deliberately, push, open a draft PR,
review/merge it, then fetch `main` and verify the files are present.

No hardware purchase is authorized until the 30-day scoped growth result,
laptop qualification, Cat6/noise/thermal acceptance, exact Value and Reliability
BOM comparison, and same-day seller/warranty/model/return validation are complete.
The 16 TB disk, BMC platform, managed switch, AP, laptop adapters, CasaOS, and
self-hosted password manager remain deferred unless their specific gates pass.
