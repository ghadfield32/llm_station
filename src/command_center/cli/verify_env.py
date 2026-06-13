#!/usr/bin/env python3
"""Verify local runtime setup before starting the command center.

`base` mode is used before first boot, when LiteLLM virtual keys do not exist
yet. `full` mode is used before the full stack starts.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = ROOT / ".env"
COMPOSE_PATH = ROOT / "docker-compose.yml"
MAKEFILE_PATH = ROOT / "Makefile"

BASE_REQUIRED = (
    "LITELLM_MASTER_KEY",
    "POSTGRES_PASSWORD",
    "LEDGER_APPROVAL_SECRET",
    "OLLAMA_API_BASE",
)

FULL_REQUIRED = BASE_REQUIRED + (
    "HERMES_LITELLM_KEY",
    "JUDGE_GATE_LITELLM_KEY",
)

OPTIONAL_WARN = (
    ("GITHUB_TOKEN", "GitHub L3 push/PR automation disabled"),
)

FORBIDDEN_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
)

PLACEHOLDER_MARKERS = (
    "xxxx",
    "change-me",
    "replace",
    "todo",
    "example",
    "placeholder",
)


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def is_placeholder(value: str) -> bool:
    if not value.strip():
        return True
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def check_digest(errors: list[str]) -> None:
    if not COMPOSE_PATH.exists():
        errors.append("missing docker-compose.yml")
        return

    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8") if MAKEFILE_PATH.exists() else ""

    if "litellm@sha256:" not in compose:
        errors.append("LiteLLM image is not pinned by digest in docker-compose.yml")
    if "REPLACE_WITH_VERIFIED_DIGEST" in compose or "REPLACE_WITH_VERIFIED_DIGEST" in makefile:
        errors.append(
            "replace REPLACE_WITH_VERIFIED_DIGEST in docker-compose.yml and Makefile "
            "with a verified LiteLLM GHCR digest"
        )


def check_env(mode: str, errors: list[str], warnings: list[str]) -> None:
    if not ENV_PATH.exists():
        errors.append("missing .env; run `make setup` / `python -m command_center.cli.init_env` or copy .env.example to .env")
        return

    values = load_env(ENV_PATH)
    for key in FORBIDDEN_ENV_KEYS:
        if key in values:
            errors.append(f"remove forbidden provider key from .env: {key}")

    required = FULL_REQUIRED if mode == "full" else BASE_REQUIRED
    for key in required:
        value = values.get(key, "")
        if is_placeholder(value):
            errors.append(f"missing/placeholder: {key}")

    for key, message in OPTIONAL_WARN:
        if is_placeholder(values.get(key, "")):
            warnings.append(f"{key} not set: {message}")

    ollama = values.get("OLLAMA_API_BASE", "")
    if "REPLACE-WITH-4090-TAILSCALE-IP" in ollama:
        errors.append("OLLAMA_API_BASE still points at the Phase 2 placeholder")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("base", "full"), default="full")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    check_digest(errors)
    check_env(args.mode, errors, warnings)

    for warning in warnings:
        print(f"WARN: {warning}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"verify-{args.mode}: FAIL")
        return 1

    print(f"verify-{args.mode}: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
