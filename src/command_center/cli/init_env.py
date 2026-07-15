#!/usr/bin/env python3
"""Create a local .env with generated local-only command-center secrets.

Provider API credentials do not belong in this repo. Claude Code and Codex use
their own subscription/OAuth logins; LiteLLM routes only to local Ollama models.
Runtime virtual keys stay blank until LiteLLM mints them during first boot.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / ".env.example"
DEST = ROOT / ".env"

GENERATED_KEYS = {
    "LITELLM_MASTER_KEY": lambda: "sk-master-" + secrets.token_urlsafe(32),
    "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(32),
    "LEDGER_APPROVAL_SECRET": lambda: secrets.token_urlsafe(32),
    "AGENT_WORKER_TOKEN": lambda: secrets.token_urlsafe(48),
}


def main() -> int:
    if DEST.exists():
        print(".env already exists; leaving it unchanged")
        return 0

    if not TEMPLATE.exists():
        print("missing .env.example", file=sys.stderr)
        return 1

    rendered: list[str] = []
    for line in TEMPLATE.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            rendered.append(line)
            continue

        key, _value = line.split("=", 1)
        if key in GENERATED_KEYS:
            rendered.append(f"{key}={GENERATED_KEYS[key]()}")
        else:
            rendered.append(line)

    DEST.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    print("created .env with generated local service and agent-worker secrets")
    print("do not add OpenAI/Anthropic/OpenRouter API keys to this file")
    print("fill HERMES_LITELLM_KEY and JUDGE_GATE_LITELLM_KEY after make keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
