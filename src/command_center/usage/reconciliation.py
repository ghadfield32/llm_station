"""Cross-source reconciliation — detects when two sources disagree about the
same runtime's usage over the same window (e.g. our own cockpit session
tally vs. a provider-native or ccusage total). A mismatch is REPORTED, never
auto-resolved: the higher-authority source stays authoritative, and the gap
is surfaced (often it means real usage happened OUTSIDE the cockpit).

Pure functions over stored samples — no I/O. Phase 1 provides the mismatch
primitive; wiring it to a UI panel / alert is a later phase.
"""
from __future__ import annotations

from dataclasses import dataclass

from .schemas import UsageSample, UsageSource, source_rank


@dataclass
class ReconciliationMismatch:
    runtime_id: str
    metric: str
    authoritative_source: str        # the higher-authority source's value we trust
    authoritative_value: float
    other_source: str
    other_value: float
    difference: float                # authoritative - other (signed)
    note: str

    def to_dict(self) -> dict:
        return {
            "runtime_id": self.runtime_id, "metric": self.metric,
            "authoritative_source": self.authoritative_source,
            "authoritative_value": self.authoritative_value,
            "other_source": self.other_source, "other_value": self.other_value,
            "difference": self.difference, "note": self.note,
        }


def _sum(samples: list[UsageSample], metric: str) -> float:
    return float(sum(getattr(s, metric) for s in samples))


def reconcile(samples: list[UsageSample], *, runtime_id: str,
              metric: str = "total_tokens",
              tolerance: float = 0.0) -> list[ReconciliationMismatch]:
    """Compare the per-source totals of `metric` for one runtime. For every
    pair where the difference exceeds `tolerance`, emit a mismatch whose
    'authoritative' side is the higher-authority source (source_rank). A
    positive difference where the authoritative source is HIGHER than a
    reconciler/estimate typically means usage happened outside the surfaces
    we directly meter."""
    by_source: dict[UsageSource, list[UsageSample]] = {}
    for s in samples:
        if s.runtime_id == runtime_id:
            by_source.setdefault(s.source, []).append(s)

    totals = {src: _sum(rows, metric) for src, rows in by_source.items()}
    sources = sorted(totals, key=source_rank, reverse=True)
    mismatches: list[ReconciliationMismatch] = []
    for i, hi in enumerate(sources):
        for lo in sources[i + 1:]:
            diff = totals[hi] - totals[lo]
            if abs(diff) <= tolerance:
                continue
            mismatches.append(ReconciliationMismatch(
                runtime_id=runtime_id, metric=metric,
                authoritative_source=hi.value, authoritative_value=totals[hi],
                other_source=lo.value, other_value=totals[lo],
                difference=diff,
                note=(f"{hi.value} reports {totals[hi]:.0f} vs {lo.value} "
                      f"{totals[lo]:.0f} — "
                      + ("possible usage outside the metered surfaces"
                         if diff > 0 else "lower-authority source reports more"))))
    return mismatches
