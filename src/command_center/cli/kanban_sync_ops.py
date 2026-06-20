"""Kanban event-stream operations: emit / project / verify / reconcile.

The event log is the single source of truth; every surface is a projection.
`emit` is the only legal writer (wall actions are rejected). `project` folds the
log into current card state. `verify` compares a surface snapshot to the fold.
`reconcile` detects drift (repairable) vs conflict (review_required) and can
write-through repairs to AppFlowy (fail-closed without board env); it never
approves, merges, or deletes.

  cc kanban-emit --action stage_card --board <b> --card <c> --source discord \
      --status-before Backlog --status-after Ready
  cc kanban-project [--output <json>]
  cc kanban-verify-projection --snapshot <snapshot.json>
  cc kanban-reconcile --snapshot <snapshot.json> [--apply]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from command_center.kanban_sync import (
    AppFlowyProjection,
    EventLog,
    GovernanceViolation,
    emit_event,
    project_cards,
    reconcile,
    verify_projection,
)

ROOT = Path(__file__).resolve().parents[3]
EVENT_LOG = "generated/kanban-events.jsonl"


def _log(root: Path = ROOT) -> EventLog:
    return EventLog(root / EVENT_LOG)


def _load_snapshot(path: Path) -> dict[str, dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(output: Path | None, data: dict[str, Any]) -> None:
    if output is None:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(prog="kanban-sync-ops")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("emit")
    pe.add_argument("--action", required=True)
    pe.add_argument("--board", required=True)
    pe.add_argument("--card", required=True)
    pe.add_argument("--source", required=True)
    pe.add_argument("--actor", default="agent")
    pe.add_argument("--repo", default=None)
    pe.add_argument("--mission", default=None)
    pe.add_argument("--status-before", default=None)
    pe.add_argument("--status-after", default=None)
    pe.add_argument("--evidence-ref", default=None)

    pp = sub.add_parser("project")
    pp.add_argument("--output", default="")

    pv = sub.add_parser("verify")
    pv.add_argument("--snapshot", required=True)
    pv.add_argument("--output", default="")

    pr = sub.add_parser("reconcile")
    pr.add_argument("--snapshot", required=True)
    pr.add_argument("--apply", action="store_true")
    pr.add_argument("--output", default="")

    args = parser.parse_args()
    log = _log()

    if args.cmd == "emit":
        try:
            ev = emit_event(
                log, action=args.action, board_id=args.board, card_id=args.card,
                source_surface=args.source, actor_type=args.actor, repo_id=args.repo,
                mission_id=args.mission, status_before=args.status_before,
                status_after=args.status_after, evidence_ref=args.evidence_ref)
        except (GovernanceViolation, ValueError) as exc:
            print(f"kanban-emit: BLOCKED\n  {exc}")
            return 1
        print(f"kanban-emit: {ev.event_type} {ev.event_id} (card {ev.card_id} -> {ev.status_after})")
        return 0

    if args.cmd == "project":
        cards = project_cards(log.read())
        result = {"n_cards": len(cards), "cards": cards}
        _write((ROOT / args.output).resolve() if args.output else None, result)
        print(f"kanban-project: {len(cards)} cards")
        for c in cards.values():
            print(f"  {c['card_id']}: {c['status']} (last_actor={c['last_actor']})")
        return 0

    if args.cmd == "verify":
        result = verify_projection(log.read(), _load_snapshot((ROOT / args.snapshot).resolve()))
        _write((ROOT / args.output).resolve() if args.output else None, result)
        print(f"kanban-verify-projection: {result['status'].upper()} "
              f"({len(result['mismatches'])} mismatches)")
        return 0 if result["status"] == "pass" else 1

    if args.cmd == "reconcile":
        from command_center.cli.github_app_verify import _merged_env, _read_dotenv
        snapshot = _load_snapshot((ROOT / args.snapshot).resolve())
        result = reconcile(log.read(), snapshot)
        repaired = []
        if args.apply and result.get("drift"):
            # repair drift only (never conflicts); write-through is fail-closed.
            # Repair to the reconciler's FOLD target (repair_to), not the card's
            # last event — the last event may be a progress comment (status None).
            proj = AppFlowyProjection(env=_merged_env(_read_dotenv(ROOT / ".env")))
            events_by_card = {e.card_id: e for e in log.read()}
            for d in result["drift"]:
                ev = events_by_card.get(d["card_id"])
                if ev is not None:
                    repaired.append(proj.write_through(ev, status_label=d["repair_to"]))
        result["repaired"] = repaired
        result["writes_performed"] = any(r.get("wrote") for r in repaired)
        _write((ROOT / args.output).resolve() if args.output else None, result)
        applied = [r for r in repaired if r.get("wrote")]
        not_applied = [r for r in repaired if not r.get("wrote")]
        print(f"kanban-reconcile: {result['status'].upper()} "
              f"drift={len(result.get('drift', []))} conflicts={len(result.get('conflicts', []))}")
        if args.apply:
            print(f"  repaired={len(applied)} not_applied={len(not_applied)}"
                  + (f" ({not_applied[0].get('reason')})" if not_applied else ""))
        for c in result.get("conflicts", []):
            print(f"  REVIEW_REQUIRED: {c['card_id']} ({c['reason']})")
        return 0 if result["status"] in ("pass", "degraded") else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
