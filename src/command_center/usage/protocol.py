"""The two interfaces the usage subsystem depends on: what a COLLECTOR
produces and what a STORE offers. Everything else (service, UI, router)
depends only on these — never on a concrete backend or a vendor SDK, the
same discipline as agent_sessions' AgentHarness/SessionStoreProtocol.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .schemas import (
    AvailabilityEvent,
    LimitSnapshot,
    RoutingDecision,
    UsageAlert,
    UsageSample,
    UsageSource,
)


@dataclass
class CollectorResult:
    """One collection pass's normalized output. A collector NEVER writes to
    the store itself — it returns this and the UsageService ingests it, so
    source-priority/idempotency/dedup live in exactly one place."""
    samples: list[UsageSample] = field(default_factory=list)
    limits: list[LimitSnapshot] = field(default_factory=list)
    availability: list[AvailabilityEvent] = field(default_factory=list)
    # collectors report their own failures here rather than raising, so one
    # broken provider never blanks the whole Usage view (mirrors the "never
    # fabricate, surface the real reason" discipline)
    warnings: list[str] = field(default_factory=list)


@runtime_checkable
class CollectorProtocol(Protocol):
    """A source of usage/limits/availability for one or more runtimes. Real
    collectors do provider I/O (async); all must translate their vendor
    source into the canonical schemas and must NEVER retain raw responses or
    credentials in what they return."""

    source: UsageSource

    def runtime_ids(self) -> list[str]:
        """Which runtime_ids this collector reports on (may be dynamic)."""
        ...

    async def collect(self) -> CollectorResult:
        """One collection pass. Returns normalized rows; reports failures as
        `warnings`, never by raising for an EXPECTED provider condition."""
        ...


@runtime_checkable
class UsageStoreProtocol(Protocol):
    """Durable storage surface. Ingestion is idempotent by source_hash (a
    repeat returns the already-stored row, does not duplicate). Query methods
    return the records the service rolls up into a RuntimeUsageStatus."""

    def ingest_sample(self, sample: UsageSample) -> UsageSample: ...

    def ingest_limit(self, snapshot: LimitSnapshot) -> LimitSnapshot: ...

    def ingest_availability(self, event: AvailabilityEvent) -> AvailabilityEvent: ...

    def record_alert(self, alert: UsageAlert) -> UsageAlert | None:
        """Returns the alert if newly recorded, or None if its dedup_key was
        already present (deduplicated — no duplicate fired)."""
        ...

    def record_routing_decision(self, decision: RoutingDecision) -> RoutingDecision: ...

    def samples_since(self, runtime_id: str, after_iso: str | None = None) -> list[UsageSample]: ...

    def latest_limits(self, runtime_id: str) -> list[LimitSnapshot]:
        """The freshest snapshot per (bucket_id) for a runtime — one row per
        live bucket, highest-authority + newest wins (the service applies
        source-priority on ingest, so this is just the current set)."""
        ...

    def latest_availability(self, runtime_id: str) -> AvailabilityEvent | None: ...

    def list_alerts(self, runtime_id: str | None = None) -> list[UsageAlert]: ...

    def list_runtime_ids(self) -> list[str]: ...
