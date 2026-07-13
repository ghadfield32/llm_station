"""CodexAppServerCollector — the FIRST real provider collector. Translates the
Codex app-server's account + rate-limit surface into the canonical usage
schemas, source=PROVIDER_NATIVE (authoritative — it can displace any
estimate). No I/O beyond the SDK; reports failures as CollectorResult
warnings + an AUTHENTICATION_REQUIRED / UNAVAILABLE availability event, never
by raising for an expected provider condition.

Every field/method used was verified by LIVE introspection against the pinned
`openai-codex` SDK (see WORKLOG.md). Rate limits come from the raw RPC
`account/rateLimits/read` (the SDK exposes no named wrapper) via the underlying
AsyncCodexClient.request(...). The response carries TWO views:
  - `rate_limits`: the single-bucket COMPATIBILITY RateLimitSnapshot
    (`primary`/`secondary` RateLimitWindow(used_percent, resets_at epoch,
    window_duration_mins), plan_type, rate_limit_reached_type, credits).
  - `rate_limits_by_limit_id`: the MULTI-BUCKET view — a dict keyed by
    limit_id (the default `codex` limit PLUS per-model limits like
    `codex_bengalfox` = "GPT-5.3-Codex-Spark"), each a dict with camelCase
    `primary`/`secondary` windows, its own `credits` (balance/hasCredits/
    unlimited), and a `limitName`.
We import EVERY named bucket and DEDUPE the compatibility windows against the
default limit (it emits the same bare primary/secondary), so nothing is
double-counted; other limit_ids are namespaced `{limit_id}_primary/_secondary`.

Two grounded corrections from that live introspection:
  - There is NO `account/usage/read` in this pinned app-server — the JSON-RPC
    server rejects it as an unknown variant (valid account methods are only
    rateLimits/read, read, login/*, logout, sendAddCreditsNudgeEmail). So there
    is no account-level token/daily-bucket summary to poll here. Per-turn TOKEN
    usage instead flows through the adapter's `ThreadTokenUsage` events, which
    the collector deliberately does NOT re-emit (that would double-count — see
    Phase 1.1 SampleKind).
  - `account/rateLimits/updated` is a server NOTIFICATION, not a request. The
    worker wires it (and every reconnect) to a fresh `collect()` refresh —
    one code path, no separate notification-payload parsing to drift against.

This collector emits LIMITS + AVAILABILITY (the provider-authoritative data).
Codex subscription usage carries NO per-session dollar charge, so any cost this
layer shows for codex_agent is subscription_not_metered, never $0.00.
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


def _win_fields(window: Any) -> tuple[int | None, int | None, int | None]:
    """(used_percent, resets_at_epoch, window_duration_mins) from a
    RateLimitWindow — which is a pydantic model (snake_case) on the
    compatibility `primary`/`secondary`, but a raw dict (camelCase) inside
    `rate_limits_by_limit_id`. Handle both."""
    if window is None:
        return None, None, None
    if isinstance(window, dict):
        return (window.get("usedPercent"), window.get("resetsAt"),
                window.get("windowDurationMins"))
    return (getattr(window, "used_percent", None),
            getattr(window, "resets_at", None),
            getattr(window, "window_duration_mins", None))


def _credits_fields(credits: Any) -> tuple[float | None, bool, bool]:
    """(balance, has_credits, unlimited) from a CreditsSnapshot (model) or its
    camelCase dict form. `balance` is a numeric STRING at the source."""
    if credits is None:
        return None, False, False
    if isinstance(credits, dict):
        bal, has, unl = (credits.get("balance"), credits.get("hasCredits"),
                         credits.get("unlimited"))
    else:
        bal = getattr(credits, "balance", None)
        has = getattr(credits, "has_credits", None)
        unl = getattr(credits, "unlimited", None)
    try:
        balance = float(bal) if bal is not None else None
    except (TypeError, ValueError):
        balance = None
    return balance, bool(has), bool(unl)


def _mk_snapshot(*, bucket_id: str, label: str, used: int | None,
                 resets_at_epoch: int | None, window_mins: int | None,
                 observed_at: str, plan_type: str | None,
                 credits_remaining: float | None) -> LimitSnapshot:
    resets_at = _epoch_to_iso(resets_at_epoch)
    # observed_at is part of the hash so each poll is a real time-series point
    # (accurate freshness); retention prunes the history.
    h = compute_source_hash("codex_limit", bucket_id, observed_at, used, resets_at)
    return LimitSnapshot(
        snapshot_id=f"LS-{h[:12]}", runtime_id=CODEX_RUNTIME_ID, bucket_id=bucket_id,
        scope=LimitScope.PROVIDER, source=UsageSource.PROVIDER_NATIVE,
        state=_limit_state(used), observed_at=observed_at, ingested_at=now_iso(),
        source_hash=h, label=label, used_percent=float(used) if used is not None else None,
        unit="percent", window_seconds=window_mins * 60 if window_mins else None,
        reset_at=resets_at, plan_type=plan_type, credits_remaining=credits_remaining)


# each limit_id carries a 5-hour "primary" and a weekly "secondary" window
_WINDOWS = (("primary", "5-hour window"), ("secondary", "weekly window"))


def _named_bucket_limits(by_limit_id: dict[str, Any], default_limit_id: str,
                         observed_at: str, plan_type: str | None,
                         ) -> list[LimitSnapshot]:
    """Import EVERY bucket in `rate_limits_by_limit_id` (the multi-bucket view:
    the default `codex` limit plus per-model limits like `codex_bengalfox`).
    The DEFAULT limit's windows keep the bare `primary`/`secondary` bucket_ids
    — they are the same data the compatibility view reports, so this DEDUPES
    the compat windows against the named view instead of emitting both. Every
    other limit_id is namespaced `{limit_id}_primary` / `_secondary`."""
    out: list[LimitSnapshot] = []
    for limit_id, entry in by_limit_id.items():
        if not isinstance(entry, dict):
            continue
        is_default = limit_id == default_limit_id
        prefix = "" if is_default else f"{limit_id}_"
        name = entry.get("limitName") or (None if is_default else limit_id)
        balance, has_credits, _unl = _credits_fields(entry.get("credits"))
        credits_remaining = balance if has_credits else None
        for win_key, win_label in _WINDOWS:
            used, resets, mins = _win_fields(entry.get(win_key))
            if used is None and resets is None and mins is None:
                continue
            label = f"{name} · {win_label}" if name else win_label
            out.append(_mk_snapshot(
                bucket_id=f"{prefix}{win_key}", label=label, used=used,
                resets_at_epoch=resets, window_mins=mins, observed_at=observed_at,
                plan_type=plan_type, credits_remaining=credits_remaining))
    return out


def _compat_limits(snap: Any, observed_at: str, plan_type: str | None,
                   ) -> list[LimitSnapshot]:
    """Fallback when the multi-bucket view is absent: the single-bucket
    compatibility `primary`/`secondary` windows on the snapshot itself."""
    balance, has_credits, _unl = _credits_fields(getattr(snap, "credits", None))
    credits_remaining = balance if has_credits else None
    out: list[LimitSnapshot] = []
    for win_key, win_label in _WINDOWS:
        used, resets, mins = _win_fields(getattr(snap, win_key, None))
        if used is None and resets is None and mins is None:
            continue
        out.append(_mk_snapshot(
            bucket_id=win_key, label=win_label, used=used, resets_at_epoch=resets,
            window_mins=mins, observed_at=observed_at, plan_type=plan_type,
            credits_remaining=credits_remaining))
    return out


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
        # Prefer the multi-bucket view (every limit_id: the default `codex`
        # limit PLUS per-model limits, each with its own credits); fall back to
        # the single-bucket compatibility windows only when it is absent. The
        # default limit's windows are emitted as bare primary/secondary in BOTH
        # paths, so the compat windows are never double-counted against it.
        by_limit_id = getattr(rl, "rate_limits_by_limit_id", None) or {}
        default_limit_id = getattr(snap, "limit_id", None) or "codex"
        if by_limit_id:
            limits = _named_bucket_limits(by_limit_id, default_limit_id,
                                          observed_at, plan_type)
        else:
            limits = _compat_limits(snap, observed_at, plan_type)

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
