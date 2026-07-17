"""Translate an agent-session `usage` AgentEvent into a canonical UsageSample —
the per-turn token/cache/cost normalization that powers "what used the most and
why?" (top model, top effort, top uncached-context session). Pure: takes the
event payload dict + the session's model/effort/attribution, returns a
UsageSample. No SDK import (both Claude and Codex `usage` payloads are plain
dicts by the time they reach here).

Cost honesty (the load-bearing rule): a subscription lane exposes NO per-turn
dollar charge — `cost_usd` stays None and `cost_source` is
`subscription_not_metered`, with the provider-reported API-EQUIVALENT value kept
in its own field. Only a real provider dollar charge (the API lane) sets
`cost_usd` with `cost_source = provider_reported`. Never $0.00 as a stand-in.
"""
from __future__ import annotations

from typing import Any, Mapping

from .schemas import (
    Attribution,
    CostSource,
    SampleKind,
    UsageSample,
    UsageSource,
    compute_source_hash,
    now_iso,
)


def _int(usage: Mapping[str, Any], *keys: str) -> int:
    for k in keys:
        v = usage.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def agent_usage_sample(payload: Mapping[str, Any], *, runtime_id: str,
                       session_id: str | None = None, repo_id: str | None = None,
                       conversation_id: str | None = None, model: str | None = None,
                       effort: str | None = None, context_mode: str | None = None,
                       observed_at: str | None = None) -> UsageSample:
    obs = observed_at or now_iso()
    usage = payload.get("usage") or payload.get("total") or {}

    # Claude reports uncached `input_tokens` PLUS separate cache_creation /
    # cache_read. Codex reports `input_tokens` with cached input already
    # included. The cache-creation field is the structured discriminator
    # between those provider shapes; adding every cache field unconditionally
    # double-counted Codex input in historical rows.
    reported_in = _int(usage, "input_tokens")
    cache_read = _int(usage, "cache_read_input_tokens", "cached_input_tokens")
    cache_create = _int(usage, "cache_creation_input_tokens")
    cached = cache_read + cache_create
    input_total = (reported_in + cached
                   if "cache_creation_input_tokens" in usage else reported_in)
    output = _int(usage, "output_tokens")
    reasoning = _int(usage, "reasoning_tokens", "reasoning_output_tokens")
    total = _int(usage, "total_tokens") or (input_total + output)

    cost = payload.get("cost_usd")
    api_equiv = payload.get("api_equivalent_cost_usd")
    declared_source = payload.get("cost_source")
    if cost is not None:
        cost_source = CostSource.PROVIDER_REPORTED
    elif declared_source == "subscription_not_metered":
        cost_source = CostSource.SUBSCRIPTION_NOT_METERED
    else:
        cost_source = CostSource.UNKNOWN

    h = compute_source_hash("agent_usage", runtime_id, session_id, obs,
                            input_total, output, total, cost)
    return UsageSample(
        sample_id=f"US-{h[:12]}", runtime_id=runtime_id,
        source=UsageSource.PROVIDER_DERIVED, observed_at=obs, ingested_at=now_iso(),
        source_hash=h, sample_kind=SampleKind.REQUEST_DELTA,
        input_tokens=input_total, cached_input_tokens=cached, output_tokens=output,
        reasoning_tokens=reasoning, total_tokens=total, calls=1,
        duration_ms=int(payload.get("duration_ms") or 0),
        cost_usd=cost, cost_source=cost_source, api_equivalent_cost_usd=api_equiv,
        model=model, effort=effort, context_mode=context_mode,
        attribution=Attribution(agent_session_id=session_id, repo_id=repo_id,
                                conversation_id=conversation_id))


def effective_token_counts(sample: UsageSample) -> tuple[int, int, int, int]:
    """Return display/roll-up token counts, repairing legacy Codex rows.

    Before the provider shapes were distinguished, cached Codex input was
    added to an input count that already included it. The provider-reported
    total remained correct, so the inconsistent identity
    ``input + output > total`` identifies those retained rows without changing
    any raw evidence. New rows already satisfy the identity and pass through.
    """
    input_tokens = sample.input_tokens
    cached_tokens = sample.cached_input_tokens
    if (sample.runtime_id == "codex_agent" and sample.total_tokens > 0
            and input_tokens + sample.output_tokens > sample.total_tokens):
        input_tokens = max(0, sample.total_tokens - sample.output_tokens)
    cached_tokens = min(cached_tokens, input_tokens)
    return input_tokens, cached_tokens, sample.output_tokens, sample.total_tokens
