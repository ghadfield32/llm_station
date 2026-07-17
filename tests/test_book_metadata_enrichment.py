from command_center.books.enrichment import (
    BookIdentity,
    book_identity_from_card,
    extract_open_library_metadata,
    match_open_library_work,
    merge_imported_metadata,
    parse_book_checklist,
)


def test_checklist_parser_preserves_source_backed_audio_and_format_details():
    entries = parse_book_checklist(
        "- [ ] **A Mind at Play (Shannon)** — Soni & Goodman · "
        "`[Opt]` audio · ~10h\n"
        "- [ ] Flatland ★ — Edwin A. Abbott · `[Fic]` page · ~3h\n"
    )

    assert entries[0].title == "A Mind at Play (Shannon)"
    assert entries[0].author == "Soni & Goodman"
    assert entries[0].format == "audio"
    assert entries[0].audio_hours == 10
    assert entries[1].title == "Flatland"
    assert entries[1].tier == "Fic"
    assert entries[1].format == "page"


def test_open_library_match_requires_exact_title_and_all_source_author_tokens():
    identity = BookIdentity("A Mind at Play (Shannon)", "Soni & Goodman")
    docs = [
        {
            "key": "/works/OL19710901W",
            "title": "A mind at play",
            "author_name": ["Jimmy Soni", "Rob Goodman"],
        },
        {
            "key": "/works/OL999W",
            "title": "A Mind at Play",
            "author_name": ["Someone Else"],
        },
        {
            "key": "/works/OL998W",
            "title": "Summary of A Mind at Play",
            "author_name": ["Jimmy Soni", "Rob Goodman"],
        },
    ]

    match = match_open_library_work(identity, docs)

    assert match.status == "matched"
    assert match.work == docs[0]
    assert match.reason == "exact_normalized_title_and_author_tokens"


def test_open_library_match_rejects_ambiguous_exact_works():
    identity = BookIdentity("The Last Days of Socrates", "Plato")
    docs = [
        {"key": "/works/OL1W", "title": identity.title,
         "author_name": ["Plato"]},
        {"key": "/works/OL2W", "title": identity.title,
         "author_name": ["Plato"]},
    ]

    match = match_open_library_work(identity, docs)

    assert match.status == "ambiguous"
    assert match.work is None
    assert match.candidate_work_ids == ("/works/OL1W", "/works/OL2W")


def test_open_library_metadata_keeps_work_level_values_separate_from_edition_fields():
    metadata = extract_open_library_metadata({
        "key": "/works/OL19710901W",
        "title": "A mind at play",
        "author_name": ["Jimmy Soni", "Rob Goodman"],
        "first_publish_year": 2017,
        "number_of_pages_median": 375,
        "language": ["eng"],
        "publisher": ["Simon & Schuster"],
        "isbn": ["9781476766706", "1476766703"],
        "subject": [
            "Mathematicians",
            "BIOGRAPHY & AUTOBIOGRAPHY / Science & Technology",
            "COMPUTERS / Information Theory",
        ],
    })

    assert metadata["open_library_work_id"] == "/works/OL19710901W"
    assert metadata["genres"] == ["Biography & Autobiography", "Computers"]
    assert metadata["page_count_median"] == 375
    assert metadata["first_publish_year"] == 2017
    assert metadata["languages"] == ["eng"]
    assert metadata["publishers"] == ["Simon & Schuster"]
    assert metadata["isbns"] == ["9781476766706", "1476766703"]
    assert "isbn" not in metadata
    assert "total_pages" not in metadata


def test_card_identity_uses_exact_retained_source_title_without_guessing():
    assert book_identity_from_card({
        "author": "Soni & Goodman",
        "appflowy_source_cells": {"Name": "A Mind at Play (Shannon)"},
    }) == BookIdentity("A Mind at Play (Shannon)", "Soni & Goodman")
    assert book_identity_from_card({
        "author": "Unknown", "appflowy_source_cells": {"Name": ""},
    }) is None


def test_import_merge_preserves_operator_divergence_and_records_conflict():
    current = {
        "genres": ["Operator classification"],
        "publishers": ["Prior source publisher"],
        "book_metadata_last_imported_fields": {
            "genres": ["Prior source genre"],
            "publishers": ["Prior source publisher"],
        },
    }
    merged = merge_imported_metadata(current, {
        "genres": ["New source genre"],
        "publishers": ["New source publisher"],
        "first_publish_year": 2017,
    })

    assert merged.fields["genres"] == ["Operator classification"]
    assert merged.fields["publishers"] == ["New source publisher"]
    assert merged.fields["first_publish_year"] == 2017
    assert merged.conflicts == {
        "genres": {
            "board_value": ["Operator classification"],
            "source_value": ["New source genre"],
            "last_imported_value": ["Prior source genre"],
        },
    }
