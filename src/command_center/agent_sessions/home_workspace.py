"""The Home workspace — a sandboxed, read-only context over the user's home dir.

Per the plan (§5): "Home should be a workspace, not a fake repo." Registering
`C:\\Users\\ghadf` as an ordinary repo would silently grant recursive access,
including to credential stores. Instead the Home workspace is a first-class
context with three properties baked in:

  * read-only by default (no writes without a governed promotion),
  * canonicalized single root (no escaping it via `..`/symlinks), and
  * credential/secret locations denied (shared `secret_paths` denylist).

The reserved context id is `home_workspace`; it needs NO autonomy.yaml manifest
(the shared context resolver special-cases it). `is_readable()` is the gate the
adapter-owned read-only tools call; native runtimes (Claude/Codex) additionally
run read-only so they cannot write regardless.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .secret_paths import is_secret_path

# Reserved context id — a session with this repo_id resolves to the home root
# below instead of an autonomy manifest.
HOME_WORKSPACE_ID = "home_workspace"


def resolve_home_root(env: dict[str, str] | None = None) -> Path:
    """The user's home directory, canonicalized. Windows USERPROFILE first,
    then POSIX HOME. Raises rather than guessing when neither is set."""
    env = env if env is not None else dict(os.environ)
    home = env.get("USERPROFILE") or env.get("HOME")
    if not home:
        raise RuntimeError(
            "Home workspace unavailable: neither USERPROFILE nor HOME is set")
    return Path(home).resolve()


@dataclass(frozen=True)
class HomeWorkspace:
    """Resolved Home workspace policy for a session."""
    root: Path
    read_only: bool = True

    def is_readable(self, rel: str) -> bool:
        """True only if `rel` stays inside the home root AND is not a secret
        path. The single gate for adapter-owned reads over the home workspace."""
        if is_secret_path(rel):
            return False
        try:
            target = (self.root / rel).resolve()
        except (OSError, ValueError):
            return False
        root = self.root.resolve()
        if target != root and root not in target.parents:
            return False          # escaped the workspace (.. / symlink)
        # a secret can also sit at an absolute path once resolved
        return not is_secret_path(str(target))


def load_home_workspace(env: dict[str, str] | None = None) -> HomeWorkspace:
    return HomeWorkspace(root=resolve_home_root(env), read_only=True)


def home_workspace_descriptor(env: dict[str, str] | None = None) -> dict[str, Any]:
    """UI/context descriptor — what the picker shows for the Home workspace,
    including an honest one-line disclosure of what is denied."""
    ws = load_home_workspace(env)
    return {
        "context_id": HOME_WORKSPACE_ID,
        "label": "Home workspace",
        "root": str(ws.root),
        "read_only": ws.read_only,
        "denied_summary": (
            "credential & secret locations (.ssh, .aws, .azure, .gnupg, .env, "
            "private keys, browser profiles) stay unreadable"),
    }
