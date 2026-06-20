"""Wire the governed action layer to the kanban event log (one funnel, all surfaces).

`wrap_governed_dispatch` wraps the channels' verb->callable dispatch so that a
SUCCESSFUL governed card/todo verb (on Discord, SMS, the in-app console, …)
appends a `KanbanEvent` — making the action layer the single legal writer the
projections read from. Non-governed verbs (search/list_*/read_item/…) pass
through untouched. If the surface can't be tagged honestly or no board is known,
the dispatch is returned unwrapped (no fabricated board/surface).

The event is emitted AFTER the verb returns: a failed action emits nothing (the
wall/failure is preserved), and an event-log write failure raises (never hidden).
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from command_center.kanban_sync.events import EventLog, emit_event

# verb -> the canonical status the card lands in. The verb name IS the action;
# emit_event maps the action to its event type. Wall verbs are absent by design.
_GOVERNED_VERBS = {
    "add_mission_card": "Backlog", "stage_card": "Ready", "block_card": "Blocked",
    "reject_card": "Rejected", "start_todo": "In Progress", "finish_todo": "Done",
}
# Channel surface string -> the KanbanEvent source_surface literal.
_SURFACE_MAP = {"app": "internal_ui", "console": "internal_ui", "ui": "internal_ui"}
_VALID_SURFACES = frozenset({"discord", "slack", "telegram", "whatsapp", "sms",
                             "internal_ui", "daily_dag", "repo_agent"})


def _card_id_from(args: tuple, kwargs: dict) -> str | None:
    for key in ("title", "task"):
        if kwargs.get(key):
            return str(kwargs[key])
    return str(args[0]) if args else None


def _emitting(fn: Callable[..., Any], *, verb: str, status_after: str,
              surface: str, board_id: str, log: EventLog) -> Callable[..., Any]:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = fn(*args, **kwargs)  # the real governed verb; wall enforced inside
        card_id = _card_id_from(args, kwargs)
        if card_id:
            emit_event(log, action=verb, board_id=board_id, card_id=card_id,
                       source_surface=surface, actor_type="agent",
                       status_after=status_after)
        return result
    return wrapper


def wrap_governed_dispatch(
    dispatch: dict[str, Callable[..., Any]], *,
    surface: str, board_id: str | None, log: EventLog,
) -> dict[str, Callable[..., Any]]:
    """Return a dispatch whose governed verbs emit a KanbanEvent on success."""
    tag = _SURFACE_MAP.get(surface, surface)
    if tag not in _VALID_SURFACES or not board_id:
        return dispatch  # cannot tag the event honestly — leave the layer untouched
    wrapped = dict(dispatch)
    for verb, status_after in _GOVERNED_VERBS.items():
        fn = dispatch.get(verb)
        if fn is not None:
            wrapped[verb] = _emitting(fn, verb=verb, status_after=status_after,
                                      surface=tag, board_id=board_id, log=log)
    return wrapped
