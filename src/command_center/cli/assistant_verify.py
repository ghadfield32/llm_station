"""cc assistant-verify — run evidence suites per assistant and feed the leaderboard.

Phase 9's `assistant-verify` complements `assistant-doctor` (which answers "does
the running worker match this checkout?"). This answers "what is the current
EVIDENCE for each assistant?" and — crucially — is the first PRODUCER for the
Phase 8 executor-ranking leaderboard: it appends typed EvidenceSamples to the
durable evidence log the leaderboard reads.

No-quota by default. It runs the checks that need no paid/subscription turn:
  * serving_reliability — from the worker's live harness probe (available→1.0,
    unavailable→0.0). Appended each run, so over many runs it is a genuine
    availability RATE (sample-size-weighted mean), not a single point.
  * safety — a structural egress-honesty check: the harness must declare its
    external-egress boundary correctly (openrouter_agent=external, locals=on-box).
Every unavailable assistant gets a PRECISE reason (the probe detail) and a
repair action (plan §9).

The quota-spending suites (task_success / latency / quality via a real read-only
fixture per assistant) are gated behind --live and NOT run by default.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

_DEFAULT_WORKER = os.environ.get("AGENT_WORKER_URL", "http://127.0.0.1:8791")
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_EVIDENCE = _REPO_ROOT / "generated" / "leaderboard-evidence.jsonl"

# Precise repair actions per harness (plan §9: every unavailable result must say
# how to fix it). Falls back to the probe detail when a harness isn't listed.
# ASCII-only (this prints to consoles that may be cp1252, e.g. Windows).
_REPAIR = {
    "claude_code_local": "install + log in the Claude CLI (`claude login`), then "
                         "restart the agent worker",
    "codex_agent": "refresh the Codex login session (`codex login`), then restart "
                   "the agent worker",
    "claude_agent": "`uv pip install claude-agent-sdk` and set ANTHROPIC_API_KEY "
                    "(optional adapter; the CLI path above is preferred)",
    "openrouter_agent": "set OPENROUTER_API_KEY and enable the frontier lane "
                        "(configs/frontier-router-budgets.yaml default.enabled: true)",
    "fake": "dev-only harness; set KANBAN_UI_FAKE_AGENT_ENABLED=1 to enable for tests",
}


def _fetch_probes(base_url: str, token: str, timeout: float) -> list[dict]:
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/agent-harnesses",
        headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _evidence_for(probe: dict) -> list[dict]:
    """The no-quota evidence samples for one harness probe."""
    hid = str(probe.get("harness_id", ""))
    available = bool(probe.get("available", False))
    egress = bool(probe.get("external_egress", False))
    expected_egress = hid == "openrouter_agent"
    safety_ok = egress == expected_egress          # declares its boundary honestly
    return [
        {"executor": hid, "dimension_id": "serving_reliability",
         "value": 1.0 if available else 0.0, "sample_size": 1,
         "source": "assistant-verify"},
        {"executor": hid, "dimension_id": "safety",
         "value": 1.0 if safety_ok else 0.0, "sample_size": 1,
         "source": "assistant-verify"},
    ]


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-url", default=_DEFAULT_WORKER)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--evidence-path", default=str(_DEFAULT_EVIDENCE))
    parser.add_argument("--no-emit", action="store_true",
                        help="verify only; do not append evidence to the leaderboard log")
    parser.add_argument("--live", action="store_true",
                        help="(reserved) also run the quota-spending fixture suites")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    # probe details/repairs may carry non-ASCII; never let a cp1252 console
    # (Windows) crash the report with UnicodeEncodeError.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

    token = os.environ.get("AGENT_WORKER_TOKEN", "")
    if not token:
        print("assistant-verify: FAIL — AGENT_WORKER_TOKEN not set (cannot reach "
              "the worker to probe assistants)")
        return 1
    try:
        probes = _fetch_probes(args.worker_url, token, args.timeout)
    except Exception as exc:
        print(f"assistant-verify: FAIL — worker unreachable at {args.worker_url}: "
              f"{type(exc).__name__}: {exc}")
        return 1

    if args.live:
        print("note: --live fixture suites (task_success/latency/quality) are not "
              "wired yet — running the no-quota checks only.")

    samples: list[dict] = []
    report: list[dict] = []
    for probe in probes:
        hid = str(probe.get("harness_id", ""))
        available = bool(probe.get("available", False))
        detail = str(probe.get("detail", ""))
        ev = _evidence_for(probe)
        samples.extend(ev)
        report.append({
            "assistant": hid,
            "available": available,
            "reason": detail,
            "repair": None if available else _REPAIR.get(hid, detail),
            "evidence": {e["dimension_id"]: e["value"] for e in ev},
        })

    emitted = 0
    if not args.no_emit:
        path = Path(args.evidence_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for s in samples:
                fh.write(json.dumps(s) + "\n")
                emitted += 1

    ok = all(r["available"] for r in report)
    if args.json:
        print(json.dumps({"overall": "pass" if ok else "fail",
                          "assistants": report, "evidence_emitted": emitted}, indent=2))
    else:
        for r in report:
            mark = "PASS" if r["available"] else "FAIL"
            print(f"[{mark}] {r['assistant']:20} "
                  f"serving={r['evidence']['serving_reliability']} "
                  f"safety={r['evidence']['safety']}")
            if not r["available"]:
                print(f"       reason: {r['reason']}")
                print(f"       repair: {r['repair']}")
        print(f"\nassistant-verify: {'PASS' if ok else 'FAIL'} "
              f"({emitted} evidence samples -> leaderboard)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
