#!/usr/bin/env python3
"""`cc` — the portable operator interface (no GNU Make, no PowerShell required).

Same operations as the Makefile / scripts/cc.ps1, in one cross-platform command so
you can drive the system with uv on any OS:

    uv run cc doctor              # zero-install: uv syncs the project, then runs
    uv run cc first-boot
    uv run cc validate
    uv run cc up

(or, if the package is already installed, just `cc <command>` / `python -m command_center.cli.main`).

Module tree / flow:
  - python operations  -> run `python -m command_center.<module>` in this interpreter
  - docker lifecycle    -> shell out to `docker compose ...` (identical to the Makefile)
  - composite flows     -> a sequence of the above (e.g. first-boot)
Trailing args after the command are forwarded (e.g. `cc impact a.py b.py`,
`cc gateway --dry-run`, `cc kanban-bridge --apply`). This mirrors the Makefile so the
three interfaces stay behaviorally identical; the Makefile remains the reference.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WHITELIST_DEFAULT = "qwen3:8b"


def run(*cmd: str) -> int:
    """Run a subprocess from the repo root, streaming output. Returns its exit code."""
    return subprocess.run(list(cmd), cwd=ROOT).returncode


def pym(module: str, *args: str) -> int:
    return run(sys.executable, "-m", module, *args)


def compose(*args: str) -> int:
    return run("docker", "compose", *args)


def _whitelist(models_yaml: str) -> list[str]:
    import yaml
    data = yaml.safe_load((ROOT / models_yaml).read_text(encoding="utf-8"))
    return data.get("local_whitelist", [])


# ── python-only operations ────────────────────────────────────────────────
def c_validate(a):
    return (pym("command_center.cli.validate_config") or pym("command_center.cli.check_cross_refs")
            or pym("command_center.registry.render") or pym("command_center.cli.check_forbidden_providers"))


def c_render(a):
    return (pym("command_center.cli.validate_config") or pym("command_center.registry.render")
            or pym("command_center.cli.check_forbidden_providers"))


def c_mission_dryrun(a):
    for tier in ("L0", "L1", "L2", "L3", "L4"):
        rc = pym("command_center.cli.smoke_mission", tier, "demo", "smoke")
        if rc:
            return rc
        print()
    return 0


def c_keys(a):
    return pym("command_center.cli.verify_env", "--mode", "base") or pym("command_center.cli.mint_keys")


# ── docker lifecycle ──────────────────────────────────────────────────────
def c_bootstrap(a):
    rc = pym("command_center.cli.verify_env", "--mode", "base") or c_render(a)
    return rc or compose("up", "-d", "litellm-db", "litellm", "ledger")


def c_up(a):
    rc = pym("command_center.cli.verify_env", "--mode", "full") or c_render(a)
    return rc or compose("up", "-d")


def c_health(a):
    import httpx
    ledger_port = os.environ.get("LEDGER_HOST_PORT", "8091")
    targets = [("litellm", "http://localhost:4000/health/liveliness"),
               ("judge-gate", "http://localhost:8088/health"),
               ("ledger", f"http://localhost:{ledger_port}/health")]
    for name, url in targets:
        try:
            httpx.get(url, timeout=5).raise_for_status()
            print(f"{name:<12} OK")
        except Exception:
            print(f"{name:<12} DOWN")
    return 0


def c_first_boot(a):
    return (pym("command_center.cli.doctor") or c_render(a) or compose("build", "ledger", "judge-gate", "proactive-runner")
            or c_bootstrap(a) or c_keys(a) or c_up(a) or c_health(a))


# ── models ────────────────────────────────────────────────────────────────
def c_models(a):
    rc = c_render(a)
    if rc:
        return rc
    for tag in _whitelist("configs/models.yaml"):
        print(f"ollama pull {tag}")
        run("ollama", "pull", tag)
    return compose("restart", "litellm")


def c_live_smoke(a):
    """Real local-model replies through Ollama/LiteLLM. Bridges to the same script
    the Makefile (bash) and cc.ps1 (powershell) use, picking the right one per OS."""
    if os.name == "nt":
        return run("powershell", "-ExecutionPolicy", "Bypass",
                   "-File", "scripts/live_smoke.ps1", *a)
    return run("bash", "scripts/live_smoke.sh", *a)


def c_models_light(a):
    import yaml
    from command_center.schemas import ModelRegistry
    light = ROOT / "configs" / "models.light.yaml"
    ModelRegistry.model_validate(yaml.safe_load(light.read_text(encoding="utf-8")))
    print("models.light.yaml: VALID")
    for tag in _whitelist("configs/models.light.yaml"):
        print(f"ollama pull {tag}")
        run("ollama", "pull", tag)
    shutil.copyfile(light, ROOT / "configs" / "models.yaml")
    rc = c_render(a)
    print("switched to LIGHT profile. Revert: git checkout configs/models.yaml")
    return rc


# ── appflowy ──────────────────────────────────────────────────────────────
def c_appflowy_up(a):
    af = ROOT / "appflowy_kanban" / "AppFlowy-Cloud"
    gos = ROOT / "appflowy_kanban" / "growth-os"
    rc = subprocess.run(["docker", "compose", "up", "-d"], cwd=af).returncode
    rc = rc or subprocess.run(
        ["docker", "compose", "-f", "docker-compose.curator.yml", "up", "-d", "--build"], cwd=gos).returncode
    print("AppFlowy + curator up. Sign up a user, put creds in growth-os/.env, then setup_workspace.py")
    return rc


# ── UIs and channels (the "one-button" layer) ────────────────────────────
def _ledger_port() -> str:
    return os.environ.get("LEDGER_HOST_PORT", "8091")


def _ui_urls() -> dict[str, str]:
    return {
        "litellm": "http://localhost:4000/ui",
        "ledger": f"http://localhost:{_ledger_port()}/",
        "kuma": "http://localhost:3001",
        "hermes": "http://localhost:9119",   # only if the hermes profile is running
    }


# transport -> (required .env keys, where to create the bot/app, one-line note)
CHANNEL_SETUP = {
    "discord": (["DISCORD_BOT_TOKEN", "DISCORD_ALLOWED_CHANNEL_IDS"],
                "https://discord.com/developers/applications",
                "New Application -> Bot -> Reset Token; enable MESSAGE CONTENT intent; copy a channel ID"),
    "slack": (["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
              "https://api.slack.com/apps",
              "Create app -> enable Socket Mode -> copy the xoxb- bot token + xapp- app token"),
    "telegram": (["TELEGRAM_BOT_TOKEN"],
                 "https://t.me/BotFather",
                 "Message @BotFather -> /newbot -> copy the token"),
    "whatsapp": (["WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_VERIFY_TOKEN"],
                 "https://developers.facebook.com/apps",
                 "Add the WhatsApp product; you also need a public HTTPS webhook (cloudflared/ngrok)"),
}


def _env_has(keys: list[str]) -> list[str]:
    """Return the subset of keys that are missing/blank in .env or the process env."""
    env = {}
    envp = ROOT / ".env"
    if envp.exists():
        for raw in envp.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    return [k for k in keys if not (env.get(k) or os.environ.get(k))]


def _enable_channel(transport: str) -> bool:
    """Flip `enabled: true` for the first channel of this transport in channels.yaml,
    preserving comments/formatting (line edit, not a yaml re-dump). Returns True if changed."""
    path = ROOT / "configs" / "channels.yaml"
    lines = path.read_text(encoding="utf-8").splitlines()
    cur_transport = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("- name:"):
            cur_transport = None
        elif s.startswith("transport:"):
            cur_transport = s.split(":", 1)[1].strip()
        elif s.startswith("enabled:") and cur_transport == transport:
            if "true" not in s:
                lines[i] = line[: line.index("enabled:")] + "enabled: true"
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return True
            return False
    return False


def c_open(a):
    import webbrowser
    urls = _ui_urls()
    targets = a if a else ["litellm", "ledger", "kuma"]
    print("opening UIs (also reachable at these URLs over Tailscale):")
    for t in targets:
        url = urls.get(t)
        if not url:
            print(f"  unknown UI '{t}' (known: {', '.join(urls)})")
            continue
        print(f"  {t:<8} {url}")
        try:
            webbrowser.open(url)
        except Exception:
            pass  # headless/SSH: the URL is printed above
    return 0


def c_channel(a):
    if not a:
        print(f"usage: cc channel <{ '|'.join(CHANNEL_SETUP) }>")
        return 2
    name = a[0]
    spec = CHANNEL_SETUP.get(name)
    if spec is None:
        print(f"cc channel: unknown '{name}' (known: {', '.join(CHANNEL_SETUP)})")
        return 2
    keys, url, note = spec
    missing = _env_has(keys)
    if missing:
        import webbrowser
        print(f"{name}: needs token(s) you create on the platform first.")
        print(f"  1. open {url}")
        print(f"     {note}")
        print(f"  2. put these into .env: {', '.join(missing)}")
        print(f"  3. re-run: cc channel {name}")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        return 1
    changed = _enable_channel(name)
    print(f"{name}: tokens present; channel {'enabled' if changed else 'already enabled'} in configs/channels.yaml")
    rc = pym("command_center.cli.validate_config")
    if rc:
        return rc
    print(f"launching {name} (Ctrl-C to stop)...")
    return pym("command_center.channels", "--channels", name)


def c_start(a):
    """One button: control plane up, optionally AppFlowy + a favorite channel, then open the UIs.
       cc start [--appflowy] [--channel NAME] [--hermes]"""
    want_appflowy = "--appflowy" in a
    want_hermes = "--hermes" in a
    channel = None
    if "--channel" in a:
        idx = a.index("--channel")
        if idx + 1 < len(a):
            channel = a[idx + 1]

    rc = c_first_boot([])
    if rc:
        return rc
    if want_hermes:
        print("starting Hermes (profile) — note: set a real hermes image in docker-compose.yml first")
        compose("--profile", "hermes", "up", "-d")
    if want_appflowy:
        pym("command_center.cli.appflowy_init")
        c_appflowy_up([])
    if channel:
        rc = c_channel([channel])  # guided: sets up + launches, or prints the token steps
    c_open(["litellm", "ledger", "kuma"] + (["hermes"] if want_hermes else []))
    print("\nstart complete. Run a channel anytime with: cc channel <name>  (or: cc gateway)")
    return 0


# name -> (handler, help). Single source for dispatch + `cc help`.
COMMANDS: dict[str, tuple] = {
    # config
    "validate": (c_validate, "configs match contracts + cross-refs + render + provider boundary"),
    "render": (c_render, "validate + render generated/litellm-config.yaml"),
    "schema": (lambda a: pym("command_center.cli.render_json_schema"), "contracts -> generated/json-schema"),
    "impact": (lambda a: pym("command_center.cli.impact", *a), "blast radius of your git diff"),
    "mission-dryrun": (c_mission_dryrun, "fake L0..L4 missions through gates+judges"),
    "evals": (lambda a: pym("command_center.cli.run_evals"), "routing/judge regression suite"),
    "forbidden-providers": (lambda a: pym("command_center.cli.check_forbidden_providers"), "local-only boundary"),
    # lifecycle
    "doctor": (lambda a: pym("command_center.cli.doctor", *a), "preflight checklist"),
    "setup": (lambda a: pym("command_center.cli.setup", *a),
              "friendly readiness: doctor + registry summary + next steps"),
    "onboard": (lambda a: pym("command_center.cli.onboard", *a),
                "friendly: onboard repo|kanban (dry-run + verify; --apply writes)"),
    "init-env": (lambda a: pym("command_center.cli.init_env"), "create .env with local secrets"),
    "verify-base": (lambda a: pym("command_center.cli.verify_env", "--mode", "base"), "pre-bootstrap checks"),
    "verify": (lambda a: pym("command_center.cli.verify_env", "--mode", "full"), "pre-up checks"),
    "bootstrap": (c_bootstrap, "first boot: litellm-db + litellm + ledger"),
    "bootstrap-local": (c_bootstrap, "local bootstrap: render + start litellm-db, litellm, ledger"),
    "verify-stack": (lambda a: pym("command_center.cli.doctor", *a), "full readiness doctor"),
    "keys": (c_keys, "mint virtual keys and write them into .env"),
    "up": (c_up, "verify + render + start the control plane"),
    "down": (lambda a: compose("down"), "stop the stack"),
    "health": (c_health, "check service health endpoints"),
    "first-boot": (c_first_boot, "one shot: doctor -> build -> bootstrap -> keys -> up -> health"),
    "live-smoke": (c_live_smoke, "real local model replies through Ollama/LiteLLM"),
    "logs": (lambda a: compose("logs", "-f"), "tail all logs"),
    # models
    "models": (c_models, "render + pull whitelisted local tags + restart litellm"),
    "models-light": (c_models_light, "switch to the small-GPU/CPU profile (qwen3:8b)"),
    "model-scout": (lambda a: pym("command_center.registry.model_scout", "--output",
                                  "generated/model-scout-report.md", *a), "propose model candidates"),
    "usage-digest": (lambda a: pym("command_center.cli.usage_digest", "--output",
                                   "generated/usage-digest.md", *a), "spend + mission summary"),
    # channels
    "gateway": (lambda a: pym("command_center.channels", *a), "run enabled chat channels (configs/channels.yaml)"),
    "notify": (lambda a: pym("command_center.cli.notify", *a), "push a proactive digest (brief + active missions) to Discord (--dry-run)"),
    "kanban-bridge": (lambda a: pym("command_center.cli.kanban_bridge", *a), "AppFlowy cards -> Ledger missions"),
    "kanban-verify": (lambda a: pym("command_center.cli.kanban_registry", "verify", *a),
                      "verify a registered kanban board's status/field/verb contract (no writes)"),
    "kanban-register": (lambda a: pym("command_center.cli.kanban_registry", "register", *a),
                        "register a kanban board (AppFlowy or internal UI) into the registry (--apply to write)"),
    "kanban-sync": (lambda a: pym("command_center.cli.kanban_registry", "sync", *a),
                    "dry-run plan of registry boards -> repos/status mapping (no writes)"),
    "kanban-emit": (lambda a: pym("command_center.cli.kanban_sync_ops", "emit", *a),
                    "governed: record a kanban action as one event (wall actions rejected)"),
    "kanban-project": (lambda a: pym("command_center.cli.kanban_sync_ops", "project", *a),
                       "fold the event log into current card state (source of truth)"),
    "kanban-verify-projection": (lambda a: pym("command_center.cli.kanban_sync_ops", "verify", *a),
                                 "compare a surface snapshot to the event log (DEGRADED if absent)"),
    "kanban-reconcile": (lambda a: pym("command_center.cli.kanban_sync_ops", "reconcile", *a),
                         "detect drift vs conflict (review_required); --apply repairs drift only"),
    "operate": (lambda a: pym("command_center.cli.operate", *a),
                "high-level operator wrapper: operate verify --all (boards + repos)"),
    "repo-register": (lambda a: pym("command_center.cli.repo_registry", "register", *a),
                      "register another local repo (disabled, dry-run by default; --apply writes)"),
    "repo-verify": (lambda a: pym("command_center.cli.repo_registry", "verify", *a),
                    "verify a repo's autonomy gates (devcontainer/CI/app/branch-protection/board/evidence)"),
    "repo-enable-autonomy": (lambda a: pym("command_center.cli.repo_registry", "enable-autonomy", *a),
                             "flip autonomous_edits_enabled only if every gate passes (--apply)"),
    "repo-merge-guard": (lambda a: pym("command_center.cli.merge_guard", *a),
                         "install/verify the local pre-push merge guard (local_pre_push_and_human_merge posture)"),
    "memory-add": (lambda a: pym("command_center.cli.memory_ops", "add", *a),
                   "add a durable memory (pending until --approved-by; secrets rejected)"),
    "memory-review": (lambda a: pym("command_center.cli.memory_ops", "review", *a),
                      "list memories: approved/pending/stale, with provenance"),
    "memory-prune": (lambda a: pym("command_center.cli.memory_ops", "prune", *a),
                     "detect/remove stale memories per each record's retention_policy (--apply)"),
    "memory-verify": (lambda a: pym("command_center.cli.memory_ops", "verify", *a),
                      "integrity: provenance present, confidential redacted, no duplicates"),
    "self-improvement-scan": (lambda a: pym("command_center.cli.self_improvement", "scan", *a),
                              "observer scan: rank findings, would-draft Proposed cards (zero writes)"),
    "self-improvement-daily": (lambda a: pym("command_center.cli.self_improvement", "daily", *a),
                               "daily observer/draft-only loop: --draft-kanban true drafts Proposed cards; never applies code"),
    "self-improvement-report": (lambda a: pym("command_center.cli.self_improvement", "report", *a),
                                "write the decision-grade self-improvement report (no cards drafted)"),
    "improve": (lambda a: pym("command_center.cli.self_improvement", "daily", *a),
                "friendly alias for self-improvement-daily (observer/draft-only)"),
    "demo": (lambda a: pym("command_center.cli.demo", *a),
             "full-loop demo: verify board+repo and document the 14-step loop (no writes, no merge)"),
    "linkedin-publish": (lambda a: pym("command_center.cli.linkedin_publish", *a), "publish approved+due LinkedIn content rows (--login | --apply)"),
    "system-validation": (lambda a: pym("command_center.cli.system_validation", *a),
                          "write whole-system validation evidence from real config state"),
    "github-app-verify": (lambda a: pym("command_center.cli.github_app_verify", *a),
                          "observer-only GitHub App installation and permission verification"),
    "branch-protection-verify": (lambda a: pym("command_center.cli.branch_protection_verify", *a),
                                 "observer-only owner/admin branch protection verification"),
    "branch-mission": (lambda a: pym("command_center.cli.branch_mission", *a),
                       "bounded local branch/worktree docs-only mission evidence; no push/PR/merge"),
    "pr-check-verify": (lambda a: pym("command_center.cli.pr_check_verify", *a),
                        "live PR check-evidence loop: create feature branch + draft PR + poll required checks"),
    "agent-validation": (lambda a: pym("command_center.cli.agent_validation", *a),
                         "live read-only agent tool, memory, and multi-turn validation"),
    "desktop-target-verify": (lambda a: pym("command_center.cli.desktop_target_verify", *a),
                              "observer-only desktop target snapshot verification"),
    "desktop-adapter": (lambda a: pym("command_center.cli.desktop_adapter", *a),
                        "desktop adapter manifest readiness gate"),
    "desktop-noop-canary": (lambda a: pym("command_center.cli.desktop_noop_canary", *a),
                            "read-only desktop/browser canary timing evidence; no live actions"),
    "desktop-action-canary": (lambda a: pym("command_center.cli.desktop_action_canary", *a),
                              "representative action-latency: reversible sandbox direct_api round-trip; fail-closed; no production board"),
    "desktop-timing-derive": (lambda a: pym("command_center.cli.desktop_timing_derive", *a),
                              "derive desktop timing candidates from measured action-latency evidence (read-only is observation only)"),
    # appflowy
    "appflowy-init": (lambda a: pym("command_center.cli.appflowy_init"), "scaffold AppFlowy + growth-os .env"),
    "appflowy-up": (c_appflowy_up, "start the AppFlowy board server + curator"),
    # one-button + UIs + channels
    "start": (c_start, "ONE BUTTON: first-boot [+--appflowy] [+--channel NAME] [+--hermes], then open UIs"),
    "open": (c_open, "open the UIs in your browser (litellm/ledger/kuma[/hermes])"),
    "channel": (c_channel, "guided favorite-channel setup: cc channel <discord|slack|telegram|whatsapp>"),
    # dev
    "lint": (lambda a: run(sys.executable, "-m", "ruff", "check", "src"), "ruff check src"),
    "test": (lambda a: run(sys.executable, "-m", "pytest", *a), "run the test suite"),
}


def print_help() -> None:
    print("cc — portable operator interface (uv run cc <command> [args])\n")
    width = max(len(n) for n in COMMANDS)
    for name, (_, desc) in COMMANDS.items():
        print(f"  {name:<{width}}  {desc}")


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("help", "-h", "--help"):
        print_help()
        return 0
    name, rest = args[0], args[1:]
    entry = COMMANDS.get(name)
    if entry is None:
        print(f"cc: unknown command '{name}'. Run `cc help`.", file=sys.stderr)
        return 2
    return entry[0](rest) or 0


if __name__ == "__main__":
    raise SystemExit(main())
