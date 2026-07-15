"""Whole-system validation evidence runner.

This command records the current contract-backed readiness state for the
autonomous pipeline. It is deliberately observer-only: it reads git metadata and
validated config, then writes a local evidence package. Live services, desktop
actions, board writes, repo mutations, provider calls, and notifications are not
performed here.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from command_center.schemas import AutonomyConfig, CONFIG_CONTRACTS

ROOT = Path(__file__).resolve().parents[3]


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return f"unknown: {completed.stderr.strip() or completed.stdout.strip()}"
    return completed.stdout.strip()


def _load_autonomy() -> AutonomyConfig:
    raw = yaml.safe_load((ROOT / "configs" / "autonomy.yaml").read_text(encoding="utf-8"))
    return AutonomyConfig.model_validate(raw)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _bullet(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- none"


def _artifact_status(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "UNREADABLE"
    status = str(data.get("status") or "unknown").upper()
    return status if status in {"PASS", "BLOCKED", "FAIL", "MISSING", "PROPOSED"} else "UNKNOWN"


def _artifact_blockers(path: Path, label: str) -> list[str]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [f"{label} unreadable"]
    blockers = data.get("blockers")
    if not isinstance(blockers, list):
        return []
    return [f"{label}: {blocker}" for blocker in blockers if isinstance(blocker, str)]


def _repo_lines(cfg: AutonomyConfig) -> list[str]:
    lines = []
    for repo in cfg.repo_manifests:
        state = "enabled" if repo.autonomous_edits_enabled else "blocked"
        blockers = ", ".join(repo.blockers) if repo.blockers else "none"
        devcontainer = repo.devcontainer_path or "none"
        lines.append(
            f"`{repo.repo_id}`: {state}; auth={repo.auth_mode}; "
            f"execution={repo.execution_mode}; risk_ceiling={repo.risk_ceiling.value}; "
            f"devcontainer={devcontainer}; blockers={blockers}"
        )
    return lines


def _desktop_lines(cfg: AutonomyConfig) -> list[str]:
    lines = []
    for target in cfg.desktop_targets:
        state = "enabled" if target.enabled else "blocked"
        blockers = ", ".join(target.blockers) if target.blockers else "none"
        card = f"{target.board}/{target.card_ref}" if target.board and target.card_ref else "none"
        evidence = target.snapshot_evidence_ref or "none"
        lines.append(
            f"`{target.target_id}`: {state}; surface={target.surface}; "
            f"os={target.os_family}; card={card}; snapshot={evidence}; blockers={blockers}"
        )
    return lines


def _canary_lines(cfg: AutonomyConfig) -> list[str]:
    lines = []
    for canary in cfg.canaries:
        state = "enabled" if canary.enabled else "blocked"
        blocked_until = ", ".join(canary.blocked_until) if canary.blocked_until else "none"
        schedule = canary.schedule or "none"
        lines.append(
            f"`{canary.name}`: {state}; kind={canary.kind}; "
            f"schedule={schedule}; blocked_until={blocked_until}"
        )
    return lines


def _agent_validation_lines(cfg: AutonomyConfig) -> list[str]:
    agent = cfg.agent_validation
    return [
        f"model_alias={agent.model_alias}",
        f"max_tokens={agent.max_tokens}",
        f"max_tokens_source={agent.max_tokens_source}",
        "required_scenarios=" + ", ".join(agent.required_scenarios),
    ]


def _github_app_lines(cfg: AutonomyConfig) -> list[str]:
    auth = cfg.github_app_auth
    repositories = ", ".join(auth.selected_repositories)
    return [
        f"status={auth.status}",
        f"app={auth.app_name}",
        f"owner={auth.owner}",
        f"homepage={auth.homepage_url}",
        f"webhook_active={auth.webhook_active}",
        f"app_id_env={auth.app_id_env}",
        f"client_id_env={auth.client_id_env}",
        f"installation_id_env={auth.installation_id_env}",
        f"private_key_path_env={auth.private_key_path_env}",
        f"selected_repositories={repositories}",
        f"token_storage_policy={auth.token_storage_policy}",
    ]


def _branch_protection_lines(cfg: AutonomyConfig) -> list[str]:
    protection = cfg.branch_protection_verification
    return [
        f"status={protection.status}",
        f"owner_admin_token_env={protection.owner_admin_token_env}",
        "selected_repositories=" + ", ".join(protection.selected_repositories),
        "required_status_check_contexts="
        + ", ".join(protection.required_status_check_contexts),
        f"required_status_check_source_path={protection.required_status_check_source_path}",
        f"codeowners_path={protection.codeowners_path}",
        f"required_approving_review_count={protection.required_approving_review_count}",
        f"required_review_count_source={protection.required_review_count_source}",
        f"require_ruleset_bypass_actors_absent={protection.require_ruleset_bypass_actors_absent}",
        f"ruleset_bypass_policy_source={protection.ruleset_bypass_policy_source}",
        f"token_policy={protection.token_policy}",
    ]


def _gap_lines(cfg: AutonomyConfig) -> list[str]:
    gaps: list[str] = []
    for repo in cfg.repo_manifests:
        if not repo.autonomous_edits_enabled:
            gaps.append(f"repo `{repo.repo_id}` autonomous edits blocked: {', '.join(repo.blockers)}")
    for target in cfg.desktop_targets:
        if not target.enabled:
            gaps.append(f"desktop target `{target.target_id}` blocked: {', '.join(target.blockers)}")
    for canary in cfg.canaries:
        if not canary.enabled:
            gaps.append(f"canary `{canary.name}` blocked until: {', '.join(canary.blocked_until)}")
    if cfg.telemetry.mode != "opentelemetry":
        gaps.append(f"telemetry mode is `{cfg.telemetry.mode}`: {', '.join(cfg.telemetry.decision_basis)}")
    if cfg.github_app_review.status != "approved":
        gaps.append(
            "GitHub App production auth review pending: "
            + ", ".join(cfg.github_app_review.requirements)
        )
    if cfg.github_app_auth.status != "verified":
        requirements = ", ".join(cfg.github_app_review.requirements)
        gaps.append(
            f"GitHub App auth is `{cfg.github_app_auth.status}` pending auth "
            f"requirements: {requirements}"
        )
    if cfg.external_runtime_evaluation.status != "approved_for_spike":
        gaps.append(
            "external runtime evaluation blocked until measured gap and gates: "
            + ", ".join(cfg.external_runtime_evaluation.required_gates)
        )
    if (
        cfg.completion_verifier.repeated_action_policy
        == "experiment_derived_threshold_required_before_autonomous_gui"
    ):
        gaps.append("loop-breaker numeric threshold not set; requires experiment-derived plan")
    return gaps


def build_package(output_root: Path, run_id: str) -> Path:
    cfg = _load_autonomy()
    out = output_root / run_id
    agent_validation_status = _artifact_status(out / "agent-validation.json")
    desktop_target_status = _artifact_status(out / "desktop-target-verify.json")
    desktop_adapter_status = _artifact_status(out / "desktop-adapter-readiness.json")
    desktop_noop_status = _artifact_status(out / "desktop-noop-canary.json")
    desktop_timing_status = _artifact_status(out / "desktop-timing-candidates.json")
    branch_protection_status = _artifact_status(out / "branch-protection-verify.json")
    github_app_status = _artifact_status(out / "github-app-verify.json")
    branch_mission_status = _artifact_status(out / "branch-mission.json")
    pr_check_status = _artifact_status(out / "pr-check-loop.json")
    commit = _git("rev-parse", "--short", "HEAD")
    status = _git("status", "--short")
    dirty = status.splitlines() if status else []
    config_names = sorted(CONFIG_CONTRACTS)
    event_kinds = [family.kind for family in cfg.event_contract.families]
    gaps = _gap_lines(cfg)
    gaps.extend(_artifact_blockers(out / "desktop-adapter-readiness.json", "desktop adapter"))
    gaps.extend(_artifact_blockers(out / "desktop-noop-canary.json", "desktop noop canary"))
    gaps.extend(_artifact_blockers(out / "desktop-timing-candidates.json", "desktop timing"))
    github_app_installation_status = (
        "PASS"
        if "github_app_installed_on_selected_llm_station_repo" in cfg.completed_work
        else "BLOCKED"
    )
    github_app_repository_permissions_status = (
        "PASS"
        if "github_app_repository_permissions_verified" in cfg.completed_work
        else "BLOCKED"
    )
    repo_autonomy_config_enabled = (
        cfg.repo_manifests and all(repo.autonomous_edits_enabled for repo in cfg.repo_manifests)
    )
    repo_autonomy_status = (
        "PASS" if repo_autonomy_config_enabled and pr_check_status == "PASS" else "BLOCKED"
    )
    desktop_automation_status = (
        "PASS"
        if cfg.desktop_targets and all(target.enabled for target in cfg.desktop_targets)
        else "BLOCKED"
    )
    github_app_production_auth_status = (
        "PASS"
        if cfg.github_app_review.status == "approved" and cfg.github_app_auth.status == "verified"
        else "BLOCKED"
    )

    _write(
        out / "BASELINE.md",
        "\n".join([
            "# Baseline",
            "",
            f"- Run id: `{run_id}`",
            f"- Commit: `{commit}`",
            f"- Dirty entries: {len(dirty)}",
            "",
            "## Dirty Worktree",
            _bullet(dirty),
            "",
            "## Validated Config Contracts",
            _bullet(config_names),
            "",
            "## Event Families",
            _bullet(event_kinds),
            "",
            "## Repo Manifests",
            _bullet(_repo_lines(cfg)),
            "",
            "## Desktop Targets",
            _bullet(_desktop_lines(cfg)),
            "",
            "## Agent Validation",
            _bullet(_agent_validation_lines(cfg)),
            "",
            "## GitHub App Auth",
            _bullet(_github_app_lines(cfg)),
            "",
            "## Branch Protection Verification",
            _bullet(_branch_protection_lines(cfg)),
        ]),
    )

    _write(
        out / "SCENARIOS.md",
        "\n".join([
            "# Scenarios",
            "",
            "| Scenario | Status | Evidence |",
            "| --- | --- | --- |",
            "| autonomy config validates | PASS | configs/autonomy.yaml |",
            "| canonical event families declared | PASS | BASELINE.md#event-families |",
            f"| repo autonomy enabled | {repo_autonomy_status} | "
            "configs/autonomy.yaml + pr-check-loop.json |",
            f"| desktop automation enabled | {desktop_automation_status} | "
            "GAPS.md#repo-and-desktop-blockers |",
            "| completion verifier requires evidence | PASS | configs/autonomy.yaml |",
            f"| local agent tool/memory/multi-turn validation | {agent_validation_status} | "
            "agent-validation.json |",
            f"| desktop target snapshot verification | {desktop_target_status} | "
            "desktop-target-verify.json |",
            f"| desktop adapter readiness | {desktop_adapter_status} | "
            "desktop-adapter-readiness.json |",
            f"| desktop no-op canary telemetry | {desktop_noop_status} | "
            "desktop-noop-canary.json |",
            f"| desktop timing candidate derivation | {desktop_timing_status} | "
            "desktop-timing-candidates.json |",
            "| no-op canaries scheduled | BLOCKED | GAPS.md#canaries |",
            "| telemetry production backend | BLOCKED | GAPS.md#telemetry |",
            f"| GitHub App production auth | {github_app_production_auth_status} | "
            "configs/autonomy.yaml |",
            f"| GitHub App verifier | {github_app_status} | github-app-verify.json |",
            f"| GitHub App installation observed | {github_app_installation_status} | "
            "github-app-verify.json |",
            f"| GitHub App repository permission verification | {github_app_repository_permissions_status} | "
            "GAPS.md#auth-and-external-runtimes |",
            f"| GitHub branch protection verification | {branch_protection_status} | "
            "branch-protection-verify.json |",
            f"| tiny branch-only repo mission | {branch_mission_status} | "
            "branch-mission.json |",
            f"| live PR/check evidence loop | {pr_check_status} | "
            "pr-check-loop.json |",
            "| external runtime spike | BLOCKED | GAPS.md#auth-and-external-runtimes |",
        ]),
    )

    _write(
        out / "COMMANDS.md",
        "\n".join([
            "# Commands",
            "",
            "- `git rev-parse --short HEAD`",
            "- `git status --short`",
            "- `AutonomyConfig.model_validate(configs/autonomy.yaml)`",
            "- Optional: `cc github-app-verify --output <package>/github-app-verify.json`",
            "- Optional: `cc branch-protection-verify --output <package>/branch-protection-verify.json`",
            "- Optional: `cc branch-mission --output <package>/branch-mission.json`",
            "- Optional: `cc pr-check-verify --apply --output <package>/pr-check-loop.json`",
            "- Optional: `cc agent-validation --output <package>/agent-validation.json`",
            "- Optional: `cc desktop-target-verify --output <package>/desktop-target-verify.json`",
            "- Optional: `cc desktop-adapter --output <package>/desktop-adapter-readiness.json`",
            "- Optional: `cc desktop-noop-canary --output <package>/desktop-noop-canary.json`",
            "- Optional: `cc desktop-timing-derive --target-id <target> "
            "--output <package>/desktop-timing-candidates.json` "
            "(required sample count comes from configs/autonomy.yaml evidence refs)",
            "",
            "No live services, desktop actions, board writes, repo mutations, model calls, "
            "or notifications were executed by this runner; optional artifacts are produced "
            "by their own observer commands.",
        ]),
    )

    _write(
        out / "PRIVACY.md",
        "\n".join([
            "# Privacy",
            "",
            "- `.env` was not read.",
            "- `cc github-app-verify`, when run separately, may read GitHub env key "
            "presence and write a redacted artifact into this package.",
            "- `cc branch-protection-verify`, when run separately, may read owner/admin "
            "observer token presence and write redacted branch-protection evidence.",
            "- `cc branch-mission`, when run separately, creates a temporary local "
            "worktree, writes one docs-only smoke file, runs configured validation "
            "commands with secret env names removed, and retains command output hashes "
            "and line counts only.",
            "- `cc pr-check-verify`, when run separately with `--apply`, uses a "
            "short-lived GitHub App installation token in memory to create one "
            "feature branch and one draft PR, then stores only PR/check metadata.",
            "- Raw chat transcripts were not read.",
            "- Screenshots were not captured.",
            "- Model prompts and outputs were not retained.",
            "- `cc agent-validation`, when run separately, stores synthetic scenario "
            "statuses only; it does not retain prompts or model text.",
            "- `cc desktop-target-verify`, when run separately, reads the board snapshot "
            "and stores target identity/status evidence only.",
            "- `cc desktop-adapter`, when run separately, stores manifest readiness "
            "evidence only and performs no desktop actions.",
            "- `cc desktop-noop-canary`, when run separately, stores redacted timing "
            "and target-assertion evidence only; it performs no desktop actions.",
            "- `cc desktop-timing-derive`, when run separately, stores provisional "
            "candidate timing values only from measured canary evidence and never "
            "writes production controls.",
            "- The package stores config-derived summaries, git metadata, blockers, and paths only.",
        ]),
    )

    _write(
        out / "FORECASTS.md",
        "\n".join([
            "# Forecasts",
            "",
            "## evidence-package-write",
            "",
            "- Source authority: `configs/autonomy.yaml` plus git metadata.",
            "- Expected state before: no system-validation package for this run id.",
            "- Expected state after: local markdown evidence package exists.",
            "- Expected events: none emitted to Ledger; file writes only.",
            "- Expected no change: no external board runtime, desktop, repo, model, provider, or notification action.",
            "- Privacy boundary: no secrets, raw transcripts, screenshots, or raw model artifacts.",
            "- Rollback: delete this run directory if the local evidence package is unwanted.",
            "- Observed result: package written by this command.",
        ]),
    )

    _write(
        out / "GAPS.md",
        "\n".join([
            "# Gaps",
            "",
            "## Repo And Desktop Blockers",
            _bullet([gap for gap in gaps if gap.startswith(("repo", "desktop"))]),
            "",
            "## Canaries",
            _bullet([gap for gap in gaps if gap.startswith("canary")]),
            "",
            "## Telemetry",
            _bullet([gap for gap in gaps if gap.startswith("telemetry")]),
            "",
            "## Auth And External Runtimes",
            _bullet([gap for gap in gaps if "GitHub App" in gap or "external runtime" in gap]),
            "",
            "## Verifier",
            _bullet([gap for gap in gaps if "loop-breaker" in gap]),
        ]),
    )

    _write(
        out / "NEXT.md",
        "\n".join([
            "# Next Ordered Work",
            "",
            "## Completed Contract Work",
            _bullet(cfg.completed_work),
            "",
            "## Remaining Ordered Work",
            "",
            *[f"{idx}. {item}" for idx, item in enumerate(cfg.ordered_work, start=1)],
        ]),
    )

    return out


def main() -> int:
    parser = argparse.ArgumentParser(prog="system-validation")
    parser.add_argument("--output-root", default="evaluation/system-validation")
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = build_package(ROOT / args.output_root, run_id)
    print(f"system-validation evidence -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
