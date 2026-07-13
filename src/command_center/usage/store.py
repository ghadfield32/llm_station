"""In-memory usage store — Phase 1 scope. Same INTERFACE
(UsageStoreProtocol) as the durable LedgerUsageStore, so the service, UI, and
router never care which backend they hold (mirrors agent_sessions'
SessionStore / LedgerSessionStore split).

Two load-bearing behaviours live here, proven by tests:
  * Idempotent ingestion — a repeat of the same source_hash returns the
    already-stored row, never a duplicate.
  * Source-priority reads — latest_limits/latest_availability return, per
    bucket, the highest-AUTHORITY then newest observation, so an `estimate`
    can never displace a real `provider_native` value in the rolled view
    (staleness is surfaced separately, never silently substituted).
"""
from __future__ import annotations

from .schemas import (
    AvailabilityEvent,
    CollectionState,
    LimitSnapshot,
    RoutingDecision,
    UsageAlert,
    UsageSample,
    _parse_iso,
    source_rank,
)


def _authority_key(row: AvailabilityEvent | LimitSnapshot):
    """Highest authority first, then newest observation — the source-priority
    ordering. A provider_native row outranks a fake/estimate row even if the
    latter is newer; ties within a source break by recency."""
    return (source_rank(row.source), _parse_iso(row.observed_at))


# Shared source-priority selectors — used by BOTH UsageStore and the durable
# LedgerUsageStore, so the two backends pick the SAME winner per bucket and
# stay behaviourally identical (an `estimate` never displaces a
# `provider_native` value in either).
def select_latest_limits(snapshots: list[LimitSnapshot]) -> list[LimitSnapshot]:
    by_bucket: dict[str, LimitSnapshot] = {}
    for snap in snapshots:
        cur = by_bucket.get(snap.bucket_id)
        if cur is None or _authority_key(snap) > _authority_key(cur):
            by_bucket[snap.bucket_id] = snap
    return sorted(by_bucket.values(), key=lambda s: s.bucket_id)


def select_latest_availability(events: list[AvailabilityEvent]) -> AvailabilityEvent | None:
    return max(events, key=_authority_key) if events else None


class UsageStore:
    def __init__(self) -> None:
        self._samples: dict[str, UsageSample] = {}
        self._limits: dict[str, LimitSnapshot] = {}
        self._availability: dict[str, AvailabilityEvent] = {}
        self._alerts: dict[str, UsageAlert] = {}
        self._routing: list[RoutingDecision] = []
        self._collection_state: dict[str, CollectionState] = {}
        # idempotency indexes: source_hash -> stored id
        self._sample_hashes: dict[str, str] = {}
        self._limit_hashes: dict[str, str] = {}
        self._availability_hashes: dict[str, str] = {}

    # ── ingestion (idempotent by source_hash) ───────────────────────────────
    def ingest_sample(self, sample: UsageSample) -> UsageSample:
        seen = self._sample_hashes.get(sample.source_hash)
        if seen is not None:
            return self._samples[seen]
        self._samples[sample.sample_id] = sample
        self._sample_hashes[sample.source_hash] = sample.sample_id
        return sample

    def ingest_limit(self, snapshot: LimitSnapshot) -> LimitSnapshot:
        seen = self._limit_hashes.get(snapshot.source_hash)
        if seen is not None:
            return self._limits[seen]
        self._limits[snapshot.snapshot_id] = snapshot
        self._limit_hashes[snapshot.source_hash] = snapshot.snapshot_id
        return snapshot

    def ingest_availability(self, event: AvailabilityEvent) -> AvailabilityEvent:
        seen = self._availability_hashes.get(event.source_hash)
        if seen is not None:
            return self._availability[seen]
        self._availability[event.event_id] = event
        self._availability_hashes[event.source_hash] = event.event_id
        return event

    def record_alert(self, alert: UsageAlert) -> UsageAlert | None:
        if alert.dedup_key in self._alerts:
            return None   # already fired for this exact threshold/window
        self._alerts[alert.dedup_key] = alert
        return alert

    def record_routing_decision(self, decision: RoutingDecision) -> RoutingDecision:
        self._routing.append(decision)
        return decision

    # ── queries ─────────────────────────────────────────────────────────────
    def samples_since(self, runtime_id: str, after_iso: str | None = None) -> list[UsageSample]:
        after = _parse_iso(after_iso) if after_iso else None
        rows = [s for s in self._samples.values() if s.runtime_id == runtime_id
                and (after is None or _parse_iso(s.observed_at) > after)]
        return sorted(rows, key=lambda s: _parse_iso(s.observed_at))

    def latest_limits(self, runtime_id: str) -> list[LimitSnapshot]:
        """One snapshot per bucket_id — the source-priority winner."""
        return select_latest_limits(
            [s for s in self._limits.values() if s.runtime_id == runtime_id])

    def latest_availability(self, runtime_id: str) -> AvailabilityEvent | None:
        return select_latest_availability(
            [e for e in self._availability.values() if e.runtime_id == runtime_id])

    def list_alerts(self, runtime_id: str | None = None) -> list[UsageAlert]:
        rows = list(self._alerts.values())
        if runtime_id is not None:
            rows = [a for a in rows if a.runtime_id == runtime_id]
        return sorted(rows, key=lambda a: a.created_at)

    def list_runtime_ids(self) -> list[str]:
        ids = {s.runtime_id for s in self._samples.values()}
        ids |= {lim.runtime_id for lim in self._limits.values()}
        ids |= {e.runtime_id for e in self._availability.values()}
        return sorted(ids)

    def get_collection_state(self, collector_id: str) -> CollectionState | None:
        return self._collection_state.get(collector_id)

    def set_collection_state(self, state: CollectionState) -> CollectionState:
        self._collection_state[state.collector_id] = state
        return state

    def prune_samples(self, before_iso: str) -> int:
        cutoff = _parse_iso(before_iso)
        to_drop = [sid for sid, s in self._samples.items()
                   if _parse_iso(s.observed_at) < cutoff]
        for sid in to_drop:
            s = self._samples.pop(sid)
            self._sample_hashes.pop(s.source_hash, None)
        return len(to_drop)
