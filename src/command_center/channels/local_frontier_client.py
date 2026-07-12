"""The local-frontier LIVE call path — a THIRD chat lane, distinct from both the local-only
LiteLLM/Ollama gateway and the paid frontier-router backup lane. Talks to an experimental
LOOPBACK-only engine (colibrì today) running entirely on this machine: no API key required,
no $ cost, no cloud egress — so unlike frontier_client.py there is no budget ledger, no cost
estimation, and no provider-selection logic here. What IS shared with that module: the same
"no tools, no board/memory context" discipline (see GatewayCore.is_local_frontier), the same
fail-closed philosophy (any gate failure raises, never a silent fallback to local Ollama), and
the same measured-not-fabricated principle for the numbers shown in the chat picker.

These engines can take MANY MINUTES per reply (colibrì: 0.05-1.06 tok/s self-reported,
unverified on this machine) — timeouts here are sized for that, not for a normal API call.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from ..schemas import contracts

ROOT = Path(__file__).resolve().parents[3]
PROVIDERS_PATH = ROOT / "configs" / "local-frontier-providers.yaml"
HEALTH_PROBE_TIMEOUT = 3.0   # local loopback — a slow/no response means "not running," not "slow reply"


def _env() -> dict[str, str]:
    """Same resolution as frontier_client._env(): the repo .env file merged under the live
    process env — a container only gets the .env FILE mounted, not every key auto-exported."""
    from . import core as _core
    return _core.env()


class LocalFrontierGateError(Exception):
    """Any gate failure — lane disabled, unknown model, base URL unset, server unreachable, a
    non-local base URL. Fail-closed: the caller (GatewayCore) does not catch this, so the
    operator sees exactly why a local-frontier turn was refused, never a silent fallback."""


def load_providers() -> contracts.LocalFrontierProvidersConfig:
    if not PROVIDERS_PATH.is_file():
        raise LocalFrontierGateError(f"{PROVIDERS_PATH} is missing")
    data = yaml.safe_load(PROVIDERS_PATH.read_text(encoding="utf-8")) or {}
    return contracts.LocalFrontierProvidersConfig.model_validate(data)


def usage_ledger_path() -> Path:
    return Path(os.environ.get("LOCAL_FRONTIER_USAGE_LEDGER")
                or ROOT / "generated" / "local-frontier-usage.jsonl")


def _append_ledger(row: dict) -> None:
    path = usage_ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


async def local_frontier_chat_completion(
    *, model_id: str, conversation_id: str, messages: list[dict],
    http: httpx.AsyncClient, task_class: str = "cockpit_chat_manual_select",
) -> dict:
    """The live call. Returns an OpenAI-shaped message dict with `_usage` attached (same
    contract GatewayCore._completion expects from frontier_chat_completion) — latency and
    computed tokens/sec, never a cost field (there is none). Raises LocalFrontierGateError on
    ANY gate failure. No `tools` field is ever sent — these engines reject it outright."""
    cfg = load_providers()
    if not cfg.enabled:
        raise LocalFrontierGateError(
            "local-frontier lane is disabled (configs/local-frontier-providers.yaml enabled: false)")
    model = cfg.models.get(model_id)
    if model is None:
        raise LocalFrontierGateError(f"model {model_id!r} is not in local-frontier-providers.yaml")
    provider_cfg = cfg.providers[model.provider]
    live_env = _env()
    base_url = live_env.get(provider_cfg.base_url_env)
    if not base_url:
        raise LocalFrontierGateError(
            f"{provider_cfg.base_url_env} is not set — start the {model.provider} server and "
            f"set it in .env before selecting this model")
    from ..cli.check_forbidden_providers import assert_local_frontier_host_allowed
    assert_local_frontier_host_allowed(base_url)  # re-validated here, not just at scan time

    headers = {"Content-Type": "application/json"}
    if provider_cfg.api_key_env:
        api_key = live_env.get(provider_cfg.api_key_env)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    body: dict[str, Any] = {
        "model": model_id, "messages": messages, "max_tokens": model.max_output_tokens}
    t0 = time.monotonic()
    try:
        r = await http.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers, json=body, timeout=model.queue_timeout_seconds)
    except httpx.TransportError as exc:
        raise LocalFrontierGateError(
            f"could not reach {model.provider} at {base_url}: {exc}") from exc
    r.raise_for_status()
    elapsed_s = time.monotonic() - t0
    data = r.json()
    msg = data["choices"][0]["message"]
    usage = data.get("usage") or {}
    completion_tokens = int(usage.get("completion_tokens") or 0)
    tokens_per_second = (round(completion_tokens / elapsed_s, 4)
                         if completion_tokens and elapsed_s > 0 else None)
    _append_ledger({
        "ts": datetime.now(timezone.utc).isoformat(),
        "conversation_id": conversation_id,
        "model_id": model_id,
        "task_class": task_class,
        "elapsed_seconds": round(elapsed_s, 2),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": completion_tokens or None,
        "tokens_per_second": tokens_per_second,
    })
    msg["_usage"] = {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": completion_tokens,
        "total_tokens": usage.get("total_tokens"),
        "elapsed_seconds": round(elapsed_s, 2),
        "tokens_per_second": tokens_per_second,
    }
    return msg


def _health(base_url: str) -> str:
    """Cheap, short-timeout /health probe — stays on loopback, never egresses. Degrades to
    'unreachable' on any failure (timeout, connection refused, non-2xx) rather than raising —
    the picker must never break because the local server isn't running.

    `/health` lives at the server ROOT, not under `/v1` (unlike every other OpenAI-compatible
    route) — base_url conventionally includes a trailing `/v1` (needed for `/v1/chat/
    completions`), so it must be stripped here specifically."""
    origin = base_url.rstrip("/")
    if origin.endswith("/v1"):
        origin = origin[: -len("/v1")]
    try:
        r = httpx.get(f"{origin}/health", timeout=HEALTH_PROBE_TIMEOUT)
        return "ready" if r.status_code == 200 else f"error_{r.status_code}"
    except httpx.TransportError:
        return "unreachable"


def _last_benchmark_summary() -> dict[str, dict]:
    """The most recent `make colibri-benchmark LIVE=1` result, keyed by model_id — real
    measured tokens/sec + pass_rate, or {} if none has run yet. Never fabricated: a missing/
    corrupt report file just means no measured-results badge, not a guessed number."""
    path = ROOT / "generated" / "local-frontier-benchmark-report.json"
    if not path.is_file():
        return {}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if report.get("mode") != "live":
        return {}
    from ..improvement.local_frontier_benchmark import summarize
    try:
        return summarize(report)
    except Exception:
        return {}


def available_local_frontier_models() -> list[dict]:
    """What the cockpit can offer in the model picker: every configured local-frontier model
    with its capability profile, whether the lane is enabled, a cheap health probe, and — once
    `make colibri-benchmark LIVE=1` has run — the last REAL measured tok/s. Read-only, stays on
    loopback. Config/env errors degrade to an empty list, never a broken chat view."""
    try:
        cfg = load_providers()
    except Exception:
        return []
    live_env = _env()
    measured = _last_benchmark_summary()
    out: list[dict] = []
    for model_id, model in cfg.models.items():
        provider_cfg = cfg.providers[model.provider]
        base_url = live_env.get(provider_cfg.base_url_env)
        health = _health(base_url) if (cfg.enabled and base_url) else "not_configured"
        out.append({
            "model_id": model_id,
            "provider": model.provider,
            "lane_enabled": cfg.enabled,
            "health": health,
            "selectable": cfg.enabled and health == "ready",
            "capabilities": model.capabilities.model_dump(),
            "context_tokens": model.context_tokens,
            "disk_footprint_gb": model.disk_footprint_gb,
            "expected_tokens_per_second": model.expected_tokens_per_second.model_dump(),
            "kv_slots": model.kv_slots,
            "max_queue": model.max_queue,
            "measured": measured.get(model_id),
        })
    return sorted(out, key=lambda r: r["model_id"])
