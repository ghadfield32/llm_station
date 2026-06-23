"""Build and persist the reference index the resolver searches.

Multi-source by design (so a query finds things whatever angle you come from):
  - curated items from configs/content_reference.yaml (docs, boards, libraries,
    model lanes) - the stable seed with human aliases;
  - live posts from the posts store (generated/content-posts.json) - so "that glm
    router post" resolves to an actual stored post, not just the doc about it.

Each record carries a searchable `text` blob and an optional embedding `vector`
(filled at build time when the semantic tier is on). Persisted as JSONL so a
rebuild is cheap and the index is inspectable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path

from .post_model import LinkedInPost


@dataclass
class IndexRecord:
    id: str
    kind: str
    title: str
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    summary: str = ""
    source_path: str = ""
    text: str = ""                       # the searchable blob (lexical tiers)
    vector: list[float] | None = None    # embedding (semantic tier), if built
    board: str = ""                      # live source database/board (for write-back)

    def blob(self) -> str:
        parts = [self.title, *self.aliases, *self.tags, self.summary, self.text]
        return " ".join(p for p in parts if p)


def _record_from_item(item) -> IndexRecord:
    return IndexRecord(
        id=item.id, kind=item.kind, title=item.title,
        aliases=list(item.aliases), tags=list(item.tags),
        summary=item.summary, source_path=item.source_path,
        text=" ".join([item.title, *item.aliases, *item.tags, item.summary]))


def _record_from_post(post: LinkedInPost) -> IndexRecord:
    hook = post.hook()
    return IndexRecord(
        id=post.id or hook[:24], kind="post", title=hook[:80],
        aliases=[], tags=post.extracted_hashtags(),
        summary=post.body[:140], source_path="generated/content-posts.json",
        text=post.body)


def post_records(posts: list[LinkedInPost]) -> list[IndexRecord]:
    """Index records for posts only (used when resolving a query specifically to a
    stored post). Order matches `posts` 1:1 so callers can zip them back."""
    return [_record_from_post(p) for p in posts]


def build_records(ref_cfg, posts: list[LinkedInPost] | None = None) -> list[IndexRecord]:
    records = [_record_from_item(i) for i in ref_cfg.items]
    seen = {r.id for r in records}
    for p in posts or []:
        rec = _record_from_post(p)
        if rec.id not in seen:                 # curated item wins on id clash
            records.append(rec)
            seen.add(rec.id)
    return records


def embed_records(records: list[IndexRecord], embedder) -> None:
    """Fill each record's vector in place. Raises if the embedder fails - a
    rebuild that silently dropped the semantic tier would be a lie."""
    if not records:
        return
    vectors = embedder.embed([r.blob() for r in records])
    for rec, vec in zip(records, vectors):
        rec.vector = vec


def write_index(path: str, records: list[IndexRecord]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(asdict(rec)) + "\n")


def load_index(path: str) -> list[IndexRecord]:
    p = Path(path)
    if not p.exists():
        return []
    out: list[IndexRecord] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(IndexRecord(**json.loads(line)))
    return out
