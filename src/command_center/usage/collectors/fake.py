"""FakeCollector — a deterministic CollectorProtocol with NO I/O, NO network,
NO provider. It exists to prove the store → service → roll-up → alert
pipeline works BEFORE any real provider collector is wired in (same role as
agent_sessions' FakeHarness). Every row it emits is fully determined by its
constructor args, so tests can drive an exact scenario (a bucket at 92% must
produce a critical alert; an UNKNOWN bucket must produce none).

`source = UsageSource.FAKE`, which ranks below every real provider source —
so even if a real collector is added later, the fake can never displace real
provider data in the rolled view.
"""
from __future__ import annotations

from ..protocol import CollectorResult
from ..schemas import (
    AvailabilityEvent,
    AvailabilityState,
    CostSource,
    LimitScope,
    LimitSnapshot,
    LimitState,
    SampleKind,
    UsageSample,
    UsageSource,
    compute_source_hash,
    now_iso,
)


def _limit_state(used_percent: float | None) -> LimitState:
    if used_percent is None:
        return LimitState.UNKNOWN
    if used_percent >= 100:
        return LimitState.EXHAUSTED
    if used_percent >= 75:
        return LimitState.NEAR_LIMIT
    return LimitState.OK


class FakeCollector:
    source = UsageSource.FAKE

    def __init__(self, runtime_id: str = "fake_runtime", *,
                 observed_at: str | None = None,
                 primary_used_percent: float | None = 40.0,
                 budget_used_percent: float | None = 20.0,
                 availability: AvailabilityState = AvailabilityState.AVAILABLE,
                 availability_reason: str = "fake collector: healthy",
                 total_tokens: int = 1000,
                 cost_usd: float = 0.01,
                 reset_at: str | None = None) -> None:
        # observed_at pinned at construction so a test gets identical
        # source_hashes across calls (idempotency is provable)
        self._runtime_id = runtime_id
        self._observed_at = observed_at or now_iso()
        self._primary_pct = primary_used_percent
        self._budget_pct = budget_used_percent
        self._availability = availability
        self._availability_reason = availability_reason
        self._total_tokens = total_tokens
        self._cost_usd = cost_usd
        self._reset_at = reset_at

    def runtime_ids(self) -> list[str]:
        return [self._runtime_id]

    async def collect(self) -> CollectorResult:
        ingested = now_iso()
        rid, obs = self._runtime_id, self._observed_at

        sample_hash = compute_source_hash("fake_sample", rid, obs)
        sample = UsageSample(
            sample_id=f"US-{sample_hash[:12]}", runtime_id=rid,
            source=self.source, observed_at=obs, ingested_at=ingested,
            source_hash=sample_hash, sample_kind=SampleKind.REQUEST_DELTA,
            input_tokens=self._total_tokens, output_tokens=0,
            total_tokens=self._total_tokens, calls=1, sessions=1,
            cost_usd=self._cost_usd, cost_source=CostSource.ESTIMATED)

        primary_hash = compute_source_hash("fake_limit", rid, "primary", obs)
        primary = LimitSnapshot(
            snapshot_id=f"LS-{primary_hash[:12]}", runtime_id=rid,
            bucket_id="primary", scope=LimitScope.PROVIDER, source=self.source,
            state=_limit_state(self._primary_pct), observed_at=obs,
            ingested_at=ingested, source_hash=primary_hash,
            label="Primary window", used_percent=self._primary_pct,
            unit="tokens", reset_at=self._reset_at)

        budget_hash = compute_source_hash("fake_budget", rid, "monthly_budget", obs)
        budget = LimitSnapshot(
            snapshot_id=f"LS-{budget_hash[:12]}", runtime_id=rid,
            bucket_id="monthly_budget", scope=LimitScope.INTERNAL_BUDGET,
            source=self.source, state=_limit_state(self._budget_pct),
            observed_at=obs, ingested_at=ingested, source_hash=budget_hash,
            label="Monthly project budget", used_percent=self._budget_pct,
            unit="usd")

        avail_hash = compute_source_hash(
            "fake_avail", rid, self._availability.value, self._availability_reason, obs)
        avail = AvailabilityEvent(
            event_id=f"AV-{avail_hash[:12]}", runtime_id=rid, source=self.source,
            state=self._availability, observed_at=obs, ingested_at=ingested,
            source_hash=avail_hash, reason=self._availability_reason)

        return CollectorResult(samples=[sample], limits=[primary, budget],
                               availability=[avail])
