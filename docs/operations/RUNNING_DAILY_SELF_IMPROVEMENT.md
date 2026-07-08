# Running the daily self-improvement loop

The control plane improves **itself** once a day: it scans sources, ranks
findings, and drafts `Proposed` experiment cards. It is **observer/draft-only** —
it never applies code, promotes, merges, or deploys. A human approves a card to
turn it into a Ledger mission that runs the normal branch/worktree/devcontainer/PR
loop with review.

## Commands

```bash
uv run cc self-improvement-scan                              # observer; ranks findings, ZERO writes
uv run cc self-improvement-daily --draft-kanban true --apply false   # draft Proposed cards
uv run cc self-improvement-report                            # write the decision report
```

- `scan` and `report` make **zero** registry writes.
- `daily --draft-kanban true` drafts `Proposed` cards through the **ObserverCharter**.
- `daily --apply true` (applying **code**) is **refused**
  (`code_apply_not_supported_daily_is_observer_draft_only`). Code changes only
  happen via an approved mission.

Default scanners are **network-free** (code health + ledger) — deterministic, no
credentials. Evidence is written to
`evaluation/system-validation/20260616-autonomy-contracts/self-improvement-daily.json`.

## What gets drafted

Each card is a bounded experiment (`Proposed`, L0–L2). Promotion/canary/merge are
not reachable from the scan — accessing them raises `CharterViolation`. Drafting
is idempotent (content-hashed ids), so re-running a day produces no duplicates.

## Schedule once per day (Airflow)

The DAG `dags/self_improvement_daily.py` is observer-only and runs daily (or on
an out-of-band trigger). It holds no write/promote/merge/deploy credentials; its
only outputs are `Proposed` cards and one report.

```bash
airflow dags list                                  # confirm it's registered
airflow dags test self_improvement_daily <date>    # one logical-date run
```

On a host without Airflow, run `cc self-improvement-daily` from a daily task
scheduler (e.g. Windows `schtasks`) — same observer/draft-only behavior.

## Human approval turns a card into work

Approve a drafted card at the kanban wall -> it becomes a Ledger mission ->
the mission runs the branch/worktree/devcontainer/PR loop -> `validate` +
`lint-test` must pass -> you review and merge. Nothing self-applies.
