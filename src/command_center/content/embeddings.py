"""Local embedders for the semantic tier of the reference resolver.

Two implementations behind one Protocol:
  - OllamaEmbedder: real local vectors via Ollama's /api/embeddings (default
    nomic-embed-text). Stays on the box - no cloud, same local-only posture as the
    rest of the system. Raises loudly if the endpoint is unreachable; the resolver
    decides whether to degrade to the lexical tiers.
  - TestEmbedder: deterministic, offline, dependency-free. Hashes tokens into a
    fixed bag-of-words vector so overlapping text is close. CI uses this so the
    semantic tier is exercised without a running model.

Cosine is pure Python (vectors are short and few) - no numpy dependency.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Protocol, runtime_checkable

import httpx

_TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@runtime_checkable
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbedder:
    """Real embeddings from a local Ollama. base_url defaults to OLLAMA_API_BASE
    (then localhost). One POST per text - fine for the small reference index."""

    def __init__(self, base_url: str | None = None, model: str = "nomic-embed-text",
                 timeout: int = 30):
        self.base_url = (base_url or os.environ.get("OLLAMA_API_BASE")
                         or "http://localhost:11434").rstrip("/")
        self.model = model
        self.timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            r = httpx.post(f"{self.base_url}/api/embeddings",
                           json={"model": self.model, "prompt": t},
                           timeout=self.timeout)
            r.raise_for_status()
            out.append([float(x) for x in r.json()["embedding"]])
        return out


class HashEmbedder:
    """Deterministic offline embedder. A token-frequency vector hashed into `dim`
    buckets, L2-normalized: shared vocabulary -> high cosine. For CI/tests and as
    a no-model fallback - named without a Test* prefix so pytest won't collect it."""

    def __init__(self, dim: int = 96):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            vec = [0.0] * self.dim
            for tok in tokens(t):
                h = int(hashlib.sha1(tok.encode()).hexdigest(), 16)
                vec[h % self.dim] += 1.0
            norm = math.sqrt(sum(x * x for x in vec))
            out.append([x / norm for x in vec] if norm else vec)
        return out
