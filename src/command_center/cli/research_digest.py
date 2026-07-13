#!/usr/bin/env python3
"""`cc research-digest` — turn an external-idea batch into durable, typed intake.

This productizes the MASTER.md §5.2 intake so the "here are 20 links, do they help us"
workflow is repeatable instead of a one-off chat. It reads the hand-authored catalog at
knowledge/research/source_catalog.yaml and can:

    cc research-digest validate            # load + Pydantic-validate the catalog (blocking)
    cc research-digest report              # human digest grouped by verdict (stdout or --out)
    cc research-digest feed                # emit generated/research-digest-feed.json

The feed is consumed by the existing observer-only scan, exactly like model-scout:

    cc self-improvement-scan --feeds generated/research-digest-feed.json

Only `verdict: evaluate` sources become feed records, and each drafts a read-only (L1)
*evaluation* card — never an adoption. Adoption still needs the full human wall (measured
gap + threat model + pre-registered experiment). Observer-only, propose-only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from command_center.research import (
    DEFAULT_CATALOG_PATH, DEFAULT_FEED_PATH, catalog_to_feed, load_catalog,
    render_digest_markdown,
)


def cmd_validate(args) -> int:
    try:
        cat = load_catalog(args.catalog)
    except FileNotFoundError:
        print(f"research-digest validate: catalog not found: {args.catalog}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 — surface the validation error verbatim
        print(f"research-digest validate: FAIL — {e}", file=sys.stderr)
        return 1
    n_eval = len(cat.evaluatable())
    print(f"research-digest validate: OK — {len(cat.sources)} source(s), "
          f"{n_eval} marked evaluate ({args.catalog})")
    return 0


def cmd_report(args) -> int:
    cat = load_catalog(args.catalog)
    md = render_digest_markdown(cat)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"research-digest report -> {args.out}")
    else:
        print(md)
    return 0


def cmd_feed(args) -> int:
    cat = load_catalog(args.catalog)
    feed = catalog_to_feed(cat)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(feed, indent=2), encoding="utf-8")
    n = len(feed.get("research_digest", []))
    print(f"research-digest feed: {n} evaluate record(s) -> {args.out}\n"
          f"  consume with: cc self-improvement-scan --feeds {args.out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="research-digest")
    ap.add_argument("--catalog", default=DEFAULT_CATALOG_PATH,
                    help=f"catalog path (default: {DEFAULT_CATALOG_PATH})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="load + validate the catalog (blocking gate)")
    v.set_defaults(func=cmd_validate)

    r = sub.add_parser("report", help="render the human digest (grouped by verdict)")
    r.add_argument("--out", default="", help="write markdown here instead of stdout")
    r.set_defaults(func=cmd_report)

    f = sub.add_parser("feed", help="emit the scan feed JSON (evaluate sources only)")
    f.add_argument("--out", default=DEFAULT_FEED_PATH,
                   help=f"feed output path (default: {DEFAULT_FEED_PATH})")
    f.set_defaults(func=cmd_feed)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
