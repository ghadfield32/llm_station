"""RoutingCalibrator — derive evidence-backed keyword→board rules from the
router-correction log, so the router can suggest a board grounded in what the
human ACTUALLY chose, instead of always asking.

Discipline (time-ordered learning):
  * PAST corrections only — `derive(as_of=...)` uses corrections dated strictly
    before the cut, so a rule is never learned from a correction it would then be
    applied to (no leakage; the standard temporal split).
  * NO invented thresholds — a keyword's board is its data-driven **majority**
    (ties are ambiguous and excluded, never guessed); `min_support` is an
    explicit, surfaced dial (default 1 = "has at least one real observation").
  * Evidence attached — every DerivedRule carries its support count AND the full
    per-board distribution, so the strength of each rule is visible.
  * Learning, not serving — derived rules become the router's board SUGGESTIONS,
    which the human still confirms; every override feeds back as new telemetry.

Deterministic + hermetic: pure functions of the correction list, no I/O.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Sequence

from pydantic import BaseModel, Field

from .router import BoardRule, _normalize
from .schemas import RoutingCorrection

# Standard English FUNCTION words (articles/prepositions/conjunctions/pronouns/
# auxiliaries) — they co-occur with every board and carry no routing signal. A
# fixed, well-known closed-class set (all present in NLTK's English stopwords);
# deliberately NOT a curated content/action-word filter, so it never suppresses a
# real routing signal (e.g. "post", "research", "cv" all survive).
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "to", "of", "and", "or", "for", "in", "on", "at", "by",
    "with", "from", "my", "is", "it", "this", "that", "be", "as", "are", "was",
    "we", "i", "you", "do", "did", "up", "out", "if", "not", "no", "so", "can",
    "could", "should", "would", "will", "have", "has", "had", "them", "they",
    "there", "then", "than", "when", "what", "which", "who", "how", "all",
    "any", "some", "but", "into", "about", "just", "like"})

# Minimum keyword length: normalization turns "e.g." into the tokens "e"/"g" —
# one- and two-letter fragments are punctuation shrapnel, not routing signal.
# ("cv" is the known real two-letter term; it is explicitly allowed.)
_MIN_TOKEN_LEN = 3
_SHORT_ALLOWLIST: frozenset[str] = frozenset({"cv", "ai", "ml"})


def _tokens(title: str) -> set[str]:
    # Unique tokens per correction: a word repeated in one title counts once, so
    # its support = number of distinct corrections, not word frequency.
    return {t for t in _normalize(title).split()
            if t and t not in _STOPWORDS
            and (len(t) >= _MIN_TOKEN_LEN or t in _SHORT_ALLOWLIST)}


class DerivedRule(BaseModel):
    """A keyword→board association LEARNED from the correction log, with its
    evidence: how many past corrections chose that board for this keyword
    (support), how many chose ANY board (total), and the full per-board
    distribution. Not applied blindly — the router turns it into a
    human-confirmable suggestion."""
    keyword: str
    board_id: str
    support: int
    total: int
    distribution: dict[str, int] = Field(default_factory=dict)


class RoutingCalibrator:
    def __init__(self, corrections: Sequence[RoutingCorrection]) -> None:
        self._corrections = list(corrections)

    def derive(self, *, as_of: str | None = None) -> list[DerivedRule]:
        """Learn keyword→board rules from PAST corrections only (``at < as_of``
        when given — an ISO-8601 string compared lexicographically, which is
        chronological because every ``at`` is stamped uniform UTC). Each keyword
        is assigned its PLURALITY board (the most-chosen; requiring a strict >50%
        majority would itself be an invented threshold); ties for the top are
        excluded (ambiguous, not guessed). Sorted strongest-evidence first."""
        counts: dict[str, Counter] = defaultdict(Counter)
        for c in self._corrections:
            if c.chosen_board_id is None:          # no board chosen -> no signal
                continue
            if as_of is not None and not c.at < as_of:   # temporal cut (past only)
                continue
            for tok in _tokens(c.title):
                counts[tok][c.chosen_board_id] += 1

        rules: list[DerivedRule] = []
        for tok, dist in counts.items():
            ranked = dist.most_common()
            best_board, best = ranked[0]
            if len(ranked) > 1 and ranked[1][1] == best:   # tie -> ambiguous, skip
                continue
            rules.append(DerivedRule(
                keyword=tok, board_id=best_board, support=best,
                total=sum(dist.values()), distribution=dict(dist)))
        rules.sort(key=lambda r: (-r.support, r.keyword))
        return rules

    def board_rules(self, domain_of: Callable[[str], str | None], *,
                    min_support: int = 1, as_of: str | None = None,
                    rules: Sequence[DerivedRule] | None = None) -> list[BoardRule]:
        """Turn derived rules into router BoardRules (one per board), keeping only
        keywords with support >= ``min_support`` and a RESOLVABLE domain
        (``domain_of(board_id)``; a board with no known domain is skipped, never
        fabricated). ``min_support`` is the honest dial: 1 = any real evidence.
        Pass ``rules`` to reuse an already-computed ``derive()`` (avoid a second
        pass); otherwise it derives with ``as_of``."""
        by_board: dict[str, tuple[str, list[str]]] = {}
        for rule in (rules if rules is not None else self.derive(as_of=as_of)):
            if rule.support < min_support:
                continue
            domain = domain_of(rule.board_id)
            if domain is None:                     # no real domain -> do not invent
                continue
            by_board.setdefault(rule.board_id, (domain, []))[1].append(rule.keyword)
        return [BoardRule(board_id=board, domain_id=dom, keywords=tuple(kws))
                for board, (dom, kws) in by_board.items()]
