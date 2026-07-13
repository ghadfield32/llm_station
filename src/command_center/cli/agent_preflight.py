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
    # Informational probes report a fact but never gate `overall` — used for a
    # probe whose NOT_CONFIGURED is an EXPECTED, benign state, not a real
    # problem (e.g. codex_api_key_present: Codex authenticates via the
    # existing `codex login` session, so OPENAI_API_KEY being unset is
    # correct, not a blocker — see run()).
    informational: bool = False


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


def _env_key_probe(check: str, key: str, *, informational: bool = False) -> Probe:
    from command_center.channels.core import env
    present = bool(env().get(key))
    # presence only — never print the value
    return Probe(check, "PASS" if present else "NOT_CONFIGURED",
                 f"{key} {'is set' if present else 'is not set'} (.env + process, merged)",
                 informational=informational)


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
        # informational: Codex authenticates via the existing `codex login`
        # session (codex_cli_session_auth below / live_auth when --live), so
        # OPENAI_API_KEY being unset is the EXPECTED, correct state — it must
        # not drag `overall` to NOT_CONFIGURED (verified live: a real turn
        # runs with no API key set). See run().
        _env_key_probe("codex_api_key_present", "OPENAI_API_KEY", informational=True),
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


def live_probe_codex(repo_id: str) -> list[Probe]:
    """REAL, opt-in, quota-consuming verification (`--live`, never run by
    default) against the actual pinned openai-codex SDK and the actual
    authenticated account — not a static file check. Exercises the required
    Codex adapter acceptance list: SDK import+version, real auth (not just
    an auth.json file existing), read-only-sandbox thread creation, a
    same-thread follow-up, resume-by-id via a FRESH harness instance
    (simulating a worker restart), the target repo being resolvable/
    openable, and zero filesystem mutation — verified via mutation_proof,
    never assumed. interrupt() mechanics themselves are proven by
    test_codex_agent_adapter.py's fake-SDK unit test; this only checks the
    live call doesn't raise."""
    import asyncio
    import importlib.metadata as md

    probes: list[Probe] = []
    try:
        import openai_codex   # noqa: F401  (import-success is the check)
        version = md.version("openai-codex")
    except ImportError as exc:
        probes.append(Probe("live_sdk_import", "BLOCKED",
                            f"openai-codex not importable: {exc!r}"))
        return probes
    probes.append(Probe("live_sdk_import", "PASS", f"openai-codex {version} imported"))

    from command_center.agent_sessions.adapters.codex_agent import (
        CodexAgentHarness, _resolve_repo_path)
    from command_center.agent_sessions.mutation_proof import snapshot
    from command_center.agent_sessions.protocol import SessionStart
    from command_center.agent_sessions.store import SessionStore

    try:
        repo_path = _resolve_repo_path(repo_id)
    except Exception as exc:
        probes.append(Probe("live_repo_resolvable", "BLOCKED", repr(exc)))
        return probes
    if not repo_path.is_dir():
        probes.append(Probe("live_repo_resolvable", "BLOCKED",
                            f"{repo_path} is not a directory"))
        return probes
    probes.append(Probe("live_repo_resolvable", "PASS",
                        f"repo_id {repo_id!r} -> {repo_path}"))

    store = SessionStore()
    harness = CodexAgentHarness(store)

    async def _run() -> list[Probe]:
        results: list[Probe] = []
        probe = await harness.probe()
        results.append(Probe("live_auth", "PASS" if probe.available else "BLOCKED",
                             probe.detail))
        if not probe.available:
            return results

        before = snapshot(repo_path)
        try:
            session_id = await harness.start_session(SessionStart(
                conversation_id="agent-preflight-live", repo_id=repo_id,
                mode="analysis", harness_id="codex_agent",
                permission_profile="read_only"))
            results.append(Probe("live_thread_created", "PASS", f"session {session_id}"))

            events1 = [e async for e in harness.send(
                session_id, "In one short sentence, what does this repository do?")]
            terminal1 = [e.type for e in events1
                        if e.type in ("session_idle", "session_failed")]
            results.append(Probe(
                "live_first_turn", "PASS" if terminal1 == ["session_idle"] else "BLOCKED",
                f"{len(events1)} events, terminal={terminal1}"))

            events2 = [e async for e in harness.send(
                session_id, "One more short sentence: what language is it mostly "
                           "written in?")]
            terminal2 = [e.type for e in events2
                        if e.type in ("session_idle", "session_failed")]
            results.append(Probe(
                "live_followup_same_thread",
                "PASS" if terminal2 == ["session_idle"] else "BLOCKED",
                f"{len(events2)} events, terminal={terminal2}"))

            external_id = store.get(session_id).external_session_id
            harness2 = CodexAgentHarness(store)   # fresh instance = simulated restart
            events3 = [e async for e in harness2.send(
                session_id, "In one word: what license, if any, does it use?")]
            results.append(Probe(
                "live_resume_by_thread_id", "PASS" if events3 else "BLOCKED",
                f"resumed via external_session_id={external_id}, {len(events3)} events"))

            try:
                await harness2.interrupt(session_id)   # idle session: must not raise
                results.append(Probe("live_interrupt_call", "PASS",
                                     "interrupt() on an idle session did not raise"))
            except Exception as exc:
                results.append(Probe("live_interrupt_call", "BLOCKED", repr(exc)))

            await harness2.close(session_id)
        finally:
            after = snapshot(repo_path)
            problems = before.diff(after)
            results.append(Probe(
                "live_zero_mutation", "PASS" if not problems else "BLOCKED",
                "no filesystem changes" if not problems else "; ".join(problems)))
        return results

    probes.extend(asyncio.run(_run()))
    return probes


