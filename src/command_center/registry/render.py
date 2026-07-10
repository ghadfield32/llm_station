#!/usr/bin/env python3
"""
render.py — configs/models.yaml -> generated/litellm-config.yaml

Validates through the ModelRegistry contract FIRST (so a broken registry can't
produce a broken proxy config), then emits the model_list block. Supports canary
and promote for safe model rollout.

  render.py                                   # normal render
  render.py --canary coder=ollama_chat/new-local-tag:0.1
  render.py --promote coder
"""
import sys
import os
import yaml

from command_center.schemas import ModelRegistry

SRC = "configs/models.yaml"
OUT = "generated/litellm-config.yaml"
START = "# >>> AUTO-GEN model_list (render.py) >>>"
END = "# <<< AUTO-GEN model_list <<<"

SETTINGS = """
router_settings:
  routing_strategy: simple-shuffle
  num_retries: 2
  request_timeout: 600

litellm_settings:
  drop_params: true
  cache: true
  cache_params: { type: local }

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  # Cross-surface net: persist request/response bodies in SpendLogs so the
  # LiteLLM Admin UI Logs page shows the full story of EVERY call through the
  # proxy, no matter which surface made it (cockpit, Discord, judges, CLI).
  # GatewayCore passes litellm_session_id=surface:conversation_id, so Session
  # Logs group by the same key as the flight recorder. Data stays in the local
  # litellm-db Postgres. Auto-retention (maximum_spend_logs_retention_period)
  # is enterprise-gated; prune manually if the DB grows:
  #   DELETE FROM "LiteLLM_SpendLogs" WHERE "startTime" < now() - interval '30 days';
  # The per-conversation flight recorder (generated/chat-transcripts/) remains
  # the primary review surface — this is the safety net underneath it.
  store_prompts_in_spend_logs: true
"""


def provider_model(c) -> str:
    return f"ollama_chat/{c.model}"


def build(reg, canary, promote) -> str:
    lines = ["model_list:"]
    for role, cands in reg.roles.items():
        ordered = sorted(cands, key=lambda c: c.priority)
        if role in promote:
            ordered = [c for c in ordered if c.canary_weight > 0] + \
                      [c for c in ordered if c.canary_weight == 0]
        for c in ordered:
            # Per-candidate endpoint: a role's lower-priority candidate can
            # live on a second GPU by setting api_base_env in models.yaml.
            # Defaults to OLLAMA_API_BASE (the primary 4090). simple-shuffle +
            # num_retries (router_settings) load-balances same-named
            # deployments and retries the survivor if one endpoint is down.
            lines += [f"  - model_name: {role}",
                      "    litellm_params:",
                      f"      model: {provider_model(c)}",
                      f"      api_base: os.environ/{c.api_base_env}"]
            if c.canary_weight and role not in canary:
                lines.append(f"      weight: {c.canary_weight}")
        if role in canary:
            model, weight = canary[role]
            lines += [f"  - model_name: {role}        # CANARY ~{int(float(weight)*100)}%",
                      "    litellm_params:",
                      f"      model: {model}",
                      "      api_base: os.environ/OLLAMA_API_BASE",
                      f"      weight: {weight}"]
    return "\n".join(lines)


def main():
    canary, promote = {}, set()
    a = sys.argv[1:]
    i = 0
    while i < len(a):
        if a[i] == "--canary":
            role, rest = a[i + 1].split("=", 1)
            model, weight = rest.rsplit(":", 1)
            if not model.startswith("ollama_chat/"):
                raise SystemExit("canary model must be local-only and start with ollama_chat/")
            canary[role] = (model, weight)
            i += 2
        elif a[i] == "--promote":
            promote.add(a[i + 1]); i += 2
        else:
            i += 1

    reg = ModelRegistry.model_validate(
        yaml.safe_load(open(SRC, encoding="utf-8")))
    block = f"{START}\n{build(reg, canary, promote)}\n{END}"
    os.makedirs("generated", exist_ok=True)
    # UTF-8 explicitly: Windows' locale default (cp1252) would write bytes the
    # downstream utf-8 readers (forbidden-provider scan, litellm) reject
    open(OUT, "w", encoding="utf-8").write(block + "\n" + SETTINGS)
    print(f"rendered {len(reg.roles)} roles -> {OUT}")
    if canary:
        print(f"  canary: {canary}")
    if promote:
        print(f"  promoted: {promote}")


if __name__ == "__main__":
    main()
