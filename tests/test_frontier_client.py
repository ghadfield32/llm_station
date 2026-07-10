"""The frontier-router LIVE call path: secret-scan redaction, running-total budget
enforcement, and the actual HTTP call — all hermetic (httpx transport mocked, no
key, no network). The shipped config stays disabled/unkeyed; tests that need the
"allowed" path monkeypatch the loaders, same pattern as test_frontier_router_eval.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from command_center.channels import frontier_client as fc
from command_center.improvement import frontier_router_eval as fre
from command_center.schemas import FrontierRouterBudgetsConfig


def _enabled_budgets(**over_default):
    default = {
        "enabled": True, "monthly_cap_usd": 10.0, "per_run_cap_usd": 1.0,
        "per_request_cap_usd": 0.25, "require_redaction": True,
        "require_human_approval_for_live_repo_context": True, "log_token_usage": True,
        "log_cost_estimate": True, "fail_on_missing_usage": True,
    }
    default.update(over_default)
    return FrontierRouterBudgetsConfig.model_validate({
        "schema_version": "command-center.frontier-router-budgets.v1",
        "default": default,
        "allowed_task_classes": ["frontier_reference_eval", "cockpit_chat_manual_select"],
        "blocked_payloads": ["secrets", "raw_env_files"],
    })


# ---- secret scan ------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "here is my key sk-abcdefghijklmnopqrstuvwx",
    "-----BEGIN RSA PRIVATE KEY-----\nMIIB...",
    "OPENAI_API_KEY=sk-should-not-leave-the-machine",
    "token ghp_abcdefghijklmnopqrstuvwxyz012345",
    "AKIAABCDEFGHIJKLMNOP",
])
def test_scan_for_secrets_catches_common_patterns(text):
    assert fc.scan_for_secrets(text) is not None


def test_scan_for_secrets_passes_plain_text():
    assert fc.scan_for_secrets("what's the weather like for the parade planning?") is None


# ---- usage ledger + running totals ------------------------------------------

def test_running_totals_sum_actual_cost_by_month_and_conversation(tmp_path, monkeypatch):
    """month_total resets each calendar month (monthly_cap_usd); convo_total is a
    LIFETIME sum for that conversation id (per_run_cap_usd never resets — a
    long-lived chat conversation cannot outrun its cap by waiting for a new month)."""
    ledger = tmp_path / "usage.jsonl"
    monkeypatch.setenv("FRONTIER_ROUTER_USAGE_LEDGER", str(ledger))
    fc._append_ledger({"ts": "2026-07-10T00:00:00+00:00", "conversation_id": "c1",
                       "actual_cost_usd": 0.10})
    fc._append_ledger({"ts": "2026-07-09T00:00:00+00:00", "conversation_id": "c1",
                       "actual_cost_usd": 0.20})
    fc._append_ledger({"ts": "2026-06-01T00:00:00+00:00", "conversation_id": "c1",
                       "actual_cost_usd": 5.00})       # prior month, still counts for c1
    fc._append_ledger({"ts": "2026-07-10T00:00:00+00:00", "conversation_id": "c2",
                       "actual_cost_usd": 0.05})
    from datetime import datetime, timezone
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    month_total, convo_total = fc.running_totals("c1", now=now)
    assert month_total == pytest.approx(0.35)   # c1 (0.10+0.20) + c2 (0.05), same month
    assert convo_total == pytest.approx(5.30)    # c1 lifetime: 0.10+0.20+5.00


def test_running_totals_ignore_corrupt_lines(tmp_path, monkeypatch):
    ledger = tmp_path / "usage.jsonl"
    monkeypatch.setenv("FRONTIER_ROUTER_USAGE_LEDGER", str(ledger))
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("{not json\n", encoding="utf-8")
    month_total, convo_total = fc.running_totals("c1")
    assert month_total == 0.0 and convo_total == 0.0


# ---- frontier_chat_completion (mocked transport) -----------------------------

def _mock_transport(payload: dict, status_code: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)
    return httpx.MockTransport(handler)


def _disabled_budgets():
    """Explicitly disabled — self-contained, not a read of the live repo config
    (whose default.enabled is a genuine, changeable operator decision)."""
    return _enabled_budgets(enabled=False)


def test_frontier_completion_refuses_disabled_lane(tmp_path, monkeypatch):
    monkeypatch.setenv("FRONTIER_ROUTER_USAGE_LEDGER", str(tmp_path / "usage.jsonl"))
    monkeypatch.setattr(fc, "load_budgets", lambda: _disabled_budgets())

    async def go():
        async with httpx.AsyncClient(transport=_mock_transport({})) as http:
            await fc.frontier_chat_completion(
                model_id="glm-5.2", conversation_id="c1",
                messages=[{"role": "user", "content": "hi"}], http=http)

    with pytest.raises(fre.RouterDisabledError):
        asyncio.run(go())


def test_frontier_completion_refuses_secret_like_message(tmp_path, monkeypatch):
    monkeypatch.setenv("FRONTIER_ROUTER_USAGE_LEDGER", str(tmp_path / "usage.jsonl"))

    async def go():
        async with httpx.AsyncClient(transport=_mock_transport({})) as http:
            await fc.frontier_chat_completion(
                model_id="glm-5.2", conversation_id="c1",
                messages=[{"role": "user",
                          "content": "OPENAI_API_KEY=sk-leaktest12345"}],
                http=http)

    with pytest.raises(fc.SecretLeakError):
        asyncio.run(go())


def test_frontier_completion_live_call_records_ledger_and_usage(
        tmp_path, monkeypatch):
    monkeypatch.setenv("FRONTIER_ROUTER_USAGE_LEDGER", str(tmp_path / "usage.jsonl"))
    monkeypatch.setattr(fc, "load_budgets", lambda: _enabled_budgets())
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    payload = {
        "choices": [{"message": {"role": "assistant", "content": "hello there"}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 10},
    }

    async def go():
        async with httpx.AsyncClient(transport=_mock_transport(payload)) as http:
            return await fc.frontier_chat_completion(
                model_id="glm-5.2", conversation_id="c1",
                messages=[{"role": "user", "content": "hi"}], http=http)

    msg = asyncio.run(go())
    assert msg["content"] == "hello there"
    assert msg["_usage"]["prompt_tokens"] == 50
    assert msg["_usage"]["actual_cost_usd"] > 0
    rows = fc._ledger_rows()
    assert len(rows) == 1 and rows[0]["conversation_id"] == "c1"
    assert rows[0]["actual_cost_usd"] > 0


def test_frontier_completion_fails_loud_on_missing_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("FRONTIER_ROUTER_USAGE_LEDGER", str(tmp_path / "usage.jsonl"))
    monkeypatch.setattr(fc, "load_budgets", lambda: _enabled_budgets())
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    payload = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}  # no usage

    async def go():
        async with httpx.AsyncClient(transport=_mock_transport(payload)) as http:
            await fc.frontier_chat_completion(
                model_id="glm-5.2", conversation_id="c1",
                messages=[{"role": "user", "content": "hi"}], http=http)

    with pytest.raises(fre.RouterGateError, match="no usage block"):
        asyncio.run(go())
    assert fc._ledger_rows() == []      # never recorded an unmeasured spend


def test_frontier_completion_enforces_conversation_cap(tmp_path, monkeypatch):
    """The running-total check must catch a conversation approaching its cap even
    though EACH individual call is comfortably under per_request_cap_usd — seed the
    ledger with prior spend for this conversation rather than shrinking the caps
    (per_request_cap_usd <= per_run_cap_usd is a schema invariant)."""
    monkeypatch.setenv("FRONTIER_ROUTER_USAGE_LEDGER", str(tmp_path / "usage.jsonl"))
    # both caps comfortably above one call's ~$0.0033 estimate (so preflight's
    # OWN per-request check passes) — the seeded conversation total is what
    # pushes this call over per_run_cap_usd
    monkeypatch.setattr(fc, "load_budgets",
                        lambda: _enabled_budgets(
                            per_run_cap_usd=0.01, per_request_cap_usd=0.01))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    fc._append_ledger({"ts": "2026-07-10T00:00:00+00:00", "conversation_id": "c1",
                       "actual_cost_usd": 0.008})

    async def go():
        async with httpx.AsyncClient(transport=_mock_transport({})) as http:
            await fc.frontier_chat_completion(
                model_id="glm-5.2", conversation_id="c1",
                messages=[{"role": "user", "content": "hi"}], http=http)

    with pytest.raises(fc.FrontierBudgetExceededError, match="per-conversation cap"):
        asyncio.run(go())


def test_available_frontier_models_reports_top3(monkeypatch):
    rows = {r["model_id"]: r for r in fc.available_frontier_models()}
    for model_id in ("glm-5.2", "deepseek-v4-pro", "kimi-k2.6"):
        assert model_id in rows
        assert rows[model_id]["estimated_cost_per_turn_usd"] > 0


def test_available_frontier_models_unselectable_when_lane_disabled(monkeypatch):
    monkeypatch.setattr(fc, "load_budgets", lambda: _disabled_budgets())
    rows = {r["model_id"]: r for r in fc.available_frontier_models()}
    assert all(not r["selectable"] for r in rows.values())
    assert all(not r["lane_enabled"] for r in rows.values())


def test_available_frontier_models_selectable_when_enabled_and_keyed(monkeypatch):
    monkeypatch.setattr(fc, "load_budgets", lambda: _enabled_budgets())
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ZAI_API_KEY", "test-key-not-real")
    rows = {r["model_id"]: r for r in fc.available_frontier_models()}
    assert rows["glm-5.2"]["selectable"] is True
