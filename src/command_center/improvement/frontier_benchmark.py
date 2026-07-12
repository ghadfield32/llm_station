"""Continual KPI check for the frontier-router lane: run configs/model-benchmarks.yaml
suites (the SAME cases/metrics used to judge local incumbents) against the configured
frontier candidates, so "is GLM-5.2/DeepSeek V4 Pro/Kimi K2.6 actually the most helpful
model for our purposes" stays a measured answer, not a leaderboard headline.

Two modes:
  --dry-run (default)  cost-only PREVIEW — no egress, works with the lane disabled.
  --live                real calls through frontier_client (task_class=
                        frontier_reference_eval, already in allowed_task_classes).
                        Every gate frontier_chat_completion enforces still applies; a
                        disabled lane or missing key means every case is recorded
                        "blocked: <reason>", not a crash and not a fabricated score.

This is REFERENCE evidence only — task_class frontier_reference_eval can never promote a
local model (see MASTER.md §5.4 "frontier-router backup lane"). Results just answer
"which of the three is worth its price for chat/tool-use quality," on a cadence the
operator controls (this module makes no scheduling decision of its own).
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ..schemas import contracts  # noqa: F401  (import-time contract registration)
from .benchmark_scoring import score_case
from .schema import ModelBenchmarksConfig

SUITE_PATH = Path("configs/model-benchmarks.yaml")
PROVIDERS_PATH = Path("configs/frontier-router-providers.yaml")
REPORT_JSON = Path("generated/frontier-benchmark-report.json")
REPORT_MD = Path("generated/frontier-benchmark-report.md")

# The 2026-07-10 top-3 pick (see docs/reviews and configs/frontier-router-providers.yaml
# header comment). Explicit, not "every configured model" — the point is a stable,
# repeatable, cheap comparison, not scanning an ever-growing candidate list unattended.
DEFAULT_CANDIDATES = ["glm-5.2", "deepseek-v4-pro", "kimi-k2.6"]


def _load_suites(path: Path = SUITE_PATH) -> ModelBenchmarksConfig:
    return ModelBenchmarksConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def dry_run(suite_role: str, candidates: list[str]) -> dict:
    """Cost-only preview: what running this suite against these candidates would cost,
    with NO egress — works even while the lane is disabled."""
    from .frontier_router_eval import dry_run_report
    suites = _load_suites()
    suite = suites.suites[suite_role]
    n_cases = len(suite.cases)
    rows = []
    total = 0.0
    for model_id in candidates:
        preview = dry_run_report(
            model_id=model_id, provider=None,
            input_tokens=200, output_tokens=suites.defaults.num_predict,
            task_class="frontier_reference_eval")
        per_call = preview.get("estimated_cost_usd") or 0.0
        est_total = per_call * n_cases
        total += est_total
        rows.append({"model_id": model_id, "cases": n_cases,
                     "estimated_cost_per_case_usd": per_call,
                     "estimated_total_usd": round(est_total, 4),
                     "budget_verdict": preview.get("budget_verdict"),
                     # cost/context math is verdict-independent; the lane must
                     # STILL be enabled + keyed for --live to actually run
                     "lane_enabled": preview.get("lane_enabled", False)})
    return {"mode": "dry_run", "suite": suite_role, "cases": n_cases,
            "candidates": rows, "estimated_total_usd": round(total, 4), "live_call": False}


async def run_live(suite_role: str, candidates: list[str]) -> dict:
    """Real calls through frontier_client — one message per case, no history, no
    tools. Every gate failure (lane disabled, no key, over budget) is caught PER CASE
    and recorded as blocked, so one candidate's missing key doesn't abort the run."""
    import httpx

    from ..channels.frontier_client import frontier_chat_completion
    suites = _load_suites()
    suite = suites.suites[suite_role]
    results: dict[str, list[dict]] = {}
    async with httpx.AsyncClient(timeout=180) as http:
        for model_id in candidates:
            rows: list[dict] = []
            for case in suite.cases:
                messages = [{"role": "user", "content": case.prompt}]
                t0 = time.monotonic()
                try:
                    msg = await frontier_chat_completion(
                        model_id=model_id,
                        conversation_id=f"frontier-benchmark:{suite_role}:{model_id}",
                        messages=messages, http=http,
                        task_class="frontier_reference_eval",
                        output_tokens_estimate=suites.defaults.num_predict)
                except Exception as exc:
                    rows.append({"case_id": case.id, "ok": False, "blocked": True,
                                "reason": f"{type(exc).__name__}: {exc}"})
                    continue
                elapsed_ms = (time.monotonic() - t0) * 1000
                content = str(msg.get("content") or "")
                score = score_case(case, content)
                usage = msg.get("_usage") or {}
                score.update({
                    "blocked": False,
                    "latency_ms": round(elapsed_ms, 1),
                    "actual_cost_usd": usage.get("actual_cost_usd"),
                    "completion_tokens": usage.get("completion_tokens"),
                })
                rows.append(score)
            results[model_id] = rows
    return {"mode": "live", "suite": suite_role, "results": results, "live_call": True}


def summarize(live_report: dict) -> dict:
    """Per-model pass rate + median latency + total measured cost — the comparison
    that answers "worth the price," not a raw score dump."""
    summary = {}
    for model_id, rows in live_report.get("results", {}).items():
        scored = [r for r in rows if not r.get("blocked")]
        blocked = [r for r in rows if r.get("blocked")]
        n = len(scored)
        passed = sum(1 for r in scored if r.get("ok"))
        latencies = sorted(r["latency_ms"] for r in scored if r.get("latency_ms") is not None)
        cost = sum(r.get("actual_cost_usd") or 0.0 for r in scored)
        summary[model_id] = {
            "cases_scored": n,
            "cases_blocked": len(blocked),
            "pass_rate": round(passed / n, 3) if n else None,
            "median_latency_ms": latencies[len(latencies) // 2] if latencies else None,
            "measured_cost_usd": round(cost, 4),
            "block_reasons": sorted({r["reason"] for r in blocked}) if blocked else [],
        }
    return summary


def _write_report(report: dict) -> None:
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = [f"# Frontier benchmark — {report.get('mode')} — "
             f"{datetime.now(timezone.utc).isoformat()}", ""]
    if report.get("mode") == "dry_run":
        lines.append(f"suite: {report['suite']} ({report['cases']} cases) — "
                     f"NO egress, preview only")
        lines.append("")
        lines.append("| model | est. cost/case | est. total | verdict | lane enabled |")
        lines.append("|---|---|---|---|---|")
        for row in report["candidates"]:
            lines.append(f"| {row['model_id']} | ${row['estimated_cost_per_case_usd']:.4f} "
                         f"| ${row['estimated_total_usd']:.4f} | {row['budget_verdict']} "
                         f"| {row['lane_enabled']} |")
    else:
        summary = summarize(report)
        lines.append(f"suite: {report['suite']} — LIVE calls made")
        lines.append("")
        lines.append("| model | pass rate | scored | blocked | median latency | measured cost |")
        lines.append("|---|---|---|---|---|---|")
        for model_id, s in summary.items():
            lines.append(
                f"| {model_id} | {s['pass_rate']} | {s['cases_scored']} | "
                f"{s['cases_blocked']} | {s['median_latency_ms']}ms | "
                f"${s['measured_cost_usd']:.4f} |")
        if any(s["block_reasons"] for s in summary.values()):
            lines.append("")
            lines.append("blocked reasons:")
            for model_id, s in summary.items():
                for reason in s["block_reasons"]:
                    lines.append(f"- {model_id}: {reason}")
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run configs/model-benchmarks.yaml suites against the frontier "
                    "candidates — dry-run (cost preview, default) or --live (real calls).")
    parser.add_argument("--suite", default="chat")
    parser.add_argument("--candidates", nargs="*", default=DEFAULT_CANDIDATES)
    parser.add_argument("--live", action="store_true",
                        help="make real calls (spends money if the lane is enabled)")
    args = parser.parse_args()

    if args.live:
        import asyncio
        report = asyncio.run(run_live(args.suite, args.candidates))
        print(json.dumps(summarize(report), indent=2, sort_keys=True))
    else:
        report = dry_run(args.suite, args.candidates)
        print(json.dumps(report, indent=2, sort_keys=True))
    _write_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
