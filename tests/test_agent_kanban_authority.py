"""Phase 5 — lock the plan §9 agent-Kanban authority matrix against the code
that enforces it (kanban_sync/events.py). This is the executable statement of
"agents may draft/note but may never approve/merge/deploy/publish/delete", so a
future change that widens agent power fails here first.
"""
from __future__ import annotations

import pytest

from command_center.kanban_sync.events import (
    _ACTION_TO_EVENT,
    _WALL_ACTIONS,
    is_human_owned_status,
)

# The plan's authority matrix, restated as data.
MAY_DO = {  # draft tasks, suggest routing, add notes, advance permitted steps
    "add_mission_card", "stage_card", "start_todo", "block_card",
    "reject_card", "finish_todo", "progress_comment",
}
MAY_NOT_DO = {  # delete canonical, approve self, merge, deploy, publish
    "approve_card", "merge", "deploy", "publish", "delete_card", "delete_board",
}


def test_agent_may_do_exactly_the_permitted_verbs():
    # every permitted verb maps to a legal card event…
    assert set(_ACTION_TO_EVENT) == MAY_DO
    # …and none of them is secretly a wall action
    assert MAY_DO.isdisjoint(_WALL_ACTIONS)


def test_agent_cannot_approve_or_delete():
    # the wall verbs are exactly the plan's "may not" set — never mappable to
    # a legal event (there is no _ACTION_TO_EVENT entry for any of them)
    assert _WALL_ACTIONS == MAY_NOT_DO
    for verb in MAY_NOT_DO:
        assert verb not in _ACTION_TO_EVENT


@pytest.mark.parametrize("status", ["Approved", "awaiting_approval",
                                    "Awaiting Approval", "AWAITING APPROVAL"])
def test_agent_cannot_set_human_owned_approval_status(status):
    # the wall is on the status VALUE, not just the action name
    assert is_human_owned_status(status) is True


@pytest.mark.parametrize("status", ["in_progress", "todo", "done", "blocked", None])
def test_ordinary_statuses_are_not_human_owned(status):
    assert is_human_owned_status(status) is False
