"""Pure aggregation for the cockpit's full-stack model usage portfolio.

The existing UsageService remains authoritative for coding-executor quota
windows.  This module covers the other model lanes from their existing,
provider-owned evidence: LiteLLM spend rows for active local Ollama models and
the frontier/local-frontier JSONL ledgers for their explicitly routed calls.

No credentials, prompts, responses, request IDs, or user identifiers enter the
returned shape.  Missing source data is represented by nullable metrics plus a
source-health row supplied by the caller; it is never converted to a fake zero.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping


def _integer(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _latest(current: str | None, candidate: Any) -> str | None:
    value = str(candidate or "").strip()
    if not value:
        return current
    if current is None:
        return value
    try:
        current_time = datetime.fromisoformat(current.replace("Z", "+00:00"))
        candidate_time = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        # Source diagnostics own invalid-time reporting. Preserve the latest
        # valid-looking value here rather than inventing an ordering.
        return current
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    if candidate_time.tzinfo is None:
        candidate_time = candidate_time.replace(tzinfo=timezone.utc)
    return value if candidate_time > current_time else current


def _new_usage() -> dict[str, Any]:
    return {
        "calls": 0,
        "failed_calls": 0,
        "outcome_observed_calls": 0,
        "duration_observed_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "duration_ms": 0,
        "cost_usd": 0.0,
        "last_used_at": None,
        "_recent_activity": [],
        "_purposes": {},
    }


def _local_inventory(models_config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    for role, candidates in (models_config.get("roles") or {}).items():
        for candidate in candidates or []:
            if candidate.get("status", "active") != "active":
                continue
            model_id = str(candidate.get("model") or "").strip()
            if not model_id:
                continue
            row = inventory.setdefault(model_id, {"roles": set(), "aliases": set()})
            row["roles"].add(str(role))
            alias = str(candidate.get("alias") or "").strip()
            if alias:
                row["aliases"].add(alias)
    return inventory


def _normalize_litellm_model(row: Mapping[str, Any]) -> str:
    model = str(row.get("model") or "").strip()
    for prefix in ("ollama_chat/", "ollama/"):
        if model.startswith(prefix):
            return model[len(prefix):]
    return model


def _model_row(*, lane: str, provider: str, model_id: str,
               status: str, roles: Iterable[str] = (),
               aliases: Iterable[str] = (), source_id: str,
               cost_source: str) -> dict[str, Any]:
    row = {
        "lane": lane,
        "provider": provider,
        "model_id": model_id,
        "status": status,
        "roles": sorted(set(roles)),
        "aliases": sorted(set(aliases)),
        "source_id": source_id,
        "cost_source": cost_source,
        **_new_usage(),
    }
    if cost_source == "local_no_provider_charge":
        # Provider API charge is absent; local hardware cost is not measured.
        row["cost_usd"] = None
    return row


def _add_usage(target: dict[str, Any], *, input_tokens: Any,
               output_tokens: Any, total_tokens: Any = None,
               duration_ms: Any = None, cost_usd: Any = None,
               observed_at: Any = None, failed: bool = False,
               purpose: Any = None, status: Any = None,
               outcome_recorded: bool = False) -> None:
    incoming = _integer(input_tokens)
    outgoing = _integer(output_tokens)
    total = (_integer(total_tokens) if isinstance(total_tokens, (int, float))
             else incoming + outgoing)
    target["calls"] += 1
    target["failed_calls"] += int(failed)
    target["outcome_observed_calls"] += int(outcome_recorded)
    target["duration_observed_calls"] += int(
        isinstance(duration_ms, (int, float)))
    target["input_tokens"] += incoming
    target["output_tokens"] += outgoing
    target["total_tokens"] += total
    if target["duration_ms"] is not None:
        target["duration_ms"] += _integer(duration_ms)
    if target["cost_usd"] is not None and isinstance(cost_usd, (int, float)):
        target["cost_usd"] += _number(cost_usd)
    target["last_used_at"] = _latest(target["last_used_at"], observed_at)
    purpose_label = str(purpose or "Unattributed usage").strip()
    purposes = target["_purposes"]
    purposes[purpose_label] = purposes.get(purpose_label, 0) + 1
    target["_recent_activity"].append({
        "purpose": purpose_label,
        "observed_at": str(observed_at or "") or None,
        "input_tokens": incoming,
        "output_tokens": outgoing,
        "total_tokens": total,
        "duration_ms": (_integer(duration_ms)
                        if isinstance(duration_ms, (int, float)) else None),
        "cost_usd": (_number(cost_usd)
                     if isinstance(cost_usd, (int, float)) else None),
        "status": str(status) if outcome_recorded and status is not None else None,
    })


_WINDOW_DAYS = {"day": 1, "week": 7, "month": 30}
_WINDOW_LABELS = {
    "day": "Past 24 hours",
    "week": "Past 7 days",
    "month": "Past 30 days",
    "all": "All retained",
}


def resolve_usage_window(value: str, *,
                         now: datetime | None = None) -> dict[str, Any]:
    """Resolve a UI window to explicit UTC bounds; reject ambiguous values."""
    window_id = value.strip().lower()
    if window_id not in {*_WINDOW_DAYS, "all"}:
        raise ValueError(
            f"unknown usage window {value!r}; expected day, week, month, or all")
    end = now or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    end = end.astimezone(timezone.utc)
    start = (end - timedelta(days=_WINDOW_DAYS[window_id])
             if window_id != "all" else None)
    return {
        "id": window_id,
        "label": _WINDOW_LABELS[window_id],
        "start_at": start.isoformat() if start else None,
        "end_at": end.isoformat(),
    }


def build_model_usage_portfolio(
    *,
    models_config: Mapping[str, Any],
    litellm_rows: Iterable[Mapping[str, Any]],
    litellm_available: bool,
    frontier_rows: Iterable[Mapping[str, Any]],
    local_frontier_rows: Iterable[Mapping[str, Any]],
    sources: Iterable[Mapping[str, Any]],
    window: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one sanitized model-level view across every configured usage lane."""
    inventory = _local_inventory(models_config)
    models: dict[tuple[str, str, str], dict[str, Any]] = {}

    # Always show the active local roster.  If LiteLLM is unavailable its usage
    # fields stay null, clearly distinct from a successfully observed zero.
    for model_id, meta in inventory.items():
        row = _model_row(
            lane="local", provider="Ollama", model_id=model_id,
            status="active", roles=meta["roles"], aliases=meta["aliases"],
            source_id="litellm", cost_source="local_no_provider_charge")
        if not litellm_available:
            for field in ("calls", "failed_calls", "input_tokens", "output_tokens",
                          "total_tokens", "duration_ms", "cost_usd"):
                row[field] = None
        models[("local", "Ollama", model_id)] = row

    if litellm_available:
        for source in litellm_rows:
            model_id = _normalize_litellm_model(source)
            key = ("local", "Ollama", model_id)
            if model_id not in inventory or key not in models:
                continue
            _add_usage(
                models[key], input_tokens=source.get("prompt_tokens"),
                output_tokens=source.get("completion_tokens"),
                total_tokens=source.get("total_tokens"),
                duration_ms=source.get("request_duration_ms"),
                cost_usd=0.0, observed_at=source.get("startTime"),
                failed=str(source.get("status") or "success").lower() not in
                       {"success", "succeeded"},
                purpose=source.get("model_group") or "Local inference",
                status=source.get("status"),
                outcome_recorded=bool(source.get("status")))

    for source in frontier_rows:
        model_id = str(source.get("model_id") or "").strip()
        provider = str(source.get("provider") or "OpenRouter").strip()
        if not model_id:
            continue
        provider_label = "OpenRouter" if provider.lower() == "openrouter" else provider
        key = ("openrouter", provider_label, model_id)
        row = models.setdefault(key, _model_row(
            lane="openrouter", provider=provider_label, model_id=model_id,
            status="observed", source_id="openrouter_ledger",
            cost_source="estimated_from_recorded_tokens"))
        # The frontier ledger records tokens and cost, but not latency. Keep
        # duration unknown instead of presenting an invented zero-millisecond run.
        row["duration_ms"] = None
        _add_usage(
            row, input_tokens=source.get("actual_input_tokens"),
            output_tokens=source.get("actual_output_tokens"),
            cost_usd=source.get("actual_cost_usd"), observed_at=source.get("ts"),
            purpose=source.get("task_class") or "Frontier inference")

    for source in local_frontier_rows:
        model_id = str(source.get("model_id") or "").strip()
        if not model_id:
            continue
        key = ("local", "Local frontier", model_id)
        row = models.setdefault(key, _model_row(
            lane="local", provider="Local frontier", model_id=model_id,
            status="observed", source_id="local_frontier_ledger",
            cost_source="local_no_provider_charge"))
        elapsed = _number(source.get("elapsed_seconds"))
        _add_usage(
            row, input_tokens=source.get("prompt_tokens"),
            output_tokens=source.get("completion_tokens"),
            duration_ms=round(elapsed * 1000), cost_usd=None,
            observed_at=source.get("ts"),
            purpose=source.get("task_class") or "Local frontier inference")

    ordered = sorted(
        models.values(),
        key=lambda row: (row["lane"], row["provider"].lower(), row["model_id"].lower()),
    )
    for row in ordered:
        if isinstance(row["cost_usd"], float):
            row["cost_usd"] = round(row["cost_usd"], 6)
        calls = row["calls"] if isinstance(row["calls"], int) else 0
        total_tokens = row["total_tokens"] if isinstance(row["total_tokens"], int) else 0
        output_tokens = row["output_tokens"] if isinstance(row["output_tokens"], int) else 0
        duration_ms = row["duration_ms"]
        duration_observed = row["duration_observed_calls"]
        if calls and duration_observed != calls:
            row["duration_ms"] = None
            duration_ms = None
        cost_usd = row["cost_usd"]
        failed_calls = row["failed_calls"] if isinstance(row["failed_calls"], int) else 0
        outcome_observed = row["outcome_observed_calls"]
        row["kpis"] = {
            "average_tokens_per_call": (
                round(total_tokens / calls, 1) if calls else None),
            "average_output_tokens_per_call": (
                round(output_tokens / calls, 1) if calls else None),
            "output_share_percent": (
                round(output_tokens / total_tokens * 100, 1) if total_tokens else None),
            "average_duration_ms": (
                round(duration_ms / calls)
                if calls and duration_observed == calls
                and isinstance(duration_ms, int) and duration_ms > 0 else None),
            "success_rate_percent": (
                round((calls - failed_calls) / calls * 100, 1)
                if calls and outcome_observed == calls else None),
            "cost_per_call_usd": (
                round(cost_usd / calls, 6)
                if calls and row["lane"] == "openrouter"
                and isinstance(cost_usd, (int, float)) else None),
        }
        purposes = row.pop("_purposes")
        row["purpose_breakdown"] = [
            {"purpose": purpose, "calls": count,
             "share_percent": round(count / calls * 100, 1) if calls else 0.0}
            for purpose, count in sorted(
                purposes.items(), key=lambda item: (-item[1], item[0]))
        ]
        recent = row.pop("_recent_activity")
        recent.sort(key=lambda item: item["observed_at"] or "", reverse=True)
        row["recent_activity"] = recent[:6]

    source_rows = []
    for source in sources:
        public_source = dict(source)
        public_source["included_row_count"] = sum(
            row["calls"] for row in ordered
            if row["source_id"] == source.get("source_id")
            and isinstance(row["calls"], int)
        )
        source_rows.append(public_source)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": dict(window or resolve_usage_window("all")),
        "models": ordered,
        "sources": source_rows,
    }
