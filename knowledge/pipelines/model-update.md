---
okf_version: '0.1'
profile: growth-os-0.1
type: Data Pipeline
title: Model-update pipeline
description: Local model rollout with no auto-promotion.
resource: config://configs/models.yaml
tags:
- pipeline
timestamp: '2026-06-13T19:43:05.390123+00:00'
last_verified_at: '2026-06-13T19:43:05.390123+00:00'
source_system: config
source_path: configs/models.yaml
source_revision: null
source_hash: sha256:b31ab6206c69b7355540af6abb08cc1fcdae4b8ba14c0dcc05697fa58487d863
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
Local model rollout with no auto-promotion.

- stages: `scout → edit → validate → evals → canary → compare → promote/rollback`
- source: `configs/models.yaml`
<!-- generated:end -->

## Human notes

_Add curated notes here; they are preserved across regenerations._
