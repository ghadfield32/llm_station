"""Generic bounded-loop proof for ANY registered repo.

Unlike `pr-check-verify` (which replays llm_station's specific "fix the fastapi
[dev] extra" CI scenario), this proves the loop in a repo-agnostic way:

  1. the App opens a feature branch with a trivial, CI-safe marker file;
  2. it opens a draft PR;
  3. the repo's OWN required checks (RepoManifest.required_status_check_contexts)
     run and succeed on that PR;
  4. the App does NOT merge (verified: the PR stays unmerged) — the human merge
     wall holds;
  5. evidence is written; the proof PR + branch are cleaned up.

It performs no merge and writes redacted evidence. Preconditions are generic (no
repo-shape assumptions): App installed for the repo + required checks declared.

  cc repo-loop-proof --repo-id betts_basketball --apply --output <path>
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from command_center.cli.github_app_verify import mint_installation_token
from command_center.cli.pr_check_verify import (
    _owner_repo,
    _request_json,
    create_branch_commit,
    open_pull_request,
    poll_check_runs,
    required_checks_for,
)
from command_center.schemas import AutonomyConfig

ROOT = Path(__file__).resolve().parents[3]
MARKER_PATH = ".github/command-center-loop-proof.md"


def _marker(mission_id: str, created_at: str) -> str:
    return (
        "# command-center bounded-loop proof\n\n"
        "Trivial, CI-safe artifact opened by the Command Center to prove the "
        "bounded PR loop (open PR -> required checks pass -> the agent does NOT "
        "merge). This PR is closed automatically once the checks are observed; the "
        "human merge wall is never bypassed.\n\n"
        f"- mission_id: {mission_id}\n- created_at: {created_at}\n"
    )


def _write_output(output: Path | None, result: dict[str, Any]) -> None:
    if output is None:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_repo_loop_proof(
    *,
    repo_id: str,
    root: Path = ROOT,
    config_path: Path | None = None,
    dotenv_path: Path | None = None,
    output: Path | None = None,
    now: datetime | None = None,
    client_factory=None,
    token_minter=mint_installation_token,
    poll_interval: float = 0.0,
    poll_timeout: float = 0.0,
    apply: bool = False,
) -> dict[str, Any]:
    if client_factory is None:
        import httpx
        client_factory = httpx.Client
    config_path = config_path or root / "configs" / "autonomy.yaml"
    dotenv_path = dotenv_path or root / ".env"
    now = now or datetime.now(timezone.utc)
    created_at = now.isoformat()
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    mission_id = f"{repo_id}-loop-proof-{stamp}"
    branch = f"mission/{repo_id}/loop-proof/{stamp}"

    cfg = AutonomyConfig.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")))
    manifest = next((r for r in cfg.repo_manifests if r.repo_id == repo_id), None)
    required, checks_source = required_checks_for(cfg, repo_id)
    result: dict[str, Any] = {
        "status": "blocked", "mission_id": mission_id, "repo_id": repo_id,
        "branch": branch, "created_at": created_at, "required_checks": list(required),
        "required_checks_source": checks_source, "merge_performed": False,
        "writes_performed": False, "blockers": [],
    }
    owner_repo = _owner_repo(manifest.remote_url) if manifest else None
    full = f"{owner_repo[0]}/{owner_repo[1]}" if owner_repo else None
    app = cfg.github_app_auth
    if manifest is None:
        result["blockers"].append(f"repo_manifest_not_found_{repo_id}")
    elif manifest.auth_mode != "github_app":
        result["blockers"].append("repo_auth_mode_not_github_app")
    if app.status != "verified" or (full and full not in app.selected_repositories):
        result["blockers"].append("github_app_not_installed_for_repo")
    if not required:
        result["blockers"].append("required_checks_not_configured")
    if not apply:
        result["blockers"].append("apply_not_set")
    if poll_interval < 0 or poll_timeout < 0:
        result["blockers"].append("poll_values_must_be_non_negative")
    if result["blockers"]:
        _write_output(output, result)
        return result

    owner, repo = owner_repo
    base = manifest.default_branch
    from command_center.cli.github_app_verify import _merged_env, _read_dotenv
    env = _merged_env(_read_dotenv(dotenv_path))
    try:
        token, _ = token_minter(env=env, auth=app, client_factory=client_factory)
    except RuntimeError as exc:
        result["blockers"].append(f"token_mint_failed_{exc}")
        _write_output(output, result)
        return result

    made = create_branch_commit(
        client_factory=client_factory, token=token, owner=owner, repo=repo,
        base=base, branch=branch, files={MARKER_PATH: _marker(mission_id, created_at)},
        message=f"chore: command-center bounded-loop proof ({mission_id})")
    if made.get("status") != 201:
        result["blockers"].append(f"branch_commit_failed_{made.get('error')}")
        _write_output(output, result)
        return result
    result["writes_performed"] = True

    pr = open_pull_request(
        client_factory=client_factory, token=token, owner=owner, repo=repo,
        head=branch, base=base, title=f"Command Center bounded-loop proof ({repo_id})",
        body="Trivial CI-safe proof PR; the agent does not merge. Auto-closed after checks.")
    pr_number = (pr.get("data") or {}).get("number")
    result["pull_request_number"] = pr_number
    if pr.get("status") != 201 or not pr_number:
        result["blockers"].append(f"pull_request_open_failed_{pr.get('status')}")
        _cleanup(client_factory, token, owner, repo, branch, None)
        _write_output(output, result)
        return result

    polled = poll_check_runs(
        client_factory=client_factory, token=token, owner=owner, repo=repo,
        sha=made["commit_sha"], required=required,
        poll_interval=poll_interval, poll_timeout=poll_timeout)
    result["checks"] = {n: rr.get("conclusion") for n, rr in polled.get("runs", {}).items()}
    result["checks_complete"] = polled.get("complete")
    result["checks_success"] = polled.get("success")

    # the App must NOT have merged — verify the PR is still unmerged
    with client_factory(timeout=30) as client:
        _, prdata = _request_json(client, "GET",
                                  f"/repos/{owner}/{repo}/pulls/{pr_number}", token=token)
    merged = bool(prdata.get("merged"))
    result["merge_performed"] = merged

    _cleanup(client_factory, token, owner, repo, branch, pr_number)

    if polled.get("success") and not merged:
        result["status"] = "pass"
    else:
        if not polled.get("success"):
            result["blockers"].append("required_checks_did_not_succeed")
        if merged:
            result["blockers"].append("pull_request_was_merged_wall_breached")
    _write_output(output, result)
    return result


def _cleanup(client_factory, token, owner, repo, branch, pr_number) -> None:
    """Close the proof PR (never merge) + delete the proof branch. Loud on failure."""
    with client_factory(timeout=30) as client:
        if pr_number is not None:
            _request_json(client, "PATCH", f"/repos/{owner}/{repo}/pulls/{pr_number}",
                          token=token, body={"state": "closed"})
        _request_json(client, "DELETE",
                      f"/repos/{owner}/{repo}/git/refs/heads/{branch}", token=token)


def main() -> int:
    parser = argparse.ArgumentParser(prog="repo-loop-proof")
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", default="")
    parser.add_argument("--poll-interval", type=float, default=20.0)
    parser.add_argument("--poll-timeout", type=float, default=1500.0)
    args = parser.parse_args()
    out = (ROOT / args.output).resolve() if args.output else None
    # run_repo_loop_proof loads creds from dotenv_path (default ROOT/.env) and mints
    # the installation token via the default token_minter.
    res = run_repo_loop_proof(repo_id=args.repo_id, apply=args.apply, output=out,
                              poll_interval=args.poll_interval, poll_timeout=args.poll_timeout)
    print(f"repo-loop-proof: {res['status'].upper()}")
    for b in res.get("blockers", []):
        print(f"  BLOCKED: {b}")
    return 0 if res["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
