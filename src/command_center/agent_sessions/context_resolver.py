"""One canonical context_id -> local path resolver for every agent adapter.

Before this, all four adapters (claude_code_local, codex_agent, claude_agent,
openrouter_agent) carried an identical private `_resolve_repo_path` that loaded
autonomy.yaml and looked up a manifest. They now delegate here, so:

  * the Home workspace (`home_workspace`) is special-cased in ONE place — it
    resolves to the user's home dir with no autonomy manifest required, and
  * registered repos still resolve through the single canonical
    `cli/repo_registry.resolve_repo_local_path` (path/symlink policy stays in
    exactly one place).

Resolution is intentionally lazy (called at session start, not at create), so a
context that isn't registered fails with a legible reason at the moment a
session actually needs it.
"""
from __future__ import annotations

import os
from pathlib import Path

from .home_workspace import HOME_WORKSPACE_ID, resolve_home_root

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AUTONOMY_CONFIG = _REPO_ROOT / "configs" / "autonomy.yaml"


def resolve_context_path(
    context_id: str, *, env: dict[str, str] | None = None,
) -> Path:
    """Resolve a session's context_id/repo_id to a local directory.

    The Home workspace resolves to the user's home dir (read-only sandbox — see
    home_workspace.py); every other id resolves through the canonical autonomy
    manifest resolver, unchanged.
    """
    env = env if env is not None else dict(os.environ)
    if context_id == HOME_WORKSPACE_ID:
        return resolve_home_root(env)

    # Delegate to cli/repo_registry's OWN resolver — never a reimplementation.
    from command_center.cli.repo_registry import (
        load_autonomy_config,
        resolve_repo_local_path,
    )
    if not _AUTONOMY_CONFIG.is_file():
        raise RuntimeError(f"configs/autonomy.yaml not found at {_AUTONOMY_CONFIG}")
    cfg = load_autonomy_config(_AUTONOMY_CONFIG)
    manifest = next(
        (m for m in cfg.repo_manifests if m.repo_id == context_id), None)
    if manifest is None:
        raise RuntimeError(
            f"repo_id {context_id!r} is not registered in configs/autonomy.yaml")
    path = resolve_repo_local_path(manifest, _REPO_ROOT, env)
    if path is None:
        raise RuntimeError(
            f"repo_id {context_id!r} has no resolvable local_path_ref "
            f"(got {manifest.local_path_ref!r})")
    return path
