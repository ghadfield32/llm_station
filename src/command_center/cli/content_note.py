#!/usr/bin/env python3
"""`cc content-note` - update a card's note BY INTENT, through the governed path.

Resolve a card (library / notes / post / any AppFlowy database) by a fuzzy or
semantic query, then record the note as a governed `progress_comment` kanban
event. That event is the ONLY legal write path: `emit_event` structurally rejects
wall actions, and a progress comment never sets status, approves, or merges.

    cc content-note --card "the glm router post" --append "cite Z.ai pricing"
    cc content-note --card "basketball library" --append "add the tracking paper" --apply

Dry-run by default (prints the event it WOULD emit). `--apply` appends it to the
event log (generated/kanban-events.jsonl); the existing board sync
(`cc kanban-reconcile --apply`) writes it through. No raw board mutation here.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from command_center.schemas import ContentPipelineConfig
from command_center.content.reference_live import fetch_all, records_from_rows
from command_center.content.reference_resolver import (
    load_ref_config, default_embedder, resolve,
)
from command_center.kanban_sync.events import EventLog, emit_event

EVENT_LOG = "generated/kanban-events.jsonl"


def resolve_card(query: str, records, *, cfg=None, embedder=None):
    """Resolve a query to one live card record (carrying board + card id). Raises
    SystemExit listing candidates when ambiguous or nothing matches."""
    cfg = cfg or load_ref_config()
    r = resolve(query, cfg=cfg, index=records, embedder=embedder)
    if r.match is None:
        if r.choices:
            opts = "; ".join(f"{m.record.id} [{m.record.board}/{m.record.kind}] "
                             f"({m.tier})" for m in r.choices)
            raise SystemExit(f"ambiguous card query {query!r} - did you mean: {opts}")
        raise SystemExit(f"no card matches {query!r}")
    return r.match.record


def emit_note(rec, note: str, verb: str, log: EventLog):
    """Record the note as a governed progress_comment event (the legal writer)."""
    return emit_event(log, action="progress_comment", board_id=rec.board,
                      card_id=rec.id, source_surface="repo_agent",
                      actor_type="agent", payload_ref=f"{verb}:{note}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cc content-note",
                                 description="update a card note by intent (governed)")
    ap.add_argument("--card", required=True, help="fuzzy/semantic query for the card")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--append", help="append this note text")
    g.add_argument("--set", dest="set_", help="set the note to this text")
    ap.add_argument("--pipeline", default="configs/content_pipeline.yaml",
                    help="content_pipeline.yaml (AppFlowy source)")
    ap.add_argument("--apply", action="store_true",
                    help="record the event (default: dry-run)")
    ap.add_argument("--log", default=EVENT_LOG)
    args = ap.parse_args(argv)

    pcfg = ContentPipelineConfig.model_validate(yaml.safe_load(open(args.pipeline)))
    cfg = load_ref_config()
    records = records_from_rows(fetch_all(pcfg.source))
    rec = resolve_card(args.card, records, cfg=cfg, embedder=default_embedder(cfg))

    note = args.append if args.append is not None else args.set_
    verb = "append" if args.append is not None else "set"
    print(f"card: {rec.id}  [{rec.board}/{rec.kind}]  {rec.title}")
    print(f"note ({verb}): {note}")

    if not args.apply:
        print("\ndry-run: rerun with --apply to record the note as a governed "
              "progress_comment event (no status change, no approval).")
        return 0

    ev = emit_note(rec, note, verb, EventLog(Path(args.log)))
    print(f"emitted {ev.event_type} {ev.event_id} (card {rec.id} on {rec.board})")
    print("write it through to the board with: cc kanban-reconcile --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
