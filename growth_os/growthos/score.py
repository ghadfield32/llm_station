"""Relevance scoring. Two interchangeable scorers, selected in
config/sources.yaml (`scoring.method`):

- keyword   : weighted term matching (no external calls). The original.
- embedding : semantic similarity via a local Ollama embedding model. The
              interest profile becomes a weighted mean of its terms'
              embeddings; items score by cosine similarity, so relevant
              items rank well even when they don't contain the exact terms
              (the failure mode of short headlines). Keyword penalties and
              the star bonus still apply on top.

`make_scorer` falls back to keyword scoring (with a warning) when Ollama is
unreachable, so the pipeline never hard-fails on a missing GPU box.
Selection stays top-N per source — no arbitrary global cutoff.
"""
from __future__ import annotations
import logging
import math

import httpx

from .config import Config, InterestProfile
from .models import CuratedItem

log = logging.getLogger("growthos.score")


# ---------------------------------------------------------------- keyword --

def score_item(item: CuratedItem, profile: InterestProfile) -> float:
    blob = item.text_blob()
    s = 0.0
    for term, w in profile.weights.items():
        if term.lower() in blob:
            s += w
    s += _penalties(blob, profile)
    s += _star_bonus(item)
    return round(s, 3)


def _penalties(blob: str, profile: InterestProfile) -> float:
    return sum(p for term, p in profile.penalties.items() if term.lower() in blob)


def _star_bonus(item: CuratedItem) -> float:
    stars = item.extra.get("stars")
    if isinstance(stars, (int, float)) and stars > 0:
        return min(stars / 1000.0, 2.0)
    return 0.0


class KeywordScorer:
    def __init__(self, profile: InterestProfile):
        self.profile = profile

    def __call__(self, items: list[CuratedItem]) -> None:
        for it in items:
            it.score = score_item(it, self.profile)


# -------------------------------------------------------------- embedding --

class EmbeddingScorer:
    """Scores items by cosine similarity to a profile vector built from the
    weighted interest terms. Construction embeds the profile eagerly so a
    dead Ollama fails fast (and make_scorer can fall back)."""

    def __init__(self, base_url: str, model: str, profile: InterestProfile,
                 scale: float = 10.0, batch: int = 32):
        self.base = base_url.rstrip("/")
        self.model = model
        self.profile = profile
        self.scale = scale
        self.batch = batch
        self._client = httpx.Client(timeout=120)
        terms = list(profile.weights.items())
        vecs = self._embed([t for t, _ in terms])
        dim = len(vecs[0])
        acc = [0.0] * dim
        total = sum(w for _, w in terms) or 1.0
        for (term, w), v in zip(terms, vecs):
            for i, x in enumerate(v):
                acc[i] += w * x
        self.profile_vec = [x / total for x in acc]
        self._pnorm = math.sqrt(sum(x * x for x in self.profile_vec)) or 1.0

    def _embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            r = self._client.post(f"{self.base}/api/embed",
                                  json={"model": self.model,
                                        "input": texts[i:i + self.batch]})
            r.raise_for_status()
            out += r.json()["embeddings"]
        return out

    def _cosine(self, v: list[float]) -> float:
        dot = sum(a * b for a, b in zip(v, self.profile_vec))
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return dot / (n * self._pnorm)

    def __call__(self, items: list[CuratedItem]) -> None:
        if not items:
            return
        vecs = self._embed([it.text_blob()[:2000] for it in items])
        for it, v in zip(items, vecs):
            sim = max(self._cosine(v), 0.0)
            it.score = round(sim * self.scale
                             + _penalties(it.text_blob(), self.profile)
                             + _star_bonus(it), 3)


def make_scorer(cfg: Config, ollama_base_url: str):
    """Build the configured scorer; degrade gracefully to keyword scoring."""
    if cfg.scoring.method == "embedding":
        if not ollama_base_url:
            log.warning("scoring.method=embedding but OLLAMA_BASE_URL is empty; "
                        "falling back to keyword scoring")
        else:
            try:
                s = EmbeddingScorer(ollama_base_url, cfg.scoring.embed_model,
                                    cfg.interest_profile, cfg.scoring.embed_scale)
                log.info("scoring: embedding (%s @ %s)", cfg.scoring.embed_model,
                         ollama_base_url)
                return s
            except Exception as exc:
                log.warning("embedding scorer unavailable (%s); falling back to "
                            "keyword scoring", exc)
    return KeywordScorer(cfg.interest_profile)


# --------------------------------------------------------------- ranking --

def rank_and_trim(items: list[CuratedItem], scorer, top_n: int,
                  include_zero: bool = False) -> list[CuratedItem]:
    """Score, sort, and cap. include_zero=True keeps zero-scored items and only
    drops penalized ones — right for hand-picked feeds (signals), where the feed
    list itself already expresses relevance. Broad searches (papers/repos) keep
    the positive-score gate."""
    scorer(items)
    items.sort(key=lambda x: x.score, reverse=True)
    floor = 0 if include_zero else 1e-9
    relevant = [i for i in items if i.score >= floor]
    return relevant[:top_n] if top_n else relevant
