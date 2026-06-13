"""
Proactive Runner — scheduled checks on already-done work.

Two lanes, both defined in configs/proactive.yaml:
  runtime_checks   — DAG/data freshness, quality, drift, service perf
  repo_stewardship — structure, tests, docs, defensive-coding debt

A check runs on its cron, collects evidence, asks its (cheap, local-first) judges
whether the target is healthy, and on a real finding does exactly ONE of:
  - ledger_report     : record a finding (and optionally a GitHub issue, after approval)
  - open_rca_mission  : open a normal Ledger mission that flows through the SAME
                        lease → checks → judges → human-gate → GitHub pipeline

It is deliberately a thin scheduler. It holds NO production secrets and has NO
write path of its own — the strongest thing it can do autonomously is open a
gated mission. The contract in src/command_center/schemas/contracts.py makes anything stronger
(L3/L4 from a scheduled check, auto-push, auto-refactor) fail `make validate`.
"""

import os
import time
import yaml
import httpx

LEDGER = os.environ.get("LEDGER_BASE_URL", "http://ledger:8090")
JUDGE_GATE = os.environ.get("JUDGE_GATE_BASE_URL", "http://judge-gate:8088")
CONFIG_PATH = os.environ.get("PROACTIVE_CONFIG", "/app/proactive.yaml")


def load_checks() -> dict:
    """Read the validated proactive config. (It was already checked by
    `make validate`; we don't re-implement validation here.)"""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def run_check(check: dict) -> dict:
    """Run one check: collect evidence, ask judges, decide on_fail action.

    The real evidence collectors (Airflow/Dagster API, asset checks, ruff/semgrep
    over a repo) are wired per-target at install. This function is the control
    flow they plug into — it stays small on purpose.
    """
    name = check["name"]
    # 1. collect evidence (placeholder: real collectors return logs/metrics/reports)
    evidence = {k: f"<{k} for {check['target']}>" for k in check.get("evidence", [])}

    # 2. ask the judges named on the check (Judge Gate routes them cheap-first)
    verdict = ask_judges(check, evidence)

    # 3. act on the verdict — at most a gated mission, never a direct edit
    if verdict["healthy"]:
        record_event(name, "health", "ok", evidence)
        return {"name": name, "result": "healthy"}

    action = check.get("on_fail", "open_rca_mission")
    if action == "ledger_report":
        record_event(name, "finding", verdict["summary"], evidence)
        return {"name": name, "result": "finding_reported"}
    # open_rca_mission: hand off to the normal mission pipeline (gated downstream)
    mission_id = open_mission(check, verdict, evidence)
    return {"name": name, "result": "rca_mission_opened", "mission_id": mission_id}


def ask_judges(check: dict, evidence: dict) -> dict:
    """Call Judge Gate with the check's judges. Returns {healthy, summary}.
    Errors propagate — a check that can't reach the judge gate should fail
    loudly and be retried on its next tick, not silently pass."""
    resp = httpx.post(
        f"{JUDGE_GATE}/proactive/judge",
        json={"check": check["name"], "judges": check.get("judges", []), "evidence": evidence},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def open_mission(check: dict, verdict: dict, evidence: dict) -> str:
    risk = to_ledger_risk(check.get("auto_patch_max_risk", "L0_read_only"))
    resp = httpx.post(
        f"{LEDGER}/mission",
        json={
            "action": f"RCA: {verdict['summary']}",
            "repo": check["target"],
            "branch": "",
            "risk": risk,
            "requires_approval": risk in {"L3", "L4"},
        },
        timeout=30,
    )
    resp.raise_for_status()
    mission_id = resp.json().get("id", "")
    httpx.post(
        f"{LEDGER}/mission/{mission_id}/event",
        json={
            "kind": "note",
            "payload": {
                "source": f"proactive:{check['name']}",
                "summary": verdict["summary"],
                "evidence": evidence,
            },
        },
        timeout=30,
    ).raise_for_status()
    return mission_id


def record_event(check_name: str, kind: str, summary: str, evidence: dict) -> None:
    httpx.post(
        f"{LEDGER}/events",
        json={"source": f"proactive:{check_name}", "kind": kind,
              "summary": summary, "evidence": evidence},
        timeout=30,
    ).raise_for_status()


def to_ledger_risk(risk: str) -> str:
    mapping = {
        "L0_read_only": "L0",
        "L1_plan_only": "L1",
        "L2_local_edits": "L2",
        "L3_external_write": "L3",
        "L4_dangerous": "L4",
    }
    return mapping.get(risk, risk[:2] if risk.startswith("L") else "L4")


def due(check: dict, now: float) -> bool:
    """Minimal cron gate. A real deployment uses a cron library or the host's
    scheduler; this keeps the dependency surface tiny for the stub. Replace with
    `croniter` if you want full cron semantics — that's a one-line dep add."""
    # Stub: the scheduler that invokes this runner (host cron / systemd timer)
    # is the source of truth for timing; when called, every check is considered due.
    return True


def main() -> None:
    cfg = load_checks()
    checks = cfg.get("runtime_checks", []) + cfg.get("repo_stewardship", [])
    now = time.time()
    for check in checks:
        if due(check, now):
            result = run_check(check)
            print(result)


if __name__ == "__main__":
    main()
