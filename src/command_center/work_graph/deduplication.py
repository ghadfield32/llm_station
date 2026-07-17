"""Deterministic, side-effect-free duplicate detection over canonical work.

Extends the router's exact-normalized-title rule with EVIDENCE-TAGGED match
classes. Like the router, this is a PROPOSER: it never merges, discards,
reopens, converts, or deletes anything. Every candidate carries plain-language
evidence and the resolutions a human may choose from; choices are recorded by
the DuplicateDecision path, never made here.

Design boundaries (per the duplicate-safe todos contract):
  * A similarity number is DIAGNOSTIC evidence, not a verdict. Lexical and
    structured signals map to a conservative match_class; anything weaker than
    exact/shared-source is at most "possible_same" until human decisions
    accumulate calibration evidence.
  * Semantic retrieval is a pluggable LOCAL hook. It is absent by default and
    its absence is stated on the report (`semantic_backend`), never silently
    ignored. Private todo text is never sent to an external embedding API.
  * Repeated activity ("applied to jobs again") classifies as
    repeat_occurrence so the UI can offer an occurrence event instead of a
    duplicate card.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

# Per-candidate classes the checker emits. Report-level outcomes that are NOT
# per-candidate classes: "same_project_cluster" (a SubjectGroupSuggestion over
# several candidates), "board_fit_only" (a BoardFitSuggestion), and
# "unrelated" (the absence of findings).
MatchClass = Literal[
    "exact_same", "likely_same", "possible_same", "repeat_occurrence",
    "expands_existing", "subtask_of_existing", "parent_of_existing",
    "same_subject_related", "same_project_cluster", "board_fit_only",
    "unrelated"]

Resolution = Literal[
    "reuse_existing", "add_occurrence", "reopen_existing", "create_separate",
    "link_related", "discard_capture", "archive_existing", "remove_placement",
    "expand_existing", "add_child", "group_under_existing",
    "create_project_group"]

EvidenceKind = Literal[
    "exact_title", "normalized_title", "same_action", "same_entity",
    "same_outcome", "same_project", "lexical_similarity",
    "semantic_similarity", "shared_source", "graph_context", "same_board"]

DeltaKind = Literal[
    "detail", "note", "acceptance_criterion", "constraint", "source_link",
    "subtask", "dependency", "due_date", "tag", "recurrence", "progress"]

# match classes ordered strongest-first for report ordering
_CLASS_RANK: dict[str, int] = {
    "exact_same": 0, "likely_same": 1, "repeat_occurrence": 2,
    "expands_existing": 3, "subtask_of_existing": 4, "parent_of_existing": 5,
    "possible_same": 6, "same_subject_related": 7, "same_project_cluster": 8,
    "board_fit_only": 9, "unrelated": 10}

_STOPWORDS = frozenset(
    "the a an to of and or for so we it its is are be can could should would "
    "have has had with that this these those on in at as my our your me i us "
    "you they them there then than will was were do does did done just like "
    "up out if but not no yes when what which who how all any some more most "
    "also into from by about".split())

# curated action verbs (stemmed comparison happens on top of these)
_ACTIONS = frozenset(
    "apply build add fix finish book buy get set setup create update make "
    "implement migrate organize check submit post learn research clean order "
    "install write plan schedule send review upgrade complete prepare track "
    "keep watch read recaulk repatch backup unseam ensure expand include "
    "sort split move delete archive verify test run confirm merge deploy "
    "launch ship publish release design refactor".split())

# action synonyms canonicalized before comparison: "schedule the appointment"
# and "book the appointment" name the SAME action. Small and curated — never
# a similarity model.
_ACTION_SYNONYMS = {
    "schedule": "book", "purchase": "buy", "repair": "fix",
    "complete": "finish", "construct": "build"}


def _action_set(tokens: set[str]) -> set[str]:
    return {_ACTION_SYNONYMS.get(t, t) for t in tokens if t in _ACTIONS}


# noun suffixes whose stems are still actions: implementation -> implement,
# confirmation -> confirm. Checked ONLY for action detection, never identity.
_NOUN_ACTION_SUFFIXES = ("ation", "ment", "ing", "ion")


def _contains_action(text_fragment: str) -> bool:
    """True when the fragment names a recognizable action, including noun
    forms of the curated verbs (e.g. 'implementation')."""
    for raw in _normalize(text_fragment).split():
        candidates = {raw, _stem(raw)}
        for suffix in _NOUN_ACTION_SUFFIXES:
            if len(raw) > len(suffix) + 2 and raw.endswith(suffix):
                candidates.add(raw[: -len(suffix)])
        if candidates & _ACTIONS:
            return True
    return False


# phrasing that signals repeated progress on existing work, not a new task
_REPEAT_MARKERS = frozenset("again more another additional".split())
_QUANTITY = re.compile(r"\b(\d+)\b")
_NUMBER_WORDS = frozenset(
    "one two three four five six seven eight nine ten couple few".split())


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def _stem(token: str) -> str:
    """Light, deterministic stem for token comparison only (never display)."""
    if len(token) > 4 and token.endswith(("ied", "ies")):
        return token[:-3] + "y"          # applied -> apply, studies -> study
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _tokens(norm: str) -> set[str]:
    return {_stem(t) for t in norm.split() if t not in _STOPWORDS and len(t) > 1}


def _containment(a: set[str], b: set[str]) -> float:
    """Overlap over the smaller set — robust when one text is much longer."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


