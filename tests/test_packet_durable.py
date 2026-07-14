"""Durable Readiness Packet (Phase H slice 2): the Ledger-backed store makes
packets survive a cockpit restart; revisions are immutable; a review binds to the
revision it reviewed (a rev-1 approval cannot satisfy rev-2); a committed packet
is frozen at the DB layer; and a re-commit after a partial failure reuses the
already-created graph instead of duplicating it.

No Docker: the Ledger FastAPI app is loaded via importlib + Starlette TestClient
(httpx-compatible), exactly like test_capture_ledger_store.py. A "restart" is a
SECOND PacketService/store reading the SAME Ledger db.
"""
from __future__ import annotations

import importlib.util
import itertools
import os
from pathlib import Path

import pytest

from command_center.work_graph import (
    ChatWorkPlanner,
    InMemoryPacketStore,
    InMemoryWorkGraphStore,
    LedgerPacketStore,
    PacketError,
    PacketRevisionConflict,
    PacketService,
    PlanBoardRef,
    WorkGraphService,
    WorkPlanIn,
    WorkPlanItemIn,
)
from command_center.work_graph.packet import _content_digest

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_APP = REPO_ROOT / "services/ledger/app.py"


@pytest.fixture
def ledger_client(tmp_path):
    os.environ["LEDGER_DB"] = str(tmp_path / "ledger.db")
    spec = importlib.util.spec_from_file_location("ledger_app_packet_test", LEDGER_APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from starlette.testclient import TestClient
    return TestClient(mod.app)


def _packets(store) -> PacketService:
    ids = itertools.count(1)
    ticks = itertools.count(1)
    return PacketService(
        store,
        clock=lambda: f"2026-07-14T02:00:{next(ticks):02d}+00:00",
        id_factory=lambda: f"pkt-{next(ids)}")


def _wg(tag: str) -> WorkGraphService:
    ticks = itertools.count(1)
    counters: dict[str, itertools.count] = {}

    def mkid(prefix: str) -> str:
        counters.setdefault(prefix, itertools.count(1))
        return f"{tag}-{prefix}-{next(counters[prefix])}"

    return WorkGraphService(InMemoryWorkGraphStore(),
                            clock=lambda: f"2026-07-14T00:00:{next(ticks):02d}+00:00",
                            id_factory=mkid)


def _planner():
    real = _wg("real")
    return ChatWorkPlanner(real, sandbox_factory=lambda: _wg("box")), real


def _items_for(real):
    return lambda pid: [it.work_item_id for it in real.list_items()
                        if getattr(it, "packet_id", None) == pid]


def _plan() -> WorkPlanIn:
    return WorkPlanIn(conversation_id="chat-1", items=[
        WorkPlanItemIn(ref="a", title="Ship the packet feature", kind="feature",
                       primary_board=PlanBoardRef(board_id="eng", domain_id="eng"))])


# ── durability ────────────────────────────────────────────────────────────────
def test_packet_survives_restart(ledger_client):
    svc = _packets(LedgerPacketStore(ledger_client))
    p = svc.assemble(_plan(), research="check licensing",
                     runbook=["build", "test"], acceptance_criteria=["works"],
                     review_roles=["codex_agent"])
    pid = p.packet_id
    svc.set_review(pid, "codex_agent", status="approved", summary="lgtm",
                   session_id="sess-9")

    # a BRAND-NEW service (= cockpit restart) over the SAME Ledger db
    fresh = _packets(LedgerPacketStore(ledger_client))
    got = fresh.get(pid)
    assert got.research == "check licensing"
    assert [s.text for s in got.runbook] == ["build", "test"]
    assert got.reviews[0].status == "approved"
    assert got.reviews[0].session_id == "sess-9"
    assert got.revision == 1
    assert fresh.is_ready(got) is True
    # the immutable revision history survived too
    assert [r.revision for r in fresh.revisions(pid)] == [1]


def test_missing_packet_is_keyerror(ledger_client):
    svc = _packets(LedgerPacketStore(ledger_client))
    with pytest.raises(KeyError):
        svc.get("never-seen")


# ── immutable revisions + deterministic digest ─────────────────────────────────
@pytest.mark.parametrize("backend", ["memory", "ledger"])
def test_revision_is_immutable(backend, ledger_client):
    store = (LedgerPacketStore(ledger_client) if backend == "ledger"
             else InMemoryPacketStore())
    svc = _packets(store)
    p = svc.assemble(_plan())
    # re-appending an existing revision number is rejected (immutability wall)
    with pytest.raises(PacketError):
        store.append_revision(p.packet_id, p.revision, "sha256:x", "{}",
                              "2026-07-14T09:00:00+00:00")


def test_revise_mints_a_new_immutable_revision(ledger_client):
    svc = _packets(LedgerPacketStore(ledger_client))
    p = svc.assemble(_plan(), research="v1")
    p2 = svc.revise(p.packet_id, research="v2")
    assert p2.revision == 2
    revs = svc.revisions(p.packet_id)
    assert [r.revision for r in revs] == [1, 2]
    # the two revisions have different content digests (research changed)
    assert revs[0].content_digest != revs[1].content_digest


def test_content_digest_excludes_reviews_and_timestamps():
    # two packets, identical plan-content but different reviews/timestamps → same
    # digest; and approving a review must NOT change the digest.
    svc = _packets(InMemoryPacketStore())
    p = svc.assemble(_plan(), research="same", review_roles=["codex_agent"])
    before = _content_digest(p)
    p2 = svc.set_review(p.packet_id, "codex_agent", status="approved")
    assert _content_digest(p2) == before          # review did not move the digest
    # a content edit DOES move it
    p3 = svc.revise(p.packet_id, research="different")
    assert _content_digest(p3) != before


# ── reviews bind to a revision ─────────────────────────────────────────────────
def test_review_approves_only_the_current_revision(ledger_client):
    svc = _packets(LedgerPacketStore(ledger_client))
    p = svc.assemble(_plan(), review_roles=["codex_agent"])
    svc.set_review(p.packet_id, "codex_agent", status="approved")
    assert svc.is_ready(svc.get(p.packet_id)) is True
    # editing content mints rev2 and reverts the slot to pending → not ready again
    p2 = svc.revise(p.packet_id, research="changed the scope")
    assert p2.revision == 2
    assert p2.reviews[0].status == "pending"
    assert svc.is_ready(p2) is False


def test_old_review_cannot_approve_new_revision(ledger_client):
    svc = _packets(LedgerPacketStore(ledger_client))
    p = svc.assemble(_plan(), review_roles=["codex_agent"])
    svc.revise(p.packet_id, research="now rev2")           # -> revision 2
    # a reviewer who read revision 1 approves with expected_revision=1 → 409
    with pytest.raises(PacketRevisionConflict):
        svc.set_review(p.packet_id, "codex_agent", status="approved",
                       expected_revision=1)


def test_stale_revision_commit_is_rejected(ledger_client):
    planner, real = _planner()
    svc = _packets(LedgerPacketStore(ledger_client))
    p = svc.assemble(_plan())                               # no reviews → ready
    svc.revise(p.packet_id, research="bumped to rev2")      # -> revision 2
    with pytest.raises(PacketRevisionConflict):
        svc.commit(p.packet_id, planner, expected_revision=1,
                   work_items_for_packet=_items_for(real))


# ── frozen after commit ────────────────────────────────────────────────────────
def test_committed_packet_is_frozen(ledger_client):
    planner, real = _planner()
    store = LedgerPacketStore(ledger_client)
    svc = _packets(store)
    p = svc.assemble(_plan(), review_roles=["codex_agent"])
    svc.set_review(p.packet_id, "codex_agent", status="approved")
    committed = svc.commit(p.packet_id, planner,
                           work_items_for_packet=_items_for(real))
    assert committed.committed_at is not None
    assert committed.work_item_ids and committed.status == "committed"
    # service wall: further review/revise raise
    with pytest.raises(PacketError):
        svc.set_review(p.packet_id, "codex_agent", status="changes_requested")
    with pytest.raises(PacketError):
        svc.revise(p.packet_id, research="too late")
    # durable DB wall: the Ledger itself rejects a review write on a committed row
    with pytest.raises(PacketError):
        store.record_review(p.packet_id, 1, "codex_agent", "approved", "", [],
                            None, "2026-07-14T10:00:00+00:00")


def test_double_commit_is_rejected(ledger_client):
    planner, real = _planner()
    svc = _packets(LedgerPacketStore(ledger_client))
    p = svc.assemble(_plan())
    svc.commit(p.packet_id, planner, work_items_for_packet=_items_for(real))
    with pytest.raises(PacketError):
        svc.commit(p.packet_id, planner, work_items_for_packet=_items_for(real))


def test_double_commit_is_rejected_in_memory():
    # the in-memory backend has no store-level guard; single-commit is enforced by
    # the service re-reading committed_at before mutating. Prove that still holds.
    planner, real = _planner()
    svc = _packets(InMemoryPacketStore())
    p = svc.assemble(_plan())
    svc.commit(p.packet_id, planner, work_items_for_packet=_items_for(real))
    with pytest.raises(PacketError):
        svc.commit(p.packet_id, planner, work_items_for_packet=_items_for(real))


def test_ledger_db_rejects_direct_double_commit(ledger_client):
    # the DB-layer 409 wall itself (hit directly, bypassing the service re-read):
    # a committed row cannot be re-committed even by a raw /commit POST.
    planner, real = _planner()
    svc = _packets(LedgerPacketStore(ledger_client))
    p = svc.assemble(_plan())
    svc.commit(p.packet_id, planner, work_items_for_packet=_items_for(real))
    r = ledger_client.post(
        f"/readiness-packet/{p.packet_id}/commit",
        json={"status": "committed", "committed_at": "2026-07-14T11:00:00+00:00",
              "updated_at": "2026-07-14T11:00:00+00:00", "work_item_ids": []})
    assert r.status_code == 409, r.text


# ── idempotent commit: no duplicate graph on retry (reconciliation C1) ──────────
def test_commit_reuses_an_existing_graph_no_duplicate():
    planner, real = _planner()
    svc = _packets(InMemoryPacketStore())
    p = svc.assemble(_plan())                               # ready, no reviews
    # simulate a prior partial commit: the graph was created (packet_id threaded)
    # but the packet was never finalized (crash before the finalize write).
    planner.commit(p.plan.model_copy(update={"packet_id": p.packet_id}))
    before = len(real.list_items())
    assert before == 1

    committed = svc.commit(p.packet_id, planner,
                           work_items_for_packet=_items_for(real))
    # the retry REUSED the existing item — no second graph
    assert len(real.list_items()) == before
    assert committed.work_item_ids == [real.list_items()[0].work_item_id]
    assert committed.committed_at is not None


def test_ledger_commit_is_atomic_and_durably_linked(ledger_client):
    # the atomic /commit finalize writes committed_at + work-links in one txn, so
    # a fresh store sees BOTH — no committed-but-unlinked window (final-diff C1).
    planner, real = _planner()
    svc = _packets(LedgerPacketStore(ledger_client))
    p = svc.assemble(_plan())
    committed = svc.commit(p.packet_id, planner,
                           work_items_for_packet=_items_for(real))
    assert committed.committed_at is not None and committed.work_item_ids

    fresh = _packets(LedgerPacketStore(ledger_client))       # restart
    got = fresh.get(p.packet_id)
    assert got.status == "committed" and got.committed_at is not None
    assert got.work_item_ids == committed.work_item_ids      # links survived
    # a second commit is rejected at the DB layer (committed_at set)
    with pytest.raises(PacketError):
        fresh.commit(p.packet_id, planner, work_items_for_packet=_items_for(real))


def test_ledger_upsert_rejects_a_committed_packet(ledger_client):
    # durable second wall (final-diff C2): the /readiness-packet upsert refuses to
    # overwrite/un-freeze a committed row.
    planner, real = _planner()
    svc = _packets(LedgerPacketStore(ledger_client))
    p = svc.assemble(_plan())
    committed = svc.commit(p.packet_id, planner,
                           work_items_for_packet=_items_for(real))
    r = ledger_client.post("/readiness-packet",
                           json=committed.model_dump(mode="json"))
    assert r.status_code == 409, r.text


def test_setting_a_review_creates_no_work_items(ledger_client):
    # a review is analysis only — it never creates the graph (the H2 read-only wall
    # at the store level: reviewers set outcomes; only commit builds work).
    planner, real = _planner()
    svc = _packets(LedgerPacketStore(ledger_client))
    p = svc.assemble(_plan(), review_roles=["codex_agent"])
    svc.set_review(p.packet_id, "codex_agent", status="approved")
    assert real.list_items() == []
    assert svc.get(p.packet_id).committed_at is None
