"""
Centralized agent-call log — one append-only JSONL recording EVERY tool call across every
surface (Discord, the local Ollama assistant, and the MCP/Claude agent), so you can check the
agents are working and monitor them whenever you like.

All three surfaces build their dispatch table from the same `TOOL_FNS`, so wrapping each entry
with `logged(fn, surface)` captures every call uniformly: which surface, which tool, a truncated
argument summary (tool args carry no secrets — tokens live in .env, never passed to a tool),
ok/error, and latency. The log is anchored to ONE file regardless of the caller's working
directory, so Discord (run from llm_station) and the assistant (run from growth-os) write the
same log. `python -m growthos.observability` prints a live monitor.

No swallowing: `logged` records an error and RE-RAISES — the surface's own loop still sees it.
"""
from __future__ import annotations

import functools
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable

# one consistent log file, anchored to the growth-os dir (not the caller's CWD)
_DEFAULT_LOG = Path(__file__).resolve().parent.parent / "_export" / "agent_calls.jsonl"
_MAX_ARG_LEN = 80


def log_path() -> Path:
    return Path(os.environ.get("GROWTHOS_AGENT_LOG", str(_DEFAULT_LOG)))


def _safe_args(args: dict) -> dict:
    """Truncate each arg value so the log stays small and never carries a large payload."""
    out: dict[str, str] = {}
    for k, v in (args or {}).items():
        s = str(v)
        out[k] = s if len(s) <= _MAX_ARG_LEN else s[:_MAX_ARG_LEN - 3] + "..."
    return out


def _current_conversation() -> str | None:
    """Join key to the gateway's turn transcripts. Guarded import: growth-os
    runs standalone in some surfaces where command_center is not importable,
    and observability must never fail because of an optional enrichment."""
    try:
        from command_center.channels.transcript import current_conversation
        return current_conversation.get()
    except Exception:
        return None


def record_call(surface: str, tool: str, args: dict, *, ok: bool, ms: float,
                detail: str = "", path: str | Path | None = None) -> dict:
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "surface": surface, "tool": tool,
           "args": _safe_args(args), "ok": ok, "ms": round(ms, 1), "detail": detail[:200]}
    conversation_id = _current_conversation()
    if conversation_id:
        rec["conversation_id"] = conversation_id
    p = Path(path) if path is not None else log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def logged(fn: Callable[..., Any], surface: str,
           path: str | Path | None = None) -> Callable[..., Any]:
    """Wrap a tool so every call is timed + recorded. Errors are recorded then re-raised
    (never swallowed). `functools.wraps` keeps name/signature so the tool schema is unchanged."""
    @functools.wraps(fn)
    def wrapper(*a: Any, **kw: Any) -> Any:
        t0 = time.perf_counter()
        try:
            result = fn(*a, **kw)
        except Exception as exc:
            record_call(surface, fn.__name__, kw, ok=False,
                        ms=(time.perf_counter() - t0) * 1000, detail=f"{type(exc).__name__}: {exc}",
                        path=path)
            raise
        record_call(surface, fn.__name__, kw, ok=True,
                    ms=(time.perf_counter() - t0) * 1000, path=path)
        return result
    return wrapper


def read_calls(path: str | Path | None = None, limit: int = 50) -> list[dict]:
    p = Path(path) if path is not None else log_path()
    if not p.exists():
        return []
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines[-limit:]]


def summarize(path: str | Path | None = None) -> dict:
    """Per-(surface, tool) counts, error rate, and median latency — the monitor view."""
    rows = read_calls(path, limit=10_000)
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        groups.setdefault((r["surface"], r["tool"]), []).append(r)
    out = []
    for (surface, tool), items in sorted(groups.items()):
        errs = sum(1 for i in items if not i["ok"])
        out.append({"surface": surface, "tool": tool, "calls": len(items),
                    "errors": errs, "error_rate": round(errs / len(items), 3),
                    "median_ms": round(median(i["ms"] for i in items), 1)})
    return {"total_calls": len(rows), "by_tool": out,
            "surfaces": sorted({r["surface"] for r in rows}),
            "tools_used": sorted({r["tool"] for r in rows})}


def main() -> int:
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    s = summarize()
    print(f"agent-call monitor — {s['total_calls']} calls · surfaces={s['surfaces']} "
          f"· {len(s['tools_used'])} distinct tools used")
    print(f"{'surface':10s} {'tool':18s} {'calls':>6s} {'errs':>5s} {'err%':>6s} {'p50ms':>7s}")
    for t in s["by_tool"]:
        print(f"{t['surface']:10s} {t['tool']:18s} {t['calls']:>6d} {t['errors']:>5d} "
              f"{t['error_rate']*100:>5.0f}% {t['median_ms']:>7.1f}")
    print("\nrecent calls:")
    for r in read_calls(limit=12):
        flag = "ok " if r["ok"] else "ERR"
        print(f"  {r['ts'][11:19]} [{r['surface']:9s}] {flag} {r['tool']}({list(r['args'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
