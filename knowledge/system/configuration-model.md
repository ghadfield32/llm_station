---
okf_version: '0.1'
profile: growth-os-0.1
type: System
title: Configuration model
description: 'The one rule: YAML configs are the editable source of truth; strict
  contracts reject unsafe states at validation time.'
resource: repo://llm_station/configs
tags:
- contracts
- configs
- pydantic
timestamp: '2026-06-13T19:43:05.390123+00:00'
last_verified_at: '2026-06-13T19:43:05.390123+00:00'
source_system: config
source_path: configs/
source_revision: null
source_hash: null
authority: derived
owner: command-center
status: current
sensitivity: internal
confidence: verified
generated_by: growthos-okf-producer
generator_version: 0.1.0
mission_id: null
experiment_id: null
supersedes: null
review_after: '2026-07-13T19:43:05.390123+00:00'
---

<!-- generated:start -->
The contract model: edit `configs/*.yaml` → Pydantic contracts validate them →
`generated/` is rendered (disposable) → `ledger.db` holds the only runtime state.

Config files under contract:

- `configs/breakage.yaml`
- `configs/channels.yaml`
- `configs/discovery.yaml`
- `configs/environments.yaml`
- `configs/evals.yaml`
- `configs/gates.yaml`
- `configs/improvement-targets.yaml`
- `configs/improvement.yaml`
- `configs/judges.yaml`
- `configs/kanban.yaml`
- `configs/models.light.yaml`
- `configs/models.yaml`
- `configs/proactive.yaml`
- `configs/standards.yaml`
- `configs/targets.yaml`
- `configs/tools.yaml`
- `configs/ui.yaml`
<!-- generated:end -->

## Human notes

_Add curated notes here; they are preserved across regenerations._
