"""Resolve a human's vague query to a concrete reference (post / board / doc /
library / lane). This is the layer the CLIs call: it loads config, picks the
embedder, runs the search cascade, and applies disambiguation - if the top two
hits are too close, it returns the top 3 to choose from instead of guessing.

The contract (docs/MASTER.md, content-usability lane): a user-facing command may
use exact names as a fast path, never as the only path. Everything here degrades
gracefully - if the local embedder is down, the lexical tiers still resolve and
the skipped semantic tier is reported, not silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from command_center.schemas import ContentReferenceConfig
from .embeddings import OllamaEmbedder
from .post_model import LinkedInPost, load_posts
from .reference_index import (
    IndexRecord, build_records, post_records, embed_records, load_index,
)
from .reference_search import search, Match

REF_CONFIG = "configs/content_reference.yaml"
_DEFAULT = object()                       # sentinel: "pick the configured embedder"


@dataclass
class Resolution:
    query: str
    match: Match | None                   # the confident pick (None if ambiguous/none)
    choices: list[Match] = field(default_factory=list)   # top 3 for context/disambig
    ambiguous: bool = False
    notes: list[str] = field(default_factory=list)


def load_ref_config(path: str = REF_CONFIG) -> ContentReferenceConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ContentReferenceConfig.model_validate(data)


def default_embedder(cfg: ContentReferenceConfig):
    return OllamaEmbedder(model=cfg.embed_model) if cfg.embed_enabled else None


def _maybe_embed(records: list[IndexRecord], cfg: ContentReferenceConfig, embedder):
    """Embed in place if the semantic tier is on. A failing embedder degrades to
    lexical (search() will note the skip at query time) rather than crashing."""
    if embedder is None or not cfg.embed_enabled:
        return
    try:
        embed_records(records, embedder)
    except Exception:
        pass


def _decide(query: str, res, margin: float, notes: list[str]) -> Resolution:
    if not res.matches:
        return Resolution(query, None, [], False, res.notes + notes)
    top = res.matches[0]
    second = res.matches[1].score if len(res.matches) > 1 else 0.0
    ambiguous = len(res.matches) > 1 and (top.score - second) < margin
    return Resolution(
        query=query, match=None if ambiguous else top,
        choices=res.matches[:3], ambiguous=ambiguous, notes=res.notes + notes)


def resolve(query: str, *, cfg: ContentReferenceConfig | None = None,
            posts: list[LinkedInPost] | None = None, embedder=_DEFAULT,
            index: list[IndexRecord] | None = None) -> Resolution:
    """Resolve across the full index (curated items + any posts). Uses the
    persisted index when one exists and no live posts were passed; otherwise
    builds in memory so freshly-stored posts are included."""
    cfg = cfg or load_ref_config()
    if embedder is _DEFAULT:
        embedder = default_embedder(cfg)
    notes: list[str] = []
    if index is None:
        persisted = load_index(cfg.index_path)
        if persisted and posts is None:
            index = persisted
        else:
            index = build_records(cfg, posts=posts)
            _maybe_embed(index, cfg, embedder)
            if not persisted:
                notes.append("using in-memory index (run `cc reference index "
                             "--rebuild` to persist + cache embeddings)")
    res = search(index, query, fuzzy_threshold=cfg.fuzzy_threshold,
                 embedder=embedder, embed_enabled=cfg.embed_enabled)
    return _decide(query, res, cfg.ambiguous_margin, notes)


def resolve_post(query: str, store: str = "generated/content-posts.json", *,
                 cfg: ContentReferenceConfig | None = None,
                 embedder=_DEFAULT) -> LinkedInPost:
    """Resolve a query specifically to a stored post (searches posts only, so it
    never returns the doc *about* a post). Raises SystemExit with the top
    candidates when the query is ambiguous or matches nothing."""
    posts = load_posts(store)
    if not posts:
        raise SystemExit(f"posts store {store!r} is empty or missing - "
                         "nothing to preview by query")
    cfg = cfg or load_ref_config()
    if embedder is _DEFAULT:
        embedder = default_embedder(cfg)
    records = post_records(posts)
    by_id = {r.id: p for r, p in zip(records, posts)}
    _maybe_embed(records, cfg, embedder)
    res = search(records, query, fuzzy_threshold=cfg.fuzzy_threshold,
                 embedder=embedder, embed_enabled=cfg.embed_enabled)
    dec = _decide(query, res, cfg.ambiguous_margin, [])
    if dec.match is None:
        if dec.choices:
            opts = "; ".join(f"{m.record.id} ({m.tier} {m.score})" for m in dec.choices)
            raise SystemExit(f"ambiguous post query {query!r} - did you mean: {opts}")
        raise SystemExit(f"no stored post matches {query!r}")
    return by_id[dec.match.record.id]
