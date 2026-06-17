"""Agent validation runner tests.

These tests are hermetic: no LiteLLM, Ollama, AppFlowy, Ledger, or secrets.
"""
from __future__ import annotations

import json

from command_center.cli import agent_validation


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, *_, **__):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers or {}, "json": json or {}})
        body = json or {}
        messages = body.get("messages") or []

        if body.get("tools"):
            return _Response({
                "choices": [{
                    "message": {
                        "content": "",
                        "tool_calls": [{
                            "id": "call-1",
                            "function": {
                                "name": "echo_marker",
                                "arguments": "{\"marker\":\"AGENT-VALIDATION-OK\"}",
                            },
                        }],
                    },
                }],
            })

        joined = "\n".join(str(message.get("content", "")) for message in messages)
        if "MEMORY-INJECTION-OK" in joined:
            content = "MEMORY-INJECTION-OK"
        elif "LONG-MULTI-TURN-OK" in joined:
            content = "LONG-MULTI-TURN-OK"
        else:
            content = "UNKNOWN"

        return _Response({"choices": [{"message": {"content": content, "tool_calls": []}}]})


def test_agent_validation_blocks_without_chat_key(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("LITELLM_BASE_URL=http://localhost:4000/v1\n", encoding="utf-8")
    output = tmp_path / "agent-validation.json"

    result = agent_validation.run_validation(dotenv_path=dotenv, output=output, model="chat")

    assert result["status"] == "blocked"
    assert result["blockers"] == ["missing_env_LITELLM_API_KEY_or_LITELLM_MASTER_KEY"]
    assert result["writes_performed"] is False
    assert result["secrets_printed"] is False
    assert output.exists()


def test_agent_validation_records_pass_without_secret_values(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_validation.httpx, "Client", _FakeClient)
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join([
            "LITELLM_BASE_URL=http://localhost:4000/v1",
            "LITELLM_MASTER_KEY=secret-value-not-written",
        ]) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "agent-validation.json"

    result = agent_validation.run_validation(dotenv_path=dotenv, output=output, model="chat")
    saved = output.read_text(encoding="utf-8")

    assert result["status"] == "pass"
    assert [item["scenario"] for item in result["scenarios"]] == [
        "chat_tool_call_parse",
        "memory_block_recall",
        "long_multi_turn_recall",
        "fresh_conversation_without_memory_abstains",
    ]
    assert all(item["status"] == "pass" for item in result["scenarios"])
    assert result["key_source"] == "LITELLM_MASTER_KEY"
    assert result["writes_performed"] is False
    assert result["secrets_printed"] is False
    assert "secret-value-not-written" not in saved
