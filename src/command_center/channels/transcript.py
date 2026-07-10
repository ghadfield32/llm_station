"""Full-fidelity turn transcripts — the flight recorder for every GatewayCore
surface (app/Discord/Slack/SMS/Telegram/WhatsApp).

The complete story of a turn (full tool args, full tool results, which context
blocks were injected, the final answer) exists only inside GatewayCore's
per-turn message assembly — the SSE stream truncates args/results and history
is an in-memory deque lost on restart. This module captures that story at the
source, one JSONL line per turn, per conversation file.

Rules:
- FAIL-OPEN: a recorder error must never abort or degrade a turn.
- Private runtime state: files live under GATEWAY_TRANSCRIPT_DIR (default
  generated/chat-transcripts/), which is gitignored — transcripts contain
  conversation content and must never be committed.
- `current_conversation` is a ContextVar the tool layer may read (guarded
  import) so agent_calls.jsonl rows become joinable to threads.
"""
from __future__ import annotations

import json
import os
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Join key for observability: set for the duration of a turn.
current_conversation: ContextVar[str | None] = ContextVar(
    "gateway_conversation", default=None)

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")
# src/command_center/channels/ -> repo root. The default must be ANCHORED:
# load_tool_layer os.chdir()s into growth-os, and a cwd-relative default would
# silently write conversation content to an un-gitignored path there.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Fail-open makes recording gaps silent by design; this counter makes them
# visible (surfaced through the cockpit's /api/chat/threads storage info).
_write_failures = 0


def write_failure_count() -> int:
    return _write_failures


def transcript_dir() -> Path:
    configured = os.environ.get("GATEWAY_TRANSCRIPT_DIR")
    if configured:
        return Path(configured)
    return _REPO_ROOT / "generated" / "chat-transcripts"


def transcripts_enabled() -> bool:
    """Privacy kill-switch: GATEWAY_TRANSCRIPTS=0 stops writing turn files.
    The conversation_id contextvar (join key) stays active either way — it
    carries no content."""
    return os.environ.get("GATEWAY_TRANSCRIPTS", "1").strip().lower() not in {
        "0", "false", "off"}


def _safe_name(conversation_id: Any) -> str:
    return _SAFE_RE.sub("_", str(conversation_id))[:200] or "_"


def transcript_path(conversation_id: Any) -> Path:
    return transcript_dir() / f"{_safe_name(conversation_id)}.jsonl"


def read_transcript(conversation_id: Any) -> list[dict]:
    """Parsed turns for one conversation (oldest first). Missing file -> []."""
    path = transcript_path(conversation_id)
    if not path.is_file():
        return []
    turns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                turns.append(json.loads(line))
            except json.JSONDecodeError:
                turns.append({"corrupt_line": line[:200]})
    return turns


class TurnRecorder:
    """Accumulates one turn's full-fidelity events; flush() appends one JSONL
    line. Every public method is exception-proof (fail-open by contract)."""

    def __init__(self, *, surface: str, model: str, conversation_id: Any,
                 user_text: str):
        self.row: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "conversation_id": str(conversation_id),
            "surface": surface,
            "model_role": model,
            "user_text": user_text,
            "context_blocks": [],
            "events": [],
            "final": None,
        }
        self._token = None
        try:
            self._token = current_conversation.set(str(conversation_id))
        except Exception:
            pass

    def context(self, kind: str) -> None:
        try:
            self.row["context_blocks"].append(kind)
        except Exception:
            pass

    def event(self, type_: str, **payload: Any) -> None:
        try:
            self.row["events"].append(
                {"type": type_, "ts": datetime.now(timezone.utc).isoformat(),
                 **{k: v for k, v in payload.items()}})
        except Exception:
            pass

    def tool(self, name: str, raw_args: str) -> None:
        self.event("tool", name=name, args=raw_args)          # FULL args

    def tool_result(self, name: str, result: Any) -> None:
        self.event("tool_result", name=name,
                   result=str(result))                        # FULL result

    def usage(self, usage: Any) -> None:
        """Per-completion token counts from the gateway response, when present
        (closes the cost-visibility gap vs dedicated observability tools)."""
        try:
            if usage:
                self.event("usage", **dict(usage))
        except Exception:
            pass

    def final(self, content: str) -> None:
        try:
            self.row["final"] = content
        except Exception:
            pass

    def flush(self) -> None:
        global _write_failures
        try:
            if transcripts_enabled():
                path = transcript_path(self.row["conversation_id"])
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(self.row, ensure_ascii=False,
                                        default=str) + "\n")
        except Exception:
            _write_failures += 1  # fail-open, but visibly: never break a turn
        finally:
            try:
                if self._token is not None:
                    current_conversation.reset(self._token)
            except Exception:
                pass
