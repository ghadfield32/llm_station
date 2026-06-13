"""Typed contracts for everything the Curator handles (Pydantic v2)."""
from __future__ import annotations
from datetime import date, datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, HttpUrl

Kind = Literal["paper", "repo", "signal"]


class CuratedItem(BaseModel):
    """One normalized item, regardless of source. The Curator only ever
    moves CuratedItems around, so adding a new source = producing these."""
    kind: Kind
    external_id: str                      # stable dedupe key (arxiv id / repo url / link)
    title: str
    url: str
    summary: str = ""
    authors: str = ""
    topics: list[str] = Field(default_factory=list)
    source: str = ""                      # which feed/query produced it
    published: Optional[date] = None
    extra: dict = Field(default_factory=dict)   # source-specific (stars, language, ...)
    score: float = 0.0                    # filled by score.py

    def text_blob(self) -> str:
        return " ".join([self.title, self.summary, " ".join(self.topics)]).lower()


class Lesson(BaseModel):
    """A self-improvement lesson on a spaced-repetition schedule."""
    lesson: str
    detail: str = ""
    domain: str = "Life"
    source: str = ""
    status: str = "Capture"
    confidence: int = 3
    next_review: Optional[date] = None
    interval: int = 1
    created: date = Field(default_factory=date.today)
