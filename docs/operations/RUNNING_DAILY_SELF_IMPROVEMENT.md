# Running the daily self-improvement loop

The control plane improves **itself** once a day: it scans sources, ranks
findings, and drafts `Proposed` experiments plus top-ranked Backlog cards on the
first-party **Self Improvement** Kanban. It is **observer/draft-only** —
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

The Kanban source enumerates `configs/kanban_boards.yaml` on every run, so newly
registered boards are included without maintaining a second Airflow Variable.
Completed/rejected history is ignored, and the Self Improvement output board is
excluded to prevent recursive findings. Other source adapters cover code health,
ledger, research, dependencies, models/providers, and leaderboards. Evidence is written to
`evaluation/system-validation/20260616-autonomy-contracts/self-improvement-daily.json`.

Repository coverage is also registry-driven. On every scheduled run the DAG
validates `configs/autonomy.yaml` and expands one isolated code-health scanner per
`repo_manifests` entry. Adding a manifest therefore adds both a scan task and a
repository tab in the cockpit without editing a second list. `local_path_ref: self`
uses `SELF_IMPROVEMENT_REPO_ROOT`; `local_path_ref: env:NAME` uses that environment
variable. An unset path is retained as a visibly failed source in the report—it is
never treated as an empty or successfully scanned repository.

The Self Improvement board shows an **All repositories** tab plus one tab per
validated manifest, the manifest's declared capabilities and reason for checking
it, live card counts, status KPIs, average score, and a dropdown containing search,
status, pillar, risk, source, and minimum-score filters. Cards retain `repo_ids` and
`repository_reason`, so a finding can be traced to its repository scope; cross-system
findings remain visible under All repositories.

## What gets drafted

Each card is a bounded experiment (`Proposed`, L0–L2). Promotion/canary/merge are
not reachable from the scan — accessing them raises `CharterViolation`. Drafting
is idempotent (content-hashed ids), so re-running a day produces no duplicates.

## Schedule once per day (Airflow)

The DAG `dags/self_improvement_daily.py` is observer-only and runs daily (or on
an out-of-band trigger). It holds no write/promote/merge/deploy credentials; its
only outputs are `Proposed` registry entries, Backlog cards on Self Improvement,
and one report.

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
