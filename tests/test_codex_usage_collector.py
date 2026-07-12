"""CodexAppServerCollector — hermetic tests against a FAKE openai_codex SDK
(installed into sys.modules; no real package/network/account). The live
account+rate-limit path is exercised separately (see WORKLOG.md); this proves
the translation into canonical schemas, the availability derivation, and the
collector-state bookkeeping deterministically.
"""
from __future__ import annotations

import asyncio
import sys
import types

from command_center.usage.collectors.codex_app_server import (
    CODEX_COLLECTOR_ID,
    CodexAppServerCollector,
)
from command_center.usage.schemas import (
    AvailabilityState,
    LimitScope,
    LimitState,
    UsageSource,
)
from command_center.usage.service import UsageService
from command_center.usage.store import UsageStore


# ── fake SDK ─────────────────────────────────────────────────────────────────

class _Enum:
    def __init__(self, value):
        self.value = value


class _Window:
    def __init__(self, used_percent, resets_at, window_duration_mins):
        self.used_percent = used_percent
        self.resets_at = resets_at
        self.window_duration_mins = window_duration_mins


class _Snapshot:
    def __init__(self, primary=None, secondary=None, plan_type="prolite", reached=None):
        self.primary = primary
        self.secondary = secondary
        self.plan_type = _Enum(plan_type) if plan_type else None
        self.rate_limit_reached_type = _Enum(reached) if reached else None
        self.credits = None
        self.limit_id = "codex"
        self.limit_name = None


class _RateLimitsResponse:
    def __init__(self, snapshot, by_limit_id=None):
        self.rate_limits = snapshot
        self.rate_limits_by_limit_id = by_limit_id or {}


class _AccountRoot:
    def __init__(self, plan="prolite"):
        self.email = "test@example.com"
        self.plan_type = _Enum(plan)
        self.type = "chatgpt"


class _AccountResponse:
    def __init__(self):
        self.account = types.SimpleNamespace(root=_AccountRoot())
        self.requires_openai_auth = True


class _FakeUnderlying:
    def __init__(self, snapshot, rl_error=None, by_limit_id=None):
        self._snapshot = snapshot
        self._rl_error = rl_error
        self._by_limit_id = by_limit_id

    async def request(self, method, params, *, response_model):
        if self._rl_error is not None:
            raise self._rl_error
        return _RateLimitsResponse(self._snapshot, self._by_limit_id)


class _FakeAsyncCodex:
    def __init__(self, config=None):
        self.account_error = None
        self.snapshot = _Snapshot(
            primary=_Window(0, 1783861277, 300),
            secondary=_Window(0, 1784400188, 10080))
        self.rl_error = None
        self.by_limit_id = None       # non-empty dict -> the multi-bucket path
        self.closed = False

    @property
    def _client(self):
        return _FakeUnderlying(self.snapshot, self.rl_error, self.by_limit_id)

    async def account(self):
        if self.account_error is not None:
            raise self.account_error
        return _AccountResponse()

    async def close(self):
        self.closed = True


def _install_fake_sdk(monkeypatch, codex: _FakeAsyncCodex):
    fake_oc = types.SimpleNamespace(
        AsyncCodex=lambda config=None: codex,
        CodexConfig=lambda **kw: types.SimpleNamespace(**kw))
    monkeypatch.setitem(sys.modules, "openai_codex", fake_oc)
    gen = types.ModuleType("openai_codex.generated.v2_all")
    gen.GetAccountRateLimitsResponse = _RateLimitsResponse
    monkeypatch.setitem(sys.modules, "openai_codex.generated.v2_all", gen)
    monkeypatch.setitem(sys.modules, "openai_codex.generated",
                        types.ModuleType("openai_codex.generated"))


# ── translation ──────────────────────────────────────────────────────────────

def test_maps_primary_and_secondary_windows_to_provider_native_buckets(monkeypatch):
    codex = _FakeAsyncCodex()
    codex.snapshot = _Snapshot(
        primary=_Window(40, 1783861277, 300),
        secondary=_Window(12, 1784400188, 10080))
    _install_fake_sdk(monkeypatch, codex)

    result = asyncio.run(CodexAppServerCollector().collect())
    buckets = {lim.bucket_id: lim for lim in result.limits}
    assert set(buckets) == {"primary", "secondary"}
    p = buckets["primary"]
    assert p.source == UsageSource.PROVIDER_NATIVE      # authoritative, beats estimates
    assert p.scope == LimitScope.PROVIDER
    assert p.used_percent == 40.0
    assert p.window_seconds == 300 * 60
    assert p.reset_at == "2026-07-12T13:01:17+00:00"    # epoch -> ISO UTC
    assert p.plan_type == "prolite"
    assert buckets["secondary"].window_seconds == 10080 * 60


