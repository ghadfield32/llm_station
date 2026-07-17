"""RoutingCalibrator: learn evidence-backed keyword->board rules from the
correction log. Deterministic + time-ordered — majority board (ties excluded),
support + distribution attached, PAST corrections only, no invented thresholds.
"""
from __future__ import annotations

import itertools

from command_center.work_graph import RoutingCalibrator, RoutingCorrection

_ids = itertools.count(1)


def _c(title: str, board: str | None, at: str) -> RoutingCorrection:
    return RoutingCorrection(correction_id=f"rc-{next(_ids)}", at=at, title=title,
                             chosen_board_id=board)


def test_derive_assigns_majority_board_with_evidence():
    calib = RoutingCalibrator([
        _c("call the dentist", "health", "t1"),
        _c("dentist appointment", "health", "t2"),
        _c("dentist billing dispute", "errands", "t3"),
    ])
    rules = {r.keyword: r for r in calib.derive()}
    dentist = rules["dentist"]
    assert dentist.board_id == "health"        # majority (2 vs 1)
    assert dentist.support == 2 and dentist.total == 3
    assert dentist.distribution == {"health": 2, "errands": 1}


def test_tie_is_excluded_not_guessed():
    calib = RoutingCalibrator([
        _c("ambiguous token", "A", "t1"),
        _c("ambiguous token", "B", "t2"),
    ])
    assert "ambiguous" not in {r.keyword for r in calib.derive()}   # tie -> skip


def test_stopwords_carry_no_signal():
    calib = RoutingCalibrator([_c("the research plan", "research", "t1")])
    kws = {r.keyword for r in calib.derive()}
    assert "research" in kws and "plan" in kws
    assert "the" not in kws                     # standard function word dropped


def test_corrections_with_no_board_are_ignored():
    calib = RoutingCalibrator([
        _c("left in inbox idea", None, "t1"),   # no board chosen -> no signal
        _c("research idea", "research", "t2"),
    ])
    boards = {r.board_id for r in calib.derive()}
    assert boards == {"research"}


def test_temporal_cut_uses_past_corrections_only():
    calib = RoutingCalibrator([
        _c("cv feasibility", "basketball_cv", "2026-07-14T00:00:01+00:00"),
        _c("cv feasibility", "basketball_cv", "2026-07-14T00:00:02+00:00"),
        _c("cv feasibility", "research", "2026-07-14T00:00:03+00:00"),   # future
    ])
    # as_of excludes the t3 correction -> only the two basketball_cv observations
    past = {r.keyword: r for r in calib.derive(as_of="2026-07-14T00:00:03+00:00")}
    assert past["cv"].board_id == "basketball_cv" and past["cv"].support == 2
    assert past["cv"].distribution == {"basketball_cv": 2}
    # including everything, research now ties in -> "cv" still majority cv (2 vs 1)
    allrules = {r.keyword: r for r in calib.derive()}
    assert allrules["cv"].total == 3


def test_board_rules_filter_by_support_and_resolve_domain():
    calib = RoutingCalibrator([
        _c("write a linkedin post", "posts", "t1"),
        _c("linkedin post idea", "posts", "t2"),
        _c("rare one-off", "misc", "t3"),
    ])
    domain_of = {"posts": "linkedin_post"}.get     # 'misc' resolves to None
    # min_support=2 keeps only the recurring 'linkedin'/'post' keywords; 'misc'
    # is dropped for lacking a resolvable domain (never fabricated)
    rules = calib.board_rules(domain_of, min_support=2)
    assert len(rules) == 1
    r = rules[0]
    assert r.board_id == "posts" and r.domain_id == "linkedin_post"
    assert set(r.keywords) >= {"linkedin", "post"}
    assert all(b != "misc" for b in {x.board_id for x in rules})


def test_min_support_1_includes_single_observation_evidence():
    calib = RoutingCalibrator([_c("dentist", "health", "t1")])
    rules = calib.board_rules({"health": "health"}.get, min_support=1)
    assert rules and rules[0].board_id == "health"
    assert rules[0].keywords == ("dentist",)


def test_learned_board_without_domain_is_derived_but_not_applied():
    calib = RoutingCalibrator([_c("ship the widget", "widgets", "t1")])
    assert any(r.board_id == "widgets" for r in calib.derive())   # learned
    assert calib.board_rules(lambda b: None) == []                # not applied


def test_action_words_still_carry_signal():
    # 'make'/'add'/'new' are NOT function words — they are kept as candidate
    # keywords (the stopword set is closed-class function words only).
    calib = RoutingCalibrator([_c("make a new build", "engineering", "t1")])
    kws = {r.keyword for r in calib.derive()}
    assert {"make", "new", "build"} <= kws
    assert "a" not in kws                                # the function word IS dropped


def test_empty_log_yields_no_rules():
    assert RoutingCalibrator([]).derive() == []
    assert RoutingCalibrator([]).board_rules(lambda b: "d") == []


def test_punctuation_shrapnel_never_becomes_a_keyword():
    # "e.g." normalizes to the tokens "e"/"g" — the live cockpit showed a
    # board suggestion that "matched 'g', 'e'". Fragments below three chars
    # are shrapnel, not signal (except the known real short terms).
    calib = RoutingCalibrator([
        _c("update the plan (e.g. do X or Y)", "site_basketball",
           "2026-07-01T00:00:00+00:00"),
        _c("fix e g artifacts in ui", "site_basketball",
           "2026-07-02T00:00:00+00:00"),
    ])
    keywords = {r.keyword for r in calib.derive()}
    assert "e" not in keywords
    assert "g" not in keywords
    assert "x" not in keywords


def test_short_allowlist_terms_survive():
    calib = RoutingCalibrator([
        _c("finish the cv pipeline", "site_basketball",
           "2026-07-01T00:00:00+00:00"),
    ])
    assert "cv" in {r.keyword for r in calib.derive()}


def test_function_words_like_if_and_not_carry_no_signal():
    # the live cockpit suggested a board because 'if', 'not', 'provide'
    # matched — closed-class words co-occur with everything
    calib = RoutingCalibrator([
        _c("if we can not provide this then stop", "station_improvements",
           "2026-07-01T00:00:00+00:00"),
    ])
    keywords = {r.keyword for r in calib.derive()}
    assert keywords.isdisjoint({"if", "not", "can", "then"})
    assert "provide" in keywords or "stop" in keywords  # content words remain
