"""LedgerWorkGraphStore — durable sibling of store.InMemoryWorkGraphStore, backed
by the Ledger's /work-item, /work-placement, /work-edge endpoints. Same surface,
so WorkGraphService (its cycle checks, one-primary rule, link generation) runs
unchanged over either backend (mirrors intake.LedgerCaptureStore).

Sync, injected httpx.Client; 404 → KeyError (the in-memory contract). Items /
placements / edges are upserted (INSERT OR REPLACE) so the service's
get→model_copy→put update path works durably. Placements/edges are soft-removed;
the canonical item + event history survive a restart.
"""
from __future__ import annotations

import httpx

from .schemas import WorkEdge, WorkEvent, WorkItem, WorkPlacement


class LedgerWorkGraphStore:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    # ---- items ----
    def add_item(self, item: WorkItem) -> None:
        self._upsert("/work-item", item.model_dump())

    def put_item(self, item: WorkItem) -> None:
        self._upsert("/work-item", item.model_dump())

    def get_item(self, work_item_id: str) -> WorkItem:
        return WorkItem(**self._get(f"/work-item/{work_item_id}", work_item_id))

    def list_items(self) -> list[WorkItem]:
        r = self._client.get("/work-items")
        r.raise_for_status()
        return [WorkItem(**d) for d in r.json()]

    # ---- placements ----
    def add_placement(self, placement: WorkPlacement) -> None:
        self._upsert("/work-placement", placement.model_dump())

    def put_placement(self, placement: WorkPlacement) -> None:
        self._upsert("/work-placement", placement.model_dump())

    def get_placement(self, placement_id: str) -> WorkPlacement:
        return WorkPlacement(**self._get(f"/work-placement/{placement_id}", placement_id))

    def placements_for(self, work_item_id: str, *,
                       active_only: bool = True) -> list[WorkPlacement]:
        return self._placements({"work_item_id": work_item_id}, active_only)

    def placements_on_board(self, board_id: str, *,
                            active_only: bool = True) -> list[WorkPlacement]:
        return self._placements({"board_id": board_id}, active_only)

    def list_placements(self, *, active_only: bool = True) -> list[WorkPlacement]:
        return self._placements({}, active_only)

    # ---- edges ----
    def add_edge(self, edge: WorkEdge) -> None:
        self._upsert("/work-edge", edge.model_dump())

    def put_edge(self, edge: WorkEdge) -> None:
        self._upsert("/work-edge", edge.model_dump())

    def get_edge(self, edge_id: str) -> WorkEdge:
        return WorkEdge(**self._get(f"/work-edge/{edge_id}", edge_id))

    def edges(self, *, active_only: bool = True) -> list[WorkEdge]:
        r = self._client.get("/work-edges",
                             params={"active_only": 1 if active_only else 0})
        r.raise_for_status()
        return [WorkEdge(**d) for d in r.json()]

    # ---- events ----
    def append_event(self, event: WorkEvent) -> None:
        r = self._client.post(f"/work-item/{event.work_item_id}/event",
                              json={"ts": event.ts, "kind": event.kind,
                                    "payload": event.payload})
        r.raise_for_status()

    def events(self, work_item_id: str) -> list[WorkEvent]:
        r = self._client.get(f"/work-item/{work_item_id}/events")
        r.raise_for_status()
        return [WorkEvent(**d) for d in r.json()]

    # ---- helpers ----
    def _upsert(self, path: str, body: dict) -> None:
        r = self._client.post(path, json=body)
        r.raise_for_status()

    def _get(self, path: str, ref: str) -> dict:
        r = self._client.get(path)
        if r.status_code == 404:
            raise KeyError(f"no such: {ref}")
        r.raise_for_status()
        return r.json()

    def _placements(self, extra: dict, active_only: bool) -> list[WorkPlacement]:
        params = {**extra, "active_only": 1 if active_only else 0}
        r = self._client.get("/work-placements", params=params)
        r.raise_for_status()
        return [WorkPlacement(**d) for d in r.json()]
