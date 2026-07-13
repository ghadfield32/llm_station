"""Universal Capture foundation — the immutable intake record, bulk-list split
(nothing lost), and the Inbox fold. No classification/routing yet (later phases);
this pins the stable record everything else will build on.
"""
from __future__ import annotations

import itertools

import pytest
from pydantic import ValidationError

from command_center.intake import (
    CaptureService,
    CaptureRecord,
    InMemoryCaptureStore,
    split_bulk_list,
)


def _service() -> CaptureService:
    ticks = itertools.count(1)
    ids = itertools.count(1)
    return CaptureService(
        InMemoryCaptureStore(),
        clock=lambda: f"2026-07-13T00:00:{next(ticks):02d}+00:00",
        id_factory=lambda: f"cap-{next(ids)}")


# ---- the raw capture is immutable ----------------------------------------------

def test_capture_record_is_frozen():
    rec = CaptureRecord(capture_id="c1", raw_content="hi", captured_at="t")
    with pytest.raises(ValidationError):
        rec.raw_content = "changed"       # the raw thought is never edited in place


def test_empty_capture_is_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        _service().capture("   ")


# ---- bulk list split loses nothing ---------------------------------------------

def test_split_bulk_list_splits_bullets_and_numbers():
    text = "- post about biomechanics\n- research shot detection\n3. call the dentist"
    assert split_bulk_list(text) == [
        "post about biomechanics", "research shot detection", "call the dentist"]


def test_split_single_free_text_is_one_capture():
    text = "I want to write about historical NBA movement metrics"
    assert split_bulk_list(text) == [text]


def test_split_empty_is_empty():
    assert split_bulk_list("   \n  ") == []


def test_capture_batch_shares_a_batch_id_and_keeps_order():
    svc = _service()
    views = svc.capture_batch("- alpha\n- beta\n- gamma")
    assert [v.record.raw_content for v in views] == ["alpha", "beta", "gamma"]
    batch_ids = {v.record.batch_id for v in views}
    assert len(batch_ids) == 1 and None not in batch_ids   # one shared, non-null batch


# ---- inbox folds everything, drops nothing -------------------------------------

def test_new_capture_lands_in_the_inbox_captured_lane():
    svc = _service()
    v = svc.capture("call the dentist", requested_mode="save_only")
    assert v.processing_status == "captured"
    inbox = svc.inbox()
    assert inbox["total"] == 1
    captured = next(c for c in inbox["columns"] if c["name"] == "captured")
    assert captured["captures"][0]["capture_id"] == v.record.capture_id


def test_routed_capture_is_still_recoverable_in_the_inbox():
    svc = _service()
    v = svc.capture("improve the job board")
    # simulate a later phase routing it out — it must remain in the Inbox
    svc._store.set_status(v.record.capture_id, "routed", at="2026-07-13T01:00:00+00:00")
    inbox = svc.inbox()
    assert inbox["total"] == 1
    lanes = {c["name"] for c in inbox["columns"]}
    assert "routed" in lanes and "captured" not in lanes


def test_context_bindings_are_preserved_but_do_not_start_work():
    svc = _service()
    v = svc.capture("why did the DAG fail?", current_board_id="basketball_cv",
                    conversation_id="chat-9", requested_mode="prepare_later")
    assert v.record.current_board_id == "basketball_cv"
    assert v.record.conversation_id == "chat-9"
    assert v.processing_status == "captured"     # saved, not executed
