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
from .service import UsageService


def usage_overview(service: UsageService) -> list[dict[str, Any]]:
    """One RuntimeUsageStatus per runtime the store knows about — the top-level
    Usage & Limits list (availability + every live bucket + rolled usage +
    honest staleness)."""
    return [s.to_dict() for s in service.all_statuses()]


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
                limit: int = 10) -> dict[str, Any]:
    """"What used the most?" for one runtime, from RECORDED driver facts —
    ranked attribution rows along a dimension (mission/repo/session/…) by a
    metric (total_tokens/cost/…). Samples missing the dimension roll into an
    explicit "(unattributed)" bucket, never dropped."""
    samples = service.store.samples_since(runtime_id)
    rows = rank_by(samples, dimension=dimension, metric=metric, limit=limit)
    return {
        "runtime_id": runtime_id, "dimension": dimension, "metric": metric,
        "rows": [{"key": r.key, "metric_value": r.metric_value,
                  "share": r.share, "sample_count": r.sample_count}
                 for r in rows],
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
