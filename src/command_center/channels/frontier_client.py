"""The frontier-router LIVE call path — the operator's explicit, budgeted escalation
to a paid open-weight model (GLM-5.2 / DeepSeek V4 Pro / Kimi K2.6 today) too large to
run on local VRAM. Reuses every gate `frontier_router_eval.preflight()` already enforces
(lane enabled, task class allowed, redaction, key present, per-request cap) and adds the
two things a single-request preflight cannot: a running-total ledger (monthly + per-
conversation caps) and the actual HTTP call.

Deliberately NOT given tools or board/growthos-memory context — see GatewayCore.is_frontier.
A frontier turn is plain conversation: prompt in, answer out, nothing about repo/board state
leaves the machine. Tool-integrated frontier chat is a distinct, larger safety decision this
module does not make.

FAIL-CLOSED throughout: any gate failure raises (RouterGateError from frontier_router_eval,
or the two errors below); nothing here silently downgrades to local or fabricates a result.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..improvement.frontier_router_eval import (
    RouterGateError,
    load_budgets,
    load_providers,
    preflight,
)
from ..improvement.router_cost import estimate_cost_usd

ROOT = Path(__file__).resolve().parents[3]
_APPROX_CHARS_PER_TOKEN = 4     # honest rough estimate for preflight sizing, not billing


def _env() -> dict[str, str]:
    """The repo .env file merged under the live process env — same resolution
    GatewayCore/LiteLLM key lookup uses (channels.core.env). A container only
    gets the .env FILE mounted, not every key auto-exported as a container env
    var, so reading raw os.environ here would silently never see the key."""
    from . import core as _core
    return _core.env()


class SecretLeakError(RouterGateError):
    """The outgoing message matched an obvious secret pattern; the send was refused
    before anything reached the provider (fail-closed, not silently stripped)."""


class FrontierBudgetExceededError(RouterGateError):
    """The per-conversation or monthly running total would be exceeded by this call."""


# Coarse, conservative patterns — false positives (refusing a safe message) are
# preferred over false negatives (leaking a real secret to a paid API).
_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),                  # OpenAI-style
    re.compile(r"\bsk-ant-[A-Za-z0-9-]{16,}\b"),              # Anthropic-style
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),                  # GitHub PAT
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),          # Slack
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                      # AWS access key
    re.compile(r"(?im)^\s*[A-Z][A-Z0-9_]{3,}_?(KEY|TOKEN|SECRET|PASSWORD)\s*=\s*\S+"),
]


def scan_for_secrets(text: str) -> str | None:
    """Returns a short reason string if `text` looks like it carries a secret, else
    None. This IS the redaction gate for the cockpit chat path — see the module
    docstring: block-and-tell, never silently mutate the message."""
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return f"message matches a secret-like pattern ({pattern.pattern[:40]}...)"
    return None


def usage_ledger_path() -> Path:
    return Path(os.environ.get("FRONTIER_ROUTER_USAGE_LEDGER")
                or ROOT / "generated" / "frontier-router-usage.jsonl")


def _ledger_rows() -> list[dict]:
    path = usage_ledger_path()
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue        # a corrupt row must not crash budget accounting
    return rows


def _append_ledger(row: dict) -> None:
    path = usage_ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def running_totals(conversation_id: str, *, now: datetime | None = None) -> tuple[float, float]:
    """(month_total_usd, conversation_total_usd) from ACTUAL recorded cost — never the
    pre-call estimate. month_total resets each calendar month (paired with
    monthly_cap_usd); conversation_total is a LIFETIME sum for that conversation id
    (paired with per_run_cap_usd) — it never resets, so a long-lived chat thread
    cannot outrun its cap by waiting for the next month. A row with no
    actual_cost_usd (should never happen once fail_on_missing_usage is enforced)
    contributes 0, not a guess."""
    now = now or datetime.now(timezone.utc)
    month_key = now.strftime("%Y-%m")
    month_total = 0.0
    convo_total = 0.0
    for row in _ledger_rows():
        cost = row.get("actual_cost_usd")
        if not isinstance(cost, (int, float)):
            continue
        if str(row.get("ts", "")).startswith(month_key):
            month_total += cost
        if row.get("conversation_id") == conversation_id:
            convo_total += cost
    return round(month_total, 6), round(convo_total, 6)


def _estimate_tokens(messages: list[dict]) -> int:
    chars = sum(len(str(m.get("content") or "")) for m in messages)
    return max(1, chars // _APPROX_CHARS_PER_TOKEN)


async def frontier_chat_completion(
    *, model_id: str, conversation_id: str, messages: list[dict],
    http: httpx.AsyncClient, task_class: str = "cockpit_chat_manual_select",
    output_tokens_estimate: int = 2000,
) -> dict:
    """The live call. Returns an OpenAI-shaped message dict with `_usage` attached
    (same contract GatewayCore._completion returns), so the tool-loop plumbing and
    the flight recorder need no special-casing beyond `msg.pop("_usage")`.

    Raises RouterGateError (or a subclass) on ANY gate failure — disabled lane,
    unknown model, secret-like content, missing key, over per-request/conversation/
    monthly cap, or a provider response with no usage block. No silent fallback to
    local; the caller (GatewayCore) does not catch this — the operator sees exactly
    why a frontier turn was refused."""
    providers_cfg = load_providers()
    budgets_cfg = load_budgets()
    policy = budgets_cfg.default

    outgoing_text = "\n".join(str(m.get("content") or "") for m in messages)
    leak = scan_for_secrets(outgoing_text)
    if leak:
        raise SecretLeakError(f"frontier send refused: {leak}")

    model = providers_cfg.models.get(model_id)
    if model is None:
        raise RouterGateError(f"model {model_id!r} is not in frontier-router-providers.yaml")
    # cheapest eligible provider for this workload — not a hardcoded preference
    from ..improvement.router_cost import cheapest_eligible
    input_tokens = _estimate_tokens(messages)
    pick = cheapest_eligible(
        model.router_candidates, input_tokens, output_tokens_estimate,
        per_request_cap_usd=policy.per_request_cap_usd)
    if pick is None:
        raise RouterGateError(
            f"no eligible provider for {model_id!r} at this size/budget "
            f"(~{input_tokens} input + {output_tokens_estimate} output tokens)")
    provider_name = pick.provider
    candidate = next(c for c in model.router_candidates if c.provider == provider_name)
    provider_cfg = providers_cfg.providers[provider_name]
    # Same key resolution as the rest of the gateway (channels.core.env): the
    # mounted .env file merged under the live process env, so a containerized
    # cockpit sees a key set only in the .env file, not just in the shell.
    api_key = _env().get(provider_cfg.secret_env, "")

    record = preflight(
        model_id=model_id, provider=provider_name, input_tokens=input_tokens,
        output_tokens=output_tokens_estimate, task_class=task_class,
        payload_redacted=True, api_key_present=bool(api_key),
        providers_cfg=providers_cfg, budgets_cfg=budgets_cfg)

    month_total, convo_total = running_totals(conversation_id)
    if month_total + record.estimated_cost_usd > policy.monthly_cap_usd:
        raise FrontierBudgetExceededError(
            f"estimated call would push this month's frontier spend to "
            f"${month_total + record.estimated_cost_usd:.4f}, over the "
            f"${policy.monthly_cap_usd:.2f} monthly cap")
    if convo_total + record.estimated_cost_usd > policy.per_run_cap_usd:
        raise FrontierBudgetExceededError(
            f"estimated call would push this conversation's frontier spend to "
            f"${convo_total + record.estimated_cost_usd:.4f}, over the "
            f"${policy.per_run_cap_usd:.2f} per-conversation cap")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body: dict[str, Any] = {"model": candidate.model, "messages": messages}
    r = await http.post(
        f"{provider_cfg.base_url.rstrip('/')}/chat/completions",
        headers=headers, json=body, timeout=180)
    r.raise_for_status()
    data = r.json()
    msg = data["choices"][0]["message"]
    usage = data.get("usage")
    if policy.fail_on_missing_usage and not usage:
        raise RouterGateError(
            f"provider {provider_name!r} returned no usage block; "
            "fail_on_missing_usage forbids recording an unmeasured spend")
    actual_in = int((usage or {}).get("prompt_tokens") or 0)
    actual_out = int((usage or {}).get("completion_tokens") or 0)
    actual_cost = estimate_cost_usd(
        actual_in, actual_out, candidate.input_usd_per_mtok, candidate.output_usd_per_mtok,
        cached_input_usd_per_mtok=candidate.cached_input_usd_per_mtok)
    if policy.log_token_usage or policy.log_cost_estimate:
        _append_ledger({
            "ts": datetime.now(timezone.utc).isoformat(),
            "conversation_id": conversation_id,
            "model_id": model_id,
            "provider": provider_name,
            "task_class": task_class,
            "estimated_cost_usd": record.estimated_cost_usd,
            "actual_input_tokens": actual_in if policy.log_token_usage else None,
            "actual_output_tokens": actual_out if policy.log_token_usage else None,
            "actual_cost_usd": actual_cost if policy.log_cost_estimate else None,
        })
    msg["_usage"] = {"prompt_tokens": actual_in, "completion_tokens": actual_out,
                      "total_tokens": actual_in + actual_out,
                      "estimated_cost_usd": record.estimated_cost_usd,
                      "actual_cost_usd": actual_cost}
    return msg


def _last_benchmark_summary() -> dict[str, dict]:
    """The most recent `make frontier-router-benchmark LIVE=1` result, keyed by
    model_id — real measured latency/pass-rate/cost from the last run, or {} if
    none has run yet. Never fabricated: a missing/corrupt report file just
    means no measured-results badge in the picker, not a guessed number."""
    path = ROOT / "generated" / "frontier-benchmark-report.json"
    if not path.is_file():
        return {}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if report.get("mode") != "live":
        return {}
    from ..improvement.frontier_benchmark import summarize
    try:
        return summarize(report)
    except Exception:
        return {}


def available_frontier_models() -> list[dict]:
    """What the cockpit can offer in the model picker: every configured model id with
    its cheapest eligible price signal for a representative turn, whether the lane is
    enabled, whether a key is present, and — when `make frontier-router-benchmark
    LIVE=1` has been run — the last REAL measured latency/pass-rate/cost from that
    run. Read-only, no egress. Config/env errors degrade to an empty list (the
    picker just shows no frontier options), never a broken chat view."""
    try:
        providers_cfg = load_providers()
        budgets_cfg = load_budgets()
    except Exception:
        return []
    policy = budgets_cfg.default
    from ..improvement.router_cost import cheapest_eligible
    measured = _last_benchmark_summary()
    out: list[dict] = []
    live_env = _env()
    for model_id, model in providers_cfg.models.items():
        pick = cheapest_eligible(model.router_candidates, 4000, 2000)
        provider_name = pick.provider if pick else model.router_candidates[0].provider
        provider_cfg = providers_cfg.providers.get(provider_name)
        key_present = bool(provider_cfg and live_env.get(provider_cfg.secret_env))
        row = {
            "model_id": model_id,
            "provider": provider_name,
            "estimated_cost_per_turn_usd": pick.estimated_cost_usd if pick else None,
            "context_tokens": pick.context_tokens if pick else None,
            "lane_enabled": policy.enabled,
            "key_present": key_present,
            "selectable": policy.enabled and key_present,
            "measured": measured.get(model_id),
        }
        out.append(row)
    return sorted(out, key=lambda r: r["model_id"])
