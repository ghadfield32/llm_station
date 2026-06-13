#!/usr/bin/env python3
"""Preflight doctor — one green/red checklist of everything first boot needs.

Surfaces every prerequisite at once (instead of failing one at a time across
setup -> bootstrap -> up): Docker daemon, uv, Ollama reachability, the service
ports, .env presence, the local-only provider boundary, and the pinned LiteLLM
digest. Exits non-zero only on real blockers; reachability/port notes are
informational (the stack may simply not be up yet).

  python -m command_center.cli.doctor      (or: make doctor)
"""
from __future__ import annotations

import shutil
import socket
import subprocess
from pathlib import Path

import httpx
import yaml

from command_center.cli.check_forbidden_providers import FORBIDDEN_KEYS, dotenv_keys

ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = ROOT / ".env"
COMPOSE = ROOT / "docker-compose.yml"
MODELS_YAML = ROOT / "configs" / "models.yaml"
# host-reachable services; (name, port). Ollama is the host runtime LiteLLM routes to.
PORTS = [("litellm", 4000), ("judge-gate", 8088), ("ledger", 8091), ("ollama", 11434)]
OLLAMA_HOST = "http://localhost:11434"


def _env_values() -> dict[str, str]:
    out: dict[str, str] = {}
    if ENV_PATH.exists():
        for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    return out


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def docker_ok() -> tuple[bool, str, bool]:
    if not shutil.which("docker"):
        return False, "docker not on PATH — install Docker Desktop / Engine", True
    r = subprocess.run(["docker", "info"], capture_output=True, text=True)
    if r.returncode != 0:
        return False, "docker installed but daemon not running — start Docker", True
    return True, "daemon running", True


def uv_ok() -> tuple[bool, str, bool]:
    path = shutil.which("uv")
    # uv is strongly preferred but `make setup` falls back to python -m venv, so warn not block
    return (bool(path), path or "uv not found — `pip install uv` for locked installs", False)


def ollama_ok() -> tuple[bool, str, bool]:
    try:
        r = httpx.get(f"{OLLAMA_HOST}/api/version", timeout=2)
        r.raise_for_status()
        return True, f"reachable at {OLLAMA_HOST} (v{r.json().get('version', '?')})", False
    except Exception:
        return False, f"not reachable at {OLLAMA_HOST} — start Ollama before live-smoke", False


def ollama_models() -> tuple[bool, str, bool]:
    """Warn (not block) if the model tags the configs route to aren't pulled yet —
    otherwise first-boot succeeds but live-smoke and every channel reply fail with
    'model not found'. The whitelist is the canonical pull set (`make models`)."""
    whitelist = yaml.safe_load(MODELS_YAML.read_text(encoding="utf-8")).get("local_whitelist", [])
    if not whitelist:
        return True, "no local_whitelist to check", False
    try:
        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        r.raise_for_status()
        pulled = {m["name"] for m in r.json().get("models", [])}
    except Exception:
        return False, "can't list models (ollama down) — start Ollama, then `make models`", False
    missing = [t for t in whitelist if t not in pulled]
    if missing:
        return (False,
                f"not pulled: {', '.join(missing)} — run `make models` "
                "(these are ~24 GB-class; on a smaller GPU/CPU run `make models-light` "
                "for a ready qwen3:8b profile instead)", False)
    return True, f"all {len(whitelist)} whitelisted models present", False


def env_present() -> tuple[bool, str, bool]:
    if ENV_PATH.exists():
        return True, ".env exists", True
    return False, "no .env — run `make setup` (or `python -m command_center.cli.init_env`)", True


def no_provider_keys() -> tuple[bool, str, bool]:
    leaked = sorted(dotenv_keys(ENV_PATH) & FORBIDDEN_KEYS)
    if leaked:
        return False, f".env contains forbidden provider key(s): {', '.join(leaked)}", True
    return True, "no OpenAI/Anthropic/OpenRouter keys in .env", True


def digest_pinned() -> tuple[bool, str, bool]:
    if not COMPOSE.exists():
        return False, "docker-compose.yml missing", True
    text = COMPOSE.read_text(encoding="utf-8")
    if "REPLACE_WITH_VERIFIED_DIGEST" in text:
        return False, "LiteLLM digest still a placeholder — pin a real sha256 (upgrade only)", True
    if "litellm@sha256:" not in text:
        return False, "LiteLLM image not pinned by digest in docker-compose.yml", True
    return True, "LiteLLM pinned by immutable digest", True


def main() -> int:
    checks = [
        ("docker", docker_ok()),
        ("uv", uv_ok()),
        ("ollama", ollama_ok()),
        ("ollama models", ollama_models()),
        (".env present", env_present()),
        ("local-only", no_provider_keys()),
        ("litellm digest", digest_pinned()),
    ]
    width = max(len(n) for n, _ in checks)
    blockers = 0
    for name, (ok, detail, is_blocker) in checks:
        if ok:
            mark = "OK  "
        elif is_blocker:
            mark = "FAIL"
            blockers += 1
        else:
            mark = "WARN"
        print(f"  [{mark}] {name:<{width}}  {detail}")

    print()
    print("  ports (listening = already up; free = ready for first boot):")
    env = _env_values()
    for name, port in PORTS:
        state = "in use" if _port_open(port) else "free"
        print(f"      {name:<12} :{port}  {state}")
    if "OLLAMA_API_BASE" in env:
        print(f"\n  OLLAMA_API_BASE (container view) = {env['OLLAMA_API_BASE']}")

    print()
    if blockers:
        print(f"doctor: {blockers} blocker(s) — fix the FAIL lines above, then re-run")
        return 1
    print("doctor: PASS — prerequisites satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
