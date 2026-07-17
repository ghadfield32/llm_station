"""LedgerWorkGraphStore — durable sibling of store.InMemoryWorkGraphStore, backed
by the Ledger's /work-item, /work-placement, /work-edge endpoints. Same surface,
so WorkGraphService (its cycle checks, one-primary rule, link generation) runs
unchanged over either backend (mirrors intake.LedgerCaptureStore).

Sync, injected httpx.Client; 404 → KeyError (the in-memory contract). Items /
placements / edges are upserted. WorkItems are created once and subsequently
changed through field-specific transactional updates. Placements/edges are soft-removed;
the canonical item + event history survive a restart.
"""
from __future__ import annotations

import httpx

from .schemas import WorkEdge, WorkEvent, WorkItem, WorkPlacement
from .store import ConcurrentWorkItemUpdate, WorkGraphIntegrityConflict


class LedgerWorkGraphStore:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    # ---- items ----
    def add_item(self, item: WorkItem) -> None:
        raise WorkGraphIntegrityConflict(
            "durable WorkItem creation requires its atomic created event"
        )

    def add_item_with_event(self, item: WorkItem, event: WorkEvent) -> None:
        self._upsert("/work-item", {
            **item.model_dump(),
            "event": {"ts": event.ts, "kind": event.kind, "payload": event.payload},
        })

    def update_item_fields(
        self, work_item_id: str, *, fields: dict,
        event: WorkEvent | None = None,
    ) -> WorkItem:
        if event is None:
            raise WorkGraphIntegrityConflict(
                "durable WorkItem updates require an atomic audit event"
            )
        body: dict = {"fields": fields}
        body["event"] = {
            "ts": event.ts, "kind": event.kind, "payload": event.payload,
        }
        r = self._client.patch(f"/work-item/{work_item_id}", json=body)
        if r.status_code == 404:
            raise KeyError(f"no such: {work_item_id}")
        r.raise_for_status()
        return WorkItem(**r.json())

    def compare_and_set_description(
        self, work_item_id: str, *, expected_updated_at: str,
        expected_description: str, description: str, updated_at: str,
    ) -> tuple[WorkItem, bool]:
        r = self._client.put(
            f"/work-item/{work_item_id}/description",
            json={
                "expected_updated_at": expected_updated_at,
                "expected_description": expected_description,
                "description": description,
                "updated_at": updated_at,
            },
        )
        if r.status_code == 404:
            raise KeyError(f"no such: {work_item_id}")
        if r.status_code == 409:
            raise ConcurrentWorkItemUpdate(
                "work item changed; refresh its story before editing the description"
            )
        r.raise_for_status()
        body = r.json()
        return WorkItem(**body["item"]), bool(body["event_appended"])

    def get_item(self, work_item_id: str) -> WorkItem:
        return WorkItem(**self._get(f"/work-item/{work_item_id}", work_item_id))

    def list_items(self) -> list[WorkItem]:
        r = self._client.get("/work-items")
        r.raise_for_status()
        return [WorkItem(**d) for d in r.json()]

    # ---- placements ----
    def add_placement(self, placement: WorkPlacement) -> None:
        raise WorkGraphIntegrityConflict(
            "durable placement creation requires its atomic placement_added event"
        )

    def add_placement_with_event(
        self, placement: WorkPlacement, event: WorkEvent,
    ) -> WorkPlacement:
        r = self._client.post("/work-placement", json={
            **placement.model_dump(),
            "event": {"ts": event.ts, "kind": event.kind, "payload": event.payload},
        })
        self._raise_integrity_conflict(r)
        r.raise_for_status()
        return WorkPlacement(**r.json())

    def remove_placement_with_event(
        self, placement_id: str, *, removed_at: str,
    ) -> WorkPlacement:
        r = self._client.post(
            f"/work-placement/{placement_id}/remove", json={"removed_at": removed_at},
        )
        if r.status_code == 404:
            raise KeyError(f"no such: {placement_id}")
        self._raise_integrity_conflict(r)
        r.raise_for_status()
        return WorkPlacement(**r.json())

    def repair_placement_with_event(
        self, placement: WorkPlacement, event: WorkEvent,
    ) -> WorkPlacement:
        r = self._client.post(
            f"/work-placement/{placement.placement_id}/repair",
            json={
                "placement": placement.model_dump(),
                "event": {
                    "ts": event.ts, "kind": event.kind, "payload": event.payload,
                },
            },
        )
        if r.status_code == 404:
            raise KeyError(f"no such: {placement.placement_id}")
        self._raise_integrity_conflict(r)
        r.raise_for_status()
        return WorkPlacement(**r.json())

    def put_placement(self, placement: WorkPlacement) -> None:
        raise WorkGraphIntegrityConflict(
            "durable placements cannot be replaced outside an audited operation"
        )

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
        raise WorkGraphIntegrityConflict(
            "durable edge creation requires its atomic edge_added event"
        )

    def add_edge_with_event(self, edge: WorkEdge, event: WorkEvent) -> WorkEdge:
        r = self._client.post("/work-edge", json={
            **edge.model_dump(),
            "event": {"ts": event.ts, "kind": event.kind, "payload": event.payload},
        })
        self._raise_integrity_conflict(r)
        r.raise_for_status()
        return WorkEdge(**r.json())

    def remove_edge_with_event(self, edge_id: str, *, removed_at: str) -> WorkEdge:
        r = self._client.post(
            f"/work-edge/{edge_id}/remove", json={"removed_at": removed_at},
        )
        if r.status_code == 404:
            raise KeyError(f"no such: {edge_id}")
        self._raise_integrity_conflict(r)
        r.raise_for_status()
        return WorkEdge(**r.json())

    def put_edge(self, edge: WorkEdge) -> None:
        raise WorkGraphIntegrityConflict(
            "durable edges cannot be replaced outside an audited operation"
        )

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
        self._raise_integrity_conflict(r)
        r.raise_for_status()

    @staticmethod
    def _raise_integrity_conflict(response: httpx.Response) -> None:
        if response.status_code == 409:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            raise WorkGraphIntegrityConflict(detail or "work graph integrity conflict")

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
