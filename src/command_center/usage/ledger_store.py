"""LedgerUsageStore — the durable sibling of store.UsageStore, backed by the
Ledger's /model-usage* endpoints. Same UsageStoreProtocol surface, so the
UsageService/UI/router never care which backend they hold (mirrors
agent_sessions' LedgerSessionStore).

Sync, injected httpx.Client (never constructed here), 404→KeyError — the
exact conventions of ledger_store.py in agent_sessions. Idempotency/dedup are
enforced server-side (UNIQUE source_hash / dedup_key); source-priority WINNER
selection is applied HERE via the shared select_latest_* helpers, so this and
the in-memory store pick the identical winner per bucket.
"""
from __future__ import annotations

import json

import httpx

from .schemas import (
    AlertKind,
    Attribution,
    AvailabilityEvent,
    AvailabilityState,
    CollectionState,
    CostSource,
    LimitScope,
    LimitSnapshot,
    LimitState,
    RoutingDecision,
    SampleKind,
    UsageAlert,
    UsageSample,
    UsageSource,
)
from .store import select_latest_availability, select_latest_limits

_ATTR_FIELDS = (
    "tenant_id", "workspace_id", "user_id", "conversation_id", "agent_session_id",
    "mission_id", "repo_id", "provider_request_id", "source_record_id")
_SAMPLE_INT_FIELDS = (
    "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens",
    "total_tokens", "calls", "sessions", "tool_calls", "duration_ms",
    "repository_scans", "test_runs", "retries", "failed_calls", "worker_restarts",
    "session_resumes")


def _sample_to_row(s: UsageSample) -> dict:
    row = {
        "sample_id": s.sample_id, "runtime_id": s.runtime_id, "source": s.source.value,
        "observed_at": s.observed_at, "ingested_at": s.ingested_at,
        "source_hash": s.source_hash, "sample_kind": s.sample_kind.value,
        "cost_usd": s.cost_usd, "cost_source": s.cost_source.value,
        "window_start": s.window_start, "window_end": s.window_end,
        "aggregation_key": s.aggregation_key}
    for f in _SAMPLE_INT_FIELDS:
        row[f] = getattr(s, f)
    for f in _ATTR_FIELDS:
        row[f] = getattr(s.attribution, f)
    return row


def _row_to_sample(d: dict) -> UsageSample:
    attribution = Attribution(**{f: d.get(f) for f in _ATTR_FIELDS})
    ints = {f: d.get(f, 0) or 0 for f in _SAMPLE_INT_FIELDS}
    return UsageSample(
        sample_id=d["sample_id"], runtime_id=d["runtime_id"],
        source=UsageSource(d["source"]), observed_at=d["observed_at"],
        ingested_at=d["ingested_at"], source_hash=d["source_hash"],
        sample_kind=SampleKind(d.get("sample_kind") or "request_delta"),
        cost_usd=d.get("cost_usd"),
        cost_source=CostSource(d.get("cost_source") or "unknown"),
        window_start=d.get("window_start"), window_end=d.get("window_end"),
        aggregation_key=d.get("aggregation_key"), attribution=attribution, **ints)


def _row_to_limit(d: dict) -> LimitSnapshot:
    return LimitSnapshot(
        snapshot_id=d["snapshot_id"], runtime_id=d["runtime_id"],
        bucket_id=d["bucket_id"], scope=LimitScope(d["scope"]),
        source=UsageSource(d["source"]), state=LimitState(d["state"]),
        observed_at=d["observed_at"], ingested_at=d["ingested_at"],
        source_hash=d["source_hash"], label=d.get("label") or "",
        used_percent=d.get("used_percent"), used_amount=d.get("used_amount"),
        limit_amount=d.get("limit_amount"), remaining_amount=d.get("remaining_amount"),
        unit=d.get("unit") or "", window_seconds=d.get("window_seconds"),
        reset_at=d.get("reset_at"), plan_type=d.get("plan_type"),
        credits_remaining=d.get("credits_remaining"))


def _avail_to_row(e: AvailabilityEvent) -> dict:
    return {
        "event_id": e.event_id, "runtime_id": e.runtime_id, "source": e.source.value,
        "state": e.state.value, "observed_at": e.observed_at,
        "ingested_at": e.ingested_at, "source_hash": e.source_hash, "reason": e.reason,
        "detail": json.dumps(e.detail)}


def _row_to_avail(d: dict) -> AvailabilityEvent:
    return AvailabilityEvent(
        event_id=d["event_id"], runtime_id=d["runtime_id"],
        source=UsageSource(d["source"]), state=AvailabilityState(d["state"]),
        observed_at=d["observed_at"], ingested_at=d["ingested_at"],
        source_hash=d["source_hash"], reason=d.get("reason") or "",
        detail=json.loads(d["detail"]) if d.get("detail") else {})


