"""Friendly operator wrapper: onboard a repo or a kanban board.

Thin sugar over the lower-level evidence commands — it infers sensible defaults
(repo id from the path, remote URL from the repo's git origin, board id from the
repo id) and then runs the same `repo-register`/`kanban-register` + verify the
detailed commands run. It writes nothing unless `--apply` is passed; the gate
checklist from `*-verify` is printed so the operator sees exactly what blocks.

  cc onboard repo --path C:/docker_projects/my_repo
  cc onboard repo --path C:/docker_projects/my_repo --apply
  cc onboard kanban --provider command_center_ui --repo my_repo
  cc onboard kanban --provider appflowy --repo my_repo \
      --workspace-ref env:APPFLOWY_WORKSPACE_ID --board-ref env:MY_REPO_BOARD_ID
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

from command_center.cli.kanban_registry import run_kanban_register, run_kanban_verify
from command_center.cli.repo_loop_proof import run_repo_loop_proof
from command_center.cli.repo_registry import (
    RUN_ID_DIR, run_repo_register, run_repo_verify,
)

ROOT = Path(__file__).resolve().parents[3]

# Onboarding modes -> the manifest's risk_ceiling (the max autonomy the repo may
# reach). Repos cannot exceed L2. "pr-autonomy" shares L2 with "local-edits" —
# the PR/no-merge boundary is the always-on branch_write_policy + merge wall, not
# a separate tier — but it is the only mode that opens PRs, so it is the one that
# needs the live PR-check loop proof (pr_check_evidence_proven).
MODE_RISK = {
    "observe-only": "L0_read_only",
    "local-edits": "L2_local_edits",
    "pr-autonomy": "L2_local_edits",
}

# gate check name -> one-line remediation the operator can act on.
REMEDIATION = {
    "devcontainer_present": "add .devcontainer/devcontainer.json to the repo",
    "ci_commands_declared": "declare ci_commands in the repo manifest (autonomy.yaml)",
    "codeowners_present": "add .github/CODEOWNERS to the repo",
    "kanban_board_mapping": "register the board (cc kanban-register) and list this "
                            "repo in its repo_ids",
    "local_path_ref_resolves": "set <REPO>_LOCAL_PATH=<abs path> in .env (not committed)",
    "github_app_installed": "install the GitHub App on this repo (see cc github-app-verify)",
    "merge_wall_verified": "verify branch protection, or install the local guard: "
                           "cc repo-merge-guard --repo-id <id> --apply",
    "no_runtime_secrets_in_container": "set secret_policy: no_runtime_secrets_inside_container",
    "pr_check_evidence_proven": "run the live PR loop proof: cc repo-loop-proof "
                                "--repo-id <id> --apply  (pr-autonomy mode runs this for you)",
    "branch_mission_proven": "run cc branch-mission (self/control repo only)",
}


def _git_origin(path: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(path), "remote", "get-url", "origin"],
                             capture_output=True, text=True)
    except FileNotFoundError:
        return None
    url = out.stdout.strip()
    return url or None


def _print_verify(label: str, result: dict[str, Any]) -> None:
    print(f"{label}: {str(result.get('status', '?')).upper()}")
    for b in result.get("blockers", []):
        print(f"  BLOCKED: {b}")
    if result.get("next"):
        print(f"  next: {result['next']}")


def _walk_gates(ver: dict[str, Any]) -> list[str]:
    """Print every gate in order (PASS/BLOCKED + remediation), return the blockers."""
    print("  gate walkthrough:")
    for g in ver.get("gates", []):
        name, status = g.get("check"), g.get("status", "?")
        if status == "PASS":
            print(f"    PASS    {name}")
        else:
            hint = REMEDIATION.get(name, "")
            print(f"    BLOCKED {name}" + (f" — {hint}" if hint else ""))
    return list(ver.get("blockers", []))


def _onboard_repo(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser()
    repo_id = args.repo_id or path.name
    board = args.kanban_board or f"{repo_id}_command_center"
    # Defensive defaults so any caller (and older callers) get the safe posture.
    mode = getattr(args, "mode", "observe-only")
    no_loop_proof = getattr(args, "no_loop_proof", False)
    remote = args.remote_url or _git_origin(path)
    if not remote:
        print("onboard repo: BLOCKED\n  no --remote-url given and the path has no "
              "git 'origin' remote — pass --remote-url explicitly")
        return 1
    print(f"onboard repo: repo_id={repo_id} board={board} mode={mode} "
          f"(risk_ceiling={MODE_RISK[mode]})")
    print(f"  path={path}  remote={remote}")
    reg = run_repo_register(repo_id=repo_id, local_path=str(path), remote_url=remote,
                            kanban_board=board, apply=args.apply, root=ROOT,
                            risk_ceiling=MODE_RISK[mode])
    _print_verify("  register", reg)
    if reg.get("status") == "blocked":
        return 1

    # verify against the real merged env so the gate checklist is accurate (the
    # local-path ref + GitHub App + branch-protection gates read env/creds — an
    # empty env would under-report them as failures).
    from command_center.cli.github_app_verify import _merged_env, _read_dotenv
    env = _merged_env(_read_dotenv(ROOT / ".env"))
    ver = run_repo_verify(repo_id=repo_id, root=ROOT, env=env)
    blockers = _walk_gates(ver)

    # pr-autonomy is the only mode that opens PRs, so it is the one that needs the
    # live PR-check loop. If that is the binding gap and its prerequisites pass,
    # run the bounded loop proof automatically (writes evidence where verify reads
    # it), then re-verify. observe-only / local-edits never auto-open a PR.
    if (mode == "pr-autonomy" and args.apply and not no_loop_proof
            and "pr_check_evidence_proven" in blockers
            and "github_app_installed" not in blockers):
        out = ROOT / RUN_ID_DIR / repo_id / "pr-check-loop.json"
        print(f"\n  pr-autonomy: pr_check_evidence_proven is the gap — running the "
              f"live PR loop proof (writes {out.relative_to(ROOT)}) ...")
        proof = run_repo_loop_proof(repo_id=repo_id, root=ROOT, output=out, apply=True)
        _print_verify("  loop-proof", proof)
        if proof.get("status") == "pass":
            ver = run_repo_verify(repo_id=repo_id, root=ROOT, env=env)
            blockers = _walk_gates(ver)

    if blockers:
        print(f"\n  STOP: {len(blockers)} blocker(s) remain — fix the BLOCKED gates "
              f"above, then re-run. autonomy stays DISABLED.")
        return 1
    print(f"\n  all gates PASS. enable when ready: "
          f"cc repo-enable-autonomy --repo-id {repo_id} --apply")
    return 0


def _onboard_kanban(args: argparse.Namespace) -> int:
    board_id = args.board_id or f"{args.repo}_command_center"
    workspace_ref = args.workspace_ref or (
        "self" if args.provider == "command_center_ui" else None)
    board_ref = args.board_ref or (board_id if args.provider == "command_center_ui" else None)
    if workspace_ref is None or board_ref is None:
        print("onboard kanban: BLOCKED\n  appflowy boards need --workspace-ref env:NAME "
              "and --board-ref env:NAME (no literal ids committed)")
        return 1
    print(f"onboard kanban: board_id={board_id} provider={args.provider} repo={args.repo}")
    reg = run_kanban_register(board_id=board_id, provider=args.provider,
                              workspace_ref=workspace_ref, board_ref=board_ref,
                              repo_ids=[args.repo], apply=args.apply)
    _print_verify("  register", reg)
    if reg.get("status") == "blocked":
        return 1
    ver = run_kanban_verify(config_path=ROOT / "configs/kanban_boards.yaml", board_id=board_id)
    _print_verify("  verify", ver)
    return 0 if ver.get("status") == "pass" else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="onboard")
    sub = parser.add_subparsers(dest="what", required=True)

    pr = sub.add_parser("repo")
    pr.add_argument("--path", required=True)
    pr.add_argument("--repo-id", default="")
    pr.add_argument("--remote-url", default="")
    pr.add_argument("--kanban-board", default="")
    pr.add_argument("--mode", choices=list(MODE_RISK), default="observe-only",
                    help="autonomy posture to register (default: observe-only)")
    pr.add_argument("--no-loop-proof", action="store_true",
                    help="pr-autonomy: do NOT auto-run the live PR loop proof")
    pr.add_argument("--apply", action="store_true")

    pk = sub.add_parser("kanban")
    pk.add_argument("--provider", required=True,
                    choices=["appflowy", "command_center_ui"])
    pk.add_argument("--repo", required=True)
    pk.add_argument("--board-id", default="")
    pk.add_argument("--workspace-ref", default="")
    pk.add_argument("--board-ref", default="")
    pk.add_argument("--apply", action="store_true")

    args = parser.parse_args()
    if args.what == "repo":
        return _onboard_repo(args)
    if args.what == "kanban":
        return _onboard_kanban(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
