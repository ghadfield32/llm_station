---
okf_version: '0.1'
profile: growth-os-0.1
type: Metric
title: Self-improvement metrics
description: DORA + acceptance + convergence + transfer over the experiment loop.
resource: repo://llm_station/src/command_center/improvement/selfmetrics.py
tags:
- metrics
- dora
- self-improvement
timestamp: '2026-06-13T19:43:05.390123+00:00'
last_verified_at: '2026-06-13T19:43:05.390123+00:00'
source_system: repository
source_path: src/command_center/improvement/selfmetrics.py
source_revision: null
source_hash: sha256:aae67cd729baf4858fbfe27a66460d0919a8e037acd8f5107aba58b3b22af371
authority: derived
owner: command-center
status: current
sensitivity: internal
confidence: high
generated_by: growthos-okf-producer
generator_version: 0.1.0
mission_id: null
experiment_id: null
supersedes: null
review_after: '2026-07-13T19:43:05.390123+00:00'
---

<!-- generated:start -->
Self-improvement metrics computed from the Ledger (pure-stdlib, deterministic):

- DORA: deploy frequency, lead time, change-failure rate, MTTR
- acceptance rate by pillar · rollback rate · cost-per-accepted
- negative-result-memory hit rate
- convergence power-law fit AP*(N) ≈ a − b·N^(−c)
- BWT / FWT (forward/backward transfer)
<!-- generated:end -->

## Human notes

_Add curated notes here; they are preserved across regenerations._