def test_availability_available_when_healthy(monkeypatch):
    codex = _FakeAsyncCodex()
    codex.snapshot = _Snapshot(primary=_Window(10, 1783861277, 300))
    _install_fake_sdk(monkeypatch, codex)
    result = asyncio.run(CodexAppServerCollector().collect())
    assert result.availability[0].state == AvailabilityState.AVAILABLE


def test_availability_near_and_limited_from_used_percent(monkeypatch):
    codex = _FakeAsyncCodex()
    codex.snapshot = _Snapshot(primary=_Window(80, 1783861277, 300))
    _install_fake_sdk(monkeypatch, codex)
    near = asyncio.run(CodexAppServerCollector().collect())
    assert near.availability[0].state == AvailabilityState.NEAR_LIMIT

    codex.snapshot = _Snapshot(primary=_Window(95, 1783861277, 300))
    limited = asyncio.run(CodexAppServerCollector().collect())
    assert limited.availability[0].state == AvailabilityState.LIMITED


def test_availability_exhausted_when_rate_limit_reached(monkeypatch):
    codex = _FakeAsyncCodex()
    codex.snapshot = _Snapshot(primary=_Window(100, 1783861277, 300),
                               reached="rate_limit_reached")
    _install_fake_sdk(monkeypatch, codex)
    result = asyncio.run(CodexAppServerCollector().collect())
    assert result.availability[0].state == AvailabilityState.EXHAUSTED
    assert "rate_limit_reached" in result.availability[0].reason
    # the 100% window is also its own EXHAUSTED bucket
    assert result.limits[0].state == LimitState.EXHAUSTED


# ── failure modes ────────────────────────────────────────────────────────────

