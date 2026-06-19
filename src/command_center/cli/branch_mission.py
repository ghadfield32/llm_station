"""Bounded branch-only repo mission smoke.

This command proves the smallest repo-autonomy loop that is safe before broad
autonomous edits are enabled: create one local feature branch in a temporary
worktree, make one docs-only change, run the repo's declared validation
commands, and write redacted evidence. It never pushes, opens a PR, merges,
deploys, changes repo settings, or reads `.env`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from command_center.autonomy.events import CanonicalEvent
from command_center.autonomy.verifier import verify_completion
from command_center.schemas import AutonomyConfig

ROOT = Path(__file__).resolve().parents[3]
WORK_ITEM = "run_tiny_branch_only_repo_mission"
COMPLETED_ITEM = "tiny_branch_only_repo_mission_passed"
DEFAULT_RUN_ID = "20260616-autonomy-contracts"
DEFAULT_DOC_PATH = Path("docs/branch-mission-smoke.md")
SECRET_NAME_RE = re.compile(r"(TOKEN|SECRET|PASSWORD|PRIVATE|CREDENTIAL|_KEY|KEY_)", re.I)
OS_ENV_ALLOWLIST = {
    "APPDATA",
    "COMSPEC",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "PATH",
    "PATHEXT",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "PROCESSOR_ARCHITECTURE",
    "PSMODULEPATH",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERDOMAIN",
    "USERNAME",
    "USERPROFILE",
    "WINDIR",
}


@dataclass(frozen=True)
class CommandRun:
    args: list[str]
    cwd: str
    exit_code: int
    stdout_sha256: str
    stderr_sha256: str
    stdout_line_count: int
    stderr_line_count: int
    stdout: str = ""
    stderr: str = ""

    @classmethod
    def from_completed(cls, args: list[str], cwd: Path, completed: subprocess.CompletedProcess[str]):
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        return cls(
            args=args,
            cwd=str(cwd),
            exit_code=completed.returncode,
            stdout_sha256=_sha256_text(stdout),
            stderr_sha256=_sha256_text(stderr),
            stdout_line_count=len(stdout.splitlines()),
            stderr_line_count=len(stderr.splitlines()),
            stdout=stdout,
            stderr=stderr,
        )

    def evidence(self) -> dict[str, Any]:
        return {
            "args": self.args,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
            "stdout_line_count": self.stdout_line_count,
            "stderr_line_count": self.stderr_line_count,
        }


Runner = Callable[[list[str], Path, Mapping[str, str]], CommandRun]


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_command(args: list[str], cwd: Path, env: Mapping[str, str]) -> CommandRun:
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=dict(env),
        check=False,
        capture_output=True,
        text=True,
    )
    return CommandRun.from_completed(args, cwd, completed)


def _split_command(command: str) -> list[str]:
    return shlex.split(command, posix=os.name != "nt")


def _load_autonomy(config_path: Path) -> AutonomyConfig:
    return AutonomyConfig.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")))


def _repo_for(cfg: AutonomyConfig, repo_id: str):
    matches = [repo for repo in cfg.repo_manifests if repo.repo_id == repo_id]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one repo manifest for {repo_id!r}, found {len(matches)}")
    return matches[0]


def _secret_env_refs(cfg: AutonomyConfig) -> set[str]:
    refs = {
        cfg.github_app_auth.app_id_env,
        cfg.github_app_auth.client_id_env,
        cfg.github_app_auth.installation_id_env,
        cfg.github_app_auth.private_key_path_env,
        cfg.branch_protection_verification.owner_admin_token_env,
    }
    if cfg.github_app_auth.webhook_secret_env:
        refs.add(cfg.github_app_auth.webhook_secret_env)
    return refs


def _sanitized_env(cfg: AutonomyConfig, base: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    secret_refs = _secret_env_refs(cfg)
    env: dict[str, str] = {}
    removed: list[str] = []
    for name, value in base.items():
        upper = name.upper()
        sensitive = upper in secret_refs or SECRET_NAME_RE.search(upper) is not None
        allowed = upper in OS_ENV_ALLOWLIST or upper.startswith("UV_")
        if sensitive:
            removed.append(name)
            continue
        if allowed:
            env[name] = value
    return env, sorted(removed)


def _mission_stamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%S%fZ")


def _mission_doc(
    *,
    mission_id: str,
    branch: str,
    repo_id: str,
    created_at: str,
    ci_commands: list[str],
) -> str:
    command_lines = "\n".join(f"- `{command}`" for command in ci_commands)
    return "\n".join([
        "# Branch Mission Smoke",
        "",
        f"- Mission id: `{mission_id}`",
        f"- Repo id: `{repo_id}`",
        f"- Branch: `{branch}`",
        f"- Created at: `{created_at}`",
        "- Scope: local branch/worktree docs-only smoke.",
        "- External writes: none.",
        "- Main branch writes: none.",
        "- PR creation: not performed by this branch-only mission.",
        "- Merge/deploy/settings/secrets changes: none.",
        "",
        "## Declared Validation Commands",
        "",
        command_lines,
        "",
    ])


def _changed_paths_from_status(status_text: str) -> list[str]:
    paths: list[str] = []
    for raw in status_text.splitlines():
        if not raw:
            continue
        path = raw[3:] if len(raw) > 3 else raw
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.replace("\\", "/"))
    return paths


def _docs_only(paths: list[str]) -> bool:
    return bool(paths) and all(path == "docs" or path.startswith("docs/") for path in paths)


def _event(
    *,
    kind: str,
    event_id: str,
    mission_id: str,
    timestamp: str,
    result: str,
    risk_tier,
    detail: dict[str, Any],
) -> CanonicalEvent:
    return CanonicalEvent(
        kind=kind,
        event_id=event_id,
        mission_id=mission_id,
        timestamp=timestamp,
        actor="cc.branch-mission",
        source_authority="configs/autonomy.yaml",
        risk_tier=risk_tier,
        privacy_classification="internal",
        result=result,
        input_artifact_hashes=[],
        output_artifact_hashes=[],
        trace_id=mission_id,
        approval_id=None,
        rollback_id=None,
        detail=detail,
    )


def _write_output(output: Path | None, result: dict[str, Any]) -> None:
    if output is None:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def execute_branch_mission(
    *,
    repo_id: str = "llm_station",
    root: Path = ROOT,
    config_path: Path | None = None,
    output: Path | None = None,
    worktree_root: Path | None = None,
    mission_id: str | None = None,
    doc_path: Path = DEFAULT_DOC_PATH,
    now: datetime | None = None,
    env_base: Mapping[str, str] | None = None,
    runner: Runner = _run_command,
) -> dict[str, Any]:
    config_path = config_path or root / "configs" / "autonomy.yaml"
    now = now or datetime.now(timezone.utc)
    created_at = now.isoformat()
    stamp = _mission_stamp(now)
    mission_id = mission_id or f"{repo_id}-docs-only-{stamp}"
    branch = f"mission/{repo_id}/docs-only/{stamp}"
    scratch_root = os.environ.get("TMPDIR") or os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp"
    worktree_root = worktree_root or Path(scratch_root) / "command-center-repo-missions"
    worktree = worktree_root / mission_id
    cfg = _load_autonomy(config_path)
    repo = _repo_for(cfg, repo_id)
    env, removed_env = _sanitized_env(cfg, env_base or os.environ)
    blockers: list[str] = []
    commands: list[dict[str, Any]] = []
    events: list[CanonicalEvent] = []

    devcontainer = root / (repo.devcontainer_path or "")
    codeowners = root / (repo.codeowners_path or "")
    if WORK_ITEM not in cfg.ordered_work and COMPLETED_ITEM not in cfg.completed_work:
        blockers.append(f"ordered_work_missing_{WORK_ITEM}")
    if cfg.github_app_auth.status != "verified":
        blockers.append("github_app_auth_not_verified")
    if cfg.branch_protection_verification.status != "verified":
        blockers.append("branch_protection_not_verified")
    if repo.auth_mode != "github_app":
        blockers.append("repo_auth_mode_not_github_app")
    if repo.branch_write_policy != "feature_branch_only":
        blockers.append("repo_branch_write_policy_not_feature_branch_only")
    if repo.execution_mode == "devcontainer" and not devcontainer.exists():
        blockers.append(f"devcontainer_manifest_missing_{repo.devcontainer_path}")
    if repo.codeowners_required and not codeowners.exists():
        blockers.append(f"codeowners_missing_{repo.codeowners_path}")
    if doc_path.is_absolute() or ".." in doc_path.parts:
        blockers.append("doc_path_must_be_repo_relative")
    if not _docs_only([doc_path.as_posix()]):
        blockers.append("mission_doc_path_not_docs_only")
    if worktree.exists():
        blockers.append("worktree_path_already_exists")

    expected_after = {
        "branch": branch,
        "worktree": str(worktree),
        "changed_paths": [doc_path.as_posix()],
        "ci": "all_declared_commands_passed",
        "push_performed": False,
        "pr_created": False,
        "merge_performed": False,
    }
    forecast = _event(
        kind="mission.forecast",
        event_id=f"{mission_id}:forecast",
        mission_id=mission_id,
        timestamp=created_at,
        result="planned",
        risk_tier=repo.risk_ceiling,
        detail={
            "expected_state_before": {
                "worktree_exists": worktree.exists(),
                "autonomous_edits_enabled": repo.autonomous_edits_enabled,
            },
            "expected_state_after": expected_after,
            "expected_events": [
                "local_branch_created",
                "local_worktree_created",
                "docs_only_change_written",
                "declared_validation_commands_run",
                "redacted_evidence_written",
            ],
            "expected_no_change": [
                "no_main_push",
                "no_remote_push",
                "no_pr",
                "no_merge",
                "no_deploy",
                "no_settings_change",
                "no_secret_write",
            ],
            "privacy_boundary": "no_env_file_read_no_secret_values_retained_command_output_hashed",
            "rollback_or_revert_plan": (
                "remove the local worktree; retain the local mission branch unless "
                "human cleanup is approved"
            ),
        },
    )
    events.append(forecast)

    if not blockers:
        worktree_root.mkdir(parents=True, exist_ok=True)
        add = runner(["git", "worktree", "add", "-b", branch, str(worktree), "HEAD"], root, env)
        commands.append({"purpose": "create_worktree_branch", **add.evidence()})
        events.append(_event(
            kind="repo.action",
            event_id=f"{mission_id}:repo-action:worktree-add",
            mission_id=mission_id,
            timestamp=created_at,
            result="verified" if add.exit_code == 0 else "failed",
            risk_tier=repo.risk_ceiling,
            detail={
                "repo_id": repo.repo_id,
                "branch": branch,
                "worktree_ref": str(worktree),
                "command": add.args,
                "exit_code": add.exit_code,
            },
        ))
        if add.exit_code != 0:
            blockers.append("git_worktree_add_failed")

    doc_file = worktree / doc_path
    if not blockers:
        doc_file.parent.mkdir(parents=True, exist_ok=True)
        doc_file.write_text(
            _mission_doc(
                mission_id=mission_id,
                branch=branch,
                repo_id=repo.repo_id,
                created_at=created_at,
                ci_commands=repo.ci_commands,
            ),
            encoding="utf-8",
        )
        status = runner(["git", "status", "--porcelain", "--untracked-files=all"], worktree, env)
        commands.append({"purpose": "inspect_changed_paths", **status.evidence()})
        if status.exit_code != 0:
            blockers.append("git_status_failed")
            changed_paths: list[str] = []
        else:
            changed_paths = _changed_paths_from_status(status.stdout)
            if not _docs_only(changed_paths):
                blockers.append("changed_paths_not_docs_only")
    else:
        changed_paths = []

    ci_results: list[dict[str, Any]] = []
    if not blockers:
        for command in repo.ci_commands:
            if any(result.get("status") == "blocked" for result in ci_results):
                ci_results.append({
                    "command": command,
                    "status": "not_run",
                    "reason": "previous_declared_validation_command_failed",
                })
                continue
            args = _split_command(command)
            run = runner(args, worktree, env)
            commands.append({"purpose": "declared_validation_command", **run.evidence()})
            status = "pass" if run.exit_code == 0 else "blocked"
            ci_results.append({
                "command": command,
                "status": status,
                "exit_code": run.exit_code,
                "stdout_sha256": run.stdout_sha256,
                "stderr_sha256": run.stderr_sha256,
                "stdout_line_count": run.stdout_line_count,
                "stderr_line_count": run.stderr_line_count,
            })
            events.append(_event(
                kind="repo.action",
                event_id=f"{mission_id}:repo-action:ci:{len(ci_results)}",
                mission_id=mission_id,
                timestamp=created_at,
                result="verified" if run.exit_code == 0 else "failed",
                risk_tier=repo.risk_ceiling,
                detail={
                    "repo_id": repo.repo_id,
                    "branch": branch,
                    "worktree_ref": str(worktree),
                    "command": args,
                    "exit_code": run.exit_code,
                },
            ))
            if run.exit_code != 0:
                blockers.append(f"declared_validation_command_failed_{len(ci_results)}")

    if blockers:
        observed_after = {
            "branch": branch,
            "worktree": str(worktree),
            "changed_paths": changed_paths,
            "ci": "blocked",
            "blockers": blockers,
            "push_performed": False,
            "pr_created": False,
            "merge_performed": False,
        }
        verifier_result = "blocked"
    else:
        observed_after = expected_after
        verifier_result = "pass"

    verification = _event(
        kind="mission.verification",
        event_id=f"{mission_id}:verification",
        mission_id=mission_id,
        timestamp=created_at,
        result="verified" if not blockers else "blocked",
        risk_tier=repo.risk_ceiling,
        detail={
            "observed_state_after": observed_after,
            "evidence_refs": [str(output)] if output is not None else [mission_id],
            "verifier_result": verifier_result,
        },
    )
    events.append(verification)
    verdict = verify_completion(
        forecast=forecast,
        verification=verification,
        recent_actions=[event for event in events if event.kind == "repo.action"],
        config=cfg,
    )
    if not verdict.passed:
        for reason in verdict.reasons:
            if reason not in blockers:
                blockers.append(reason)

    final_status = "pass" if not blockers else "blocked"
    doc_sha = _sha256_file(doc_file) if doc_file.exists() else None
    result = {
        "status": final_status,
        "mission_id": mission_id,
        "repo_id": repo.repo_id,
        "risk_tier": repo.risk_ceiling.value,
        "created_at": created_at,
        "branch": branch,
        "worktree": str(worktree),
        "doc_path": doc_path.as_posix(),
        "doc_sha256": doc_sha,
        "changed_paths": changed_paths,
        "docs_only": _docs_only(changed_paths),
        "declared_ci_commands": repo.ci_commands,
        "ci_results": ci_results,
        "completion_verdict": {
            "status": verdict.status,
            "reasons": verdict.reasons,
        },
        "blockers": blockers,
        "devcontainer": {
            "execution_mode": repo.execution_mode,
            "manifest_path": repo.devcontainer_path,
            "manifest_verified": bool(repo.devcontainer_path and devcontainer.exists()),
            "runtime_invoked": False,
            "runtime_invocation_policy": "not_invoked_by_branch_only_smoke",
        },
        "github_policy": {
            "auth_mode": repo.auth_mode,
            "branch_write_policy": repo.branch_write_policy,
            "autonomous_edits_enabled": repo.autonomous_edits_enabled,
            "push_performed": False,
            "pr_created": False,
            "merge_performed": False,
            "settings_changed": False,
            "secrets_changed": False,
        },
        "privacy": {
            "env_file_read": False,
            "secret_values_retained": False,
            "command_output_retention": "sha256_and_line_counts_only",
            "secret_env_var_names_removed": removed_env,
        },
        "commands": commands,
        "events": [event.model_dump(mode="json") for event in events],
    }
    _write_output(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="branch-mission")
    parser.add_argument("--repo-id", default="llm_station")
    parser.add_argument("--config", default="configs/autonomy.yaml")
    parser.add_argument(
        "--output",
        default=(
            "evaluation/system-validation/"
            f"{DEFAULT_RUN_ID}/branch-mission.json"
        ),
    )
    parser.add_argument("--worktree-root", default="")
    parser.add_argument("--mission-id", default="")
    args = parser.parse_args()

    output = (ROOT / args.output).resolve()
    worktree_root = Path(args.worktree_root).resolve() if args.worktree_root else None
    result = execute_branch_mission(
        repo_id=args.repo_id,
        root=ROOT,
        config_path=(ROOT / args.config).resolve(),
        output=output,
        worktree_root=worktree_root,
        mission_id=args.mission_id or None,
    )
    print(f"branch-mission: {result['status'].upper()}")
    print(f"  mission: {result['mission_id']}")
    print(f"  branch: {result['branch']}")
    print(f"  worktree: {result['worktree']}")
    for blocker in result.get("blockers", []):
        print(f"  BLOCKED: {blocker}")
    print(f"evidence -> {args.output}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