class DuplicateEvidence(BaseModel):
    kind: EvidenceKind
    detail: str                      # plain language, shown to the human
    source: str                      # which signal produced it


class ExpansionDelta(BaseModel):
    """One selectable piece of NEW information a capture adds to existing
    work. Applying deltas is append-only: the existing title and description
    are never replaced automatically."""
    delta_id: str
    kind: DeltaKind
    text: str
    proposed_target: str = "existing"     # existing | child
    selected: bool = True


class SubjectGroupSuggestion(BaseModel):
    """Several existing items + the new text share a subject: suggest grouping
    them under an existing project or creating a new project group. A project
    group is a WorkItem(kind='project') with parent_of edges — it is NOT a
    board, and suggesting it never creates anything."""
    subject_tokens: list[str]
    member_work_item_ids: list[str]
    member_titles: list[str]
    existing_parent_id: str | None = None
    existing_parent_title: str | None = None
    suggested_group_title: str | None = None
    detail: str


class BoardFitSuggestion(BaseModel):
    """Existing items about the same subject cluster on one board: evidence
    for routing the NEW item there. Separate work, same home — never a merge
    signal."""
    board_id: str
    matching_item_count: int
    detail: str


class ExistingWorkContext(BaseModel):
    """Everything the checker may see about one existing canonical item.
    Composed by the caller from the work graph + capture store; the checker
    itself reads no store."""
    work_item_id: str
    title: str
    canonical_status: str = "backlog"
    board_ids: list[str] = Field(default_factory=list)
    primary_board_id: str | None = None
    capture_raw: str | None = None       # immutable source text, if captured
    description: str = ""                # for delta novelty comparison
    last_activity_at: str | None = None
    completion_at: str | None = None
    occurrence_count: int = 0
    kind: str = "todo"
    parent_id: str | None = None         # parent project, when one exists


class DuplicateFinding(BaseModel):
    existing_work_item_id: str
    title: str
    canonical_status: str
    board_ids: list[str] = Field(default_factory=list)
    primary_board_id: str | None = None
    match_class: MatchClass
    evidence: list[DuplicateEvidence] = Field(default_factory=list)
    last_activity_at: str | None = None
    completion_at: str | None = None
    occurrence_count: int = 0
    expansion_deltas: list[ExpansionDelta] = Field(default_factory=list)
    suggested_parent_id: str | None = None
    suggested_relation: str | None = None
    allowed_resolutions: list[Resolution] = Field(default_factory=list)


class DuplicateReport(BaseModel):
    """The side-effect-free result of checking ONE text: per-candidate
    findings plus report-level subject-group and board-fit suggestions.
    'unrelated' is the absence of all three."""
    text: str
    normalized: str
    findings: list[DuplicateFinding] = Field(default_factory=list)
    subject_groups: list[SubjectGroupSuggestion] = Field(default_factory=list)
    board_fit: list[BoardFitSuggestion] = Field(default_factory=list)
    # honest degradation: absent semantic backend is stated, never implied away
    semantic_backend: str = "unavailable_lexical_only"


def _resolutions(match_class: MatchClass, status: str) -> list[Resolution]:
    base: list[Resolution]
    if match_class == "repeat_occurrence":
        base = ["add_occurrence", "create_separate", "link_related",
                "discard_capture"]
    elif match_class == "expands_existing":
        base = ["expand_existing", "add_child", "reuse_existing",
                "create_separate", "link_related", "discard_capture"]
    elif match_class == "subtask_of_existing":
        base = ["add_child", "link_related", "create_separate",
                "discard_capture"]
    elif match_class == "parent_of_existing":
        base = ["create_project_group", "link_related", "create_separate",
                "discard_capture"]
    elif match_class == "same_subject_related":
        base = ["link_related", "group_under_existing",
                "create_project_group", "create_separate", "discard_capture"]
    else:
        base = ["reuse_existing", "create_separate", "link_related",
                "discard_capture"]
        if status in ("in_progress", "done"):
            base.insert(1, "add_occurrence")
    if status in ("done", "archived", "rejected"):
        if "reopen_existing" not in base:
            base.insert(1, "reopen_existing")
    base.append("archive_existing")
    return base


