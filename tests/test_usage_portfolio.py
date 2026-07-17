"""KPI coverage for the full-stack Usage & Limits model portfolio."""
from datetime import datetime, timezone

from command_center.usage.portfolio import (
    build_model_usage_portfolio,
    resolve_usage_window,
)


MODELS = {
    "roles": {
        "chat": [{"alias": "chat-qwen", "model": "qwen3:30b"}],
        "planner": [
            {"alias": "planner-qwen", "model": "qwen3:30b"},
            {"alias": "planner-devstral", "model": "devstral:24b"},
        ],
        "coder": [{"alias": "retired", "model": "old:7b", "status": "scout"}],
    },
}


def _build(**overrides):
    args = {
        "models_config": MODELS,
        "litellm_rows": [],
        "litellm_available": True,
        "frontier_rows": [],
        "local_frontier_rows": [],
        "sources": [],
    }
    args.update(overrides)
    return build_model_usage_portfolio(**args)


def test_active_local_models_are_model_level_and_stale_cloud_rows_are_excluded():
    out = _build(litellm_rows=[
        {"model": "ollama_chat/qwen3:30b", "model_group": "chat",
         "prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14,
         "request_duration_ms": 250, "spend": 0, "status": "success",
         "startTime": "2026-07-16T10:00:00Z"},
        {"model": "gpt-4o", "prompt_tokens": 99, "completion_tokens": 99},
    ])
    rows = {row["model_id"]: row for row in out["models"]}
    assert set(rows) == {"qwen3:30b", "devstral:24b"}
    assert rows["qwen3:30b"]["roles"] == ["chat", "planner"]
    assert rows["qwen3:30b"]["aliases"] == ["chat-qwen", "planner-qwen"]
    assert rows["qwen3:30b"]["total_tokens"] == 14
    assert rows["qwen3:30b"]["kpis"]["average_tokens_per_call"] == 14.0
    assert rows["qwen3:30b"]["kpis"]["success_rate_percent"] == 100.0
    assert rows["qwen3:30b"]["purpose_breakdown"] == [
        {"purpose": "chat", "calls": 1, "share_percent": 100.0}]
    assert rows["qwen3:30b"]["recent_activity"][0]["purpose"] == "chat"
    assert rows["devstral:24b"]["calls"] == 0
    assert out["sources"] == []


def test_openrouter_and_local_frontier_ledgers_join_the_same_portfolio():
    out = _build(
        frontier_rows=[
            {"provider": "openrouter", "model_id": "glm-5.2",
             "actual_input_tokens": 12, "actual_output_tokens": 8,
             "actual_cost_usd": 0.0012, "ts": "2026-07-10T12:00:00Z"},
            {"provider": "openrouter", "model_id": "glm-5.2",
             "actual_input_tokens": 4, "actual_output_tokens": 6,
             "actual_cost_usd": 0.0008, "ts": "2026-07-10T13:00:00Z"},
        ],
        local_frontier_rows=[
            {"model_id": "glm-5.2-colibri", "prompt_tokens": 3,
             "completion_tokens": 2, "elapsed_seconds": 5.5,
             "ts": "2026-07-11T12:00:00Z"},
        ],
    )
    by_model = {row["model_id"]: row for row in out["models"]}
    assert by_model["glm-5.2"]["provider"] == "OpenRouter"
    assert by_model["glm-5.2"]["calls"] == 2
    assert by_model["glm-5.2"]["total_tokens"] == 30
    assert by_model["glm-5.2"]["cost_usd"] == 0.002
    assert by_model["glm-5.2"]["duration_ms"] is None
    assert by_model["glm-5.2"]["kpis"]["cost_per_call_usd"] == 0.001
    assert by_model["glm-5.2"]["kpis"]["success_rate_percent"] is None
    assert by_model["glm-5.2"]["outcome_observed_calls"] == 0
    assert (
        by_model["glm-5.2"]["recent_activity"][0]["purpose"]
        == "Frontier inference"
    )
    assert by_model["glm-5.2-colibri"]["provider"] == "Local frontier"
    assert by_model["glm-5.2-colibri"]["duration_ms"] == 5500
    assert by_model["glm-5.2-colibri"]["cost_usd"] is None
    assert by_model["glm-5.2-colibri"]["recent_activity"][0]["cost_usd"] is None
    assert by_model["glm-5.2-colibri"]["kpis"]["success_rate_percent"] is None


def test_source_counts_distinguish_loaded_rows_from_displayed_models():
    out = _build(
        litellm_rows=[
            {"model": "ollama_chat/qwen3:30b", "prompt_tokens": 3,
             "completion_tokens": 2, "total_tokens": 5, "status": "success"},
            {"model": "unconfigured:latest", "prompt_tokens": 9,
             "completion_tokens": 1, "total_tokens": 10, "status": "success"},
        ],
        sources=[{"source_id": "litellm", "row_count": 2}],
    )
    assert out["sources"][0]["row_count"] == 2
    assert out["sources"][0]["included_row_count"] == 1


def test_partial_duration_coverage_is_not_averaged_as_if_complete():
    out = _build(litellm_rows=[
        {"model": "qwen3:30b", "prompt_tokens": 3, "completion_tokens": 2,
         "total_tokens": 5, "request_duration_ms": 100, "status": "success"},
        {"model": "qwen3:30b", "prompt_tokens": 4, "completion_tokens": 1,
         "total_tokens": 5, "status": "success"},
    ])
    row = next(model for model in out["models"] if model["model_id"] == "qwen3:30b")
    assert row["duration_ms"] is None
    assert row["kpis"]["average_duration_ms"] is None


def test_latest_model_use_compares_timestamps_not_iso_spelling():
    out = _build(litellm_rows=[
        {"model": "qwen3:30b", "prompt_tokens": 1, "completion_tokens": 1,
         "total_tokens": 2, "status": "success",
         "startTime": "2026-07-16T10:00:00+02:00"},
        {"model": "qwen3:30b", "prompt_tokens": 1, "completion_tokens": 1,
         "total_tokens": 2, "status": "success",
         "startTime": "2026-07-16T09:00:00Z"},
    ])
    row = next(model for model in out["models"] if model["model_id"] == "qwen3:30b")
    assert row["last_used_at"] == "2026-07-16T09:00:00Z"


def test_unavailable_litellm_is_unknown_not_fabricated_zero():
    out = _build(litellm_available=False)
    local = next(row for row in out["models"] if row["model_id"] == "qwen3:30b")
    assert local["calls"] is None
    assert local["total_tokens"] is None
    assert local["cost_usd"] is None
    assert local["kpis"]["average_tokens_per_call"] is None
    assert local["recent_activity"] == []


def test_usage_windows_are_explicit_rolling_utc_bounds():
    now = datetime(2026, 7, 16, 18, 0, tzinfo=timezone.utc)
    week = resolve_usage_window("week", now=now)
    assert week == {
        "id": "week",
        "label": "Past 7 days",
        "start_at": "2026-07-09T18:00:00+00:00",
        "end_at": "2026-07-16T18:00:00+00:00",
    }
    assert resolve_usage_window("all", now=now)["start_at"] is None
