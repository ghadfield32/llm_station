"""Alert derivation + deduplication. Pure functions over a LimitSnapshot /
availability transition — no I/O. The store's record_alert dedups by
`dedup_key`, so the SAME threshold crossing for the SAME reset window fires
exactly once, never once per poll (a load-bearing requirement — a collector
may poll every 30s).

An alert is NEVER derived from an UNKNOWN or missing signal: you cannot warn
that a bucket is 90% used when the provider never told you the percentage.
"""
from __future__ import annotations

from dataclasses import dataclass

from .schemas import (
    AlertKind,
    AvailabilityEvent,
    AvailabilityState,
    LimitScope,
    LimitSnapshot,
    LimitState,
    UsageAlert,
    now_iso,
)


@dataclass(frozen=True)
class AlertThresholds:
    warning_percent: float = 75.0
    critical_percent: float = 90.0


def _dedup_key(runtime_id: str, subject_id: str, kind: AlertKind,
               threshold: float | None, reset_at: str | None) -> str:
    """One firing per (runtime, subject, kind, threshold, reset window). The
    reset_at is part of the key so the SAME bucket crossing the SAME threshold
    in a NEW window (after a reset) is a genuinely new, non-deduplicated
    alert."""
    return f"{runtime_id}|{subject_id}|{kind.value}|{threshold}|{reset_at or ''}"


def _alert_id(dedup_key: str) -> str:
    import hashlib
    return "ALERT-" + hashlib.sha256(dedup_key.encode()).hexdigest()[:12]


def alerts_for_limit(snap: LimitSnapshot,
                     thresholds: AlertThresholds) -> list[UsageAlert]:
    """The alert(s) a limit snapshot warrants — caller passes each to
    store.record_alert (which dedups). Returns [] for UNKNOWN/None percent
    (never alert on data we don't have)."""
    budget = snap.scope == LimitScope.INTERNAL_BUDGET

    if snap.state == LimitState.EXHAUSTED:
        kind = AlertKind.BUDGET_EXHAUSTED if budget else AlertKind.LIMIT_EXHAUSTED
        key = _dedup_key(snap.runtime_id, snap.bucket_id, kind, None, snap.reset_at)
        return [UsageAlert(
            alert_id=_alert_id(key), runtime_id=snap.runtime_id, kind=kind,
            dedup_key=key, created_at=now_iso(), subject_id=snap.bucket_id,
            message=f"{snap.label or snap.bucket_id} is exhausted"
                    + (f"; resets {snap.reset_at}" if snap.reset_at else ""))]

    if snap.state == LimitState.UNKNOWN or snap.used_percent is None:
        return []   # cannot alert on an unknown quota

    pct = snap.used_percent
    if pct >= thresholds.critical_percent:
        kind = AlertKind.BUDGET_WARNING if budget else AlertKind.LIMIT_CRITICAL
        threshold = thresholds.critical_percent
    elif pct >= thresholds.warning_percent:
        kind = AlertKind.BUDGET_WARNING if budget else AlertKind.LIMIT_WARNING
        threshold = thresholds.warning_percent
    else:
        return []

    key = _dedup_key(snap.runtime_id, snap.bucket_id, kind, threshold, snap.reset_at)
    return [UsageAlert(
        alert_id=_alert_id(key), runtime_id=snap.runtime_id, kind=kind,
        dedup_key=key, created_at=now_iso(), subject_id=snap.bucket_id,
        threshold=threshold,
        message=f"{snap.label or snap.bucket_id} at {pct:.0f}% "
                + (f"(resets {snap.reset_at})" if snap.reset_at else ""))]


def alert_for_availability(prev: AvailabilityEvent | None,
                           new: AvailabilityEvent) -> UsageAlert | None:
    """Fire only on a MEANINGFUL availability change, never every poll. First
    observation (prev is None) only alerts if the runtime starts in a
    non-available state worth surfacing."""
    notable = {AvailabilityState.EXHAUSTED, AvailabilityState.LIMITED,
               AvailabilityState.AUTHENTICATION_REQUIRED, AvailabilityState.UNAVAILABLE}
    if prev is not None and prev.state == new.state:
        return None
    if prev is None and new.state not in notable:
        return None
    # dedup per (runtime, state, reason) — re-entering the same state with the
    # same reason won't re-fire until it changes
    key = _dedup_key(new.runtime_id, new.state.value,
                     AlertKind.AVAILABILITY_CHANGED, None, new.reason)
    return UsageAlert(
        alert_id=_alert_id(key), runtime_id=new.runtime_id,
        kind=AlertKind.AVAILABILITY_CHANGED, dedup_key=key, created_at=now_iso(),
        subject_id=new.state.value,
        message=f"{new.runtime_id} is {new.state.value}"
                + (f": {new.reason}" if new.reason else ""))