def test_sdk_absent_is_unavailable_not_a_crash(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai_codex", None)
    result = asyncio.run(CodexAppServerCollector().collect())
    assert result.availability[0].state == AvailabilityState.UNAVAILABLE
    assert result.warnings


def test_auth_failure_is_authentication_required(monkeypatch):
    codex = _FakeAsyncCodex()
    codex.account_error = RuntimeError("not logged in")
    _install_fake_sdk(monkeypatch, codex)
    result = asyncio.run(CodexAppServerCollector().collect())
    assert result.availability[0].state == AvailabilityState.AUTHENTICATION_REQUIRED
    assert result.warnings


def test_rate_limits_read_failure_keeps_available_but_warns(monkeypatch):
    codex = _FakeAsyncCodex()
    codex.rl_error = RuntimeError("rpc boom")
    _install_fake_sdk(monkeypatch, codex)
    result = asyncio.run(CodexAppServerCollector().collect())
    # auth worked, so still available — but no limit rows and a warning
    assert result.availability[0].state == AvailabilityState.AVAILABLE
    assert result.limits == []
    assert result.warnings


# ── multi-bucket view (rate_limits_by_limit_id) ──────────────────────────────

def _win_d(used, resets, mins):
    return {"usedPercent": used, "windowDurationMins": mins, "resetsAt": resets}


def _credits_d(has, balance, unlimited=False):
    return {"hasCredits": has, "unlimited": unlimited, "balance": balance}


def _limit_entry(limit_id, *, name=None, primary=None, secondary=None, credits=None):
    return {"limitId": limit_id, "limitName": name, "primary": primary,
            "secondary": secondary, "credits": credits, "individualLimit": None}


def test_multi_bucket_imports_every_named_limit_and_dedupes_compat(monkeypatch):
    codex = _FakeAsyncCodex()
    # the default `codex` limit + a per-model limit, the real shape
    codex.by_limit_id = {
        "codex": _limit_entry(
            "codex",
            primary=_win_d(40, 1783861277, 300),
            secondary=_win_d(12, 1784400188, 10080),
            credits=_credits_d(False, "0")),
        "codex_bengalfox": _limit_entry(
            "codex_bengalfox", name="GPT-5.3-Codex-Spark",
            primary=_win_d(7, 1783877044, 300),
            secondary=_win_d(3, 1784463844, 10080)),
    }
    _install_fake_sdk(monkeypatch, codex)

    result = asyncio.run(CodexAppServerCollector().collect())
    buckets = {lim.bucket_id: lim for lim in result.limits}
    # default limit keeps bare primary/secondary (dedupes the compat view);
    # the per-model limit is namespaced — 4 buckets, no duplicates
    assert set(buckets) == {"primary", "secondary",
                            "codex_bengalfox_primary", "codex_bengalfox_secondary"}
    assert len(result.limits) == 4
    assert buckets["primary"].used_percent == 40.0
    assert buckets["primary"].source == UsageSource.PROVIDER_NATIVE
    # the named limit carries its human label
    assert "GPT-5.3-Codex-Spark" in buckets["codex_bengalfox_primary"].label
    assert buckets["codex_bengalfox_secondary"].window_seconds == 10080 * 60


def test_credits_imported_only_when_has_credits(monkeypatch):
    codex = _FakeAsyncCodex()
    codex.by_limit_id = {
        "codex": _limit_entry("codex", primary=_win_d(5, 1783861277, 300),
                              credits=_credits_d(False, "0")),          # off -> None
        "codex_paid": _limit_entry("codex_paid", name="Paid",
                                   primary=_win_d(5, 1783861277, 300),
                                   credits=_credits_d(True, "12.5")),   # on -> 12.5
    }
    _install_fake_sdk(monkeypatch, codex)
    buckets = {lim.bucket_id: lim
               for lim in asyncio.run(CodexAppServerCollector().collect()).limits}
    assert buckets["primary"].credits_remaining is None
    assert buckets["codex_paid_primary"].credits_remaining == 12.5


def test_multi_bucket_availability_uses_worst_window_across_all_limits(monkeypatch):
    codex = _FakeAsyncCodex()
    codex.by_limit_id = {
        "codex": _limit_entry("codex", primary=_win_d(10, 1783861277, 300)),
        "codex_hot": _limit_entry("codex_hot", name="Hot",
                                  primary=_win_d(93, 1783861277, 300)),  # worst
    }
    _install_fake_sdk(monkeypatch, codex)
    result = asyncio.run(CodexAppServerCollector().collect())
    assert result.availability[0].state == AvailabilityState.LIMITED
    assert "93%" in result.availability[0].reason


# ── end-to-end through the service + collector state ─────────────────────────

def test_tracked_run_records_success_state_and_status(monkeypatch):
    codex = _FakeAsyncCodex()
    codex.snapshot = _Snapshot(primary=_Window(40, 1783861277, 300),
                               secondary=_Window(5, 1784400188, 10080))
    _install_fake_sdk(monkeypatch, codex)
    store = UsageStore()
    svc = UsageService(store, staleness_seconds=1e9)
    asyncio.run(svc.run_collector_tracked(CodexAppServerCollector(), CODEX_COLLECTOR_ID))

    st = svc.runtime_status("codex_agent")
    assert st.availability == AvailabilityState.AVAILABLE
    assert {lim.bucket_id for lim in st.limits} == {"primary", "secondary"}
    state = store.get_collection_state(CODEX_COLLECTOR_ID)
    assert state.auth_state == "ok"
    assert state.consecutive_failures == 0
    assert state.last_success_at is not None


def test_tracked_run_records_failure_state_on_crash(monkeypatch):
    class _Boom:
        source = UsageSource.PROVIDER_NATIVE

        def runtime_ids(self):
            return ["codex_agent"]

        async def collect(self):
            raise RuntimeError("collector crashed")

    store = UsageStore()
    svc = UsageService(store)
    fired = asyncio.run(svc.run_collector_tracked(_Boom(), CODEX_COLLECTOR_ID))
    assert fired == []
    state = store.get_collection_state(CODEX_COLLECTOR_ID)
    assert state.consecutive_failures == 1
    assert "collector crashed" in state.last_error


def test_provider_native_limit_beats_a_prior_estimate(monkeypatch):
    """The whole point of a real collector: its PROVIDER_NATIVE bucket
    displaces any earlier ESTIMATE for the same bucket in the rolled view."""
    from command_center.usage.schemas import (
        LimitSnapshot, compute_source_hash, now_iso)

    store = UsageStore()
    h = compute_source_hash("est", "primary")
    store.ingest_limit(LimitSnapshot(
        snapshot_id="LS-est", runtime_id="codex_agent", bucket_id="primary",
        scope=LimitScope.PROVIDER, source=UsageSource.ESTIMATE, state=LimitState.NEAR_LIMIT,
        observed_at=now_iso(), ingested_at=now_iso(), source_hash=h, used_percent=88.0))

    codex = _FakeAsyncCodex()
    codex.snapshot = _Snapshot(primary=_Window(40, 1783861277, 300))
    _install_fake_sdk(monkeypatch, codex)
    svc = UsageService(store, staleness_seconds=1e9)
    asyncio.run(svc.run_collector_tracked(CodexAppServerCollector(), CODEX_COLLECTOR_ID))

    primary = next(lim for lim in svc.runtime_status("codex_agent").limits
                   if lim.bucket_id == "primary")
    assert primary.source == UsageSource.PROVIDER_NATIVE
    assert primary.used_percent == 40.0   # the estimate's 88% is displaced
