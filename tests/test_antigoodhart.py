"""Phase-3 anti-Goodhart tests: contamination detection, the proxy-vs-held-out gap, the
generalization gap, and saturation→rotation. These are permanent defenses — Goodhart is the
default failure mode of any optimizing loop."""
from __future__ import annotations

from pathlib import Path

from command_center.improvement.evals import (
    ngram_overlap, goodhart_gap, generalization_gap, SealedEvalStore,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---- n-gram overlap / contamination ----------------------------------------

def test_ngram_overlap_bounds():
    assert ngram_overlap("the quick brown fox jumps", "the quick brown fox jumps", n=3) == 1.0
    assert ngram_overlap("alpha beta gamma delta", "one two three four five", n=3) == 0.0
    # half the probe's 3-grams appear in the reference
    ov = ngram_overlap("the quick brown fox", "the quick brown zzz qqq www", n=2)
    assert 0.0 < ov < 1.0


def test_contamination_scan_flags_leaked_sealed_item():
    store = SealedEvalStore(repo_root=str(REPO_ROOT))
    suite = store.load_suite("sealed-retrieval-holdout", role="verifier")
    leaked_query = suite["cases"][0]["query"]
    # implementer evidence that contains a sealed query verbatim -> contaminated
    res = store.contamination_scan(f"... training note: {leaked_query} ...",
                                   "sealed-retrieval-holdout", role="verifier", n=4)
    assert res["contaminated"] and res["max_overlap"] >= 0.5
    # clean evidence -> not contaminated
    clean = store.contamination_scan("nothing from the sealed set here at all",
                                     "sealed-retrieval-holdout", role="verifier", n=4)
    assert not clean["contaminated"]


# ---- Goodhart gap + generalization gap -------------------------------------

def test_goodhart_gap_signature():
    # proxy improved 0.30 but the held-out 'true' metric only 0.05 -> gap 0.25 (gaming)
    gap = goodhart_gap(0.60, 0.90, 0.50, 0.55)
    assert abs(gap - 0.25) < 1e-9
    # honest improvement: proxy and held-out move together -> gap ~ 0
    assert abs(goodhart_gap(0.6, 0.8, 0.5, 0.7)) < 1e-9


def test_generalization_gap():
    assert abs(generalization_gap(0.9, 0.5) - 0.4) < 1e-9
    assert generalization_gap(0.7, 0.7) == 0.0


# ---- saturation -> rotation -------------------------------------------------

def test_recommend_rotation_on_saturated_suite():
    store = SealedEvalStore(repo_root=str(REPO_ROOT))
    # threshold defaults to 0.98; candidates all acing it -> rotate
    assert store.recommend_rotation("sealed-retrieval-holdout", [1.0, 0.99, 1.0])
    # a recent miss -> still discriminating, keep it
    assert not store.recommend_rotation("sealed-retrieval-holdout", [1.0, 0.5, 1.0])
    assert not store.recommend_rotation("sealed-retrieval-holdout", [])
