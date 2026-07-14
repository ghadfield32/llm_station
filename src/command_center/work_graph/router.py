"""WorkRouter — a DETERMINISTIC first-pass router that turns free text (a pasted
idea list, or a capture's raw content) into a *proposed* work plan for a human to
review, edit, and only then commit via the preview/convert/commit endpoints.

It is a proposer, never an actor:
  * It NEVER commits — `route()` returns a RoutingProposal and touches no store.
  * It NEVER silently auto-routes to a board. Board suggestions are evidence-
    tagged (which keyword matched which injected rule); anything not matched by
    exactly one rule becomes a needs_confirmation question, and the plan item's
    primary board is left unset. No injected rules → every item asks the human
    which board (the honest default until routing is calibrated).
  * It NEVER fabricates a dependency edge. Ordering words ("before", "until", …)
    surface a needs_confirmation question ("does this block another item?"),
    they do not invent an edge whose endpoints it cannot determine.
  * It NEVER auto-drops a likely duplicate. An EXACT normalized-title match
    against an existing item becomes a duplicate_candidate + a question; the item
    is still proposed.

Everything here is rule-based and injected (board rules, known boards, existing
titles) so it is hermetic and honest — no LLM, no invented thresholds, no fuzzy
similarity cutoffs (exact normalized match only; fuzzy dedup is a calibrated
later phase). Kind inference sets a default label the human can change.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from pydantic import BaseModel, Field

from .planner import PlanBoardRef, WorkPlanIn, WorkPlanItemIn, summarize_plan
from .schemas import BoardSuggestion, RoutingQuestion, WorkGraphPlanSummary

# keyword -> default WorkItem kind. A default LABEL the human can change, tagged
# with the word that matched — not a claim about the work, just a starting point.
_KIND_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("post", ("post", "linkedin", "tweet", "thread")),
    ("paper", ("paper", "publication", "manuscript")),
    ("research", ("research", "feasibility", "investigate", "explore", "study")),
    ("bug", ("bug", "broken", "regression", "hotfix")),
    ("feature", ("feature", "implement", "build a", "add a")),
    ("decision", ("decide", "decision", "choose between")),
)
# words that signal a dependency but whose endpoints text alone can't fix — they
# raise a question, never an invented edge.
_DEP_WORDS: tuple[str, ...] = (
    "before", "until", "after", "once", "prerequisite", "depends on",
    "blocked by", "blocks", "first,")


class BoardRule(BaseModel):
    """An injected keyword→board rule. Evidence-backed routing config, provided by
    the caller (not invented here); a match records which keyword fired."""
    board_id: str
    domain_id: str
    keywords: tuple[str, ...]


class DuplicateCandidate(BaseModel):
    ref: str
    existing_work_item_id: str
    existing_title: str
    reason: str


class RoutingProposal(BaseModel):
    """A PROPOSAL, never a commit. `plan` is a ready-to-review WorkPlanIn (board
    left unset unless one rule matched); the human confirms the questions and
    edits before calling /convert or /commit."""
    conversation_id: str | None = None
    capture_id: str | None = None
    plan: WorkPlanIn
    summary: WorkGraphPlanSummary | None = None    # "this will create …"
    board_suggestions: list[BoardSuggestion] = Field(default_factory=list)
    needs_confirmation: list[RoutingQuestion] = Field(default_factory=list)
    duplicate_candidates: list[DuplicateCandidate] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def _infer_kind(norm_title: str) -> str:
    for kind, words in _KIND_KEYWORDS:
        if any(w in norm_title for w in words):
            return kind
    return "todo"


class WorkRouter:
    def __init__(self, *, split: Callable[[str], list[str]],
                 board_rules: Sequence[BoardRule] = (),
                 known_boards: Sequence[str] = (),
                 existing_titles: Sequence[tuple[str, str]] = ()) -> None:
        # split: text -> list of deliverable lines (inject intake.split_bulk_list)
        # existing_titles: (work_item_id, title) pairs for exact-dup detection
        self._split = split
        self._rules = list(board_rules)
        self._known_boards = list(known_boards)
        self._existing = [(wid, _normalize(t)) for wid, t in existing_titles]

    def route(self, text: str, *, conversation_id: str | None = None,
              capture_id: str | None = None) -> RoutingProposal:
        lines = [ln for ln in self._split(text or "") if ln.strip()]
        items: list[WorkPlanItemIn] = []
        suggestions: list[BoardSuggestion] = []
        questions: list[RoutingQuestion] = []
        dups: list[DuplicateCandidate] = []
        notes: list[str] = []

        for i, line in enumerate(lines):
            ref = f"i{i + 1}"
            title = line.strip()
            norm = _normalize(title)
            kind = _infer_kind(norm)

            primary = self._route_board(ref, norm, suggestions, questions)
            items.append(WorkPlanItemIn(ref=ref, title=title, kind=kind,
                                        primary_board=primary))

            self._flag_duplicate(ref, title, norm, dups, questions)
            self._flag_dependency(ref, norm, title, questions)

        if not items:
            notes.append("no deliverables found in the input")
        plan = WorkPlanIn(conversation_id=conversation_id, capture_id=capture_id,
                          items=items, edges=[])
        return RoutingProposal(
            conversation_id=conversation_id, capture_id=capture_id, plan=plan,
            summary=summarize_plan(plan),
            board_suggestions=suggestions, needs_confirmation=questions,
            duplicate_candidates=dups, notes=notes)

    # ---- board routing: evidence-tagged suggestion, else ask -----------------
    def _route_board(self, ref: str, norm: str, suggestions: list[BoardSuggestion],
                     questions: list[RoutingQuestion]) -> PlanBoardRef | None:
        # whole-word (not substring) match: a short derived keyword like 'cv' must
        # not fire inside an unrelated word. norm is already punctuation-stripped +
        # single-spaced by _normalize, so \b word boundaries are exact.
        matched = [(r, [w for w in r.keywords
                        if re.search(rf"\b{re.escape(w)}\b", norm)])
                   for r in self._rules]
        matched = [(r, ws) for r, ws in matched if ws]
        if len(matched) == 1:
            rule, words = matched[0]
            suggestions.append(BoardSuggestion(
                ref=ref, board_id=rule.board_id,
                reason=f"matched {', '.join(repr(w) for w in words)}"))
            return PlanBoardRef(board_id=rule.board_id, domain_id=rule.domain_id)
        # zero or ambiguous matches → the human picks; never auto-routed
        if len(matched) > 1:
            for rule, words in matched:
                suggestions.append(BoardSuggestion(
                    ref=ref, board_id=rule.board_id,
                    reason=f"matched {', '.join(repr(w) for w in words)}"))
        questions.append(RoutingQuestion(
            ref=ref, question="Which board should this go on?",
            options=([r.board_id for r, _ in matched] if matched
                     else list(self._known_boards))))
        return None

    def _flag_duplicate(self, ref: str, title: str, norm: str,
                        dups: list[DuplicateCandidate],
                        questions: list[RoutingQuestion]) -> None:
        for wid, existing_norm in self._existing:
            if existing_norm and existing_norm == norm:
                dups.append(DuplicateCandidate(
                    ref=ref, existing_work_item_id=wid, existing_title=title,
                    reason="exact title match with an existing work item"))
                questions.append(RoutingQuestion(
                    ref=ref, question=f"'{title}' matches existing work "
                    f"{wid} — reuse it, create separate, or link as related?",
                    options=["use_existing", "create_separate", "link_related"]))
                return

    def _flag_dependency(self, ref: str, norm: str, title: str,
                         questions: list[RoutingQuestion]) -> None:
        hit = next((w for w in _DEP_WORDS if w in norm), None)
        if hit is not None:
            questions.append(RoutingQuestion(
                ref=ref, question=f"'{title}' reads like a dependency "
                f"(matched {hit!r}) — which item does it block or depend on?",
                options=[]))
