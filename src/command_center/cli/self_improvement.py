"""Daily self-improvement: scan / daily / report (observer + draft-only).

Thin operator surface over the existing observer pipeline
(command_center.improvement.discovery). The scan reads sources, ranks findings,
and drafts ONLY `Proposed` experiment cards through the ObserverCharter — it never
applies code, promotes, merges, or deploys. An approved card becomes a Ledger
mission that runs the branch/worktree/devcontainer/PR loop with human review.

  cc self-improvement-scan                               # observer; zero writes
  cc self-improvement-daily --draft-kanban true --apply false   # draft Proposed cards
  cc self-improvement-report                             # write the decision report

`--apply true` (applying CODE changes) is intentionally unsupported here: the
daily loop is observer/draft-only by structural design.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from command_center.improvement.discovery import (
    DEFAULT_REPORT_PATH,
    ObserverCharter,
    ScanPipeline,
    build_scanner,
    offline_specs,
)
from command_center.improvement.registry import ExperimentRegistry

ROOT = Path(__file__).resolve().parents[3]
DAILY_EVIDENCE = (
    "evaluation/system-validation/20260616-autonomy-contracts/self-improvement-daily.json"
)


def _offline_scanners(reg: ExperimentRegistry):
    """Network-free scanners only (code health + ledger) — deterministic, no creds."""
    return [build_scanner(spec, reg, lambda _spec: []) for spec in offline_specs()]


def _run_pipeline(
    *, reg: ExperimentRegistry, report_path: str, apply: bool, now: datetime, outcomes=None,
):
    pipe = ScanPipeline(ObserverCharter(reg, report_path=report_path))
    date, now_iso = now.date().isoformat(), now.isoformat()
    if outcomes is not None:
        rep = pipe.run_from_outcomes(outcomes, date=date, now_iso=now_iso, apply=apply)
    else:
        rep = pipe.run(_offline_scanners(reg), date=date, now_iso=now_iso, apply=apply)
    return pipe, rep


def run_scan(
    *, reg: ExperimentRegistry, now: datetime | None = None,
    report_path: str = DEFAULT_REPORT_PATH, output: Path | None = None, outcomes=None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    _pipe, rep = _run_pipeline(reg=reg, report_path=report_path, apply=False, now=now,
                               outcomes=outcomes)
    result = {
        "schema_version": "command-center.self-improvement-scan.v1",
        "mode": "observer", "applied_code_changes": False, "drafted_cards": False,
        "n_sources": rep.n_sources, "n_failed": rep.n_failed, "n_findings": rep.n_findings,
        "would_draft_ids": rep.would_draft_ids, "drafted_ids": rep.drafted_ids,
        "status": "observed",
    }
    _write(output, result)
    return result


def run_daily(
    *, reg: ExperimentRegistry, now: datetime | None = None, draft_kanban: bool = False,
    code_apply: bool = False, report_path: str = DEFAULT_REPORT_PATH,
    output: Path | None = None, outcomes=None,
) -> dict[str, Any]:
    if code_apply:
        # observer/draft-only by design: code changes require an approved mission.
        return {"status": "blocked", "drafted_cards": False, "applied_code_changes": False,
                "blockers": ["code_apply_not_supported_daily_is_observer_draft_only"],
                "next": "approve a drafted card at the kanban wall; it becomes a Ledger mission"}
    now = now or datetime.now(timezone.utc)
    _pipe, rep = _run_pipeline(reg=reg, report_path=report_path, apply=draft_kanban, now=now,
                               outcomes=outcomes)
    result = {
        "schema_version": "command-center.self-improvement-daily.v1",
        "date": now.date().isoformat(),
        "draft_kanban": draft_kanban, "applied_code_changes": False,
        "n_findings": rep.n_findings, "would_draft_ids": rep.would_draft_ids,
        "drafted_card_ids": rep.drafted_ids, "report_path": rep.report_path,
        "status": "drafted" if draft_kanban else "observed",
    }
    _write(output, result)
    return result


def run_report(
    *, reg: ExperimentRegistry, now: datetime | None = None,
    report_path: str = DEFAULT_REPORT_PATH, outcomes=None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    pipe, rep = _run_pipeline(reg=reg, report_path=report_path, apply=False, now=now,
                              outcomes=outcomes)
    # observer write of the decision report (no cards drafted)
    written = pipe.charter.write_report(rep.report_markdown)
    return {"status": "report_written", "report_path": written, "n_findings": rep.n_findings}


def _write(output: Path | None, data: dict[str, Any]) -> None:
    if output is None:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _bool(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def main() -> int:
    parser = argparse.ArgumentParser(prog="self-improvement")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    pd = sub.add_parser("daily")
    pd.add_argument("--draft-kanban", default="false")
    pd.add_argument("--apply", default="false")
    sub.add_parser("report")
    args = parser.parse_args()

    reg = ExperimentRegistry()
    if args.cmd == "scan":
        r = run_scan(reg=reg,
                     output=(ROOT / DAILY_EVIDENCE).with_name("self-improvement-scan.json"))
        print(f"self-improvement-scan: {r['status'].upper()} "
              f"sources={r['n_sources']} findings={r['n_findings']} "
              f"would_draft={len(r['would_draft_ids'])}")
        return 0
    if args.cmd == "daily":
        r = run_daily(reg=reg, draft_kanban=_bool(args.draft_kanban), code_apply=_bool(args.apply),
                      output=(ROOT / DAILY_EVIDENCE))
        print(f"self-improvement-daily: {r['status'].upper()}")
        for b in r.get("blockers", []):
            print(f"  BLOCKED: {b}")
        if r.get("status") == "drafted":
            print(f"  drafted Proposed cards: {r['drafted_card_ids']}")
        if r.get("next"):
            print(f"  NEXT: {r['next']}")
        return 0 if r["status"] in ("drafted", "observed") else 1
    if args.cmd == "report":
        r = run_report(reg=reg)
        print(f"self-improvement-report: {r['status'].upper()} -> {r['report_path']}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
