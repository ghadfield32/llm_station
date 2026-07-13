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
from pathlib import Path

import pytest

from command_center.work_graph import (
    LedgerWorkGraphStore,
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
