"""Observer-only desktop target evidence verifier.

This validates the declared desktop target against a live/snapshot board
artifact. It does not click, type, move cards, mutate external board runtime, or read secrets.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from command_center.schemas import AutonomyConfig

ROOT = Path(__file__).resolve().parents[3]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _string_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, bool | int | float):
        yield str(value)
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _string_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _string_values(nested)


def _card_values(column_name: str, card: dict[str, Any]) -> list[str]:
    values = [column_name]
    values.extend(_string_values(card.get("title")))
    values.extend(_string_values(card.get("meta")))
    values.extend(_string_values(card.get("fields") or {}))
    return values


def _find_card(snapshot: dict[str, Any], board_name: str, card_ref: str) -> tuple[dict[str, Any], str] | None:
    for board in snapshot.get("boards", []):
        if board.get("board") != board_name:
            continue
        if board.get("error"):
            return None
        for column in board.get("columns", []):
            column_name = str(column.get("name") or "")
            for card in column.get("cards", []):
                fields = card.get("fields") or {}
                candidates = {
                    str(card.get("title") or ""),
                    str(fields.get("CardKey") or ""),
                }
                if card_ref in candidates:
                    return card, column_name
    return None


def verify_desktop_targets(
    *,
    config_path: Path = ROOT / "configs" / "autonomy.yaml",
    output: Path | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    cfg = AutonomyConfig.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")))
    targets: list[dict[str, Any]] = []
    blockers: list[str] = []

    for target in cfg.desktop_targets:
        target_blockers: list[str] = []
        snapshot_ref = target.snapshot_evidence_ref or ""
        snapshot_path = Path(snapshot_ref)
        if not snapshot_path.is_absolute():
            snapshot_path = root / snapshot_path

        result: dict[str, Any] = {
            "target_id": target.target_id,
            "enabled": target.enabled,
            "board": target.board,
            "card_ref": target.card_ref,
            "snapshot_evidence_ref": snapshot_ref,
            "snapshot_present": snapshot_path.is_file(),
            "verifier_type": target.verifier.type,
            "must_show": target.verifier.must_show,
            "writes_performed": False,
        }

        if not snapshot_path.is_file():
            target_blockers.append(f"desktop_target_{target.target_id}_snapshot_missing")
        elif target.board and target.card_ref:
            snapshot = _load_json(snapshot_path)
            result["snapshot_generated_at"] = snapshot.get("generated_at")
            found = _find_card(snapshot, target.board, target.card_ref)
            if found is None:
                target_blockers.append(f"desktop_target_{target.target_id}_card_not_found")
                result["card_found"] = False
            else:
                card, column_name = found
                values = _card_values(column_name, card)
                fields = card.get("fields") or {}
                result.update({
                    "card_found": True,
                    "column": column_name,
                    "title": card.get("title"),
                    "status_field": fields.get("Status"),
                })
                missing = [
                    expected
                    for expected in target.verifier.must_show
                    if expected not in values
                ]
                if missing:
                    for expected in missing:
                        target_blockers.append(
                            f"desktop_target_{target.target_id}_missing_verifier_value_{expected}"
                        )
        else:
            target_blockers.append(f"desktop_target_{target.target_id}_missing_board_or_card_ref")

        result["status"] = "pass" if not target_blockers else "blocked"
        result["blockers"] = target_blockers
        targets.append(result)
        blockers.extend(target_blockers)

    evidence = {
        "status": "pass" if not blockers else "blocked",
        "targets": targets,
        "blockers": blockers,
        "writes_performed": False,
        "secrets_printed": False,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(prog="desktop-target-verify")
    parser.add_argument("--config", default="configs/autonomy.yaml")
    parser.add_argument(
        "--output",
        default="evaluation/system-validation/20260616-autonomy-contracts/desktop-target-verify.json",
    )
    args = parser.parse_args()

    result = verify_desktop_targets(
        config_path=(ROOT / args.config).resolve(),
        output=(ROOT / args.output).resolve(),
    )
    print(f"desktop-target-verify: {result['status'].upper()}")
    for blocker in result.get("blockers", []):
        print(f"  BLOCKED: {blocker}")
    print(f"evidence -> {args.output}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
