"""Durable work graph — the Ledger-backed store makes work items, their board
placements, and typed edges survive a cockpit/worker restart (the in-memory
store's Phase-C-2 successor). Proves the canonical WorkGraphService logic (one
primary, acyclic blocking-relations, ordered events, link generation) runs
UNCHANGED over the durable backend, exactly as it does over the in-memory store.

No Docker: the Ledger FastAPI app is loaded via importlib + Starlette TestClient
(httpx-compatible), like test_capture_ledger_store.py. A "restart" is modelled as
a SECOND service/store reading the SAME Ledger db.
"""
from __future__ import annotations

import importlib.util
import itertools
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from command_center.work_graph import (
    LedgerWorkGraphStore,
    WorkPlacement,
    WorkGraphError,
    WorkGraphService,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_APP = REPO_ROOT / "services/ledger/app.py"


@pytest.fixture
def ledger_client(tmp_path):
    os.environ["LEDGER_DB"] = str(tmp_path / "ledger.db")
    spec = importlib.util.spec_from_file_location(
        "ledger_app_workgraph_store_test", LEDGER_APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from starlette.testclient import TestClient
    return TestClient(mod.app)


def _svc(client) -> WorkGraphService:
    # Each service gets its OWN id/clock counters (a real restart re-seeds them);
    # reads never allocate ids, so re-seeding is safe for the "fresh service" tests.
    ids = itertools.count(1)
    ticks = itertools.count(1)
    return WorkGraphService(
        LedgerWorkGraphStore(client),
        clock=lambda: f"2026-07-13T00:00:{next(ticks):02d}+00:00",
        id_factory=lambda prefix: f"{prefix}-{next(ids)}")


def _tagged_svc(client, tag: str) -> WorkGraphService:
    ids = itertools.count(1)
    ticks = itertools.count(1)
    return WorkGraphService(
        LedgerWorkGraphStore(client),
        clock=lambda: f"2026-07-16T00:00:{next(ticks):02d}+00:00",
        id_factory=lambda prefix: f"{prefix}-{tag}-{next(ids)}",
    )


def test_item_placement_edge_survive_a_fresh_service_over_same_ledger(ledger_client):
    svc = _svc(ledger_client)
    a = svc.create_item("ship the work graph", kind="feature", conversation_id="chat-9")
    b = svc.create_item("write the durability test", kind="todo")
    svc.add_placement(a.work_item_id, "board-eng", "engineering", is_primary=True)
    svc.add_placement(a.work_item_id, "board-life", "life")     # secondary
    svc.add_edge(b.work_item_id, a.work_item_id, "implements")

    # a BRAND-NEW service (= cockpit/worker restart) over the SAME Ledger db
    fresh = _svc(ledger_client)
    got = fresh.get_item(a.work_item_id)
    assert got.title == "ship the work graph"
    assert got.kind == "feature"
    assert got.conversation_id == "chat-9"
    assert got.primary_board_id == "board-eng"          # primary placement persisted
    placements = fresh._store.placements_for(a.work_item_id)
    assert {p.board_id for p in placements} == {"board-eng", "board-life"}
    edges = fresh._store.edges()
    assert len(edges) == 1 and edges[0].relation == "implements"
    assert edges[0].blocking is True                    # implements ∈ ACYCLIC_RELATIONS


def test_durable_creation_commits_created_event_with_the_row(ledger_client):
    svc = _tagged_svc(ledger_client, "create")
    item = svc.create_item("atomic origin")
    assert [event.kind for event in svc._store.events(item.work_item_id)] == ["created"]


def test_concurrent_durable_primary_placements_leave_exactly_one(ledger_client):
    seed = _tagged_svc(ledger_client, "seed-primary")
    item = seed.create_item("one primary under concurrency")
    services = [_tagged_svc(ledger_client, "primary-a"),
                _tagged_svc(ledger_client, "primary-b")]

    def place(index: int):
        try:
            return services[index].add_placement(
                item.work_item_id, f"board-{index}", f"domain-{index}",
                is_primary=True,
            )
        except WorkGraphError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(place, range(2)))
    assert sum(not isinstance(result, Exception) for result in results) == 1
    active = seed._store.placements_for(item.work_item_id)
    assert len(active) == 1 and active[0].is_primary is True
    assert seed.get_item(item.work_item_id).primary_board_id == active[0].board_id
    assert len([event for event in seed._store.events(item.work_item_id)
                if event.kind == "placement_added"]) == 1


def test_concurrent_reciprocal_blocking_edges_never_form_cycle(ledger_client):
    seed = _tagged_svc(ledger_client, "seed-edge")
    a = seed.create_item("A").work_item_id
    b = seed.create_item("B").work_item_id
    services = [_tagged_svc(ledger_client, "edge-a"),
                _tagged_svc(ledger_client, "edge-b")]

    def connect(index: int):
        frm, to = ((a, b), (b, a))[index]
        try:
            return services[index].add_edge(frm, to, "blocks")
        except WorkGraphError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(connect, range(2)))
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert len(seed._store.edges()) == 1


