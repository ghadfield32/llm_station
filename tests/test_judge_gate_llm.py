"""judge_gate._llm honesty contract.

_llm must report WHY a model call failed, distinctly:
  - finish_reason == "length"  -> truncation error (not "bad JSON")
  - unparseable content        -> non-JSON error, with finish_reason in the message
  - upstream non-200           -> LiteLLM error
  - valid JSON                 -> parsed dict
The model HTTP call is faked, so this is hermetic — no LiteLLM/Ollama needed.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

APP = Path(__file__).resolve().parents[1] / "services" / "judge_gate" / "app.py"


class _FakeResp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    """Stand-in for httpx.AsyncClient(...) used as an async context manager."""
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *a, **k):
        return self._resp


@pytest.fixture
def judge(monkeypatch):
    import os
    os.environ["STANDARDS_CONFIG"] = ""        # skip standards file read; irrelevant here
    spec = importlib.util.spec_from_file_location("judge_app_under_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["judge_app_under_test"] = mod
    spec.loader.exec_module(mod)
    mod.JUDGE_GATE_KEY = "test-key"            # _llm refuses to run without a key

    def use(resp):
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: _FakeClient(resp))
    return mod, use


def _chat(content, finish, completion_tokens=10):
    return {"choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"completion_tokens": completion_tokens, "prompt_tokens": 100}}


def test_valid_json_parsed(judge):
    mod, use = judge
    use(_FakeResp(200, _chat('{"healthy": true, "summary": "ok"}', "stop")))
    out = asyncio.run(mod._llm("triage", "sys", "user"))
    assert out == {"healthy": True, "summary": "ok"}


def test_truncation_reported_as_truncation_not_bad_json(judge):
    mod, use = judge
    # Length-capped: incomplete JSON AND finish_reason="length".
    use(_FakeResp(200, _chat('{"healthy": false, "findings": ["a", "b', "length", 600)))
    with pytest.raises(HTTPException) as ei:
        asyncio.run(mod._llm("triage", "sys", "user"))
    assert ei.value.status_code == 502
    assert "truncated" in ei.value.detail
    assert "max_tokens=600" in ei.value.detail
    assert "non-JSON" not in ei.value.detail          # must NOT mislabel it


def test_non_json_reports_finish_reason(judge):
    mod, use = judge
    use(_FakeResp(200, _chat("Sure! Here is the verdict: all good.", "stop")))
    with pytest.raises(HTTPException) as ei:
        asyncio.run(mod._llm("triage", "sys", "user"))
    assert ei.value.status_code == 502
    assert "non-JSON" in ei.value.detail
    assert "finish_reason=stop" in ei.value.detail


def test_upstream_error_surfaced(judge):
    mod, use = judge
    use(_FakeResp(500, payload=None, text="ollama unreachable"))
    with pytest.raises(HTTPException) as ei:
        asyncio.run(mod._llm("triage", "sys", "user"))
    assert ei.value.status_code == 502
    assert "LiteLLM error 500" in ei.value.detail
