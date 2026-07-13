"""The retrieval cascade: each tier (exact id, alias, normalized, fuzzy, keyword,
semantic) fires when it should, the strongest tier wins, and the semantic tier
degrades to lexical (with a note) when the embedder is unavailable. Uses the
deterministic HashEmbedder so the semantic tier runs offline in CI."""
from __future__ import annotations

from command_center.schemas import ReferenceItem, ContentReferenceConfig
from command_center.content.embeddings import HashEmbedder
from command_center.content.reference_index import build_records, embed_records
from command_center.content.reference_search import search, normalize, BM25


def _cfg(items):
    return ContentReferenceConfig(schema_version="1", items=items)


ITEMS = [
    ReferenceItem(id="linkedin_pipeline", kind="doc", title="LinkedIn Pipeline",
                  aliases=["linkedin posts", "post preview"],
                  tags=["linkedin", "content", "publishing"],
                  summary="draft preview validate linkedin posts"),
    ReferenceItem(id="frontier_router_backup", kind="model",
                  title="Frontier Router Backup",
                  aliases=["glm router", "paid model backup"],
                  tags=["router", "glm", "openrouter", "budget"],
                  summary="opt-in paid escalation behind budget gates"),
    ReferenceItem(id="board_personal", kind="kanban",
                  title="Personal Content Board",
                  aliases=["personal board", "my content kanban"],
                  tags=["kanban", "appflowy", "personal"],
                  summary="three column board in queue in progress completed"),
]


def _index(embed=True):
    recs = build_records(_cfg(ITEMS))
    if embed:
        embed_records(recs, HashEmbedder())
    return recs


def _top(query, **kw):
    res = search(_index(), query, **kw)
    return res.matches[0] if res.matches else None


def test_normalize_collapses_punctuation_and_case():
    assert normalize("GLM-Router!!  Backup") == "glm router backup"


def test_exact_id_wins_with_score_one():
    m = _top("frontier_router_backup")
    assert m.record.id == "frontier_router_backup"
    assert m.tier == "exact_id" and m.score == 1.0


def test_alias_exact_match():
    m = _top("glm router")
    assert m.record.id == "frontier_router_backup"
    assert m.tier in ("alias", "normalized")


def test_fuzzy_tolerates_misspelling():
    m = _top("fronteer routter")          # two typos, no exact alias
    assert m.record.id == "frontier_router_backup"
    assert m.tier == "fuzzy"


def test_keyword_tier_matches_on_body_terms():
    # "completed" only appears in board_personal's summary, not its title/aliases
    m = _top("in progress completed column")
    assert m.record.id == "board_personal"
    assert m.tier in ("keyword", "semantic")


def test_semantic_tier_runs_with_test_embedder():
    res = search(_index(embed=True), "publish linkedin", embedder=HashEmbedder())
    assert res.matches and not res.notes        # tier exercised, nothing skipped
    assert res.matches[0].record.id == "linkedin_pipeline"


def test_semantic_degrades_to_lexical_with_a_note():
    class Raising:
        def embed(self, texts):
            raise RuntimeError("ollama down")
    res = search(_index(embed=True), "glm router", embedder=Raising())
    assert any("semantic tier skipped" in n for n in res.notes)
    assert res.matches[0].record.id == "frontier_router_backup"   # lexical still works


def test_no_match_returns_empty():
    res = search(_index(), "xylophone quantum zebra")
    assert res.matches == []


def test_bm25_ranks_term_frequency():
    bm = BM25([["a", "b", "c"], ["a", "a", "a"], ["d"]])
    scores = bm.scores(["a"])
    assert scores[1] > scores[0] > 0       # doc with more 'a' ranks higher
    assert scores[2] == 0.0

