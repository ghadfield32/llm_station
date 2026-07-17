"""Runtime fingerprint — the read-only drift detector for agent sessions.

The 2026-07-17 incident: a session died with 'AutonomyConfig
research_capabilities Extra inputs are not permitted' because a RUNNING
process (worker, then the cockpit container) held an OLD RepoManifest contract
in memory while reading a NEWER configs/autonomy.yaml. Strict validation caught
the drift — but only at session-creation time, as an opaque failure.

This module makes the drift observable BEFORE a session fails: it reports the
process's source root, git SHA, the SHA-256 of the configs it depends on, and —
critically — whether the RUNNING process's own contract can still validate the
on-disk config (`autonomy_validates`). `cc assistant-doctor` fetches this from
the worker and compares it to the host checkout, so the answer becomes
"FAIL — worker configuration does not match the active checkout" instead of a
mid-chat Pydantic traceback.

Pure filesystem reads; no session state, no network.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]

# The configs whose drift breaks agent sessions / board rendering. autonomy.yaml
# is the one that actually failed; the board configs gate the cockpit surfaces.
_TRACKED_CONFIGS = ("autonomy.yaml", "assistant-routing.yaml",
                    "frontier-router-budgets.yaml", "kanban_boards.yaml",
                    "domain_surfaces.yaml")


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_sha(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None


def _git_dirty(root: Path) -> bool | None:
    """True when the working tree has uncommitted changes — i.e. the running
    build is NOT from a committed SHA and is therefore not reproducible. Surfaced
    so a dirty-tree deployment is visible, not silent (release-stabilization §1)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10)
        return bool(out.stdout.strip())
    except Exception:
        return None


def _autonomy_validates(root: Path) -> tuple[bool, str | None]:
    """Does the RUNNING process's contract validate the on-disk autonomy.yaml?
    This is the live drift signal — True even when SHAs match but the loaded
    contract is stale means the process is current; False means restart/rebuild.
    """
    try:
        from command_center.cli.repo_registry import load_autonomy_config
        load_autonomy_config(root / "configs" / "autonomy.yaml")
        return True, None
    except Exception as exc:   # a ValidationError here IS the drift — report it
        return False, f"{type(exc).__name__}: {exc}"[:300]


def compute_fingerprint(root: Path = _REPO_ROOT) -> dict[str, Any]:
    """The read-only runtime fingerprint for THIS process (worker or cockpit)."""
    ok, detail = _autonomy_validates(root)
    return {
        "source_root": str(root),
        "git_sha": _git_sha(root),
        "git_dirty": _git_dirty(root),         # True = not a reproducible build
        "config_sha256": {
            name: _sha256(root / "configs" / name)
            for name in _TRACKED_CONFIGS
        },
        "autonomy_validates": ok,
        "autonomy_validation_error": detail,   # None when ok
    }
