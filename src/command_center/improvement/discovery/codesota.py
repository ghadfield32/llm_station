"""
CodeSOTA frontier-watch adapter — a keyless leaderboard feed for the daily scan.

CodeSOTA (https://www.codesota.com) publishes an open, sign-up-free JSON registry of
the current state-of-the-art per task. This adapter turns its per-task SOTA picks into
records the generic `ModelRegistryScanner._classify` already understands
(candidate-vs-incumbent on a metric) — so it plugs into the existing discovery pipeline
with no change to the scanner itself.

Scope, deliberately: this is FRONTIER-WATCH AWARENESS, not open-weight discovery. CodeSOTA
does not carry license / params / quant / VRAM / Ollama-tag, and its SOTA picks are mostly
closed models — so it must NOT be fed through the open-weight `model_scout_candidate` path
(`_classify_model_scout`), which requires those local-readiness fields. The open-weight
local-coding signal stays with `aider-polyglot` in `registry.model_scout`. This feed only
answers "where is the public SOTA today, and by how much does it lead the next-best model".

Two data-hygiene rules, enforced here:
  * Per-row benchmark validation. A task's runners-up sometimes carry a DIFFERENT benchmark's
    metric than the pick (observed: a `swe-bench-agentic` row nested under `terminal-bench-2`).
    We only ever compare the pick against runners-up on the SAME `benchmark.id` — never trust
    the task-level benchmark label. A task with no comparable runner-up yields no record.
  * Fail loud. A transport error (network / non-200) propagates; a configured task id that
    CodeSOTA no longer knows raises (it's OUR config to fix). The per-source isolate guard in
    the DAG turns either into a visible "failed source" line — never a silent empty feed.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Callable

import httpx

CODESOTA_BASE = "https://www.codesota.com"

# The coding / agentic tasks worth watching for a code-control-plane. Keyless, configurable.
DEFAULT_TASKS: tuple[str, ...] = (
    "swe-bench",
    "autonomous-coding",
    "code-generation",
    "coding-agents",
    "code-completion",
    "code-translation",
)

# A `http_get` returns already-parsed JSON for a URL. Injected so tests run offline.
HttpGet = Callable[[str], dict]


def _default_http_get(url: str) -> dict:
    r = httpx.get(url, timeout=30, follow_redirects=True, headers={"Accept": "application/json"})
    r.raise_for_status()
    return r.json()


def _benchmark_id(row: dict) -> str | None:
    bench = row.get("benchmark")
    return bench.get("id") if isinstance(bench, dict) else None


def _benchmark_name(row: dict) -> str | None:
    bench = row.get("benchmark")
    return bench.get("name") if isinstance(bench, dict) else None


def _best_comparable_runner_up(pick: dict, runners_up: list[dict]) -> dict | None:
    """The strongest runner-up ON THE SAME BENCHMARK AND METRIC as the pick — our incumbent.

    Same benchmark id AND same score_metric is the row-level guard against CodeSOTA's
    cross-benchmark mixing. 'Strongest' respects the metric's direction: the max score when
    higher-is-better, else the min. Returns None when nothing is comparable (→ no record)."""
    pick_bench = _benchmark_id(pick)
    pick_metric = pick.get("score_metric")
    higher_is_better = bool(pick.get("higher_is_better", True))
    comparable = [
        r for r in runners_up
        if _benchmark_id(r) == pick_bench
        and r.get("score_metric") == pick_metric
        and isinstance(r.get("score"), (int, float))
    ]
    if not comparable:
        return None
    return max(comparable, key=lambda r: r["score"]) if higher_is_better \
        else min(comparable, key=lambda r: r["score"])


def _record_for_task(task: str, payload: dict) -> dict | None:
    """Map one `/api/sota/{task}` payload to a ModelRegistryScanner record, or None when the
    pick has no comparable next-best model to stand in as the incumbent."""
    pick = payload.get("pick")
    if not isinstance(pick, dict) or not isinstance(pick.get("score"), (int, float)):
        return None
    runner_up = _best_comparable_runner_up(pick, payload.get("runners_up") or [])
    if runner_up is None:
        return None
    higher_is_better = bool(pick.get("higher_is_better", True))
    return {
        # --- the fields the generic _classify reads ---
        "model": pick.get("model_name") or pick.get("model_id"),
        "provider": pick.get("vendor"),
        "metric": pick.get("score_metric") or _benchmark_name(pick) or "score",
        "candidate": float(pick["score"]),
        "incumbent": float(runner_up["score"]),
        "direction": "increase" if higher_is_better else "decrease",
        "cost_per_mtok": pick.get("cost_per_1k_usd"),
        # --- provenance (ignored by _classify, surfaced when records are inspected/dumped) ---
        "source_name": "codesota",
        "task": payload.get("task_full_id") or task,
        "benchmark_id": _benchmark_id(pick),
        "benchmark_name": _benchmark_name(pick),
        "source_url": pick.get("model_url"),
        "evaluation_date": pick.get("result_date") or payload.get("as_of"),
        "snapshot_id": payload.get("snapshot_id"),
        "runner_up_model": runner_up.get("model_name") or runner_up.get("model_id"),
    }


def fetch_codesota_records(tasks: tuple[str, ...] | list[str] = DEFAULT_TASKS, *,
                           http_get: HttpGet = _default_http_get) -> list[dict]:
    """Fetch the SOTA pick for each task and return ModelRegistryScanner-shaped records.

    Fails loud: a transport error propagates; a task id CodeSOTA does not recognise raises a
    RuntimeError (a stale entry in OUR task list, worth surfacing as a failed source)."""
    records: list[dict] = []
    for task in tasks:
        payload = http_get(f"{CODESOTA_BASE}/api/sota/{task}?tier=sota")
        if "error" in payload:
            raise RuntimeError(
                f"codesota: task {task!r} not in registry "
                f"({payload.get('error')}); see {CODESOTA_BASE}/api/sota")
        record = _record_for_task(task, payload)
        if record is not None:
            records.append(record)
    return records


def main() -> int:
    """Dump the live feed as a JSON list — what populates the `improvement_feed_codesota`
    Airflow Variable the daily DAG reads (and lets you eyeball / A/B the data by hand)."""
    parser = argparse.ArgumentParser(description="Dump CodeSOTA frontier-watch feed records")
    parser.add_argument("--tasks", nargs="*", default=list(DEFAULT_TASKS),
                        help="CodeSOTA task ids to watch (default: coding/agentic set)")
    args = parser.parse_args()
    print(json.dumps(fetch_codesota_records(tuple(args.tasks)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
