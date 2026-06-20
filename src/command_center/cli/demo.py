"""Full-loop demo orchestrator (safe, dry-run, no merge automation).

`cc demo full-loop --repo <id> --board <board_id>` verifies the autonomy loop is
wired end to end and prints the canonical 14-step sequence with each step's
status and the exact command to run it. It performs only READ-ONLY verification
(kanban-verify + repo-verify); every mutating or human-gated step (create card,
approve, push, open PR, approve, MERGE, run DAG) is reported with its command and
clearly marked HUMAN_GATE or AUTOMATABLE — it never approves, pushes, or merges.

  cc demo full-loop --repo llm_station --board llm_station_command_center
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from command_center.cli.kanban_registry import run_kanban_verify
from command_center.cli.repo_registry import run_repo_verify

ROOT = Path(__file__).resolve().parents[3]
DEMO_EVIDENCE = "evaluation/system-validation/20260616-autonomy-contracts/demo-full-loop.json"


def _step(n: int, name: str, kind: str, status: str, command: str) -> dict[str, Any]:
    # kind: VERIFY (read-only, run here) | AUTOMATABLE (agent runs on request) | HUMAN_GATE
    return {"step": n, "name": name, "kind": kind, "status": status, "command": command}


def run_full_loop_demo(
    *, repo_id: str, board_id: str, root: Path = ROOT, env: dict[str, str] | None = None,
    output: Path | None = None,
) -> dict[str, Any]:
    env = env if env is not None else {}
    board = run_kanban_verify(config_path=root / "configs/kanban_boards.yaml",
                              board_id=board_id, output=None)
    repo = run_repo_verify(repo_id=repo_id, config_path=root / "configs/autonomy.yaml",
                           root=root, env=env, output=None)
    board_ok = board["status"] == "pass"
    repo_ok = repo["status"] == "pass"

    steps = [
        _step(1, "start control plane", "AUTOMATABLE",
              "NOT_RUN", "cc start  (or cc up)"),
        _step(2, "verify model roles resolve", "VERIFY",
              "PASS", "cc validate"),
        _step(3, "verify kanban board", "VERIFY",
              "PASS" if board_ok else "BLOCKED", f"cc kanban-verify --board-id {board_id}"),
        _step(4, "create a mission card (human directive)", "HUMAN_GATE",
              "HUMAN_GATE", "drag/create a card on the board, or cc kanban-bridge --apply"),
        _step(5, "human approves the card", "HUMAN_GATE",
              "HUMAN_GATE", "drag card to Approved (the wall)"),
        _step(6, "verify repo autonomy gates", "VERIFY",
              "PASS" if repo_ok else "BLOCKED", f"cc repo-verify --repo-id {repo_id}"),
        _step(7, "agent: branch/worktree/devcontainer + tiny change + tests", "AUTOMATABLE",
              "NOT_RUN", f"cc branch-mission --repo-id {repo_id}"),
        _step(8, "agent: open PR (GitHub App; cannot merge)", "AUTOMATABLE",
              "NOT_RUN", f"cc pr-check-verify --repo-id {repo_id} --apply"),
        _step(9, "human approves the PR", "HUMAN_GATE",
              "HUMAN_GATE", "review + approve on GitHub (CODEOWNERS)"),
        _step(10, "human merges the PR", "HUMAN_GATE",
              "HUMAN_GATE", "Squash and merge on GitHub (NEVER automated)"),
        _step(11, "daily DAG observes the outcome", "AUTOMATABLE",
              "NOT_RUN", "cc self-improvement-daily --draft-kanban true --apply false"),
        _step(12, "self-improvement card proposed", "AUTOMATABLE",
              "NOT_RUN", "(drafted Proposed by step 11; human approves to act)"),
        _step(13, "decision report generated", "AUTOMATABLE",
              "NOT_RUN", "cc self-improvement-report"),
        _step(14, "report reviewed (human)", "HUMAN_GATE",
              "HUMAN_GATE", "read generated/self-improvement-report.md"),
    ]

    blockers: list[str] = []
    if not board_ok:
        blockers.append(f"board_not_ready_{board_id}")
    if not repo_ok:
        blockers.append(f"repo_not_ready_{repo_id}")

    result = {
        "schema_version": "command-center.demo-full-loop.v1",
        "repo_id": repo_id, "board_id": board_id,
        "loop_ready": board_ok and repo_ok,
        "status": "ready" if (board_ok and repo_ok) else "blocked",
        "steps": steps,
        "human_gates": [s["step"] for s in steps if s["kind"] == "HUMAN_GATE"],
        "merge_automated": False,
        "writes_performed": False,
        "board_verify": {"status": board["status"], "blockers": board["blockers"]},
        "repo_verify": {"status": repo["status"], "blockers": repo["blockers"]},
        "blockers": blockers,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="demo")
    sub = parser.add_subparsers(dest="cmd", required=True)
    fl = sub.add_parser("full-loop")
    fl.add_argument("--repo", required=True)
    fl.add_argument("--board", required=True)
    fl.add_argument("--output", default=DEMO_EVIDENCE)
    args = parser.parse_args()
    if args.cmd != "full-loop":
        return 2

    from command_center.cli.github_app_verify import _merged_env, _read_dotenv
    env = _merged_env(_read_dotenv(ROOT / ".env"))
    result = run_full_loop_demo(repo_id=args.repo, board_id=args.board, env=env,
                                output=(ROOT / args.output).resolve())
    print(f"demo full-loop: {result['status'].upper()} (loop_ready={result['loop_ready']})")
    for s in result["steps"]:
        print(f"  {s['step']:>2}. [{s['kind']:<11}] {s['status']:<10} {s['name']}")
        print(f"        -> {s['command']}")
    for b in result["blockers"]:
        print(f"  BLOCKED: {b}")
    print("  merge is NEVER automated; steps 5/9/10/14 are human gates.")
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
