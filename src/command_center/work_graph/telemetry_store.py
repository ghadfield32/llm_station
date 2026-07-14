"""Stores for router-correction telemetry: an in-memory store and a durable
Ledger-backed sibling with the SAME surface, so RoutingTelemetryService never
cares which backend it holds (mirrors the work-graph / capture stores).

Corrections are append-only ground truth: `add` records one, `get`/`list` read
them back. The Ledger store is the one that matters in practice — telemetry is
only evidence if it survives a restart; the in-memory store is for tests and a
Ledger-less dev. 404 → KeyError (the in-memory contract).
"""
from __future__ import annotations

import httpx

from .schemas import RoutingCorrection


class InMemoryRoutingTelemetryStore:
    def __init__(self) -> None:
        self._by_id: dict[str, RoutingCorrection] = {}
        self._order: list[str] = []

    def add(self, correction: RoutingCorrection) -> None:
        if correction.correction_id not in self._by_id:
            self._order.append(correction.correction_id)
        self._by_id[correction.correction_id] = correction

    def get(self, correction_id: str) -> RoutingCorrection:
        c = self._by_id.get(correction_id)
        if c is None:
            raise KeyError(f"no such routing correction: {correction_id}")
        return c

    def list(self, *, since: str | None = None, board: str | None = None,
             limit: int | None = None) -> list[RoutingCorrection]:
        out = [self._by_id[i] for i in self._order]
        if since is not None:
            out = [c for c in out if c.at >= since]
        if board is not None:
            out = [c for c in out if c.chosen_board_id == board]
        if limit is not None:
            out = out[:limit]
        return out


class LedgerRoutingTelemetryStore:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def add(self, correction: RoutingCorrection) -> None:
        r = self._client.post("/routing-correction", json=correction.model_dump())
        r.raise_for_status()

    def get(self, correction_id: str) -> RoutingCorrection:
        r = self._client.get(f"/routing-correction/{correction_id}")
        if r.status_code == 404:
            raise KeyError(f"no such routing correction: {correction_id}")
        r.raise_for_status()
        return RoutingCorrection(**r.json())

    def list(self, *, since: str | None = None, board: str | None = None,
             limit: int | None = None) -> list[RoutingCorrection]:
        params: dict[str, object] = {}
        if since is not None:
            params["since"] = since
        if board is not None:
            params["board"] = board
        if limit is not None:
            params["limit"] = limit
        r = self._client.get("/routing-corrections", params=params)
        r.raise_for_status()
        return [RoutingCorrection(**d) for d in r.json()]
