# Command Center — the whole interface. `make help`.
# YAML configs are the source of truth; Pydantic validates them; generated/ is
# disposable; the ledger holds runtime state. Nothing here is clever.

SHELL := /bin/bash
COMPOSE := docker compose
LITELLM_URL := http://localhost:4000
OLLAMA_HOST ?= http://localhost:11434
LEDGER_HOST_PORT ?= 8091
LITELLM_DIGEST ?= ghcr.io/berriai/litellm@sha256:7c311546c25e7bb6e8cafede9fcd3d0d622ac636b5c9418befaa32e85dfb0186

.PHONY: help setup verify verify-base validate schema render up bootstrap down keys health \
        models models-canary models-promote models-rollback \
        model-scout model-fit proactive-validate proactive-smoke targets-validate kanban-validate tools-validate capabilities-digests capabilities-verify evals cross-refs ui-validate \
        standards-validate forbidden-providers usage-digest usage-report live-smoke impact mission-dryrun env-smoke repo-install backup restore-drill logs \
        gateway channels-validate lint test doctor first-boot models-light \
        improvement-validate improvement-list improvement-register improvement-baseline \
        improvement-run improvement-verify improvement-report improvement-request-promotion \
        improvement-canary improvement-promote improvement-rollback improvement-post-watch \
        improvement-board improvement-propose improvement-scan improvement-scan-validate \
        knowledge-generate knowledge-validate judge-calibration attention-digest \
        kanban-digest kanban-surface-validate kanban-board-snapshot life-center-sync

help:  ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n",$$1,$$2}'

validate:  ## Validate configs, cross-file refs, render, and the configured provider posture
	@$(PY) -m command_center.cli.validate_config
	@$(PY) -m command_center.cli.check_cross_refs
	@$(PY) -m command_center.registry.render
	@$(PY) -m command_center.cli.check_forbidden_providers --configured-posture

schema:  ## Generate JSON Schema from contracts -> generated/json-schema
	@$(PY) -m command_center.cli.render_json_schema

render:  ## Validate + render generated/litellm-config.yaml from configs
	@$(PY) -m command_center.cli.validate_config
	@$(PY) -m command_center.registry.render
	@$(PY) -m command_center.cli.check_forbidden_providers --configured-posture

impact:  ## Blast radius of your git diff (or: make impact FILES="a b")
	@$(PY) -m command_center.cli.impact $(FILES)

mission-dryrun:  ## Run fake L0..L4 missions through gates+judges (no model calls)
	@for t in L0 L1 L2 L3 L4; do $(PY) -m command_center.cli.smoke_mission $$t demo "smoke"; echo; done

env-smoke:  ## Validate environments + isolation invariants
	@$(PY) -c "import yaml; from command_center.schemas import EnvironmentsConfig; EnvironmentsConfig.model_validate(yaml.safe_load(open('configs/environments.yaml'))); print('env-smoke: PASS')"

proactive-validate:  ## Validate configs/proactive.yaml against its contract
	@$(PY) -c "import yaml; from command_center.schemas import ProactiveConfig; ProactiveConfig.model_validate(yaml.safe_load(open('configs/proactive.yaml'))); print('proactive-validate: PASS')"

proactive-smoke:  ## Dry-run proactive lanes: list schedules, actions, write/risk caps (no calls)
	@$(PY) -c "import yaml; from command_center.schemas import ProactiveConfig; c=ProactiveConfig.model_validate(yaml.safe_load(open('configs/proactive.yaml'))); [print(f'  {x.name:34s} {x.schedule:14s} on_fail={x.on_fail:18s} max={x.auto_patch_max_risk.value}') for x in c.runtime_checks+c.repo_stewardship]; [print(f'  {x.name:34s} {x.schedule:14s} self_improvement writes={\"+\".join(x.write_scopes):29s} max_generated={x.max_generated_experiment_risk.value}') for x in c.self_improvement_scans]; print('proactive-smoke: PASS')"

