"""CodexAppServerCollector — the FIRST real provider collector. Translates the
Codex app-server's account + rate-limit surface into the canonical usage
schemas, source=PROVIDER_NATIVE (authoritative — it can displace any
estimate). No I/O beyond the SDK; reports failures as CollectorResult
warnings + an AUTHENTICATION_REQUIRED / UNAVAILABLE availability event, never
by raising for an expected provider condition.

Every field/method used was verified by LIVE introspection against the pinned
`openai-codex` SDK (see WORKLOG.md): rate limits come from the raw RPC
`account/rateLimits/read` (the SDK exposes no named wrapper) via the
underlying AsyncCodexClient.request(...), returning a RateLimitSnapshot with
`primary`/`secondary` RateLimitWindow(used_percent, resets_at epoch,
window_duration_mins), plus plan_type, rate_limit_reached_type, credits, and
rate_limits_by_limit_id.

This collector emits LIMITS + AVAILABILITY (the provider-authoritative data).
Per-turn TOKEN usage is already captured by the agent-session adapter's own
`usage` events, so it is NOT re-emitted here (that would double-count — see
Phase 1.1 SampleKind). Codex subscription usage carries NO per-session dollar
charge, so any cost this layer shows for codex_agent is
subscription_not_metered, never $0.00.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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

CODEX_RUNTIME_ID = "codex_agent"      # matches CodexAgentHarness.name (cockpit joins on it)
CODEX_COLLECTOR_ID = "codex_app_server"

# used_percent thresholds for deriving a per-bucket state / overall availability
_NEAR = 75
_CRIT = 90


def _import_sdk() -> Any:
    try:
        import openai_codex as oc
    except ImportError as exc:  # pragma: no cover - exercised by the SDK-absent test
        raise ImportError(
            "openai-codex is not installed (optional dependency) — install with "
            "`uv sync --extra agent-codex`") from exc
    return oc


def _epoch_to_iso(epoch: int | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _limit_state(used_percent: int | None) -> LimitState:
    if used_percent is None:
        return LimitState.UNKNOWN
    if used_percent >= 100:
        return LimitState.EXHAUSTED
    if used_percent >= _NEAR:
        return LimitState.NEAR_LIMIT
    return LimitState.OK


def _window_snapshot(window: Any, *, bucket_id: str, label: str, observed_at: str,
                     plan_type: str | None) -> LimitSnapshot | None:
    if window is None:
        return None
    used = getattr(window, "used_percent", None)
    resets_at = _epoch_to_iso(getattr(window, "resets_at", None))
    window_mins = getattr(window, "window_duration_mins", None)
    # observed_at is part of the hash so each poll is a real time-series point
    # (accurate freshness); retention prunes the history.
    h = compute_source_hash("codex_limit", bucket_id, observed_at, used, resets_at)
    return LimitSnapshot(
        snapshot_id=f"LS-{h[:12]}", runtime_id=CODEX_RUNTIME_ID, bucket_id=bucket_id,
        scope=LimitScope.PROVIDER, source=UsageSource.PROVIDER_NATIVE,
        state=_limit_state(used), observed_at=observed_at, ingested_at=now_iso(),
        source_hash=h, label=label, used_percent=float(used) if used is not None else None,
        unit="percent", window_seconds=window_mins * 60 if window_mins else None,
        reset_at=resets_at, plan_type=plan_type)


def _availability(snap: Any, limits: list[LimitSnapshot], observed_at: str,
                  plan_label: str) -> AvailabilityEvent:
    reached = getattr(snap, "rate_limit_reached_type", None)
    if reached is not None:
        state = AvailabilityState.EXHAUSTED
        reason = f"rate limit reached: {getattr(reached, 'value', reached)}"
    else:
        worst = max((lim.used_percent or 0.0) for lim in limits) if limits else 0.0
        if worst >= _CRIT:
            state, reason = AvailabilityState.LIMITED, f"a window is at {worst:.0f}%"
        elif worst >= _NEAR:
            state, reason = AvailabilityState.NEAR_LIMIT, f"a window is at {worst:.0f}%"
        else:
            state, reason = AvailabilityState.AVAILABLE, f"healthy ({plan_label})"
    h = compute_source_hash("codex_avail", state.value, reason, observed_at)
    return AvailabilityEvent(
        event_id=f"AV-{h[:12]}", runtime_id=CODEX_RUNTIME_ID,
        source=UsageSource.PROVIDER_NATIVE, state=state, observed_at=observed_at,
        ingested_at=now_iso(), source_hash=h, reason=reason,
        detail={"plan": plan_label})


class CodexAppServerCollector:
    source = UsageSource.PROVIDER_NATIVE

    def __init__(self) -> None:
        self._client: Any = None

    def runtime_ids(self) -> list[str]:
        return [CODEX_RUNTIME_ID]

    async def _codex(self) -> Any:
        if self._client is None:
            oc = _import_sdk()
            # same guard the adapter uses: a global ~/.codex/config.toml
            # reasoning-effort newer than the pinned CLI build breaks calls.
            self._client = oc.AsyncCodex(
                oc.CodexConfig(config_overrides=("model_reasoning_effort=medium",)))
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None

    async def collect(self) -> CollectorResult:
        observed_at = now_iso()
        try:
            _import_sdk()  # fail fast with UNAVAILABLE if the SDK isn't installed
        except ImportError as exc:
            return self._unavailable(observed_at,
                                     AvailabilityState.UNAVAILABLE, str(exc))
        try:
            codex = await self._codex()
            acct = await codex.account()
        except Exception as exc:
            return self._unavailable(
                observed_at, AvailabilityState.AUTHENTICATION_REQUIRED,
                f"codex auth/account failed: {exc!r} — run `codex login`")

        plan_label = _plan_label(acct)
        try:
            from openai_codex.generated.v2_all import GetAccountRateLimitsResponse
            underlying = getattr(codex, "_client", None) or getattr(codex, "client")
            rl = await underlying.request(
                "account/rateLimits/read", None,
                response_model=GetAccountRateLimitsResponse)
        except Exception as exc:
            return CollectorResult(
                availability=[_avail_only(observed_at, AvailabilityState.AVAILABLE,
                                          f"authenticated ({plan_label}); "
                                          f"rate limits unavailable: {exc!r}")],
                warnings=[f"codex rateLimits/read failed: {exc!r}"])

        snap = rl.rate_limits
        plan_type = getattr(getattr(snap, "plan_type", None), "value", None)
        limits: list[LimitSnapshot] = []
        primary = _window_snapshot(getattr(snap, "primary", None), bucket_id="primary",
                                   label="Primary window", observed_at=observed_at,
                                   plan_type=plan_type)
        secondary = _window_snapshot(getattr(snap, "secondary", None),
                                     bucket_id="secondary", label="Secondary window",
                                     observed_at=observed_at, plan_type=plan_type)
        limits += [s for s in (primary, secondary) if s is not None]

        avail = _availability(snap, limits, observed_at, plan_label)
        return CollectorResult(limits=limits, availability=[avail])

    def _unavailable(self, observed_at: str, state: AvailabilityState,
                     reason: str) -> CollectorResult:
        return CollectorResult(availability=[_avail_only(observed_at, state, reason)],
                               warnings=[reason])


def _plan_label(acct: Any) -> str:
    try:
        root = acct.account.root
        plan = getattr(root, "plan_type", None)
        return getattr(plan, "value", str(plan)) if plan else "unknown plan"
    except AttributeError:
        return "unknown plan"


def _avail_only(observed_at: str, state: AvailabilityState, reason: str) -> AvailabilityEvent:
    h = compute_source_hash("codex_avail", state.value, reason, observed_at)
    return AvailabilityEvent(
        event_id=f"AV-{h[:12]}", runtime_id=CODEX_RUNTIME_ID,
        source=UsageSource.PROVIDER_NATIVE, state=state, observed_at=observed_at,
        ingested_at=now_iso(), source_hash=h, reason=reason)
