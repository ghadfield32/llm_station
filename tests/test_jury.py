"""Phase-2 judge/jury tests. Agreement coefficients are checked against hand-computed
textbook values; the bias controls catch a position-biased and a verbosity-biased judge."""
from __future__ import annotations

import pytest

from command_center.improvement.jury import (
    cohens_kappa, fleiss_kappa, krippendorff_alpha, agreement_label,
    Jury, position_consistent, verbosity_bias_slope, anonymize,
)


# ---- Cohen's kappa ----------------------------------------------------------

def test_cohens_kappa_known_table():
    # confusion [[20,5],[10,15]] -> po=0.7, pe=0.5, kappa=0.4
    a = ["A"] * 20 + ["A"] * 5 + ["B"] * 10 + ["B"] * 15
    b = ["A"] * 20 + ["B"] * 5 + ["A"] * 10 + ["B"] * 15
    assert abs(cohens_kappa(a, b) - 0.4) < 1e-9


def test_cohens_kappa_perfect_and_bounds():
    assert cohens_kappa(["x", "y", "z"], ["x", "y", "z"]) == 1.0
    with pytest.raises(ValueError):
        cohens_kappa(["x"], ["x", "y"])


# ---- Fleiss' kappa ----------------------------------------------------------

def test_fleiss_kappa_negative_known():
    # items [[2,1],[1,2]] with 3 raters: P_bar=1/3, P_e=0.5 -> kappa=-1/3
    assert abs(fleiss_kappa([[2, 1], [1, 2]]) - (-1 / 3)) < 1e-9


def test_fleiss_kappa_unanimous_is_one():
    assert fleiss_kappa([[3, 0], [0, 3]]) == 1.0
    with pytest.raises(ValueError):
        fleiss_kappa([[3, 0], [2, 0]])   # ragged (different rater counts)


# ---- Krippendorff's alpha ---------------------------------------------------

def test_krippendorff_alpha_hand_computed():
    # coders x units; one disagreement on the last unit -> alpha = 1 - 2/(46/7) ≈ 0.6957
    data = [[1, 2, 3, 3], [1, 2, 3, 4]]
    assert abs(krippendorff_alpha(data) - (1 - 2 / (46 / 7))) < 1e-9


def test_krippendorff_alpha_perfect():
    assert krippendorff_alpha([[1, 2, 3], [1, 2, 3]]) == 1.0


def test_agreement_label_bands():
    assert agreement_label(0.05) == "slight"
    assert agreement_label(0.5) == "moderate"
    assert agreement_label(0.9) == "near-perfect"
    assert agreement_label(-0.1) == "poor"


# ---- the jury ---------------------------------------------------------------

def test_jury_majority_and_disagreement_set():
    judges = {
        "j1": lambda x: "block" if x > 0 else "allow",
        "j2": lambda x: "block" if x > 1 else "allow",
        "j3": lambda x: "block" if x > 0 else "allow",
    }
    jury = Jury(judges)
    res = jury.evaluate([2, 1, -1], ids=["a", "b", "c"])
    labels = res.majority_labels()
    # item a=2: all block (unanimous). b=1: j1+j3 block, j2 allow -> majority block, split.
    # c=-1: all allow (unanimous).
    assert labels == {"a": "block", "b": "block", "c": "allow"}
    assert res.disagreement_ids == ["b"]          # only b split the panel
    assert res.inter_judge_kappa is not None


def test_jury_requires_two_judges():
    with pytest.raises(ValueError):
        Jury({"only": lambda x: "block"})


# ---- bias controls ----------------------------------------------------------

def test_position_bias_detected():
    # a judge that ALWAYS prefers whichever is shown first is position-biased
    biased = lambda a, b: "first"  # noqa: E731
    assert not position_consistent(biased, "x", "y")
    # a fair judge: prefers the lexicographically larger, regardless of order
    fair = lambda a, b: "first" if a > b else "second"  # noqa: E731
    assert position_consistent(fair, "x", "y")


def test_verbosity_bias_slope():
    scores = [1.0, 2.0, 3.0, 4.0, 5.0]
    lengths = [10.0, 20.0, 30.0, 40.0, 50.0]      # perfectly correlated with score
    assert abs(verbosity_bias_slope(scores, lengths) - 1.0) < 1e-9
    uncorrelated = [3.0, 1.0, 4.0, 1.0, 5.0]
    slope = verbosity_bias_slope([1.0, 2.0, 3.0, 4.0, 5.0], uncorrelated)
    assert abs(slope) < 0.7                       # weak/no length effect


def test_anonymize_strips_identity_markers():
    text = "As an AI, my answer (from GPT-4) beats Model A's response."
    out = anonymize(text)
    assert "GPT-4" not in out and "Model A" not in out
    assert "as an ai" not in out.lower() and "my answer" not in out.lower()
    assert "[ANON]" in out
