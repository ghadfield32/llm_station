"""The content engine's LLM seam: one Protocol, several adapters.

  ContentLLMClient   - the interface every drafter/judge calls
  LiteLLMContentClient - the local default (Ollama via the LiteLLM role); free
  OllamaContentClient  - direct Ollama /api/chat (no LiteLLM in the path)
  DryRunRouterClient   - prices a paid route from policy metadata and REFUSES to
                         call it; the only way to exercise a paid policy here
  TestContentClient    - deterministic, offline; for tests

Why a seam: routing is local-first (docs/MASTER.md). Ollama stays the default;
LiteLLM is just the local adapter; paid external routes (GLM/Kimi) stay opt-in
escalation behind the budget + redaction gates below. There is intentionally NO
live external client in this layer - a live paid call is operator-gated (the
cheap-external smoke test), so `make_client` hands a paid policy to the dry-run
estimator, never to the network.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import httpx

from .llm import chat, _THINK


@dataclass
class ContentLLMRequest:
    system: str
    user: str
    model: str = "chat"                  # local role (e.g. "chat") or external model id
    temperature: float = 0.5
    max_tokens: int = 1200


@dataclass
class ContentLLMResponse:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    dry_run: bool = False
    notes: list[str] = field(default_factory=list)


@runtime_checkable
class ContentLLMClient(Protocol):
    def complete(self, request: ContentLLMRequest) -> ContentLLMResponse: ...


# ── gates (pure functions; reusable when a live paid client is added) ─────────
def estimate_tokens(text: str) -> int:
    """~4 chars/token heuristic; good enough for a budget estimate."""
    return max(1, len(text) // 4)


def price_for(model: str, prices) -> object | None:
    return next((p for p in prices if p.model == model), None)


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int,
                      prices) -> float:
    p = price_for(model, prices)
    if p is None:
        return 0.0
    return (prompt_tokens / 1e6) * p.input_usd_per_mtok + \
           (completion_tokens / 1e6) * p.output_usd_per_mtok


# Obvious secrets/PII to strip before ANY external egress. Conservative on
# purpose: better to over-redact a paid prompt than leak a key.
_REDACTIONS: list[tuple[str, re.Pattern]] = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("api_key", re.compile(r"\b(?:sk|pk|ghp|gho|xoxb|AKIA)[-_A-Za-z0-9]{8,}\b")),
    ("bearer", re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{8,}")),
    ("urn", re.compile(r"urn:li:[A-Za-z0-9:_-]+")),
]


def redact(text: str) -> tuple[str, list[str]]:
    """Return (redacted_text, kinds_found). Used to satisfy require_redaction
    before a paid route. Surfaces what it scrubbed - never silent."""
    found: list[str] = []
    out = text
    for kind, rx in _REDACTIONS:
        if rx.search(out):
            found.append(kind)
            out = rx.sub(f"[REDACTED:{kind}]", out)
    return out, found


def within_budget(cost_usd: float, max_request_usd: float) -> bool:
    return max_request_usd <= 0 or cost_usd <= max_request_usd


# ── adapters ──────────────────────────────────────────────────────────────
class LiteLLMContentClient:
    """Local default - drafts/judges through the LiteLLM role (Ollama-backed).
    Free (cost 0) and never leaves the box."""

    def __init__(self, base_url: str, key: str):
        self.base_url, self.key = base_url, key

    def complete(self, request: ContentLLMRequest) -> ContentLLMResponse:
        text = chat(self.base_url, self.key, request.model, request.system,
                    request.user, temperature=request.temperature,
                    max_tokens=request.max_tokens)
        return ContentLLMResponse(text=text, model=request.model, cost_usd=0.0)


class OllamaContentClient:
    """Direct Ollama /api/chat - same local model, no LiteLLM in the path."""

    def __init__(self, base_url: str | None = None, timeout: int = 240):
        self.base_url = (base_url or os.environ.get("OLLAMA_API_BASE")
                         or "http://localhost:11434").rstrip("/")
        self.timeout = timeout

    def complete(self, request: ContentLLMRequest) -> ContentLLMResponse:
        r = httpx.post(f"{self.base_url}/api/chat",
                       json={"model": request.model, "stream": False,
                             "options": {"temperature": request.temperature},
                             "messages": [{"role": "system", "content": request.system},
                                          {"role": "user", "content": request.user}]},
                       timeout=self.timeout)
        r.raise_for_status()
        text = _THINK.sub("", r.json()["message"]["content"]).strip()
        return ContentLLMResponse(text=text, model=request.model, cost_usd=0.0)


class DryRunRouterClient:
    """Prices a paid route from policy + price metadata and REFUSES to call it.
    Returns an empty completion with the cost estimate and a budget verdict, so a
    human can see what a paid escalation would cost before any egress."""

    def __init__(self, policy, prices):
        self.policy, self.prices = policy, prices

    def complete(self, request: ContentLLMRequest) -> ContentLLMResponse:
        pt = estimate_tokens(request.system + request.user)
        ct = request.max_tokens
        cost = estimate_cost_usd(request.model, pt, ct, self.prices)
        notes = [f"DRY RUN: would route to {request.model} via policy "
                 f"'{self.policy.name}' (no live call made)"]
        if not within_budget(cost, self.policy.max_request_usd):
            notes.append(f"OVER BUDGET: est ${cost:.4f} > cap "
                         f"${self.policy.max_request_usd:.4f}")
        if self.policy.require_redaction:
            _, found = redact(request.user)
            notes.append(f"redaction would scrub: {', '.join(found) or 'nothing'}")
        if self.policy.human_approval:
            notes.append("policy requires human approval before any live run")
        return ContentLLMResponse(text="", model=request.model, prompt_tokens=pt,
                                  completion_tokens=ct, cost_usd=round(cost, 6),
                                  dry_run=True, notes=notes)


class TestContentClient:
    """Deterministic offline client for tests. Records calls; returns a fixed
    reply (default a valid HOOK:/BODY: draft)."""

    __test__ = False                     # not a pytest test class, despite the name

    def __init__(self, reply: str = "HOOK: A tight hook.\nBODY: A short body. Worth it?"):
        self.reply = reply
        self.calls: list[ContentLLMRequest] = []

    def complete(self, request: ContentLLMRequest) -> ContentLLMResponse:
        self.calls.append(request)
        return ContentLLMResponse(text=self.reply, model=request.model)


# ── factory ─────────────────────────────────────────────────────────────
def select_policy(routing, name: str | None = None):
    """Return the named policy, or the routing default. Raises if unknown."""
    target = name or routing.default_policy
    for p in routing.policies:
        if p.name == target:
            return p
    raise SystemExit(f"unknown content_llm policy {target!r} "
                     f"(have: {', '.join(p.name for p in routing.policies) or '<none>'})")


def make_client(policy, *, base_url: str, key: str, prices) -> ContentLLMClient:
    """Build the client for a policy. Local policies get the LiteLLM client; paid
    policies get the dry-run estimator (a live external client is intentionally
    not built here - that path is operator-gated)."""
    if not policy.allow_paid:
        return LiteLLMContentClient(base_url, key)
    return DryRunRouterClient(policy, prices)
