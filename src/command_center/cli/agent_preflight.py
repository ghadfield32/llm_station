"""cc agent-preflight — Phase 0 of the Claude Agent / Codex Agent chat-integration plan
(see WORKLOG.md "Agent-session chat integration"): a deterministic, evidence-only probe of
whether the Claude Agent SDK / Codex SDK are actually usable in this environment, before any
chat-routing behavior changes. Every check reports PASS / BLOCKED: <reason> / NOT_CONFIGURED
— never a generic "unavailable" (see command-center-wide no-fabricated-metrics discipline).

Read-only: this module makes no network calls, spawns nothing beyond a `--version` probe of
an already-installed binary, and writes nothing. It does not import claude_agent_sdk/
openai_codex at module scope (see growthos-tool-layer pattern) so `cc agent-preflight`
still runs cleanly when neither is installed.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


@dataclass
class Probe:
    check: str
    status: str          # PASS | BLOCKED | NOT_CONFIGURED
    detail: str


def _sdk_probe(check: str, import_name: str, dist_name: str) -> Probe:
    spec = importlib.util.find_spec(import_name)
    if spec is None:
        return Probe(check, "NOT_CONFIGURED",
                     f"`import {import_name}` not found in {sys.executable} — "
                     f"run `pip install {dist_name}` to install it")
    try:
        version = importlib.metadata.version(dist_name)
    except importlib.metadata.PackageNotFoundError:
        version = "unknown (importable but no matching distribution metadata)"
    return Probe(check, "PASS", f"{dist_name} {version} importable from {spec.origin}")


def _cli_probe(check: str, binary: str) -> Probe:
    path = shutil.which(binary)
    if path is None:
        return Probe(check, "NOT_CONFIGURED", f"`{binary}` not found on PATH")
    try:
        result = subprocess.run([path, "--version"], capture_output=True,
                                text=True, timeout=10)
        version = (result.stdout or result.stderr).strip() or "(no version output)"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Probe(check, "BLOCKED", f"{path} found but `--version` failed: {exc!r}")
    return Probe(check, "PASS", f"{path} — {version}")


def _env_key_probe(check: str, key: str) -> Probe:
    from command_center.channels.core import env
    present = bool(env().get(key))
    # presence only — never print the value
    return Probe(check, "PASS" if present else "NOT_CONFIGURED",
                 f"{key} {'is set' if present else 'is not set'} (.env + process, merged)")


def _codex_cli_session_auth_probe() -> Probe:
    """openai-codex's own README documents reusing an existing `codex login` session
    automatically (login_chatgpt / login_chatgpt_device_code / login_api_key are all
    supported) — that session lives under CODEX_HOME (default ~/.codex), not an env var
    check_forbidden_providers inspects. A PASS here means a prior `codex login` exists; it
    does NOT mean OPENAI_API_KEY is set anywhere, and it is the one path that plausibly
    avoids the forbidden-provider wall entirely (see _forbidden_provider_policy_probe)."""
    home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    auth_file = home / "auth.json"
    if auth_file.is_file():
        return Probe("codex_cli_session_auth", "PASS",
                     f"found a prior `codex login` session at {auth_file}")
    return Probe("codex_cli_session_auth", "NOT_CONFIGURED",
                 f"no {auth_file} — run `codex login` on this host to create one")


def _forbidden_provider_policy_probe() -> Probe:
    """Ground truth read directly from check_forbidden_providers.py, not a paraphrase:
    ANTHROPIC_API_KEY / OPENAI_API_KEY are in FORBIDDEN_KEYS and are NEVER exempted by
    --allow-frontier-router-egress (only OPENROUTER_API_KEY/ZAI_API_KEY can be — see
    ROUTER_LANE_KEYS). The Claude Agent SDK requires ANTHROPIC_API_KEY (Anthropic's own
    docs explicitly forbid OAuth/claude.ai-login passthrough for third-party products, so
    there is no way around this for Claude specifically) — meaning it would fail
    `cc validate` today, with no existing flag that helps. This is a real, unresolved
    operator policy decision, not a bug to patch around."""
    from command_center.cli.check_forbidden_providers import FORBIDDEN_KEYS, ROUTER_LANE_KEYS
    never_exemptable = sorted(FORBIDDEN_KEYS - ROUTER_LANE_KEYS)
    return Probe(
        "forbidden_provider_policy", "BLOCKED",
        f"{never_exemptable} are permanently forbidden by check_forbidden_providers.py — "
        f"no existing --allow-* flag exempts them (only {sorted(ROUTER_LANE_KEYS)} can be, "
        f"via --allow-frontier-router-egress). Setting ANTHROPIC_API_KEY for the Claude "
        f"Agent SDK would fail `cc validate` today; a Claude Agent harness needs an "
        f"explicit, separately-gated policy decision before Phase 2, not a code "
        f"workaround. Codex may not hit this wall at all if it authenticates via a reused "
        f"`codex login` CLI session instead of OPENAI_API_KEY — see "
        f"codex_cli_session_auth above.")


def probe_claude() -> list[Probe]:
    return [
        _sdk_probe("claude_sdk_importable", "claude_agent_sdk", "claude-agent-sdk"),
        _cli_probe("claude_cli_installed", "claude"),
        _env_key_probe("claude_api_key_present", "ANTHROPIC_API_KEY"),
    ]


def probe_codex() -> list[Probe]:
    return [
        _sdk_probe("codex_sdk_importable", "openai_codex", "openai-codex"),
        _cli_probe("codex_cli_installed", "codex"),
        _env_key_probe("codex_api_key_present", "OPENAI_API_KEY"),
        _codex_cli_session_auth_probe(),
    ]


def probe_host() -> list[Probe]:
    """Docker detection via /.dockerenv (the standard signal). This CLI command is meant to
    run on the host (`uv run cc agent-preflight`) — a BLOCKED result here means it was run
    from inside a container that does not mount the host's Claude/Codex CLI config
    (~/.claude, ~/.codex, CLAUDE_CONFIG_DIR, CODEX_HOME) by default, per docker-compose.yml."""
    in_container = Path("/.dockerenv").is_file()
    return [Probe(
        "execution_context",
        "BLOCKED" if in_container else "PASS",
        ("running INSIDE a container — the agent-kanban-ui container does not mount "
         "~/.claude, ~/.codex, CLAUDE_CONFIG_DIR, or CODEX_HOME by default; a host-side "
         "worker is the more likely design, not this container calling the SDKs directly"
         if in_container else "running on the host"))]


def run(harness: str) -> dict:
    probes: list[Probe] = list(probe_host())
    if harness in ("all", "claude"):
        probes += probe_claude()
    if harness in ("all", "codex"):
        probes += probe_codex()
    probes.append(_forbidden_provider_policy_probe())
    overall = ("BLOCKED" if any(p.status == "BLOCKED" for p in probes) else
               "NOT_CONFIGURED" if any(p.status == "NOT_CONFIGURED" for p in probes) else
               "PASS")
    return {
        "schema_version": "command-center.agent-preflight.v1",
        "harness": harness,
        "overall": overall,
        "probes": [asdict(p) for p in probes],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evidence-only probe for the Claude/Codex agent-session chat "
                    "integration plan (Phase 0) — never changes chat routing, never "
                    "writes anything.")
    parser.add_argument("--harness", choices=["all", "claude", "codex"], default="all")
    parser.add_argument("--repo", default="",
                        help="unused placeholder for a future per-repo worktree/"
                             "devcontainer check (Phase 1+)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    result = run(args.harness)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"agent-preflight ({args.harness}): {result['overall']}")
        for p in result["probes"]:
            print(f"  [{p['status']:>14}] {p['check']}: {p['detail']}")
    return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
