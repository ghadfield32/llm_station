"""Shared workspace-boundary contract for native agent-session adapters.

The native CLIs own their filesystem tools, so the common enforcement seam is
the first-turn instruction sent to the model. Claude may additionally gain a
CLI-level read deny when its installed help explicitly documents one; this
module never assumes a flag or permission-rule grammar from another version.
"""
from __future__ import annotations

import subprocess
from functools import lru_cache
from os import fspath
from pathlib import Path

from .secret_paths import is_secret_path

_SECRET_PATH_EXAMPLES = (
    ".ssh",
    ".aws",
    ".azure",
    ".gnupg",
    ".env",
    ".env.local",
    "credentials",
    "secrets",
    "id_rsa",
    "id_ed25519",
    "private.pem",
    "private.key",
)


def workspace_bounds_instruction(
    workspace_root: str | Path,
    context_id: str,
) -> str:
    """Return the mandatory filesystem contract for one resolved context."""
    root = fspath(workspace_root)
    secret_examples = ", ".join(
        f"`{path}`" for path in _SECRET_PATH_EXAMPLES if is_secret_path(path)
    )
    home_rule = ""
    if context_id == "home_workspace":
        home_rule = (
            "\n- This is `home_workspace`: use targeted reads of specific, necessary paths "
            "only. Never enumerate the full home tree or run full-tree traversal or "
            "recursive scans."
        )

    return (
        "[WORKSPACE BOUNDS — MANDATORY]\n"
        f"- Context ID: `{context_id}`\n"
        f"- Workspace root: `{root}`\n"
        "- The workspace root above is the ONLY search space. Do not read, glob, grep, "
        "list, resolve, or traverse any path outside it.\n"
        "- Secret paths recognized by "
        "`command_center.agent_sessions.secret_paths.is_secret_path` are always "
        f"off-limits, even inside the workspace. Examples include {secret_examples}, "
        "credential stores, browser profiles, private keys, and keystores."
        f"{home_rule}\n"
        "- If a request requires an outside-workspace or secret path, refuse that part "
        "and continue only with in-bounds, non-secret paths.\n"
        "[END WORKSPACE BOUNDS]"
    )


def prepend_workspace_bounds(
    prompt: str,
    workspace_root: str | Path,
    context_id: str,
) -> str:
    """Prepend the shared contract without changing the caller's prompt text."""
    return f"{workspace_bounds_instruction(workspace_root, context_id)}\n\n{prompt}"


@lru_cache(maxsize=8)
def _claude_help_output(claude_bin: str) -> str:
    """Read the installed CLI's help once per binary path."""
    try:
        result = subprocess.run(
            [claude_bin, "--help"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return f"{result.stdout or ''}\n{result.stderr or ''}"


def claude_cli_read_deny_args(
    claude_bin: str,
    workspace_root: str | Path,
) -> list[str]:
    """Return only runtime-documented Claude CLI read-path deny arguments.

    The currently installed CLI help advertises tool-wide ``--disallowedTools``
    and opaque ``--settings <file-or-json>`` inputs, but it does not document a
    read-path matcher or the settings permission schema. Those are not enough
    evidence to construct path rules safely, so no additions are emitted. Keep
    the root parameter in this API because a future, explicitly documented
    read-path seam must be scoped to this resolved workspace.
    """
    help_output = _claude_help_output(claude_bin)

    # A generic settings input or tool-wide deny is not proof of a path-scoped
    # Read rule grammar. The current help names both, but documents neither a
    # Read path matcher nor the settings permission schema. Inspect it, retain
    # the workspace-root API needed by a verified future seam, and emit nothing
    # rather than guessing a flag or rule syntax.
    _ = (help_output, fspath(workspace_root))
    return []
