"""`cc content-note`: resolve a card by intent and record the note through the
GOVERNED path - a progress_comment event that never sets status, approves, or
merges. The wall (emit_event rejecting approve/merge) is what makes a note update
safe; these tests pin both the happy path and that boundary."""
from __future__ import annotations

import pytest

from command_center.cli import content_note as cn
from command_center.content.reference_live import records_from_rows
from command_center.content.reference_index import embed_records
from command_center.content.reference_resolver import load_ref_config
from command_center.content.embeddings import HashEmbedder
from command_center.kanban_sync.events import EventLog, emit_event, GovernanceViolation

ROWS = {
    "library": [
        {"id": "lib1", "cells": {"Name": "Basketball Tracking Library",
                                 "Why": "CV tracking refs", "Topics": "basketball"}},
    ],
    "notes": [
        {"id": "n1", "cells": {"Title": "Standup note", "Notes": "old text",
                               "Tags": "daily"}},
    ],
    "geoffhadfield32_content": [
        {"id": "p1", "cells": {"Hook": "GLM router backup post",
                               "Body": "how I built it"}},
    ],
}


def _records():
    recs = records_from_rows(ROWS)
    embed_records(recs, HashEmbedder())
    return recs


def test_resolve_card_by_intent():
    rec = cn.resolve_card("basketball tracking libary", _records(),
                          cfg=load_ref_config(), embedder=HashEmbedder())
    assert rec.id == "lib1" and rec.board == "library"


def test_resolve_card_ambiguous_raises_with_candidates():
    rows = {"notes": [{"id": "a", "cells": {"Title": "Bayesian workflow"}},
                      {"id": "b", "cells": {"Title": "Bayesian workflow"}}]}
    recs = records_from_rows(rows)
    embed_records(recs, HashEmbedder())
    with pytest.raises(SystemExit) as e:
        cn.resolve_card("bayesian workflow", recs, cfg=load_ref_config(),
                        embedder=HashEmbedder())
    assert "ambiguous" in str(e.value)


def test_emit_note_is_a_governed_progress_comment(tmp_path):
    rec = cn.resolve_card("standup note", _records(), cfg=load_ref_config(),
                          embedder=HashEmbedder())
    log = EventLog(tmp_path / "events.jsonl")
    ev = cn.emit_note(rec, "remember to push the branch", "append", log)
    assert ev.event_type == "kanban.card.progress_comment_added"
    assert ev.status_after is None                 # never sets status / approves
    assert ev.actor_type == "agent"
    assert ev.payload_ref == "append:remember to push the branch"
    assert len(log.read()) == 1                    # appended to the governed log


def test_note_path_can_never_approve_or_merge(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    for wall in ("approve_card", "merge", "publish", "delete_card"):
        with pytest.raises(GovernanceViolation):
            emit_event(log, action=wall, board_id="library", card_id="lib1",
                       source_surface="repo_agent")
    assert log.read() == []                        # nothing written for wall actions
