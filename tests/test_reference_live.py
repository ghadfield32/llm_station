"""The live AppFlowy bridge mappers: board rows -> IndexRecords (every database,
kind derived, card id preserved, no-title rows skipped, date cells tolerated) and
content-board cards -> LinkedInPosts. Pure functions, fed injected rows, so this
runs offline. Also checks a vague/misspelled query resolves to a live card."""
from __future__ import annotations

from command_center.content.reference_live import records_from_rows, posts_from_rows
from command_center.content.reference_index import embed_records
from command_center.content.reference_resolver import resolve, load_ref_config
from command_center.content.embeddings import HashEmbedder

ROWS = {
    "library": [
        {"id": "lib1", "cells": {"Name": "World Models Reading List",
                                 "Why": "core papers on world models",
                                 "Topics": "world model, rl"}},
        {"id": "lib2", "cells": {"Name": "Basketball Tracking Library",
                                 "Why": "CV tracking references",
                                 "Topics": {"start": "2026-01-01"}}},  # date cell
        {"id": "lib3", "cells": {"Why": "no title -> skipped"}},
    ],
    "notes": [
        {"id": "n1", "cells": {"Title": "Standup note",
                               "Notes": "remember to push the branch",
                               "Tags": "daily"}},
    ],
    "geoffhadfield32_content": [
        {"id": "p1", "cells": {"Hook": "GLM router backup",
                               "Body": "how I built it", "Status": "In Queue"}},
    ],
}


def test_records_from_rows_maps_every_database():
    recs = records_from_rows(ROWS)
    by_id = {r.id: r for r in recs}
    assert by_id["lib1"].kind == "library" and by_id["lib1"].board == "library"
    assert by_id["n1"].kind == "note"
    assert by_id["p1"].kind == "post"
    # board name is always a tag (so "the notes db" style queries hit)
    assert "notes" in by_id["n1"].tags


def test_records_skips_rows_without_a_title():
    recs = records_from_rows(ROWS)
    assert "lib3" not in {r.id for r in recs}        # no usable title
    assert sum(1 for r in recs if r.board == "library") == 2


def test_records_tolerate_date_dict_cells():
    recs = records_from_rows(ROWS)               # lib2 has a date-dict Topics cell
    assert any(r.id == "lib2" for r in recs)     # did not crash, still indexed


def test_posts_from_rows_builds_linkedin_posts():
    posts = posts_from_rows(ROWS["geoffhadfield32_content"], author_name="board")
    assert posts[0].id == "p1"
    assert posts[0].hook() == "GLM router backup"
    assert "how I built it" in posts[0].body


def test_live_card_resolves_by_vague_query():
    recs = records_from_rows(ROWS)
    embed_records(recs, HashEmbedder())
    r = resolve("basketball tracking libary", cfg=load_ref_config(),
                index=recs, embedder=HashEmbedder())
    landed = (r.match or r.choices[0]).record
    assert landed.id == "lib2" and landed.board == "library"
