"""Universal Capture foundation — the immutable intake record, bulk-list split
(nothing lost), and the Inbox fold. No classification/routing yet (later phases);
this pins the stable record everything else will build on.
"""
from __future__ import annotations

import itertools
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from command_center.intake import (
    CaptureConversionConflict,
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


def test_split_bulk_list_splits_phone_note_unicode_bullets():
    # Phone note apps paste ◦ (U+25E6), ⁃ (U+2043), ‣ (U+2023) bullets —
    # sometimes with a tab, and sometimes a lone empty bullet line.
    text = "◦ Book MJ appt\n◦\tWatch tenet\n◦\n⁃ show the last 10 drafts\n‣ buy tickets"
    assert split_bulk_list(text) == [
        "Book MJ appt", "Watch tenet", "show the last 10 drafts", "buy tickets"]


def test_split_strips_stacked_markers_but_never_content():
    # Phone notes stack markers ("◦ - item"); strip formatting, keep words.
    assert split_bulk_list("◦ - have LinkedIn prepared\n◦ - post about ESEA") == [
        "have LinkedIn prepared", "post about ESEA"]


def test_split_keeps_checked_lines_visible_between_bullets():
    # A pasted ✓ line is NOT a bullet: it stays its own visible capture, so
    # finished work is never silently turned into an open todo nor dropped.
    text = "◦ open item one\n✓ already finished item\n◦ open item two"
    assert split_bulk_list(text) == [
        "open item one", "✓ already finished item", "open item two"]


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


def test_prepare_is_idempotent_and_keeps_full_raw_capture():
    svc = _service()
    raw = "First line\n\nSecond line with every original detail."
    captured = svc.capture(raw, conversation_id="unrelated-chat")

    first = svc.prepare(captured.record.capture_id)
    first_view = svc.get(captured.record.capture_id)
    repeated = svc.prepare(captured.record.capture_id)
    repeated_view = svc.get(captured.record.capture_id)

    assert first == repeated
    assert first["conversation_id"] == f"capture:{captured.record.capture_id}"
    assert first["processing_status"] == "ready_to_route"
    assert raw in first["chat_prompt"]
    assert {row["id"] for row in first["available_actions"]} == {
        "continue_in_chat", "route_to_todos",
        "choose_existing_board", "create_new_board",
    }
    assert first_view.event_count == repeated_view.event_count == 2
    assert svc.get(captured.record.capture_id).record.raw_content == raw


def test_prepare_unknown_capture_is_keyerror():
    with pytest.raises(KeyError):
        _service().prepare("never-seen")


def test_atomic_capture_conversion_accepts_exact_retries_and_rejects_divergence():
    svc = _service()
    capture_id = svc.capture("route this").record.capture_id
    svc.mark_converted(capture_id, ["W-1", "W-2"], conversation_id="chat-1")
    first_count = svc.get(capture_id).event_count
    svc.mark_converted(capture_id, ["W-1", "W-2"], conversation_id="chat-1")
    assert svc.get(capture_id).event_count == first_count
    with pytest.raises(CaptureConversionConflict, match="conflicting WorkItem link"):
        svc.mark_converted(capture_id, ["W-3"], conversation_id="chat-1")


def test_mixed_in_memory_capture_links_reject_before_routing():
    svc = _service()
    capture_id = svc.capture("mixed links").record.capture_id
    from command_center.intake import CaptureEvent
    svc._store.append_event(CaptureEvent(
        capture_id=capture_id, ts="t1", kind="link",
        payload={"work_item_ids": ["W-expected"], "conversation_id": "chat-1"},
    ))
    svc._store.append_event(CaptureEvent(
        capture_id=capture_id, ts="t2", kind="link",
        payload={"work_item_ids": ["W-foreign"], "conversation_id": "chat-2"},
    ))
    with pytest.raises(CaptureConversionConflict, match="conflicting WorkItem link"):
        svc.mark_converted(
            capture_id, ["W-expected"], conversation_id="chat-1",
        )
    assert svc.get(capture_id).processing_status == "captured"


def test_concurrent_identical_capture_conversion_records_one_link():
    svc = _service()
    capture_id = svc.capture("route concurrently").record.capture_id
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(
            lambda _index: svc.mark_converted(
                capture_id, [], conversation_id="chat-empty",
            ),
            range(4),
        ))
    events = svc._store.events(capture_id)
    assert len([event for event in events if event.kind == "link"]) == 1
    assert len([event for event in events if event.kind == "status"
                and event.payload.get("status") == "routed"]) == 1
