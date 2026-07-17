"""Duplicate detection: evidence-tagged, side-effect-free, local-only.

Covers the duplicate-safe todos contract: exact + paraphrase suggestion,
repeat-occurrence classification, related-but-distinct separation, honest
semantic degradation, dependency false-positive protection, and occurrence /
duplicate-decision events on the canonical work graph.
"""
from __future__ import annotations

import inspect
import itertools

from command_center.intake import split_bulk_list
from command_center.work_graph import (
    DuplicateChecker,
    ExistingWorkContext,
    InMemoryWorkGraphStore,
    WorkGraphService,
    WorkRouter,
)
from command_center.work_graph import deduplication


def _ctx(title, *, wid="W-1", status="backlog", capture_raw=None,
         boards=(), occurrences=0):
    return ExistingWorkContext(
        work_item_id=wid, title=title, canonical_status=status,
        capture_raw=capture_raw, board_ids=list(boards),
        occurrence_count=occurrences)


def _service():
    seq = itertools.count(1)
    return WorkGraphService(
        InMemoryWorkGraphStore(),
        clock=lambda: f"2026-07-16T00:00:{next(seq):02d}+00:00",
        id_factory=lambda p: f"{p}-{next(seq)}")


# ---- exact and near matches -------------------------------------------------

def test_exact_duplicate_is_suggested():
    checker = DuplicateChecker([_ctx("Watch tenet", wid="W-9")])
    report = checker.check("Watch tenet")
    assert report.findings[0].match_class == "exact_same"
    assert report.findings[0].existing_work_item_id == "W-9"
    assert any(e.kind == "exact_title" for e in report.findings[0].evidence)


def test_case_and_punctuation_variants_match():
    checker = DuplicateChecker([_ctx("Re caulk bathtub")])
    report = checker.check("re-caulk   BATHTUB!")
    assert report.findings[0].match_class == "exact_same"


def test_reworded_same_outcome_is_suggested():
    # the real gap: raw phone sentence vs the reworded card title
    checker = DuplicateChecker([_ctx(
        "Add adjustable 30-day application outcome memory", status="done")])
    report = checker.check(
        "keep a bare database of jobs applied to lasting 30 days adjustable")
    assert report.findings, "paraphrase must at least be surfaced"
    assert report.findings[0].match_class in ("possible_same", "likely_same")
    kinds = {e.kind for e in report.findings[0].evidence}
    assert kinds & {"same_entity", "lexical_similarity"}


def test_repaste_of_source_capture_is_likely_same():
    # the five job-search re-pastes: identical raw text, reworded title
    raw = ("Make kanban job hunt have a go through application with you "
           "setup so you can work through it one by one page by page "
           "together if wanted.")
    checker = DuplicateChecker([_ctx(
        "Build a page-by-page job application companion", status="done",
        capture_raw=raw)])
    report = checker.check(raw)
    assert report.findings[0].match_class == "likely_same"
    assert any(e.kind == "shared_source" for e in report.findings[0].evidence)


def test_same_action_different_entity_is_not_merged():
    checker = DuplicateChecker([_ctx("Apply to more jobs")])
    report = checker.check("Apply for a passport renewal")
    assert all(f.match_class in ("same_subject_related",)
               for f in report.findings) or not report.findings


def test_same_entity_different_action_is_same_subject_related():
    checker = DuplicateChecker([_ctx("Research the best camera setup")])
    report = checker.check("Buy the selected camera setup")
    assert report.findings
    finding = report.findings[0]
    assert finding.match_class in ("same_subject_related", "possible_same")
    assert "reuse_existing" not in finding.allowed_resolutions or \
        finding.match_class != "same_subject_related"


def test_unrelated_text_produces_no_findings():
    checker = DuplicateChecker([_ctx("Watch tenet")])
    assert checker.check("Fix the downstairs toilet").findings == []


# ---- repeat occurrences -----------------------------------------------------

def test_applied_again_classifies_as_repeat_occurrence():
    checker = DuplicateChecker([_ctx("Apply to more jobs", status="done")])
    report = checker.check("I applied to jobs again")
    finding = report.findings[0]
    assert finding.match_class == "repeat_occurrence"
    assert "add_occurrence" in finding.allowed_resolutions


