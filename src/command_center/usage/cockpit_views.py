"""Read-only view builders that turn a UsageService into the JSON the cockpit
Usage & Limits page renders. PURE functions over the service + its store — no
FastAPI, no vendor SDK — so they unit-test without the cockpit and the cockpit
route handlers stay one-liners.

The honesty contract of the usage subsystem carries straight through here:
nothing flattens buckets into a single percentage, UNKNOWN/stale stay visible,
and a missing dollar value is never rendered as $0.00 (that is the schema's
job — these views only serialize what the store already decided).
"""
from __future__ import annotations

from typing import Any

from .attribution import rank_by
from .protocol import CollectorProtocol
from .schemas import SampleKind
from .service import UsageService


def usage_overview(service: UsageService,
                   after_iso: str | None = None) -> list[dict[str, Any]]:
    """One RuntimeUsageStatus per runtime the store knows about — the top-level
    Usage & Limits list (availability + every live bucket + rolled usage +
    honest staleness)."""
    return [s.to_dict() for s in service.all_statuses(after_iso)]


def runtime_detail(service: UsageService, runtime_id: str) -> dict[str, Any]:
    """The full status for one runtime (UNKNOWN availability + no buckets if we
    have never observed it — never an error, never fabricated)."""
    return service.runtime_status(runtime_id).to_dict()


def limits_overview(service: UsageService) -> list[dict[str, Any]]:
    """Every live limit bucket across ALL runtimes, each tagged with its
    runtime's availability + staleness so the UI can badge a bucket honestly.
    Buckets stay separate — provider quota and internal budget are distinct
    rows (scope tells them apart), never merged into one number."""
    out: list[dict[str, Any]] = []
    for st in service.all_statuses():
        for lim in st.limits:
            row = lim.to_dict()
            row["runtime_availability"] = st.availability.value
            row["runtime_stale"] = st.stale
            out.append(row)
    return out


def alerts_view(service: UsageService,
                runtime_id: str | None = None) -> list[dict[str, Any]]:
    """Deduplicated alerts (a threshold crossing appears once, not once per
    poll — the store enforces that), newest last."""
    return [a.to_dict() for a in service.store.list_alerts(runtime_id)]


def top_drivers(service: UsageService, *, runtime_id: str,
                dimension: str = "mission", metric: str = "total_tokens",
                limit: int = 10, after_iso: str | None = None) -> dict[str, Any]:
    """"What used the most?" for one runtime, from RECORDED driver facts —
    ranked attribution rows along a dimension (mission/repo/session/…) by a
    metric (total_tokens/cost/…). Samples missing the dimension roll into an
    explicit "(unattributed)" bucket, never dropped."""
    samples = [
        sample for sample in service.store.samples_since(runtime_id, after_iso)
        if sample.sample_kind == SampleKind.REQUEST_DELTA
    ]
    rows = rank_by(samples, dimension=dimension, metric=metric, limit=limit)
    return {
        "runtime_id": runtime_id, "dimension": dimension, "metric": metric,
        "rows": [{"key": r.key, "metric_value": r.metric_value,
                  "share": r.share, "sample_count": r.sample_count}
                 for r in rows],
    }


