"""Repo registration + autonomy-gate operations: verify / register / enable.

Onboards additional local repos under the same safety contract as llm_station.
A repo manifest (in configs/autonomy.yaml) binds a repo to a kanban board and the
branch/worktree/devcontainer/PR loop. Autonomy stays OFF until every gate passes:
manifest valid, devcontainer present, CI commands declared, GitHub App installed
for the repo, branch protection verified, CODEOWNERS present, board mapping
verified, and the bounded branch-mission + live PR check-evidence loops proven.

  cc repo-verify [--repo-id <id> | --all]
  cc repo-register --repo-id <id> --local-path <path> --remote-url <url> \
      --kanban-board <board_id> [--apply]
  cc repo-enable-autonomy --repo-id <id> [--apply]

These commands never push to main, never merge, never alter branch protection,
and never write secrets or absolute machine paths into committed config.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from command_center.schemas import AutonomyConfig, KanbanBoardsConfig, RepoManifest

ROOT = Path(__file__).resolve().parents[3]
AUTONOMY = "configs/autonomy.yaml"
KANBAN_BOARDS = "configs/kanban_boards.yaml"
RUN_ID_DIR = "evaluation/system-validation/20260616-autonomy-contracts"


def _load_autonomy(config_path: Path) -> AutonomyConfig:
    return AutonomyConfig.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")))


def _load_boards(root: Path) -> KanbanBoardsConfig:
    return KanbanBoardsConfig.model_validate(
        yaml.safe_load((root / KANBAN_BOARDS).read_text(encoding="utf-8"))
    )


def _owner_repo(remote_url: str) -> str:
    tail = remote_url.rstrip("/")
    if tail.endswith(".git"):
        tail = tail[:-4]
    return "/".join(tail.split("/")[-2:])


def _evidence_status(path: Path) -> str:
    if not path.is_file():
        return "NOT_RUN"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "UNREADABLE"
    return "PASS" if str(data.get("status")).lower() == "pass" else "BLOCKED"


def _gate(check_id: str, ok: bool, detail: str, *, status: str | None = None) -> dict[str, Any]:
    return {"check": check_id, "status": status or ("PASS" if ok else "BLOCKED"), "detail": detail}


def verify_repo(
    *,
    repo: RepoManifest,
    cfg: AutonomyConfig,
    boards: KanbanBoardsConfig,
    root: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    gates: list[dict[str, Any]] = []

    # Resolve the TARGET repo root. A 'self' repo IS this control repo; an external
    # repo's files live at its resolved local path. Gates that inspect repo files
    # (devcontainer, CODEOWNERS) and per-repo loop evidence must check the target,
    # not the control repo — otherwise an external repo falsely inherits the control
    # repo's files/evidence.
    ref = repo.local_path_ref
    if ref == "self":
        target_root: Path | None = root
    elif ref and ref.startswith("env:") and env.get(ref.split(":", 1)[1]):
        target_root = Path(env[ref.split(":", 1)[1]])
    else:
        target_root = None  # unresolved -> file gates cannot verify the real repo

    where = "self" if ref == "self" else (str(target_root) if target_root else f"{ref}(unresolved)")
    devc_ok = (target_root is not None and bool(repo.devcontainer_path)
               and (target_root / repo.devcontainer_path).is_file())
    gates.append(_gate("devcontainer_present", devc_ok,
                       f"{repo.devcontainer_path or 'none'} in {where}"))
    gates.append(_gate("ci_commands_declared", bool(repo.ci_commands),
                       ", ".join(repo.ci_commands) or "none"))
    co_ok = (not repo.codeowners_required) or (
        target_root is not None and bool(repo.codeowners_path)
        and (target_root / repo.codeowners_path).is_file())
    gates.append(_gate("codeowners_present", co_ok,
                       f"{repo.codeowners_path or 'none'} in {where}"))
    gates.append(_gate("codeowners_required", repo.codeowners_required, str(repo.codeowners_required)))

    # board mapping: kanban_board_id exists AND that board drives this repo
    board = next((b for b in boards.boards if b.board_id == repo.kanban_board_id), None)
    board_ok = board is not None and repo.repo_id in board.repo_ids
    gates.append(_gate("kanban_board_mapping", board_ok,
                       f"board={repo.kanban_board_id}; "
                       f"board_repos={board.repo_ids if board else 'missing'}"))

    # local_path_ref: 'self' or env:NAME that resolves to a real directory.
    if ref == "self":
        lp_ok, lp_detail = True, "self"
    elif ref and ref.startswith("env:"):
        name = ref.split(":", 1)[1]
        lp_ok = target_root is not None and target_root.is_dir()
        lp_detail = (f"env:{name} -> {target_root} dir_exists={lp_ok}" if env.get(name)
                     else f"env:{name} not set")
    else:
        lp_ok, lp_detail = False, f"invalid local_path_ref={ref!r}"
    gates.append(_gate("local_path_ref_resolves", lp_ok, lp_detail))

    full = _owner_repo(repo.remote_url)
    app = cfg.github_app_auth
    gates.append(_gate("github_app_installed",
                       app.status == "verified" and full in app.selected_repositories,
                       f"status={app.status}; selected={full in app.selected_repositories}"))
    bp = cfg.branch_protection_verification
    gates.append(_gate("branch_protection_verified",
                       bp.status == "verified" and full in bp.selected_repositories,
                       f"status={bp.status}; selected={full in bp.selected_repositories}"))

    gates.append(_gate("no_runtime_secrets_in_container",
                       repo.secret_policy == "no_runtime_secrets_inside_container",
                       repo.secret_policy))

    # bounded-loop evidence (proven once PER REPO, never faked). The self/control
    # repo's evidence lives at RUN_ID_DIR/*.json; an external repo's loop must be
    # proven under RUN_ID_DIR/<repo_id>/*.json — it does not inherit the control
    # repo's proof.
    ev_dir = root / RUN_ID_DIR if ref == "self" else root / RUN_ID_DIR / repo.repo_id
    bm = _evidence_status(ev_dir / "branch-mission.json")
    pc = _evidence_status(ev_dir / "pr-check-loop.json")
    gates.append(_gate("branch_mission_proven", bm == "PASS", f"branch-mission.json={bm}", status=bm))
    gates.append(_gate("pr_check_evidence_proven", pc == "PASS",
                       f"pr-check-loop.json={pc}", status=pc))

    blockers = [g["check"] for g in gates if g["status"] != "PASS"]
    return {
        "repo_id": repo.repo_id,
        "repository": full,
        "autonomous_edits_enabled": repo.autonomous_edits_enabled,
        "gates": gates,
        "blockers": blockers,
        "status": "pass" if not blockers else "blocked",
    }


def run_repo_verify(
    *,
    repo_id: str | None = None,
    all_repos: bool = False,
    config_path: Path = ROOT / AUTONOMY,
    root: Path = ROOT,
    env: dict[str, str] | None = None,
    output: Path | None = None,
) -> dict[str, Any]:
    cfg = _load_autonomy(config_path)
    boards = _load_boards(root)
    env = env if env is not None else {}
    if all_repos:
        targets = cfg.repo_manifests
    else:
        targets = [r for r in cfg.repo_manifests if r.repo_id == repo_id]
    blockers: list[str] = []
    if not all_repos and not targets:
        blockers.append(f"repo_not_registered_{repo_id}")
    results = [verify_repo(repo=r, cfg=cfg, boards=boards, root=root, env=env) for r in targets]
    for r in results:
        blockers.extend(f"{r['repo_id']}:{b}" for b in r["blockers"])
    result = {
        "schema_version": "command-center.repo-verify.v1",
        "status": "pass" if not blockers else "blocked",
        "repos_verified": [r["repo_id"] for r in results],
        "results": results,
        "blockers": blockers,
        "writes_performed": False,
        "secrets_printed": False,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def build_repo_manifest_block(
    *, repo_id: str, remote_url: str, local_path_ref: str, kanban_board_id: str,
    devcontainer_path: str = ".devcontainer/devcontainer.json",
) -> RepoManifest:
    """Build a DISABLED manifest (blockers listed) for a newly registered repo."""
    return RepoManifest(
        repo_id=repo_id,
        remote_url=remote_url,
        default_branch="main",
        protected_branches=["main"],
        allowed_base_branches=["main"],
        branch_write_policy="feature_branch_only",
        auth_mode="github_app_pending",
        execution_mode="devcontainer",
        devcontainer_path=devcontainer_path,
        ci_commands=["uv run cc validate", "uv run pytest"],
        secret_policy="no_runtime_secrets_inside_container",
        codeowners_required=True,
        codeowners_path=".github/CODEOWNERS",
        risk_ceiling="L2_local_edits",  # type: ignore[arg-type]
        kanban_board_id=kanban_board_id,
        local_path_ref=local_path_ref,
        autonomous_edits_enabled=False,
        blockers=["repo_autonomy_not_yet_verified"],
    )


def run_repo_register(
    *, repo_id: str, local_path: str, remote_url: str, kanban_board: str,
    apply: bool = False, config_path: Path = ROOT / AUTONOMY, root: Path = ROOT,
) -> dict[str, Any]:
    cfg = _load_autonomy(config_path)
    if any(r.repo_id == repo_id for r in cfg.repo_manifests):
        return {"status": "blocked", "blockers": [f"repo_id_already_registered_{repo_id}"]}
    boards = _load_boards(root)
    if not any(b.board_id == kanban_board for b in boards.boards):
        return {"status": "blocked",
                "blockers": [f"kanban_board_not_registered_{kanban_board}"],
                "next": "register the board first with cc kanban-register"}
    # store the local path as an env reference so no absolute path is committed
    env_name = f"{repo_id.upper()}_LOCAL_PATH"
    manifest = build_repo_manifest_block(
        repo_id=repo_id, remote_url=remote_url,
        local_path_ref=f"env:{env_name}", kanban_board_id=kanban_board,
    )  # validates or raises
    block = yaml.safe_dump([manifest.model_dump(mode="json")], sort_keys=False, indent=2)
    if not apply:
        return {
            "status": "validated_dry_run", "repo_id": repo_id,
            "local_path_env": env_name, "local_path_runtime_value": local_path,
            "next": (f"set {env_name}={local_path} in .env (not committed), then rerun with "
                     "--apply to add the disabled manifest, then cc repo-verify"),
            "manifest_block": block,
        }
    # insert the manifest before the next top-level section (desktop_targets:)
    text = config_path.read_text(encoding="utf-8")
    anchor = "\ndesktop_targets:"
    if anchor not in text:
        return {"status": "blocked", "blockers": ["autonomy_yaml_missing_desktop_targets_anchor"]}
    indented = "".join(f"  {line}\n" if line.strip() else "\n"
                       for line in block.rstrip("\n").splitlines())
    new_text = text.replace(anchor, "\n" + indented + anchor, 1)
    # re-validate the whole config before writing
    AutonomyConfig.model_validate(yaml.safe_load(new_text))
    config_path.write_text(new_text, encoding="utf-8")
    return {"status": "registered", "repo_id": repo_id, "local_path_env": env_name,
            "next": f"set {env_name}={local_path} in .env, then cc repo-verify --repo-id {repo_id}"}


def run_repo_enable_autonomy(
    *, repo_id: str, apply: bool = False, config_path: Path = ROOT / AUTONOMY,
    root: Path = ROOT, env: dict[str, str] | None = None,
) -> dict[str, Any]:
    verify = run_repo_verify(repo_id=repo_id, config_path=config_path, root=root, env=env or {})
    if verify["status"] != "pass":
        return {"status": "blocked", "repo_id": repo_id,
                "blockers": verify["blockers"],
                "next": "clear the failing gates above; autonomy cannot be enabled with blockers"}
    if not apply:
        return {"status": "verified_dry_run", "repo_id": repo_id,
                "next": "all gates pass; rerun with --apply to flip autonomous_edits_enabled"}
    text = config_path.read_text(encoding="utf-8")
    cfg = _load_autonomy(config_path)
    repo = next(r for r in cfg.repo_manifests if r.repo_id == repo_id)
    if repo.autonomous_edits_enabled:
        return {"status": "already_enabled", "repo_id": repo_id}
    # flip the specific manifest's flag + clear blockers, then re-validate.
    raw = yaml.safe_load(text)
    for r in raw["repo_manifests"]:
        if r["repo_id"] == repo_id:
            r["autonomous_edits_enabled"] = True
            r["blockers"] = []
    AutonomyConfig.model_validate(raw)  # enforce the enabled-manifest invariants
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return {"status": "enabled", "repo_id": repo_id}


def main() -> int:
    parser = argparse.ArgumentParser(prog="repo-registry")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pv = sub.add_parser("verify")
    pv.add_argument("--repo-id", default="")
    pv.add_argument("--all", action="store_true")
    pv.add_argument("--output", default="")
    pr = sub.add_parser("register")
    pr.add_argument("--repo-id", required=True)
    pr.add_argument("--local-path", required=True)
    pr.add_argument("--remote-url", required=True)
    pr.add_argument("--kanban-board", required=True)
    pr.add_argument("--apply", action="store_true")
    pe = sub.add_parser("enable-autonomy")
    pe.add_argument("--repo-id", required=True)
    pe.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    from command_center.cli.github_app_verify import _merged_env, _read_dotenv
    env = _merged_env(_read_dotenv(ROOT / ".env"))

    if args.cmd == "verify":
        result = run_repo_verify(repo_id=args.repo_id or None, all_repos=args.all, env=env,
                                 output=(ROOT / args.output).resolve() if args.output else None)
        print(f"repo-verify: {result['status'].upper()}")
        for b in result["blockers"]:
            print(f"  BLOCKED: {b}")
        return 0 if result["status"] == "pass" else 1
    if args.cmd == "register":
        result = run_repo_register(repo_id=args.repo_id, local_path=args.local_path,
                                   remote_url=args.remote_url, kanban_board=args.kanban_board,
                                   apply=args.apply)
        print(f"repo-register: {result['status'].upper()}")
        for b in result.get("blockers", []):
            print(f"  BLOCKED: {b}")
        if result.get("next"):
            print(f"  NEXT: {result['next']}")
        return 0 if result["status"] in ("registered", "validated_dry_run") else 1
    if args.cmd == "enable-autonomy":
        result = run_repo_enable_autonomy(repo_id=args.repo_id, apply=args.apply, env=env)
        print(f"repo-enable-autonomy: {result['status'].upper()}")
        for b in result.get("blockers", []):
            print(f"  BLOCKED: {b}")
        if result.get("next"):
            print(f"  NEXT: {result['next']}")
        return 0 if result["status"] in ("enabled", "verified_dry_run", "already_enabled") else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
