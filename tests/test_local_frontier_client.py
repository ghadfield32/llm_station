"""The local-frontier LIVE call path: lane-enabled gate, host allowlist, and the actual HTTP
call — all hermetic (httpx transport mocked, no key, no network). The shipped config stays
disabled, same pattern as test_frontier_client.py. Unlike that suite there is no cost/budget
here (no $ price for a local engine) — the ledger records latency + tokens/sec instead.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from command_center.channels import local_frontier_client as lfc
from command_center.schemas.contracts import LocalFrontierProvidersConfig


def _providers_config(**over_enabled):
    raw = {
        "schema_version": "command-center.local-frontier-providers.v1",
        "enabled": True,
        "providers": {"colibri": {"base_url_env": "LOCAL_FRONTIER_COLIBRI_BASE_URL"}},
        "models": {
            "glm-5.2-colibri": {
                "provider": "colibri",
                "context_tokens": 8192,
                "disk_footprint_gb": 370,
                "expected_tokens_per_second": {"low": 0.05, "high": 1.06, "source": "test"},
            }
        },
    }
    raw.update(over_enabled)
    return LocalFrontierProvidersConfig.model_validate(raw)


def _disabled_config():
    return _providers_config(enabled=False)


def _mock_transport(payload: dict, status_code: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)
    return httpx.MockTransport(handler)


# ---- gates --------------------------------------------------------------------------------

def test_completion_refuses_disabled_lane(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_FRONTIER_USAGE_LEDGER", str(tmp_path / "usage.jsonl"))
    monkeypatch.setattr(lfc, "load_providers", lambda: _disabled_config())

    async def go():
        async with httpx.AsyncClient(transport=_mock_transport({})) as http:
            await lfc.local_frontier_chat_completion(
                model_id="glm-5.2-colibri", conversation_id="c1",
                messages=[{"role": "user", "content": "hi"}], http=http)

    with pytest.raises(lfc.LocalFrontierGateError, match="disabled"):
        asyncio.run(go())


def test_completion_refuses_unknown_model(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_FRONTIER_USAGE_LEDGER", str(tmp_path / "usage.jsonl"))
    monkeypatch.setattr(lfc, "load_providers", lambda: _providers_config())

    async def go():
        async with httpx.AsyncClient(transport=_mock_transport({})) as http:
            await lfc.local_frontier_chat_completion(
                model_id="not-a-real-model", conversation_id="c1",
                messages=[{"role": "user", "content": "hi"}], http=http)

    with pytest.raises(lfc.LocalFrontierGateError, match="not in local-frontier"):
        asyncio.run(go())


def test_completion_refuses_when_base_url_env_unset(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_FRONTIER_USAGE_LEDGER", str(tmp_path / "usage.jsonl"))
    monkeypatch.setattr(lfc, "load_providers", lambda: _providers_config())
    # monkeypatch.delenv only clears the PROCESS env — _env() also merges the real .env FILE
    # (this developer's may legitimately carry LOCAL_FRONTIER_COLIBRI_BASE_URL from a real
    # Phase 2 run), so isolate by replacing _env() itself, same pattern
    # test_forbidden_providers_egress.py uses for OPENROUTER_API_KEY isolation.
    monkeypatch.setattr(lfc, "_env", lambda: {})

    async def go():
        async with httpx.AsyncClient(transport=_mock_transport({})) as http:
            await lfc.local_frontier_chat_completion(
                model_id="glm-5.2-colibri", conversation_id="c1",
                messages=[{"role": "user", "content": "hi"}], http=http)

    with pytest.raises(lfc.LocalFrontierGateError, match="is not set"):
        asyncio.run(go())


def test_completion_refuses_non_local_base_url(tmp_path, monkeypatch):
    """Defense in depth — re-validated at call time even though check_forbidden_providers
    already scans .env/process env statically (the env var could change between scans)."""
    monkeypatch.setenv("LOCAL_FRONTIER_USAGE_LEDGER", str(tmp_path / "usage.jsonl"))
    monkeypatch.setattr(lfc, "load_providers", lambda: _providers_config())
    monkeypatch.setenv("LOCAL_FRONTIER_COLIBRI_BASE_URL", "http://evil.example.com:8000/v1")

    async def go():
        async with httpx.AsyncClient(transport=_mock_transport({})) as http:
            await lfc.local_frontier_chat_completion(
                model_id="glm-5.2-colibri", conversation_id="c1",
                messages=[{"role": "user", "content": "hi"}], http=http)

    with pytest.raises(ValueError, match="not loopback"):
        asyncio.run(go())


# ---- live call (mocked transport) ----------------------------------------------------------

def test_completion_live_call_never_sends_tools_and_records_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_FRONTIER_USAGE_LEDGER", str(tmp_path / "usage.jsonl"))
    monkeypatch.setattr(lfc, "load_providers", lambda: _providers_config())
    monkeypatch.setenv("LOCAL_FRONTIER_COLIBRI_BASE_URL", "http://127.0.0.1:8000/v1")
    payload = {
        "choices": [{"message": {"role": "assistant", "content": "hello from colibri"}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10},
    }
    seen_bodies = []

    async def handler(request: httpx.Request) -> httpx.Response:
        import json
        # MockTransport can otherwise complete faster than time.monotonic()'s resolution
        # (elapsed_s==0.0 would make tokens_per_second silently None) — a real (slow) call
        # never has this problem; a short real sleep here is more honest than patching the
        # global clock, which would also break asyncio's own internal scheduling.
        await asyncio.sleep(0.01)
        seen_bodies.append(json.loads(request.content))
        return httpx.Response(200, json=payload)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await lfc.local_frontier_chat_completion(
                model_id="glm-5.2-colibri", conversation_id="c1",
                messages=[{"role": "user", "content": "hi"}], http=http)

    msg = asyncio.run(go())
    assert msg["content"] == "hello from colibri"
    assert "tools" not in seen_bodies[0]     # never sends a tools schema
    # REQUIRED, not optional — an uncapped reply can outrun queue_timeout_seconds itself at
    # colibri-class throughput (regression: a real cockpit turn without this hit exactly that
    # 2026-07-11, surfacing as an opaque transport error instead of a clean timeout).
    assert seen_bodies[0]["max_tokens"] == 200
    assert msg["_usage"]["completion_tokens"] == 10
    assert msg["_usage"]["tokens_per_second"] is not None
    assert "actual_cost_usd" not in msg["_usage"]   # no $ cost for a local engine

    ledger = (tmp_path / "usage.jsonl").read_text(encoding="utf-8").strip()
    assert '"conversation_id": "c1"' in ledger
    assert "tokens_per_second" in ledger


def test_completion_raises_on_unreachable_server(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_FRONTIER_USAGE_LEDGER", str(tmp_path / "usage.jsonl"))
    monkeypatch.setattr(lfc, "load_providers", lambda: _providers_config())
    monkeypatch.setenv("LOCAL_FRONTIER_COLIBRI_BASE_URL", "http://127.0.0.1:8000/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await lfc.local_frontier_chat_completion(
                model_id="glm-5.2-colibri", conversation_id="c1",
                messages=[{"role": "user", "content": "hi"}], http=http)

    with pytest.raises(lfc.LocalFrontierGateError, match="could not reach"):
        asyncio.run(go())


# ---- available_local_frontier_models ---------------------------------------------------

def test_available_models_unselectable_when_lane_disabled(monkeypatch):
    monkeypatch.setattr(lfc, "load_providers", lambda: _disabled_config())
    rows = {r["model_id"]: r for r in lfc.available_local_frontier_models()}
    assert rows["glm-5.2-colibri"]["selectable"] is False
    assert rows["glm-5.2-colibri"]["lane_enabled"] is False
    assert rows["glm-5.2-colibri"]["health"] == "not_configured"


def test_health_probe_strips_v1_suffix_before_appending_health(monkeypatch):
    """Regression test: /health lives at the server ROOT (e.g. http://127.0.0.1:8000/health),
    not under /v1 like every other route — a real colibri server returns 401 (not 404) for an
    unrecognized /v1/health path, which silently looked like a broken server rather than a
    client bug until caught against the live Phase 2 server."""
    seen_urls = []

    def fake_get(url, timeout):
        seen_urls.append(url)
        class R:
            status_code = 200
        return R()

    monkeypatch.setattr(lfc.httpx, "get", fake_get)
    result = lfc._health("http://127.0.0.1:8000/v1")
    assert result == "ready"
    assert seen_urls == ["http://127.0.0.1:8000/health"]


def test_available_models_degrades_to_empty_list_on_config_error(monkeypatch):
    def boom():
        raise lfc.LocalFrontierGateError("config missing")
    monkeypatch.setattr(lfc, "load_providers", boom)
    assert lfc.available_local_frontier_models() == []
