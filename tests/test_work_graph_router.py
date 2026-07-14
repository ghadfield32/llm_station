"""WorkRouter — deterministic free-text → proposed plan. It PROPOSES, never acts:
splits deliverables, tags evidence-backed board suggestions, asks (never guesses)
on ambiguity/dependency, flags exact-title duplicates without dropping them, and
commits nothing. No LLM, no fuzzy thresholds — hermetic and honest.
"""
from __future__ import annotations

from command_center.intake import split_bulk_list
from command_center.work_graph import BoardRule, RoutingProposal, WorkRouter


def _router(**kw) -> WorkRouter:
    return WorkRouter(split=split_bulk_list, **kw)


def test_bulk_list_splits_into_one_item_each():
    prop = _router().route("- alpha\n- beta\n- gamma")
    assert [it.title for it in prop.plan.items] == ["alpha", "beta", "gamma"]
    assert [it.ref for it in prop.plan.items] == ["i1", "i2", "i3"]


def test_single_line_is_one_item():
    prop = _router().route("just one thought")
    assert len(prop.plan.items) == 1


def test_matched_board_rule_suggests_with_evidence_and_sets_primary():
    r = _router(board_rules=[BoardRule(board_id="posts", domain_id="posts",
                                       keywords=("post", "linkedin"))])
    prop = r.route("write a linkedin post about historical metrics")
    assert prop.plan.items[0].primary_board.board_id == "posts"
    sug = prop.board_suggestions[0]
    assert sug.board_id == "posts" and "linkedin" in sug.reason
    # a confidently-routed item raises no board question
    assert not any(q.question.startswith("Which board") for q in prop.needs_confirmation)


def test_unmatched_board_asks_the_human_with_real_options():
    r = _router(known_boards=["research", "posts", "basketball_cv"])
    prop = r.route("do the thing")
    assert prop.plan.items[0].primary_board is None        # never auto-routed
    q = next(q for q in prop.needs_confirmation if q.question.startswith("Which board"))
    assert q.options == ["research", "posts", "basketball_cv"]


def test_ambiguous_board_lists_both_matches_and_still_asks():
    r = _router(board_rules=[
        BoardRule(board_id="research", domain_id="research", keywords=("research",)),
        BoardRule(board_id="posts", domain_id="posts", keywords=("post",))])
    prop = r.route("research and post about it")               # matches BOTH
    assert prop.plan.items[0].primary_board is None
    assert {s.board_id for s in prop.board_suggestions} == {"research", "posts"}
    q = next(q for q in prop.needs_confirmation if q.question.startswith("Which board"))
    assert set(q.options) == {"research", "posts"}


def test_kind_inferred_from_keywords():
    r = _router()
    assert r.route("write a post").plan.items[0].kind == "post"
    assert r.route("research the feasibility").plan.items[0].kind == "research"
    assert r.route("mow the lawn").plan.items[0].kind == "todo"


def test_exact_duplicate_is_flagged_not_dropped():
    r = _router(existing_titles=[("W-9", "Call the dentist")])
    prop = r.route("call the dentist!")                         # same normalized title
    assert len(prop.plan.items) == 1                            # still proposed
    assert prop.duplicate_candidates[0].existing_work_item_id == "W-9"
    assert any("reuse it" in q.question for q in prop.needs_confirmation)


def test_dependency_word_raises_a_question_never_an_edge():
    prop = _router().route("confirm footage rights before implementation")
    assert prop.plan.edges == []                               # NO fabricated edge
    assert any("dependency" in q.question for q in prop.needs_confirmation)


def test_route_is_a_pure_proposal():
    # the router holds no store — route() returns a proposal and mutates nothing.
    prop = _router().route("- a\n- b")
    assert isinstance(prop, RoutingProposal)
    assert prop.plan.edges == []
    # a proposal is not a commit: no work_item ids are assigned yet (refs only)
    assert all(it.ref.startswith("i") for it in prop.plan.items)


def test_empty_input_yields_no_items_with_a_note():
    prop = _router().route("   ")
    assert prop.plan.items == []
    assert prop.notes
