---
okf_version: '0.1'
profile: growth-os-0.1
type: Data Pipeline
title: Kanban bridge (cards → missions)
description: 'The dispatch contract: sections, risk ceilings, ready statuses.'
resource: config://configs/kanban.yaml
tags:
- kanban
- agents
- dispatch
- appflowy
timestamp: '2026-06-13T20:08:23.902021+00:00'
last_verified_at: '2026-06-13T20:08:23.902021+00:00'
source_system: config
source_path: configs/kanban.yaml
source_revision: null
source_hash: sha256:81654e48985f86e3bb18c0551e0f63676ea40d7fdfbff38b37a0bca2221c7bfc
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
review_after: '2026-07-13T20:08:23.902021+00:00'
---

<!-- generated:start -->
The Kanban bridge — Approved cards become Ledger missions. Agents may DRAFT cards;
only a human drag to Approved dispatches one. Dispatch sections + risk ceilings:

| Section | Target kind | Max auto risk | Ready statuses |
|---|---|---|---|
| dags | dag | L2_local_edits | Approved |
| learning | learning | L1_plan_only | Approved |
| betts-basketball | repo | L2_local_edits | Approved |
| command-center | repo | L2_local_edits | Approved |
<!-- generated:end -->

## Human notes

_Add curated notes here; they are preserved across regenerations._
