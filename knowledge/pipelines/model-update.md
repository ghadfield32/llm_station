---
okf_version: '0.1'
profile: growth-os-0.1
type: Data Pipeline
title: Model-update pipeline
description: Local model rollout with no auto-promotion.
resource: config://configs/models.yaml
tags:
- pipeline
timestamp: '2026-06-14T03:01:33.913942+00:00'
last_verified_at: '2026-06-14T03:01:33.913942+00:00'
source_system: config
source_path: configs/models.yaml
source_revision: null
source_hash: sha256:438183494d6cad84e842f933fb8c67099f0c6e60c02e054a37462f861a78dce1
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
review_after: '2026-07-14T03:01:33.913942+00:00'
---

<!-- generated:start -->
Local model rollout with no auto-promotion.

- stages: `scout → edit → validate → evals → canary → compare → promote/rollback`
- source: `configs/models.yaml`
<!-- generated:end -->

## Human notes

_Add curated notes here; they are preserved across regenerations._
