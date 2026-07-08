"""Internal (command_center_ui) board provider over the kanban event log.

Status truth = the fold of governed events (project_cards); rich card fields
live in a per-board JSON card store (per-deployment runtime state under
generated/boards/, like the event log itself). Status changes go ONLY through
emit_event, so the wall (no approve/merge/delete, no human-owned statuses)
holds identically on the internal surface. Field upserts never carry status.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from command_center.boards.provider import BoardProvider
from command_center.boards.types import (
    COMMAND_CENTER_CAPABILITIES, BoardCapabilities, UnsupportedOperation,
)
from command_center.kanban_sync.events import (
    EventLog, KanbanEvent, emit_event, is_human_owned_status,
)
from command_center.kanban_sync.projection import project_cards

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_name(card_id: str) -> str:
    # card ids come from configs/hashes, but the store must never let one
    # traverse paths — replace anything outside a safe charset.
    return _SAFE_ID_RE.sub("_", card_id) or "_"


class CommandCenterBoardProvider(BoardProvider):
    def __init__(self, *, board_id: str, event_log: EventLog, store_dir: Path,
                 status_mapping: dict[str, str] | None = None):
        self.board_id = board_id
        self.log = event_log
        self.store_dir = Path(store_dir) / board_id
        self.status_mapping = status_mapping or {}

    def capabilities(self) -> BoardCapabilities:
        return COMMAND_CENTER_CAPABILITIES

    # -- card field store (runtime state; status never lives here) ----------
    def _card_path(self, card_id: str) -> Path:
        return self.store_dir / f"{_safe_name(card_id)}.json"

    def _read_fields(self, card_id: str) -> dict[str, Any]:
        path = self._card_path(card_id)
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def list_cards(self) -> list[dict[str, Any]]:
        folded = self._fold()
        out = []
        for card_id, card in folded.items():
            fields = self._read_fields(card_id)
            fields.pop("status", None)  # status truth is the fold, not the store
            out.append({**fields, **card})
        # stored cards that predate any status event still exist (created via
        # upsert only) — surface them with status None rather than hiding them
        if self.store_dir.is_dir():
            for path in sorted(self.store_dir.glob("*.json")):
                fields = json.loads(path.read_text(encoding="utf-8"))
                card_id = fields.get("card_id")
                if card_id and card_id not in folded:
                    fields.pop("status", None)
                    out.append({"status": None, "board_id": self.board_id,
                                **fields, "card_id": card_id})
        return out

    def _fold(self) -> dict[str, dict[str, Any]]:
        events = [e for e in self.log.read() if e.board_id == self.board_id]
        return project_cards(events)

    def snapshot(self) -> dict[str, dict[str, Any]] | None:
        return self._fold()

    def upsert_card(self, card_id: str, fields: dict[str, Any], *,
                    status: str | None = None) -> dict[str, Any]:
        if is_human_owned_status(status):
            return {"status": "refused", "card_id": card_id,
                    "reason": "refuse_to_write_human_owned_status", "wrote": False}
        stored = self._read_fields(card_id)
        stored.update(fields)
        stored["card_id"] = card_id
        stored.pop("status", None)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._card_path(card_id).write_text(
            json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
        result: dict[str, Any] = {"status": "written", "card_id": card_id, "wrote": True}
        if status is not None:
            # a status on upsert is a card creation — route through the governed
            # writer so the wall applies (raises GovernanceViolation on abuse)
            emit_event(self.log, action="add_mission_card", board_id=self.board_id,
                       card_id=card_id, source_surface="internal_ui",
                       actor_type="agent", status_after=status)
            result["status_label"] = status
        return result

    def write_status(self, event: KanbanEvent, *,
                     status_label: str | None = None) -> dict[str, Any]:
        # the event log IS this provider's surface: an already-emitted event is
        # already projected; nothing further to write. Refuse human-owned labels
        # for parity with the AppFlowy projection contract.
        label = status_label or event.status_after
        if is_human_owned_status(label):
            return {"status": "refused", "card_id": event.card_id,
                    "reason": "refuse_to_write_human_owned_status", "wrote": False}
        return {"status": "written", "card_id": event.card_id,
                "status_label": label, "wrote": True,
                "note": "event log is the internal surface; fold reflects it"}

    def delete_row(self, card_id: str) -> dict[str, Any]:
        raise UnsupportedOperation(
            "delete_row",
            "delete_card is a wall verb on every provider (human-only)",
            "a human may archive the card from the cockpit or remove the store file")

    def set_group_by(self, field_name: str) -> dict[str, Any]:
        return {"status": "written", "group_by": field_name, "wrote": True}

    def create_select_option(self, field_name: str, option: str) -> dict[str, Any]:
        return {"status": "written", "field": field_name, "option": option, "wrote": True}

    def validate(self) -> dict[str, Any]:
        out = super().validate()
        out["board_id"] = self.board_id
        out["event_log"] = str(self.log.path)
        out["card_store"] = str(self.store_dir)
        out["n_cards"] = len(self._fold())
        return out
