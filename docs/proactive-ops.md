# Proactive ops — watching the work that's already done

The request pipeline (`docs/model-routing.md`) handles new work. This lane handles
**work that already shipped and keeps running**: your DAGs, data assets, services,
and the repos themselves. It runs on a schedule, checks health, and on a real problem
opens a gated RCA/debug mission that flows through the *same* lease → checks → judges
→ human-gate → GitHub pipeline as everything else.

It is defined in `configs/proactive.yaml`, validated by `ProactiveConfig` in
`schemas/contracts.py`, and run by `services/proactive_runner`. Edit the YAML,
`make proactive-validate`, done. No code changes to add or retune a check.

## Two lanes

**Runtime health** — are the DAGs/data/services still current and correct?
- DAG run health (failed/retried/delayed/long-running tasks)
- Freshness ("did today's data actually arrive?", outputs current within N hours)
- Data quality (schema, null rate, row counts, distribution drift)
- Service/pipeline perf (latency, error rate, GPU util, cost)

**Repo stewardship** — is the code still built to your standard, or accreting debt?
- Structure / architecture boundaries / frontend + pipeline organization
- Test quality, docs freshness, dead code, dependency drift
- Defensive-coding debt: swallowed exceptions, broad try/except, hidden fallbacks,
  workaround comments, duplicate abstractions — the same things the
  `defensive-coding-judge` blocks at commit time, now swept for *after the fact*

The deterministic tools run first in both lanes (Airflow/Dagster asset checks, Great
Expectations, Evidently/whylogs for drift; ruff/semgrep/pytest for repos). LLMs only
judge what the tools surface — cheaper, and the tools are the source of truth.

## The cardinal safety property: observe, don't refactor

A proactive check's strongest autonomous action is **opening a gated mission**. It
cannot edit, push, merge, or refactor on its own. This isn't a convention — it's
enforced by the contract, which makes the unsafe configs *fail validation*:

```
runtime check proposing L3 external write   → REJECTED
runtime check proposing L4 dangerous        → REJECTED
repo stewardship exceeding L2               → REJECTED
check with no owner / no schedule           → REJECTED
check with neither evidence nor checks      → REJECTED
on_fail: auto_fix (or anything else)        → REJECTED
duplicate check names                       → REJECTED
```

(All eight tested and firing.) So "a wandering refactor agent" and "a scheduled job
that pushes to GitHub" are not things you can accidentally configure.

Each check declares `on_fail`:
- `ledger_report` — record a finding (and, only after your approval, open a GitHub issue).
- `open_rca_mission` — open a normal mission that goes through every gate.

And `auto_patch_max_risk` caps what a resulting patch may even *propose* — L0/L1 for
report-only checks, at most L2 (a leased worktree patch, still fully gated) for the rest.
The control plane's own stewardship check is capped at L1: it can flag and plan, never auto-patch itself.

## Authorization levels (who is allowed to do what)

The proactive lane reuses the same risk tiers as everything else — there's no second
permission system to keep in sync. Mapped to the lane:

| Level | Proactive meaning | Example | Auto? |
|-------|-------------------|---------|-------|
| L0 | read-only observation | scan a DAG's logs, profile a repo | yes |
| L1 | propose a plan | "here's how I'd fix the freshness gap" | yes, after plan critic |
| L2 | leased worktree patch | fix a brittle test, remove dead code | yes *into a branch*, then gated |
| L3 | external write | open the PR / GitHub issue | human approval |
| L4 | dangerous | re-run a prod deploy, rotate a key, delete data | manual only, never from a schedule |

A check at L0 runs unattended. Anything that would touch GitHub or production stops at
a human gate — the proactive runner just queues it in the Ledger for you to approve from
your phone.

## The RCA / debug loop

When a runtime check fails for real (not noise), it opens an RCA mission:

1. Cheap local **log-scanner** classifies symptom vs. root-cause hint, filters noise.
2. On a genuine issue, escalate to the cross-provider **root-cause-debugger** (frontier).
3. It checks lineage (upstream/downstream), data quality/freshness/drift, and recent
   code/config changes to find the *actual cause*, not the symptom.
4. It writes a fix plan; any patch goes through a leased worktree + deterministic checks
   + pre-commit judges + human approval — same pipeline as a normal mission.
5. After a fix, a **post-watch window** monitors the target (1h immediate regressions,
   24h freshness/outputs/cost, 7d drift/recurring warnings) and reports status.

The RCA report is logged to the Ledger so the finding, cause, evidence, and fix are
auditable later.

## Work docs — keeping their work organized

Each lane keeps a running record so it builds on itself instead of re-deriving context:
- **Ledger** holds the durable per-mission/per-check record: findings, RCA reports,
  evidence snapshots, approvals, post-watch outcomes. This is the source of truth.
- **Repo docs** (README/runbook/architecture notes) are updated *only when behavior,
  setup, interfaces, schemas, or runbooks actually changed* — via the `docs` stage in
  the pipeline, with the `docs-truth` and `docs-minimality` judges preventing churn.
  No generic documentation drift.

So "continuously updated work docs" = the Ledger as the live operational log, plus
gated, minimal updates to the repo's own docs when something real changed.

## Where the judges come from

The lane's judges are defined in `configs/judges.yaml` under two stages:
- `proactive-runtime`: `freshness-judge`, `log-scanner`, `data-contract-judge`
  (all local-first, escalating to planner/security-judge on a real signal)
- `proactive-steward`: `defensive-coding-judge`, `scope-judge`

Cheap-first holds here as everywhere: local models scan continuously at ~$0; only a
genuine finding escalates to the local planner/debugger aliases and then into the gated mission flow.

## Running it

```bash
make proactive-validate     # contract-check configs/proactive.yaml
make proactive-smoke        # list every check, its schedule, on_fail, and risk cap
```

The runner is a thin scheduler invoked by host cron / systemd timer:
`docker compose run --rm proactive-runner`. It shares the Ledger and Judge Gate, holds
no secrets, and mounts `proactive.yaml` read-only. Wire the real evidence collectors
(Airflow/Dagster API, asset checks, ruff/semgrep over each repo) per target at install —
the runner is the control flow they plug into.
