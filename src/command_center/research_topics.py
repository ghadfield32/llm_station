"""Human research topics and provider-specific query compilation.

The cockpit stores readable topics (for example ``Bayesian forecasting``).
Provider syntax is an adapter concern and must never leak into the editable
board contract.  These helpers are deliberately pure so the UI projection and
both Growth OS source adapters agree about topic identity.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

_SPACE_RE = re.compile(r"\s+")
_TERM_RE = re.compile(r"[A-Za-z0-9]+(?:[.+#-][A-Za-z0-9]+)*")
_STOP_WORDS = frozenset({"a", "an", "and", "for", "of", "the", "to", "with"})


def normalize_research_topic(value: str) -> str:
    """Return one display-safe topic, rejecting provider query fragments."""
    topic = _SPACE_RE.sub(" ", value.strip().strip(","))
    if not topic:
        raise ValueError("research topics cannot be empty")
    if len(topic) > 100:
        raise ValueError("research topics must be at most 100 characters")
    if re.search(r"(?:^|\s)(?:all|cat|ti|au|abs|co|jr|rn|id|topic|stars|pushed|language):", topic, re.I):
        raise ValueError(
            "enter a readable topic, not arXiv/GitHub query syntax")
    if re.search(r"\b(?:AND|OR|ANDNOT)\b", topic):
        raise ValueError(
            "enter a readable topic; Boolean provider operators are added automatically")
    return topic


def normalize_research_topics(values: Iterable[str]) -> list[str]:
    """Normalize and case-insensitively deduplicate topics in display order."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        topic = normalize_research_topic(str(value))
        key = topic.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(topic)
    return out


def topic_terms(topic: str) -> list[str]:
    terms = [term.casefold() for term in _TERM_RE.findall(topic)]
    informative = [term for term in terms if term not in _STOP_WORDS]
    return informative or terms


def matching_research_topics(text: str, topics: Iterable[str]) -> list[str]:
    """Classify source text using all informative words in each topic."""
    words = {term.casefold() for term in _TERM_RE.findall(text)}
    word_forms = words | {
        word[:-1] for word in words if word.endswith("s") and len(word) > 3
    }
    return [
        topic for topic in normalize_research_topics(topics)
        if all(
            term in word_forms or (
                term.endswith("s") and len(term) > 3 and term[:-1] in word_forms
            )
            for term in topic_terms(topic)
        )
    ]


def arxiv_query_for_topic(topic: str) -> str:
    """Compile readable words into the arXiv API's ``all:`` query grammar."""
    terms = topic_terms(normalize_research_topic(topic))
    if not terms:
        raise ValueError("research topic has no searchable words")
    return " AND ".join(f"all:{term}" for term in terms)


def github_query_for_topic(topic: str) -> str:
    """Compile a readable topic into GitHub repository search syntax."""
    terms = topic_terms(normalize_research_topic(topic))
    if not terms:
        raise ValueError("research topic has no searchable words")
    return f"{' '.join(terms)} in:name,description,readme"