def test_removed_primary_retry_repairs_legacy_split_state(ledger_client):
    svc = _tagged_svc(ledger_client, "remove")
    item = svc.create_item("repair removed primary")
    placement = svc.add_placement(
        item.work_item_id, "tasks", "tasks", is_primary=True,
    )
    # Seed the historical split directly in SQLite. The public store no longer
    # exposes an eventless replacement path, which is the invariant under test.
    with sqlite3.connect(os.environ["LEDGER_DB"]) as connection:
        connection.execute(
            "UPDATE work_placements SET removed_at=? WHERE placement_id=?",
            ("2026-07-16T00:00:20+00:00", placement.placement_id),
        )
        connection.commit()
    assert svc.get_item(item.work_item_id).primary_board_id == "tasks"
    assert not [event for event in svc._store.events(item.work_item_id)
                if event.kind == "placement_removed"]
    svc.remove_placement(placement.placement_id)
    assert svc.get_item(item.work_item_id).primary_board_id is None
    removed = [event for event in svc._store.events(item.work_item_id)
               if event.kind == "placement_removed"]
    assert len(removed) == 1
    assert removed[0].payload["placement_id"] == placement.placement_id


def test_old_durable_primary_removal_retry_keeps_new_same_board_primary(ledger_client):
    svc = _tagged_svc(ledger_client, "same-board")
    item = svc.create_item("durable same-board replacement")
    old = svc.add_placement(
        item.work_item_id, "shared", "domain-one", is_primary=True,
    )
    svc.remove_placement(old.placement_id)
    current = svc.add_placement(
        item.work_item_id, "shared", "domain-two", is_primary=True,
    )

    svc.remove_placement(old.placement_id)

    assert svc.get_item(item.work_item_id).primary_board_id == "shared"
    assert svc._store.get_placement(current.placement_id).removed_at is None


def test_ledger_refuses_eventless_graph_creation_endpoints(ledger_client):
    svc = _tagged_svc(ledger_client, "event-boundary")
    item = svc.create_item("event boundary")
    raw_item = item.model_copy(update={"work_item_id": "W-eventless"})
    assert ledger_client.post("/work-item", json=raw_item.model_dump()).status_code == 422
    raw_placement = WorkPlacement(
        placement_id="P-eventless", work_item_id=item.work_item_id,
        board_id="tasks", domain_id="tasks", created_at="t",
    )
    assert ledger_client.post(
        "/work-placement", json=raw_placement.model_dump(),
    ).status_code == 422


def test_invalid_durable_status_never_commits(ledger_client):
    svc = _tagged_svc(ledger_client, "bad-status")
    item = svc.create_item("valid durable status")
    response = ledger_client.patch(
        f"/work-item/{item.work_item_id}",
        json={
            "fields": {"canonical_status": "invented", "updated_at": "later"},
            "event": {"ts": "later", "kind": "status", "payload": {"status": "invented"}},
        },
    )
    assert response.status_code == 422
    assert svc.get_item(item.work_item_id).canonical_status == "backlog"


def test_insertion_order_and_whole_graph_survive(ledger_client):
    svc = _svc(ledger_client)
    a = svc.create_item("alpha")
    b = svc.create_item("beta")
    svc.add_placement(a.work_item_id, "b1", "d1")
    svc.add_edge(a.work_item_id, b.work_item_id, "related_to")

    g = _svc(ledger_client).graph()                     # different service, same Ledger
    assert [i.title for i in g.items] == ["alpha", "beta"]
    assert len(g.placements) == 1 and g.placements[0].board_id == "b1"
    assert len(g.edges) == 1 and g.edges[0].relation == "related_to"


def test_status_transition_appends_ordered_events_and_is_recoverable(ledger_client):
    svc = _svc(ledger_client)
    a = svc.create_item("improve the job board")
    svc.set_status(a.work_item_id, "in_progress")
    fresh = _svc(ledger_client)
    assert fresh.get_item(a.work_item_id).canonical_status == "in_progress"
    # events are ordered: created, then the status transition
    kinds = [e.kind for e in fresh._store.events(a.work_item_id)]
    assert kinds == ["created", "status"]


