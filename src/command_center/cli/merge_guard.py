"""Local merge guard: a pre-push hook that blocks direct pushes to protected
branches on THIS machine.

This is the local-posture merge wall's *belt*. The primary wall against the agent
is structural and global (the action layer has no merge verb; the kanban contract
forbids `merge`; direct main pushes are refused) — this hook additionally stops a
local `git push` to a protected branch (e.g. a stray script or a human slip). It
is LOWER ASSURANCE than a GitHub ruleset (no server-side backstop; bypassable with
`--no-verify` or a token from elsewhere), and is recorded as such — never as
"branch protection verified".

  cc repo-merge-guard install --repo-id betts_basketball
  cc repo-merge-guard verify  --repo-id betts_basketball
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from command_center.schemas import AutonomyConfig

ROOT = Path(__file__).resolve().parents[3]
AUTONOMY = "configs/autonomy.yaml"
GUARD_MARKER = "command-center-local-merge-guard-v1"


def guard_hook(protected_branches: list[str]) -> str:
    """Render the pre-push hook that rejects pushes to the protected branches."""
    cases = "\n".join(
        f"    refs/heads/{b})\n"
        f"      echo \"merge-guard: direct push to {b} is blocked — open a PR and "
        f"merge after human review.\" >&2 ; exit 1 ;;"
        for b in protected_branches
    )
    return (
        "#!/bin/sh\n"
        f"# {GUARD_MARKER}\n"
        "# Installed by `cc repo-merge-guard`. The agent is PR-only; this is a\n"
        "# local belt that blocks direct pushes to protected branches.\n"
        "while read -r local_ref local_sha remote_ref remote_sha; do\n"
        "  case \"$remote_ref\" in\n"
        f"{cases}\n"
        "  esac\n"
        "done\n"
        "exit 0\n"
    )


def _hook_path(repo_root: Path) -> Path:
    return repo_root / ".git" / "hooks" / "pre-push"


def verify_guard(repo_root: Path | None) -> tuple[bool, str]:
    """True iff the merge guard is installed in repo_root's git hooks."""
    if repo_root is None:
        return False, "repo_path_unresolved"
    if not (repo_root / ".git").exists():
        return False, f"not_a_git_repo:{repo_root}"
    hook = _hook_path(repo_root)
    if not hook.is_file():
        return False, "pre_push_hook_absent"
    text = hook.read_text(encoding="utf-8", errors="replace")
    if GUARD_MARKER not in text:
        return False, "pre_push_hook_present_but_not_merge_guard"
    return True, f"merge_guard_installed:{hook}"


def _resolve_repo_root(repo, env: dict[str, str]) -> Path | None:
    ref = repo.local_path_ref
    if ref == "self":
        return ROOT
    if ref and ref.startswith("env:") and env.get(ref.split(":", 1)[1]):
        return Path(env[ref.split(":", 1)[1]])
    return None


def install_guard(*, repo_id: str, config_path: Path = ROOT / AUTONOMY,
                  env: dict[str, str] | None = None) -> dict[str, Any]:
    env = env if env is not None else {}
    cfg = AutonomyConfig.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")))
    repo = next((r for r in cfg.repo_manifests if r.repo_id == repo_id), None)
    if repo is None:
        return {"status": "blocked", "blockers": [f"repo_not_registered_{repo_id}"]}
    repo_root = _resolve_repo_root(repo, env)
    if repo_root is None or not (repo_root / ".git").is_dir():
        return {"status": "blocked",
                "blockers": [f"repo_local_path_unresolved_or_not_git_{repo_id}"]}
    hook = _hook_path(repo_root)
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(guard_hook(repo.protected_branches), encoding="utf-8")
    hook.chmod(0o755)
    ok, detail = verify_guard(repo_root)
    return {"status": "installed" if ok else "blocked", "repo_id": repo_id,
            "protected_branches": repo.protected_branches, "hook_path": str(hook),
            "verify": detail}


def main() -> int:
    parser = argparse.ArgumentParser(prog="repo-merge-guard")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("install", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--repo-id", required=True)
    args = parser.parse_args()
    from command_center.cli.github_app_verify import _merged_env, _read_dotenv
    env = _merged_env(_read_dotenv(ROOT / ".env"))
    cfg = AutonomyConfig.model_validate(
        yaml.safe_load((ROOT / AUTONOMY).read_text(encoding="utf-8")))
    repo = next((r for r in cfg.repo_manifests if r.repo_id == args.repo_id), None)

    if args.cmd == "install":
        res = install_guard(repo_id=args.repo_id, env=env)
        print(f"repo-merge-guard install: {res['status'].upper()}")
        for b in res.get("blockers", []):
            print(f"  BLOCKED: {b}")
        if res.get("hook_path"):
            print(f"  hook: {res['hook_path']} (blocks {res.get('protected_branches')})")
        return 0 if res["status"] == "installed" else 1

    if args.cmd == "verify":
        root = _resolve_repo_root(repo, env) if repo else None
        ok, detail = verify_guard(root)
        print(f"repo-merge-guard verify: {'PASS' if ok else 'BLOCKED'}  {detail}")
        return 0 if ok else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
