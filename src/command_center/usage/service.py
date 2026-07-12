"""UsageService — the single orchestrator between collectors and the store.
All source-priority, idempotency, alert-dedup and roll-up logic funnels
through here so those invariants live in exactly one place (mirrors
AgentSessionService).

Flow: run a collector → ingest its normalized rows (idempotent) → fire only
NEW, deduplicated alerts for the AUTHORITATIVE current state of each bucket
and each availability change → assemble a RuntimeUsageStatus the cockpit
renders (availability + all live buckets kept separate + rolled usage +
honest staleness).
"""
from __future__ import annotations

from .alerts import AlertThresholds, alert_for_availability, alerts_for_limit
from .protocol import CollectorProtocol, CollectorResult, UsageStoreProtocol
from .schemas import (
    Attribution,
    AvailabilityState,
    RuntimeUsageStatus,
    UsageAlert,
    UsageSample,
    UsageSource,
    age_seconds,
    now_iso,
)


class UsageService:
    def __init__(self, store: UsageStoreProtocol, *,
                 thresholds: AlertThresholds | None = None,
                 staleness_seconds: float = 300.0) -> None:
        self.store = store
        self.thresholds = thresholds or AlertThresholds()
        self.staleness_seconds = staleness_seconds

    async def run_collector(self, collector: CollectorProtocol) -> list[UsageAlert]:
        """Collect once and ingest — returns the alerts that newly fired."""
        result = await collector.collect()
        return self.ingest_collector_result(result)

    def ingest_collector_result(self, result: CollectorResult) -> list[UsageAlert]:
        affected = {s.runtime_id for s in result.samples}
        affected |= {lim.runtime_id for lim in result.limits}
        affected |= {e.runtime_id for e in result.availability}

        # capture prior AUTHORITATIVE availability before ingesting new events
        prev_avail = {rid: self.store.latest_availability(rid) for rid in affected}

        for sample in result.samples:
            self.store.ingest_sample(sample)
        for event in result.availability:
            self.store.ingest_availability(event)
        for snap in result.limits:
            self.store.ingest_limit(snap)

        fired: list[UsageAlert] = []
        for rid in sorted(affected):
            # availability: alert only if the authoritative state genuinely changed
            new_avail = self.store.latest_availability(rid)
            if new_avail is not None:
                prev = prev_avail.get(rid)
                changed = prev is None or prev.state != new_avail.state
                if changed:
                    alert = alert_for_availability(prev, new_avail)
                    if alert is not None:
                        recorded = self.store.record_alert(alert)
                        if recorded is not None:
                            fired.append(recorded)
            # limits: alert on the AUTHORITATIVE current snapshot per bucket only
            for snap in self.store.latest_limits(rid):
                for alert in alerts_for_limit(snap, self.thresholds):
                    recorded = self.store.record_alert(alert)
                    if recorded is not None:
                        fired.append(recorded)
        return fired

    def runtime_status(self, runtime_id: str) -> RuntimeUsageStatus:
        """The composite the UI renders — availability + all live buckets
        (kept separate) + rolled usage + honest staleness. Never flattens
        buckets into one percentage; UNKNOWN availability stays UNKNOWN."""
        avail = self.store.latest_availability(runtime_id)
        limits = self.store.latest_limits(runtime_id)
        rolled = self._roll_usage(runtime_id)

        # staleness = the freshest signal older than the bound. Availability
        # and limit snapshots are the "liveness" signals; if the newest of
        # them is stale, the whole status is flagged stale (shown, never
        # substituted).
        freshest = None
        for ts in ([avail.observed_at] if avail else []) + [lim.observed_at for lim in limits]:
            if freshest is None or ts > freshest:
                freshest = ts
        stale = freshest is not None and age_seconds(freshest) > self.staleness_seconds

        return RuntimeUsageStatus(
            runtime_id=runtime_id,
            availability=avail.state if avail else AvailabilityState.UNKNOWN,
            availability_reason=avail.reason if avail else "no availability signal yet",
            availability_observed_at=avail.observed_at if avail else None,
            limits=limits, rolled_usage=rolled, stale=stale, generated_at=now_iso())

    def all_statuses(self) -> list[RuntimeUsageStatus]:
        return [self.runtime_status(rid) for rid in self.store.list_runtime_ids()]

    def _roll_usage(self, runtime_id: str, after_iso: str | None = None) -> UsageSample | None:
        samples = self.store.samples_since(runtime_id, after_iso)
        if not samples:
            return None
        agg = UsageSample(
            sample_id=f"ROLLUP-{runtime_id}", runtime_id=runtime_id,
            source=UsageSource.PROVIDER_DERIVED, observed_at=samples[-1].observed_at,
            ingested_at=now_iso(), source_hash="", attribution=Attribution())
        for s in samples:
            agg.input_tokens += s.input_tokens
            agg.cached_input_tokens += s.cached_input_tokens
            agg.output_tokens += s.output_tokens
            agg.total_tokens += s.total_tokens
            agg.calls += s.calls
            agg.sessions += s.sessions
            agg.tool_calls += s.tool_calls
            agg.duration_ms += s.duration_ms
            agg.cost_usd = round(agg.cost_usd + s.cost_usd, 6)
        return agg
