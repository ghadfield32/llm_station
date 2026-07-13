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
    _ADDITIVE_SAMPLE_KINDS,
    Attribution,
    AvailabilityState,
    CollectionState,
    RuntimeUsageStatus,
    SampleKind,
    UsageAlert,
    UsageSample,
    UsageSource,
    age_seconds,
    now_iso,
    summarize_cost,
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

    async def run_collector_tracked(self, collector: CollectorProtocol,
                                    collector_id: str) -> list[UsageAlert]:
        """Like run_collector, but persists a durable CollectionState checkpoint
        so a real collector resumes and its failures are visible. A collect()
        that RAISES (a genuine crash) increments consecutive_failures and
        records the error; a clean run resets them. auth_state reflects
        whether the collector reported an AUTHENTICATION_REQUIRED availability
        (a "ran but not authed" case is a soft failure, not a crash)."""
        prev = self.store.get_collection_state(collector_id)
        try:
            result = await collector.collect()
        except Exception as exc:
            failures = (prev.consecutive_failures if prev else 0) + 1
            self.store.set_collection_state(CollectionState(
                collector_id=collector_id, updated_at=now_iso(),
                last_success_at=prev.last_success_at if prev else None,
                last_error=repr(exc), consecutive_failures=failures,
                auth_state=prev.auth_state if prev else "unknown"))
            return []
        fired = self.ingest_collector_result(result)
        auth_state = ("authentication_required"
                      if any(e.state == AvailabilityState.AUTHENTICATION_REQUIRED
                             for e in result.availability) else "ok")
        self.store.set_collection_state(CollectionState(
            collector_id=collector_id, updated_at=now_iso(), last_success_at=now_iso(),
            last_error=None, consecutive_failures=0, auth_state=auth_state))
        return fired

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
        """Cockpit-ATTRIBUTED roll-up — sums ONLY additive REQUEST_DELTA
        samples, so the same activity observed by several collectors (a
        session_total, a provider_window_total, a ccusage reconciliation
        observation) is never triple-counted. Provider-wide totals live in
        the limit snapshots / a separate query, not here. Cost is summed
        honestly (None stays None, subscription activity is not $0.00)."""
        additive = [s for s in self.store.samples_since(runtime_id, after_iso)
                    if s.sample_kind in _ADDITIVE_SAMPLE_KINDS]
        if not additive:
            return None
        agg = UsageSample(
            sample_id=f"ROLLUP-{runtime_id}", runtime_id=runtime_id,
            source=UsageSource.PROVIDER_DERIVED, observed_at=additive[-1].observed_at,
            ingested_at=now_iso(), source_hash="",
            sample_kind=SampleKind.SESSION_TOTAL, attribution=Attribution())
        for s in additive:
            agg.input_tokens += s.input_tokens
            agg.cached_input_tokens += s.cached_input_tokens
            agg.output_tokens += s.output_tokens
            agg.reasoning_tokens += s.reasoning_tokens
            agg.total_tokens += s.total_tokens
            agg.calls += s.calls
            agg.sessions += s.sessions
            agg.tool_calls += s.tool_calls
            agg.duration_ms += s.duration_ms
            agg.repository_scans += s.repository_scans
            agg.test_runs += s.test_runs
            agg.retries += s.retries
            agg.failed_calls += s.failed_calls
            agg.worker_restarts += s.worker_restarts
            agg.session_resumes += s.session_resumes
        agg.cost_usd, agg.cost_source = summarize_cost(additive)
        return agg
