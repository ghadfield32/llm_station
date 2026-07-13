"""Canonical usage/limits/availability/budget records — the SAME shape
regardless of which runtime (Codex, Claude, OpenRouter, LiteLLM, Ollama, a
local engine) or which collector produced them. A collector's job is
translating its vendor-specific source into THESE; nothing upstream (store,
service, UI, router) should ever need to know which vendor produced a row.

Plain dataclasses (house style — mirrors agent_sessions/store.py), ISO-8601
UTC timestamp strings. The four concepts are deliberately four different
record types so they can never be conflated:

  UsageSample        — what we OBSERVED being consumed (attributable)
  LimitSnapshot      — a provider quota bucket OR an internal budget, as of a time
  AvailabilityEvent  — a runtime's availability state transition
  UsageAlert         — a deduplicated threshold/reset/availability alert

Plus RoutingDecision (why a runtime was picked/rejected) and the composite
RuntimeUsageStatus roll-up the cockpit renders.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def age_seconds(observed_at: str, *, now: str | None = None) -> float:
    """Seconds between an observation and now — the basis for staleness.
    Never negative (clock skew clamps to 0)."""
    ref = _parse_iso(now) if now else datetime.now(timezone.utc)
    return max(0.0, (ref - _parse_iso(observed_at)).total_seconds())


# ── source authority ────────────────────────────────────────────────────────
class UsageSource(str, Enum):
    """WHERE a row came from — used for source-priority: a lower-authority
    source must NEVER overwrite a higher one for the same runtime+bucket
    (see service.py). `estimate` is our own math (router_cost); it can never
    displace a real provider-reported limit."""
    PROVIDER_NATIVE = "provider_native"      # Codex account/rateLimits, Claude RateLimitEvent, OpenRouter key
    PROVIDER_DERIVED = "provider_derived"    # LiteLLM spend logs, computed from a provider usage block
    RECONCILER = "reconciler"                # ccusage — historical, never authoritative for REMAINING quota
    ESTIMATE = "estimate"                    # our own preflight estimate (router_cost)
    FAKE = "fake"                            # the deterministic test collector


# highest number = most authoritative. FAKE ranks above ESTIMATE so a test
# collector can drive the whole pipeline deterministically, but still below
# any real provider source.
_SOURCE_RANK = {
    UsageSource.PROVIDER_NATIVE: 40,
    UsageSource.PROVIDER_DERIVED: 30,
    UsageSource.RECONCILER: 20,
    UsageSource.FAKE: 15,
    UsageSource.ESTIMATE: 10,
}


def source_rank(source: UsageSource) -> int:
    return _SOURCE_RANK[source]


# ── availability / limit / budget vocabularies ──────────────────────────────
class AvailabilityState(str, Enum):
    AVAILABLE = "available"
    BUSY = "busy"
    NEAR_LIMIT = "near_limit"
    LIMITED = "limited"
    EXHAUSTED = "exhausted"
    AUTHENTICATION_REQUIRED = "authentication_required"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"        # we genuinely do not know — NEVER shown as "available"


class LimitState(str, Enum):
    OK = "ok"
    NEAR_LIMIT = "near_limit"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"        # provider did not report — NEVER coerced to 0% used


class LimitScope(str, Enum):
    """A LimitSnapshot is EITHER a provider quota bucket OR one of OUR internal
    budgets — the same record type, kept distinct by this field so provider
    allowance is never confused with an internal spending rule."""
    PROVIDER = "provider"
    INTERNAL_BUDGET = "internal_budget"


class CostSource(str, Enum):
    """WHERE a cost figure came from — so a MISSING dollar value is never shown
    as $0.00. Subscription Codex/Claude sessions genuinely expose token
    activity WITHOUT a per-session dollar charge; that is
    `subscription_not_metered`, not zero. `cost_usd = None` + one of these is
    the honest representation."""
    PROVIDER_REPORTED = "provider_reported"          # a real provider dollar charge
    ESTIMATED = "estimated"                          # our router_cost math
    SUBSCRIPTION_NOT_METERED = "subscription_not_metered"  # activity under a plan, no $ per session
    UNKNOWN = "unknown"                              # we simply don't know
    MIXED = "mixed"                                  # a roll-up spanning >1 of the above


class SampleKind(str, Enum):
    """What KIND of usage measurement this is — the guard against double-
    counting. Only REQUEST_DELTA is ADDITIVE (safe to sum). The others are
    snapshots/totals from a provider or a reconciler and must NOT be summed
    into the cockpit-attributed total (see service.py's roll-up); they are
    separate authoritative views."""
    REQUEST_DELTA = "request_delta"                  # one request's incremental usage (additive)
    SESSION_TOTAL = "session_total"                  # a session's running total (a snapshot)
    PROVIDER_WINDOW_TOTAL = "provider_window_total"  # provider's total for a quota window
    PROVIDER_LIFETIME_TOTAL = "provider_lifetime_total"
    DAILY_BUCKET = "daily_bucket"                    # provider's per-day bucket
    RECONCILIATION_OBSERVATION = "reconciliation_observation"  # ccusage etc. — evidence only


# the ONLY additive sample kind — summing anything else double-counts
_ADDITIVE_SAMPLE_KINDS = frozenset({SampleKind.REQUEST_DELTA})


class AlertKind(str, Enum):
    USAGE_UPDATED = "usage_updated"
    LIMIT_UPDATED = "limit_updated"
    LIMIT_WARNING = "limit_warning"
    LIMIT_CRITICAL = "limit_critical"
    LIMIT_EXHAUSTED = "limit_exhausted"
    LIMIT_RESET = "limit_reset"
    AVAILABILITY_CHANGED = "availability_changed"
    USAGE_RECONCILIATION_MISMATCH = "usage_reconciliation_mismatch"
    BUDGET_WARNING = "budget_warning"
    BUDGET_EXHAUSTED = "budget_exhausted"


# ── attribution ─────────────────────────────────────────────────────────────
@dataclass
class Attribution:
    """WHO/WHAT a usage row belongs to, so "what used the most?" is answered
    from recorded fact, never a guess. Every field optional — a plain
    non-cockpit chat call may only have a conversation_id, a mission run has
    the full chain. Deliberately holds NO credential/token/raw-response
    field (see the subsystem invariant)."""
    tenant_id: str | None = None
    workspace_id: str | None = None
    user_id: str | None = None
    conversation_id: str | None = None
    agent_session_id: str | None = None
    mission_id: str | None = None
    repo_id: str | None = None
    provider_request_id: str | None = None
    source_record_id: str | None = None   # the source's own id for this row (for reconciliation)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_source_hash(*parts: Any) -> str:
    """Idempotency key for ingestion: a stable hash over the identifying parts
    of a source record. Re-ingesting the same source row (same parts) is a
    no-op. Deterministic — sorted-keys JSON, sha256."""
    payload = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


# ── the four records ────────────────────────────────────────────────────────
@dataclass
class UsageSample:
    """One observed usage measurement for a runtime. `sample_kind` says whether
    it is additive (REQUEST_DELTA) or a snapshot/total that must NOT be summed
    (see service.py). `cost_usd` is None when there is no dollar figure —
    NEVER 0.0 as a stand-in — and `cost_source` says why. The driver_* fields
    feed the "what used the most?" explanation from recorded fact."""
    sample_id: str
    runtime_id: str                    # "codex_agent" | "claude_agent" | "openrouter:deepseek..." | "ollama:qwen3:30b"
    source: UsageSource
    observed_at: str                   # when the SOURCE observed it
    ingested_at: str                   # when WE stored it
    source_hash: str                   # idempotency key
    sample_kind: SampleKind = SampleKind.REQUEST_DELTA
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0
    sessions: int = 0
    tool_calls: int = 0
    duration_ms: int = 0
    cost_usd: float | None = None      # None = no dollar figure (see cost_source), NOT $0.00
    cost_source: CostSource = CostSource.UNKNOWN
    # cost/window bounds — a provider window/daily bucket carries these
    window_start: str | None = None
    window_end: str | None = None
    aggregation_key: str | None = None  # groups snapshots of the SAME window across polls
    # driver facts for "what used the most?" — recorded, never guessed
    repository_scans: int = 0
    test_runs: int = 0
    retries: int = 0
    failed_calls: int = 0
    worker_restarts: int = 0
    session_resumes: int = 0
    attribution: Attribution = field(default_factory=Attribution)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source"] = self.source.value
        d["sample_kind"] = self.sample_kind.value
        d["cost_source"] = self.cost_source.value
        return d


@dataclass
class LimitSnapshot:
    """A provider quota bucket OR internal budget, as reported at a moment.
    Multiple buckets per runtime coexist (Codex primary+weekly, Claude
    five_hour+seven_day_sonnet+seven_day_opus, ...) — keyed by
    (runtime_id, bucket_id). `used_percent`/`remaining`/`reset_at` are None
    when the source didn't report them; state=UNKNOWN then, NEVER 0%."""
    snapshot_id: str
    runtime_id: str
    bucket_id: str                     # "primary" | "seven_day_sonnet" | "monthly_project_budget" | ...
    scope: LimitScope
    source: UsageSource
    state: LimitState
    observed_at: str
    ingested_at: str
    source_hash: str
    label: str = ""                    # human label for the bucket
    used_percent: float | None = None  # None = provider didn't report
    used_amount: float | None = None   # tokens or USD, unit in `unit`
    limit_amount: float | None = None
    remaining_amount: float | None = None
    unit: str = ""                     # "tokens" | "usd" | "requests" | ""
    window_seconds: int | None = None
    reset_at: str | None = None
    plan_type: str | None = None
    credits_remaining: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["scope"] = self.scope.value
        d["source"] = self.source.value
        d["state"] = self.state.value
        return d


@dataclass
class AvailabilityEvent:
    """A runtime availability transition. `reason` is a concrete string, never
    a generic "unavailable" (same discipline as agent_preflight probes)."""
    event_id: str
    runtime_id: str
    source: UsageSource
    state: AvailabilityState
    observed_at: str
    ingested_at: str
    source_hash: str
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source"] = self.source.value
        d["state"] = self.state.value
        return d


@dataclass
class UsageAlert:
    """A deduplicated alert. dedup_key = (runtime_id, subject_id, kind,
    threshold, reset_at) — the same threshold crossing for the same reset
    window fires ONCE, never once per poll (see alerts.py)."""
    alert_id: str
    runtime_id: str
    kind: AlertKind
    dedup_key: str
    created_at: str
    subject_id: str = ""               # bucket_id / budget id the alert is about
    threshold: float | None = None
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d


@dataclass
class RoutingDecision:
    """WHY a runtime was selected or rejected for a mission — records the exact
    usage/limit/availability/budget evidence used, so an auto-router decision
    is auditable and never a silent fallback (Phase 8 consumes this; the table
    exists from Phase 1 so decisions are captured as soon as routing exists)."""
    decision_id: str
    created_at: str
    mission_id: str | None
    runtime_id: str
    selected: bool
    reason: str
    usage_snapshot_id: str | None = None
    limit_snapshot_ids: list[str] = field(default_factory=list)
    availability_at_selection: str | None = None    # AvailabilityState value
    budget_state_at_selection: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize_cost(samples: list["UsageSample"]) -> tuple[float | None, CostSource]:
    """Honest cost roll-up: sums ONLY the samples that carry a real dollar
    figure. If none do, returns (None, ...) — never 0.0 as a stand-in.
    cost_source is PROVIDER_REPORTED/ESTIMATED when uniform, MIXED when both
    appear, SUBSCRIPTION_NOT_METERED when the only signal is subscription
    activity, else UNKNOWN."""
    priced = [s for s in samples if s.cost_usd is not None]
    if not priced:
        if any(s.cost_source == CostSource.SUBSCRIPTION_NOT_METERED for s in samples):
            return None, CostSource.SUBSCRIPTION_NOT_METERED
        return None, CostSource.UNKNOWN
    total = round(sum(s.cost_usd for s in priced if s.cost_usd is not None), 6)
    sources = {s.cost_source for s in priced}
    if sources == {CostSource.PROVIDER_REPORTED}:
        return total, CostSource.PROVIDER_REPORTED
    if sources == {CostSource.ESTIMATED}:
        return total, CostSource.ESTIMATED
    return total, CostSource.MIXED


@dataclass
class CollectionState:
    """Durable per-collector checkpoint — prevents duplicate range re-imports
    and makes a collector's failures visible. A collector reads this before
    polling (resume from last_cursor) and writes it after (advance cursor /
    record error + backoff)."""
    collector_id: str
    updated_at: str
    last_success_at: str | None = None
    last_cursor: str | None = None
    last_source_record_id: str | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    next_eligible_at: str | None = None
    auth_state: str = "unknown"        # ok | authentication_required | unknown

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── the composite roll-up the cockpit renders ───────────────────────────────
@dataclass
class RuntimeUsageStatus:
    """The single object the Usage & Limits UI shows per runtime: current
    availability + every live limit bucket (provider AND internal budget,
    kept separate) + rolled usage. Assembled by service.py from the stored
    records — NEVER by flattening buckets into one percentage."""
    runtime_id: str
    availability: AvailabilityState
    availability_reason: str
    availability_observed_at: str | None
    limits: list[LimitSnapshot]        # all live buckets, provider + internal_budget
    rolled_usage: UsageSample | None   # aggregate over the roll-up window (None = no samples)
    stale: bool                        # true if the freshest signal is older than the staleness bound
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_id": self.runtime_id,
            "availability": self.availability.value,
            "availability_reason": self.availability_reason,
            "availability_observed_at": self.availability_observed_at,
            "limits": [lim.to_dict() for lim in self.limits],
            "rolled_usage": self.rolled_usage.to_dict() if self.rolled_usage else None,
            "stale": self.stale,
            "generated_at": self.generated_at,
        }
