"""First-party Kanban opportunity feed for the self-improvement scan."""
from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from command_center.boards.command_center_provider import CommandCenterBoardProvider
from command_center.kanban_sync.events import EventLog
from command_center.schemas.contracts import KanbanBoardsConfig

DEFAULT_OUTPUT_BOARD_ID = "self_improvement"


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _card_title(card: dict[str, Any]) -> str:
    for key in ("title", "task", "role_title", "hook", "action", "name", "card_id"):
        if card.get(key):
            return str(card[key])
    return "untitled card"


def all_board_opportunity_records(
    *,
    board_config_path: str | Path,
    board_store_dir: str | Path,
    event_log_path: str | Path,
    output_board_id: str = DEFAULT_OUTPUT_BOARD_ID,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Read active cards from every registered board except the output board."""
    raw = yaml.safe_load(Path(board_config_path).read_text(encoding="utf-8"))
    registry = KanbanBoardsConfig.model_validate(raw)
    log = EventLog(event_log_path)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    records: list[dict[str, Any]] = []
    latest_event: dict[tuple[str, str], datetime] = {}
    for event in log.read():
        stamp = _parse_time(event.created_at)
        if stamp is not None:
            latest_event[(event.board_id, event.card_id)] = stamp

    for spec in registry.boards:
        if spec.board_id == output_board_id:
            continue
        provider = CommandCenterBoardProvider(
            board_id=spec.board_id, event_log=log, store_dir=Path(board_store_dir),
            status_mapping=dict(spec.status_mapping),
        )
        terminal = {str(spec.status_mapping[key]).casefold() for key in ("done", "rejected")}
        blocked_label = str(spec.status_mapping["blocked"]).casefold()
        for card in provider.list_cards():
            status = str(card.get("status") or "")
            if status.casefold() in terminal:
                continue
            card_id = str(card.get("card_id") or "")
            stamp = latest_event.get((spec.board_id, card_id))
            if stamp is None:
                for key in ("updated_at", "last_updated", "created_at", "created"):
                    stamp = _parse_time(card.get(key))
                    if stamp is not None:
                        break
            age_days = max(0.0, (current - stamp).total_seconds() / 86400) if stamp else 0.0
            records.append({
                "title": _card_title(card), "column": status or "Unstaged",
                "age_days": age_days,
                "blocked": bool(card.get("blocked")) or status.casefold() == blocked_label,
                "board_id": spec.board_id, "card_id": card_id,
                "repo_ids": list(spec.repo_ids),
                "repository_reason": (
                    f"This opportunity is on {spec.board_id}, which is registered to "
                    f"{', '.join(spec.repo_ids)}."
                    if spec.repo_ids else
                    f"This opportunity is cross-system work from {spec.board_id}; "
                    "review it under All repositories."
                ),
            })
    return records


def fetch_all_board_records() -> list[dict[str, Any]]:
    """Environment-bound live fetcher used by the scheduled Airflow task."""
    config = os.environ.get(
        "SELF_IMPROVEMENT_BOARD_CONFIG",
        os.environ.get("KANBAN_BACKUP_BOARD_CONFIG", "configs/kanban_boards.yaml"),
    )
    output = os.environ.get("SELF_IMPROVEMENT_BOARD_ID", DEFAULT_OUTPUT_BOARD_ID)
    records = all_board_opportunity_records(
        board_config_path=config,
        board_store_dir=os.environ.get("KANBAN_BOARD_STORE", "generated/boards"),
        event_log_path=os.environ.get("KANBAN_EVENT_LOG", "generated/kanban-events.jsonl"),
        output_board_id=output,
    )
    registry = KanbanBoardsConfig.model_validate(
        yaml.safe_load(Path(config).read_text(encoding="utf-8")))
    scanned = [board.board_id for board in registry.boards if board.board_id != output]
    print(f"[self_improvement_daily] scanned {len(scanned)} registered boards "
          f"({len(records)} active cards); output excluded: {output}; boards={scanned}")
    return records
