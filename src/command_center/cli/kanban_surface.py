"""Operator CLI for the agent kanban surface.

    python -m command_center.cli.kanban_surface digest [--output PATH]
    python -m command_center.cli.kanban_surface validate

`digest` renders real metrics from the agent-call log spine + the tuning verdict.
`validate` runs the blocking N/N PASS gate. Wired as `make kanban-digest` /
`make kanban-surface-validate`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..channels.core import GROWTHOS_ROOT
from ..kanban.digest import render_digest
from ..kanban.metrics import compute_metrics, load_calls, log_path
from ..kanban.tuning import recommend_fuzzy_ratio
from ..kanban.validate import run_gate
from ..channels.board_state import all_boards_json, load_agent_surface_config


def _digest(output: str) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    calls = load_calls()
    metrics = compute_metrics(calls)
    cfg = load_agent_surface_config()
    # production has no labelled resolution outcomes yet → the learner abstains,
    # which is reported honestly in the digest (never a fabricated recommendation).
    tune = recommend_fuzzy_ratio([], cfg.tuning, cfg.addressing.fuzzy_min_ratio)
    md = render_digest(metrics, tune,
                       generated_at=datetime.now(timezone.utc).isoformat(),
                       log_file=log_path())
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"kanban digest -> {out}  ({metrics.total_calls} calls)")
    return 0


def _board_snapshot(output: str) -> int:
    """Write the AppFlowy board snapshot the UI reads. Runs where growthos + creds
    live (the worker/curator); per-board fail-loud (unreadable boards are recorded
    with their error, never dropped) so a stale/partial snapshot is never silent."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    # Resolve the output BEFORE chdir (so `--output generated/...` lands at the repo
    # root, not under growth-os). growthos has its own tree/.env/databases.json, so
    # bootstrap it exactly like the gateway: on sys.path + CWD at the growth-os root.
    out = Path(output).resolve()
    sys.path.insert(0, str(GROWTHOS_ROOT))
    os.chdir(GROWTHOS_ROOT)
    data = {"generated_at": datetime.now(timezone.utc).isoformat(),
            "boards": all_boards_json()}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    errs = [b["board"] for b in data["boards"] if b.get("error")]
    print(f"board snapshot -> {out}  ({len(data['boards'])} boards"
          + (f", {len(errs)} unreadable: {errs}" if errs else "") + ")")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="kanban_surface")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("digest", help="render the observability digest")
    d.add_argument("--output", default="generated/kanban-digest.md")
    sub.add_parser("validate", help="blocking N/N PASS gate")
    b = sub.add_parser("board-snapshot", help="write the AppFlowy board snapshot")
    b.add_argument("--output", default="generated/board-snapshot.json")
    args = ap.parse_args()
    if args.cmd == "digest":
        return _digest(args.output)
    if args.cmd == "board-snapshot":
        return _board_snapshot(args.output)
    return 0 if run_gate() else 1


if __name__ == "__main__":
    raise SystemExit(main())
