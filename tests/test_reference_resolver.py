"""The resolver: disambiguation (top-3 when two hits are too close), resolving a
query specifically to a stored post, and that the SHIPPED config resolves real
misspelled/vague queries to the right item. This pins the MASTER invariant: no
user-facing lookup depends on exact names only."""
from __future__ import annotations

import json

import pytest

from command_center.schemas import ReferenceItem, ContentReferenceConfig
from command_center.content.embeddings import HashEmbedder
from command_center.content.reference_index import build_records, embed_records
from command_center.content.reference_resolver import (
    resolve, resolve_post, load_ref_config,
)


def _cfg(items, **kw):
    return ContentReferenceConfig(schema_version="1", items=items, **kw)


def _indexed(cfg, posts=None):
    recs = build_records(cfg, posts=posts)
    embed_records(recs, HashEmbedder())
    return recs


def _best_id(r):
    """The id a user would land on: the confident match, else the top choice."""
    m = r.match or (r.choices[0] if r.choices else None)
    return m.record.id if m else None


# ── disambiguation ──────────────────────────────────────────────────────────
def test_ambiguous_near_ties_return_top_three():
    items = [
        ReferenceItem(id="a", kind="doc", title="Quarterly Report",
                      aliases=["q report"], tags=["report", "quarter"]),
        ReferenceItem(id="b", kind="doc", title="Quarterly Recap",
                      aliases=["q recap"], tags=["report", "quarter"]),
    ]
    cfg = _cfg(items, ambiguous_margin=0.5)      # wide margin -> force ambiguity
    r = resolve("quarterly", cfg=cfg, index=_indexed(cfg), embedder=HashEmbedder())
    assert r.ambiguous and r.match is None
    assert len(r.choices) == 2


def test_confident_match_is_not_ambiguous():
    items = [
        ReferenceItem(id="linkedin_pipeline", kind="doc", title="LinkedIn Pipeline",
                      aliases=["linkedin posts"], tags=["linkedin"]),
        ReferenceItem(id="unrelated", kind="doc", title="Tax Filing Guide",
                      aliases=["taxes"], tags=["finance"]),
    ]
    cfg = _cfg(items)
    r = resolve("linkedin_pipeline", cfg=cfg, index=_indexed(cfg),
                embedder=HashEmbedder())
    assert not r.ambiguous and r.match.record.id == "linkedin_pipeline"


# ── resolve_post ────────────────────────────────────────────────────────────
def _store(tmp_path, posts):
    p = tmp_path / "content-posts.json"
    p.write_text(json.dumps({"posts": posts}), encoding="utf-8")
    return str(p)


def test_resolve_post_finds_by_fuzzy_hook(tmp_path):
    posts = [
        {"author_name": "Geoff", "id": "p_glm",
         "body": "How I built a GLM router backup for frontier escalation.\n\nDetails?"},
        {"author_name": "Geoff", "id": "p_pymc",
         "body": "A PyMC workflow for hierarchical models.\n\nThoughts?"},
    ]
    cfg = load_ref_config()
    store = _store(tmp_path, posts)
    post = resolve_post("glm routter backup", store, cfg=cfg, embedder=HashEmbedder())
    assert post.id == "p_glm"


def test_resolve_post_missing_store_raises(tmp_path):
    with pytest.raises(SystemExit):
        resolve_post("anything", str(tmp_path / "nope.json"),
                     cfg=load_ref_config(), embedder=HashEmbedder())


def test_resolve_post_ambiguous_raises_with_candidates(tmp_path):
    posts = [
        {"author_name": "G", "id": "x1", "body": "Bayesian workflow notes.\n\nQ?"},
        {"author_name": "G", "id": "x2", "body": "Bayesian workflow notes.\n\nQ?"},
    ]
    cfg = load_ref_config()
    with pytest.raises(SystemExit) as e:
        resolve_post("bayesian workflow", _store(tmp_path, posts),
                     cfg=cfg, embedder=HashEmbedder())
    assert "ambiguous" in str(e.value)


# ── the shipped config resolves real vague/misspelled queries ───────────────
@pytest.mark.parametrize("query,expected", [
    ("linkdin post", "linkedin_pipeline"),
    ("fronteer router", "frontier_router_backup"),
    ("glm routter", "frontier_router_backup"),
    ("the kanban for model eval", "model_eval_lanes"),
    ("the personal kanban", "board_personal"),
    ("library with reference posts", "reference_posts_library"),
])
def test_shipped_config_resolves_intent(query, expected):
    cfg = load_ref_config()
    r = resolve(query, cfg=cfg, index=_indexed(cfg), embedder=HashEmbedder())
    assert _best_id(r) == expected, f"{query!r} -> {_best_id(r)} (notes={r.notes})"


def test_shipped_config_validates_and_has_unique_ids():
    cfg = load_ref_config()
    ids = [i.id for i in cfg.items]
    assert len(ids) == len(set(ids)) and len(ids) >= 6

