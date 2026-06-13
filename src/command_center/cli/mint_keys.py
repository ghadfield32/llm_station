#!/usr/bin/env python3
"""Mint the budgeted LiteLLM virtual keys AND write them into .env.

Removes the one hand-editing step in first boot: the old flow printed two keys
for you to copy-paste into .env and re-confirm. This calls /key/generate for the
two service aliases and writes HERMES_LITELLM_KEY / JUDGE_GATE_LITELLM_KEY back
into .env in place (creating the lines if absent, replacing them if present).

Requires LiteLLM already up (see `make bootstrap`) and LITELLM_MASTER_KEY in .env.
Fails loudly if the proxy is unreachable or the response has no key — no silent
placeholder is ever written.

  python -m command_center.cli.mint_keys      (called by `make keys`)
"""
from __future__ import annotations

from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = ROOT / ".env"

# alias -> the budgeted scope it is allowed to call (mirrors the Makefile payloads)
KEYS = {
    "HERMES_LITELLM_KEY": {
        "key_alias": "hermes-orchestrator",
        "models": ["triage", "planner", "coder", "architect-judge", "security-judge", "local-judge"],
        "metadata": {"routing": "local-only"},
        "rpm_limit": 60,
        "max_parallel_requests": 4,
    },
    "JUDGE_GATE_LITELLM_KEY": {
        "key_alias": "judge-gate",
        "models": ["triage", "planner", "architect-judge", "security-judge", "local-judge"],
        "metadata": {"routing": "local-only"},
        "rpm_limit": 120,
        "max_parallel_requests": 4,
    },
}


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip("'\"")
    return values


def write_env_value(env_var: str, value: str) -> None:
    """Replace the `env_var=` line in .env, or append it if missing. Preserves
    every other line, comment, and ordering."""
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    prefix = f"{env_var}="
    replaced = False
    for i, line in enumerate(lines):
        if line.strip().startswith(prefix):
            lines[i] = f"{env_var}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{env_var}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mint_one(base_url: str, master_key: str, payload: dict) -> str:
    r = httpx.post(
        f"{base_url.rstrip('/')}/key/generate",
        headers={"Authorization": f"Bearer {master_key}", "Content-Type": "application/json"},
        json=payload, timeout=30,
    )
    r.raise_for_status()
    key = r.json().get("key")
    if not key:
        raise RuntimeError(f"/key/generate for {payload['key_alias']} returned no 'key': {r.text[:200]}")
    return key


def main() -> int:
    if not ENV_PATH.exists():
        raise SystemExit("mint_keys: no .env — run `make setup` first")
    env = read_env()
    master_key = env.get("LITELLM_MASTER_KEY", "")
    if not master_key:
        raise SystemExit("mint_keys: LITELLM_MASTER_KEY missing from .env (run `make setup`)")
    base_url = env.get("LITELLM_URL") or "http://localhost:4000"

    for env_var, payload in KEYS.items():
        key = mint_one(base_url, master_key, payload)
        write_env_value(env_var, key)
        print(f"  wrote {env_var}  ({payload['key_alias']}, scope: {len(payload['models'])} aliases)")

    print("keys: minted and written to .env — next: `make up`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