def test_quantity_phrase_classifies_as_repeat_occurrence():
    checker = DuplicateChecker([_ctx("Apply to more jobs", status="done")])
    report = checker.check("Applied to three more jobs")
    assert report.findings[0].match_class == "repeat_occurrence"


def test_completed_item_offers_reopen():
    checker = DuplicateChecker([_ctx("Watch tenet", status="done")])
    finding = checker.check("Watch tenet").findings[0]
    assert "reopen_existing" in finding.allowed_resolutions
    assert "add_occurrence" in finding.allowed_resolutions   # rewatch


# ---- expansion, subtasks, parents --------------------------------------------

def test_expansion_deltas_are_field_level():
    checker = DuplicateChecker([_ctx("Build an editable company watchlist")])
    report = checker.check(
        "Build an editable company watchlist. Track competitor companies. "
        "Refresh the list weekly. Notify me when a target company posts a "
        "suitable job.")
    finding = report.findings[0]
    assert finding.match_class == "expands_existing"
    assert "expand_existing" in finding.allowed_resolutions
    kinds = [d.kind for d in finding.expansion_deltas]
    assert len(finding.expansion_deltas) >= 3
    assert "recurrence" in kinds                     # "refresh weekly"
    # the fragment equal to the existing title adds nothing -> not a delta
    texts = [d.text for d in finding.expansion_deltas]
    assert "Build an editable company watchlist" not in texts


def test_subtask_of_project_is_classified():
    checker = DuplicateChecker([
        _ctx("Camera Setup Project", wid="W-p1", status="in_progress")
        .model_copy(update={"kind": "project"})])
    report = checker.check("Buy the tripod for the camera setup")
    finding = report.findings[0]
    assert finding.match_class == "subtask_of_existing"
    assert "add_child" in finding.allowed_resolutions
    assert finding.suggested_parent_id == "W-p1"
    assert finding.suggested_relation == "parent_of"


def test_parent_of_existing_detected_for_umbrella_text():
    checker = DuplicateChecker([_ctx("Research camera options", wid="W-c1")])
    report = checker.check(
        "Camera setup project: research camera options, buy the selected "
        "setup, and test the installation")
    finding = report.findings[0]
    assert finding.match_class == "parent_of_existing"
    assert "create_project_group" in finding.allowed_resolutions


# ---- subject groups and board fit ---------------------------------------------

def test_related_tasks_suggest_project_group_not_board():
    checker = DuplicateChecker([
        _ctx("Research the best camera setup", wid="W-1"),
        _ctx("Compare camera prices", wid="W-2"),
    ])
    report = checker.check("Buy a camera tripod")
    assert report.subject_groups
    group = report.subject_groups[0]
    assert set(group.member_work_item_ids) == {"W-1", "W-2"}
    assert group.existing_parent_id is None
    assert group.suggested_group_title            # proposes a PROJECT
    assert "board" not in (group.suggested_group_title or "").lower()


def test_related_tasks_suggest_existing_project_parent():
    checker = DuplicateChecker([
        _ctx("Camera Setup", wid="W-p").model_copy(
            update={"kind": "project"}),
        _ctx("Research the best camera setup", wid="W-1").model_copy(
            update={"parent_id": "W-p"}),
        _ctx("Compare camera prices", wid="W-2").model_copy(
            update={"parent_id": "W-p"}),
    ])
    report = checker.check("Buy a camera tripod")
    assert report.subject_groups
    assert report.subject_groups[0].existing_parent_id == "W-p"
    assert report.subject_groups[0].suggested_group_title is None


def test_board_fit_suggests_board_where_subject_clusters():
    checker = DuplicateChecker([
        _ctx("Fix trade history filters", wid="W-1",
             boards=["site_basketball"]),
        _ctx("Add trade grades to news", wid="W-2",
             boards=["site_basketball"]),
        _ctx("Have trade history feed into news", wid="W-3",
             boards=["site_basketball"]),
    ])
    report = checker.check("Expand the trade history tab with pick cards")
    assert report.board_fit
    assert report.board_fit[0].board_id == "site_basketball"
    assert report.board_fit[0].matching_item_count >= 3


