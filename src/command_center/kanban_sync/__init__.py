"""Live kanban state: one event stream, first-party projections.

The Ledger / kanban event log is the source of truth. Surfaces (internal UI, Discord/SMS, and the daily DAG) are projections — they never hold their own
authority. The governed action layer is the only legal writer: every kanban
change is recorded as a `KanbanEvent`, and projections are derived from those
events. Wall actions (approve/merge/deploy/delete) can never emit a legal event.
"""
from command_center.kanban_sync.events import (
    ALLOWED_EVENT_TYPES,
    FORBIDDEN_EVENT_TYPES,
    GovernanceViolation,
    KanbanEvent,
    EventLog,
    emit_event,
    is_human_owned_status,
    normalize_status,
)
from command_center.kanban_sync.projection import (
    project_cards,
    reconcile,
    verify_projection,
)
from command_center.kanban_sync.wiring import wrap_governed_dispatch
from command_center.kanban_sync.dependencies import (
    CardDependencies,
    is_card_blocked,
    parse_card_dependencies,
    unmet_blockers,
)

__all__ = [
    "ALLOWED_EVENT_TYPES", "FORBIDDEN_EVENT_TYPES", "GovernanceViolation",
    "KanbanEvent", "EventLog", "emit_event", "is_human_owned_status",
    "normalize_status",
    "project_cards", "reconcile", "verify_projection",
    "wrap_governed_dispatch",
    "CardDependencies", "is_card_blocked", "parse_card_dependencies", "unmet_blockers",
]
