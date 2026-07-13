"""Pure cost estimation + provider ranking for the frontier-router backup lane.

No I/O, no network, no keys — deterministic math over public price metadata. Every router run
must preflight a cost ESTIMATE through here before any call; actual provider-reported usage is
recorded SEPARATELY and never overwrites the estimate (no fabricated "actual" cost). The
cheapest provider is computed per workload, never hardcoded — prices change.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


def estimate_cost_usd(
    input_tokens: int,
    output_tokens: int,
    input_usd_per_mtok: float,
    output_usd_per_mtok: float,
    cached_input_tokens: int = 0,
    cached_input_usd_per_mtok: float | None = None,
) -> float:
    """Estimated USD for one request. Cached input tokens are billed at the cached rate when the
    provider/model supplies one, else at the normal input rate."""
    if min(input_tokens, output_tokens, cached_input_tokens) < 0:
        raise ValueError("token counts must be non-negative")
    if cached_input_tokens > input_tokens:
        raise ValueError("cached_input_tokens cannot exceed input_tokens")
    uncached_input = input_tokens - cached_input_tokens
    input_cost = (uncached_input / 1_000_000) * input_usd_per_mtok
    cached_rate = (cached_input_usd_per_mtok
                   if cached_input_usd_per_mtok is not None else input_usd_per_mtok)
    input_cost += (cached_input_tokens / 1_000_000) * cached_rate
    output_cost = (output_tokens / 1_000_000) * output_usd_per_mtok
    return round(input_cost + output_cost, 6)


@dataclass(frozen=True)
class CostRecord:
    """The preflight cost record emitted before any call. `actual_*` stay None until the
    provider returns real usage — the estimate is never overwritten."""
    provider: str
    model: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    budget_verdict: str                 # allowed | denied:<reason>
    cost_source: str = "preflight_estimate"
    actual_input_tokens: int | None = None
    actual_output_tokens: int | None = None
    actual_cost_usd: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RankedCandidate:
    provider: str
    model: str
    estimated_cost_usd: float
    context_tokens: int
    eligible: bool
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def _field(candidate, name, default=None):
    """Read a field from a contract object or a plain dict (duck-typed, decoupled)."""
    if isinstance(candidate, dict):
        return candidate.get(name, default)
    return getattr(candidate, name, default)


def rank_candidates(candidates, input_tokens: int, output_tokens: int, *,
                    cached_input_tokens: int = 0,
                    per_request_cap_usd: float | None = None) -> list[RankedCandidate]:
    """Rank router candidates by ESTIMATED cost for this workload (cheapest first). A candidate
    is `eligible` only if its context window holds input+output and (when a cap is given) the
    estimate is under the per-request cap. The cheapest *eligible* candidate is the head of the
    returned list — data-derived, not a hardcoded provider preference."""
    needed_ctx = input_tokens + output_tokens
    ranked: list[RankedCandidate] = []
    for c in candidates:
        ctx = int(_field(c, "context_tokens", 0))
        cost = estimate_cost_usd(
            input_tokens, output_tokens,
            float(_field(c, "input_usd_per_mtok", 0.0)),
            float(_field(c, "output_usd_per_mtok", 0.0)),
            cached_input_tokens=cached_input_tokens,
            cached_input_usd_per_mtok=_field(c, "cached_input_usd_per_mtok"),
        )
        if ctx < needed_ctx:
            eligible, reason = False, (
                f"context {ctx} < needed {needed_ctx}")
        elif per_request_cap_usd is not None and cost > per_request_cap_usd:
            eligible, reason = False, (
                f"estimate ${cost:.4f} > per-request cap ${per_request_cap_usd:.4f}")
        else:
            eligible, reason = True, "eligible"
        ranked.append(RankedCandidate(
            provider=str(_field(c, "provider", "?")), model=str(_field(c, "model", "?")),
            estimated_cost_usd=cost, context_tokens=ctx, eligible=eligible, reason=reason))
    # cheapest first; ineligible sink to the bottom regardless of price.
    ranked.sort(key=lambda r: (not r.eligible, r.estimated_cost_usd))
    return ranked


def cheapest_eligible(candidates, input_tokens: int, output_tokens: int, *,
                      cached_input_tokens: int = 0,
                      per_request_cap_usd: float | None = None) -> RankedCandidate | None:
    """The single cheapest eligible candidate for this workload, or None if none qualifies."""
    ranked = rank_candidates(
        candidates, input_tokens, output_tokens, cached_input_tokens=cached_input_tokens,
        per_request_cap_usd=per_request_cap_usd)
    eligible = [r for r in ranked if r.eligible]
    return eligible[0] if eligible else None
