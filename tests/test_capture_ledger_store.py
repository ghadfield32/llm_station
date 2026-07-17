"""Durable Universal Capture — the Ledger-backed store makes captures survive a
cockpit/worker restart (the in-memory store's immediate successor). Proves the
Phase-B acceptance: capture + batch survive restart, events stay ordered, replay
is idempotent, and a missing capture is a KeyError (in-memory contract).

No Docker: the Ledger FastAPI app is loaded via importlib + Starlette TestClient
(httpx-compatible), exactly like test_usage_ledger_durability.py. A "restart" is
modelled as a SECOND service/store reading the SAME Ledger db.
"""
from __future__ import annotations

import importlib.util
import itertools
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from command_center.intake import (
    CaptureConversionConflict,
    CaptureEvent,
    CaptureEvent,
    CaptureRecord,
    CaptureService,
    LedgerCaptureStore,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_APP = REPO_ROOT / "services/ledger/app.py"


@pytest.fixture
def ledger_client(tmp_path):
    os.environ["LEDGER_DB"] = str(tmp_path / "ledger.db")
    spec = importlib.util.spec_from_file_location("ledger_app_capture_store_test", LEDGER_APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from starlette.testclient import TestClient
    return TestClient(mod.app)


def _svc(client) -> CaptureService:
    ids = itertools.count(1)
    ticks = itertools.count(1)
    return CaptureService(
        LedgerCaptureStore(client),
        clock=lambda: f"2026-07-13T00:00:{next(ticks):02d}+00:00",
        id_factory=lambda: f"cap-{next(ids)}")


def test_capture_survives_a_fresh_service_over_the_same_ledger(ledger_client):
    svc = _svc(ledger_client)
    v = svc.capture("call the dentist", requested_mode="save_only",
                    conversation_id="chat-9")
    cid = v.record.capture_id
    # a BRAND-NEW service (= cockpit/worker restart) over the SAME Ledger db
    fresh = _svc(ledger_client)
    got = fresh.get(cid)
    assert got.record.raw_content == "call the dentist"
    assert got.record.conversation_id == "chat-9"
    assert got.processing_status == "captured"
    assert fresh.inbox()["total"] == 1


def test_bulk_batch_and_insertion_order_survive(ledger_client):
    svc = _svc(ledger_client)
    svc.capture_batch("- alpha\n- beta\n- gamma")
    listed = _svc(ledger_client).list()          # different service, same Ledger
    assert [x.record.raw_content for x in listed] == ["alpha", "beta", "gamma"]
    batch_ids = {x.record.batch_id for x in listed}
    assert len(batch_ids) == 1 and None not in batch_ids


def test_status_transition_appends_ordered_event_and_is_recoverable(ledger_client):
    svc = _svc(ledger_client)
    cid = svc.capture("improve the job board").record.capture_id
    svc._store.set_status(cid, "routed", at="2026-07-13T01:00:00+00:00")
    fresh = _svc(ledger_client)
    got = fresh.get(cid)
    assert got.processing_status == "routed"
    # events are ordered (created status, then routed status)
    kinds = [e.kind for e in fresh._store.events(cid)]
    assert kinds == ["status", "status"]
    # still recoverable from the Inbox, now in the routed lane
    lanes = {c["name"] for c in fresh.inbox()["columns"]}
    assert "routed" in lanes


def test_replay_same_capture_id_is_idempotent(ledger_client):
    store = LedgerCaptureStore(ledger_client)
    rec = CaptureRecord(capture_id="cap-x", raw_content="hi", captured_at="t1")
    store.add(rec, status="captured", at="t1")
    store.add(rec, status="captured", at="t1")   # replay → no-op, not duplicated
    view = store.view("cap-x")
    assert view.record.raw_content == "hi"
    assert view.event_count == 1                 # single created event, not two


def test_unknown_capture_is_keyerror(ledger_client):
    store = LedgerCaptureStore(ledger_client)
    with pytest.raises(KeyError):
        store.view("never-seen")
    with pytest.raises(KeyError):
        store.set_status("never-seen", "routed", at="t")


def test_prepare_survives_restart_and_replay_is_idempotent(ledger_client):
    svc = _svc(ledger_client)
    raw = "Route this later\nwith the full second line intact."
    capture_id = svc.capture(raw).record.capture_id

    first = svc.prepare(capture_id)
    first_count = svc.get(capture_id).event_count
    fresh = _svc(ledger_client)
    repeated = fresh.prepare(capture_id)

    assert repeated == first
    assert repeated["conversation_id"] == f"capture:{capture_id}"
    assert raw in repeated["chat_prompt"]
    assert fresh.get(capture_id).processing_status == "ready_to_route"
    assert fresh.get(capture_id).event_count == first_count == 2


def test_durable_atomic_conversion_exact_and_divergent_retries(ledger_client):
    svc = _svc(ledger_client)
    capture_id = svc.capture("durable route").record.capture_id
    svc.mark_converted(capture_id, ["W-1", "W-2"], conversation_id="chat-1")
    first_count = svc.get(capture_id).event_count
    _svc(ledger_client).mark_converted(
        capture_id, ["W-1", "W-2"], conversation_id="chat-1",
    )
    assert _svc(ledger_client).get(capture_id).event_count == first_count
    with pytest.raises(CaptureConversionConflict, match="different WorkItem link"):
        _svc(ledger_client).mark_converted(
            capture_id, ["W-3"], conversation_id="chat-1",
        )


def test_mixed_capture_link_history_rejects_even_an_expected_member(ledger_client):
    svc = _svc(ledger_client)
    capture_id = svc.capture("mixed link authority").record.capture_id
    svc._store.append_event(CaptureEvent(
        capture_id=capture_id,
        ts="2026-07-16T00:00:10+00:00",
        kind="link",
        payload={"work_item_ids": ["W-expected"], "conversation_id": "chat-1"},
    ))
    svc._store.append_event(CaptureEvent(
        capture_id=capture_id,
        ts="2026-07-16T00:00:11+00:00",
        kind="link",
        payload={"work_item_ids": ["W-foreign"], "conversation_id": "chat-2"},
    ))
    with pytest.raises(CaptureConversionConflict, match="conflicting history"):
        svc.mark_converted(
            capture_id, ["W-expected"], conversation_id="chat-1",
        )
    assert svc.get(capture_id).processing_status == "captured"


def test_capture_id_replay_rejects_changed_immutable_wording(ledger_client):
    original = {
        "capture_id": "C-fixed",
        "raw_content": "original immutable wording",
        "source_type": "text",
        "captured_at": "2026-07-16T00:00:00+00:00",
        "attachments": [],
        "requested_mode": "create_task",
        "status": "captured",
    }
    assert ledger_client.post("/capture", json=original).status_code == 200
    divergent = ledger_client.post(
        "/capture", json={**original, "raw_content": "different wording"},
    )
    assert divergent.status_code == 409
    assert divergent.json()["detail"] == (
        "capture ID replay changes immutable fields: raw_content"
    )
    assert ledger_client.get("/capture/C-fixed").json()["raw_content"] == (
        "original immutable wording"
    )


def test_durable_concurrent_identical_conversion_records_one_link(ledger_client):
    svc = _svc(ledger_client)
    capture_id = svc.capture("durable concurrent route").record.capture_id
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(
            lambda _index: _svc(ledger_client).mark_converted(
                capture_id, [], conversation_id="chat-empty",
            ),
            range(4),
        ))
    events = _svc(ledger_client)._store.events(capture_id)
    assert len([event for event in events if event.kind == "link"]) == 1
    assert len([event for event in events if event.kind == "status"
                and event.payload.get("status") == "routed"]) == 1


def test_concurrent_capture_id_collision_is_exact_success_or_conflict_not_500(
    ledger_client,
):
    base = {
        "capture_id": "C-concurrent",
        "source_type": "text",
        "captured_at": "2026-07-16T00:00:00+00:00",
        "attachments": [],
        "requested_mode": "create_task",
        "status": "captured",
    }
    bodies = [
        {**base, "raw_content": "original"},
        {**base, "raw_content": "divergent"},
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(
            lambda body: ledger_client.post("/capture", json=body).status_code,
            bodies,
        ))
    assert sorted(statuses) == [200, 409]
