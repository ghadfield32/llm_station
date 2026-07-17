"""CaptureService.mark_converted — record that a capture became canonical work:
append a 'link' event carrying the created work_item_ids and move the capture to
the 'routed' lane. The capture is never destroyed; it stays recoverable.
"""
from __future__ import annotations

import itertools

import pytest

from command_center.intake import CaptureService, InMemoryCaptureStore


def _svc() -> CaptureService:
    ids = itertools.count(1)
    ticks = itertools.count(1)
    return CaptureService(
        InMemoryCaptureStore(),
        clock=lambda: f"2026-07-13T00:00:{next(ticks):02d}+00:00",
        id_factory=lambda: f"cap-{next(ids)}")


def test_mark_converted_links_and_routes_but_preserves_the_capture():
    svc = _svc()
    cid = svc.capture("research NBA footage", conversation_id="chat-9").record.capture_id
    view = svc.mark_converted(cid, ["W-1", "W-2"], conversation_id="chat-9")

    assert view.processing_status == "routed"          # moved to the routed lane
    # the raw thought is untouched (immutable capture)
    assert view.record.raw_content == "research NBA footage"
    # a 'link' event records the work it produced
    link = [e for e in svc._store.events(cid) if e.kind == "link"]
    assert len(link) == 1
    assert link[0].payload["work_item_ids"] == ["W-1", "W-2"]
    # still recoverable from the Inbox, now in the routed lane
    lanes = {c["name"] for c in svc.inbox()["columns"]}
    assert "routed" in lanes


def test_mark_converted_unknown_capture_is_keyerror():
    with pytest.raises(KeyError):
        _svc().mark_converted("never-seen", ["W-1"])


def test_mark_converted_uses_one_atomic_store_boundary_not_split_status_calls(
    monkeypatch,
):
    svc = _svc()
    cid = svc.capture("durable conversion").record.capture_id
    def forbidden_split_call(*_args, **_kwargs):
        raise AssertionError("atomic conversion must not call set_status separately")

    monkeypatch.setattr(svc._store, "set_status", forbidden_split_call)
    view = svc.mark_converted(cid, ["W-1"])
    assert view.processing_status == "routed"
    assert len([e for e in svc._store.events(cid) if e.kind == "link"]) == 1
    assert len([
        e for e in svc._store.events(cid)
        if e.kind == "status" and e.payload.get("status") == "routed"
    ]) == 1
