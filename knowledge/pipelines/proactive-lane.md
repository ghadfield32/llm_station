---
okf_version: '0.1'
profile: growth-os-0.1
type: Data Pipeline
title: Proactive ops lane
description: Scheduled checks on already-shipped work → RCA missions (human-gated).
resource: config://configs/proactive.yaml
tags:
- pipeline
timestamp: '2026-06-13T19:43:05.390123+00:00'
last_verified_at: '2026-06-13T19:43:05.390123+00:00'
source_system: config
source_path: configs/proactive.yaml
source_revision: null
source_hash: sha256:2fb9df3c221d4682ef0633826f5435e0d3c63f1bc51591c8e372cb943ba88471
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
Scheduled checks on already-shipped work → RCA missions (human-gated).

- stages: `scheduled trigger → evidence → classify → RCA mission → post-watch`
- source: `configs/proactive.yaml`
<!-- generated:end -->

## Human notes

_Add curated notes here; they are preserved across regenerations._
