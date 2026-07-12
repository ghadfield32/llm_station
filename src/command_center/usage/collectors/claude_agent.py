"""ClaudeRateLimitCollector — translates Claude Agent SDK `RateLimitEvent`s into
the canonical usage schemas, source=PROVIDER_NATIVE.

CRITICAL difference from the Codex collector: Claude limits are **event-driven**,
NOT pollable. The SDK emits a `RateLimitEvent` DURING a session when the rate-limit
state changes (verified by live SDK introspection: `RateLimitEvent.rate_limit_info`
is a `RateLimitInfo(status, resets_at epoch, rate_limit_type, utilization,
overage_*)`, with status ∈ {allowed, allowed_warning, rejected} and rate_limit_type
∈ {five_hour, seven_day, seven_day_opus, seven_day_sonnet, overage}). There is no
"read my current limits" RPC. So:

  * The Claude adapter emits a normalized `rate_limit` AgentEvent when it sees a
    RateLimitEvent; the worker forwards that event's payload dict to `feed()`.
  * `collect()` returns the LATEST fed state, or — until any event has been seen —
    an HONEST `unknown` availability ("no RateLimitEvent observed yet"), NEVER a
    fabricated quota and NEVER inferred from token counts.

This collector consumes a plain dict (the AgentEvent payload), never the SDK type,
so nothing in `usage/` imports `claude_agent_sdk` (same SDK-free discipline as the
rest of the subsystem). The dict keys mirror `RateLimitInfo`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from ..protocol import CollectorResult
from ..schemas import (
    AvailabilityEvent,
    AvailabilityState,
    LimitScope,
    LimitSnapshot,
    LimitState,
    UsageSource,
    compute_source_hash,
    now_iso,
)

CLAUDE_RUNTIME_ID = "claude_agent"          # matches ClaudeAgentHarness.name
CLAUDE_COLLECTOR_ID = "claude_agent_ratelimit"

# human labels per RateLimitType bucket
_BUCKET_LABELS = {
    "five_hour": "5-hour window",
    "seven_day": "weekly window",
    "seven_day_opus": "weekly (Opus)",
    "seven_day_sonnet": "weekly (Sonnet)",
    "overage": "overage",
}


def _epoch_to_iso(epoch: int | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _used_percent(utilization: float | None) -> float | None:
    """RateLimitInfo.utilization is a float whose scale the SDK docs don't pin
    down; live introspection shows the field but no live value was available to
    confirm 0..1 vs 0..100 (claude_agent needs ANTHROPIC_API_KEY, not present on
    the build host). Treat <=1.0 as a fraction and scale to a percent; treat a
    larger value as already a percent. Either way it is provider-reported, never
    inferred from tokens."""
    if utilization is None:
        return None
    return round(utilization * 100.0, 2) if utilization <= 1.0 else round(utilization, 2)


def _status_state(status: str | None) -> LimitState:
    if status == "rejected":
        return LimitState.EXHAUSTED
    if status == "allowed_warning":
        return LimitState.NEAR_LIMIT
    if status == "allowed":
        return LimitState.OK
    return LimitState.UNKNOWN


def _bucket_snapshot(*, runtime_id: str, bucket_id: str, status: str | None,
                     utilization: float | None, resets_at: int | None,
                     observed_at: str) -> LimitSnapshot:
    used = _used_percent(utilization)
    reset_iso = _epoch_to_iso(resets_at)
    h = compute_source_hash("claude_limit", runtime_id, bucket_id, observed_at,
                            status, used, reset_iso)
    return LimitSnapshot(
        snapshot_id=f"LS-{h[:12]}", runtime_id=runtime_id, bucket_id=bucket_id,
        scope=LimitScope.PROVIDER, source=UsageSource.PROVIDER_NATIVE,
        state=_status_state(status), observed_at=observed_at, ingested_at=now_iso(),
        source_hash=h, label=_BUCKET_LABELS.get(bucket_id, bucket_id),
        used_percent=used, unit="percent", reset_at=reset_iso)


def translate_rate_limit_info(info: Mapping[str, Any], observed_at: str,
                              runtime_id: str = CLAUDE_RUNTIME_ID) -> CollectorResult:
    """Pure: one RateLimitInfo dict -> a PROVIDER_NATIVE LimitSnapshot for its
    bucket (plus a separate `overage` bucket when the info carries overage
    fields) + an AvailabilityEvent derived from `status` (rejected -> EXHAUSTED,
    allowed_warning -> NEAR_LIMIT, allowed -> AVAILABLE). A missing
    rate_limit_type still yields availability (the status is authoritative) but
    no named bucket. `runtime_id` distinguishes the lanes: a claude_code_local
    (CLI subscription) feed must attribute to "claude_code_local", NOT the API
    lane's "claude_agent" — otherwise the two collide on one card."""
    status = info.get("status")
    bucket_type = info.get("rate_limit_type")
    limits: list[LimitSnapshot] = []
    if bucket_type:
        limits.append(_bucket_snapshot(
            runtime_id=runtime_id, bucket_id=str(bucket_type), status=status,
            utilization=info.get("utilization"), resets_at=info.get("resets_at"),
            observed_at=observed_at))
    if info.get("overage_status") is not None:
        limits.append(_bucket_snapshot(
            runtime_id=runtime_id, bucket_id="overage", status=info.get("overage_status"),
            utilization=None, resets_at=info.get("overage_resets_at"),
            observed_at=observed_at))

    if status == "rejected":
        state = AvailabilityState.EXHAUSTED
        reason = f"provider rejected: {bucket_type or 'rate limit'} exhausted"
    elif status == "allowed_warning":
        state = AvailabilityState.NEAR_LIMIT
        reason = f"approaching limit on {bucket_type or 'a window'}"
    elif status == "allowed":
        state = AvailabilityState.AVAILABLE
        reason = "provider allows requests"
    else:
        state = AvailabilityState.UNKNOWN
        reason = f"unrecognized rate-limit status: {status!r}"

    h = compute_source_hash("claude_avail", runtime_id, state.value, reason, observed_at)
    avail = AvailabilityEvent(
        event_id=f"AV-{h[:12]}", runtime_id=runtime_id,
        source=UsageSource.PROVIDER_NATIVE, state=state, observed_at=observed_at,
        ingested_at=now_iso(), source_hash=h, reason=reason,
        detail={"rate_limit_type": bucket_type})
    return CollectorResult(limits=limits, availability=[avail])


