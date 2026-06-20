"""High-level operator command: aggregate the verification surfaces.

A friendly wrapper so operators don't memorize every low-level command. The
detailed commands (cc kanban-verify, repo-verify, kanban-reconcile, …) stay
available for evidence/debugging.

  cc operate verify --all
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from command_center.cli.kanban_registry import run_kanban_verify
from command_center.cli.repo_registry import run_repo_verify

ROOT = Path(__file__).resolve().parents[3]


def operate_verify_all(
    *, root: Path = ROOT, env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Aggregate verify across every board + repo (read-only)."""
    env = env if env is not None else {}
    boards = run_kanban_verify(config_path=root / "configs/kanban_boards.yaml")
    repos = run_repo_verify(all_repos=True, config_path=root / "configs/autonomy.yaml",
                            root=root, env=env)
    blockers = ([f"board:{b}" for b in boards["blockers"]]
                + [f"repo:{b}" for b in repos["blockers"]])
    return {
        "status": "pass" if not blockers else "blocked",
        "boards_verified": boards["boards_verified"],
        "boards_status": boards["status"],
        "repos_verified": repos["repos_verified"],
        "repos_status": repos["status"],
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="operate")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pv = sub.add_parser("verify")
    pv.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if args.cmd != "verify":
        return 2

    from command_center.cli.github_app_verify import _merged_env, _read_dotenv
    env = _merged_env(_read_dotenv(ROOT / ".env"))
    result = operate_verify_all(env=env)
    print(f"operate verify: {result['status'].upper()}")
    print(f"  boards ({result['boards_status']}): {result['boards_verified']}")
    print(f"  repos  ({result['repos_status']}): {result['repos_verified']}")
    for b in result["blockers"]:
        print(f"  BLOCKED: {b}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
