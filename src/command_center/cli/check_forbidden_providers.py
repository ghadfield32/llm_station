#!/usr/bin/env python3
"""Fail if cloud provider routes or provider API keys re-enter the local-only setup."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN_KEYS = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"}
FORBIDDEN_MODEL_FRAGMENTS = ("openai/", "anthropic/", "openrouter/", "gpt-", "claude-")

# Keys that belong ONLY to the separate, budgeted frontier-router backup lane. They stay
# forbidden by default; they are permitted ONLY under explicit `--allow-frontier-router-egress`
# AND only when the budget is enabled with redaction + usage accounting. The local LiteLLM lane
# (models.yaml / litellm-config) stays cloud-free in BOTH modes — that is never relaxed.
ROUTER_LANE_KEYS = {"OPENROUTER_API_KEY", "ZAI_API_KEY"}
FRONTIER_BUDGETS = ROOT / "configs" / "frontier-router-budgets.yaml"

# Keys that belong ONLY to the separate agent-session subsystem (Claude Agent / Codex Agent —
# see src/command_center/agent_sessions/; real filesystem/shell tool access via their own SDKs,
# NOT the GatewayCore chat lane). Permitted ONLY under explicit
# `--allow-agent-session-egress` AND only when configs/agent-session-budgets.yaml enables at
# least one harness. Entirely independent of ROUTER_LANE_KEYS/frontier_egress_ready — neither
# flag exempts the other lane's keys. The local LiteLLM lane stays cloud-free in every mode.
AGENT_SESSION_KEYS = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}
AGENT_SESSION_BUDGETS = ROOT / "configs" / "agent-session-budgets.yaml"


def frontier_egress_ready() -> tuple[bool, str]:
    """The router lane may permit its keys only when its budget is deliberately enabled with the
    safety knobs on. Reads the raw budgets YAML (no fabrication: a missing/false flag = not
    ready)."""
    if not FRONTIER_BUDGETS.exists():
        return False, "configs/frontier-router-budgets.yaml is missing"
    data = yaml.safe_load(FRONTIER_BUDGETS.read_text(encoding="utf-8")) or {}
    default = data.get("default") or {}
    if not default.get("enabled"):
        return False, "budgets.default.enabled is false"
    if not default.get("require_redaction"):
        return False, "budgets.default.require_redaction is false"
    if not default.get("fail_on_missing_usage"):
        return False, "budgets.default.fail_on_missing_usage is false"
    return True, "frontier-router budget enabled with redaction + usage accounting"


def agent_session_egress_ready() -> tuple[bool, str]:
    """The agent-session subsystem may permit ANTHROPIC_API_KEY/OPENAI_API_KEY only when this
    file deliberately enables it AND at least one harness under default.harnesses is turned on
    (enabled: true with every harness false is a no-op, not readiness). Reads the raw budgets
    YAML (no fabrication: a missing/false flag = not ready)."""
    if not AGENT_SESSION_BUDGETS.exists():
        return False, "configs/agent-session-budgets.yaml is missing"
    data = yaml.safe_load(AGENT_SESSION_BUDGETS.read_text(encoding="utf-8")) or {}
    default = data.get("default") or {}
    if not default.get("enabled"):
        return False, "agent-session-budgets.yaml default.enabled is false"
    harnesses = default.get("harnesses") or {}
    active = sorted(name for name, on in harnesses.items() if on)
    if not active:
        return False, "no harness under default.harnesses is enabled"
    return True, f"agent-session egress enabled for: {', '.join(active)}"


def dotenv_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    keys: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.add(line.split("=", 1)[0].strip())
    return keys


def check_env_files(errors: list[str], forbidden: set[str]) -> None:
    for rel in (".env", ".env.example"):
        keys = dotenv_keys(ROOT / rel)
        leaked = sorted(keys & forbidden)
        if leaked:
            errors.append(f"{rel} defines forbidden provider key(s): {', '.join(leaked)}")


def check_process_env(errors: list[str], forbidden: set[str]) -> None:
    leaked = sorted(key for key in forbidden if os.environ.get(key))
    if leaked:
        errors.append(f"process environment contains forbidden provider key(s): {', '.join(leaked)}")


def check_compose(errors: list[str], forbidden: set[str]) -> None:
    path = ROOT / "docker-compose.yml"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    for key in forbidden:
        if f"${{{key}}}" in text:
            errors.append(f"docker-compose.yml passes forbidden provider key {key}")


def check_models_yaml(errors: list[str]) -> None:
    path = ROOT / "configs" / "models.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for role, candidates in (data.get("roles") or {}).items():
        for candidate in candidates or []:
            provider = candidate.get("provider")
            model = str(candidate.get("model", ""))
            alias = candidate.get("alias", "<unknown>")
            if provider != "ollama":
                errors.append(f"configs/models.yaml role '{role}' alias '{alias}' uses forbidden provider '{provider}'")
            if any(fragment in model.lower() for fragment in ("gpt-", "claude-", "openrouter/")):
                errors.append(f"configs/models.yaml role '{role}' alias '{alias}' uses forbidden model '{model}'")


def check_litellm_config(errors: list[str]) -> None:
    path = ROOT / "generated" / "litellm-config.yaml"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    for fragment in FORBIDDEN_MODEL_FRAGMENTS:
        if fragment in lowered:
            errors.append(f"generated/litellm-config.yaml contains forbidden model fragment '{fragment}'")

    data: dict[str, Any] = yaml.safe_load(text) or {}
    for entry in data.get("model_list", []) or []:
        params = entry.get("litellm_params") or {}
        model = str(params.get("model", ""))
        api_base = str(params.get("api_base", ""))
        name = entry.get("model_name", "<unknown>")
        if not model.startswith("ollama_chat/"):
            errors.append(f"generated alias '{name}' is not ollama_chat-backed: {model}")
        if api_base != "os.environ/OLLAMA_API_BASE":
            errors.append(f"generated alias '{name}' does not use OLLAMA_API_BASE")


def main(allow_router_egress: bool = False, allow_agent_session_egress: bool = False) -> int:
    errors: list[str] = []
    forbidden = set(FORBIDDEN_KEYS)
    if allow_router_egress:
        ready, why = frontier_egress_ready()
        if ready:
            # Permit ONLY the router-lane keys, and ONLY for the env/process/compose checks.
            forbidden -= ROUTER_LANE_KEYS
            print(f"frontier-router egress mode: router-lane keys permitted ({why})")
        else:
            errors.append(
                f"--allow-frontier-router-egress requested but the lane is not ready: {why}")
    if allow_agent_session_egress:
        ready, why = agent_session_egress_ready()
        if ready:
            # Permit ONLY the agent-session keys — independent of ROUTER_LANE_KEYS above.
            forbidden -= AGENT_SESSION_KEYS
            print(f"agent-session egress mode: agent-session keys permitted ({why})")
        else:
            errors.append(
                f"--allow-agent-session-egress requested but not ready: {why}")

    check_env_files(errors, forbidden)
    check_process_env(errors, forbidden)
    check_compose(errors, forbidden)
    # The LOCAL lane is cloud-free in EVERY mode — never relaxed by either egress flag.
    check_models_yaml(errors)
    check_litellm_config(errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print("forbidden-providers: FAIL")
        return 1

    labels = []
    if allow_router_egress:
        labels.append("frontier-router egress")
    if allow_agent_session_egress:
        labels.append("agent-session egress")
    label = f" ({', '.join(labels)})" if labels else ""
    print(f"forbidden-providers: PASS{label}")
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Fail if cloud routes/keys re-enter the local-only setup.")
    parser.add_argument(
        "--allow-frontier-router-egress", action="store_true",
        help=("permit the budgeted router-lane keys (OPENROUTER_API_KEY/ZAI_API_KEY) IFF "
              "configs/frontier-router-budgets.yaml is enabled with redaction + usage "
              "accounting; the local LiteLLM lane stays cloud-free regardless"))
    parser.add_argument(
        "--allow-agent-session-egress", action="store_true",
        help=("permit the agent-session keys (ANTHROPIC_API_KEY/OPENAI_API_KEY) IFF "
              "configs/agent-session-budgets.yaml enables at least one harness; the local "
              "LiteLLM lane and the frontier-router lane stay unaffected regardless"))
    args = parser.parse_args()
    raise SystemExit(main(
        allow_router_egress=args.allow_frontier_router_egress,
        allow_agent_session_egress=args.allow_agent_session_egress))
