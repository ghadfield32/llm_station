"""Pure rendering for the proactive job-review channel nudge."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _one_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def render_job_digest_ping(
    items: Sequence[Mapping[str, Any]],
    board_url: str,
) -> str | None:
    """Return one review nudge, or no message when there is nothing to review."""
    if not items:
        return None
    top = items[0]
    count = len(items)
    noun = "job" if count == 1 else "jobs"
    line = (
        f"{count} new {noun} to review"
        f" · top: {_one_line(top.get('company'))} — {_one_line(top.get('role'))}"
    )
    link = _one_line(board_url)
    return f"{line} · → {link}" if link else line
