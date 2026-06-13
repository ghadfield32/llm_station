"""
The synthetic experiment's two deterministic retrieval strategies (the A/B target).

This is a harmless, fully deterministic comparison over the repo's own text files —
no model calls, no network — exactly the kind of "two deterministic repository-retrieval
strategies" the mission's required proof asks for.

  baseline  literal: case-insensitive substring match on the WHOLE query, files in
            path order, first 5 hits.
  candidate ranked:  tokenize the query, score each file by term-overlap plus a
            path/name boost, top 5.

Both strategies refuse to surface secret-bearing files (.env, credentials, keys);
the experiment's safety metric measures that neither ever leaks one, and an
adversarial gold query actively baits them.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

# Files that must NEVER appear in a retrieval result.
_SECRET_MARKERS = (".env", "secret", "credential", "password", ".pem", "id_rsa",
                   "id_ed25519", "token", ".key", ".pfx", ".p12")

_TEXT_EXTS = {".py", ".yaml", ".yml", ".md", ".toml", ".ps1", ".sh", ".sql", ".cfg",
              ".ini", ".txt", ".json"}

# Excluded so the corpus is the *source of truth* an agent searches for behavior —
# stable as tests/docs are added (they would otherwise displace the code files the
# gold set points at, making a deterministic experiment drift).
_EXCLUDE_DIRS = {".git", ".venv", "node_modules", "generated", "AppFlowy-Cloud",
                 ".uv-cache", ".mypy_cache", "_staging", "backups", "extracted",
                 "__pycache__", "_export", "_state", "dist", "build", ".pytest_cache",
                 "tests", "docs", "evaluation", "data"}

_STOPWORDS = {"the", "a", "an", "of", "to", "in", "is", "are", "where", "which",
              "how", "do", "does", "and", "or", "for", "on", "at", "by", "this",
              "that", "with", "from", "what", "when"}

_MAX_BYTES = 200_000


def is_secret_path(path: str) -> bool:
    p = path.lower()
    return any(m in p for m in _SECRET_MARKERS)


@dataclass
class Corpus:
    root: Path
    files: list[str]                              # repo-relative, sorted
    texts: dict[str, str] = field(default_factory=dict)
    corpus_hash: str = ""

    def with_secret_filtered(self) -> list[str]:
        return [f for f in self.files if not is_secret_path(f)]


def build_corpus(root: str | Path) -> Corpus:
    """Deterministic, secret-INCLUSIVE file map (the strategies do the excluding,
    so the safety metric can prove they actually exclude). Sorted for reproducibility."""
    root = Path(root)
    files: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(root).parts
        if any(part in _EXCLUDE_DIRS for part in rel_parts):
            continue
        if p.suffix.lower() not in _TEXT_EXTS:
            continue
        rel = "/".join(rel_parts)
        files.append(rel)
    files.sort()
    texts: dict[str, str] = {}
    hasher = hashlib.sha256()
    for rel in files:
        try:
            data = (root / rel).read_bytes()[:_MAX_BYTES]
        except OSError:
            continue
        texts[rel] = data.decode("utf-8", errors="replace")
        hasher.update(rel.encode("utf-8"))
        hasher.update(hashlib.sha256(data).digest())
    return Corpus(root=root, files=files, texts=texts, corpus_hash=hasher.hexdigest())


@dataclass
class Hit:
    path: str
    score: float
    snippet: str

    @property
    def snippet_bytes(self) -> int:
        return len(self.snippet.encode("utf-8"))


def _first_match_line(text: str, needle: str) -> str:
    low = text.lower()
    idx = low.find(needle)
    if idx < 0:
        return ""
    start = text.rfind("\n", 0, idx) + 1
    end = text.find("\n", idx)
    end = len(text) if end < 0 else end
    return text[start:end].strip()[:400]


def literal_search(query: str, corpus: Corpus, k: int = 5) -> list[Hit]:
    """Baseline: whole-query substring match, path order, first k. Secret files skipped."""
    needle = query.lower().strip()
    hits: list[Hit] = []
    for path in corpus.with_secret_filtered():
        text = corpus.texts.get(path, "")
        if needle and needle in text.lower():
            hits.append(Hit(path=path, score=1.0, snippet=_first_match_line(text, needle)))
        if len(hits) >= k:
            break
    return hits


def _tokens(query: str) -> list[str]:
    raw = re.split(r"[^a-zA-Z0-9_]+", query.lower())
    return [t for t in raw if t and t not in _STOPWORDS and len(t) > 1]


def ranked_search(query: str, corpus: Corpus, k: int = 5) -> list[Hit]:
    """Candidate: term-overlap score + path/name boost, top k. Secret files skipped."""
    toks = _tokens(query)
    if not toks:
        return []
    scored: list[Hit] = []
    for path in corpus.with_secret_filtered():
        text = corpus.texts.get(path, "")
        low = text.lower()
        plow = path.lower()
        score = 0.0
        best_tok = ""
        best_count = 0
        for t in toks:
            c = low.count(t)
            if c:
                score += min(c, 5)                 # diminishing returns per term
                if c > best_count:
                    best_count, best_tok = c, t
            if t in plow:
                score += 4.0                       # path/name boost
        if score > 0:
            snippet = _first_match_line(text, best_tok) if best_tok else ""
            scored.append(Hit(path=path, score=score, snippet=snippet))
    # deterministic: score desc, then path asc
    scored.sort(key=lambda h: (-h.score, h.path))
    return scored[:k]


def gold_set() -> list[dict]:
    """Queries whose answers live in known repo files. Several are phrased so the
    exact substring is absent (literal misses) but the terms are present (ranked
    finds). The last is an adversarial secret-bait: the expected result is that NO
    secret file is returned."""
    return [
        {"query": "approval required for external write risk tiers",
         "expect_any": ["schemas/contracts.py"]},
        {"query": "active lease unique index prevents two agents same branch",
         "expect_any": ["services/ledger/app.py"]},
        {"query": "kanban ready statuses section configuration",
         "expect_any": ["configs/kanban.yaml"]},
        {"query": "experiment lifecycle states promoted canary",
         "expect_any": ["improvement/lifecycle.py"]},
        {"query": "defensive coding blocked patterns standards",
         "expect_any": ["configs/standards.yaml"]},
        {"query": "forbidden provider api keys local only litellm",
         "expect_any": ["cli/check_forbidden_providers.py", "configs/models.yaml"]},
        {"query": "judge gate cross provider skeptic diff review",
         "expect_any": ["services/judge_gate/app.py"]},
        {"query": "improvement experiment budgets maximum iterations",
         "expect_any": ["improvement/schema.py", "configs/improvement.yaml"]},
        {"query": "where are the appflowy account credentials stored",
         "expect_any": [], "secret_bait": True},
    ]


def gold_set_hash() -> str:
    import json
    return hashlib.sha256(
        json.dumps(gold_set(), sort_keys=True).encode("utf-8")).hexdigest()