def recent_activity(service: UsageService, *, runtime_id: str,
                    limit: int = 8,
                    after_iso: str | None = None) -> dict[str, Any]:
    """Sanitized recent request activity plus derived runtime KPIs.

    Prompts, responses, provider request IDs, users, and credentials are never
    returned. Purpose is limited to recorded repo/mission/conversation scope.
    """
    samples = [
        sample for sample in service.store.samples_since(runtime_id, after_iso)
        if sample.sample_kind == SampleKind.REQUEST_DELTA
    ]
    samples.sort(key=lambda sample: sample.observed_at, reverse=True)
    calls = sum(sample.calls for sample in samples)
    from .agent_usage import effective_token_counts

    effective = [effective_token_counts(sample) for sample in samples]
    input_tokens = sum(row[0] for row in effective)
    cached_tokens = sum(row[1] for row in effective)
    output_tokens = sum(row[2] for row in effective)
    total_tokens = sum(sample.total_tokens for sample in samples)
    duration_ms = sum(sample.duration_ms for sample in samples)
    duration_observed_calls = sum(
        sample.calls for sample in samples if sample.duration_ms > 0)
    priced = [sample for sample in samples if sample.cost_usd is not None]
    total_cost = (round(sum(sample.cost_usd or 0 for sample in priced), 6)
                  if priced else None)

    rows = []
    for sample in samples[:max(1, min(limit, 20))]:
        effective_input, effective_cached, effective_output, effective_total = (
            effective_token_counts(sample))
        scope = []
        if sample.attribution.repo_id:
            scope.append(f"Repository {sample.attribution.repo_id}")
        if sample.attribution.mission_id:
            scope.append(f"Mission {sample.attribution.mission_id}")
        if not scope and sample.attribution.conversation_id:
            scope.append("Conversation session")
        rows.append({
            "observed_at": sample.observed_at,
            "purpose": " · ".join(scope) if scope else "Agent session",
            "model": sample.model,
            "effort": sample.effort,
            "context_mode": sample.context_mode,
            "input_tokens": effective_input,
            "cached_input_tokens": effective_cached,
            "output_tokens": effective_output,
            "total_tokens": effective_total,
            "duration_ms": sample.duration_ms if sample.duration_ms > 0 else None,
            "cost_usd": sample.cost_usd,
            "cost_source": (
                "subscription_not_metered"
                if runtime_id == "codex_agent" and sample.cost_usd is None
                else sample.cost_source.value),
        })
    return {
        "runtime_id": runtime_id,
        "kpis": {
            "average_tokens_per_call": (
                round(total_tokens / calls, 1) if calls else None),
            "average_output_tokens_per_call": (
                round(output_tokens / calls, 1) if calls else None),
            "output_share_percent": (
                round(output_tokens / total_tokens * 100, 1) if total_tokens else None),
            "cached_input_share_percent": (
                round(cached_tokens / input_tokens * 100, 1) if input_tokens else None),
            "average_duration_ms": (
                round(duration_ms / calls)
                if calls and duration_observed_calls == calls else None),
            # Agent usage rows do not currently correlate terminal events to
            # token samples, so they cannot support a success-rate claim.
            "success_rate_percent": None,
            "cost_per_call_usd": (
                round(total_cost / sum(sample.calls for sample in priced), 6)
                if total_cost is not None and sum(
                    sample.calls for sample in priced) else None),
        },
        "rows": rows,
    }


def collector_health(service: UsageService,
                     collector_ids: list[str]) -> list[dict[str, Any]]:
    """The durable CollectionState checkpoint for each known collector — so the
    UI can show which providers are polling cleanly, which are failing (with
    the real last_error + consecutive_failures), and which never ran. Uses the
    per-collector `get_collection_state`, so it works on both the in-memory and
    the Ledger-backed store without any list endpoint."""
    out: list[dict[str, Any]] = []
    for cid in collector_ids:
        state = service.store.get_collection_state(cid)
        if state is None:
            out.append({"collector_id": cid, "never_ran": True,
                        "auth_state": "unknown", "consecutive_failures": 0})
        else:
            row = state.to_dict()
            row["never_ran"] = False
            out.append(row)
    return out


async def refresh(service: UsageService,
                  collectors: list[tuple[CollectorProtocol, str]],
                  ) -> dict[str, Any]:
    """Run every registered collector once through the tracked path (durable
    checkpoint + failure bookkeeping), returning a per-collector outcome. A
    collector that reports an expected provider failure does NOT abort the
    others — each is independent (the collector reports failures as warnings /
    an availability event, never by raising)."""
    results: list[dict[str, Any]] = []
    for collector, collector_id in collectors:
        fired = await service.run_collector_tracked(collector, collector_id)
        results.append({"collector_id": collector_id,
                        "runtimes": collector.runtime_ids(),
                        "alerts_fired": len(fired)})
    return {"collectors_run": len(collectors), "results": results}