_URL = re.compile(r"https?://\S+")
_RECURRENCE_WORDS = frozenset(
    "daily weekly monthly quarterly yearly every recurring".split())
_DUE_WORDS = frozenset("due deadline by before until".split())


def _split_fragments(text: str) -> list[str]:
    """Deterministic fragment split for delta extraction: sentences and
    line/bullet boundaries. No LLM, no rewriting — fragments are verbatim."""
    parts: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        for frag in re.split(r"(?<=[.!?;])\s+", line.strip()):
            frag = frag.strip(" \t-•◦⁃‣")
            if frag:
                parts.append(frag)
    return parts


def extract_deltas(new_text: str, existing_title: str,
                   existing_description: str = "") -> list[ExpansionDelta]:
    """Selectable NEW information the text adds beyond the existing item.
    A fragment qualifies only when it carries tokens the existing item lacks;
    classification is keyword-deterministic. Applying is the caller's job —
    extraction never mutates anything."""
    known = _tokens(_normalize(existing_title)) | _tokens(
        _normalize(existing_description))
    deltas: list[ExpansionDelta] = []
    for i, frag in enumerate(_split_fragments(new_text)):
        norm = _normalize(frag)
        novel = _tokens(norm) - known
        if not novel and not _URL.search(frag):
            continue                      # nothing new in this fragment
        raw_words = set(norm.split())
        if _URL.search(frag):
            kind: DeltaKind = "source_link"
        elif raw_words & _RECURRENCE_WORDS:
            kind = "recurrence"
        elif raw_words & _DUE_WORDS and _contains_action(frag):
            kind = "due_date"
        elif (_QUANTITY.search(norm) or raw_words & _NUMBER_WORDS) and (
                raw_words & _REPEAT_MARKERS):
            kind = "progress"
        elif _contains_action(frag):
            kind = "subtask"
        else:
            kind = "detail"
        deltas.append(ExpansionDelta(
            delta_id=f"d{i + 1}", kind=kind, text=frag,
            proposed_target="child" if kind == "subtask" else "existing"))
    return deltas