def _alert_to_row(a: UsageAlert) -> dict:
    return {
        "alert_id": a.alert_id, "runtime_id": a.runtime_id, "kind": a.kind.value,
        "dedup_key": a.dedup_key, "created_at": a.created_at, "subject_id": a.subject_id,
        "threshold": a.threshold, "message": a.message, "detail": json.dumps(a.detail)}


def _row_to_alert(d: dict) -> UsageAlert:
    return UsageAlert(
        alert_id=d["alert_id"], runtime_id=d["runtime_id"], kind=AlertKind(d["kind"]),
        dedup_key=d["dedup_key"], created_at=d["created_at"],
        subject_id=d.get("subject_id") or "", threshold=d.get("threshold"),
        message=d.get("message") or "",
        detail=json.loads(d["detail"]) if d.get("detail") else {})


class LedgerUsageStore:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def ingest_sample(self, sample: UsageSample) -> UsageSample:
        r = self._client.post("/model-usage/sample", json=_sample_to_row(sample))
        r.raise_for_status()
        return _row_to_sample(r.json())

    def ingest_limit(self, snapshot: LimitSnapshot) -> LimitSnapshot:
        r = self._client.post("/model-usage/limit", json=snapshot.to_dict())
        r.raise_for_status()
        return _row_to_limit(r.json())

    def ingest_availability(self, event: AvailabilityEvent) -> AvailabilityEvent:
        r = self._client.post("/model-usage/availability", json=_avail_to_row(event))
        r.raise_for_status()
        return _row_to_avail(r.json())

    def record_alert(self, alert: UsageAlert) -> UsageAlert | None:
        r = self._client.post("/model-usage/alert", json=_alert_to_row(alert))
        r.raise_for_status()
        body = r.json()
        return _row_to_alert(body["alert"]) if body["recorded"] else None

    def record_routing_decision(self, decision: RoutingDecision) -> RoutingDecision:
        row = {
            "decision_id": decision.decision_id, "created_at": decision.created_at,
            "mission_id": decision.mission_id, "runtime_id": decision.runtime_id,
            "selected": 1 if decision.selected else 0, "reason": decision.reason,
            "usage_snapshot_id": decision.usage_snapshot_id,
            "limit_snapshot_ids": json.dumps(decision.limit_snapshot_ids),
            "availability_at_selection": decision.availability_at_selection,
            "budget_state_at_selection": decision.budget_state_at_selection}
        r = self._client.post("/model-usage/routing-decision", json=row)
        r.raise_for_status()
        return decision

    def samples_since(self, runtime_id: str, after_iso: str | None = None) -> list[UsageSample]:
        params = {"runtime_id": runtime_id}
        if after_iso:
            params["after"] = after_iso
        r = self._client.get("/model-usage/samples", params=params)
        r.raise_for_status()
        return [_row_to_sample(row) for row in r.json()]

    def latest_limits(self, runtime_id: str) -> list[LimitSnapshot]:
        r = self._client.get("/model-usage/limits", params={"runtime_id": runtime_id})
        r.raise_for_status()
        return select_latest_limits([_row_to_limit(row) for row in r.json()])

    def latest_availability(self, runtime_id: str) -> AvailabilityEvent | None:
        r = self._client.get("/model-usage/availability", params={"runtime_id": runtime_id})
        r.raise_for_status()
        return select_latest_availability([_row_to_avail(row) for row in r.json()])

    def list_alerts(self, runtime_id: str | None = None) -> list[UsageAlert]:
        params = {"runtime_id": runtime_id} if runtime_id else {}
        r = self._client.get("/model-usage/alerts", params=params)
        r.raise_for_status()
        return [_row_to_alert(row) for row in r.json()]

    def list_runtime_ids(self) -> list[str]:
        r = self._client.get("/model-usage/runtimes")
        r.raise_for_status()
        return list(r.json())

    def get_collection_state(self, collector_id: str) -> CollectionState | None:
        r = self._client.get(f"/model-usage/collection-state/{collector_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        d = r.json()
        return CollectionState(
            collector_id=d["collector_id"], updated_at=d["updated_at"],
            last_success_at=d.get("last_success_at"), last_cursor=d.get("last_cursor"),
            last_source_record_id=d.get("last_source_record_id"),
            last_error=d.get("last_error"),
            consecutive_failures=d.get("consecutive_failures", 0) or 0,
            next_eligible_at=d.get("next_eligible_at"),
            auth_state=d.get("auth_state") or "unknown")

    def set_collection_state(self, state: CollectionState) -> CollectionState:
        r = self._client.post("/model-usage/collection-state", json=state.to_dict())
        r.raise_for_status()
        return state

    def prune_samples(self, before_iso: str) -> int:
        r = self._client.post("/model-usage/prune", json={"before": before_iso})
        r.raise_for_status()
        return int(r.json()["removed"])
