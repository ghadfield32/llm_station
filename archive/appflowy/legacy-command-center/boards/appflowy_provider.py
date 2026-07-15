"""AppFlowy board provider: wraps the REST write path, fails loud on API gaps.

The self-hosted AppFlowy REST API can upsert/read rows but cannot delete rows,
set a board view's group-by, or create select options (client-only operations
over its sync protocol). Those methods raise UnsupportedOperation carrying the
manual remedy that `cc job-search board-doctor` and READINESS_FAQ document —
never a silent no-op. Reads are injectable: without a reader this provider
reports snapshot()=None so verify/reconcile stay honestly DEGRADED.
"""
from __future__ import annotations

from typing import Any, Callable

from command_center.boards.provider import BoardProvider
from command_center.boards.types import APPFLOWY_CAPABILITIES, BoardCapabilities, UnsupportedOperation
from command_center.kanban_sync.events import KanbanEvent, is_human_owned_status
from command_center.kanban_sync.projection import AppFlowyProjection

_GROUP_BY_REMEDY = (
    "open the board in AppFlowy -> Settings -> Group by -> Status "
    "(one-time; see docs/job_search/READINESS_FAQ.md)"
)


class AppFlowyBoardProvider(BoardProvider):
    def __init__(self, *, board_id: str, env: dict[str, str],
                 snapshot_reader: Callable[[], dict[str, dict[str, Any]] | None] | None = None,
                 client_factory: Callable[..., Any] | None = None):
        self.board_id = board_id
        self._projection = AppFlowyProjection(env=env, client_factory=client_factory)
        self._snapshot_reader = snapshot_reader
        self._env = env

    def capabilities(self) -> BoardCapabilities:
        return APPFLOWY_CAPABILITIES

    def list_cards(self) -> list[dict[str, Any]]:
        snap = self.snapshot()
        if snap is None:
            return []
        return [dict(card, card_id=card_id) for card_id, card in snap.items()]

    def snapshot(self) -> dict[str, dict[str, Any]] | None:
        if self._snapshot_reader is None:
            return None
        return self._snapshot_reader()

    def upsert_card(self, card_id: str, fields: dict[str, Any], *,
                    status: str | None = None) -> dict[str, Any]:
        if is_human_owned_status(status):
            return {"status": "refused", "card_id": card_id,
                    "reason": "refuse_to_write_human_owned_status", "wrote": False}
        if not self._projection.configured():
            return {"status": "degraded", "card_id": card_id,
                    "reason": "appflowy_projection_not_configured", "wrote": False}
        cells = dict(fields)
        if status is not None:
            cells["Status"] = status
        factory = self._projection._client_factory
        if factory is None:
            import httpx
            factory = httpx.Client
        env, refs = self._projection.env, self._projection.refs
        base = env[refs["base"]].rstrip("/")
        with factory(timeout=30) as client:
            auth = client.post(f"{base}/gotrue/token?grant_type=password",
                               json={"email": env[refs["user"]],
                                     "password": env[refs["password"]]})
            auth.raise_for_status()
            token = auth.json()["access_token"]
            resp = client.put(
                f"{base}/api/workspace/{env[refs['workspace']]}/database/"
                f"{env[refs['database']]}/row",
                headers={"Authorization": f"Bearer {token}"},
                json={"pre_hash": card_id, "cells": cells, "document": None})
            resp.raise_for_status()
        return {"status": "written", "card_id": card_id, "wrote": True}

    def write_status(self, event: KanbanEvent, *,
                     status_label: str | None = None) -> dict[str, Any]:
        return self._projection.write_through(event, status_label=status_label)

    def delete_row(self, card_id: str) -> dict[str, Any]:
        raise UnsupportedOperation(
            "delete_row",
            "AppFlowy's self-hosted REST API has no row-delete endpoint",
            "delete the card in the AppFlowy app (right-click -> Delete)")

    def set_group_by(self, field_name: str) -> dict[str, Any]:
        raise UnsupportedOperation(
            "set_group_by",
            "AppFlowy's REST API cannot set a board view's group-by field",
            _GROUP_BY_REMEDY)

    def create_select_option(self, field_name: str, option: str) -> dict[str, Any]:
        raise UnsupportedOperation(
            "create_select_option",
            "AppFlowy's REST API cannot create select options (and select "
            "writes can silently no-op, upstream #8665)",
            "add the option in the AppFlowy app, then re-run board-doctor")

    def validate(self) -> dict[str, Any]:
        out = super().validate()
        out["configured"] = self._projection.configured()
        out["board_id"] = self.board_id
        return out
