"""Friendly operator wrapper: `cc setup` — readiness + what to do next.

Runs the real `doctor` preflight (its exit code is this command's exit code — a
failing machine is never masked as ready), then prints a registry summary and the
exact next commands. It reads state; it never fabricates readiness.

  cc setup
  cc setup local
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from command_center.cli import doctor
from command_center.schemas import AutonomyConfig, KanbanBoardsConfig

ROOT = Path(__file__).resolve().parents[3]


def _summary() -> None:
    boards = KanbanBoardsConfig.model_validate(
        yaml.safe_load((ROOT / "configs/kanban_boards.yaml").read_text(encoding="utf-8")))
    cfg = AutonomyConfig.model_validate(
        yaml.safe_load((ROOT / "configs/autonomy.yaml").read_text(encoding="utf-8")))
    enabled = [r.repo_id for r in cfg.repo_manifests if r.autonomous_edits_enabled]
    print("\n--- registry --------------------------------------------------")
    print(f"  boards: {[b.board_id for b in boards.boards]}")
    print(f"  repos:  {[r.repo_id for r in cfg.repo_manifests]} "
          f"(autonomy enabled: {enabled or 'none'})")

    from command_center.cli.github_app_verify import _merged_env, _read_dotenv
    from command_center.channels.core import kanban_emission_status
    st = kanban_emission_status(_merged_env(_read_dotenv(ROOT / ".env")))
    print("\n--- live-sync emission (standard sync path; on by default) ----")
    print(f"  status: {'ACTIVE' if st['active'] else 'inactive'} "
          f"board={st['board_id'] or '(none)'}")
    print(f"  {st['reason']}")
    if not st["active"]:
        print("  governed kanban writes from every surface emit one event once a "
              "board is resolved; opt out with KANBAN_EMIT_EVENTS=0")

    print("\n--- next ------------------------------------------------------")
    print("  cc onboard repo --path <dir>         # register another local repo")
    print("  cc onboard kanban --provider <p> --repo <id>")
    print("  cc operate verify --all              # verify boards + repos")
    print("  cc improve daily --draft-kanban true # daily self-improvement (draft-only)")
    print("  cc demo full-loop --repo <id> --board <board_id>")


def main() -> int:
    # `cc setup [local]` — `local` is accepted for parity with the docs; the doctor
    # runs the same checks regardless. Run doctor with clean argv so it uses defaults.
    saved = sys.argv
    sys.argv = ["doctor"]
    try:
        rc = doctor.main()
    finally:
        sys.argv = saved
    _summary()
    print(f"\nsetup: doctor {'PASS' if rc == 0 else 'BLOCKED'} — see checklist above")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
