"""Live validation for the Growth OS gateway agent surface.

This is intentionally read-only. It validates that the local chat model path can
handle the behaviors the gateway relies on: parsed tool calls, durable memory
blocks, long multi-turn context, and no raw tool-call markup leakage. It does not
call Growth OS tools, mutate AppFlowy, write repos, or retain prompts beyond the
redacted evidence file.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx
import yaml

from command_center.schemas import AgentValidationConfig, AutonomyConfig

ROOT = Path(__file__).resolve().parents[3]
SCENARIO_NAMES = [
    "chat_tool_call_parse",
    "memory_block_recall",
    "long_multi_turn_recall",
    "fresh_conversation_without_memory_abstains",
]


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _merged_env(dotenv_path: Path) -> dict[str, str]:
    return {**_read_dotenv(dotenv_path), **os.environ}


def _chat_base(env: dict[str, str]) -> str:
    if env.get("LITELLM_BASE_URL"):
        return env["LITELLM_BASE_URL"].rstrip("/")
    return env.get("LITELLM_URL", "http://localhost:4000").rstrip("/") + "/v1"


def _chat_key(env: dict[str, str]) -> tuple[str, str]:
    for name in ("LITELLM_API_KEY", "LITELLM_MASTER_KEY"):
        value = env.get(name, "")
        if value:
            return name, value
    return "", ""


def _load_validation_config(config_path: Path) -> AgentValidationConfig:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return AutonomyConfig.model_validate(raw).agent_validation


def _complete(
    client: httpx.Client,
    *,
    base: str,
    key: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 512,
) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if tools is not None:
        body["tools"] = tools
    response = client.post(f"{base}/chat/completions", headers=headers, json=body)
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:200]}
    return response.status_code, payload


def _message(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices") or [{}]
    return choices[0].get("message") or {}


def _scenario(
    results: list[dict[str, Any]],
    name: str,
    fn,
) -> None:
    try:
        detail = fn()
        results.append({"scenario": name, "status": "pass", **detail})
    except Exception as exc:  # noqa: BLE001 - evidence runner reports exact blocker
        results.append({
            "scenario": name,
            "status": "fail",
            "error_type": type(exc).__name__,
            "error": str(exc),
        })


def run_validation(
    *,
    dotenv_path: Path,
    output: Path,
    config_path: Path = ROOT / "configs" / "autonomy.yaml",
    model: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    validation_cfg = _load_validation_config(config_path)
    selected_model = model or validation_cfg.model_alias
    selected_max_tokens = (
        max_tokens if max_tokens is not None else validation_cfg.max_tokens
    )
    max_tokens_source = "cli_argument" if max_tokens is not None else validation_cfg.max_tokens_source
    env = _merged_env(dotenv_path)
    base = _chat_base(env)
    key_name, key = _chat_key(env)
    results: list[dict[str, Any]] = []

    if list(validation_cfg.required_scenarios) != SCENARIO_NAMES:
        result = {
            "status": "blocked",
            "blockers": ["agent_validation_required_scenarios_do_not_match_implemented_order"],
            "model": selected_model,
            "base_url": base,
            "key_source": "",
            "max_tokens": selected_max_tokens,
            "max_tokens_source": max_tokens_source,
            "required_scenarios": list(validation_cfg.required_scenarios),
            "scenarios": [],
            "writes_performed": False,
            "secrets_printed": False,
        }
        _write_json(output, result)
        return result

    if selected_max_tokens <= 0:
        result = {
            "status": "blocked",
            "blockers": ["agent_validation_max_tokens_must_be_positive"],
            "model": selected_model,
            "base_url": base,
            "key_source": "",
            "max_tokens": selected_max_tokens,
            "max_tokens_source": max_tokens_source,
            "required_scenarios": list(validation_cfg.required_scenarios),
            "scenarios": [],
            "writes_performed": False,
            "secrets_printed": False,
        }
        _write_json(output, result)
        return result

    if not key:
        result = {
            "status": "blocked",
            "blockers": ["missing_env_LITELLM_API_KEY_or_LITELLM_MASTER_KEY"],
            "model": selected_model,
            "base_url": base,
            "key_source": "",
            "max_tokens": selected_max_tokens,
            "max_tokens_source": max_tokens_source,
            "required_scenarios": list(validation_cfg.required_scenarios),
            "scenarios": [],
            "writes_performed": False,
            "secrets_printed": False,
        }
        _write_json(output, result)
        return result

    marker = "AGENT-VALIDATION-OK"
    long_marker = "LONG-MULTI-TURN-OK"
    memory_marker = "MEMORY-INJECTION-OK"
    tools = [{
        "type": "function",
        "function": {
            "name": "echo_marker",
            "description": "Return the marker exactly.",
            "parameters": {
                "type": "object",
                "properties": {"marker": {"type": "string"}},
                "required": ["marker"],
            },
        },
    }]

    with httpx.Client(timeout=180) as client:

        def tool_call_parse() -> dict[str, Any]:
            status, payload = _complete(
                client,
                base=base,
                key=key,
                model=selected_model,
                messages=[{"role": "user", "content": f"Use echo_marker with marker {marker}."}],
                tools=tools,
                max_tokens=selected_max_tokens,
            )
            if status != 200:
                raise RuntimeError(f"chat tool-call request returned HTTP {status}")
            msg = _message(payload)
            calls = msg.get("tool_calls") or []
            if len(calls) != 1:
                raise RuntimeError(f"expected one parsed tool call, got {len(calls)}")
            call = calls[0]
            if call.get("function", {}).get("name") != "echo_marker":
                raise RuntimeError("parsed tool call used the wrong function")
            raw_args = call.get("function", {}).get("arguments") or "{}"
            args = json.loads(raw_args)
            if args.get("marker") != marker:
                raise RuntimeError("parsed tool call used the wrong marker")
            content = msg.get("content") or ""
            if any(token in content for token in ("<function=", "<tool_call>", "<parameter=")):
                raise RuntimeError("raw tool-call markup leaked into assistant content")
            return {"tool_calls": len(calls), "raw_markup_leaked": False}

        def memory_injection() -> dict[str, Any]:
            status, payload = _complete(
                client,
                base=base,
                key=key,
                model=selected_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "=== REMEMBERED ===\n"
                            f"- validation marker: {memory_marker}\n"
                            "=== END REMEMBERED ==="
                        ),
                    },
                    {
                        "role": "user",
                        "content": "What validation marker is in remembered memory? Reply with only it.",
                    },
                ],
                max_tokens=selected_max_tokens,
            )
            if status != 200:
                raise RuntimeError(f"memory injection request returned HTTP {status}")
            content = (_message(payload).get("content") or "").strip()
            if memory_marker not in content:
                raise RuntimeError("model did not use injected memory block")
            return {"marker_seen": True}

        def long_multiturn_recall() -> dict[str, Any]:
            messages: list[dict[str, Any]] = [
                {
                    "role": "system",
                    "content": "You are validating multi-turn recall. Answer exactly when asked.",
                },
                {"role": "user", "content": f"The validation marker is {long_marker}."},
                {"role": "assistant", "content": "Noted."},
            ]
            for idx in range(1, 15):
                messages.extend([
                    {"role": "user", "content": f"Filler turn {idx}: acknowledge only."},
                    {"role": "assistant", "content": f"Acknowledged filler {idx}."},
                ])
            messages.append({
                "role": "user",
                "content": "What is the validation marker from earlier? Reply with only it.",
            })
            status, payload = _complete(
                client,
                base=base,
                key=key,
                model=selected_model,
                messages=messages,
                max_tokens=selected_max_tokens,
            )
            if status != 200:
                raise RuntimeError(f"long multi-turn request returned HTTP {status}")
            content = (_message(payload).get("content") or "").strip()
            if long_marker not in content:
                raise RuntimeError("model did not recall the earlier marker")
            return {"turn_pairs_between_fact_and_query": 14, "marker_seen": True}

        def fresh_without_memory_abstains() -> dict[str, Any]:
            status, payload = _complete(
                client,
                base=base,
                key=key,
                model=selected_model,
                messages=[{
                    "role": "user",
                    "content": (
                        "No memory block is available. What is the previous validation "
                        "marker? If no marker is available, reply exactly UNKNOWN."
                    ),
                }],
                max_tokens=selected_max_tokens,
            )
            if status != 200:
                raise RuntimeError(f"fresh abstention request returned HTTP {status}")
            content = (_message(payload).get("content") or "").strip()
            if "UNKNOWN" not in content:
                raise RuntimeError("fresh conversation did not abstain without memory")
            return {"abstained_without_memory": True}

        _scenario(results, "chat_tool_call_parse", tool_call_parse)
        _scenario(results, "memory_block_recall", memory_injection)
        _scenario(results, "long_multi_turn_recall", long_multiturn_recall)
        _scenario(results, "fresh_conversation_without_memory_abstains", fresh_without_memory_abstains)

    blockers = [
        f"scenario_{item['scenario']}_failed"
        for item in results
        if item["status"] != "pass"
    ]
    result = {
        "status": "pass" if not blockers else "blocked",
        "blockers": blockers,
        "model": selected_model,
        "base_url": base,
        "key_source": key_name,
        "max_tokens": selected_max_tokens,
        "max_tokens_source": max_tokens_source,
        "required_scenarios": list(validation_cfg.required_scenarios),
        "scenarios": results,
        "writes_performed": False,
        "secrets_printed": False,
    }
    _write_json(output, result)
    return result


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(prog="agent-validation")
    parser.add_argument("--dotenv", default=".env")
    parser.add_argument("--config", default="configs/autonomy.yaml")
    parser.add_argument(
        "--output",
        default="evaluation/system-validation/20260616-autonomy-contracts/agent-validation.json",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="override the config-derived single-response generation budget",
    )
    args = parser.parse_args()

    result = run_validation(
        dotenv_path=(ROOT / args.dotenv).resolve(),
        output=(ROOT / args.output).resolve(),
        config_path=(ROOT / args.config).resolve(),
        model=args.model,
        max_tokens=args.max_tokens,
    )
    print(f"agent-validation: {result['status'].upper()}")
    for scenario in result["scenarios"]:
        print(f"  {scenario['scenario']}: {scenario['status'].upper()}")
        if scenario["status"] != "pass":
            print(f"    {scenario.get('error_type')}: {scenario.get('error')}")
    for blocker in result.get("blockers", []):
        print(f"  BLOCKED: {blocker}")
    print(f"evidence -> {args.output}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
