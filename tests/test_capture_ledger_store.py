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
from pathlib import Path

import pytest

from command_center.intake import CaptureRecord, CaptureService, LedgerCaptureStore

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
