"""The retrieval cascade. Given the index and a query, score every record across
tiers and return them ranked. Tiers, cheapest/strictest first:

  1 exact id          query == record id                       (1.00)
  2 alias             normalized query == a title/alias        (0.97)
  3 normalized        normalized query is a substring          (0.90)
  4 fuzzy (RapidFuzz) misspelling-tolerant title/alias match   (~0.60-0.92)
  5 BM25 keyword      term-frequency relevance over the blob   (~0.40-0.75)
  6 semantic (embed)  local-embedding cosine, if vectors exist (~0.45-0.90)

Each record keeps the score of its STRONGEST tier (so an exact id always beats a
fuzzy near-miss), and the winning tier is reported. The optional LLM-rerank
(step 7 in the design) is a documented seam, off by default - it would reorder
the top-k here. The resolver layers disambiguation (step 8) on top.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from .embeddings import tokens, cosine
from .reference_index import IndexRecord

_NORM = re.compile(r"[^a-z0-9]+")


def normalize(s: str) -> str:
    return _NORM.sub(" ", s.lower()).strip()


@dataclass
class Match:
    record: IndexRecord
    score: float
    tier: str


@dataclass
class SearchResult:
    query: str
    matches: list[Match]              # ranked, best first
    notes: list[str]                  # diagnostics (e.g. semantic tier skipped)

    @property
    def best(self) -> Match | None:
        return self.matches[0] if self.matches else None


class BM25:
    """Compact BM25 over pre-tokenized docs (no external dependency)."""

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.N = len(docs)
        self.avgdl = (sum(len(d) for d in docs) / self.N) if self.N else 0.0
        df: dict[str, int] = {}
        for d in docs:
            for t in set(d):
                df[t] = df.get(t, 0) + 1
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def scores(self, q: list[str]) -> list[float]:
        out = [0.0] * self.N
        qset = set(q)
        for i, d in enumerate(self.docs):
            if not d:
                continue
            counts: dict[str, int] = {}
            for t in d:
                counts[t] = counts.get(t, 0) + 1
            s = 0.0
            for t in qset:
                f = counts.get(t, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * len(d) / (self.avgdl or 1))
                s += self.idf.get(t, 0.0) * (f * (self.k1 + 1)) / denom
            out[i] = s
        return out


def _fuzzy(nq: str, rec: IndexRecord) -> float:
    cands = [normalize(rec.title), *(normalize(a) for a in rec.aliases)]
    return max((max(fuzz.token_set_ratio(nq, c), fuzz.partial_ratio(nq, c))
                for c in cands if c), default=0.0)


def search(index: list[IndexRecord], query: str, *, fuzzy_threshold: int = 72,
           embedder=None, embed_enabled: bool = True) -> SearchResult:
    notes: list[str] = []
    nq = normalize(query)
    qtok = tokens(query)

    # tier 5: BM25 over the full blob (term-frequency relevance)
    bm = BM25([tokens(r.blob()) for r in index])
    bm_scores = bm.scores(qtok)
    bm_max = max(bm_scores) if bm_scores else 0.0

    # tier 6: semantic cosine (only if vectors exist and an embedder is available)
    qvec = None
    has_vectors = any(r.vector for r in index)
    if embed_enabled and embedder is not None and has_vectors:
        try:
            qvec = embedder.embed([query])[0]
        except Exception as e:                 # Ollama down etc. -> degrade, but say so
            notes.append(f"semantic tier skipped: {type(e).__name__}: {e}")

    matches: list[Match] = []
    for i, rec in enumerate(index):
        best, tier = 0.0, ""

        def consider(score: float, label: str):
            nonlocal best, tier
            if score > best:
                best, tier = score, label

        if query.strip().lower() == rec.id.lower():
            consider(1.0, "exact_id")
        if nq and (nq == normalize(rec.title)
                   or any(nq == normalize(a) for a in rec.aliases)):
            consider(0.97, "alias")
        if nq and (nq in normalize(rec.title)
                   or any(nq in normalize(a) or (normalize(a) and normalize(a) in nq)
                          for a in rec.aliases)):
            consider(0.90, "normalized")
        ratio = _fuzzy(nq, rec)
        if ratio >= fuzzy_threshold:
            consider(0.60 + 0.32 * (ratio / 100.0), "fuzzy")
        if bm_max > 0 and bm_scores[i] > 0:
            consider(0.40 + 0.35 * (bm_scores[i] / bm_max), "keyword")
        if qvec is not None and rec.vector:
            consider(0.45 + 0.45 * max(0.0, cosine(qvec, rec.vector)), "semantic")

        if best > 0:
            matches.append(Match(rec, round(best, 4), tier))

    matches.sort(key=lambda m: m.score, reverse=True)
    return SearchResult(query=query, matches=matches, notes=notes)
