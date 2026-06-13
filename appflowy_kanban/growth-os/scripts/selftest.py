"""System self-test — every promise the Growth OS x Command Center system
makes, checked live. Run after any structural change; the goal is 100%.

Module tree / stages (each check independent; failures don't stop the run):
  infra      appflowy API + login, curator container, scheduled bridge task,
             discord gateway process, network_health (5 hops)
  library    book_note write+readback, Section populated, import clobber
             guard (human Notes survive re-import)
  boards     todos/mission_intake/betts_basketball_board exist w/ Board views
  dags       live counts, broken rows carry FAILED summaries + log URLs,
             dag_health returns root-cause for a known-failing DAG
  watchers   packages rows for betts, guidelines Current rows, Suggested
             annotations present, retention config loads
  loop       bridge dry-run exits 0, mission_status reads a real mission
  known-gaps in-app AI is license-walled upstream (asserted as the
             documented state, not hidden)

Run:  PYTHONPATH=. .venv/Scripts/python.exe scripts/selftest.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from growthos import actions
from growthos.config import load_projects

GROWTHOS = Path(__file__).resolve().parent.parent
CC_ROOT = GROWTHOS.parents[1]

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str):
    def deco(fn):
        try:
            detail = fn() or ""
            RESULTS.append((name, True, str(detail)[:90]))
        except Exception as exc:
            RESULTS.append((name, False, str(exc)[:160]))
    return deco


# ----------------------------------------------------------------- infra --

@check("appflowy login + workspace")
def _():
    af = actions.client()
    assert af.ws, "no workspace id"
    return af.ws[:8]


@check("network_health: all hops ok")
def _():
    h = actions.network_health()
    bad = {k: v for k, v in h.items() if v != "ok"}
    assert not bad, f"unhealthy: {bad}"
    return ", ".join(h)


@check("curator container running")
def _():
    out = subprocess.run(["docker", "ps", "--filter", "name=growthos-curator",
                          "--format", "{{.Status}}"], capture_output=True,
                         text=True, timeout=30).stdout.strip()
    assert out.startswith("Up"), out or "not running"
    return out


@check("bridge scheduled task exists")
def _():
    out = subprocess.run(["schtasks", "/query", "/tn", "CC kanban bridge"],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, "task 'CC kanban bridge' not found"
    return "scheduled"


@check("channel gateway process alive")
def _():
    # the gateway now runs as `python -m command_center.channels` (any transport)
    out = subprocess.run(
        ["powershell", "-NoProfile", "-c",
         "(Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | "
         "Where-Object { $_.CommandLine -like '*command_center.channels*' "
         "-or $_.CommandLine -like '*discord_gateway*' }).Count"],
        capture_output=True, text=True, timeout=60).stdout.strip()
    assert out and int(out) >= 1, "no channel gateway process"
    return f"{out} process(es)"


# --------------------------------------------------------------- library --

@check("book_note write + readback")
def _():
    stamp = datetime.now().isoformat()[:19]
    msg = actions.book_note("Range", f"selftest {stamp}")
    assert "1 row updated" in msg, msg
    row = next(c for c in actions._rows("library") if c["Name"] == "Range")
    assert f"selftest {stamp}" in (row.get("Notes") or ""), "note not persisted"
    return "persisted"


@check("library Section numbers populated")
def _():
    n = sum(1 for c in actions._rows("library")
            if c.get("Section") not in ("", None))
    assert n >= 200, f"only {n} rows have Section"
    return f"{n} rows"


@check("import clobber guard (human notes survive)")
def _():
    row = next(c for c in actions._rows("library") if c["Name"] == "Range")
    assert "Kicking off the Lineage" in (row.get("Notes") or ""), \
        "hand-written note missing - import overwrote it"
    return "guarded"


# ---------------------------------------------------------------- boards --

@check("boards exist incl. betts_basketball_board")
def _():
    dbs = json.loads((GROWTHOS / "config/databases.json").read_text())
    for need in ("todos", "mission_intake", "betts_basketball_board",
                 "packages", "guidelines", "dags"):
        assert need in dbs, f"missing {need}"
    return f"{len(dbs)} databases mapped"


# ------------------------------------------------------------------ dags --

@check("dags board: live statuses + failure summaries")
def _():
    rows = actions.list_dags()
    assert isinstance(rows, list) and len(rows) >= 70, f"{len(rows)} rows"
    broken = [r for r in rows if r["status"] == "Broken"]
    for b in broken:
        assert "FAILED" in b["notes"] and "logs:" in b["notes"], \
            f"{b['dag_id']} missing summary"
    return f"{len(rows)} dags, {len(broken)} broken w/ summaries"


@check("dag_health returns root cause for failing DAG")
def _():
    h = actions.dag_health("fantasy_inseason_refresh")
    assert isinstance(h, dict) and h["state"] == "failed", h
    assert ".py:" in h["error"], "no file:line pointer"
    return h["error"][:80]


# -------------------------------------------------------------- watchers --

@check("packages: pending updates for betts")
def _():
    n = sum(1 for c in actions._rows("packages")
            if c.get("Repo") == "betts_basketball")
    assert n >= 10, f"only {n}"
    return f"{n} tracked"


@check("guidelines: standards mirrored as Current")
def _():
    n = sum(1 for c in actions._rows("guidelines")
            if c.get("Status") == "Current")
    assert n >= 3, f"only {n}"
    return f"{n} Current rows"


@check("enrichment: Suggested annotations present")
def _():
    n = sum(1 for db in ("papers", "repos")
            for c in actions._rows(db) if c.get("Suggested"))
    assert n >= 5, f"only {n}"
    return f"{n} annotated"


@check("retention policy loads (no hardcoded thresholds)")
def _():
    import yaml
    cfg = yaml.safe_load((GROWTHOS / "config/sources.yaml")
                         .read_text(encoding="utf-8"))
    assert cfg["retention"]["days"] and cfg["retention"]["databases"]
    return f"{cfg['retention']['days']}d window"


@check("projects registry validates")
def _():
    p = load_projects()
    assert any(x.airflow for x in p.projects), "no airflow project"
    return ", ".join(x.name for x in p.projects)


# ------------------------------------------------------------------ loop --

@check("bridge dry-run clean")
def _():
    out = subprocess.run([sys.executable, "scripts/kanban_bridge.py"],
                         capture_output=True, text=True, timeout=120,
                         cwd=str(CC_ROOT))
    assert out.returncode == 0, out.stderr[-160:]
    return out.stdout.strip().splitlines()[-1]


@check("mission_status reads live ledger record")
def _():
    m = actions.mission_status("T-b5f2e70f")
    assert isinstance(m, dict) and m["status"], m
    return f"{m['id']} {m['status']}"


@check("project_status context pack complete")
def _():
    ps = actions.project_status("betts_basketball")
    for key in ("dags", "broken_dags", "package_updates_pending",
                "open_mission_cards", "open_todos"):
        assert key in ps, f"missing {key}"
    return f"{sum(ps['dags'].values())} dags, " \
           f"{len(ps['package_updates_pending'])} pkg updates"


@check("tool boundary validation (anti-loop)")
def _():
    bad = [
        actions.list_todos(status="open"),
        actions.list_inbox(database="todos"),
        actions.list_cards(status="open"),
        actions.list_dags(status="failed"),
    ]
    for r in bad:
        assert isinstance(r, str) and "invalid" in r, \
            f"silent fallback returned: {r!r}"
    return "4/4 bad inputs rejected loudly"


@check("gateway loop-breaker present (both channels)")
def _():
    gw = (CC_ROOT / "src/command_center/channels/core.py").read_text(encoding="utf-8")
    asst = (GROWTHOS / "growthos/assistant.py").read_text(encoding="utf-8")
    for src, name in ((gw, "gateway"), (asst, "assistant")):
        assert "already called this with identical" in src, f"{name} missing breaker"
        assert "Tool budget exhausted" in src, f"{name} missing forced answer"
    return "repeat-call breaker + forced final answer"


# ------------------------------------------------------------ known gaps --

@check("in-app AI: documented upstream license wall")
def _():
    out = subprocess.run(["docker", "ps", "-a", "--filter", "name=appflowy-ai",
                          "--format", "{{.Status}}"], capture_output=True,
                         text=True, timeout=30).stdout.strip()
    assert out.startswith("Exited"), \
        f"ai container should be stopped (license-walled), is: {out}"
    override = (CC_ROOT / "appflowy_kanban/AppFlowy-Cloud/"
                "docker-compose.override.yml").read_text(encoding="utf-8")
    assert "license" in override.lower(), "verdict not documented"
    return "stopped + documented"


def main() -> int:
    width = max(len(n) for n, _, _ in RESULTS)
    passed = 0
    for name, ok, detail in RESULTS:
        mark = "PASS" if ok else "FAIL"
        passed += ok
        print(f"[{mark}] {name:<{width}}  {detail}")
    pct = 100 * passed // len(RESULTS)
    print(f"\n{passed}/{len(RESULTS)} checks passed ({pct}%)")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
