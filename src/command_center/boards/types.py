"""Shared board-provider types: capabilities + the fail-loud unsupported error.

Every provider declares what its backend can actually do. Consumers branch on
`BoardCapabilities` flags instead of guessing; an operation a backend cannot
perform raises `UnsupportedOperation` (never a silent no-op), so a caller can
surface the honest degraded state and, where one exists, the manual fallback.
"""
from __future__ import annotations

from dataclasses import dataclass


class UnsupportedOperation(RuntimeError):
    """The backend cannot perform this operation at all (API gap or wall rule).

    Carries the operator-facing remedy so surfaces can show "do X manually"
    instead of a bare error.
    """

    def __init__(self, operation: str, reason: str, remedy: str | None = None):
        self.operation = operation
        self.reason = reason
        self.remedy = remedy
        msg = f"{operation}: {reason}"
        if remedy:
            msg += f" — manual fallback: {remedy}"
        super().__init__(msg)


@dataclass(frozen=True)
class BoardCapabilities:
    """What a board backend can do. Flags describe the BACKEND's API surface;
    a False here is a hard limit (AppFlowy REST gaps) or a deliberate wall
    (agents never delete cards on any provider)."""

    provider: str
    supports_delete_row: bool
    supports_group_by_api: bool
    supports_select_option_create: bool
    supports_mobile_native: bool
    supports_custom_card_rendering: bool
    supports_live_sync: bool


# AppFlowy self-hosted REST API (verified 2026-07-08): row upsert/read only.
# No row delete, no view group-by, no select-option creation (upstream #8665:
# select writes can silently no-op on some versions — why writes verify after).
APPFLOWY_CAPABILITIES = BoardCapabilities(
    provider="appflowy",
    supports_delete_row=False,
    supports_group_by_api=False,
    supports_select_option_create=False,
    supports_mobile_native=True,
    supports_custom_card_rendering=False,
    supports_live_sync=False,
)

# Internal provider: full control over the event log + card store; deletion is
# still False because delete_card is a wall verb on every provider — that is
# governance, not an API gap.
COMMAND_CENTER_CAPABILITIES = BoardCapabilities(
    provider="command_center_ui",
    supports_delete_row=False,
    supports_group_by_api=True,
    supports_select_option_create=True,
    supports_mobile_native=False,
    supports_custom_card_rendering=True,
    supports_live_sync=True,
)
