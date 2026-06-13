# Daily self-improvement DAG

An observer-only daily scan that keeps the project improving without giving a
scheduled job authority to change the system. It reads Kanban, Ledger history,
repo/code-health outputs, model/provider feeds, dependency advisories, research
feeds, usage/cost logs, and Airflow/project telemetry. It writes only:

1. Backlog cards in `Proposed` state.
2. One decision-grade report for the daily brief.

It never approves, verifies, promotes, starts canaries, merges, deploys, rotates
secrets, or executes the experiments it drafts. The validated contract lives in
`configs/proactive.yaml` under `self_improvement_scans.daily-self-improvement-brief`.

## Boundary

`llm_station` remains the control plane. It should not become an Airflow data
pipeline. The Airflow DAG belongs in the managed Airflow environment and should
invoke the control-plane commands as a low-privilege service identity.

Required service-account scopes:

- Read: Kanban, Ledger, repo scan artifacts, model/provider scan artifacts,
  dependency reports, Airflow/OpenLineage metrics.
- Write: Backlog cards and one report artifact.
- No access: GitHub merge/write tokens, deploy credentials, secret-manager write,
  promotion endpoints, verifier identity, execution-plane shell access.

## DAG Shape

```text
daily 02:00 or manual touchpoint trigger
  -> scan_sources              dynamic map by source/pillar
  -> classify_and_dedup        normalize, content-hash, open-card dedup, cooldown
  -> score_and_rank            ICE/RICE/WSJF plus value-of-information
  -> draft_proposals           top-N bounded experiment contracts only
  -> emit_report_and_cards     one report + Proposed backlog cards
  -> notify_touchpoints        links only; approval remains in Kanban
```

Use Airflow TaskFlow tasks with retries and exponential backoff. Keep API scans in
pools so arXiv, Semantic Scholar, GitHub, provider feeds, and AppFlowy are not
hammered. Use content hashes because Airflow dataset events indicate producer
success, not that content changed.

The DAG's final task should call the same safe entry points operators use:

```bash
make proactive-validate
make proactive-smoke
python -m command_center.cli.improvement propose --signals generated/self-improvement-signals.json --apply
python -m command_center.cli.improvement board --apply
python -m command_center.cli.improvement attention
```

`--apply` here means "write Proposed experiments/cards and report state." It does
not run, verify, canary, promote, merge, or deploy anything.

## Pillars

| Pillar | Sources | Proposal triggers | Target types |
|---|---|---|---|
| Automation | Airflow metrics, OpenLineage, Kanban cycle time | repeated manual step, SLA miss, recurring RCA | `workflow`, `proactive_check` |
| Structure | CodeScene/Sonar/radon-style outputs, repo history | churn x complexity hotspot, coupling risk | `repository_template`, `skill`, `tool` |
| Updated metrics | LiteLLM usage, model/provider feeds, leaderboards, prices | fit-gated model candidate, price drop, routing regret | `model`, `routing`, `judge` |
| Code quality | ruff, mypy, Semgrep, Bandit, pip-audit, coverage, mutation | quality gate fail, CVE, coverage/mutation weakness | `tool`, `standard`, `repository_template` |
| Rules/standards | standards.yaml, judge calibration, recurring review findings | guardrail gap, false positive/negative cluster | `standard`, `judge`, `documentation` |
| Data handling | schema checks, drift, retrieval quality, artifact freshness | schema break, drift, retrieval miss, stale output | `retrieval`, `memory`, `workflow` |
| Full idea updates | arXiv, Semantic Scholar, Papers with Code, repos | high-VOI relevant paper or repo survives triage | `skill`, `tool`, `workflow` |
| Reliability/observability | incidents, DORA signals, logs, OpenLineage | rising failure/recovery time, weak lineage | `proactive_check`, `workflow`, `standard` |
| Cost/FinOps | LiteLLM spend, provider pricing, compute spend | cost-per-accepted-improvement breach | `routing`, `model`, `workflow` |

## Metrics to track

- Acceptance rate by pillar.
- Idea-to-promotion cycle time.
- DORA-style deployment frequency, change lead time, change failure rate,
  failed deployment recovery time, and rework rate.
- Rollback rate and post-watch regression rate.
- Cost per accepted improvement.
- Human-attention efficiency: decisions per review hour, evidence volume per
  decision, stale card percentage, expired card percentage.
- Independent reproduction coverage.
- Negative-result-memory hit rate.
- Novelty/diversity of proposals.
- Convergence/saturation: marginal value of additional experiments and whether
  the loop should shift from tuning to architecture or net-new ideas.

## Report contract

The daily report is capped. It should show the top ranked items only, each with:

- One-line claim.
- Evidence source and artifact path.
- Pillar and target type.
- Risk tier.
- Confidence band or uncertainty note.
- Expected value / VOI summary.
- What is unknown.
- Link to the Proposed backlog card, when a card was created.

No report item should ask a human to approve from Airflow. The report points to
the Kanban wall.

## Rollout

Phase 1: report only plus dry-run card generation. Advance when the daily report
is useful and stale/expired card rates stay low.

Phase 2: write bounded `Proposed` cards for low-risk model, routing, prompt,
workflow, and proactive-check experiments. Advance when acceptance rate by pillar
stabilizes and cost per accepted improvement is in budget.

Phase 3: add code-quality and data-handling proposals from heavier nightly scans:
Semgrep cross-file, mutation testing, dependency reachability, schema/drift, and
coverage. Advance when independent reproduction coverage does not fall.

Phase 4: add convergence/saturation analytics and DORA dashboarding over the
Ledger. Shift budget away from saturated tuning loops toward architecture or
net-new ideas when marginal value flattens.

Rollback a phase if rollback rate rises, reports flood the human queue, verifier
coverage falls, or cost grows while accepted improvements flatten.

## Manual touchpoints

Kanban, Discord, chat, and MCP may trigger the scan, but they do not become
approval systems. Their allowed action is "start or request the observer scan" and
"show the resulting report/card links." Approval, canary, and promotion stay in
the existing human-gated lifecycle.
