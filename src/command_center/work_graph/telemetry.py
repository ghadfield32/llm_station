"""RoutingTelemetryService — record and read back router-correction evidence.

It only RECORDS and READS; it derives no rules. `record` stamps a correction with
an id + timestamp and computes `accepted` (did the router's suggestion match the
human's choice). `summary` is a read-only evidence surface (counts + acceptance
rate + chosen-board tallies) — NOT a rule set. Deriving evidence-backed board
rules from this log is a later, deliberately separate calibration phase; keeping
the raw log honest and un-aggregated is the whole point. Clock + id injected →
hermetic.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence

from .schemas import RoutingCorrection
from .telemetry_store import InMemoryRoutingTelemetryStore


class RoutingTelemetryService:
    def __init__(self, store: InMemoryRoutingTelemetryStore, *,
                 clock: Callable[[], str], id_factory: Callable[[], str]) -> None:
        self._store = store
        self._clock = clock
        self._id = id_factory

    def record(self, title: str, *, ref: str | None = None,
               suggested_board_id: str | None = None,
               chosen_board_id: str | None = None,
               matched_keywords: Sequence[str] = (),
               conversation_id: str | None = None,
               capture_id: str | None = None,
               source: str = "chat") -> RoutingCorrection:
        """Record one human correction. Raises ValueError on empty title."""
        title = (title or "").strip()
        if not title:
            raise ValueError("routing correction title must not be empty")
        accepted = (chosen_board_id is not None
                    and chosen_board_id == suggested_board_id)
        correction = RoutingCorrection(
            correction_id=self._id(), at=self._clock(), title=title, ref=ref,
            suggested_board_id=suggested_board_id,
            chosen_board_id=chosen_board_id, accepted=accepted,
            matched_keywords=list(matched_keywords),
            conversation_id=conversation_id, capture_id=capture_id, source=source)
        self._store.add(correction)
        return correction

    def get(self, correction_id: str) -> RoutingCorrection:
        return self._store.get(correction_id)

    def list(self, *, since: str | None = None, board: str | None = None,
             limit: int | None = None) -> list[RoutingCorrection]:
        return self._store.list(since=since, board=board, limit=limit)

    def summary(self) -> dict:
        """Read-only evidence surface: totals + acceptance rate + chosen-board
        tallies. NOT a rule set — acceptance_rate is None (not a made-up value)
        when there is no evidence yet."""
        rows = self._store.list()
        total = len(rows)
        accepted = sum(1 for c in rows if c.accepted)
        by_board: dict[str, int] = {}
        for c in rows:
            if c.chosen_board_id:
                by_board[c.chosen_board_id] = by_board.get(c.chosen_board_id, 0) + 1
        return {"total": total, "accepted": accepted,
                "acceptance_rate": (accepted / total) if total else None,
                "by_chosen_board": by_board}