class DuplicateChecker:
    """Checks one text against injected existing-work contexts. Hermetic:
    no store, no clock, no network. A LOCAL semantic retrieval stage plugs in
    here in a later, evidence-calibrated slice; until it exists every report
    states `unavailable_lexical_only` — the absence is reported, never
    simulated."""

    #: at most this many findings are returned, strongest first
    MAX_FINDINGS = 3
    #: containment at/above which lexical overlap alone is a likely match
    LIKELY_CONTAINMENT = 0.8
    #: containment at/above which lexical overlap alone is a possible match
    POSSIBLE_CONTAINMENT = 0.45

    def __init__(self, existing: Sequence[ExistingWorkContext]) -> None:
        self._existing = list(existing)

    def check(self, text: str) -> DuplicateReport:
        norm = _normalize(text)
        toks = _tokens(norm)
        actions = _action_set(toks)
        entities = toks - _ACTIONS - _REPEAT_MARKERS - _NUMBER_WORDS
        # repeat markers checked against RAW words — stopword filtering must
        # never eat "more"/"again"; number words also signal logged activity
        raw_words = set(norm.split())
        has_repeat = bool(
            raw_words & _REPEAT_MARKERS or raw_words & _NUMBER_WORDS
            or _QUANTITY.search(norm))

        findings: list[tuple[float, DuplicateFinding]] = []
        for ctx in self._existing:
            found = self._match_one(
                ctx, text=text, norm=norm, toks=toks, actions=actions,
                entities=entities, has_repeat=has_repeat)
            if found is not None:
                findings.append(found)
        findings.sort(key=lambda pair: (
            _CLASS_RANK[pair[1].match_class], -pair[0]))
        top = [f for _, f in findings[: self.MAX_FINDINGS]]
        # a capture that IS existing work must not also invite grouping —
        # a group action would recreate it as a duplicate child
        is_same_work = any(f.match_class in
                           ("exact_same", "likely_same", "repeat_occurrence")
                           for f in top)
        report = DuplicateReport(
            text=text, normalized=norm, findings=top,
            subject_groups=([] if is_same_work
                            else self._subject_groups(entities, top)),
            board_fit=[] if is_same_work else self._board_fit(entities, top),
            semantic_backend="unavailable_lexical_only")
        return report

    # -- report-level: subject clusters and board fit ----------------------
    def _related(self, entities: set[str]) -> list[tuple[
            set[str], "ExistingWorkContext"]]:
        """Existing items sharing at least one meaningful entity token."""
        out = []
        for ctx in self._existing:
            shared = entities & (_tokens(_normalize(ctx.title)) - _ACTIONS)
            if shared:
                out.append((shared, ctx))
        return out

    def _subject_groups(self, entities: set[str],
                        top: list[DuplicateFinding]
                        ) -> list[SubjectGroupSuggestion]:
        """same_project_cluster: >=2 existing items share the new text's
        subject and none of them is already the same work. Suggest grouping
        under an existing project parent when one exists, else propose a new
        project group — a SUGGESTION only, nothing is created."""
        same_work = {f.existing_work_item_id for f in top if f.match_class in
                     ("exact_same", "likely_same", "repeat_occurrence")}
        related = [(shared, ctx) for shared, ctx in self._related(entities)
                   if ctx.work_item_id not in same_work]
        if len(related) < 2:
            return []
        by_id = {c.work_item_id: c for c in self._existing}
        subject = sorted(set().union(*[s for s, _ in related]))
        members = [ctx for _, ctx in related][:6]
        parent = next(
            (by_id[m.parent_id] for m in members
             if m.parent_id and m.parent_id in by_id), None)
        if parent is None:
            parent = next((m for m in members if m.kind == "project"), None)
        return [SubjectGroupSuggestion(
            subject_tokens=subject[:5],
            member_work_item_ids=[m.work_item_id for m in members],
            member_titles=[m.title for m in members],
            existing_parent_id=parent.work_item_id if parent else None,
            existing_parent_title=parent.title if parent else None,
            suggested_group_title=(None if parent else
                                   " ".join(subject[:3]).title() + " Project"),
            detail=(f"{len(members)} existing items share the subject "
                    f"{', '.join(subject[:3])!s} — group them?"))]

    def _board_fit(self, entities: set[str],
                   top: list[DuplicateFinding]) -> list[BoardFitSuggestion]:
        """board_fit_only: same-subject items cluster on one board — evidence
        for routing the NEW item there. Never a merge signal."""
        counts: dict[str, int] = {}
        for _, ctx in self._related(entities):
            for board in ctx.board_ids:
                counts[board] = counts.get(board, 0) + 1
        best = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:1]
        return [BoardFitSuggestion(
            board_id=board, matching_item_count=n,
            detail=f"{n} items about this subject live on {board}")
            for board, n in best if n >= 3]

    # -- single-candidate classification ----------------------------------
    def _match_one(self, ctx: ExistingWorkContext, *, text: str, norm: str,
                   toks: set[str], actions: set[str], entities: set[str],
                   has_repeat: bool) -> tuple[float, DuplicateFinding] | None:
        ex_norm = _normalize(ctx.title)
        ex_toks = _tokens(ex_norm)
        ex_actions = _action_set(ex_toks)
        ex_entities = ex_toks - _ACTIONS
        evidence: list[DuplicateEvidence] = []
        contain = _containment(toks, ex_toks)

        exact = bool(ex_norm) and ex_norm == norm
        if exact:
            evidence.append(DuplicateEvidence(
                kind="exact_title", source="normalized_title",
                detail="the wording matches this item's title exactly"))

        shared_source = False
        if ctx.capture_raw:
            if _normalize(ctx.capture_raw) == norm:
                shared_source = True
                evidence.append(DuplicateEvidence(
                    kind="shared_source", source="capture_raw",
                    detail=("this exact wording was captured before and "
                            f"became '{ctx.title}'")))

        same_action = bool(actions & ex_actions)
        same_entity = _containment(entities, ex_entities) >= 0.5 and bool(
            entities & ex_entities)
        if same_action:
            evidence.append(DuplicateEvidence(
                kind="same_action", source="action_lexicon",
                detail="same action: " + ", ".join(sorted(actions & ex_actions))))
        if same_entity:
            evidence.append(DuplicateEvidence(
                kind="same_entity", source="token_overlap",
                detail="same subject: " + ", ".join(
                    sorted(entities & ex_entities)[:4])))
        if contain >= self.POSSIBLE_CONTAINMENT and not exact:
            evidence.append(DuplicateEvidence(
                kind="lexical_similarity", source="token_containment",
                detail=f"{int(contain * 100)}% of the shorter text's words "
                       "appear in both"))

        # asymmetric containments distinguish expansion (existing ⊂ new)
        # from subtask (new ⊂ existing scope) from symmetric same-work
        ex_in_new = (len(toks & ex_toks) / len(ex_toks)) if ex_toks else 0.0
        much_longer = len(toks) >= len(ex_toks) + 3

        # classification, strongest rule first. Identity beats repeat
        # phrasing: an EXACT re-paste of "Apply to more jobs" is the same
        # statement, not evidence of new progress.
        match_class: MatchClass | None = None
        if exact or shared_source:
            match_class = "exact_same" if exact else "likely_same"
        elif has_repeat and same_action and same_entity:
            match_class = "repeat_occurrence"
            evidence.append(DuplicateEvidence(
                kind="same_outcome", source="repeat_marker",
                detail="phrasing signals repeated progress on this work, "
                       "not a new task"))
        elif ex_in_new >= 0.75 and much_longer and same_entity:
            # the new text contains the existing work and adds real content.
            # Opening WITH the existing work = the same deliverable plus
            # additions (expansion); an umbrella that lists several distinct
            # deliverables = a parent.
            lead = _tokens(" ".join(norm.split()[: len(ex_toks) + 2]))
            opens_with_existing = bool(ex_toks) and (
                len(lead & ex_toks) / len(ex_toks)) >= 0.9
            new_actions = [a for a in actions if a not in ex_actions]
            if not opens_with_existing and len(new_actions) >= 2:
                match_class = "parent_of_existing"
                evidence.append(DuplicateEvidence(
                    kind="same_project", source="asymmetric_containment",
                    detail="the new text describes something bigger that "
                           "contains this existing work"))
            else:
                match_class = "expands_existing"
                evidence.append(DuplicateEvidence(
                    kind="same_outcome", source="asymmetric_containment",
                    detail="the new text covers this item and adds new "
                           "details on top of it"))
        elif same_entity and ctx.kind == "project" and not exact:
            match_class = "subtask_of_existing"
            evidence.append(DuplicateEvidence(
                kind="same_project", source="project_context",
                detail=f"'{ctx.title}' is a project this could be one "
                       "step of"))
        elif contain >= self.LIKELY_CONTAINMENT and len(toks & ex_toks) >= 3:
            match_class = "likely_same"
        elif same_entity and (contain >= self.POSSIBLE_CONTAINMENT
                              or len(toks & ex_toks) >= 3
                              or same_action):
            # entity overlap is REQUIRED: "apply to jobs" must never flag
            # "apply for passport" just because the action matches. Beyond
            # that: enough shared stems, OR the same (synonym-canonical)
            # action on the same subject — "schedule the MJ appointment"
            # vs "book MJ appt" — reads as a paraphrase worth surfacing.
            match_class = "possible_same"
        elif same_entity and actions and ex_actions and not same_action:
            match_class = "same_subject_related"
            evidence.append(DuplicateEvidence(
                kind="same_project", source="entity_overlap",
                detail="same subject but a different action — probably "
                       "related work, not the same task"))
        if match_class is None:
            return None
        # description-aware, IDENTICAL inputs to the resolve-time recompute —
        # otherwise selected delta ids could shift positionally and apply
        # the wrong fragment
        deltas = (extract_deltas(text, ctx.title, ctx.description)
                  if match_class in ("expands_existing", "parent_of_existing")
                  else [])
        finding = DuplicateFinding(
            existing_work_item_id=ctx.work_item_id, title=ctx.title,
            canonical_status=ctx.canonical_status, board_ids=ctx.board_ids,
            primary_board_id=ctx.primary_board_id, match_class=match_class,
            evidence=evidence, last_activity_at=ctx.last_activity_at,
            completion_at=ctx.completion_at,
            occurrence_count=ctx.occurrence_count,
            expansion_deltas=deltas,
            suggested_parent_id=(ctx.work_item_id
                                 if match_class == "subtask_of_existing"
                                 else ctx.parent_id),
            suggested_relation=("parent_of"
                                if match_class in ("subtask_of_existing",
                                                   "parent_of_existing")
                                else "related_to"),
            allowed_resolutions=_resolutions(
                match_class, ctx.canonical_status))
        return (contain + (1.0 if exact or shared_source else 0.0), finding)
