---
okf_version: '0.1'
profile: growth-os-0.1
type: Runbook
title: Operator interface
description: 73 make targets — the operator entry points.
resource: repo://llm_station/Makefile
tags:
- operator
- make
- cli
timestamp: '2026-06-14T03:44:07.529660+00:00'
last_verified_at: '2026-06-14T03:44:07.529660+00:00'
source_system: repository
source_path: Makefile
source_revision: null
source_hash: sha256:e47d1f9d15852425f0f824031c7566b482c9bab0800f383bdbae156646ad2a4d
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
review_after: '2026-07-14T03:44:07.529660+00:00'
---

<!-- generated:start -->
Operator commands (`make <target>`; Windows: `.\scripts\cc.ps1 <target>`).

- `make help` — List targets
- `make validate` — Validate all configs/*.yaml against Pydantic contracts + cross-file refs
- `make schema` — Generate JSON Schema from contracts -> generated/json-schema
- `make render` — Validate + render generated/litellm-config.yaml from configs
- `make impact` — Blast radius of your git diff (or: make impact FILES="a b")
- `make mission-dryrun` — Run fake L0..L4 missions through gates+judges (no model calls)
- `make env-smoke` — Validate environments + isolation invariants
- `make proactive-validate` — Validate configs/proactive.yaml against its contract
- `make proactive-smoke` — Dry-run proactive lanes: list schedules, actions, write/risk caps (no calls)
- `make targets-validate` — Validate configs/targets.yaml (the watch inventory)
- `make kanban-validate` — Validate the first-party kanban intake contract
- `uv run cc kanban-verify --all` — Verify every registered first-party board.
- `uv run cc kanban-project` — Project governed events into local board state.
- `make tools-validate` — Validate configs/tools.yaml (tool permission registry)
- `make evals` — Run the routing/judge regression suite against gates (no model calls)
- `make cross-refs` — Check proactive targets exist in targets.yaml (cross-file lint)
- `make ui-validate` — Validate configs/ui.yaml (human UI surface, WebUI safety)
- `make standards-validate` — Validate configs/standards.yaml (executor + judge standing standards)
- `make forbidden-providers` — Assert LiteLLM is local-only and provider API keys are absent
- `make setup` — Check deps, create isolated .venv (uv), create .env, validate+render, build images
- `make doctor` — Preflight: docker daemon, uv, ollama, service ports, .env, provider boundary, digest
- `make first-boot` — One-shot first boot: doctor -> setup -> bootstrap -> keys (auto-writes .env) -> up -> health
- `make verify-base` — Verify digest + base secrets before first boot keys exist
- `make verify` — Verify pinned digest + all runtime keys before full stack up
- `make up` — Verify + render config then start the control plane
- `make bootstrap` — FIRST BOOT ONLY: bring up litellm+db+ledger so you can mint keys
- `make down` — Stop
- `make keys` — Mint budgeted LiteLLM virtual keys and write them straight into .env (no copy-paste)
- `make health` — Check every service health endpoint
- `make models` — Validate+render, pull local tags, restart litellm
- `make models-light` — Switch to the small-GPU/CPU profile (qwen3:8b), pull it, re-render
- `make models-canary` — Route ~10% of a role to a local challenger. ROLE= MODEL=ollama_chat/tag
- `make models-promote` — Promote canary to primary for ROLE=
- `make models-rollback` — Revert canary for ROLE=
- `make model-scout` — Propose model candidates from configured sources. Never edits configs.
- `make model-fit` — Which installed Ollama models fit the GPU budget. CTX= MODEL= ENV= VRAM=
- `make usage-digest` — Write generated/usage-digest.md from LiteLLM + Ledger usage APIs
- `make usage-report` — Alias for usage-digest
- `make kanban-digest` — Write generated/kanban-digest.md — agent-surface metrics + tuning verdict (real data)
- `make kanban-surface-validate` — Blocking N/N gate for the agent kanban surface (config/leakage/verbs/tuning)
- `make kanban-board-snapshot` — Write generated/board-snapshot.json for the UI (run on the worker; uses the local Growth OS board store)
- `make live-smoke` — Print real local model replies through Ollama/LiteLLM. TRIAGE=triage PLANNER=planner JUDGE=local-judge
- `make repo-install` — Install hooks + devcontainer + standards into a repo. REPO=/path [PROFILE=python_ml_pipeline]
- `make backup` — restic snapshot (see docs/setup/SETUP-FROM-SCRATCH.md, Backups)
- `make restore-drill` — Restore latest backup to temp + diff (schedule monthly)
- `make logs` — Tail all logs
- `make channels-validate` — Validate configs/channels.yaml (chat transport registry)
- `make gateway` — Run enabled chat channels from configs/channels.yaml. Installs the gateways extra first.
- `make notify` — Push a proactive digest (brief + active missions) to Discord. ARGS=--dry-run to preview.
- `make lint` — ruff + mypy over src/ (install the dev extra first: uv pip install -e ".[dev]")
- `make test` — Run the test suite (install the dev extra first: uv pip install -e ".[dev]")
- `make improvement-validate` — Validate configs/improvement.yaml experiment definitions
- `make improvement-list` — List registered experiments (STATUS= to filter)
- `make improvement-register` — Register an experiment ID=EXP-... (dry-run; APPLY=1 to commit). MISSION= optional
- `make improvement-baseline` — Capture the baseline for ID=EXP-... (dry-run; APPLY=1 to run)
- `make improvement-run` — Run the candidate for ID=EXP-... (dry-run; APPLY=1 to run)
- `make improvement-verify` — Independently verify ID=EXP-... (dry-run; APPLY=1 to run). VERIFIER= optional
- `make improvement-report` — Full audit report for ID=EXP-...
- `make improvement-request-promotion` — Move a Verified experiment to Awaiting Human Promotion. ID=EXP-... APPLY=1
- `make improvement-canary` — HUMAN: start a canary. ID=EXP-... APPROVER=you APPLY=1
- `make improvement-promote` — HUMAN: promote after a clean canary. ID=EXP-... APPROVER=you APPLY=1
- `make improvement-rollback` — Roll back ID=EXP-... (APPLY=1). REASON= optional
- `make improvement-post-watch` — Record a post-watch checkpoint. ID=EXP-... CHECKPOINT=1h [REGRESSION=1] APPLY=1
- `make improvement-board` — Project the registry onto the improvements board (dry-run; APPLY=1 to write)
- `make improvement-propose` — Run controlled proposal generation from evidence (dry-run; APPLY=1 to draft)
- `make improvement-scan` — Observer-only self-improvement scan -> Proposed cards + report (dry-run; APPLY=1). FEEDS=path SHOW=1
- `make improvement-scan-validate` — Blocking validation gate for the discovery scan (N/N PASS)
- `make knowledge-generate` — Generate the observer-only OKF knowledge/ bundle from authoritative sources
- `make knowledge-validate` — Blocking validation gate for the knowledge/ bundle (N/N PASS)
- `make judge-calibration` — Score the judge against the calibration set (TP/FP/FN/precision/recall)
- `make attention-digest` — Print the human-attention morning brief + queue metrics
<!-- generated:end -->

## Human notes

_Add curated notes here; they are preserved across regenerations._
