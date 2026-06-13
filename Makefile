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
        model-scout proactive-validate proactive-smoke targets-validate kanban-validate kanban-bridge appflowy-audit tools-validate evals cross-refs ui-validate \
        standards-validate forbidden-providers usage-digest usage-report live-smoke impact mission-dryrun env-smoke repo-install backup restore-drill logs \
        gateway channels-validate lint test

help:  ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n",$$1,$$2}'

validate:  ## Validate all configs/*.yaml against Pydantic contracts + cross-file refs
	@$(PY) -m command_center.cli.validate_config
	@$(PY) -m command_center.cli.check_cross_refs
	@$(PY) -m command_center.registry.render
	@$(PY) -m command_center.cli.check_forbidden_providers

schema:  ## Generate JSON Schema from contracts -> generated/json-schema
	@$(PY) -m command_center.cli.render_json_schema

render:  ## Validate + render generated/litellm-config.yaml from configs
	@$(PY) -m command_center.cli.validate_config
	@$(PY) -m command_center.registry.render
	@$(PY) -m command_center.cli.check_forbidden_providers

impact:  ## Blast radius of your git diff (or: make impact FILES="a b")
	@$(PY) -m command_center.cli.impact $(FILES)

mission-dryrun:  ## Run fake L0..L4 missions through gates+judges (no model calls)
	@for t in L0 L1 L2 L3 L4; do $(PY) -m command_center.cli.smoke_mission $$t demo "smoke"; echo; done

env-smoke:  ## Validate environments + isolation invariants
	@$(PY) -c "import yaml; from command_center.schemas import EnvironmentsConfig; EnvironmentsConfig.model_validate(yaml.safe_load(open('configs/environments.yaml'))); print('env-smoke: PASS')"

proactive-validate:  ## Validate configs/proactive.yaml against its contract
	@$(PY) -c "import yaml; from command_center.schemas import ProactiveConfig; ProactiveConfig.model_validate(yaml.safe_load(open('configs/proactive.yaml'))); print('proactive-validate: PASS')"

proactive-smoke:  ## Dry-run the proactive lane: list checks + their on_fail + risk cap (no calls)
	@$(PY) -c "import yaml; from command_center.schemas import ProactiveConfig; c=ProactiveConfig.model_validate(yaml.safe_load(open('configs/proactive.yaml'))); [print(f'  {x.name:34s} {x.schedule:14s} on_fail={x.on_fail:18s} max={x.auto_patch_max_risk.value}') for x in c.runtime_checks+c.repo_stewardship]; print('proactive-smoke: PASS')"

targets-validate:  ## Validate configs/targets.yaml (the watch inventory)
	@$(PY) -c "import yaml; from command_center.schemas import TargetsConfig; TargetsConfig.model_validate(yaml.safe_load(open('configs/targets.yaml'))); print('targets-validate: PASS')"

kanban-validate:  ## Validate configs/kanban.yaml (AppFlowy/GrowthOS intake)
	@$(PY) -c "import yaml; from command_center.schemas import KanbanConfig; KanbanConfig.model_validate(yaml.safe_load(open('configs/kanban.yaml'))); print('kanban-validate: PASS')"

kanban-bridge:  ## Dry-run AppFlowy mission_intake -> Ledger mission drafts. APPLY=1 opens missions.
	@$(PY) -m command_center.cli.kanban_bridge $(if $(APPLY),--apply,)

appflowy-audit:  ## Read-only audit of AppFlowy board fields/views/blank starter rows. DETAILS=1 samples rows.
	@cd appflowy_kanban/growth-os && PYTHONPATH=. .venv/Scripts/python.exe scripts/audit_workspace.py $(if $(DETAILS),--details,)

tools-validate:  ## Validate configs/tools.yaml (tool permission registry)
	@$(PY) -c "import yaml; from command_center.schemas import ToolsConfig; ToolsConfig.model_validate(yaml.safe_load(open('configs/tools.yaml'))); print('tools-validate: PASS')"

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
	@test -f .env || { $(PY) -m command_center.cli.init_env; echo "replace LiteLLM digest, confirm OLLAMA_API_BASE, then re-run"; exit 1; }
	@$(MAKE) render
	@$(COMPOSE) build ledger judge-gate proactive-runner
	@echo "setup OK — next: replace the LiteLLM digest, then make bootstrap"

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