class ClaudeRateLimitCollector:
    """Event-fed collector. `feed(payload)` records the latest RateLimitInfo dict
    (the worker calls it on every `rate_limit` AgentEvent from the adapter);
    `collect()` returns the translation of the latest, or an honest UNKNOWN until
    one has been seen. Because Claude never exposes remaining quota except through
    these events, an unpolled/never-run claude_agent is legitimately UNKNOWN — and
    is shown as such, not as available."""

    source = UsageSource.PROVIDER_NATIVE

    def __init__(self, runtime_id: str = CLAUDE_RUNTIME_ID) -> None:
        # the lane this collector reports for: "claude_code_local" (CLI
        # subscription, the default lane) or "claude_agent" (the API lane).
        # Default preserves the original single-lane behaviour.
        self._runtime_id = runtime_id
        self._latest: Mapping[str, Any] | None = None
        self._latest_at: str | None = None

    def runtime_ids(self) -> list[str]:
        return [self._runtime_id]

    def feed(self, rate_limit_payload: Mapping[str, Any],
             observed_at: str | None = None) -> None:
        """Record the newest RateLimitInfo dict (from a `rate_limit` AgentEvent).
        observed_at defaults to now; a caller replaying a stored event should pass
        the event's own ts so freshness stays accurate."""
        self._latest = dict(rate_limit_payload)
        self._latest_at = observed_at or now_iso()

    async def collect(self) -> CollectorResult:
        if self._latest is None:
            observed_at = now_iso()
            h = compute_source_hash("claude_avail", self._runtime_id, "unknown",
                                    "no-event", observed_at)
            return CollectorResult(
                availability=[AvailabilityEvent(
                    event_id=f"AV-{h[:12]}", runtime_id=self._runtime_id,
                    source=UsageSource.PROVIDER_NATIVE, state=AvailabilityState.UNKNOWN,
                    observed_at=observed_at, ingested_at=now_iso(), source_hash=h,
                    reason="no RateLimitEvent observed yet — Claude limits are "
                           "event-driven; state is unknown until a session emits one")],
                warnings=[f"{self._runtime_id}: no rate-limit event observed yet"])
        return translate_rate_limit_info(self._latest, self._latest_at or now_iso(),
                                         self._runtime_id)