targets-validate:  ## Validate configs/targets.yaml (the watch inventory)
	@$(PY) -c "import yaml; from command_center.schemas import TargetsConfig; TargetsConfig.model_validate(yaml.safe_load(open('configs/targets.yaml'))); print('targets-validate: PASS')"

kanban-validate:  ## Validate configs/kanban.yaml (first-party governed intake)
	@$(PY) -c "import yaml; from command_center.schemas import KanbanConfig; KanbanConfig.model_validate(yaml.safe_load(open('configs/kanban.yaml'))); print('kanban-validate: PASS')"

tools-validate:  ## Validate configs/tools.yaml (tool permission registry)
	@$(PY) -c "import yaml; from command_center.schemas import ToolsConfig; ToolsConfig.model_validate(yaml.safe_load(open('configs/tools.yaml'))); print('tools-validate: PASS')"

capabilities-digests:  ## Print recomputed digests for capability provenance (paste into configs/capabilities.yaml)
	@$(PY) -m command_center.cli.capability_digest

capabilities-verify:  ## Recompute capability provenance digests and fail on drift
	@$(PY) -m command_center.cli.capability_digest --check

evals:  ## Run the routing/judge regression suite against gates (no model calls)
	@$(PY) -m command_center.cli.run_evals

cross-refs:  ## Check proactive targets exist in targets.yaml (cross-file lint)
	@$(PY) -m command_center.cli.check_cross_refs

ui-validate:  ## Validate configs/ui.yaml (human UI surface, WebUI safety)
	@$(PY) -c "import yaml; from command_center.schemas import UIConfig; UIConfig.model_validate(yaml.safe_load(open('configs/ui.yaml'))); print('ui-validate: PASS')"

standards-validate:  ## Validate configs/standards.yaml (executor + judge standing standards)
	@$(PY) -c "import yaml; from command_center.schemas import StandardsConfig; StandardsConfig.model_validate(yaml.safe_load(open('configs/standards.yaml'))); print('standards-validate: PASS')"

forbidden-providers:  ## Assert LiteLLM is local-only and provider API keys are absent
	@$(PY) -m command_center.cli.check_forbidden_providers

# Host tooling runs in an isolated .venv (created by `make setup`, uv-preferred).
# Services run in Docker. Nothing installs into system Python.
UV := $(shell command -v uv 2>/dev/null)
PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

setup:  ## Check deps, create isolated .venv (uv), create .env, validate+render, build images
	@command -v docker >/dev/null || { echo "install docker"; exit 1; }
	@if [ -n "$(UV)" ]; then \
	  test -d .venv || uv venv .venv; \
	  uv pip install -e . --python .venv/bin/python --quiet; \
	else \
	  echo "uv not found — falling back to python3 -m venv (install uv for faster, locked installs)"; \
	  test -d .venv || python3 -m venv .venv; \
	  .venv/bin/pip install --quiet -e .; \
	fi
	@test -f .env || { $(PY) -m command_center.cli.init_env; echo "created .env — set OLLAMA_API_BASE (local default host.docker.internal is fine), then re-run 'make setup'"; exit 1; }
	@$(MAKE) render
	@$(COMPOSE) build ledger judge-gate proactive-runner
	@echo "setup OK — next: 'make first-boot' (one shot), or bootstrap -> keys -> up"

doctor:  ## Preflight: docker daemon, uv, ollama, service ports, .env, provider boundary, digest
	@$(PY) -m command_center.cli.doctor

first-boot:  ## One-shot first boot: doctor -> setup -> bootstrap -> keys (auto-writes .env) -> up -> health
	@$(MAKE) doctor
	@$(MAKE) setup
	@$(MAKE) bootstrap
	@$(MAKE) keys
	@$(MAKE) up
	@$(MAKE) health

verify-base:  ## Verify digest + base secrets before first boot keys exist
	@$(PY) -m command_center.cli.verify_env --mode base

verify:  ## Verify pinned digest + all runtime keys before full stack up
	@$(PY) -m command_center.cli.verify_env --mode full

up:  ## Verify + render config then start the control plane
	@$(MAKE) verify
	@$(MAKE) render
	@$(COMPOSE) up -d
	@echo "up — run 'make keys' if first boot, then 'make health'"

