"""Provider-agnostic board layer. See docs/reviews/2026-07-08-cockpit-decision.md."""
from command_center.boards.provider import BoardProvider, provider_for_board
from command_center.boards.types import (
    APPFLOWY_CAPABILITIES, COMMAND_CENTER_CAPABILITIES,
    BoardCapabilities, UnsupportedOperation,
)

__all__ = [
    "APPFLOWY_CAPABILITIES", "COMMAND_CENTER_CAPABILITIES", "BoardCapabilities",
    "BoardProvider", "UnsupportedOperation", "provider_for_board",
]
