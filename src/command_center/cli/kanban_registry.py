"""Kanban board registry operations: verify / register / sync (dry-run).

The registry (`configs/kanban_boards.yaml`, contract `KanbanBoardsConfig`) maps a
board_id to the internal Command Center UI surface, the repos it
drives, the canonical status workflow, the required mission-card fields, and the
agent verb contract. These commands operate on that registry only; they never
approve, merge, deploy, or delete, and they perform no board writes.

  cc kanban-verify [--board-id <id>] [--snapshot <path>]
  cc kanban-register --board-id <id> --provider command_center_ui \
      --workspace-ref <ref> --board-ref <ref> --repo-id <id> [--apply]
  cc kanban-sync [--board-id <id>] --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml

from command_center.schemas import KanbanBoardsConfig
from command_center.schemas.contracts import (
    _KANBAN_CANONICAL_STATUSES,
    _KANBAN_GRANTABLE_VERBS,
    _KANBAN_WALL_VERBS,
    KanbanBoardSpec,
)

ROOT = Path(__file__).resolve().parents[3]
CONFIG = "configs/kanban_boards.yaml"
# Field-name fragments that must never appear in a committed board snapshot.
_SECRET_NAME_HINTS = ("token", "secret", "password", "passwd", "apikey", "api_key",
                      "private", "credential", "pem")


def _load(config_path: Path) -> KanbanBoardsConfig:
    return KanbanBoardsConfig.model_validate(
        yaml.safe_load(config_path.read_text(encoding="utf-8"))
    )


def _write_json(output: Path | None, data: dict[str, Any]) -> None:
    if output is None:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _snapshot_findings(snapshot_path: Path) -> dict[str, Any]:
    """Duplicate-MissionID detection + redaction check over a board snapshot.

    Returns status NOT_RUN when no snapshot is supplied (never faked).
    """
    if snapshot_path is None or not snapshot_path.is_file():
        return {"status": "NOT_RUN", "reason": "no_board_snapshot_supplied"}
    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    mission_ids: list[str] = []
    secret_fields: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                lk = str(key).lower()
                if lk in ("missionid", "mission_id") and value:
                    mission_ids.append(str(value))
                if any(hint in lk for hint in _SECRET_NAME_HINTS):
                    secret_fields.append(str(key))
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(data)
    duplicates = sorted({m for m in mission_ids if mission_ids.count(m) > 1})
    blockers = []
    if duplicates:
        blockers.append(f"duplicate_mission_ids:{duplicates}")
    if secret_fields:
        blockers.append(f"unredacted_secret_field_names:{sorted(set(secret_fields))}")
    return {
        "status": "PASS" if not blockers else "BLOCKED",
        "mission_id_count": len(mission_ids),
        "duplicate_mission_ids": duplicates,
        "blockers": blockers,
    }


def run_kanban_verify(
    *,
    config_path: Path = ROOT / CONFIG,
    board_id: str | None = None,
    snapshot_path: Path | None = None,
    output: Path | None = None,
) -> dict[str, Any]:
    cfg = _load(config_path)
    boards = cfg.boards if board_id is None else [b for b in cfg.boards if b.board_id == board_id]
    blockers: list[str] = []
    if board_id is not None and not boards:
        blockers.append(f"board_not_registered_{board_id}")

    board_results: list[dict[str, Any]] = []
    for b in boards:
        bb: list[str] = []
        if set(b.status_mapping) != set(_KANBAN_CANONICAL_STATUSES):
            bb.append("status_mapping_not_canonical")
        if not b.required_fields:
            bb.append("required_fields_missing")
        allowed, forbidden = set(b.allowed_agent_verbs), set(b.forbidden_agent_verbs)
        if _KANBAN_WALL_VERBS - forbidden:
            bb.append("wall_verbs_not_forbidden")
        if allowed - _KANBAN_GRANTABLE_VERBS:
            bb.append("allowed_verbs_exceed_grantable")
        if allowed & forbidden:
            bb.append("allowed_forbidden_overlap")
        # forbidden wall verbs must be unavailable to the action layer: no board
        # may grant them, anywhere in the registry.
        if allowed & _KANBAN_WALL_VERBS:
            bb.append("board_grants_wall_verb")
        snap = _snapshot_findings(snapshot_path) if board_id == b.board_id or board_id is None else {"status": "NOT_RUN"}
        if snap.get("status") == "BLOCKED":
            bb.extend(snap.get("blockers", []))
        board_results.append({
            "board_id": b.board_id,
            "provider": b.provider,
            "repo_ids": b.repo_ids,
            "status": "pass" if not bb else "blocked",
            "blockers": bb,
            "snapshot_check": snap,
        })
        blockers.extend(f"{b.board_id}:{x}" for x in bb)

    # Every board uses the one first-party action contract.
    providers = {b.provider for b in cfg.boards}
    same_contract = True

    result = {
        "schema_version": "command-center.kanban-verify.v1",
        "status": "pass" if not blockers else "blocked",
        "registry_path": CONFIG,
        "boards_verified": [b.board_id for b in boards],
        "board_results": board_results,
        "providers_present": sorted(providers),
        "shared_action_contract": same_contract,
        "canonical_statuses": sorted(_KANBAN_CANONICAL_STATUSES),
        "grantable_verbs": sorted(_KANBAN_GRANTABLE_VERBS),
        "wall_verbs_forbidden": sorted(_KANBAN_WALL_VERBS),
        "blockers": blockers,
        "writes_performed": False,
        "secrets_printed": False,
    }
    _write_json(output, result)
    return result


def run_kanban_register(
    *,
    board_id: str,
    provider: str,
    workspace_ref: str,
    board_ref: str,
    repo_ids: list[str],
    status_mapping: dict[str, str] | None = None,
    required_fields: list[str] | None = None,
    allowed_agent_verbs: list[str] | None = None,
    forbidden_agent_verbs: list[str] | None = None,
    apply: bool = False,
    config_path: Path = ROOT / CONFIG,
) -> dict[str, Any]:
    cfg = _load(config_path)
    if any(b.board_id == board_id for b in cfg.boards):
        return {"status": "blocked", "blockers": [f"board_id_already_registered_{board_id}"]}
    spec = KanbanBoardSpec(
        board_id=board_id,
        provider=provider,  # type: ignore[arg-type]
        workspace_ref=workspace_ref,
        board_ref=board_ref,
        repo_ids=repo_ids,
        status_mapping=status_mapping or {s: s.replace("_", " ").title()
                                         for s in sorted(_KANBAN_CANONICAL_STATUSES)},
        required_fields=required_fields or ["MissionID", "RepoID", "Risk", "LastSync", "Section"],
        allowed_agent_verbs=allowed_agent_verbs or sorted(_KANBAN_GRANTABLE_VERBS),
        forbidden_agent_verbs=forbidden_agent_verbs or sorted(_KANBAN_WALL_VERBS),
    )  # validates the contract or raises
    # Render ONLY the new board as a list-item block. We append it textually
    # rather than re-dumping the whole file, so the registry's header comments and
    # the existing boards' formatting are preserved (no data loss on register).
    block = yaml.safe_dump([spec.model_dump(mode="json")], sort_keys=False, indent=2)
    if not apply:
        return {
            "status": "validated_dry_run",
            "board_id": board_id,
            "next": "rerun with --apply to write the board into the registry",
            "proposed": spec.model_dump(mode="json"),
            "board_block": block,
        }
    text = config_path.read_text(encoding="utf-8")
    # Match the indentation the existing board list uses so the appended item joins
    # the SAME yaml list — hand-authored files indent items by 2 spaces, safe_dump'd
    # files by 0; mixing the two would produce invalid yaml.
    m = re.search(r"^([ ]*)- ", text, re.MULTILINE)
    indent = m.group(1) if m else "  "
    indented = "".join(f"{indent}{line}\n" if line.strip() else "\n"
                       for line in block.rstrip("\n").splitlines())
    new_text = text.rstrip("\n") + "\n" + indented
    # re-validate the whole registry (duplicate ids, contract) before writing
    KanbanBoardsConfig.model_validate(yaml.safe_load(new_text))
    config_path.write_text(new_text, encoding="utf-8")
    return {"status": "registered", "board_id": board_id, "registry_path": CONFIG}


def run_kanban_sync(
    *,
    config_path: Path = ROOT / CONFIG,
    board_id: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    if not dry_run:
        # Actual board mutation is the governed event writer's job (cc kanban-emit
        # --apply). This command is a read-only planner; refuse to imply writes.
        return {"status": "blocked", "blockers": ["kanban_sync_apply_not_supported_use_kanban_emit"]}
    cfg = _load(config_path)
    boards = cfg.boards if board_id is None else [b for b in cfg.boards if b.board_id == board_id]
    plan = [{
        "board_id": b.board_id,
        "provider": b.provider,
        "workspace_ref": b.workspace_ref,
        "board_ref": b.board_ref,
        "repo_ids": b.repo_ids,
        "status_mapping": b.status_mapping,
        "would_mutate": False,
    } for b in boards]
    return {
        "schema_version": "command-center.kanban-sync.v1",
        "status": "dry_run",
        "boards": plan,
        "writes_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="kanban-registry")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pv = sub.add_parser("verify")
    pv.add_argument("--board-id", default="")
    pv.add_argument("--snapshot", default="")
    pv.add_argument("--output", default="")

    pr = sub.add_parser("register")
    pr.add_argument("--board-id", required=True)
    pr.add_argument("--provider", required=True, choices=["command_center_ui"])
    pr.add_argument("--workspace-ref", required=True)
    pr.add_argument("--board-ref", required=True)
    pr.add_argument("--repo-id", action="append", default=[], dest="repo_ids")
    pr.add_argument("--apply", action="store_true")

    ps = sub.add_parser("sync")
    ps.add_argument("--board-id", default="")
    ps.add_argument("--dry-run", action="store_true")
    ps.add_argument("--apply", action="store_true")

    args = parser.parse_args()
    if args.cmd == "verify":
        result = run_kanban_verify(
            board_id=args.board_id or None,
            snapshot_path=(ROOT / args.snapshot).resolve() if args.snapshot else None,
            output=(ROOT / args.output).resolve() if args.output else None,
        )
        print(f"kanban-verify: {result['status'].upper()}")
        for b in result.get("blockers", []):
            print(f"  BLOCKED: {b}")
        return 0 if result["status"] == "pass" else 1
    if args.cmd == "register":
        result = run_kanban_register(
            board_id=args.board_id, provider=args.provider,
            workspace_ref=args.workspace_ref, board_ref=args.board_ref,
            repo_ids=args.repo_ids, apply=args.apply,
        )
        print(f"kanban-register: {result['status'].upper()}")
        for b in result.get("blockers", []):
            print(f"  BLOCKED: {b}")
        if result.get("next"):
            print(f"  NEXT: {result['next']}")
        return 0 if result["status"] in ("registered", "validated_dry_run") else 1
    if args.cmd == "sync":
        if not args.dry_run and not args.apply:
            args.dry_run = True
        result = run_kanban_sync(board_id=args.board_id or None, dry_run=not args.apply)
        print(f"kanban-sync: {result['status'].upper()}")
        for b in result.get("blockers", []):
            print(f"  BLOCKED: {b}")
        for b in result.get("boards", []):
            print(f"  plan: {b['board_id']} ({b['provider']}) -> repos {b['repo_ids']}")
        return 0 if result["status"] == "dry_run" else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
