#!/usr/bin/env python3
"""`cc content-preview` - render a post the way LinkedIn will show it BEFORE it
ships, so a human reviews a real preview instead of raw text.

Three sources, in priority order:
  --post  "<fuzzy query>"   resolve a stored post by meaning/alias/fuzzy (no exact
                            name required - see content.reference_resolver)
  --post-id <id>            exact id in the posts store
  --hook/--body inline      ad-hoc preview of text you paste

Outputs (all three forms, per the preview contract):
  - terminal markdown preview (stdout)
  - a self-contained LinkedIn-styled HTML file (generated/preview/<id>.html)
  - copy-ready export text (--text to stdout, --out FILE to write)

Read-only: never posts, never approves. Publishing stays cc linkedin-publish.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from command_center.content.post_model import LinkedInPost, load_posts
from command_center.content.renderers import markdown_preview, html_preview, export_text

DEFAULT_STORE = "generated/content-posts.json"
PREVIEW_DIR = "generated/preview"


def _by_id(posts: list[LinkedInPost], post_id: str) -> LinkedInPost:
    for p in posts:
        if p.id == post_id:
            return p
    raise SystemExit(f"no post with id {post_id!r} in store "
                     f"(have: {', '.join(p.id for p in posts) or '<empty>'})")


def _resolve(query: str, store: str, live: bool, pipeline: str) -> LinkedInPost:
    """Fuzzy/semantic lookup of a post by intent. With --live, resolve against the
    actual LinkedIn content-board cards; otherwise the JSON store. Imported lazily
    so the renderer path has no dependency on the reference index."""
    from command_center.content.reference_resolver import resolve_post, resolve_post_in
    if live:
        import yaml
        from command_center.schemas import ContentPipelineConfig
        from command_center.content.reference_live import fetch_posts
        pcfg = ContentPipelineConfig.model_validate(yaml.safe_load(open(pipeline)))
        return resolve_post_in(query, fetch_posts(pcfg.source))
    return resolve_post(query, store)


def build_post(args) -> LinkedInPost:
    if args.post:
        return _resolve(args.post, args.store, args.live, args.pipeline)
    if args.post_id:
        return _by_id(load_posts(args.store), args.post_id)
    if args.body:
        body = f"{args.hook.strip()}\n\n{args.body.strip()}" if args.hook else args.body
        if not args.author:
            raise SystemExit("inline preview needs --author")
        return LinkedInPost(author_name=args.author, author_headline=args.headline,
                            body=body, id="inline")
    raise SystemExit("nothing to preview: pass --post, --post-id, or --body")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cc content-preview",
                                 description="LinkedIn-accurate post preview (read-only)")
    ap.add_argument("--post", help="fuzzy/semantic query to find a post by intent")
    ap.add_argument("--post-id", help="exact post id in the store")
    ap.add_argument("--store", default=DEFAULT_STORE)
    ap.add_argument("--live", action="store_true",
                    help="resolve --post against the live LinkedIn content boards")
    ap.add_argument("--pipeline", default="configs/content_pipeline.yaml",
                    help="content_pipeline.yaml (AppFlowy source for --live)")
    ap.add_argument("--platform", default="linkedin", choices=["linkedin"])
    ap.add_argument("--device", default="desktop", choices=["desktop", "mobile"],
                    help="which see-more fold the markdown preview shows")
    ap.add_argument("--author")
    ap.add_argument("--headline")
    ap.add_argument("--hook")
    ap.add_argument("--body")
    ap.add_argument("--html-out", help="HTML path (default generated/preview/<id>.html)")
    ap.add_argument("--no-html", action="store_true", help="skip the HTML file")
    ap.add_argument("--text", action="store_true", help="also print copy-ready text")
    ap.add_argument("--out", help="write copy-ready text to this file")
    args = ap.parse_args(argv)

    # The preview uses Unicode (…, ✓, fold/visibility glyphs). Windows consoles
    # default to cp1252 and would crash on print; emit UTF-8 where we can.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    post = build_post(args)
    print(markdown_preview(post, args.device))

    if not args.no_html:
        out = Path(args.html_out) if args.html_out else \
            Path(PREVIEW_DIR) / f"{post.id or 'post'}.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html_preview(post, args.device), encoding="utf-8")
        print(f"\nHTML preview -> {out}", file=sys.stderr)

    text = export_text(post)
    if args.text:
        print("\n--- copy-ready text ---\n" + text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"copy-ready text -> {args.out}", file=sys.stderr)

    # A post over the hard cap is a real failure (exit 1); warnings don't fail.
    return 1 if any(w.level == "error" for w in post.lint()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
