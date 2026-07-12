"""Continual KPI check for the local-frontier lane: run configs/model-benchmarks.yaml suites
(the SAME cases/metrics used to judge local incumbents AND the paid frontier-router lane —
see frontier_benchmark.py) against the configured local-frontier candidates (colibrì today),
so "is this experimental local engine actually worth the wait" stays a measured answer, never
a self-reported README number treated as fact.

Two modes:
  --dry-run (default)  lists what would run, no live call — works even with the lane disabled.
  --live                real calls through local_frontier_client. Every gate
                        local_frontier_chat_completion enforces still applies; a disabled lane
                        or unreachable server means every case is recorded "blocked: <reason>,"
                        not a crash and not a fabricated score.

Unlike frontier_benchmark.py there is no cost field anywhere here — local-frontier engines
have no $ price, only a (potentially very long) wall-clock one. The headline metric is
tokens/sec, not latency or cost. `--max-cases` defaults small (3): at the self-reported
0.05-1.06 tok/s range, a full suite live run could take hours, and running it unbounded by
default would silently turn a quick sanity check into an all-afternoon job.

This is REFERENCE evidence only — task_class frontier_reference_eval can never promote a local
Ollama model (see MASTER.md §5.4). Results just answer "is this worth running again," on a
cadence the operator controls (this module makes no scheduling decision of its own).
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
REPORT_JSON = Path("generated/local-frontier-benchmark-report.json")
REPORT_MD = Path("generated/local-frontier-benchmark-report.md")


def _load_suites(path: Path = SUITE_PATH) -> ModelBenchmarksConfig:
    return ModelBenchmarksConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _default_candidates() -> list[str]:
    """Every model configured in local-frontier-providers.yaml — there is no curated
    top-N pick here (unlike frontier_benchmark's DEFAULT_CANDIDATES): whatever an operator
    has configured for this experimental lane is the whole candidate set."""
    from ..channels.local_frontier_client import load_providers
    try:
        return sorted(load_providers().models)
    except Exception:
        return []


def dry_run(suite_role: str, candidates: list[str], max_cases: int) -> dict:
    """Preview: what running this suite against these candidates would look like, with NO
    egress — works even while the lane is disabled. No cost estimate (there is none)."""
    from ..channels.local_frontier_client import load_providers
    suites = _load_suites()
    suite = suites.suites[suite_role]
    n_cases = min(len(suite.cases), max_cases)
    try:
        cfg = load_providers()
        lane_enabled = cfg.enabled
    except Exception:
        lane_enabled = False
    rows = [{"model_id": model_id, "cases": n_cases, "lane_enabled": lane_enabled}
           for model_id in candidates]
    return {"mode": "dry_run", "suite": suite_role, "cases": n_cases,
            "candidates": rows, "live_call": False}


async def run_live(suite_role: str, candidates: list[str], max_cases: int) -> dict:
    """Real calls through local_frontier_client — one message per case, no history, no
    tools. Every gate failure (lane disabled, no base URL, unreachable server) is caught PER
    CASE and recorded as blocked, so one candidate's missing server doesn't abort the run.
    Bounded to `max_cases` per candidate given the expected multi-minute-per-reply cost."""
    import httpx

    from ..channels.local_frontier_client import local_frontier_chat_completion
    suites = _load_suites()
    suite = suites.suites[suite_role]
    cases = suite.cases[:max_cases]
    results: dict[str, list[dict]] = {}
    async with httpx.AsyncClient(timeout=None) as http:
        for model_id in candidates:
            rows: list[dict] = []
            for case in cases:
                messages = [{"role": "user", "content": case.prompt}]
                t0 = time.monotonic()
                try:
                    msg = await local_frontier_chat_completion(
                        model_id=model_id,
                        conversation_id=f"local-frontier-benchmark:{suite_role}:{model_id}",
                        messages=messages, http=http,
                        task_class="frontier_reference_eval")
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
                    "completion_tokens": usage.get("completion_tokens"),
                    "tokens_per_second": usage.get("tokens_per_second"),
                })
                rows.append(score)
            results[model_id] = rows
    return {"mode": "live", "suite": suite_role, "results": results, "live_call": True}


def summarize(live_report: dict) -> dict:
    """Per-model pass rate + median tokens/sec — the headline metric for this lane (there is
    no cost to compare, and latency alone is misleading at sub-1-tok/s speeds)."""
    summary = {}
    for model_id, rows in live_report.get("results", {}).items():
        scored = [r for r in rows if not r.get("blocked")]
        blocked = [r for r in rows if r.get("blocked")]
        n = len(scored)
        passed = sum(1 for r in scored if r.get("ok"))
        tps = sorted(r["tokens_per_second"] for r in scored
                    if r.get("tokens_per_second") is not None)
        summary[model_id] = {
            "cases_scored": n,
            "cases_blocked": len(blocked),
            "pass_rate": round(passed / n, 3) if n else None,
            "median_tokens_per_second": tps[len(tps) // 2] if tps else None,
            "block_reasons": sorted({r["reason"] for r in blocked}) if blocked else [],
        }
    return summary


def _write_report(report: dict) -> None:
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = [f"# Local-frontier benchmark — {report.get('mode')} — "
             f"{datetime.now(timezone.utc).isoformat()}", ""]
    if report.get("mode") == "dry_run":
        lines.append(f"suite: {report['suite']} ({report['cases']} cases, capped) — "
                     f"NO egress, preview only")
        lines.append("")
        lines.append("| model | cases | lane enabled |")
        lines.append("|---|---|---|")
        for row in report["candidates"]:
            lines.append(f"| {row['model_id']} | {row['cases']} | {row['lane_enabled']} |")
    else:
        summary = summarize(report)
        lines.append(f"suite: {report['suite']} — LIVE calls made")
        lines.append("")
        lines.append("| model | pass rate | scored | blocked | median tok/s |")
        lines.append("|---|---|---|---|---|")
        for model_id, s in summary.items():
            lines.append(
                f"| {model_id} | {s['pass_rate']} | {s['cases_scored']} | "
                f"{s['cases_blocked']} | {s['median_tokens_per_second']} |")
        if any(s["block_reasons"] for s in summary.values()):
            lines.append("")
            lines.append("blocked reasons:")
            for model_id, s in summary.items():
                for reason in s["block_reasons"]:
                    lines.append(f"- {model_id}: {reason}")
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run configs/model-benchmarks.yaml suites against the local-frontier "
                    "candidates (colibrì today) — dry-run (preview, default) or --live "
                    "(real calls, can take a long time).")
    parser.add_argument("--suite", default="chat")
    parser.add_argument("--candidates", nargs="*", default=None,
                        help="omit to use every model in local-frontier-providers.yaml")
    parser.add_argument("--live", action="store_true",
                        help="make real calls — can take minutes PER CASE")
    parser.add_argument("--max-cases", type=int, default=3,
                        help="cap cases per candidate (default 3 — a full suite live can "
                             "take hours at colibrì's expected throughput)")
    args = parser.parse_args()
    candidates = args.candidates if args.candidates is not None else _default_candidates()

    if args.live:
        import asyncio
        report = asyncio.run(run_live(args.suite, candidates, args.max_cases))
        print(json.dumps(summarize(report), indent=2, sort_keys=True))
    else:
        report = dry_run(args.suite, candidates, args.max_cases)
        print(json.dumps(report, indent=2, sort_keys=True))
    _write_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
