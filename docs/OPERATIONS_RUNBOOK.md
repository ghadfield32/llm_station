# Operations runbook

Day-to-day operation of a running deployment.

## Daily loop

```bash
uv run cc doctor                 # green/red preflight (run any time)
uv run cc up                     # steady-state control plane (after first cc start)
uv run cc health                 # service health endpoints
uv run cc usage-digest           # LiteLLM spend + Ledger mission summary
uv run cc self-improvement-daily --draft-kanban true --apply false
```

## The work loop (per mission)

1. A card is drafted (by a human, the gateway, or the daily scan) on a board.
2. **Human approves** the card (drag to Approved).
3. `cc kanban-bridge --apply` turns approved cards into Ledger missions.
4. The mission runs one branch -> worktree -> devcontainer -> PR (L0–L2 only).
5. CI (`validate` + `lint-test`) must pass.
6. **Human approves + merges** the PR (CODEOWNERS). The agent never merges.

## Verifying readiness

```bash
uv run cc kanban-verify --board-id <board>
uv run cc repo-verify   --repo-id  <repo>
uv run cc demo full-loop --repo <repo> --board <board>   # documents all 14 steps
uv run cc system-validation --run-id 20260616-autonomy-contracts
```

## Memory hygiene

```bash
uv run cc memory-review          # approved / pending / stale, with provenance
uv run cc memory-prune --apply   # drop stale records per each record's retention_policy
uv run cc memory-verify          # integrity: provenance present, confidential redacted
```

## Emergency stop

- **Stop the stack:** `uv run cc down` (or `docker compose down`).
- **Stop a channel:** Ctrl-C the gateway process / `docker compose stop <svc>`.
- **Freeze repo autonomy:** set `autonomous_edits_enabled: false` on the repo
  manifest in `configs/autonomy.yaml` and `cc validate`. Disabled manifests must
  list blockers; the agent can no longer run missions on it.
- **Freeze the daily DAG:** pause `self_improvement_daily` in Airflow (it's
  observer-only, but pausing stops new drafts).
- **Revoke remote write:** uninstall / suspend the GitHub App, or let the
  short-lived installation token expire. Nothing on `main` can change without a
  human merge regardless.

## Backups / state

The Ledger SQLite is the runtime state of record. Cross-conversation memory lives
in `generated/memory/` (gitignored, per-deployment). Evidence packages are under
`evaluation/system-validation/`.

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for known gotchas.
