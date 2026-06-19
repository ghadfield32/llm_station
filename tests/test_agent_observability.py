"""
The centralized agent-call log: every tool call (any surface) is recorded with a truncated,
secret-safe arg summary; errors are recorded AND re-raised (never swallowed); the monitor
summary groups by surface/tool with error rates and median latency. Hermetic — no AppFlowy.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_GROWTHOS = Path(__file__).resolve().parents[1] / "appflowy_kanban" / "growth-os"
sys.path.insert(0, str(_GROWTHOS))

from growthos.observability import logged, read_calls, record_call, summarize  # noqa: E402


def test_logged_records_success_with_arg_keys(tmp_path):
    log = tmp_path / "calls.jsonl"

    def search(database, query):
        return ["a", "b"]

    logged(search, "assistant", path=log)(database="library", query="Turing")
    rows = read_calls(log)
    assert len(rows) == 1
    r = rows[0]
    assert r["tool"] == "search" and r["surface"] == "assistant" and r["ok"] is True
    assert set(r["args"]) == {"database", "query"} and isinstance(r["ms"], (int, float))


def test_logged_records_error_and_reraises(tmp_path):
    log = tmp_path / "c.jsonl"

    def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError):                 # the error is NOT swallowed
        logged(boom, "mcp", path=log)()
    r = read_calls(log)[0]
    assert r["ok"] is False and "nope" in r["detail"] and r["surface"] == "mcp"


def test_args_are_truncated_no_payload_bloat(tmp_path):
    log = tmp_path / "c.jsonl"
    logged(lambda note: "ok", "discord", path=log)(note="x" * 500)
    assert len(read_calls(log)[0]["args"]["note"]) <= 80      # never logs a large payload


def test_summary_groups_by_surface_tool_with_error_rate(tmp_path):
    log = tmp_path / "c.jsonl"
    record_call("assistant", "search", {"q": "a"}, ok=True, ms=10, path=log)
    record_call("assistant", "search", {"q": "b"}, ok=False, ms=20, detail="e", path=log)
    record_call("mcp", "book_note", {"t": "x"}, ok=True, ms=5, path=log)
    s = summarize(log)
    assert s["total_calls"] == 3
    by = {(r["surface"], r["tool"]): r for r in s["by_tool"]}
    assert by[("assistant", "search")]["calls"] == 2
    assert by[("assistant", "search")]["errors"] == 1
    assert by[("assistant", "search")]["error_rate"] == 0.5
    assert set(s["surfaces"]) == {"assistant", "mcp"}
    assert "book_note" in s["tools_used"]
