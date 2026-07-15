"""The first-party BoardProvider contract.

All status writes go through the governed event path and refuse human-owned
approval statuses. Consumers depend on the registry entry and never on an
external board client.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from command_center.boards.types import BoardCapabilities
from command_center.kanban_sync.events import EventLog, KanbanEvent


class BoardProvider(ABC):
    """Backend-agnostic board operations. Implementations must fail loud
    (UnsupportedOperation) for anything their backend cannot do."""

    @abstractmethod
    def capabilities(self) -> BoardCapabilities: ...

    @abstractmethod
    def list_cards(self) -> list[dict[str, Any]]:
        """Current cards with status + known fields. May be [] when the
        backend is unreachable/unconfigured — pair with snapshot() semantics."""

    @abstractmethod
    def snapshot(self) -> dict[str, dict[str, Any]] | None:
        """Card_id -> {status, ...} for verify/reconcile, or None when the
        surface cannot be read (callers report DEGRADED, never guess)."""

    @abstractmethod
    def upsert_card(self, card_id: str, fields: dict[str, Any], *,
                    status: str | None = None) -> dict[str, Any]:
        """Create/update a card's fields (and optionally its status label).
        Never touches human-owned approval statuses."""

    @abstractmethod
    def write_status(self, event: KanbanEvent, *,
                     status_label: str | None = None) -> dict[str, Any]:
        """Project one governed kanban event's status onto the surface."""

    # Operations that are API gaps or wall rules on some backends. Implementations
    # either perform them or raise UnsupportedOperation with the manual remedy.
    @abstractmethod
    def delete_row(self, card_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def set_group_by(self, field_name: str) -> dict[str, Any]: ...

    @abstractmethod
    def create_select_option(self, field_name: str, option: str) -> dict[str, Any]: ...

    def validate(self) -> dict[str, Any]:
        """Cheap health summary; providers may extend."""
        caps = self.capabilities()
        return {"provider": caps.provider, "capabilities": caps.__dict__}


def provider_for_board(
    spec: Any,
    *,
    env: dict[str, str] | None = None,
    event_log: EventLog | None = None,
    store_dir: str | Path | None = None,
) -> BoardProvider:
    """Build the first-party provider for a registry entry."""
    from command_center.boards.command_center_provider import CommandCenterBoardProvider

    if spec.provider == "command_center_ui":
        log = event_log or EventLog("generated/kanban-events.jsonl")
        store = Path(store_dir) if store_dir else Path("generated/boards")
        return CommandCenterBoardProvider(
            board_id=spec.board_id, event_log=log, store_dir=store,
            status_mapping=dict(spec.status_mapping))
    raise ValueError(f"unknown board provider {spec.provider!r}")
