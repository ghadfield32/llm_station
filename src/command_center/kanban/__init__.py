"""Agent kanban surface — observability + data-derived tuning (Phase 3).

The agent-call log (growthos.observability -> _export/agent_calls.jsonl) is the
event spine: every tool call on every surface is already recorded there, so this
package READS that single source rather than emitting a parallel event store.

  metrics.py   real metrics from the spine (redundant-call rate, verb adoption, …)
  features.py  pre-decision feature names + leakage guard (the no-leakage contract)
  tuning.py    data-derived knob recommendation; abstains below the decision floor
  digest.py    `make kanban-digest` — Markdown report from real data
  validate.py  `make kanban-surface-validate` — blocking N/N PASS gate
"""