def test_exact_match_produces_no_group_noise():
    checker = DuplicateChecker([_ctx("Watch tenet", wid="W-1")])
    report = checker.check("Watch tenet")
    assert report.subject_groups == []
    assert report.board_fit == []


# ---- review-findings regressions ---------------------------------------------

def test_exact_repaste_with_repeat_words_is_exact_not_occurrence():
    # Codex finding #5: "Apply to more jobs" re-pasted verbatim contains
    # "more" but is the SAME statement — identity outranks repeat phrasing
    checker = DuplicateChecker([_ctx("Apply to more jobs", status="done")])
    finding = checker.check("Apply to more jobs").findings[0]
    assert finding.match_class == "exact_same"


def test_verbatim_source_repaste_outranks_repeat_marker():
    raw = "Applied to 30 companies via the kanban flow"
    checker = DuplicateChecker([_ctx(
        "Track kanban applications", capture_raw=raw)])
    assert checker.check(raw).findings[0].match_class == "likely_same"


def test_deltas_are_description_aware_and_stable():
    # Codex finding #6: match-time and resolve-time extraction must use
    # identical inputs or selected ids shift positionally
    ctx = _ctx("Build a watchlist").model_copy(update={
        "description": "Track competitor companies."})
    report = DuplicateChecker([ctx]).check(
        "Build a watchlist. Track competitor companies. Refresh weekly.")
    finding = report.findings[0]
    texts = [d.text for d in finding.expansion_deltas]
    # the description-known fragment adds nothing -> NOT a delta
    assert "Track competitor companies." not in texts
    assert any("Refresh weekly" in t for t in texts)
    from command_center.work_graph import extract_deltas
    recomputed = extract_deltas(
        "Build a watchlist. Track competitor companies. Refresh weekly.",
        ctx.title, ctx.description)
    assert [(d.delta_id, d.text) for d in finding.expansion_deltas] == \
        [(d.delta_id, d.text) for d in recomputed]


def test_same_work_match_suppresses_group_and_board_suggestions():
    # Codex finding #7: a capture that IS existing work must not also offer
    # grouping — the group action would recreate it as a duplicate child
    checker = DuplicateChecker([
        _ctx("Watch tenet", wid="W-1", boards=["movies_shows"]),
        _ctx("Watch tenet again soon", wid="W-2", boards=["movies_shows"]),
        _ctx("Tenet rewatch notes", wid="W-3", boards=["movies_shows"]),
    ])
    report = checker.check("Watch tenet")
    assert report.findings[0].match_class == "exact_same"
    assert report.subject_groups == []
    assert report.board_fit == []


# ---- honesty and privacy ----------------------------------------------------

def test_semantic_backend_unavailable_degrades_visibly_to_lexical():
    report = DuplicateChecker([_ctx("Watch tenet")]).check("Watch tenet")
    assert report.semantic_backend == "unavailable_lexical_only"


def test_no_external_embedding_call_for_private_todos():
    src = inspect.getsource(deduplication)
    for banned in ("httpx", "urllib", "requests", "socket", "openai",
                   "anthropic"):
        assert banned not in src, f"dedup module must not import {banned}"


def test_check_is_side_effect_free():
    ctxs = [_ctx("Watch tenet", status="done")]
    checker = DuplicateChecker(ctxs)
    before = [c.model_dump() for c in ctxs]
    checker.check("Watch tenet")
    checker.check("watched tenet again")
    assert [c.model_dump() for c in ctxs] == before


# ---- router integration -----------------------------------------------------

def _router(existing):
    return WorkRouter(split=split_bulk_list,
                      duplicate_checker=DuplicateChecker(existing))


def test_router_surfaces_rich_report_and_legacy_candidate():
    proposal = _router([_ctx("Watch tenet", wid="W-7", status="done")]).route(
        "Watch tenet")
    assert proposal.duplicate_candidates[0].existing_work_item_id == "W-7"
    assert proposal.duplicate_reports[0].report.findings[0].match_class == \
        "exact_same"
    q = next(q for q in proposal.needs_confirmation
             if "what should happen" in q.question)
    assert "add_occurrence" in q.options


