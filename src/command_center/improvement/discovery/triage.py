"""
Triage — decide, for each Finding, whether it becomes a Backlog card or is held back.

The board stays signal, not noise, through four gates (mirrors the proactive proposal guards,
extended with a real negative-result memory):

  * NOISE            — confidence below the floor.
  * DUPLICATE_OPEN   — an experiment for the same dedup target is already in flight or shipped.
  * NEGATIVE_MEMORY  — we already tried this and a human REJECTED it / it was ROLLED BACK.
                       Re-proposing it would be the system forgetting its own mistakes; suppress
                       and COUNT it (the negative-result-memory hit rate is a tracked metric).
  * COOLDOWN         — a soft terminal (Deferred / Inconclusive / Expired) within the window.

Everything else is a DRAFT. Pure and deterministic given `now_iso` (no wall-clock reads here).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ..registry import ExperimentRegistry
from .findings import Finding

# already in flight or already shipped — do not re-draft
_ACTIVE = frozenset({
    "Proposed", "Baseline Ready", "Running", "Awaiting Verification",
    "Verified", "Awaiting Human Promotion", "Canary", "Promoted",
})
# a human said no, or it regressed in production — this is negative-result memory
_HARD_NEGATIVE = frozenset({"Rejected", "Rolled Back"})
# soft terminals that may be re-proposed once the cooldown elapses
_SOFT_TERMINAL = frozenset({"Deferred", "Inconclusive", "Expired"})


class TriageDecision(StrEnum):
    DRAFT = "draft"
    NOISE = "noise"
    DUPLICATE_OPEN = "duplicate_open"
    DUPLICATE_BATCH = "duplicate_batch"
    NEGATIVE_MEMORY = "negative_memory"
    COOLDOWN = "cooldown"


@dataclass
class TriageResult:
    finding: Finding
    decision: TriageDecision
    reason: str
    prior_status: str | None = None

    @property
    def is_draft(self) -> bool:
        return self.decision is TriageDecision.DRAFT


def _age_hours(ts: str | None, now_iso: str) -> float:
    if not ts:
        return 1e9
    try:
        return max(0.0, (datetime.fromisoformat(now_iso)
                         - datetime.fromisoformat(ts)).total_seconds() / 3600.0)
    except (ValueError, TypeError) as e:
        raise ValueError(f"un-parseable timestamp {ts!r} / {now_iso!r}") from e


class Triage:
    def __init__(self, registry: ExperimentRegistry, *,
                 min_confidence: float = 0.4, cooldown_hours: float = 168.0):
        self.reg = registry
        self.min_confidence = min_confidence
        self.cooldown_hours = cooldown_hours

    def classify(self, findings: list[Finding], *, now_iso: str) -> list[TriageResult]:
        by_id = {e["experiment_id"]: e for e in self.reg.list_experiments()}
        seen: set[str] = set()
        out: list[TriageResult] = []
        for f in findings:
            out.append(self._classify_one(f, by_id, seen, now_iso))
        return out

    def _classify_one(self, f: Finding, by_id: dict[str, dict],
                      seen: set[str], now_iso: str) -> TriageResult:
        eid = f.experiment_id
        if f.confidence < self.min_confidence:
            return TriageResult(f, TriageDecision.NOISE,
                                f"confidence {f.confidence:.2f} < floor {self.min_confidence:.2f}")
        if eid in seen:
            return TriageResult(f, TriageDecision.DUPLICATE_BATCH, "same target seen earlier in batch")
        prior = by_id.get(eid)
        if prior is not None:
            status = prior["status"]
            if status in _ACTIVE:
                return TriageResult(f, TriageDecision.DUPLICATE_OPEN,
                                    f"an experiment is already {status}", status)
            if status in _HARD_NEGATIVE:
                return TriageResult(f, TriageDecision.NEGATIVE_MEMORY,
                                    f"previously {status} — not re-proposing a known dead end", status)
            if status in _SOFT_TERMINAL:
                age = _age_hours(prior.get("updated_at") or prior.get("created_at"), now_iso)
                if age < self.cooldown_hours:
                    return TriageResult(f, TriageDecision.COOLDOWN,
                                        f"{status} {age:.0f}h ago < cooldown {self.cooldown_hours:.0f}h",
                                        status)
        seen.add(eid)
        return TriageResult(f, TriageDecision.DRAFT, "new actionable finding")

    @staticmethod
    def drafts(results: list[TriageResult]) -> list[TriageResult]:
        return [r for r in results if r.is_draft]

    @staticmethod
    def negative_hits(results: list[TriageResult]) -> list[TriageResult]:
        return [r for r in results if r.decision is TriageDecision.NEGATIVE_MEMORY]