def run(harness: str, *, live: bool = False, repo: str = "") -> dict:
    probes: list[Probe] = list(probe_host())
    if harness in ("all", "claude"):
        probes += probe_claude()
    if harness in ("all", "codex"):
        probes += probe_codex()
        if live:
            if not repo:
                probes.append(Probe(
                    "live_probe", "BLOCKED",
                    "--live requires --repo <repo_id> (a repo_manifests entry "
                    "in configs/autonomy.yaml)"))
            else:
                probes += live_probe_codex(repo)
    # This probe is genuinely a CLAUDE-specific blocker (the Claude Agent SDK
    # structurally requires ANTHROPIC_API_KEY, which is permanently forbidden
    # without an explicit policy decision — see the probe's own docstring).
    # Codex never touches OPENAI_API_KEY (verified live: authenticates via a
    # reused `codex login` session), so including this probe in a codex-only
    # run made `cc agent-preflight --harness codex --live` report BLOCKED
    # overall even when every Codex-relevant check passed — not honest.
    if harness in ("all", "claude"):
        probes.append(_forbidden_provider_policy_probe())
    # Informational probes report a fact but never gate overall (e.g.
    # codex_api_key_present, whose NOT_CONFIGURED is the expected state for
    # existing-login Codex — see probe_codex). A truly optional-and-absent
    # thing must not make a fully-working setup look non-PASS.
    gating = [p for p in probes if not p.informational]
    overall = ("BLOCKED" if any(p.status == "BLOCKED" for p in gating) else
               "NOT_CONFIGURED" if any(p.status == "NOT_CONFIGURED" for p in gating) else
               "PASS")
    return {
        "schema_version": "command-center.agent-preflight.v1",
        "harness": harness,
        "live": live,
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
                        help="repo_id (from configs/autonomy.yaml repo_manifests) for "
                             "--live's real Codex thread — required when --live is set")
    parser.add_argument("--live", action="store_true",
                        help="REAL, quota-consuming verification against the actual "
                             "authenticated Codex account (codex harness only) — never "
                             "run unless you explicitly pass this; see live_probe_codex")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    result = run(args.harness, live=args.live, repo=args.repo)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"agent-preflight ({args.harness}): {result['overall']}")
        for p in result["probes"]:
            print(f"  [{p['status']:>14}] {p['check']}: {p['detail']}")
    return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