bootstrap:  ## FIRST BOOT ONLY: bring up litellm+db+ledger so you can mint keys
	@$(MAKE) verify-base
	@$(MAKE) render
	@$(COMPOSE) up -d litellm-db litellm ledger
	@echo "waiting for litellm to be healthy..."
	@for i in $$(seq 1 20); do \
	  curl -fsS $(LITELLM_URL)/health/liveliness >/dev/null 2>&1 && { echo "litellm healthy"; break; }; \
	  sleep 3; done
	@echo ""
	@echo "next: run 'make keys', paste the two keys into .env, then 'make up'"

down:  ## Stop
	@$(COMPOSE) down

keys:  ## Mint budgeted LiteLLM virtual keys and write them straight into .env (no copy-paste)
	@$(MAKE) verify-base
	@$(PY) -m command_center.cli.mint_keys

health:  ## Check every service health endpoint
	@for s in "litellm:4000/health/liveliness" "judge-gate:8088/health" "ledger:$(LEDGER_HOST_PORT)/health"; do \
	  n=$${s%%:*}; p=$${s#*:}; printf "%-12s " $$n; curl -fsS http://localhost:$$p >/dev/null 2>&1 && echo OK || echo DOWN; done

agent-worker-health:  ## Scripted deployment proof: host worker reachable directly AND from inside the deployed cockpit container via host.docker.internal.
	@printf "%-28s " "host-worker (direct)"; curl -fsS http://127.0.0.1:$${AGENT_WORKER_PORT:-8791}/health >/dev/null 2>&1 && echo OK || echo "DOWN (start with: .\\scripts\\start_agent_worker.ps1 start)"
	@printf "%-28s " "cockpit -> host-worker"; \
	docker compose exec -T agent-kanban-ui python -c \
	  "import httpx,sys; r=httpx.get('http://host.docker.internal:$${AGENT_WORKER_PORT:-8791}/health', timeout=5); sys.exit(0 if r.status_code==200 else 1)" \
	  >/dev/null 2>&1 && echo OK || echo "DOWN (is the agent-kanban-ui container running? docker compose --profile ui up -d agent-kanban-ui)"

models:  ## Validate+render, pull local tags, restart litellm
	@$(MAKE) render
	@for t in $$($(PY) -c "import yaml; print(' '.join(yaml.safe_load(open('configs/models.yaml')).get('local_whitelist',[])))"); do echo "ollama pull $$t"; OLLAMA_HOST=$(OLLAMA_HOST) ollama pull $$t || echo "(skip $$t)"; done
	@$(COMPOSE) restart litellm && echo "models updated"

models-light:  ## Switch to the small-GPU/CPU profile (qwen3:8b), pull it, re-render
	@$(PY) -c "import yaml; from command_center.schemas import ModelRegistry; ModelRegistry.model_validate(yaml.safe_load(open('configs/models.light.yaml'))); print('models.light.yaml: VALID')"
	@for t in $$($(PY) -c "import yaml; print(' '.join(yaml.safe_load(open('configs/models.light.yaml')).get('local_whitelist',[])))"); do echo "ollama pull $$t"; OLLAMA_HOST=$(OLLAMA_HOST) ollama pull $$t || echo "(skip $$t)"; done
	@cp configs/models.light.yaml configs/models.yaml
	@$(MAKE) render
	@echo "switched to LIGHT profile (qwen3:8b). Revert: git checkout configs/models.yaml"

models-canary:  ## Route ~10% of a role to a local challenger. ROLE= MODEL=ollama_chat/tag
	@test -n "$(ROLE)" -a -n "$(MODEL)" || { echo "usage: make models-canary ROLE=coder MODEL=ollama_chat/qwen3-coder:30b"; exit 1; }
	@$(PY) -m command_center.registry.render --canary $(ROLE)=$(MODEL):0.1
	@$(COMPOSE) restart litellm && echo "canary live for $(ROLE)"

models-promote:  ## Promote canary to primary for ROLE=
	@test -n "$(ROLE)" || { echo "usage: make models-promote ROLE=coder"; exit 1; }
	@$(PY) -m command_center.registry.render --promote $(ROLE)
	@$(COMPOSE) restart litellm && echo "promoted $(ROLE) (edit configs/models.yaml to persist)"

models-rollback:  ## Revert canary for ROLE=
	@test -n "$(ROLE)" || { echo "usage: make models-rollback ROLE=coder"; exit 1; }
	@$(PY) -m command_center.registry.render
	@$(COMPOSE) restart litellm && echo "rolled back $(ROLE)"

model-scout:  ## Propose model candidates + watchlist (GLM/Kimi) from configured sources. Never edits configs.
	@$(PY) -m command_center.registry.model_scout --output generated/model-scout-report.md --feed-output generated/model-scout-feed.json || true
	@echo "review generated/model-scout-report.md; daily scan feed is generated/model-scout-feed.json"

model-scout-scan:  ## ONE-STEP bridge: discover models (scout) THEN feed them into the self-improvement scan. APPLY=1 drafts Proposed cards.
	@$(PY) -m command_center.registry.model_scout --output generated/model-scout-report.md --feed-output generated/model-scout-feed.json || true
	@$(PY) -m command_center.cli.improvement scan $(if $(APPLY),--apply,) --feeds generated/model-scout-feed.json $(if $(SHOW),--show-report,)
	@echo "scout -> scan bridge done (frontier_watch = track-as-context; pull_to_verify = propose pull; canary/promote stay human-only)"

frontier-router-dry-run:  ## Preview a frontier-router call's cost + policy (NO live egress). MODEL= PROVIDER= IN= OUT= TASK=
	@$(PY) -m command_center.cli.frontier_router dry-run --model $(or $(MODEL),glm-5.2) $(if $(PROVIDER),--provider $(PROVIDER),) --input-tokens $(or $(IN),120000) --output-tokens $(or $(OUT),8000) --task-class $(or $(TASK),frontier_reference_eval)

frontier-router-price-audit:  ## Flag stale frontier-router provider prices (never overwrites). TODAY=YYYY-MM-DD optional.
	@$(PY) -m command_center.cli.frontier_router price-audit $(if $(TODAY),--today $(TODAY),)

frontier-router-egress-check:  ## Forbidden-providers check in EGRESS mode (permits budgeted router keys; local lane stays strict).
	@$(PY) -m command_center.cli.check_forbidden_providers --allow-frontier-router-egress

agent-session-egress-check:  ## Forbidden-providers check in AGENT-SESSION EGRESS mode (permits ANTHROPIC/OPENAI keys only if configs/agent-session-budgets.yaml enables a harness; local lane + frontier lane stay strict).
	@$(PY) -m command_center.cli.check_forbidden_providers --allow-agent-session-egress

frontier-router-benchmark:  ## Continual top-3 KPI check (configs/model-benchmarks.yaml suite vs frontier candidates). SUITE= LIVE=1 for real calls (spends money if the lane is enabled).
	@$(PY) -m command_center.improvement.frontier_benchmark --suite $(or $(SUITE),chat) $(if $(LIVE),--live,)

colibri-benchmark:  ## Continual KPI check for the local-frontier lane (configs/model-benchmarks.yaml suite vs colibrì). SUITE= LIVE=1 for real calls (no $ cost, but can take minutes-to-hours). MAX_CASES= caps cases/candidate (default 3).
	@$(PY) -m command_center.improvement.local_frontier_benchmark --suite $(or $(SUITE),chat) $(if $(LIVE),--live,) --max-cases $(or $(MAX_CASES),3)

model-fit:  ## Which installed Ollama models fit the GPU budget. CTX= MODEL= ENV= VRAM=
	@$(PY) -m command_center.cli.model_fit $(if $(CTX),--ctx $(CTX),) $(if $(MODEL),--model $(MODEL),) $(if $(ENV),--env $(ENV),) $(if $(VRAM),--vram-gb $(VRAM),)

usage-digest:  ## Write generated/usage-digest.md from LiteLLM + Ledger usage APIs
	@$(PY) -m command_center.cli.usage_digest --output generated/usage-digest.md

usage-report: usage-digest  ## Alias for usage-digest

kanban-digest:  ## Write generated/kanban-digest.md — agent-surface metrics + tuning verdict (real data)
	@$(PY) -m command_center.cli.kanban_surface digest --output generated/kanban-digest.md

kanban-surface-validate:  ## Blocking N/N gate for the agent kanban surface (config/leakage/verbs/tuning)
	@$(PY) -m command_center.cli.kanban_surface validate

kanban-board-snapshot:  ## Write generated/board-snapshot.json for compatibility/history (local boards need no snapshot)
	@$(PY) -m command_center.cli.kanban_surface board-snapshot --output generated/board-snapshot.json

live-smoke:  ## Print real local model replies through Ollama/LiteLLM. TRIAGE=triage PLANNER=planner JUDGE=local-judge
	@uv run cc live-smoke $(or $(TRIAGE),triage) $(or $(PLANNER),planner) $(or $(JUDGE),local-judge)

repo-install:  ## Install hooks + devcontainer + standards into a repo. REPO=/path [PROFILE=python_ml_pipeline]
	@test -n "$(REPO)" || { echo "usage: make repo-install REPO=/path/to/repo [PROFILE=python_ml_pipeline]"; exit 1; }
	@cp repo-template/.pre-commit-config.yaml repo-template/CODEOWNERS "$(REPO)/"
	@cp -r repo-template/.github repo-template/scripts repo-template/.devcontainer "$(REPO)/"
	@$(PY) -m command_center.cli.render_standards $(or $(PROFILE),python_ml_pipeline) "$(REPO)"
	@echo "installed into $(REPO) — run 'cd $(REPO) && pre-commit install'"

backup:  ## restic snapshot (see docs/setup/SETUP-FROM-SCRATCH.md, Backups)
	@echo "wire to your restic repo (see docs/setup/SETUP-FROM-SCRATCH.md, Backups section)"

restore-drill:  ## Restore latest backup to temp + diff (schedule monthly)
	@echo "restore into /tmp/restore-drill and diff"

logs:  ## Tail all logs
	@$(COMPOSE) logs -f

channels-validate:  ## Validate configs/channels.yaml (chat transport registry)
	@$(PY) -m command_center.cli.validate_config | grep -E 'channels|PASS|FAIL' || true
	@$(PY) -m command_center.channels --dry-run

gateway:  ## Run enabled chat channels from configs/channels.yaml. Installs the gateways extra first.
	@if [ -n "$(UV)" ]; then uv pip install -e ".[gateways]" --python $(PY) --quiet; else $(PY) -m pip install -e ".[gateways]" --quiet; fi
	@$(PY) -m command_center.channels $(if $(CHANNELS),--channels $(CHANNELS),)

notify:  ## Push a proactive digest (brief + active missions) to Discord. ARGS=--dry-run to preview.
	@$(PY) -m command_center.cli.notify $(ARGS)

lint:  ## ruff + mypy over src/ (install the dev extra first: uv pip install -e ".[dev]")
	@$(PY) -m ruff check src
	@$(PY) -m mypy

test:  ## Run the test suite (install the dev extra first: uv pip install -e ".[dev]")
	@$(PY) -m pytest

# ---- improvement loop (experiment registry on the Ledger; dry-run by default) ----
improvement-validate:  ## Validate configs/improvement.yaml experiment definitions
	@$(PY) -m command_center.cli.improvement validate
improvement-list:  ## List registered experiments (STATUS= to filter)
	@$(PY) -m command_center.cli.improvement list $(if $(STATUS),--status $(STATUS),)
improvement-register:  ## Register an experiment ID=EXP-... (dry-run; APPLY=1 to commit). MISSION= optional
	@$(PY) -m command_center.cli.improvement register --id $(ID) $(if $(MISSION),--mission $(MISSION),) $(if $(APPLY),--apply,)
improvement-baseline:  ## Capture the baseline for ID=EXP-... (dry-run; APPLY=1 to run)
	@$(PY) -m command_center.cli.improvement baseline --id $(ID) $(if $(APPLY),--apply,)
improvement-run:  ## Run the candidate for ID=EXP-... (dry-run; APPLY=1 to run)
	@$(PY) -m command_center.cli.improvement run --id $(ID) $(if $(APPLY),--apply,)
improvement-verify:  ## Independently verify ID=EXP-... (dry-run; APPLY=1 to run). VERIFIER= optional
	@$(PY) -m command_center.cli.improvement verify --id $(ID) $(if $(VERIFIER),--verifier $(VERIFIER),) $(if $(APPLY),--apply,)
improvement-report:  ## Full audit report for ID=EXP-...
	@$(PY) -m command_center.cli.improvement report --id $(ID)
improvement-request-promotion:  ## Move a Verified experiment to Awaiting Human Promotion. ID=EXP-... APPLY=1
	@$(PY) -m command_center.cli.improvement request-promotion --id $(ID) $(if $(APPLY),--apply,)
improvement-canary:  ## HUMAN: start a canary. ID=EXP-... APPROVER=you APPLY=1
	@$(PY) -m command_center.cli.improvement canary --id $(ID) --approver "$(APPROVER)" $(if $(APPLY),--apply,)
improvement-promote:  ## HUMAN: promote after a clean canary. ID=EXP-... APPROVER=you APPLY=1
	@$(PY) -m command_center.cli.improvement promote --id $(ID) --approver "$(APPROVER)" $(if $(APPLY),--apply,)
improvement-rollback:  ## Roll back ID=EXP-... (APPLY=1). REASON= optional
	@$(PY) -m command_center.cli.improvement rollback --id $(ID) $(if $(REASON),--reason "$(REASON)",) $(if $(APPLY),--apply,)
improvement-post-watch:  ## Record a post-watch checkpoint. ID=EXP-... CHECKPOINT=1h [REGRESSION=1] APPLY=1
	@$(PY) -m command_center.cli.improvement post-watch --id $(ID) --checkpoint $(or $(CHECKPOINT),1h) $(if $(REGRESSION),--regression,) $(if $(APPLY),--apply,)
improvement-board:  ## Project the registry onto the improvements board (dry-run; APPLY=1 to write)
	@$(PY) -m command_center.cli.improvement board $(if $(APPLY),--apply,)
improvement-propose:  ## Run controlled proposal generation from evidence (dry-run; APPLY=1 to draft)
	@$(PY) -m command_center.cli.improvement propose $(if $(APPLY),--apply,)
improvement-scan:  ## Observer-only self-improvement scan -> Proposed cards + report (dry-run; APPLY=1). FEEDS=path SHOW=1
	@$(PY) -m command_center.cli.improvement scan $(if $(APPLY),--apply,) $(if $(FEEDS),--feeds $(FEEDS),) $(if $(METHOD),--method $(METHOD),) $(if $(SHOW),--show-report,)
improvement-scan-validate:  ## Blocking validation gate for the discovery scan (N/N PASS)
	@$(PY) -m command_center.cli.improvement scan-validate
life-center-sync:  ## Sync life-center-infra catalog+verify -> Life Center Kanban boards (scheduler entrypoint, NOT Airflow). PROFILE=everything
	@$(PY) -m command_center.cli.life_center_sync $(if $(PROFILE),--profile $(PROFILE),)
knowledge-generate:  ## Generate the observer-only OKF knowledge/ bundle from authoritative sources
	@$(PY) -m command_center.cli.knowledge generate
knowledge-validate:  ## Blocking validation gate for the knowledge/ bundle (N/N PASS)
	@$(PY) -m command_center.cli.knowledge validate
system-validation:  ## Write whole-system validation evidence from real config state. RUN_ID= optional
	@$(PY) -m command_center.cli.system_validation $(if $(RUN_ID),--run-id $(RUN_ID),)
judge-calibration:  ## Score the judge against the calibration set (TP/FP/FN/precision/recall)
	@$(PY) -m command_center.cli.improvement calibration
attention-digest:  ## Print the human-attention morning brief + queue metrics
	@$(PY) -m command_center.cli.improvement attention
