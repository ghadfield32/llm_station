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


def check_env_files(errors: list[str]) -> None:
    for rel in (".env", ".env.example"):
        keys = dotenv_keys(ROOT / rel)
        leaked = sorted(keys & FORBIDDEN_KEYS)
        if leaked:
            errors.append(f"{rel} defines forbidden provider key(s): {', '.join(leaked)}")


def check_process_env(errors: list[str]) -> None:
    leaked = sorted(key for key in FORBIDDEN_KEYS if os.environ.get(key))
    if leaked:
        errors.append(f"process environment contains forbidden provider key(s): {', '.join(leaked)}")


def check_compose(errors: list[str]) -> None:
    path = ROOT / "docker-compose.yml"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    for key in FORBIDDEN_KEYS:
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


def main() -> int:
    errors: list[str] = []
    check_env_files(errors)
    check_process_env(errors)
    check_compose(errors)
    check_models_yaml(errors)
    check_litellm_config(errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print("forbidden-providers: FAIL")
        return 1

    print("forbidden-providers: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