keys:  ## Create budgeted LiteLLM virtual keys (first boot)
	@$(MAKE) verify-base
	@source .env; \
	echo "hermes-orchestrator:"; curl -s $(LITELLM_URL)/key/generate -H "Authorization: Bearer $$LITELLM_MASTER_KEY" -H 'Content-Type: application/json' -d '{"key_alias":"hermes-orchestrator","models":["triage","planner","coder","architect-judge","security-judge","local-judge"],"metadata":{"routing":"local-only"},"rpm_limit":60,"max_parallel_requests":4}'; echo; \
	echo "judge-gate:"; curl -s $(LITELLM_URL)/key/generate -H "Authorization: Bearer $$LITELLM_MASTER_KEY" -H 'Content-Type: application/json' -d '{"key_alias":"judge-gate","models":["triage","planner","architect-judge","security-judge","local-judge"],"metadata":{"routing":"local-only"},"rpm_limit":120,"max_parallel_requests":4}'; echo; \
	echo "paste BOTH keys above into .env as HERMES_LITELLM_KEY / JUDGE_GATE_LITELLM_KEY,"; \
	echo "confirm they are non-empty, then run 'make up'."

health:  ## Check every service health endpoint
	@for s in "litellm:4000/health/liveliness" "judge-gate:8088/health" "ledger:$(LEDGER_HOST_PORT)/health"; do \
	  n=$${s%%:*}; p=$${s#*:}; printf "%-12s " $$n; curl -fsS http://localhost:$$p >/dev/null 2>&1 && echo OK || echo DOWN; done

models:  ## Validate+render, pull local tags, restart litellm
	@$(MAKE) render
	@for t in $$($(PY) -c "import yaml; print(' '.join(yaml.safe_load(open('configs/models.yaml')).get('local_whitelist',[])))"); do echo "ollama pull $$t"; OLLAMA_HOST=$(OLLAMA_HOST) ollama pull $$t || echo "(skip $$t)"; done
	@$(COMPOSE) restart litellm && echo "models updated"

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

model-scout:  ## Propose model candidates from configured sources. Never edits configs.
	@$(PY) -m command_center.registry.model_scout --output generated/model-scout-report.md || true
	@echo "review generated/model-scout-report.md, then edit configs/models.yaml manually if warranted"

usage-digest:  ## Write generated/usage-digest.md from LiteLLM + Ledger usage APIs
	@$(PY) -m command_center.cli.usage_digest --output generated/usage-digest.md

usage-report: usage-digest  ## Alias for usage-digest

live-smoke:  ## Print real local model replies through Ollama/LiteLLM. TRIAGE=triage PLANNER=planner JUDGE=local-judge
	@bash scripts/live_smoke.sh $(or $(TRIAGE),triage) $(or $(PLANNER),planner) $(or $(JUDGE),local-judge)

repo-install:  ## Install hooks + devcontainer + standards into a repo. REPO=/path [PROFILE=python_ml_pipeline]
	@test -n "$(REPO)" || { echo "usage: make repo-install REPO=/path/to/repo [PROFILE=python_ml_pipeline]"; exit 1; }
	@cp repo-template/.pre-commit-config.yaml repo-template/CODEOWNERS "$(REPO)/"
	@cp -r repo-template/.github repo-template/scripts repo-template/.devcontainer "$(REPO)/"
	@$(PY) -m command_center.cli.render_standards $(or $(PROFILE),python_ml_pipeline) "$(REPO)"
	@echo "installed into $(REPO) — run 'cd $(REPO) && pre-commit install'"

backup:  ## restic snapshot (see docs/SETUP-FROM-SCRATCH.md, Backups)
	@echo "wire to your restic repo (see docs/SETUP-FROM-SCRATCH.md, Backups section)"

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

lint:  ## ruff + mypy over src/ (install the dev extra first: uv pip install -e ".[dev]")
	@$(PY) -m ruff check src
	@$(PY) -m mypy

test:  ## Run the test suite (install the dev extra first: uv pip install -e ".[dev]")
	@$(PY) -m pytest