def test_atomic_description_edit_and_exact_retry_survive_restart(ledger_client):
    svc = _svc(ledger_client)
    item = svc.create_item("durable organized text", description="before")
    updated = svc.update_description(
        item.work_item_id, "after",
        expected_updated_at=item.updated_at,
        expected_description="before",
    )
    fresh = _svc(ledger_client)
    replay = fresh.update_description(
        item.work_item_id, "after",
        expected_updated_at=item.updated_at,
        expected_description="before",
    )
    assert replay.description == "after"
    assert replay.updated_at == updated.updated_at
    events = [event for event in fresh._store.events(item.work_item_id)
              if event.kind == "description_edited"]
    assert len(events) == 1


def test_atomic_description_edit_rejects_stale_durable_writer(ledger_client):
    svc = _svc(ledger_client)
    item = svc.create_item("durable conflict", description="before")
    svc.update_description(
        item.work_item_id, "winner",
        expected_updated_at=item.updated_at,
        expected_description="before",
    )
    with pytest.raises(WorkGraphError, match="refresh its story"):
        _svc(ledger_client).update_description(
            item.work_item_id, "loser",
            expected_updated_at=item.updated_at,
            expected_description="before",
        )
    assert _svc(ledger_client).get_item(item.work_item_id).description == "winner"


def test_durable_description_status_race_never_reverts_a_committed_edit(
    ledger_client,
):
    svc = _svc(ledger_client)
    item = svc.create_item("durable status race", description="before")

    def edit():
        try:
            _svc(ledger_client).update_description(
                item.work_item_id, "after",
                expected_updated_at=item.updated_at,
                expected_description="before",
            )
        except WorkGraphError:
            pass

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda fn: fn(), (
            edit,
            lambda: _svc(ledger_client).set_status(
                item.work_item_id, "in_progress"),
        )))
    fresh = _svc(ledger_client)
    current = fresh.get_item(item.work_item_id)
    edited = any(
        event.kind == "description_edited"
        for event in fresh._store.events(item.work_item_id)
    )
    assert current.canonical_status == "in_progress"
    assert current.description == ("after" if edited else "before")


def test_durable_description_primary_race_never_reverts_a_committed_edit(
    ledger_client,
):
    svc = _svc(ledger_client)
    item = svc.create_item("durable primary race", description="before")

    def edit():
        try:
            _svc(ledger_client).update_description(
                item.work_item_id, "after",
                expected_updated_at=item.updated_at,
                expected_description="before",
            )
        except WorkGraphError:
            pass

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda fn: fn(), (
            edit,
            lambda: _svc(ledger_client).add_placement(
                item.work_item_id, "board-race", "domain-race",
                is_primary=True,
            ),
        )))
    fresh = _svc(ledger_client)
    current = fresh.get_item(item.work_item_id)
    edited = any(
        event.kind == "description_edited"
        for event in fresh._store.events(item.work_item_id)
    )
    assert current.primary_board_id == "board-race"
    assert current.description == ("after" if edited else "before")


def test_one_primary_rule_enforced_over_the_durable_store(ledger_client):
    svc = _svc(ledger_client)
    a = svc.create_item("one primary only")
    svc.add_placement(a.work_item_id, "b1", "d1", is_primary=True)
    # a SECOND primary must be rejected — read back through the Ledger, not memory
    fresh = _svc(ledger_client)
    with pytest.raises(WorkGraphError, match="already has a primary board"):
        fresh.add_placement(a.work_item_id, "b2", "d2", is_primary=True)


def test_cycle_rejected_across_restart(ledger_client):
    svc = _svc(ledger_client)
    a = svc.create_item("A")
    b = svc.create_item("B")
    svc.add_edge(a.work_item_id, b.work_item_id, "blocks")
    # a fresh service must still see A->B and reject the closing B->A blocks edge
    fresh = _svc(ledger_client)
    with pytest.raises(WorkGraphError, match="would create a cycle"):
        fresh.add_edge(b.work_item_id, a.work_item_id, "blocks")
    # an informational relation may still cycle
    fresh.add_edge(b.work_item_id, a.work_item_id, "related_to")


def test_soft_removed_placement_preserves_item_and_clears_primary(ledger_client):
    svc = _svc(ledger_client)
    a = svc.create_item("keep the item")
    p = svc.add_placement(a.work_item_id, "b1", "d1", is_primary=True)
    svc.remove_placement(p.placement_id)
    fresh = _svc(ledger_client)
    assert fresh.get_item(a.work_item_id).primary_board_id is None   # primary cleared
    assert fresh._store.placements_for(a.work_item_id, active_only=True) == []
    assert len(fresh._store.placements_for(a.work_item_id, active_only=False)) == 1


def test_unknown_item_is_keyerror(ledger_client):
    store = LedgerWorkGraphStore(ledger_client)
    with pytest.raises(KeyError):
        store.get_item("never-seen")
    with pytest.raises(KeyError):
        store.get_placement("never-seen")
    with pytest.raises(KeyError):
        store.get_edge("never-seen")