def test_router_repeat_occurrence_question_offers_update():
    proposal = _router(
        [_ctx("Apply to more jobs", status="in_progress")]).route(
        "applied to jobs again")
    assert any("progress on" in q.question
               for q in proposal.needs_confirmation)


def test_router_possible_match_is_reported_but_not_blocking():
    proposal = _router([_ctx(
        "Add adjustable 30-day application outcome memory")]).route(
        "keep a database of jobs applied to for 30 days")
    assert proposal.duplicate_reports          # surfaced as evidence
    assert not proposal.duplicate_candidates   # but never a blocking dup


def test_router_without_checker_keeps_exact_rule():
    router = WorkRouter(split=split_bulk_list,
                        existing_titles=[("W-3", "Watch tenet")])
    proposal = router.route("Watch tenet")
    assert proposal.duplicate_candidates[0].existing_work_item_id == "W-3"


# ---- dependency false-positive protection -----------------------------------

def test_burn_after_reading_is_not_a_dependency():
    proposal = _router([]).route("Burn after reading")
    assert not any("depend" in q.question or "time context" in q.question
                   for q in proposal.needs_confirmation)


def test_movie_titles_do_not_trigger_dependency_parser():
    titles = ["Burn after reading", "One of them days",
              "Back in actionf", "The bounty hunter",
              "Seeking a friend for the end of the world"]
    for title in titles:
        proposal = _router([]).route(title)
        assert not any("block or depend" in q.question
                       for q in proposal.needs_confirmation), title


def test_before_movie_phrase_asks_for_timing_not_fake_graph_edge():
    proposal = _router([]).route(
        "Get tie for the grey suit at mens warehouse before movie or "
        "something")
    questions = [q.question for q in proposal.needs_confirmation]
    assert any("time context" in q for q in questions)
    assert not any("block or depend" in q for q in questions)


def test_two_deliverable_dependency_still_asks():
    proposal = _router([]).route(
        "finish the website content before we submit the launch review")
    assert any("block or depend" in q.question
               for q in proposal.needs_confirmation)


# ---- occurrences + decisions on the canonical graph --------------------------

def test_add_occurrence_increments_badge_and_keeps_status():
    svc = _service()
    item = svc.create_item("Apply to more jobs")
    svc.set_status(item.work_item_id, "done")
    svc.add_occurrence(item.work_item_id, note="Applied again")
    svc.add_occurrence(item.work_item_id, quantity=3, unit="applications",
                       source_capture_id="cap-abc123")
    assert svc.occurrence_count(item.work_item_id) == 2
    assert svc.get_item(item.work_item_id).canonical_status == "done"


def test_occurrence_preserves_source_capture_and_quantity():
    svc = _service()
    item = svc.create_item("Apply to more jobs")
    event = svc.add_occurrence(item.work_item_id, quantity=3,
                               unit="applications",
                               source_capture_id="cap-abc123",
                               note="Applied to three more jobs")
    assert event.payload == {
        "note": "Applied to three more jobs", "quantity": 3,
        "unit": "applications", "source_capture_id": "cap-abc123"}


def test_occurrence_rejects_nonpositive_quantity():
    svc = _service()
    item = svc.create_item("Apply to more jobs")
    try:
        svc.add_occurrence(item.work_item_id, quantity=0)
    except ValueError:
        pass
    else:
        raise AssertionError("quantity=0 must be rejected")
    assert svc.occurrence_count(item.work_item_id) == 0


def test_duplicate_decision_is_recorded_append_only():
    svc = _service()
    item = svc.create_item("Watch tenet")
    svc.record_duplicate_decision(
        item.work_item_id, resolution="add_occurrence",
        capture_id="cap-1", match_class="repeat_occurrence",
        evidence_kinds=["same_action", "same_entity"], note="rewatch")
    svc.record_duplicate_decision(
        item.work_item_id, resolution="discard_capture", capture_id="cap-2")
    decisions = svc.duplicate_decisions(item.work_item_id)
    assert [d.payload["resolution"] for d in decisions] == [
        "add_occurrence", "discard_capture"]
