---
okf_version: '0.1'
profile: growth-os-0.1
type: System
title: Model roles
description: Role → ranked local Ollama model candidates (no provider keys).
resource: config://configs/models.yaml
tags:
- models
- ollama
- routing
timestamp: '2026-06-14T03:03:21.476749+00:00'
last_verified_at: '2026-06-14T03:03:21.476749+00:00'
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
review_after: '2026-07-14T03:03:21.476749+00:00'
---

<!-- generated:start -->
Local-only model roles (every role must be `provider: ollama, local: true`).

- **triage** → `qwen3-coder:30b`
- **chat** → `qwen3:30b`
- **local-judge** → `qwen3:30b, devstral:24b`
- **planner** → `qwen3:30b, devstral:24b`
- **coder** → `qwen3-coder:30b`
- **architect-judge** → `qwen3-coder:30b, qwen3:30b`
- **security-judge** → `qwen3:30b, devstral:24b`
<!-- generated:end -->

## Human notes

_Add curated notes here; they are preserved across regenerations._
