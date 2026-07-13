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


# ---- cache_slot mapping ---------------------------------------------------------------------

def test_cache_slot_is_deterministic_and_in_bounds():
    for kv_slots in (1, 2, 16):
        for conversation_id in ("c1", "acceptance-gate-test", "a very long conversation id"):
            slot = lfc._cache_slot_for(conversation_id, kv_slots)
            assert 0 <= slot < kv_slots
            # same input -> same output, every time (KV cache persists across engine
            # restarts on colibri's side; the mapping must be stable to actually use that)
            assert slot == lfc._cache_slot_for(conversation_id, kv_slots)


def test_cache_slot_does_not_depend_on_process_hash_randomization():
    """Python's builtin hash() is PYTHONHASHSEED-randomized per process — using it here would
    map the same conversation to a different slot after every restart, defeating colibri's own
    KV-cache-persists-across-restarts feature. sha256 must be used instead."""
    import os
    import subprocess
    import sys
    script = (
        "from command_center.channels.local_frontier_client import _cache_slot_for; "
        "print(_cache_slot_for('a-stable-conversation-id', 16))"
    )
    results = set()
    for seed in ("1", "2", "3"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        proc = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, env=env, check=True)
        results.add(proc.stdout.strip())
    assert len(results) == 1, f"cache_slot changed across PYTHONHASHSEED values: {results}"


def test_different_conversations_can_map_to_different_slots():
    """Not a strict requirement (small kv_slots means collisions are expected and fine — see
    _cache_slot_for's docstring), but with kv_slots=16 a handful of distinct conversation ids
    landing on the exact same slot would suggest the hash isn't actually varying by input."""
    slots = {lfc._cache_slot_for(f"conversation-{i}", 16) for i in range(20)}
    assert len(slots) > 1


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
        # 50ms clears Windows' ~15.6ms monotonic granularity (10ms could round to 0 there).
        await asyncio.sleep(0.05)
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
    # Every request carries a cache_slot — without this, unrelated conversations silently
    # share KV state (observed live 2026-07-11/12: prefill cost grew 13 -> 163 tokens as
    # earlier, unrelated turns bled into the shared default slot 0).
    assert 0 <= seen_bodies[0]["cache_slot"] < 2   # kv_slots=2 in _providers_config()
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
