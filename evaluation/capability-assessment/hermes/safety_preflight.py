#!/usr/bin/env python3
"""Hermes spike isolation preflight (WS4).

Validates a Hermes v0.16.0 profile config against the isolation invariants in
PRE-REGISTRATION.md BEFORE the spike launches. The schema below was verified
against the installed package (hermes_cli/config.py, auth.py), NOT assumed:

  - `provider` must be an explicit LOCAL provider (`custom`/`ollama`). Auto-
    resolution (`auth.resolve_provider`) NEVER selects a local provider — it
    falls through to cloud/OpenRouter — so leaving it unset/`auto` is unsafe.
  - `base_url` must target Ollama `:11434` on a local host, NOT the LiteLLM
    proxy `:4000` (which triggers Hermes hang #26489).
  - `api_key` must be empty/local (no provider credential).
  - `model` must be set (otherwise it routes to a cloud default).
  - any `custom_providers[].base_url` must also be local.

NOTE (corrected from the first draft): v0.16.0 has NO `data_collection`/telemetry
config key — the original draft checked a key that does not exist. Telemetry/
exfil is instead controlled structurally (no cloud provider, no API key, local-
only endpoint) and verified at runtime by an egress scan of the logs. Pure check
+ thin CLI; no side effects, no network.

Usage:  python safety_preflight.py <hermes-config.yaml>   # exit 0 = PASS, 1 = FAIL
"""
from __future__ import annotations

import sys
from pathlib import Path

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
LOCAL_PROVIDERS = {"custom", "ollama", "vllm", "llamacpp", "llama.cpp", "llama-cpp"}
ALLOWED_KEYS = {"", "ollama", "local", "not-needed", "none"}


def _base_url_problems(base: str, where: str) -> list[str]:
    out: list[str] = []
    if ":4000" in base:
        out.append(
            f"{where} points at LiteLLM :4000 — triggers Hermes hang #26489; "
            "point at Ollama :11434 directly")
    if ":11434" not in base:
        out.append(f"{where} must target Ollama :11434 directly, got {base or '<unset>'!r}")
    if not any(h in base for h in LOCAL_HOSTS):
        out.append(f"{where} must be a local host {LOCAL_HOSTS}, got {base or '<unset>'!r}")
    return out


def check_hermes_isolation(config: dict) -> list[str]:
    """Return a list of isolation violations ([] means safe to run the spike)."""
    problems: list[str] = []

    provider = str(config.get("provider") or "").lower()
    if provider not in LOCAL_PROVIDERS:
        problems.append(
            f"provider must be an explicit local provider {sorted(LOCAL_PROVIDERS)}, "
            f"got {provider or '<unset>'!r} — 'auto'/cloud resolves to OpenRouter and needs a key")

    problems += _base_url_problems(str(config.get("base_url") or ""), "base_url")

    key = str(config.get("api_key") or "").strip().lower()
    if key not in ALLOWED_KEYS:
        problems.append("api_key is a non-local value — the spike uses no provider keys")

    if not str(config.get("model") or "").strip():
        problems.append("model must be set — an empty model routes to a cloud default")

    for i, entry in enumerate(config.get("custom_providers") or []):
        if not isinstance(entry, dict):
            continue
        base = str(entry.get("base_url") or entry.get("url") or "")
        problems += _base_url_problems(base, f"custom_providers[{i}].base_url")
        ek = str(entry.get("api_key") or "").strip().lower()
        if ek not in ALLOWED_KEYS:
            problems.append(f"custom_providers[{i}].api_key is a non-local value")

    return problems


def main(argv: list[str] | None = None) -> int:
    import yaml
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: safety_preflight.py <hermes-config.yaml>")
        return 2
    cfg = yaml.safe_load(Path(args[0]).read_text(encoding="utf-8")) or {}
    problems = check_hermes_isolation(cfg)
    if problems:
        print("PREFLIGHT: FAIL")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("PREFLIGHT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
