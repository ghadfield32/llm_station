"""Stable JSON and compact human rendering for bench results."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .models import CORE_DIMENSIONS, Cell, MatrixReport, Verdict

DEFAULT_MATRIX_PATH = Path("generated/adapter-capability-matrix.json")


def build_report(*, live: bool, cells: list[Cell]) -> MatrixReport:
    counts = Counter(cell.verdict for cell in cells)
    return MatrixReport(
        mode="live" if live else "offline",
        dimensions=list(CORE_DIMENSIONS),
        cells=cells,
        summary={verdict: counts.get(verdict, 0) for verdict in Verdict},
    )


def write_report(report: MatrixReport, path: Path = DEFAULT_MATRIX_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.json_payload(), indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def render_table(report: MatrixReport) -> str:
    headers = ("ADAPTER", "DIMENSION", "DECLARED", "OBSERVED", "VERDICT", "DETAIL")
    rows = [
        (
            cell.adapter,
            cell.dimension.value,
            cell.declared.value,
            cell.observed.value,
            cell.verdict.value,
            cell.detail,
        )
        for cell in report.cells
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers) - 1)
    ]

    def render_row(row: tuple[str, ...]) -> str:
        fixed = "  ".join(
            row[index].ljust(widths[index]) for index in range(len(widths)))
        return f"{fixed}  {row[-1]}"

    separator = "  ".join("-" * width for width in widths) + "  " + "-" * 6
    return "\n".join([render_row(headers), separator, *(render_row(row) for row in rows)])
