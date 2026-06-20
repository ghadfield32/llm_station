#!/usr/bin/env python3
"""System doctor for local Command Center readiness.

The doctor is intentionally explicit: it reports local policy failures as
``FAIL``, missing external prerequisites as ``BLOCKED``, and checks skipped
because a prerequisite failed as ``NOT_RUN``. Evidence is redacted by design:
environment values, token material, private keys, screenshots, and credential
contents are never printed or written.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
from pydantic import ValidationError

from command_center.cli.branch_protection_verify import verify_branch_protection
from command_center.cli.check_forbidden_providers import (
    FORBIDDEN_KEYS,
    check_compose,
    check_env_files,
    check_litellm_config,
    check_models_yaml,
    check_process_env,
)
from command_center.cli.github_app_verify import verify_github_app
from command_center.schemas import (
    AutonomyConfig,
    ChannelsConfig,
    CONFIG_CONTRACTS,
    KanbanConfig,
    ModelRegistry,
    UIConfig,
)

ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = ROOT / ".env"
MODELS_YAML = ROOT / "configs" / "models.yaml"
KANBAN_YAML = ROOT / "configs" / "kanban.yaml"
UI_YAML = ROOT / "configs" / "ui.yaml"
AUTONOMY_YAML = ROOT / "configs" / "autonomy.yaml"
CHANNELS_YAML = ROOT / "configs" / "channels.yaml"
LITELLM_CONFIG = ROOT / "generated" / "litellm-config.yaml"
GITHUB_TIMEOUT_SECONDS = 30

Status = Literal["PASS", "FAIL", "BLOCKED", "NOT_RUN"]

SECRET_LITERAL_PATTERNS = {
    "github_classic_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "github_fine_grained_token": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}


@dataclass
class Check:
    check_id: str
    title: str
    status: Status
    blocker: str = ""
    next_command: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.check_id,
            "title": self.title,
            "status": self.status,
            "evidence": self.evidence,
        }
        if self.blocker:
            payload["blocker"] = self.blocker
        if self.next_command:
            payload["next_command"] = self.next_command
        return payload


def _read_dotenv(path: Path = ENV_PATH) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _merged_env() -> dict[str, str]:
    return {**_read_dotenv(), **os.environ}


def _env_presence(names: list[str], env: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {"name": name, "present": bool(env.get(name)), "length": len(env.get(name, ""))}
        for name in names
    ]


def _run(
    cmd: list[str],
    *,
    timeout: int,
    cwd: Path = ROOT,
) -> tuple[int | None, str, str, bool]:
    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return None, "", str(exc), False
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return None, stdout, stderr, True
    return completed.returncode, completed.stdout, completed.stderr, False


def _command_evidence(cmd: list[str], returncode: int | None, timed_out: bool = False) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "command": cmd,
        "returncode": returncode,
    }
    if timed_out:
        evidence["timed_out"] = True
    return evidence


def _socket_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _http_check(name: str, url: str, next_command: str) -> Check:
    try:
        response = httpx.get(url, timeout=5)
    except httpx.HTTPError as exc:
        return Check(
            name,
            name.replace("_", " "),
            "BLOCKED",
            blocker=f"{url} is not reachable: {exc.__class__.__name__}",
            next_command=next_command,
            evidence={"url": url, "reachable": False},
        )
    if response.status_code >= 400:
        return Check(
            name,
            name.replace("_", " "),
            "BLOCKED",
            blocker=f"{url} returned HTTP {response.status_code}",
            next_command=next_command,
            evidence={"url": url, "status_code": response.status_code},
        )
    return Check(
        name,
        name.replace("_", " "),
        "PASS",
        evidence={"url": url, "status_code": response.status_code},
    )


def check_python() -> Check:
    ok = sys.version_info >= (3, 12)
    return Check(
        "python_version",
        "Python version",
        "PASS" if ok else "FAIL",
        blocker="" if ok else "Python 3.12 or newer is required",
        next_command="" if ok else "install Python 3.12+ and rerun uv run cc doctor",
        evidence={"version": platform.python_version(), "implementation": platform.python_implementation()},
    )


def check_uv_available() -> Check:
    path = shutil.which("uv")
    return Check(
        "uv_available",
        "uv available",
        "PASS" if path else "BLOCKED",
        blocker="" if path else "uv is not on PATH",
        next_command="" if path else "install uv, then rerun uv run cc doctor",
        evidence={"path_present": bool(path)},
    )


def check_uv_sync(uv_check: Check) -> Check:
    if uv_check.status != "PASS":
        return Check(
            "uv_sync_frozen",
            "uv sync frozen",
            "NOT_RUN",
            blocker="uv is not available",
            next_command="install uv, then run uv sync --frozen --extra dev --extra gateways",
            evidence={"dependency": uv_check.check_id},
        )
    cmd = ["uv", "sync", "--frozen", "--extra", "dev", "--extra", "gateways"]
    returncode, _, _, timed_out = _run(cmd, timeout=300)
    ok = returncode == 0
    return Check(
        "uv_sync_frozen",
        "uv sync frozen",
        "PASS" if ok else "FAIL",
        blocker="" if ok else "uv sync --frozen did not complete successfully",
        next_command="" if ok else "uv sync --frozen --extra dev --extra gateways",
        evidence=_command_evidence(cmd, returncode, timed_out),
    )


def check_docker_available() -> Check:
    if not shutil.which("docker"):
        return Check(
            "docker_available",
            "Docker available",
            "BLOCKED",
            blocker="docker is not on PATH",
            next_command="install Docker Desktop or Docker Engine, then rerun uv run cc doctor",
            evidence={"path_present": False},
        )
    cmd = ["docker", "info"]
    returncode, _, _, timed_out = _run(cmd, timeout=30)
    ok = returncode == 0
    return Check(
        "docker_available",
        "Docker daemon",
        "PASS" if ok else "BLOCKED",
        blocker="" if ok else "docker is installed but the daemon is not reachable",
        next_command="" if ok else "start Docker Desktop, then rerun uv run cc doctor",
        evidence=_command_evidence(cmd, returncode, timed_out),
    )


def check_docker_compose(docker_check: Check) -> Check:
    if docker_check.status != "PASS":
        return Check(
            "docker_compose_available",
            "Docker Compose available",
            "NOT_RUN",
            blocker="Docker daemon is not ready",
            next_command="start Docker Desktop, then rerun uv run cc doctor",
            evidence={"dependency": docker_check.check_id},
        )
    cmd = ["docker", "compose", "version"]
    returncode, _, _, timed_out = _run(cmd, timeout=30)
    ok = returncode == 0
    return Check(
        "docker_compose_available",
        "Docker Compose available",
        "PASS" if ok else "BLOCKED",
        blocker="" if ok else "docker compose is not available",
        next_command="" if ok else "install Docker Compose, then rerun uv run cc doctor",
        evidence=_command_evidence(cmd, returncode, timed_out),
    )


def check_config_contracts() -> Check:
    failures: list[str] = []
    validated: list[str] = []
    for rel_path, contract in CONFIG_CONTRACTS.items():
        path = ROOT / rel_path
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            contract.model_validate(data)
            validated.append(rel_path)
        except FileNotFoundError:
            failures.append(f"{rel_path}: missing")
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(part) for part in first.get("loc", ()))
            failures.append(f"{rel_path}: {loc}: {first.get('msg')}")
        except Exception as exc:  # noqa: BLE001 - surfaced as explicit doctor evidence.
            failures.append(f"{rel_path}: {exc}")
    return Check(
        "config_contracts",
        "Config contracts",
        "PASS" if not failures else "FAIL",
        blocker="; ".join(failures[:3]) if failures else "",
        next_command="" if not failures else "uv run cc validate",
        evidence={"validated": validated, "failure_count": len(failures), "failures": failures[:10]},
    )


def check_model_roles(config_check: Check) -> Check:
    if config_check.status != "PASS":
        return Check(
            "model_roles_resolve",
            "Configured model roles resolve",
            "NOT_RUN",
            blocker="config contracts did not pass",
            next_command="uv run cc validate",
            evidence={"dependency": config_check.check_id},
        )

    registry = ModelRegistry.model_validate(yaml.safe_load(MODELS_YAML.read_text(encoding="utf-8")))
    roles = sorted(registry.roles)
    whitelist = set(registry.local_whitelist)
    missing_whitelist = sorted(
        {
            candidate.model
            for candidates in registry.roles.values()
            for candidate in candidates
            if candidate.local and candidate.model not in whitelist
        }
    )
    if missing_whitelist:
        return Check(
            "model_roles_resolve",
            "Configured model roles resolve",
            "FAIL",
            blocker=f"local model(s) missing from local_whitelist: {', '.join(missing_whitelist)}",
            next_command="edit configs/models.yaml, then run uv run cc validate",
            evidence={"roles": roles, "missing_from_local_whitelist": missing_whitelist},
        )

    if not LITELLM_CONFIG.is_file():
        return Check(
            "model_roles_resolve",
            "Configured model roles resolve",
            "FAIL",
            blocker="generated/litellm-config.yaml is missing",
            next_command="uv run cc render",
            evidence={"roles": roles, "rendered_config_present": False},
        )
    rendered = yaml.safe_load(LITELLM_CONFIG.read_text(encoding="utf-8")) or {}
    rendered_roles = sorted(
        {
            str(entry.get("model_name"))
            for entry in rendered.get("model_list", [])
            if isinstance(entry, dict) and entry.get("model_name")
        }
    )
    missing_rendered = sorted(set(roles) - set(rendered_roles))
    if missing_rendered:
        return Check(
            "model_roles_resolve",
            "Configured model roles resolve",
            "FAIL",
            blocker=f"generated LiteLLM config missing role(s): {', '.join(missing_rendered)}",
            next_command="uv run cc render",
            evidence={"roles": roles, "rendered_roles": rendered_roles},
        )
    return Check(
        "model_roles_resolve",
        "Configured model roles resolve",
        "PASS",
        evidence={"roles": roles, "rendered_roles": rendered_roles},
    )


def check_ollama() -> Check:
    return _http_check(
        "ollama_reachable",
        "http://127.0.0.1:11434/api/version",
        "start Ollama, then rerun uv run cc doctor",
    )


def check_litellm() -> Check:
    return _http_check(
        "litellm_reachable",
        "http://127.0.0.1:4000/health/liveliness",
        "uv run cc bootstrap-local",
    )


def check_ledger() -> Check:
    env = _merged_env()
    port = env.get("LEDGER_HOST_PORT", "8091")
    url = f"http://127.0.0.1:{port}/health"
    return _http_check("ledger_reachable", url, "uv run cc bootstrap-local")


def check_appflowy_config(config_check: Check) -> Check:
    if config_check.status != "PASS":
        return Check(
            "appflowy_config",
            "AppFlowy config",
            "NOT_RUN",
            blocker="config contracts did not pass",
            next_command="uv run cc validate",
            evidence={"dependency": config_check.check_id},
        )

    cfg = KanbanConfig.model_validate(yaml.safe_load(KANBAN_YAML.read_text(encoding="utf-8")))
    enabled = [
        source
        for source in cfg.sources
        if source.enabled and source.kind == "appflowy"
    ]
    if not enabled:
        return Check(
            "appflowy_config",
            "AppFlowy config",
            "PASS",
            evidence={"enabled_appflowy_sources": []},
        )

    env = _merged_env()
    missing: list[str] = []
    source_results: list[dict[str, Any]] = []
    for source in enabled:
        growthos_root = ROOT / source.growthos_root
        database_map = growthos_root / source.database_map_path
        env_names = [
            source.base_url_env,
            source.workspace_id_env,
            source.email_env,
            source.password_env,
        ]
        missing_env = [name for name in env_names if name and not env.get(name)]
        source_result = {
            "name": source.name,
            "growthos_root": source.growthos_root,
            "growthos_root_exists": growthos_root.is_dir(),
            "database_map_path": str(Path(source.growthos_root) / source.database_map_path),
            "database_map_exists": database_map.is_file(),
            "env": _env_presence([name for name in env_names if name], env),
        }
        source_results.append(source_result)
        if not growthos_root.is_dir():
            missing.append(f"{source.name}: missing growthos_root {source.growthos_root}")
        if not database_map.is_file():
            missing.append(
                f"{source.name}: missing database map "
                f"{Path(source.growthos_root) / source.database_map_path}"
            )
        for env_name in missing_env:
            missing.append(f"{source.name}: missing env {env_name}")

    return Check(
        "appflowy_config",
        "AppFlowy config",
        "PASS" if not missing else "BLOCKED",
        blocker="; ".join(missing[:5]) if missing else "",
        next_command="" if not missing else "set AppFlowy env refs, then run uv run cc kanban-bridge --dry-run",
        evidence={"sources": source_results},
    )


def check_internal_ui_config(config_check: Check) -> Check:
    if config_check.status != "PASS":
        return Check(
            "internal_ui_config",
            "Internal UI config",
            "NOT_RUN",
            blocker="config contracts did not pass",
            next_command="uv run cc validate",
            evidence={"dependency": config_check.check_id},
        )
    cfg = UIConfig.model_validate(yaml.safe_load(UI_YAML.read_text(encoding="utf-8")))
    ui = cfg.agent_kanban_ui
    service_files = [
        "services/agent_kanban_ui/app.py",
        "services/agent_kanban_ui/web/package.json",
        "services/agent_kanban_ui/web/src/App.tsx",
    ]
    missing_files = [rel for rel in service_files if not (ROOT / rel).is_file()]
    if not ui.enabled:
        return Check(
            "internal_ui_config",
            "Internal UI config",
            "PASS",
            evidence={"enabled": False, "service_files_present": len(missing_files) == 0},
        )
    return Check(
        "internal_ui_config",
        "Internal UI config",
        "PASS" if not missing_files else "FAIL",
        blocker="" if not missing_files else f"missing UI file(s): {', '.join(missing_files)}",
        next_command="" if not missing_files else "restore internal UI files, then run uv run cc validate",
        evidence={
            "enabled": True,
            "host": ui.host,
            "port": ui.port,
            "external_write_policy": ui.external_write_policy,
            "missing_files": missing_files,
        },
    )


def check_airflow_dag_folder() -> Check:
    folder = ROOT / "dags"
    dag = folder / "self_improvement_daily.py"
    missing: list[str] = []
    if not folder.is_dir():
        missing.append("dags folder is missing")
    if not dag.is_file():
        missing.append("dags/self_improvement_daily.py is missing")
    return Check(
        "airflow_dag_folder",
        "Airflow DAG folder",
        "PASS" if not missing else "FAIL",
        blocker="; ".join(missing),
        next_command="" if not missing else "restore dags/self_improvement_daily.py",
        evidence={"dags_dir_exists": folder.is_dir(), "self_improvement_daily_exists": dag.is_file()},
    )


def check_github_env_refs(config_check: Check) -> Check:
    if config_check.status != "PASS":
        return Check(
            "github_app_env_refs",
            "GitHub App env refs",
            "NOT_RUN",
            blocker="config contracts did not pass",
            next_command="uv run cc validate",
            evidence={"dependency": config_check.check_id},
        )
    cfg = AutonomyConfig.model_validate(yaml.safe_load(AUTONOMY_YAML.read_text(encoding="utf-8")))
    auth = cfg.github_app_auth
    required = [
        auth.app_id_env,
        auth.client_id_env,
        auth.private_key_path_env,
    ]
    optional = [auth.installation_id_env]
    if auth.webhook_active and auth.webhook_secret_env:
        required.append(auth.webhook_secret_env)
    elif auth.webhook_secret_env:
        optional.append(auth.webhook_secret_env)
    env = _merged_env()
    missing_required = [name for name in required if not env.get(name)]
    return Check(
        "github_app_env_refs",
        "GitHub App env refs",
        "PASS" if not missing_required else "BLOCKED",
        blocker="" if not missing_required else f"missing env ref(s): {', '.join(missing_required)}",
        next_command="" if not missing_required else "set GitHub App env refs in .env, then run uv run cc doctor",
        evidence={
            "required": _env_presence(required, env),
            "optional": _env_presence(optional, env),
            "selected_repositories": auth.selected_repositories,
        },
    )


def check_github_app_installed(github_env_check: Check) -> Check:
    if github_env_check.status != "PASS":
        return Check(
            "github_app_installed",
            "GitHub App installed",
            "NOT_RUN",
            blocker="GitHub App env refs are missing",
            next_command="set GitHub App env refs, then run uv run cc github-app-verify",
            evidence={"dependency": github_env_check.check_id},
        )
    try:
        result = verify_github_app()
    except Exception as exc:  # noqa: BLE001 - surfaced as explicit doctor evidence.
        return Check(
            "github_app_installed",
            "GitHub App installed",
            "BLOCKED",
            blocker=f"github-app-verify could not complete: {exc.__class__.__name__}",
            next_command="uv run cc github-app-verify",
            evidence={"exception_type": exc.__class__.__name__},
        )
    ok = result.get("status") == "pass"
    return Check(
        "github_app_installed",
        "GitHub App installed",
        "PASS" if ok else "BLOCKED",
        blocker="" if ok else "; ".join(result.get("blockers", [])[:5]),
        next_command="" if ok else "uv run cc github-app-verify",
        evidence={
            "status": result.get("status"),
            "repositories": result.get("repositories", []),
            "branch_protection": result.get("branch_protection", []),
            "env": result.get("env", []),
            "writes_performed": result.get("writes_performed"),
            "secrets_printed": result.get("secrets_printed"),
        },
    )


def check_branch_protection(config_check: Check) -> Check:
    if config_check.status != "PASS":
        return Check(
            "branch_protection_verified",
            "Branch protection verified",
            "NOT_RUN",
            blocker="config contracts did not pass",
            next_command="uv run cc validate",
            evidence={"dependency": config_check.check_id},
        )
    try:
        result = verify_branch_protection(output=None)
    except Exception as exc:  # noqa: BLE001 - surfaced as explicit doctor evidence.
        return Check(
            "branch_protection_verified",
            "Branch protection verified",
            "BLOCKED",
            blocker=f"branch-protection-verify could not complete: {exc.__class__.__name__}",
            next_command="uv run cc branch-protection-verify",
            evidence={"exception_type": exc.__class__.__name__},
        )
    ok = result.get("status") == "pass"
    return Check(
        "branch_protection_verified",
        "Branch protection verified",
        "PASS" if ok else "BLOCKED",
        blocker="" if ok else "; ".join(result.get("blockers", [])[:5]),
        next_command="" if ok else "uv run cc branch-protection-verify",
        evidence={
            "status": result.get("status"),
            "workflow_source": result.get("workflow_source"),
            "workflow_jobs": result.get("workflow_jobs"),
            "repositories": result.get("repositories", []),
            "env": result.get("env", []),
            "writes_performed": result.get("writes_performed"),
            "secrets_printed": result.get("secrets_printed"),
        },
    )


def check_repo_paths(config_check: Check) -> Check:
    if config_check.status != "PASS":
        return Check(
            "repo_manifest_paths",
            "Repo manifest paths",
            "NOT_RUN",
            blocker="config contracts did not pass",
            next_command="uv run cc validate",
            evidence={"dependency": config_check.check_id},
        )
    cfg = AutonomyConfig.model_validate(yaml.safe_load(AUTONOMY_YAML.read_text(encoding="utf-8")))
    blockers: list[str] = []
    repos: list[dict[str, Any]] = []
    for repo in cfg.repo_manifests:
        repo_root = ROOT
        devcontainer_present = True
        if repo.execution_mode == "devcontainer":
            devcontainer_present = bool(repo.devcontainer_path and (repo_root / repo.devcontainer_path).is_file())
            if not devcontainer_present:
                blockers.append(f"{repo.repo_id}: missing devcontainer {repo.devcontainer_path}")
        codeowners_present = True
        if repo.codeowners_required:
            codeowners_present = bool(repo.codeowners_path and (repo_root / repo.codeowners_path).is_file())
            if not codeowners_present:
                blockers.append(f"{repo.repo_id}: missing CODEOWNERS {repo.codeowners_path}")
        repos.append({
            "repo_id": repo.repo_id,
            "execution_mode": repo.execution_mode,
            "devcontainer_path": repo.devcontainer_path,
            "devcontainer_present": devcontainer_present,
            "codeowners_path": repo.codeowners_path,
            "codeowners_present": codeowners_present,
            "ci_command_count": len(repo.ci_commands),
            "autonomous_edits_enabled": repo.autonomous_edits_enabled,
        })
    return Check(
        "repo_manifest_paths",
        "Repo manifest paths",
        "PASS" if not blockers else "FAIL",
        blocker="; ".join(blockers[:5]),
        next_command="" if not blockers else "restore missing repo guardrail files, then run uv run cc validate",
        evidence={"repos": repos},
    )


def check_forbidden_provider_scan() -> Check:
    errors: list[str] = []
    check_env_files(errors)
    check_process_env(errors)
    check_compose(errors)
    check_models_yaml(errors)
    check_litellm_config(errors)
    return Check(
        "forbidden_provider_scan",
        "Forbidden provider scan",
        "PASS" if not errors else "FAIL",
        blocker="; ".join(errors[:5]),
        next_command="" if not errors else "remove forbidden provider keys/routes, then run uv run cc forbidden-providers",
        evidence={"forbidden_keys": sorted(FORBIDDEN_KEYS), "error_count": len(errors), "errors": errors[:10]},
    )


def _tracked_files_for_secret_scan() -> list[Path]:
    cmd = [
        "git",
        "ls-files",
        "--",
        ".env.example",
        ".github",
        "configs",
        "docker-compose.yml",
        "pyproject.toml",
        "dags",
    ]
    returncode, stdout, _, _ = _run(cmd, timeout=30)
    if returncode != 0:
        return []
    return [ROOT / line for line in stdout.splitlines() if line.strip()]


def check_committed_config_secret_scan() -> Check:
    findings: list[dict[str, str]] = []
    scanned = 0
    for path in _tracked_files_for_secret_scan():
        if not path.is_file():
            continue
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for name, pattern in SECRET_LITERAL_PATTERNS.items():
            if pattern.search(text):
                findings.append({"path": rel, "pattern": name})
    return Check(
        "committed_config_secret_scan",
        "Committed config secret scan",
        "PASS" if not findings else "FAIL",
        blocker="" if not findings else f"secret-like literal(s) found in {len(findings)} tracked file(s)",
        next_command="" if not findings else "remove secret material from tracked files, then rotate any exposed credential",
        evidence={"scanned_file_count": scanned, "findings": findings},
    )


def check_dirty_generated_evidence(expected_outputs: set[Path]) -> Check:
    cmd = ["git", "status", "--porcelain", "--", "generated", "evaluation"]
    returncode, stdout, _, timed_out = _run(cmd, timeout=30)
    if returncode != 0:
        return Check(
            "dirty_generated_evidence",
            "Dirty generated evidence",
            "BLOCKED",
            blocker="could not inspect generated/evaluation git status",
            next_command="git status --porcelain -- generated evaluation",
            evidence=_command_evidence(cmd, returncode, timed_out),
        )
    dirty: list[str] = []
    for line in stdout.splitlines():
        path_text = line[3:].strip()
        if not path_text:
            continue
        path = (ROOT / path_text).resolve()
        if any(
            path == expected
            or path in expected.parents
            or expected.is_relative_to(path)
            for expected in expected_outputs
        ):
            continue
        dirty.append(line)
    return Check(
        "dirty_generated_evidence",
        "Dirty generated evidence",
        "PASS" if not dirty else "FAIL",
        blocker="" if not dirty else "dirty generated/evaluation evidence exists",
        next_command="" if not dirty else "review or clean generated/evaluation evidence before readiness claims",
        evidence={
            "dirty_entries": dirty,
            "expected_outputs": [
                p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else p.name
                for p in sorted(expected_outputs)
            ],
        },
    )


def check_channel_token_presence(config_check: Check) -> Check:
    if config_check.status != "PASS":
        return Check(
            "channel_token_refs",
            "Channel token refs",
            "NOT_RUN",
            blocker="config contracts did not pass",
            next_command="uv run cc validate",
            evidence={"dependency": config_check.check_id},
        )
    channels = ChannelsConfig.model_validate(yaml.safe_load(CHANNELS_YAML.read_text(encoding="utf-8")))
    env = _merged_env()
    required_by_transport = {
        "discord": ["DISCORD_BOT_TOKEN", "DISCORD_ALLOWED_CHANNEL_IDS"],
        "slack": ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
        "telegram": ["TELEGRAM_BOT_TOKEN"],
        "whatsapp": ["WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_VERIFY_TOKEN"],
        "sms": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"],
    }
    enabled_results: list[dict[str, Any]] = []
    missing: list[str] = []
    for channel in channels.channels:
        if not channel.enabled:
            continue
        keys = required_by_transport.get(channel.transport, [])
        missing_keys = [key for key in keys if not env.get(key)]
        missing.extend(f"{channel.name}: {key}" for key in missing_keys)
        enabled_results.append({
            "name": channel.name,
            "transport": channel.transport,
            "model": channel.model,
            "env": _env_presence(keys, env),
        })
    return Check(
        "channel_token_refs",
        "Channel token refs",
        "PASS" if not missing else "BLOCKED",
        blocker="" if not missing else f"missing enabled channel env ref(s): {', '.join(missing)}",
        next_command="" if not missing else "set enabled channel token env refs or disable the channel in configs/channels.yaml",
        evidence={"enabled_channels": enabled_results},
    )


def collect_checks(*, expected_outputs: set[Path] | None = None) -> list[Check]:
    expected_outputs = expected_outputs or set()
    checks: list[Check] = []

    python_check = check_python()
    uv_check = check_uv_available()
    docker_check = check_docker_available()
    config_check = check_config_contracts()
    github_env_check = check_github_env_refs(config_check)

    checks.extend([
        python_check,
        uv_check,
        check_uv_sync(uv_check),
        docker_check,
        check_docker_compose(docker_check),
        config_check,
        check_model_roles(config_check),
        check_ollama(),
        check_litellm(),
        check_ledger(),
        check_appflowy_config(config_check),
        check_internal_ui_config(config_check),
        check_airflow_dag_folder(),
        github_env_check,
        check_github_app_installed(github_env_check),
        check_branch_protection(config_check),
        check_repo_paths(config_check),
        check_forbidden_provider_scan(),
        check_committed_config_secret_scan(),
        check_dirty_generated_evidence(expected_outputs),
        check_channel_token_presence(config_check),
    ])
    return checks


def _summary(checks: list[Check]) -> dict[str, Any]:
    counts = {status: 0 for status in ("PASS", "FAIL", "BLOCKED", "NOT_RUN")}
    for check in checks:
        counts[check.status] += 1
    overall = "PASS" if counts["FAIL"] == 0 and counts["BLOCKED"] == 0 else "BLOCKED"
    if counts["FAIL"]:
        overall = "FAIL"
    return {"status": overall, "counts": counts}


def _report(checks: list[Check]) -> dict[str, Any]:
    return {
        "schema_version": "command-center.doctor.v1",
        "repo": ROOT.name,
        "summary": _summary(checks),
        "checks": [check.as_dict() for check in checks],
        "safety": {
            "secrets_printed": False,
            "secret_values_recorded": False,
            "repo_source_writes_performed": False,
            "external_writes_performed": False,
            "venv_sync_may_write": True,
            "provider_api_keys_allowed": False,
            "direct_main_push": False,
            "merge_automation": False,
            "branch_protection_weakened": False,
            "desktop_live_actions": False,
        },
    }


def print_human(report: dict[str, Any]) -> None:
    checks = report["checks"]
    width = max(len(check["id"]) for check in checks)
    for check in checks:
        print(f"[{check['status']:<7}] {check['id']:<{width}}  {check['title']}")
        if blocker := check.get("blocker"):
            print(f"          blocker: {blocker}")
        if next_command := check.get("next_command"):
            print(f"          next: {next_command}")
    summary = report["summary"]
    counts = summary["counts"]
    print()
    print(
        "doctor: "
        f"{summary['status']} "
        f"(PASS={counts['PASS']} FAIL={counts['FAIL']} "
        f"BLOCKED={counts['BLOCKED']} NOT_RUN={counts['NOT_RUN']})"
    )
    print("doctor evidence: redacted JSON available with --json or --output <path>")


def _resolve_output(path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def main() -> int:
    parser = argparse.ArgumentParser(prog="doctor")
    parser.add_argument("--json", action="store_true", help="print the full redacted JSON report")
    parser.add_argument("--output", default="", help="write the redacted JSON report to this path")
    args = parser.parse_args()

    expected_outputs: set[Path] = set()
    output_path = _resolve_output(args.output) if args.output else None
    if output_path is not None:
        expected_outputs.add(output_path)

    checks = collect_checks(expected_outputs=expected_outputs)
    report = _report(checks)

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_human(report)
        if output_path is not None:
            print(f"evidence -> {output_path.relative_to(ROOT).as_posix()}")

    status = report["summary"]["status"]
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
