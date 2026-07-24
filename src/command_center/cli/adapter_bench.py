"""`cc adapter-bench`: report-only declared-vs-observed adapter matrix."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from ..agent_sessions.bench.models import Verdict
from ..agent_sessions.bench.render import (
    DEFAULT_MATRIX_PATH,
    build_report,
    render_table,
    write_report,
)
from ..agent_sessions.bench.runner import run_bench


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Observe adapter capabilities and reconcile harness declarations")
    parser.add_argument(
        "--live",
        action="store_true",
        help="operator-only: invoke available real runtimes; never use in CI",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when DRIFT is present (default remains report-only)",
    )
    parser.add_argument(
        "--repo-id",
        default="llm_station",
        help="registered repo context used only by live probes",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_MATRIX_PATH,
        help=f"matrix JSON path (default: {DEFAULT_MATRIX_PATH})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cells = asyncio.run(run_bench(live=args.live, repo_id=args.repo_id))
    report = build_report(live=args.live, cells=cells)
    output = write_report(report, args.output)
    print(render_table(report))
    print(f"\nMatrix: {output}")
    print("Mode: report-only" if not args.strict else "Mode: strict DRIFT exit")
    has_drift = any(cell.verdict is Verdict.DRIFT for cell in cells)
    return 1 if args.strict and has_drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
