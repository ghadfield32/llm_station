# AppFlowy to first-party boards

AppFlowy is a read-only historical recovery source. The first-party board stores
and governed kanban event log are current truth.

## Preserved recovery evidence

The 2026-07-15 recovery used copies of the original Docker volumes:

- `appflowy_postgres_migration_snapshot_20260715`
- `appflowy_minio_migration_snapshot_20260715`

The original `appflowy_postgres_data` and `appflowy_minio_data` volumes were
not modified. The isolated recovery service exposed AppFlowy and GoTrue only on
loopback ports 18000 and 19999.

| Source database | First-party board | Rows |
| --- | --- | ---: |
| papers | research_papers | 1,351 |
| repos | research_repos | 89 |
| dags | dag_operations | 118 |
| library | reading_library | 283 |
| geoffhadfield32_content | linkedin_content_pipeline_internal | 40 |
| world_model_sports_content | linkedin_content_pipeline_internal | 41 |
| **Total** | | **1,922** |

The retained 12-paper and 10-repo CSVs were incomplete evidence and were not
used as authoritative recovery input.

## Migration contract

`uv run cc appflowy-migrate` is dry-run by default. It reads and validates the
entire source before writing, rejects unresolved identities/statuses, preserves
exact cells and provenance, initializes only missing statuses, and never deletes
or archives a card because a source row is absent. Imported fields update only
while the first-party value still equals the prior import; divergent first-party
edits win and receive an explicit conflict record.

The historical library used `Name` for the book title while other sources used
`Title`. The library migration therefore has an explicit ordered alias contract:
`Title` wins when present, otherwise `Name` supplies the first-party `title`.
This repairs cards imported before that mapping existed without resetting their
status. A divergent operator-edited first-party title is reported as a conflict
and is never overwritten. Dry-run output includes per-field change counts and a
separate status-initialization count so a title-only repair is distinguishable
from a workflow change.

One real `Key` collision existed across the two content accounts. The final
historical owner retains the legacy key; the other row receives a deterministic
`<account>:<key>` identity. This produces 81 distinct post cards and remains
idempotent.

Required environment variables are `APPFLOWY_BASE_URL`,
`APPFLOWY_AUTH_URL`, `APPFLOWY_WORKSPACE_ID`, `APPFLOWY_EMAIL`, and
`APPFLOWY_PASSWORD`. Secrets remain in environment files and must never be
printed or committed.

```powershell
uv run cc appflowy-migrate
uv run cc appflowy-migrate --apply
uv run cc appflowy-migrate
```

The final command is the idempotence audit: every row must report `noop`, with
zero creates, updates, and conflicts. The completed recovery met that contract
for all 1,922 rows.

For a library-title repair, first review the dry run and require exactly the
expected `title` updates with zero status initializations. `--apply` remains an
explicit operator action; do not infer approval from a successful dry run. After
apply, repeat the dry run and verify zero remaining changes. Conflicts are an
intentional stop for human reconciliation, not values for the importer to fill.
Retained first-party evidence contains 276 nonblank `Name` titles and seven rows
whose source title is genuinely blank. The source-backed dry run must confirm
that count; blank rows remain visibly unresolved and are never filled by guess.
They stay individually editable in the cockpit and do not participate in
duplicate title/author comparison until an operator supplies a title.

## Ongoing operation

Do not keep AppFlowy running as a second live writer. `growthos-watcher` owns
current Papers/Repos/DAG intake through the first-party client. Posts and current
Books are edited in the cockpit; the library importer is historical recovery only.
Watcher outcomes are stored at `growth_os/_state/watcher_status.json` and
served by `GET http://127.0.0.1:8787/api/upkeep/status`.

Stopping the isolated recovery containers does not delete original or snapshot
volumes.
