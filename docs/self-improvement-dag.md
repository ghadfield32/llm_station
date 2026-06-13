# The daily self-improvement DAG

A scheduled, **observer-only** loop that runs the improvement system *on itself*: every day (and
on demand from any touchpoint) it scans many sources across nine pillars, ranks what it finds,
and drafts **bounded `Proposed` experiment cards** plus **one decision-grade report**. It writes
nothing else. Promotion, canary, and merge stay human-only — the wall is structural, not a
convention.

> TL;DR: `make improvement-scan` (dry-run) → preview the report. `make improvement-scan APPLY=1`
> → draft the Backlog cards + write the report. The Airflow DAG `self_improvement_daily` does the
> same on a 06:00 UTC schedule and can be triggered out-of-band from Kanban/Discord/CLI.

---

## 1. Why it exists

The control plane already *reacts* (the proactive lane drafts experiments from observed failures).
This closes the other half: a standing, **proactive sweep** that looks outward (new papers, new
models/providers, dependency advisories) and inward (code health, data/retrieval quality, the
Ledger's own reliability) so the system stays at the frontier and keeps paying down its own debt —
without ever granting an automated process the right to ship.

## 2. The three walls (unchanged)

1. **Human-only promotion / canary.** Drafted cards land in `Proposed`. Only a human moves anything
   to Canary/Promoted (`HUMAN_ONLY_STATES`). The scan has no path to those states.
2. **Independent verifier that can only reject.** Untouched. The scan never verifies or promotes.
3. **No self-promotion.** The Ledger is append-only; the scan's only writes are `Proposed` cards +
   a report, both through the `ObserverCharter`, which exposes *no* promote/merge/deploy/set_status
   method. A bug or a compromise still cannot escalate — the capability isn't reachable.

## 3. The nine pillars

| Pillar | What it watches | Default target type | Representative sources |
|--------|-----------------|---------------------|------------------------|
| automation | toil, schedule gaps, stale Kanban | workflow | airflow_metrics, kanban_cycle_time |
| structure | architecture hotspots, coupling, oversized modules | repository_template | codescene, radon, code_health |
| updated_metrics | better models/providers/pricing/benchmarks | routing | litellm_registry, chatbot_arena, openrouter |
| code_quality | lint, complexity, dead code, vulns, debt | repository_template | ruff, mypy, semgrep, pip_audit, code_health |
| rules_standards | coding standards, guardrails, policy | standard | semgrep_custom, standards_yaml |
| data_handling | schemas, retrieval quality, drift | retrieval | great_expectations, evidently, ledger_runs |
| full_idea | net-new capabilities from research | skill | arxiv, semantic_scholar, papers_with_code |
| reliability_observability | error/latency/DORA, incident clusters | proactive_check | prometheus, openlineage, ledger |
| cost_finops | token spend, cost-per-improvement | routing | litellm_spend, provider_billing, ledger |

Every pillar resolves to a real `TargetType`, so a drafted card enters the existing experiment
lifecycle correctly. (See [src/command_center/improvement/discovery/pillars.py](../src/command_center/improvement/discovery/pillars.py).)

## 4. The pipeline (five stages)

```
scan_*  →  classify_and_dedup  →  score_and_rank  →  draft_proposals  →  emit_report_and_cards
(mapped)     (triage)              (ICE/RICE/WSJF/VOI)  (Proposed cards)    (one report)
```

- **scan_** — one task per source (Airflow dynamic task mapping). A source's live fetch runs inside
  an isolate guard, so a dead feed becomes a **visible "failed source" line** in the report (and an
  Airflow log), never a silent gap or a swallowed exception.
- **classify_and_dedup** — drop noise (low confidence), dedup against open cards, honor cooldowns,
  and **suppress anything the negative-result memory already recorded as human-rejected** (so the
  loop never re-proposes its own dead ends — and the suppression is counted and reported).
- **score_and_rank** — ICE for triage, RICE for features, **WSJF to rescue security/CVE/debt work**
  that pure value scoring buries, VOI to ask "is this experiment worth the budget?".
- **draft_proposals** — render each top finding as a bounded, secret-free, L2-capped `Proposed`
  experiment with a required primary metric + a regression-capped safety metric.
- **emit_report_and_cards** — write the cards + one Markdown report. The card cap never silently
  drops surplus; it is reported as "held by card cap" and resurfaces next run.

## 5. Ranking, briefly

| Method | Formula | Use |
|--------|---------|-----|
| ICE | Impact × Confidence × Ease | fast first-pass triage |
| RICE | Reach × Impact × Confidence ÷ Effort | feature-scale (full_idea) items |
| WSJF | (Impact + Time-criticality + Risk-reduction) ÷ Effort | portfolio sequencing; lifts CVEs/debt |
| VOI | (Value × P(changes decision)) ÷ Cost | which experiment buys the most certainty |

Confidence is reported as a **band**, never a single number, and the band tightens with corroborating
sources.

## 6. Self-improvement metrics (is the loop actually improving?)

[src/command_center/improvement/selfmetrics.py](../src/command_center/improvement/selfmetrics.py) reads the Ledger and computes, pure-stdlib and deterministically:

- **DORA** — deployment frequency, lead time for changes, change-failure rate, MTTR (a PROMOTED
  event is a deploy; a later ROLLED_BACK is a failure). Missing data is honest `None`, never a fake 0.
- **Acceptance rate by pillar / rollback rate / cost-per-accepted-improvement** — is it proposing
  things humans accept, and at what unit cost?
- **Negative-result-memory hit rate** — how often it correctly *declined* to re-propose a dead end.
- **Convergence power-law fit** AP*(N) ≈ a − b·N^(−c) — are returns diminishing, and toward what
  ceiling `a`? (Fit with no SciPy: for fixed `c` the model is linear in (a, b); grid-search `c`.)
- **BWT / FWT** (Gradient Episodic Memory) — does improving a new capability help or hurt the ones
  we already had / haven't trained yet?

## 7. Touchpoints — "set it loose" from anywhere

The heavy logic is one pure pipeline, so every entry point is a thin caller:

- **CLI:** `python -m command_center.cli.improvement scan [--apply] [--feeds feeds.json] [--show-report]`
  (dry-run by default). `make improvement-scan` / `.\scripts\cc.ps1 improvement-scan`.
- **Airflow:** the `self_improvement_daily` DAG (daily cron). Update the `scan-request` Asset/Dataset
  to fire an out-of-band run — that's the hook a Kanban automation or a Discord bot triggers.
- **Feeds:** network sources read pre-ingested records (an upstream ingestion DAG / a `--feeds` JSON
  file). The offline sources (`code_health`, `ledger`) always run with zero configuration.

## 8. Idempotency & safety properties (all tested)

- Experiment ids are content hashes of the finding; drafting is dedup-guarded; the run is keyed to
  its logical date → **re-running a day produces no duplicate cards**.
- `max_active_runs=1`, `catchup=False` → no overlapping scans, no backfill storms.
- A dry run performs **zero** registry writes and writes no file; it still renders the full report.
- The DAG imports **no** promotion/merge/deploy capability (asserted by an AST test).

## 9. File map

| Concern | Module |
|---------|--------|
| pillars → target types + sources | `discovery/pillars.py` |
| the Finding model + → `Proposed` experiment | `discovery/findings.py` |
| ICE/RICE/WSJF/VOI + confidence band | `discovery/ranking.py` |
| observer-only structural wall | `discovery/charter.py` |
| scanners (offline code-health + injected feeds) | `discovery/sources.py` |
| dedup / negative-memory / cooldown | `discovery/triage.py` |
| decision-grade report | `discovery/report.py` |
| scan→classify→rank→draft→emit | `discovery/pipeline.py` |
| Airflow-free DAG glue + serialization | `discovery/dag_support.py` |
| DORA / acceptance / convergence / transfer | `selfmetrics.py` |
| the Airflow DAG | `dags/self_improvement_daily.py` |
| the CLI touchpoint | `cli/improvement.py` (`scan`) |

Tests: `tests/test_discovery_foundations.py`, `test_discovery_sources.py`, `test_discovery_pipeline.py`,
`test_selfmetrics.py`, `test_dag_support.py`, `test_self_improvement_dag.py`, `test_cli_scan.py`.

See also: [docs/improvement-roadmap-phases.md](improvement-roadmap-phases.md) for the measurement-science
phases (mSPRT/CUPED, judge/jury, anti-Goodhart, bandits, drift/canary, AI-control) this builds on.
