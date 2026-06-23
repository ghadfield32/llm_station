#!/usr/bin/env python3
"""`cc reference` - build the reference index and find things by intent.

    cc reference index --rebuild        # (re)build configs/content_reference.yaml
                                        #  + the posts store into data/reference/
    cc reference find "the glm router post"   # resolve a vague query to a reference

The whole point: you do not need exact names. A misspelled or vague query
resolves through aliases, fuzzy, keyword, and local-embedding tiers; if two hits
are too close it shows you the top 3 instead of guessing. Read-only.
"""
from __future__ import annotations

import argparse
import sys

from command_center.content.post_model import load_posts
from command_center.content.reference_index import (
    build_records, embed_records, write_index,
)
from command_center.content.reference_resolver import (
    load_ref_config, default_embedder, resolve, REF_CONFIG,
)

DEFAULT_STORE = "generated/content-posts.json"


def cmd_index(args) -> int:
    cfg = load_ref_config(args.config)
    posts = load_posts(args.store)
    records = build_records(cfg, posts=posts)
    if args.live:
        import yaml
        from command_center.schemas import ContentPipelineConfig
        from command_center.content.reference_live import fetch_all, records_from_rows
        pcfg = ContentPipelineConfig.model_validate(
            yaml.safe_load(open(args.pipeline)))
        live = records_from_rows(fetch_all(pcfg.source))
        seen = {r.id for r in records}
        records += [r for r in live if r.id not in seen]
        print(f"  live: indexed {len(live)} board rows from AppFlowy")
    note = ""
    if cfg.embed_enabled:
        try:
            embed_records(records, default_embedder(cfg))
            note = f"embeddings: {cfg.embed_model} ({len(records)} vectors)"
        except Exception as e:               # Ollama not up -> lexical index, said plainly
            note = f"embeddings SKIPPED ({type(e).__name__}: {e}); lexical index only"
    write_index(cfg.index_path, records)
    posts_n = sum(1 for r in records if r.kind == "post")
    print(f"reference index -> {cfg.index_path}  "
          f"({len(records)} records, {posts_n} posts)")
    if note:
        print("  " + note)
    return 0


def cmd_find(args) -> int:
    r = resolve(args.query)
    for n in r.notes:
        print(f"# {n}", file=sys.stderr)
    if not r.choices:
        print(f"no match for {args.query!r}")
        return 1
    header = ("ambiguous - top %d for" % len(r.choices)) if r.ambiguous else "best match for"
    print(f"{header} {args.query!r}:")
    for m in r.choices:
        mark = "->" if (r.match is not None and m is r.match) else "  "
        print(f" {mark} {m.record.id:28} {m.tier:10} {m.score:.3f}  {m.record.title}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cc reference",
                                 description="reference index + intent-based lookup")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("index", help="build/persist the reference index")
    pi.add_argument("--rebuild", action="store_true",
                    help="rebuild from configs + posts store (the only mode)")
    pi.add_argument("--live", action="store_true",
                    help="also index every live AppFlowy database (library, notes, "
                         "posts, ...) so cards resolve by intent")
    pi.add_argument("--config", default=REF_CONFIG)
    pi.add_argument("--pipeline", default="configs/content_pipeline.yaml",
                    help="content_pipeline.yaml (AppFlowy source for --live)")
    pi.add_argument("--store", default=DEFAULT_STORE)
    pi.set_defaults(func=cmd_index)

    pf = sub.add_parser("find", help="resolve a query to a reference")
    pf.add_argument("query")
    pf.set_defaults(func=cmd_find)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
