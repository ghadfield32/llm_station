"""Attribution roll-up — answers "what used the most?" from RECORDED fact,
never a guessed explanation. Pure aggregation over stored UsageSamples along
whichever attribution dimension the caller asks for (mission, repo, user,
session, ...), ranked by a chosen metric (cost, tokens, tool_calls, ...).

Only the fields Attribution actually carries are groupable; there is no
credential/raw-response dimension here, by construction.
"""
from __future__ import annotations

from dataclasses import dataclass

from .schemas import UsageSample

# groupable attribution dimensions -> Attribution attribute name
_DIMENSIONS = {
    "tenant": "tenant_id", "workspace": "workspace_id", "user": "user_id",
    "conversation": "conversation_id", "session": "agent_session_id",
    "mission": "mission_id", "repo": "repo_id",
}
# dimensions that live on the UsageSample itself (not Attribution) — so "top
# model" / "top effort" are answered from recorded fact, not a guess.
_SAMPLE_DIMENSIONS = {"model": "model", "effort": "effort", "context": "context_mode"}


def _dimension_value(sample: UsageSample, dimension: str) -> str:
    if dimension in _SAMPLE_DIMENSIONS:
        return getattr(sample, _SAMPLE_DIMENSIONS[dimension]) or "(unattributed)"
    return getattr(sample.attribution, _DIMENSIONS[dimension]) or "(unattributed)"

# rankable metrics -> UsageSample attribute name
_METRICS = {
    "cost": "cost_usd", "total_tokens": "total_tokens",
    "uncached_input_tokens": None,   # computed below
    "output_tokens": "output_tokens", "calls": "calls",
    "tool_calls": "tool_calls", "duration_ms": "duration_ms",
    "sessions": "sessions",
}


def _metric_value(sample: UsageSample, metric: str) -> float:
    if metric == "uncached_input_tokens":
        return float(max(0, sample.input_tokens - sample.cached_input_tokens))
    attr = _METRICS[metric]
    assert attr is not None   # only "uncached_input_tokens" maps to None (handled above)
    return float(getattr(sample, attr))


@dataclass
class AttributionRow:
    key: str                 # the dimension value (e.g. a mission_id), or "(unattributed)"
    metric_value: float
    share: float             # fraction of the total (0..1)
    sample_count: int


def rank_by(samples: list[UsageSample], *, dimension: str, metric: str,
            limit: int = 10) -> list[AttributionRow]:
    """Top-N attribution rows for a metric along a dimension. Samples missing
    that dimension roll into a single explicit "(unattributed)" bucket — never
    dropped, never guessed."""
    if dimension not in _DIMENSIONS and dimension not in _SAMPLE_DIMENSIONS:
        known = sorted({*_DIMENSIONS, *_SAMPLE_DIMENSIONS})
        raise ValueError(f"unknown attribution dimension {dimension!r} (known: {known})")
    if metric not in _METRICS:
        raise ValueError(f"unknown metric {metric!r} (known: {sorted(_METRICS)})")

    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for s in samples:
        key = _dimension_value(s, dimension)
        totals[key] = totals.get(key, 0.0) + _metric_value(s, metric)
        counts[key] = counts.get(key, 0) + 1

    grand = sum(totals.values())
    rows = [AttributionRow(key=k, metric_value=v,
                           share=(v / grand if grand else 0.0),
                           sample_count=counts[k])
            for k, v in totals.items()]
    rows.sort(key=lambda r: r.metric_value, reverse=True)
    return rows[:limit]
